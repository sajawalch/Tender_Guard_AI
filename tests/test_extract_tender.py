"""Extraction post-processing, tested without any real LLM: a fake `openai` module
hands back canned JSON, so we test OUR code (cleaning, normalising, the rules)."""

import json
import sys
import types

import pytest

from schema import PECCategory
from extract_tender import (extract_fields_with_llm, extract_text_from_document,
                            sanitize_amounts, verify_requirements)


@pytest.fixture
def llm(monkeypatch):
    """Replaces the openai package. There are two model calls per tender:
    step 1 (the fields) answers llm['payload'], step 2 (the checklist lines) answers llm['requirements'].
    llm['kwargs'] / llm['requirement_kwargs'] record what our code sent in each step."""
    import extract_tender
    state = {"payload": {}, "requirements": {"requirements": []}, "requirements_error": None,
             "kwargs": None, "requirement_kwargs": None}

    def create(**kwargs):
        if kwargs["messages"][0]["content"] == extract_tender.REQUIREMENTS_SYSTEM_PROMPT:
            state["requirement_kwargs"] = kwargs
            if state["requirements_error"]:
                raise RuntimeError(state["requirements_error"])
            payload = state["requirements"]
        else:
            state["kwargs"] = kwargs
            payload = state["payload"]
        message = types.SimpleNamespace(content=json.dumps(payload))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    fake = types.ModuleType("openai")
    fake.OpenAI = lambda **kw: types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", fake)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    return state


def run(text="tender text", tender_id="T1", title="My tender", **kw):
    return extract_fields_with_llm(text, tender_id=tender_id, title=title, **kw)


# ---------------------------------------------------------------- sanitize_amounts

@pytest.mark.parametrize("bad", [0, 1, 64.883, 999, 999.99])
def test_impossible_amounts_become_none(bad):
    out = sanitize_amounts({"contract_value_pkr": bad, "bid_security_amount_pkr": bad})
    assert out["contract_value_pkr"] is None
    assert out["bid_security_amount_pkr"] is None


@pytest.mark.parametrize("good", [1000, 25_831_313, 1_291_565.65])
def test_real_amounts_are_kept(good):
    out = sanitize_amounts({"contract_value_pkr": good, "bid_security_amount_pkr": good})
    assert out["contract_value_pkr"] == good
    assert out["bid_security_amount_pkr"] == good


def test_sanitize_leaves_other_fields_and_missing_values_alone():
    out = sanitize_amounts({"completion_period_days": 30, "advance_payment_percent": 0, "contract_value_pkr": None})
    assert out == {"completion_period_days": 30, "advance_payment_percent": 0, "contract_value_pkr": None}


def test_sanitize_ignores_non_numbers():
    out = sanitize_amounts({"contract_value_pkr": "twenty million", "bid_security_amount_pkr": True})
    assert out["contract_value_pkr"] == "twenty million"
    assert out["bid_security_amount_pkr"] is True


# ---------------------------------------------------------------- PEC category normalising

@pytest.mark.parametrize("written,expected", [
    ("C-05", PECCategory.C5), ("C-5", PECCategory.C5), ("c-01", PECCategory.C1),
    ("C-06", PECCategory.C6), ("C-A", PECCategory.C_A), (" C-04 ", PECCategory.C4),
])
def test_zero_padded_pec_categories_are_normalised(llm, written, expected):
    llm["payload"] = {"pec_category_required": written}
    assert run().pec_category_required == expected


def test_unknown_pec_category_gives_a_clear_error(llm):
    llm["payload"] = {"pec_category_required": "C-9"}
    with pytest.raises(RuntimeError, match="expected format"):
        run()


# ---------------------------------------------------------------- literal extraction rules

def test_fields_the_document_does_not_state_stay_none(llm):
    llm["payload"] = {"contract_value_pkr": 25_000_000}
    t = run()
    assert t.bid_security_amount_pkr is None
    assert t.advance_payment_percent is None
    assert t.pec_category_required is None


def test_bid_security_percent_is_never_turned_into_an_amount(llm):
    llm["payload"] = {"bid_security_percent": 5, "bid_security_amount_pkr": None, "contract_value_pkr": 20_000_000}
    t = run()
    assert t.bid_security_percent == 5
    assert t.bid_security_amount_pkr is None


def test_no_advance_payment_stays_zero(llm):
    llm["payload"] = {"advance_payment_percent": 0}
    assert run().advance_payment_percent == 0


def test_impossible_amount_is_dropped_inside_the_pipeline(llm):
    llm["payload"] = {"contract_value_pkr": 64.883, "bid_security_amount_pkr": 1_291_566}
    t = run()
    assert t.contract_value_pkr is None
    assert t.bid_security_amount_pkr == 1_291_566


def test_required_documents_are_trimmed_and_blanks_dropped(llm):
    llm["payload"] = {"required_documents": ["  Income tax returns  ", "", "   ", "Audited accounts"]}
    assert run().required_documents == ["Income tax returns", "Audited accounts"]


def test_required_documents_that_is_not_a_list_becomes_empty(llm):
    llm["payload"] = {"required_documents": "Income tax returns"}
    assert run().required_documents == []


# ---------------------------------------------------------------- title / organization rules

def test_title_from_caller_wins(llm):
    llm["payload"] = {"project_title": "Title the model found"}
    assert run(title="My tender").title == "My tender"


@pytest.mark.parametrize("weak_title", ["TS0000016176E.pdf", ""])
def test_model_title_is_used_when_caller_title_is_just_a_file_name(llm, weak_title):
    llm["payload"] = {"project_title": "Construction of 6 flats"}
    assert run(title=weak_title).title == "Construction of 6 flats"


def test_organization_from_caller_wins_otherwise_model_value_is_used(llm):
    llm["payload"] = {"organization": "FESCO"}
    assert run().organization == "FESCO"
    assert run(organization="PPRA").organization == "PPRA"


# ---------------------------------------------------------------- what we send to the model

def test_request_is_deterministic_json_and_names_the_tender(llm):
    run(title="Khurrianwala flats")
    sent = llm["kwargs"]
    assert sent["temperature"] == 0
    assert sent["response_format"] == {"type": "json_object"}
    user_message = sent["messages"][1]["content"]
    assert 'THIS SPECIFIC TENDER: "Khurrianwala flats"' in user_message


def test_text_beyond_60000_characters_is_currently_cut(llm):
    """KNOWN LIMIT, documented on purpose: clauses after 60,000 characters never reach the model.
    When chunked reading is added, change this test."""
    run(text="A" * 60_000 + "TAIL_MARKER")
    user_message = llm["kwargs"]["messages"][1]["content"]
    assert "TAIL_MARKER" not in user_message
    assert "A" * 60_000 in user_message


def test_unknown_provider_is_refused(llm, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "somebody-else")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        run()


# ---------------------------------------------------------------- reading files

def test_text_file_is_read(tmp_path):
    f = tmp_path / "tender.txt"
    f.write_text("Bid security: PKR 1,000,000", encoding="utf-8")
    assert "Bid security" in extract_text_from_document(str(f))


def test_missing_file_gives_a_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Tender file not found"):
        extract_text_from_document(str(tmp_path / "nope.pdf"))


# ---------------------------------------------------------------- step 2: the requirements checklist
# A made-up notice that contains the clauses the checklist must capture.

NOTICE = (
    "2. This Invitation for Bids is open to all Bidders meeting the following criteria:- "
    "h) The bidder should have an Average Annual Turnover half time of the amount mentioned against this work "
    "during last three (03) years certified from audited financial statement.\n"
    "j) All safety instructions narrated in NEPRA Safety Code must be adopted in true letter and spirit.\n"
    "13  Construction of 06 No. Cat-IV Flats  25831313.00  1291566.00  12.915  210 Days  C-05\n"
    "5. All bids must be accompanied by a Bids Security in favor of Executive Engineer Civil Works Division-II "
    "FESCO Faisalabad of any scheduled bank of Pakistan and shall be valid 28 days beyond bid validity. "
    "The bid shall be valid for 140-Days.\n"
    "a) Bids must be submitted through E-PADS Version 2.0 on 03.11.2026 up-to 11:30 AM\n"
    "PEC certificate renewed for the year 2026-27 must be provided.\n"
)

TURNOVER = {
    "text": "Average annual turnover of 12.915 (figure stated against this work in the notice; unit not stated) "
            "for the last three (03) years, certified from audited financial statement",
    "evidence": "The bidder should have an Average Annual Turnover half time of the amount mentioned against "
                "this work during last three (03) years certified from audited financial statement.",
}
NEPRA = {"text": "Adopt all safety instructions narrated in the NEPRA Safety Code",
         "evidence": "All safety instructions narrated in NEPRA Safety Code must be adopted in true letter and spirit."}
CDR = {"text": "Bid security in favor of Executive Engineer Civil Works Division-II FESCO Faisalabad, from any "
               "scheduled bank of Pakistan, valid 28 days beyond bid validity (bid valid 140 days)",
       "evidence": "Bids Security in favor of Executive Engineer Civil Works Division-II FESCO Faisalabad of any "
                   "scheduled bank of Pakistan and shall be valid 28 days beyond bid validity."}
EPADS = {"text": "Submit the bid through E-PADS Version 2.0 by 11:30 AM on 03.11.2026",
         "evidence": "Bids must be submitted through E-PADS Version 2.0 on 03.11.2026 up-to 11:30 AM"}


def test_requirement_lines_keep_the_notices_own_numbers_and_names(llm):
    llm["requirements"] = {"requirements": [TURNOVER, NEPRA, CDR, EPADS]}
    t = run(text=NOTICE)
    assert len(t.requirement_items) == 4
    assert any("12.915" in i and "unit not stated" in i for i in t.requirement_items)
    assert any("NEPRA Safety Code" in i for i in t.requirement_items)
    assert any("28 days beyond bid validity" in i for i in t.requirement_items)
    assert any("E-PADS Version 2.0" in i for i in t.requirement_items)


def test_each_kept_line_stores_its_evidence_quote_for_the_user_to_check(llm):
    llm["requirements"] = {"requirements": [NEPRA]}
    t = run(text=NOTICE)
    assert t.source_text_snippets["requirement_items[0]"] == NEPRA["evidence"]


def test_a_line_whose_quote_is_not_in_the_document_is_dropped(llm):
    # no numbers in it, so only the evidence check can catch this one
    invented = {"text": "Hold a quality management certificate",
                "evidence": "The bidder must hold a valid quality management certificate."}
    llm["requirements"] = {"requirements": [NEPRA, invented]}
    assert run(text=NOTICE).requirement_items == [NEPRA["text"]]


def test_a_calculated_number_never_reaches_the_checklist(llm):
    calculated = {"text": "Bid security valid for 168 days", "evidence": CDR["evidence"]}
    llm["requirements"] = {"requirements": [calculated]}
    assert run(text=NOTICE).requirement_items == []        # 140 + 28 = 168 is not in the notice


def test_a_unit_converted_figure_is_dropped(llm):
    converted = {"text": "Average annual turnover of 12,915,000", "evidence": TURNOVER["evidence"]}
    llm["requirements"] = {"requirements": [converted]}
    assert run(text=NOTICE).requirement_items == []


def test_a_failure_in_step_2_does_not_break_the_extraction(llm):
    llm["payload"] = {"contract_value_pkr": 25_831_313}
    llm["requirements_error"] = "model busy"
    t = run(text=NOTICE)
    assert t.contract_value_pkr == 25_831_313
    assert t.requirement_items == []


def test_step_2_is_deterministic_and_names_the_tender(llm):
    llm["requirements"] = {"requirements": [NEPRA]}
    run(text=NOTICE, title="Khurrianwala flats")
    sent = llm["requirement_kwargs"]
    assert sent["temperature"] == 0
    assert sent["response_format"] == {"type": "json_object"}
    assert 'THIS SPECIFIC TENDER: "Khurrianwala flats"' in sent["messages"][1]["content"]


@pytest.mark.parametrize("answer", [{"requirements": "not a list"}, ["not", "a", "dict"], {}])
def test_unusable_step_2_answers_give_an_empty_checklist(llm, answer):
    llm["requirements"] = answer
    assert run(text=NOTICE).requirement_items == []


def test_verify_requirements_drops_bad_entries_and_duplicates():
    items = [NEPRA, NEPRA, "just a string", {"text": "x", "evidence": NEPRA["evidence"]},
             {"text": "Short evidence line", "evidence": "too short"}]
    kept, dropped = verify_requirements(items, NOTICE)
    assert [k["text"] for k in kept] == [NEPRA["text"]]
    assert dropped == 4


def test_quote_matching_ignores_spacing_case_and_punctuation():
    reflowed = {"text": "Adopt NEPRA safety rules",
                "evidence": "ALL SAFETY  instructions narrated in\nNEPRA Safety Code must be adopted in true letter and spirit"}
    kept, dropped = verify_requirements([reflowed], NOTICE)
    assert len(kept) == 1 and dropped == 0