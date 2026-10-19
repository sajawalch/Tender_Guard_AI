"""
TenderGuard AI — extraction pipeline.

Step 1: pull raw text out of a tender document — a PDF (PyMuPDF, with a
         pdfplumber fallback) or a plain .txt file (read directly, no
         parsing needed — useful for testing against synthetic_tenders.md
         before your PDF pipeline is fully working).
Step 2: send that text to an LLM with a strict instruction to return ONLY the
         fields in our schema, as JSON — nothing invented, nulls where the
         document doesn't say.

Run this file directly for a quick manual test:
    python extract_tender.py path/to/tender.pdf
    python extract_tender.py path/to/tender.txt ST-2026-001 "Some Title"

Requires (install locally, where you have internet):
    pip install pymupdf pdfplumber pydantic openai
    (or: pip install pymupdf pdfplumber pydantic anthropic, if using Claude instead)
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

from schema import TenderTerms

# Load variables from a local .env file if present, so you don't need to
# retype OPENAI_API_KEY every time you open a new terminal. Falls back
# silently to whatever's already in your shell environment if no .env
# file exists or python-dotenv isn't installed.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------- document -> text

def extract_text_from_document(doc_path: str) -> str:
    """Routes to .txt (plain read) or .pdf (parsing) based on file extension."""
    if doc_path.lower().endswith(".txt") or doc_path.lower().endswith(".md"):
        return Path(doc_path).read_text(encoding="utf-8")
    return extract_text_from_pdf(doc_path)


def extract_text_from_pdf(pdf_path: str) -> str:
    """Try PyMuPDF first (fast, handles most PPRA tenders fine).
    Fall back to pdfplumber if PyMuPDF returns suspiciously little text
    (a common sign the PDF is scanned/image-based)."""
    text = ""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        print(f"PyMuPDF failed ({e}), trying pdfplumber...", file=sys.stderr)

    if len(text.strip()) < 200:  # suspiciously little text -> likely scanned
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            print(f"pdfplumber also failed ({e}).", file=sys.stderr)

    if len(text.strip()) < 200:
        print(
            "WARNING: very little text extracted. This PDF is likely scanned "
            "images rather than real text — you'll need OCR (e.g. pytesseract) "
            "to read it. Not included in this starter script; add if you hit "
            "this case with your real downloaded PPRA tenders.",
            file=sys.stderr,
        )
    return text


# ---------------------------------------------------------------- text -> fields

EXTRACTION_SYSTEM_PROMPT = """You are a precise document-extraction engine for \
Pakistani government construction tenders. You will be given the raw text of a \
tender document. Extract ONLY the following fields and return them as a single \
JSON object matching this exact structure — no extra commentary, no markdown \
fences, just the JSON object.

Fields to extract (use null for anything not explicitly stated — NEVER guess \
or infer a number that isn't written in the text):

{
  "contract_value_pkr": number or null,
  "bid_security_amount_pkr": number or null,
  "bid_security_percent": number or null,
  "liquidated_damages_rate_percent_per_day": number or null,
  "liquidated_damages_cap_percent": number or null,
  "advance_payment_percent": number or null,
  "payment_cycle_days": integer or null,
  "pec_category_required": one of ["C-A","C-1","C-2","C-3","C-4","C-5","C-6"] or null,
  "requires_active_taxpayer_status": true or false,
  "min_years_experience_required": integer or null,
  "completion_period_days": integer or null,
  "source_text_snippets": {
     "<field_name>": "<the exact sentence this value came from>"
  }
}

Rules:
- Only populate source_text_snippets for fields you actually filled in (not null).
- If bid security is stated as a percentage (e.g. "2% of estimated cost"), put it \
in bid_security_percent, not bid_security_amount_pkr.
- If the document mentions PEC registration/licence without a specific category \
letter, set pec_category_required to null but still note it in source_text_snippets \
under a "pec_mention" key.
- requires_active_taxpayer_status is true ONLY if the document explicitly mentions \
FBR / Active Taxpayer List / ATL requirements.
- Phrases that explicitly state an absence or a single-payment structure ARE \
explicit values, not missing information — extract them as numbers, don't leave \
them null:
    - "no advance payment" / "no mobilization advance" -> advance_payment_percent: 0
    - "lump sum on completion" / "single payment upon completion" / \
      "payment on completion" -> payment_cycle_days: 0
  Only use null for a field when the document truly says nothing about it at all, \
  not when it explicitly describes a zero/one-time arrangement in words.
"""


def extract_fields_with_llm(raw_text: str, tender_id: str, title: str,
                              organization: str | None = None) -> TenderTerms:
    """Calls an LLM API to extract structured fields from raw tender text.

    Set LLM_PROVIDER to "openai" or "anthropic" (defaults to "openai" since
    that's what most people already have a key for). Needs the matching
    environment variable set:
        OPENAI_API_KEY      (if LLM_PROVIDER=openai)
        ANTHROPIC_API_KEY    (if LLM_PROVIDER=anthropic)
    """
    import os
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()

    # Truncate very long documents to keep cost/latency reasonable — most
    # key clauses (bid security, LD, eligibility) appear in the first
    # ~15,000 characters of a PPRA tender. Adjust if you find otherwise.
    truncated = raw_text[:15000]

    if provider == "openai":
        import openai
        client = openai.OpenAI()  # reads OPENAI_API_KEY from env

        response = client.chat.completions.create(
            model="gpt-4o-mini",  # fast + cheap; swap to "gpt-4o" if accuracy is weak
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": truncated},
            ],
            response_format={"type": "json_object"},  # forces valid JSON, no fence-stripping needed
            max_tokens=1500,
        )
        raw_json = response.choices[0].message.content.strip()

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": truncated}],
        )
        raw_json = response.content[0].text.strip()
        # Strip markdown fences if the model adds them despite instructions
        if raw_json.startswith("```"):
            raw_json = raw_json.split("```")[1]
            if raw_json.startswith("json"):
                raw_json = raw_json[4:]

    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'openai' or 'anthropic'.")

    extracted = json.loads(raw_json)

    return TenderTerms(
        tender_id=tender_id,
        title=title,
        organization=organization,
        **extracted,
    )


# ---------------------------------------------------------------- CLI entry point

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_tender.py path/to/tender.pdf [tender_id] [title]")
        sys.exit(1)

    doc_path = sys.argv[1]
    tender_id = sys.argv[2] if len(sys.argv) > 2 else Path(doc_path).stem
    title = sys.argv[3] if len(sys.argv) > 3 else "Unknown title"

    print(f"Extracting text from {doc_path} ...")
    text = extract_text_from_document(doc_path)
    print(f"Got {len(text)} characters of text.\n")

    print("Calling LLM for structured extraction "
          "(requires OPENAI_API_KEY, or ANTHROPIC_API_KEY + LLM_PROVIDER=anthropic)...")
    terms = extract_fields_with_llm(text, tender_id=tender_id, title=title)

    print("\n--- Extracted TenderTerms ---")
    print(terms.model_dump_json(indent=2))