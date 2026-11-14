"""bid_service: the in-memory result cache and the .docx it builds for the web app."""

import re

import pytest
from docx import Document

import bid_service
from matching_engine import match


@pytest.fixture
def decided(make_tender, make_criteria):
    """decided(contract_value) -> (tender, contractor, decision). 20M is a Select, 90M a Reject."""
    def _decide(contract_value, tender_id="TS-1"):
        tender = make_tender(tender_id=tender_id, title="Road works", contract_value_pkr=contract_value)
        contractor = make_criteria(contractor_name="Alpha Builders", max_contract_value_pkr=50_000_000)
        return tender, contractor, match(tender, contractor)
    return _decide


def doc_text(path):
    return "\n".join(p.text for p in Document(path).paragraphs)


def test_store_result_returns_a_unique_id(decided):
    first = bid_service.store_result(*decided(20_000_000))
    second = bid_service.store_result(*decided(20_000_000))
    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_select_builds_a_docx_for_the_firm(decided):
    result_id = bid_service.store_result(*decided(20_000_000))
    path, name = bid_service.build_bid_file(result_id)
    assert name == "Bid_Draft_TS-1.docx"
    assert "Alpha Builders" in doc_text(path)


def test_reject_needs_confirmation(decided):
    result_id = bid_service.store_result(*decided(90_000_000))
    with pytest.raises(bid_service.BidNotAllowed):
        bid_service.build_bid_file(result_id)
    with pytest.raises(bid_service.BidNotAllowed):
        bid_service.build_bid_file(result_id, force=False)


def test_forced_reject_lists_the_failed_check_on_the_cover_page(decided):
    result_id = bid_service.store_result(*decided(90_000_000))
    path, _ = bid_service.build_bid_file(result_id, force=True)
    text = doc_text(path)
    assert "Issues flagged by the automated check." in text
    assert "exceeds your maximum" in text


def test_unknown_result_id(decided):
    with pytest.raises(bid_service.ResultNotFound):
        bid_service.build_bid_file("does-not-exist")


def test_old_results_are_dropped_after_the_cache_limit(decided):
    ids = [bid_service.store_result(*decided(20_000_000, tender_id=f"T-{i}"))
           for i in range(bid_service.MAX_CACHED_RESULTS + 5)]
    assert len(bid_service._cache) == bid_service.MAX_CACHED_RESULTS
    with pytest.raises(bid_service.ResultNotFound):
        bid_service.build_bid_file(ids[0])
    assert bid_service.build_bid_file(ids[-1])[0].endswith(".docx")


def test_download_name_is_safe_for_any_tender_id(decided):
    result_id = bid_service.store_result(*decided(20_000_000, tender_id="TS/001 ??"))
    _, name = bid_service.build_bid_file(result_id)
    assert name.endswith(".docx")
    assert not any(ch in name for ch in '/\\? ')


def test_a_draft_after_insufficient_data_needs_no_confirmation_but_says_nothing_was_checked(make_tender, make_criteria):
    tender = make_tender(tender_id="T-EMPTY", title="Empty tender")
    contractor = make_criteria(contractor_name="Alpha Builders")
    decision = match(tender, contractor)
    assert decision.decision == "Insufficient data"
    result_id = bid_service.store_result(tender, contractor, decision)
    path, _ = bid_service.build_bid_file(result_id)           # no force needed
    text = doc_text(path)
    assert "0 of 8 criteria checked" in text
    assert "NO VERDICT" in text