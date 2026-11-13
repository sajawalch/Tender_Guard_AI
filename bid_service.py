"""
TenderGuard AI - bid_service.py

Keeps the latest decisions in memory (so the web app can build a draft bid
document for a result the user just saw) and builds the .docx.

The cache is in memory only: it is lost when the server restarts
(and uvicorn --reload restarts it whenever you save a .py file).
"""

import re
import tempfile
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from generate_bid_document import generate_bid_document

MAX_CACHED_RESULTS = 50
_cache: "OrderedDict[str, dict]" = OrderedDict()
_lock = threading.Lock()
_OUT_DIR = Path(tempfile.gettempdir()) / "tenderguard_bids"


class ResultNotFound(Exception):
    """The result id is unknown (never existed, or the server restarted)."""


class BidNotAllowed(Exception):
    """The decision was Reject and the caller did not confirm with force=True."""


def store_result(tender, contractor, decision) -> str:
    result_id = uuid.uuid4().hex
    with _lock:
        _cache[result_id] = {"tender": tender, "contractor": contractor, "decision": decision}
        while len(_cache) > MAX_CACHED_RESULTS:
            _cache.popitem(last=False)
    return result_id


def build_bid_file(result_id: str, force: bool = False) -> tuple[str, str]:
    """Returns (path_to_docx, suggested_download_name)."""
    with _lock:
        item = _cache.get(result_id)
    if item is None:
        raise ResultNotFound(result_id)

    tender, contractor, decision = item["tender"], item["contractor"], item["decision"]
    if decision.decision == "Reject" and not force:
        raise BidNotAllowed("This tender was rejected for this contractor.")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUT_DIR / f"{result_id}.docx"
    failed = [r.reason for r in decision.results if not r.passed]
    generate_bid_document(
        tender, contractor, str(path),
        failed_checks=failed or None,
        confidence_note=decision.confidence_note,
    )
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", tender.tender_id) or "tender"
    return str(path), f"Bid_Draft_{safe}.docx"