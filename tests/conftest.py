"""Shared fixtures for the TenderGuard AI tests.

All tests run offline: no OpenAI calls, no internet, no real PDFs.
Run them from the project folder with:   python -m pytest
"""

import sys
from pathlib import Path

import pytest

# Make the project's own modules (schema.py, matching_engine.py ...) importable.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schema import ContractorCriteria, TenderTerms  # noqa: E402


@pytest.fixture
def make_tender():
    """make_tender(contract_value_pkr=20_000_000, ...) -> TenderTerms"""
    def _make(**fields):
        base = {"tender_id": "T-001", "title": "Test tender"}
        base.update(fields)
        return TenderTerms(**base)
    return _make


@pytest.fixture
def make_criteria():
    """make_criteria(max_contract_value_pkr=50_000_000, ...) -> ContractorCriteria"""
    def _make(**fields):
        base = {"contractor_name": "Test Firm", "pec_category_held": "C-3"}
        base.update(fields)
        return ContractorCriteria(**base)
    return _make


@pytest.fixture(autouse=True)
def empty_bid_cache():
    """The bid cache is a module-level dict; keep tests independent of each other."""
    import bid_service
    bid_service._cache.clear()
    yield
    bid_service._cache.clear()