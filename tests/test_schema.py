"""Schema rules: deadline warnings, PEC ranking, required fields, defaults."""

from datetime import date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from schema import (ContractorCriteria, CriterionResult, MatchDecision, PECCategory,
                    PEC_CATEGORY_RANK, TenderTerms)


def tender_closing_in(make_tender, days, with_time=False):
    day = date.today() + timedelta(days=days)
    text = datetime.combine(day, time(11, 0)).strftime("%Y-%m-%d %H:%M") if with_time else day.strftime("%Y-%m-%d")
    return make_tender(bid_closing_date=text)


# ---------------------------------------------------------------- deadline

@pytest.mark.parametrize("days", [-3, 0, 1, 7, 30])
def test_days_until_deadline_counts_whole_days(make_tender, days):
    assert tender_closing_in(make_tender, days).days_until_deadline == days


def test_days_until_deadline_ignores_the_time_of_day(make_tender):
    assert tender_closing_in(make_tender, 10, with_time=True).days_until_deadline == 10


def test_no_warning_when_deadline_is_more_than_a_week_away(make_tender):
    assert tender_closing_in(make_tender, 8).deadline_warning is None


def test_warning_seven_days_before(make_tender):
    assert "Bids close in 7 days" in tender_closing_in(make_tender, 7).deadline_warning


def test_warning_uses_singular_for_one_day(make_tender):
    warning = tender_closing_in(make_tender, 1).deadline_warning
    assert "1 day (" in warning
    assert "1 days" not in warning


def test_warning_on_the_closing_day(make_tender):
    assert "TODAY" in tender_closing_in(make_tender, 0).deadline_warning


def test_warning_after_the_deadline(make_tender):
    assert "already passed" in tender_closing_in(make_tender, -1).deadline_warning


def test_no_deadline_means_no_warning(make_tender):
    t = make_tender()
    assert t.days_until_deadline is None
    assert t.deadline_warning is None


@pytest.mark.parametrize("raw", ["03/11/2026", "next Tuesday", "2026-13-45", ""])
def test_unrecognised_deadline_format_gives_no_warning(make_tender, raw):
    t = make_tender(bid_closing_date=raw)
    assert t.days_until_deadline is None
    assert t.deadline_warning is None


def test_deadline_with_surrounding_spaces_is_still_read(make_tender):
    day = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
    assert make_tender(bid_closing_date=f"  {day} ").days_until_deadline == 2


# ---------------------------------------------------------------- PEC ranking

def test_every_pec_category_has_a_rank():
    assert set(PEC_CATEGORY_RANK) == set(PECCategory)


def test_pec_ranks_rise_from_c6_to_c_a():
    order = [PECCategory.C6, PECCategory.C5, PECCategory.C4, PECCategory.C3,
             PECCategory.C2, PECCategory.C1, PECCategory.C_A]
    ranks = [PEC_CATEGORY_RANK[c] for c in order]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


# ---------------------------------------------------------------- validation and defaults

def test_tender_needs_id_and_title():
    with pytest.raises(ValidationError):
        TenderTerms(tender_id="only-an-id")


def test_contractor_rejects_unknown_pec_category():
    with pytest.raises(ValidationError):
        ContractorCriteria(contractor_name="Firm", pec_category_held="C-9")


def test_contractor_defaults():
    c = ContractorCriteria(contractor_name="Firm", pec_category_held="C-3")
    assert c.is_active_taxpayer is True
    assert c.years_experience == 0
    assert c.max_bid_security_pkr is None          # no limit unless the contractor sets one


def test_tender_fields_default_to_not_stated(make_tender):
    t = make_tender()
    assert t.contract_value_pkr is None
    assert t.bid_security_amount_pkr is None
    assert t.advance_payment_percent is None
    assert t.requires_active_taxpayer_status is False


def test_list_defaults_are_not_shared_between_tenders(make_tender):
    a, b = make_tender(), make_tender()
    assert a.required_documents == []
    assert a.required_documents is not b.required_documents
    assert a.requirement_items == []
    assert a.requirement_items is not b.requirement_items


# ---------------------------------------------------------------- MatchDecision helpers

def _result(name, passed):
    return CriterionResult(criterion_name=name, passed=passed, reason=f"{name} {'ok' if passed else 'bad'}")


def test_failing_reasons_lists_only_failures():
    d = MatchDecision(tender_id="T", contractor_name="C", decision="Reject",
                      results=[_result("a", True), _result("b", False)], total_criteria=8)
    assert d.failing_reasons == ["b bad"]
    assert d.criteria_checked == 2


def test_confidence_note_names_the_skipped_checks():
    d = MatchDecision(tender_id="T", contractor_name="C", decision="Select",
                      results=[_result("a", True)] * 5, total_criteria=8,
                      skipped_criteria=["liquidated_damages", "advance_payment", "experience"])
    assert d.confidence_note.startswith("5 of 8 criteria checked")
    assert "liquidated damages, advance payment, experience" in d.confidence_note


def test_zero_total_criteria_is_never_low_confidence():
    d = MatchDecision(tender_id="T", contractor_name="C", decision="Select", results=[], total_criteria=0)
    assert not d.is_low_confidence