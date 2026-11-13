"""The draft bid .docx: checklist (each requirement once), cover page, blank date, declaration note."""

from datetime import date, datetime, timedelta

import pytest
from docx import Document

from generate_bid_document import (_same_requirement, build_document_checklist,
                                   format_closing_date, generate_bid_document)

DATE_PLACEHOLDER = "Date: [TO BE FILLED ON THE DAY OF SUBMISSION]"


@pytest.fixture
def khurrianwala(make_tender):
    """Modelled on tender TS0000016176E, including the requirement written twice."""
    return make_tender(
        tender_id="TS0000016176E",
        title="Construction of 06 No. Cat-IV Flats at 132KV Grid Station Khurrianwala",
        organization="FESCO", addressee="Executive Engineer Civil Works Division-II FESCO Faisalabad",
        contract_value_pkr=25_831_313, bid_security_amount_pkr=1_291_566,
        pec_category_required="C-5", pec_specialization_code="CE-10",
        requires_active_taxpayer_status=True, min_similar_contracts=2, similar_contracts_lookback_years=10,
        completion_period_days=210, bid_validity_days=140,
        required_documents=[
            "Income Tax Returns for last three (03) years",
            "Successful completion certificate for at least two contracts of same nature within ten years",
            "Consolidated value of contracts must be more than 40% of the estimated / B.O.Q Cost",
            "Original CDR (Bid Security) in favor of Executive Engineer, valid 28 days beyond bid validity",
            "PEC certificate renewed for the year 2026-27",
            "Identity Card of Contractor",
        ],
        requirement_items=[
            "PEC certificate renewed for the year 2026-27 with category having specialization code as mentioned against above",
            "The bidder shall be in the Active Taxpayer List (ATL)",
            "Income Tax Returns for the last three (03) years",
            "Registration for sales tax with Punjab Revenue Authority (PRA)",
            "Identity Card of Contractor / Managing Partner / Director of the firm",
            "At least two contracts of same nature with successful completion certificate as main contractor within ten years",
            "Consolidated value of these contracts must be more than 40% of the estimated / B.O.Q Cost",
            "Average annual turnover of 12.915 (figure stated against this work in the notice; unit not stated) "
            "for the last three (03) years, certified from audited financial statement",
            "Cash or cash equivalents to 10% of contract value and current contract commitment, shown by bank statements",
            "Adopt all safety instructions narrated in the NEPRA Safety Code",
            "Submit the bid through E-PADS Version 2.0 by 11:30 AM on 03.11.2026",
            "Bid security in favor of Executive Engineer Civil Works Division-II FESCO Faisalabad of any scheduled "
            "bank of Pakistan, valid 28 days beyond bid validity",
            "Provide Original CDR (Bid Security) in favor of Executive Engineer Civil Works Division-II FESCO "
            "Faisalabad to the opening committee on 03-11-2026 up to 11:30 AM",
        ])


def paragraphs(path):
    return [p.text for p in Document(str(path)).paragraphs]


# ---------------------------------------------------------------- checklist

def test_similar_contracts_requirement_appears_once(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert len([i for i in items if "completion certificate" in i.lower()]) == 1


def test_tender_specific_requirements_are_kept(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert any("40%" in i for i in items)
    assert any("Income Tax Returns" in i for i in items)


def test_notice_wording_for_the_cdr_replaces_the_generic_line(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert any("28 days" in i and "Executive Engineer" in i for i in items)
    assert any("Original CDR" in i for i in items)
    assert not any("as specified" in i for i in items)


def test_generic_bid_security_line_is_used_when_the_notice_gives_no_detail(make_tender):
    items = build_document_checklist(make_tender(bid_security_amount_pkr=500_000))
    assert any("Call Deposit Receipt" in i for i in items)


def test_pec_and_id_items_from_the_notice_are_not_repeated(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert len([i for i in items if "PEC" in i]) == 1
    assert len([i for i in items if "CNIC" in i or "Identity Card" in i]) == 1


def test_checklist_has_no_duplicates_and_always_ends_with_the_basics(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert len({i.lower() for i in items}) == len(items)
    assert items[-3:] == ["Company registration / incorporation certificate",
                          "National Tax Number (NTN) certificate",
                          "CNIC copy of authorized signatory"]


def test_checklist_items_start_with_a_capital_letter(make_tender):
    items = build_document_checklist(make_tender(required_documents=["audited financial statements"]))
    assert "Audited financial statements" in items


def test_experience_requirement_is_not_listed_twice(make_tender):
    items = build_document_checklist(make_tender(
        min_years_experience_required=5, required_documents=["Proof of 5 years of experience"]))
    assert len([i for i in items if "years" in i.lower() and "experience" in i.lower()]) == 1


# ---------------------------------------------------------------- the tender's own details (the five reported gaps)

def test_turnover_amount_is_in_the_checklist_without_inventing_a_unit(khurrianwala):
    line = next(i for i in build_document_checklist(khurrianwala) if "turnover" in i.lower())
    assert "12.915" in line
    assert "unit not stated" in line
    assert "million" not in line.lower()
    assert "half time" not in line.lower()


def test_cdr_says_who_it_is_payable_to_and_how_long_it_stays_valid(khurrianwala):
    items = build_document_checklist(khurrianwala)
    security = next(i for i in items if "28 days beyond bid validity" in i)
    assert "Executive Engineer Civil Works Division-II FESCO Faisalabad" in security
    assert not any(i.strip().endswith("as specified") for i in items)
    assert any("opening committee" in i for i in items)          # the second, different CDR statement
    assert "168" not in "\n".join(items)                         # 140 + 28 is never calculated for the bidder


def test_nepra_safety_code_requirement_is_listed(khurrianwala):
    assert any("NEPRA Safety Code" in i for i in build_document_checklist(khurrianwala))


def test_electronic_submission_through_e_pads_is_listed(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert any("E-PADS Version 2.0" in i and "03.11.2026" in i for i in items)


def test_pec_line_carries_the_notices_renewal_year_not_relevant_year(khurrianwala):
    pec = [i for i in build_document_checklist(khurrianwala) if "PEC" in i]
    assert len(pec) == 1
    assert "2026-27" in pec[0]
    assert "relevant year" not in pec[0]
    assert "Category C-5" in pec[0] and "CE-10" in pec[0]


def test_pec_line_keeps_relevant_year_wording_only_when_the_notice_gives_no_year(make_tender):
    pec = [i for i in build_document_checklist(make_tender(pec_category_required="C-4")) if "PEC" in i]
    assert len(pec) == 1 and "relevant year" in pec[0]


def test_pec_requirement_is_still_listed_when_no_category_was_extracted(make_tender):
    t = make_tender(requirement_items=["PEC certificate renewed for the year 2026-27"])
    assert any("2026-27" in i for i in build_document_checklist(t))


def test_the_same_requirement_from_two_lists_is_listed_once(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert len([i for i in items if "income tax returns" in i.lower()]) == 1
    assert len([i for i in items if "40%" in i]) == 1
    assert len([i for i in items if "active taxpayer" in i.lower()]) == 1
    assert len([i for i in items if "cnic" in i.lower() or "identity card" in i.lower()]) == 1
    assert len({i.lower() for i in items}) == len(items)


def test_other_tender_conditions_are_kept(khurrianwala):
    items = build_document_checklist(khurrianwala)
    assert any("Punjab Revenue Authority" in i for i in items)
    assert any("10% of contract value" in i for i in items)


def test_similarity_rule_merges_rewordings_but_not_different_requirements():
    assert _same_requirement("Income Tax Returns for last three (03) years",
                             "The bidder will provide the Income Tax Returns for last three (03) years")
    assert not _same_requirement("Consolidated value of contracts must be more than 40% of the BOQ cost",
                                 "Completion certificates for at least two contracts of same nature")
    assert not _same_requirement("National Tax Number (NTN) certificate",
                                 "Income Tax Returns for the last three years")


# ---------------------------------------------------------------- date formatting

@pytest.mark.parametrize("raw,expected", [
    ("2026-11-03 11:30", "03 November 2026, 11:30 AM"),
    ("2026-11-03 15:05", "03 November 2026, 03:05 PM"),
    ("2026-11-03", "03 November 2026"),
    ("3rd November", "3rd November"),        # unknown format comes back unchanged, never guessed
    (None, None), ("", None),
])
def test_format_closing_date(raw, expected):
    assert format_closing_date(raw) == expected


# ---------------------------------------------------------------- the document itself

@pytest.fixture
def built(tmp_path, khurrianwala, make_tender, make_criteria):
    """A draft for a tender whose deadline passed yesterday."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    tender = make_tender(**{**khurrianwala.model_dump(), "bid_closing_date": yesterday})
    contractor = make_criteria(contractor_name="Sindh Horizon Builders", company_address="Plot 45, Hyderabad",
                               contact_person="Faisal Memon", contact_designation="Managing Partner",
                               phone="+92-22-0000107", ntn_number="0000107-7")
    path = tmp_path / "bid.docx"
    generate_bid_document(tender, contractor, str(path),
                          failed_checks=["Contract value PKR 90,000,000 exceeds your maximum"],
                          confidence_note="5 of 8 criteria checked")
    return path


def test_first_page_is_a_cover_page_for_the_contractor_only(built):
    text = paragraphs(built)
    assert text[0] == "DRAFT \u2014 NOT READY TO SUBMIT"
    assert any(p.startswith("Deadline.") and "already passed" in p for p in text)
    assert any(p.startswith("How much was checked.") for p in text)
    assert any(p.startswith("Issues flagged by the automated check.") for p in text)
    assert any("exceeds your maximum" in p for p in text)
    assert 'w:type="page"' in Document(str(built)).element.xml


def test_warnings_come_before_the_letter_not_inside_it(built):
    text = paragraphs(built)
    letter_start = text.index("Sindh Horizon Builders")
    assert text.index(next(p for p in text if p.startswith("Deadline."))) < letter_start
    assert not any(p.startswith(("Deadline.", "DEADLINE")) for p in text[letter_start:])


def test_letter_date_is_left_blank(built):
    text = paragraphs(built)
    assert DATE_PLACEHOLDER in text
    assert date.today().strftime("%d %B %Y") not in "\n".join(text)


def test_declaration_carries_a_drafting_note_and_signature_block(built):
    text = paragraphs(built)
    note = next(p for p in text if p.startswith("[Drafting note"))
    assert "delete before submitting" in note
    assert "Authorized Signatory: " in "\n".join(text)
    assert "Name: Faisal Memon" in text
    assert "Designation: Managing Partner" in text


def test_price_is_left_for_the_bidder(built):
    doc = Document(str(built))
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert "[TO BE FILLED]" in cells
    assert any("AMOUNT TO BE INSERTED" in p for p in paragraphs(built))


def test_cover_page_without_any_warnings_still_has_the_todo_list(tmp_path, make_tender, make_criteria):
    path = tmp_path / "clean.docx"
    generate_bid_document(make_tender(), make_criteria(), str(path))
    text = paragraphs(path)
    assert "Before you submit" in text
    assert not any(p.startswith(("Issues flagged", "Deadline.", "How much was checked")) for p in text)