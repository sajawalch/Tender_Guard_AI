"""The matching engine is the heart of the project: deterministic rules, no LLM.
Rule under test: a check only runs when BOTH sides have a value, otherwise it is skipped."""

from pathlib import Path

import pytest

from schema import PECCategory, PEC_CATEGORY_RANK
from matching_engine import (
    ALL_CHECKS, match,
    check_contract_value, check_pec_category, check_bid_security,
    check_liquidated_damages, check_advance_payment, check_active_taxpayer,
    check_experience, check_completion_period,
)


# ---------------------------------------------------------------- contract value

def test_contract_value_inside_range_passes(make_tender, make_criteria):
    r = check_contract_value(make_tender(contract_value_pkr=20_000_000),
                             make_criteria(min_contract_value_pkr=5_000_000, max_contract_value_pkr=50_000_000))
    assert r.passed
    assert "within" in r.reason


def test_contract_value_above_maximum_fails(make_tender, make_criteria):
    r = check_contract_value(make_tender(contract_value_pkr=90_000_000),
                             make_criteria(max_contract_value_pkr=50_000_000))
    assert not r.passed
    assert "exceeds" in r.reason


def test_contract_value_below_minimum_fails(make_tender, make_criteria):
    r = check_contract_value(make_tender(contract_value_pkr=1_000_000),
                             make_criteria(min_contract_value_pkr=5_000_000))
    assert not r.passed
    assert "below" in r.reason


@pytest.mark.parametrize("value", [5_000_000, 50_000_000])
def test_contract_value_exactly_on_a_limit_passes(make_tender, make_criteria, value):
    r = check_contract_value(make_tender(contract_value_pkr=value),
                             make_criteria(min_contract_value_pkr=5_000_000, max_contract_value_pkr=50_000_000))
    assert r.passed


def test_contract_value_not_stated_is_skipped(make_tender, make_criteria):
    assert check_contract_value(make_tender(), make_criteria(max_contract_value_pkr=1)) is None


# ---------------------------------------------------------------- PEC category

ALL_CATEGORIES = list(PECCategory)
PAIRS = [(held, required) for held in ALL_CATEGORIES for required in ALL_CATEGORIES]


@pytest.mark.parametrize("held,required", PAIRS)
def test_pec_passes_exactly_when_held_rank_is_at_least_required(make_tender, make_criteria, held, required):
    r = check_pec_category(make_tender(pec_category_required=required), make_criteria(pec_category_held=held))
    assert r.passed == (PEC_CATEGORY_RANK[held] >= PEC_CATEGORY_RANK[required])


def test_pec_lower_category_fails_with_clear_reason(make_tender, make_criteria):
    # C-A is the highest category and C-6 the lowest, so a C-4 holder cannot bid on a C-3 tender.
    r = check_pec_category(make_tender(pec_category_required="C-3"), make_criteria(pec_category_held="C-4"))
    assert not r.passed
    assert "does NOT meet" in r.reason


def test_pec_higher_category_may_bid_on_a_lower_category_tender(make_tender, make_criteria):
    r = check_pec_category(make_tender(pec_category_required="C-4"), make_criteria(pec_category_held="C-3"))
    assert r.passed
    assert "meets" in r.reason


def test_pec_not_stated_is_skipped(make_tender, make_criteria):
    assert check_pec_category(make_tender(), make_criteria()) is None


# ---------------------------------------------------------------- bid security

def test_bid_security_within_limit_passes(make_tender, make_criteria):
    r = check_bid_security(make_tender(bid_security_amount_pkr=1_000_000), make_criteria(max_bid_security_pkr=2_000_000))
    assert r.passed


def test_bid_security_above_limit_fails(make_tender, make_criteria):
    r = check_bid_security(make_tender(bid_security_amount_pkr=3_000_000), make_criteria(max_bid_security_pkr=2_000_000))
    assert not r.passed
    assert "EXCEEDS" in r.reason


def test_bid_security_given_as_percent_is_worked_out_from_contract_value(make_tender, make_criteria):
    tender = make_tender(contract_value_pkr=25_000_000, bid_security_percent=5)   # 5% = 1,250,000
    assert not check_bid_security(tender, make_criteria(max_bid_security_pkr=1_000_000)).passed
    r = check_bid_security(tender, make_criteria(max_bid_security_pkr=2_000_000))
    assert r.passed
    assert r.tender_value == "PKR 1,250,000"


def test_bid_security_fixed_amount_wins_over_percent(make_tender, make_criteria):
    tender = make_tender(contract_value_pkr=25_000_000, bid_security_percent=50, bid_security_amount_pkr=100_000)
    r = check_bid_security(tender, make_criteria(max_bid_security_pkr=200_000))
    assert r.passed
    assert r.tender_value == "PKR 100,000"


def test_bid_security_percent_without_contract_value_is_skipped(make_tender, make_criteria):
    assert check_bid_security(make_tender(bid_security_percent=5), make_criteria(max_bid_security_pkr=1)) is None


def test_bid_security_skipped_when_contractor_set_no_limit(make_tender, make_criteria):
    assert check_bid_security(make_tender(bid_security_amount_pkr=1_000_000), make_criteria()) is None


# ---------------------------------------------------------------- liquidated damages

def test_liquidated_damages_within_tolerance_passes(make_tender, make_criteria):
    r = check_liquidated_damages(make_tender(liquidated_damages_rate_percent_per_day=0.067),
                                 make_criteria(max_acceptable_ld_rate_percent_per_day=0.1))
    assert r.passed


def test_liquidated_damages_above_tolerance_fails(make_tender, make_criteria):
    r = check_liquidated_damages(make_tender(liquidated_damages_rate_percent_per_day=0.15),
                                 make_criteria(max_acceptable_ld_rate_percent_per_day=0.1))
    assert not r.passed
    assert "EXCEEDS" in r.reason


def test_liquidated_damages_equal_to_tolerance_passes(make_tender, make_criteria):
    r = check_liquidated_damages(make_tender(liquidated_damages_rate_percent_per_day=0.1),
                                 make_criteria(max_acceptable_ld_rate_percent_per_day=0.1))
    assert r.passed


def test_liquidated_damages_skipped_when_either_side_missing(make_tender, make_criteria):
    assert check_liquidated_damages(make_tender(), make_criteria(max_acceptable_ld_rate_percent_per_day=0.1)) is None
    assert check_liquidated_damages(make_tender(liquidated_damages_rate_percent_per_day=0.1), make_criteria()) is None


# ---------------------------------------------------------------- advance payment

def test_advance_payment_at_or_above_minimum_passes(make_tender, make_criteria):
    crit = make_criteria(min_required_advance_payment_percent=10)
    assert check_advance_payment(make_tender(advance_payment_percent=15), crit).passed
    assert check_advance_payment(make_tender(advance_payment_percent=10), crit).passed


def test_advance_payment_below_minimum_fails(make_tender, make_criteria):
    r = check_advance_payment(make_tender(advance_payment_percent=5), make_criteria(min_required_advance_payment_percent=10))
    assert not r.passed
    assert "BELOW" in r.reason


def test_no_advance_payment_is_zero_not_silence(make_tender, make_criteria):
    """'No advance payment' is stored as 0 and must be checked; an unstated value is None and skipped."""
    crit = make_criteria(min_required_advance_payment_percent=10)
    assert not check_advance_payment(make_tender(advance_payment_percent=0), crit).passed
    assert check_advance_payment(make_tender(), crit) is None


# ---------------------------------------------------------------- taxpayer, experience, completion

def test_taxpayer_required_and_held_passes(make_tender, make_criteria):
    assert check_active_taxpayer(make_tender(requires_active_taxpayer_status=True),
                                 make_criteria(is_active_taxpayer=True)).passed


def test_taxpayer_required_but_not_held_fails(make_tender, make_criteria):
    r = check_active_taxpayer(make_tender(requires_active_taxpayer_status=True),
                              make_criteria(is_active_taxpayer=False))
    assert not r.passed


def test_taxpayer_not_required_is_skipped(make_tender, make_criteria):
    assert check_active_taxpayer(make_tender(), make_criteria(is_active_taxpayer=False)) is None


def test_experience_checks(make_tender, make_criteria):
    tender = make_tender(min_years_experience_required=5)
    assert check_experience(tender, make_criteria(years_experience=8)).passed
    assert check_experience(tender, make_criteria(years_experience=5)).passed
    assert not check_experience(tender, make_criteria(years_experience=2)).passed
    assert check_experience(make_tender(), make_criteria(years_experience=8)) is None


def test_completion_period_must_give_enough_time(make_tender, make_criteria):
    crit = make_criteria(max_acceptable_completion_period_days=120)
    assert check_completion_period(make_tender(completion_period_days=150), crit).passed
    assert check_completion_period(make_tender(completion_period_days=120), crit).passed
    r = check_completion_period(make_tender(completion_period_days=90), crit)
    assert not r.passed
    assert "TIGHTER" in r.reason


def test_completion_period_skipped_when_either_side_missing(make_tender, make_criteria):
    assert check_completion_period(make_tender(), make_criteria(max_acceptable_completion_period_days=120)) is None
    assert check_completion_period(make_tender(completion_period_days=90), make_criteria()) is None


# ---------------------------------------------------------------- match(): the roll-up

SKIPPED_NAMES = ["contract_value", "pec_category", "bid_security", "liquidated_damages",
                 "advance_payment", "active_taxpayer", "experience", "completion_period"]


@pytest.fixture
def full_tender(make_tender):
    """A tender that makes all 8 checks run."""
    return make_tender(
        contract_value_pkr=20_000_000, pec_category_required="C-3", bid_security_amount_pkr=1_000_000,
        liquidated_damages_rate_percent_per_day=0.05, advance_payment_percent=15,
        requires_active_taxpayer_status=True, min_years_experience_required=5, completion_period_days=200,
    )


@pytest.fixture
def full_criteria(make_criteria):
    """A contractor with a limit for every check."""
    return make_criteria(
        pec_category_held="C-3", min_contract_value_pkr=5_000_000, max_contract_value_pkr=50_000_000,
        max_bid_security_pkr=2_000_000, max_acceptable_ld_rate_percent_per_day=0.1,
        min_required_advance_payment_percent=10, years_experience=8,
        max_acceptable_completion_period_days=120, is_active_taxpayer=True,
    )


def test_engine_has_eight_checks():
    assert len(ALL_CHECKS) == 8


def test_match_selects_when_every_check_passes(full_tender, full_criteria):
    d = match(full_tender, full_criteria)
    assert d.decision == "Select"
    assert d.criteria_checked == 8
    assert d.skipped_criteria == []
    assert not d.is_low_confidence
    assert d.confidence_note == "8 of 8 criteria checked"


def test_match_rejects_when_any_single_check_fails(make_tender, full_tender, full_criteria):
    tender = make_tender(**{**full_tender.model_dump(), "contract_value_pkr": 90_000_000})
    d = match(tender, full_criteria)
    assert d.decision == "Reject"
    assert len(d.failing_reasons) == 1
    assert "exceeds" in d.failing_reasons[0]


def test_match_reports_ids_and_names(full_tender, full_criteria):
    d = match(full_tender, full_criteria)
    assert d.tender_id == "T-001"
    assert d.contractor_name == "Test Firm"
    assert d.total_criteria == 8


def test_match_is_deterministic(full_tender, full_criteria):
    first, second = match(full_tender, full_criteria), match(full_tender, full_criteria)
    assert first.decision == second.decision
    assert [r.model_dump() for r in first.results] == [r.model_dump() for r in second.results]


def test_nothing_checked_is_insufficient_data_not_select(make_tender, make_criteria):
    """If no check can run, nothing was compared: the tender is neither approved nor rejected."""
    d = match(make_tender(), make_criteria())
    assert d.decision == "Insufficient data"
    assert d.criteria_checked == 0
    assert d.skipped_criteria == SKIPPED_NAMES
    assert d.is_low_confidence
    assert "NO VERDICT" in d.confidence_note
    assert "Read the full tender yourself" in d.confidence_note


def test_insufficient_data_also_when_every_value_is_on_only_one_side(make_tender, make_criteria):
    """Tender states things the contractor set no limit for, and the contractor has limits the tender never states."""
    tender = make_tender(bid_security_amount_pkr=1_000_000, liquidated_damages_rate_percent_per_day=0.1)
    crit = make_criteria(max_acceptable_completion_period_days=120, min_required_advance_payment_percent=10)
    assert match(tender, crit).decision == "Insufficient data"


def test_a_single_passing_check_is_still_a_select_but_low_confidence(make_tender, make_criteria):
    d = match(make_tender(contract_value_pkr=10_000_000), make_criteria())
    assert d.decision == "Select"
    assert d.criteria_checked == 1
    assert d.is_low_confidence
    assert "NO VERDICT" not in d.confidence_note


def test_a_single_failing_check_is_still_a_reject(make_tender, make_criteria):
    d = match(make_tender(contract_value_pkr=90_000_000), make_criteria(max_contract_value_pkr=50_000_000))
    assert d.decision == "Reject"


def test_exactly_half_checked_is_not_low_confidence(make_tender, make_criteria):
    tender = make_tender(contract_value_pkr=10_000_000, pec_category_required="C-3",
                         bid_security_amount_pkr=500_000, requires_active_taxpayer_status=True)
    crit = make_criteria(max_bid_security_pkr=1_000_000)
    d = match(tender, crit)
    assert d.criteria_checked == 4
    assert not d.is_low_confidence


def test_fewer_than_half_checked_is_low_confidence(make_tender, make_criteria):
    tender = make_tender(contract_value_pkr=10_000_000, pec_category_required="C-3", bid_security_amount_pkr=500_000)
    d = match(tender, make_criteria(max_bid_security_pkr=1_000_000))
    assert d.criteria_checked == 3
    assert d.is_low_confidence
    assert "could not compare" in d.confidence_note


def test_skipped_check_never_causes_a_reject(make_tender, make_criteria):
    """Missing information must not fail a contractor: the contract value passes, the LD check is skipped."""
    tender = make_tender(contract_value_pkr=10_000_000, liquidated_damages_rate_percent_per_day=5.0)
    d = match(tender, make_criteria())            # the contractor set no LD limit
    assert d.decision == "Select"
    assert "liquidated_damages" in d.skipped_criteria


def test_matching_engine_contains_no_llm_code():
    """Project rule: no LLM calls inside matching_engine.py."""
    source = (Path(__file__).resolve().parent.parent / "matching_engine.py").read_text(encoding="utf-8").lower()
    for word in ("openai", "anthropic", "chat.completions"):
        assert word not in source