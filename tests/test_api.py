"""The FastAPI backend, called the way the React app calls it. The PDF reader and the LLM are
replaced by fakes, and contractor_profiles.json is replaced by a temporary copy, so nothing
real is read, written or paid for."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import api_server  # noqa: E402

PROFILES = [
    {"contractor_name": "Alpha Builders", "pec_category_held": "C-3",
     "min_contract_value_pkr": 1_000_000, "max_contract_value_pkr": 50_000_000,
     "max_acceptable_payment_cycle_days": 30, "company_address": "Plot 1", "_notes": "demo firm"},
    {"contractor_name": "Beta Co", "pec_category_held": "C-6"},
]
DOCX = "wordprocessingml"


@pytest.fixture
def profiles_file(tmp_path, monkeypatch):
    path = tmp_path / "contractor_profiles.json"
    path.write_text(json.dumps(PROFILES), encoding="utf-8")
    monkeypatch.setattr(api_server, "CONTRACTOR_FILE", path)
    return path


@pytest.fixture
def client(profiles_file):
    return TestClient(api_server.app)


@pytest.fixture
def pipeline(monkeypatch, make_tender):
    """Fakes for 'read the PDF' and 'ask the LLM'. Change state[...] inside a test."""
    state = {"text": "Some tender text", "llm_error": None, "read_error": None,
             "tender": make_tender(tender_id="T-API", title="API tender", contract_value_pkr=20_000_000)}

    def fake_read(path):
        if state["read_error"]:
            raise RuntimeError(state["read_error"])
        return state["text"]

    def fake_llm(text, tender_id, title, organization=None):
        if state["llm_error"]:
            raise RuntimeError(state["llm_error"])
        return state["tender"]

    monkeypatch.setattr(api_server, "extract_text_from_document", fake_read)
    monkeypatch.setattr(api_server, "extract_fields_with_llm", fake_llm)
    return state


def upload(client, name="Alpha Builders", filename="tender.pdf", content=b"%PDF-1.4 fake", title=""):
    return client.post("/api/decide", files={"file": (filename, content, "application/pdf")},
                       data={"contractor_name": name, "title": title})


def saved_profiles(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- contractors

def test_list_contractors(client):
    body = client.get("/api/contractors").json()
    assert [c["name"] for c in body] == ["Alpha Builders", "Beta Co"]
    assert body[0]["pec_category"] == "C-3"
    assert body[0]["mine"] is False
    assert "_notes" not in body[0]["profile"]


def test_new_firm_is_saved_and_marked_as_mine(client, profiles_file):
    r = client.post("/api/contractors", json={"original_name": None, "profile": {
        "contractor_name": "  Gamma Builders ", "pec_category_held": "C-4", "years_experience": 5,
        "max_contract_value_pkr": 20_000_000, "max_bid_security_pkr": None}})
    assert r.status_code == 200
    assert r.json()["name"] == "Gamma Builders"
    saved = saved_profiles(profiles_file)[-1]
    assert saved["contractor_name"] == "Gamma Builders"
    assert saved["_mine"] is True
    assert saved["pec_category_held"] == "C-4"
    gamma = [c for c in client.get("/api/contractors").json() if c["name"] == "Gamma Builders"][0]
    assert gamma["mine"] is True


def test_editing_keeps_fields_the_form_does_not_show(client, profiles_file):
    r = client.post("/api/contractors", json={"original_name": "Alpha Builders", "profile": {
        "contractor_name": "Alpha Builders", "pec_category_held": "C-3", "max_contract_value_pkr": 60_000_000}})
    assert r.status_code == 200
    alpha = saved_profiles(profiles_file)[0]
    assert alpha["max_contract_value_pkr"] == 60_000_000          # changed
    assert alpha["max_acceptable_payment_cycle_days"] == 30       # not in the request: kept
    assert alpha["_notes"] == "demo firm"                         # kept
    assert len(saved_profiles(profiles_file)) == 2                # edited in place, not duplicated


def test_renaming_a_firm(client, profiles_file):
    r = client.post("/api/contractors", json={"original_name": "Alpha Builders", "profile": {
        "contractor_name": "Alpha Builders Ltd", "pec_category_held": "C-3"}})
    assert r.status_code == 200
    names = [c["name"] for c in client.get("/api/contractors").json()]
    assert "Alpha Builders Ltd" in names
    assert "Alpha Builders" not in names
    assert saved_profiles(profiles_file)[0]["_notes"] == "demo firm"


def test_new_firm_cannot_reuse_a_name_in_any_letter_case(client):
    r = client.post("/api/contractors", json={"original_name": None, "profile": {
        "contractor_name": "alpha BUILDERS", "pec_category_held": "C-4"}})
    assert r.status_code == 409


def test_renaming_onto_another_firms_name_is_refused(client):
    r = client.post("/api/contractors", json={"original_name": "Alpha Builders", "profile": {
        "contractor_name": "Beta Co", "pec_category_held": "C-3"}})
    assert r.status_code == 409


@pytest.mark.parametrize("profile,fragment", [
    ({"contractor_name": "X", "pec_category_held": "C-3",
      "min_contract_value_pkr": 900_000_000, "max_contract_value_pkr": 1_000}, "smallest contract"),
    ({"contractor_name": "X", "pec_category_held": "C-3", "years_experience": -1}, "negative"),
    ({"contractor_name": "   ", "pec_category_held": "C-3"}, "firm's name"),
    ({"contractor_name": "X", "pec_category_held": "C-9"}, "pec_category_held"),
])
def test_invalid_criteria_are_refused_and_nothing_is_saved(client, profiles_file, profile, fragment):
    r = client.post("/api/contractors", json={"original_name": None, "profile": profile})
    assert r.status_code == 422
    assert fragment in r.json()["detail"]
    assert len(saved_profiles(profiles_file)) == 2


# ---------------------------------------------------------------- decide

def test_decide_returns_everything_the_ui_needs(client, pipeline):
    r = upload(client)
    assert r.status_code == 200
    d = r.json()
    for key in ("result_id", "decision", "criteria_checked", "criteria_total", "skipped_criteria",
                "low_confidence", "confidence_note", "deadline_warning", "text_truncated",
                "results", "extracted_fields", "tender_title", "contractor_name"):
        assert key in d
    assert d["decision"] == "Select"
    assert d["contractor_name"] == "Alpha Builders"
    assert d["results"][0]["criterion"] == "contract_value"
    assert d["extracted_fields"]["tender_id"] == "T-API"
    assert d["criteria_checked"] == len(d["results"])


def test_decide_says_insufficient_data_when_nothing_could_be_compared(client, pipeline, make_tender):
    pipeline["tender"] = make_tender(tender_id="T-EMPTY", title="Empty tender")
    d = upload(client).json()
    assert d["decision"] == "Insufficient data"
    assert d["results"] == []
    assert d["criteria_checked"] == 0
    assert d["low_confidence"] is True
    assert "NO VERDICT" in d["confidence_note"]


def test_a_draft_can_still_be_made_when_there_was_no_verdict(client, pipeline, make_tender):
    pipeline["tender"] = make_tender(tender_id="T-EMPTY", title="Empty tender")
    result_id = upload(client).json()["result_id"]
    r = client.post("/api/generate-bid", json={"result_id": result_id})      # no 'force' needed
    assert r.status_code == 200
    assert r.content[:2] == b"PK"


def test_decide_rejects_an_oversized_contract(client, pipeline, make_tender):
    pipeline["tender"] = make_tender(tender_id="T-BIG", title="Big", contract_value_pkr=90_000_000)
    d = upload(client).json()
    assert d["decision"] == "Reject"
    assert "exceeds" in d["results"][0]["reason"]


def test_decide_flags_text_that_will_be_cut(client, pipeline):
    pipeline["text"] = "x" * 60_001
    assert upload(client).json()["text_truncated"] is True
    pipeline["text"] = "x" * 60_000
    assert upload(client).json()["text_truncated"] is False


def test_decide_unknown_contractor(client, pipeline):
    assert upload(client, name="Nobody Ltd").status_code == 404


def test_decide_wrong_file_type(client, pipeline):
    assert upload(client, filename="notes.exe").status_code == 415


def test_decide_empty_file(client, pipeline):
    assert upload(client, content=b"").status_code == 422


def test_decide_file_too_large(client, pipeline, monkeypatch):
    monkeypatch.setattr(api_server, "MAX_UPLOAD_MB", 0)
    assert upload(client).status_code == 413


def test_decide_unreadable_file(client, pipeline):
    pipeline["read_error"] = "corrupt pdf"
    r = upload(client)
    assert r.status_code == 422
    assert "corrupt pdf" in r.json()["detail"]


def test_decide_file_with_no_text(client, pipeline):
    pipeline["text"] = "   "
    assert upload(client).status_code == 422


def test_decide_reports_extraction_failure(client, pipeline):
    pipeline["llm_error"] = "Connection error"
    r = upload(client)
    assert r.status_code == 500
    assert "Extraction failed" in r.json()["detail"]


# ---------------------------------------------------------------- generate-bid

def test_generate_bid_returns_a_word_file(client, pipeline):
    result_id = upload(client).json()["result_id"]
    r = client.post("/api/generate-bid", json={"result_id": result_id})
    assert r.status_code == 200
    assert DOCX in r.headers["content-type"]
    assert r.content[:2] == b"PK"                       # a .docx is a zip file
    assert "Bid_Draft_T-API.docx" in r.headers["content-disposition"]


def test_generate_bid_for_a_reject_needs_force(client, pipeline, make_tender):
    pipeline["tender"] = make_tender(tender_id="T-BIG", title="Big", contract_value_pkr=90_000_000)
    result_id = upload(client).json()["result_id"]
    assert client.post("/api/generate-bid", json={"result_id": result_id}).status_code == 409
    forced = client.post("/api/generate-bid", json={"result_id": result_id, "force": True})
    assert forced.status_code == 200
    assert DOCX in forced.headers["content-type"]


def test_generate_bid_unknown_result(client):
    r = client.post("/api/generate-bid", json={"result_id": "nope", "force": True})
    assert r.status_code == 404
    assert "Analyse the tender again" in r.json()["detail"]
