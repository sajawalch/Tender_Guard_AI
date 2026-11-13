"""
TenderGuard AI - FastAPI backend.

    uvicorn api_server:app --reload

Endpoints
    GET  /api/contractors   list of saved contractor profiles
    POST /api/decide        upload tender PDF + contractor name -> decision
    POST /api/generate-bid  {result_id, force} -> draft bid .docx

Endpoints are plain `def` (not async) on purpose: reading PDFs, OCR and the
OpenAI call all block, and FastAPI runs plain `def` endpoints in a thread
pool so one slow upload does not freeze the whole server.
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from schema import ContractorCriteria
from extract_tender import extract_text_from_document, extract_fields_with_llm
from matching_engine import match
import bid_service

# extract_tender.py already calls load_dotenv(). Accept the common typo
# OPEN_AI_API_KEY too, so a misspelt .env line does not silently break extraction.
if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPEN_AI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ["OPEN_AI_API_KEY"]

BASE_DIR = Path(__file__).parent
CONTRACTOR_FILE = BASE_DIR / "contractor_profiles.json"
REACT_BUILD_DIR = BASE_DIR / "frontend-react" / "dist"

MAX_UPLOAD_MB = 25
ALLOWED_SUFFIXES = {".pdf", ".txt", ".md"}
LLM_TEXT_LIMIT = 60000  # same limit extract_tender.py applies before calling the model
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

app = FastAPI(title="TenderGuard AI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


_profile_lock = threading.Lock()


def load_contractors_raw() -> list[dict]:
    with open(CONTRACTOR_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_contractors_raw(items: list[dict]) -> None:
    """Write to a temp file first, then swap it in, so a crash can never
    leave contractor_profiles.json half-written."""
    tmp = CONTRACTOR_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONTRACTOR_FILE)


def public_profile(c: dict) -> dict:
    return {k: v for k, v in c.items() if not k.startswith("_")}


@app.get("/api/contractors")
def list_contractors():
    return [
        {
            "name": c["contractor_name"],
            "pec_category": c["pec_category_held"],
            "max_contract_value_pkr": c.get("max_contract_value_pkr"),
            "mine": bool(c.get("_mine")),   # created through the web form (not a demo firm)
            "profile": public_profile(c),
        }
        for c in load_contractors_raw()
    ]


class SaveContractorRequest(BaseModel):
    original_name: Optional[str] = None   # set when editing / renaming an existing firm
    profile: dict


NON_NEGATIVE_FIELDS = [
    "min_contract_value_pkr", "max_contract_value_pkr", "max_bid_security_pkr",
    "max_acceptable_ld_rate_percent_per_day", "min_required_advance_payment_percent",
    "max_acceptable_completion_period_days", "years_experience",
]


@app.post("/api/contractors")
def save_contractor(req: SaveContractorRequest):
    """Create a new firm profile, or update an existing one. The profile is
    validated with the same pydantic model the matcher uses."""
    incoming = {k: v for k, v in req.profile.items() if not k.startswith("_")}
    try:
        criteria = ContractorCriteria(**incoming)
    except ValidationError as e:
        msgs = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        raise HTTPException(422, msgs)

    name = criteria.contractor_name.strip()
    if not name:
        raise HTTPException(422, "Enter your firm's name.")
    for f in NON_NEGATIVE_FIELDS:
        v = getattr(criteria, f)
        if v is not None and v < 0:
            raise HTTPException(422, f"{f.replace('_', ' ')} cannot be negative.")
    lo, hi = criteria.min_contract_value_pkr, criteria.max_contract_value_pkr
    if lo is not None and hi is not None and lo > hi:
        raise HTTPException(422, "The smallest contract value is larger than the largest.")

    saved = {k: v for k, v in criteria.model_dump(mode="json").items() if k in incoming}
    saved["contractor_name"] = name

    with _profile_lock:
        items = load_contractors_raw()
        orig_key = (req.original_name or "").strip().lower()
        idx = next((i for i, c in enumerate(items)
                    if c["contractor_name"].strip().lower() == orig_key), None) if orig_key else None
        clash = next((i for i, c in enumerate(items)
                      if c["contractor_name"].strip().lower() == name.lower() and i != idx), None)
        if clash is not None:
            raise HTTPException(409, f"A firm named '{name}' already exists. Pick it from the list to edit it.")
        if idx is None:
            items.append(criteria.model_dump(mode="json") | {"contractor_name": name, "_mine": True})
            idx = len(items) - 1
        else:
            items[idx] = {**items[idx], **saved}   # keeps fields this form does not show
        save_contractors_raw(items)
        result = public_profile(items[idx])

    return {"name": name, "profile": result}


@app.post("/api/decide")
def decide(
    file: UploadFile = File(...),
    contractor_name: str = Form(...),
    title: str = Form(""),
):
    # 1. contractor
    wanted = contractor_name.strip().lower()
    raw = next((c for c in load_contractors_raw()
                if c["contractor_name"].strip().lower() == wanted), None)
    if raw is None:
        raise HTTPException(404, f"Contractor '{contractor_name}' not found.")
    contractor = ContractorCriteria(**{k: v for k, v in raw.items() if not k.startswith("_")})

    # 2. upload checks
    filename = Path(file.filename or "tender.pdf").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Upload a PDF (or a .txt tender).")
    data = file.file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
    if not data:
        raise HTTPException(422, "The uploaded file is empty.")

    # 3. read -> extract -> match
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        try:
            text = extract_text_from_document(tmp_path)
        except Exception as e:
            raise HTTPException(422, f"Could not read this file: {e}")
        if not text.strip():
            raise HTTPException(422, "No text could be read from this file, even with OCR.")

        try:
            tender = extract_fields_with_llm(
                text, tender_id=Path(filename).stem, title=title.strip() or filename)
        except Exception as e:
            raise HTTPException(500, f"Extraction failed: {e}")
    finally:
        os.unlink(tmp_path)

    decision = match(tender, contractor)
    result_id = bid_service.store_result(tender, contractor, decision)

    return {
        "result_id": result_id,
        "tender_title": tender.title,
        "contractor_name": contractor.contractor_name,
        "decision": decision.decision,
        "criteria_checked": decision.criteria_checked,
        "criteria_total": decision.total_criteria,
        "skipped_criteria": decision.skipped_criteria,
        "low_confidence": decision.is_low_confidence,
        "confidence_note": decision.confidence_note,
        "deadline_warning": tender.deadline_warning,
        "text_length": len(text),
        "text_truncated": len(text) > LLM_TEXT_LIMIT,
        "results": [
            {
                "criterion": r.criterion_name,
                "passed": r.passed,
                "tender_value": r.tender_value,
                "criteria_value": r.criteria_value,
                "reason": r.reason,
            }
            for r in decision.results
        ],
        "extracted_fields": tender.model_dump(mode="json"),
    }


class GenerateBidRequest(BaseModel):
    result_id: str
    force: bool = False


@app.post("/api/generate-bid")
def generate_bid(req: GenerateBidRequest):
    try:
        path, download_name = bid_service.build_bid_file(req.result_id, force=req.force)
    except bid_service.ResultNotFound:
        raise HTTPException(404, "This result is no longer stored (the server restarted). "
                                 "Analyse the tender again.")
    except bid_service.BidNotAllowed as e:
        raise HTTPException(409, str(e))
    return FileResponse(path, media_type=DOCX_MIME, filename=download_name)


# Production: serve the built React app (after `npm run build`). Mounted last
# so it never shadows the /api routes.
if REACT_BUILD_DIR.exists():
    app.mount("/", StaticFiles(directory=str(REACT_BUILD_DIR), html=True), name="frontend")