"""
TenderGuard AI — core data schema.

These two models are the backbone of the whole system:
- TenderTerms   -> what gets extracted FROM a tender document
- ContractorCriteria -> what a contractor sets about THEMSELVES, once

The matching engine (matching_engine.py) compares one of each and produces
a Select/Reject decision.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    BUILDING_CONSTRUCTION = "building_construction"
    ROADS_HIGHWAYS = "roads_highways"
    ELECTRICAL_MECHANICAL = "electrical_mechanical"
    REPAIR_MAINTENANCE = "repair_maintenance"
    WATER_POWER = "water_power"
    OTHER = "other"


class PECCategory(str, Enum):
    """PEC constructor licence categories, highest (C-A) to lowest (C-6).
    Lower categories = smaller contract value limits."""
    C_A = "C-A"
    C1 = "C-1"
    C2 = "C-2"
    C3 = "C-3"
    C4 = "C-4"
    C5 = "C-5"
    C6 = "C-6"


# Rough relative ordering so we can compare "is contractor's category >= required category"
PEC_CATEGORY_RANK = {
    PECCategory.C6: 1,
    PECCategory.C5: 2,
    PECCategory.C4: 3,
    PECCategory.C3: 4,
    PECCategory.C2: 5,
    PECCategory.C1: 6,
    PECCategory.C_A: 7,
}


class TenderTerms(BaseModel):
    """Fields extracted FROM a tender document. Every field is Optional
    because real tenders don't always state every term explicitly —
    the extraction step should leave a field as None rather than guess."""

    tender_id: str = Field(..., description="Tender reference number, e.g. TS0000016176E")
    title: str = Field(..., description="Tender title / short description")
    organization: Optional[str] = Field(None, description="Procuring agency / department")

    project_type: Optional[ProjectType] = None

    contract_value_pkr: Optional[float] = Field(
        None, description="Estimated / engineer's estimate contract value in PKR"
    )

    bid_security_amount_pkr: Optional[float] = Field(
        None, description="Bid security as a fixed PKR amount, if stated that way"
    )
    bid_security_percent: Optional[float] = Field(
        None, description="Bid security as a percentage of contract value, if stated that way"
    )

    liquidated_damages_rate_percent_per_day: Optional[float] = Field(
        None, description="LD rate, e.g. 0.067 for 1/15th percent per day"
    )
    liquidated_damages_cap_percent: Optional[float] = Field(
        None, description="Maximum LD as % of contract value, e.g. 10.0"
    )

    advance_payment_percent: Optional[float] = Field(
        None, description="Advance payment offered, as % of contract value"
    )
    payment_cycle_days: Optional[int] = Field(
        None, description="How often payments are made (e.g. 30 for monthly)"
    )

    pec_category_required: Optional[PECCategory] = Field(
        None, description="Minimum PEC licence category a bidder must hold"
    )
    requires_active_taxpayer_status: bool = Field(
        False, description="Whether FBR Active Taxpayer List status is required"
    )
    min_years_experience_required: Optional[int] = None

    completion_period_days: Optional[int] = None
    bid_closing_date: Optional[str] = Field(None, description="ISO date string")

    source_text_snippets: dict[str, str] = Field(
        default_factory=dict,
        description="field_name -> the exact sentence it was extracted from, "
                    "for human verification. ALWAYS populate this for extracted fields.",
    )


class ContractorCriteria(BaseModel):
    """A contractor's own qualification profile — set once, reused for every tender."""

    contractor_name: str
    pec_category_held: PECCategory

    min_contract_value_pkr: Optional[float] = Field(
        None, description="Don't bother with tenders smaller than this"
    )
    max_contract_value_pkr: Optional[float] = Field(
        None, description="Can't realistically handle tenders larger than this "
                           "(often driven by PEC category limit)"
    )

    max_bid_security_pkr: Optional[float] = Field(
        None, description="Maximum bid security the firm can tie up in cash/guarantee"
    )

    max_acceptable_ld_rate_percent_per_day: Optional[float] = None
    max_acceptable_ld_cap_percent: Optional[float] = None

    min_required_advance_payment_percent: Optional[float] = Field(
        None, description="Won't bid if advance payment is below this"
    )
    max_acceptable_payment_cycle_days: Optional[int] = None

    is_active_taxpayer: bool = True
    years_experience: int = 0

    preferred_project_types: list[ProjectType] = Field(default_factory=list)

    max_acceptable_completion_period_days: Optional[int] = Field(
        None, description="Reject if the tender's timeline is tighter than this minimum"
    )


class CriterionResult(BaseModel):
    """Result of checking ONE criterion against ONE tender field."""
    criterion_name: str
    passed: bool
    tender_value: Optional[str] = None
    criteria_value: Optional[str] = None
    reason: str


class MatchDecision(BaseModel):
    """Final output of the matching engine for one (tender, contractor) pair."""
    tender_id: str
    contractor_name: str
    decision: str  # "Select" or "Reject"
    results: list[CriterionResult]

    @property
    def failing_reasons(self) -> list[str]:
        return [r.reason for r in self.results if not r.passed]