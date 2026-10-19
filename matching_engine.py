"""
TenderGuard AI — matching engine.

Pure rule-based comparison: no AI/LLM involved in THIS file. By the time
a TenderTerms object reaches here, extraction is already done (see
extract_tender.py). This keeps the actual Select/Reject decision 100%
deterministic and explainable — the same tender + same criteria always
gives the same answer, which is exactly what your Success Criteria
(PRD section 11) promises.

Design rule: a criterion is only checked if BOTH the tender field and the
contractor's limit are present. If either is missing, we skip it (can't
fail a contractor on information we don't have) — see `source_text_snippets`
on TenderTerms to track what was actually found vs. missing.
"""

from schema import TenderTerms, ContractorCriteria, CriterionResult, MatchDecision, PEC_CATEGORY_RANK


def check_contract_value(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    if tender.contract_value_pkr is None:
        return None
    value = tender.contract_value_pkr
    too_small = criteria.min_contract_value_pkr is not None and value < criteria.min_contract_value_pkr
    too_large = criteria.max_contract_value_pkr is not None and value > criteria.max_contract_value_pkr
    passed = not (too_small or too_large)
    if too_large:
        reason = (f"Contract value PKR {value:,.0f} exceeds your maximum of "
                  f"PKR {criteria.max_contract_value_pkr:,.0f}")
    elif too_small:
        reason = (f"Contract value PKR {value:,.0f} is below your minimum of "
                  f"PKR {criteria.min_contract_value_pkr:,.0f}")
    else:
        reason = f"Contract value PKR {value:,.0f} is within your acceptable range"
    return CriterionResult(
        criterion_name="contract_value", passed=passed,
        tender_value=f"PKR {value:,.0f}",
        criteria_value=f"{criteria.min_contract_value_pkr}-{criteria.max_contract_value_pkr}",
        reason=reason,
    )


def check_pec_category(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    if tender.pec_category_required is None:
        return None
    required_rank = PEC_CATEGORY_RANK[tender.pec_category_required]
    held_rank = PEC_CATEGORY_RANK[criteria.pec_category_held]
    passed = held_rank >= required_rank
    reason = (
        f"Your licence category {criteria.pec_category_held.value} "
        f"{'meets' if passed else 'does NOT meet'} the required "
        f"{tender.pec_category_required.value}"
    )
    return CriterionResult(
        criterion_name="pec_category", passed=passed,
        tender_value=tender.pec_category_required.value,
        criteria_value=criteria.pec_category_held.value,
        reason=reason,
    )


def check_bid_security(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    required_amount = tender.bid_security_amount_pkr
    if required_amount is None and tender.bid_security_percent is not None and tender.contract_value_pkr:
        required_amount = tender.contract_value_pkr * tender.bid_security_percent / 100
    if required_amount is None or criteria.max_bid_security_pkr is None:
        return None
    passed = required_amount <= criteria.max_bid_security_pkr
    reason = (
        f"Bid security required (PKR {required_amount:,.0f}) "
        f"{'is within' if passed else 'EXCEEDS'} your limit of PKR {criteria.max_bid_security_pkr:,.0f}"
    )
    return CriterionResult(
        criterion_name="bid_security", passed=passed,
        tender_value=f"PKR {required_amount:,.0f}",
        criteria_value=f"PKR {criteria.max_bid_security_pkr:,.0f}",
        reason=reason,
    )


def check_liquidated_damages(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    if tender.liquidated_damages_rate_percent_per_day is None or \
       criteria.max_acceptable_ld_rate_percent_per_day is None:
        return None
    passed = tender.liquidated_damages_rate_percent_per_day <= criteria.max_acceptable_ld_rate_percent_per_day
    reason = (
        f"LD rate {tender.liquidated_damages_rate_percent_per_day}%/day "
        f"{'is within' if passed else 'EXCEEDS'} your tolerance of "
        f"{criteria.max_acceptable_ld_rate_percent_per_day}%/day"
    )
    return CriterionResult(
        criterion_name="liquidated_damages", passed=passed,
        tender_value=f"{tender.liquidated_damages_rate_percent_per_day}%/day",
        criteria_value=f"{criteria.max_acceptable_ld_rate_percent_per_day}%/day",
        reason=reason,
    )


def check_advance_payment(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    if tender.advance_payment_percent is None or criteria.min_required_advance_payment_percent is None:
        return None
    passed = tender.advance_payment_percent >= criteria.min_required_advance_payment_percent
    reason = (
        f"Advance payment offered ({tender.advance_payment_percent}%) "
        f"{'meets' if passed else 'is BELOW'} your minimum of "
        f"{criteria.min_required_advance_payment_percent}%"
    )
    return CriterionResult(
        criterion_name="advance_payment", passed=passed,
        tender_value=f"{tender.advance_payment_percent}%",
        criteria_value=f"{criteria.min_required_advance_payment_percent}%",
        reason=reason,
    )


def check_active_taxpayer(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    if not tender.requires_active_taxpayer_status:
        return None
    passed = criteria.is_active_taxpayer
    reason = ("You are on the FBR Active Taxpayer List" if passed
              else "This tender requires FBR Active Taxpayer status, which your profile does not have")
    return CriterionResult(
        criterion_name="active_taxpayer_status", passed=passed,
        tender_value="Required", criteria_value=str(criteria.is_active_taxpayer),
        reason=reason,
    )


def check_experience(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    if tender.min_years_experience_required is None:
        return None
    passed = criteria.years_experience >= tender.min_years_experience_required
    reason = (
        f"Your {criteria.years_experience} years' experience "
        f"{'meets' if passed else 'is below'} the required "
        f"{tender.min_years_experience_required} years"
    )
    return CriterionResult(
        criterion_name="experience", passed=passed,
        tender_value=f"{tender.min_years_experience_required} yrs required",
        criteria_value=f"{criteria.years_experience} yrs held",
        reason=reason,
    )


def check_completion_period(tender: TenderTerms, criteria: ContractorCriteria) -> CriterionResult | None:
    if tender.completion_period_days is None or criteria.max_acceptable_completion_period_days is None:
        return None
    passed = tender.completion_period_days >= criteria.max_acceptable_completion_period_days
    reason = (
        f"Completion period of {tender.completion_period_days} days "
        f"{'gives you enough time' if passed else 'is TIGHTER than your minimum comfortable timeline of '+str(criteria.max_acceptable_completion_period_days)+' days'}"
    )
    return CriterionResult(
        criterion_name="completion_period", passed=passed,
        tender_value=f"{tender.completion_period_days} days",
        criteria_value=f">= {criteria.max_acceptable_completion_period_days} days needed",
        reason=reason,
    )


ALL_CHECKS = [
    check_contract_value,
    check_pec_category,
    check_bid_security,
    check_liquidated_damages,
    check_advance_payment,
    check_active_taxpayer,
    check_experience,
    check_completion_period,
]


def match(tender: TenderTerms, criteria: ContractorCriteria) -> MatchDecision:
    """Run every applicable check and roll up to a final Select/Reject.
    Rule: ANY failed criterion -> Reject. All applicable criteria pass (or
    were skipped due to missing data) -> Select."""
    results = []
    for check_fn in ALL_CHECKS:
        result = check_fn(tender, criteria)
        if result is not None:
            results.append(result)

    decision = "Reject" if any(not r.passed for r in results) else "Select"

    return MatchDecision(
        tender_id=tender.tender_id,
        contractor_name=criteria.contractor_name,
        decision=decision,
        results=results,
    )


if __name__ == "__main__":
    # Quick smoke test with dummy data — replace with real data once you
    # have ground_truth_tenders.json and contractor_profiles.json populated.
    from schema import ProjectType, PECCategory

    sample_tender = TenderTerms(
        tender_id="TS0000016176E",
        title="Construction of 06 No. Cat-IV Flats at 132KV Grid Station Khurrianwala",
        organization="FESCO",
        project_type=ProjectType.BUILDING_CONSTRUCTION,
        contract_value_pkr=25_000_000,
        bid_security_amount_pkr=1_291_565,
        pec_category_required=PECCategory.C4,
        requires_active_taxpayer_status=True,
        completion_period_days=180,
    )

    sample_criteria = ContractorCriteria(
        contractor_name="Al-Hamd Builders (Pvt) Ltd",
        pec_category_held=PECCategory.C3,
        min_contract_value_pkr=5_000_000,
        max_contract_value_pkr=50_000_000,
        max_bid_security_pkr=2_000_000,
        is_active_taxpayer=True,
        years_experience=8,
        max_acceptable_completion_period_days=150,
    )

    decision = match(sample_tender, sample_criteria)
    print(f"Decision: {decision.decision}\n")
    for r in decision.results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.criterion_name}: {r.reason}")