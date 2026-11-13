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
import re
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
    import os
    if not os.path.exists(doc_path):
        raise FileNotFoundError(
            f"Tender file not found: '{doc_path}'\n"
            f"  The script is running from: {os.getcwd()}\n"
            f"  Check the file name and that it is saved in that folder "
            f"(run  ls tenders  to list what is there)."
        )
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
            "Very little real text found — this PDF is likely scanned images, "
            "not selectable text. Falling back to OCR (this is slower)...",
            file=sys.stderr,
        )
        text = extract_text_via_ocr(pdf_path)

    return text


def extract_text_via_ocr(pdf_path: str) -> str:
    """Renders each PDF page to an image and runs Tesseract OCR on it.

    Requires:
        pip install pytesseract pillow
        PLUS the actual Tesseract OCR engine installed separately (it is NOT
        a pip package) — on Windows, download the installer from:
        https://github.com/UB-Mannheim/tesseract/wiki
        After installing, you may need to point pytesseract at the exe, e.g.:
        pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
    """
    try:
        import fitz  # PyMuPDF — reused here just to rasterize pages to images
        import pytesseract
        from PIL import Image
        import io
        import os
    except ImportError as e:
        print(
            f"OCR dependencies missing ({e}). Run: "
            f"pip install pytesseract pillow  —  AND install the Tesseract "
            f"OCR engine itself (see function docstring for the Windows link).",
            file=sys.stderr,
        )
        return ""

    # pytesseract calls the Tesseract .exe as an external program — it does
    # NOT come from pip install. On Windows this often isn't on PATH, so we
    # check the default install location automatically before giving up.
    if sys.platform == "win32":
        default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(default_path):
            pytesseract.pytesseract.tesseract_cmd = default_path
        elif not os.path.exists(pytesseract.pytesseract.tesseract_cmd or ""):
            print(
                "ERROR: Tesseract OCR engine not found. This is a separate "
                "program from the pip package — download and install it from:\n"
                "  https://github.com/UB-Mannheim/tesseract/wiki\n"
                "Then re-run this script. If you installed it somewhere other "
                "than the default location, edit the 'default_path' line in "
                "extract_tender.py's extract_text_via_ocr() to match where "
                "you installed it.",
                file=sys.stderr,
            )
            return ""

    doc = fitz.open(pdf_path)
    all_text = []
    for page_num, page in enumerate(doc):
        # Render at 2x zoom for better OCR accuracy on scanned/stamped documents
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        page_text = pytesseract.image_to_string(img)
        all_text.append(page_text)
        print(f"  OCR'd page {page_num + 1}/{len(doc)} "
              f"({len(page_text)} chars found)", file=sys.stderr)
    doc.close()

    return "\n".join(all_text)


# ---------------------------------------------------------------- text -> fields

EXTRACTION_SYSTEM_PROMPT = """You are a precise document-extraction engine for \
Pakistani government construction tenders. You will be given the raw text of a \
tender document. Extract ONLY the following fields and return them as a single \
JSON object matching this exact structure — no extra commentary, no markdown \
fences, just the JSON object.

Fields to extract (use null for anything not explicitly stated — NEVER guess \
or infer a number that isn't written in the text):

{
  "organization": the procuring agency / department that issued the tender, or null,
  "project_title": the name/subject of the WORK being tendered (e.g. "Repair and \
Maintenance of Office of Chief Engineer ..."), NOT the department letterhead, or null,
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
  "min_similar_contracts": integer or null,
  "similar_contracts_lookback_years": integer or null,
  "pec_specialization_code": string or null,
  "addressee": string or null,
  "required_documents": [list of short strings, or an empty list],
  "completion_period_days": integer or null,
  "bid_validity_days": integer or null,
  "bid_closing_date": "YYYY-MM-DD HH:MM" (24-hour) or "YYYY-MM-DD" if no time is stated, or null,
  "source_text_snippets": {
     "<field_name>": "<the exact sentence this value came from>"
  }
}

Rules:
- Only populate source_text_snippets for fields you actually filled in (not null).
- If bid security is stated as a percentage (e.g. "2% of estimated cost"), put it \
in bid_security_percent and leave bid_security_amount_pkr null. NEVER calculate an \
amount yourself by multiplying a percentage by the contract value — only fill \
bid_security_amount_pkr when the document itself states a rupee figure.
- If the document mentions PEC registration/licence without a specific category \
letter, set pec_category_required to null but still note it in source_text_snippets \
under a "pec_mention" key.
- bid_validity_days: the number of days the bid must stay valid (e.g. "bid shall be valid for 140 days" -> 140). bid_closing_date: the LAST date (and time) for SUBMITTING bids, not the opening or publication date. If a date is partly illegible or garbled (common in scanned notices), use null instead of guessing.
- min_years_experience_required is ONLY for an explicit statement of years of \
experience or years in business (e.g. "5 years of experience"). If the notice \
instead says the bidder must have completed N contracts of the same nature within \
the last M years, set min_similar_contracts=N and similar_contracts_lookback_years=M \
and leave min_years_experience_required null. NEVER turn "within ten years" into \
"10 years of experience".
- pec_specialization_code: the specialization code written next to the PEC \
category (e.g. "CE-10"), or null.
- addressee: the specific officer or office the bid is submitted to, or the bid \
security is payable in favour of (e.g. "Executive Engineer, Civil Works Division, \
<utility>, <city>"), or null.
- required_documents: one short phrase per ADDITIONAL document or eligibility proof \
the notice requires from bidders. Work through the notice's eligibility / \
qualification list ITEM BY ITEM (a, b, c, ... or 1, 2, 3, ...) and include EVERY \
item that is not excluded below — do not stop after the first few and do not merge \
different requirements into one. Typical items: tax returns for the last N years, \
audited financial statements or annual-turnover proof, bank statements or \
cash/liquidity proof, sales-tax registration, the value or number of past \
contracts, and conditions on how the bid security must be delivered or how long it \
must stay valid. KEEP every number exactly as the notice states it (percentages, \
years, amounts), e.g. "Cash or cash equivalents of 10% of contract value shown by \
bank statements of the last year". Do NOT list PEC registration, Active Taxpayer \
List status, the bid security AMOUNT or ID-card copies here — those are handled \
separately. Use an empty list if there is nothing else. Never invent requirements.
- requires_active_taxpayer_status is true ONLY if the document explicitly mentions \
FBR / Active Taxpayer List / ATL requirements.
- Phrases that EXPLICITLY state an absence or a single-payment structure ARE \
explicit values, not missing information — extract them as numbers, don't leave \
them null:
    - "no advance payment" / "no mobilization advance" -> advance_payment_percent: 0
    - "lump sum on completion" / "single payment upon completion" / \
      "payment on completion" -> payment_cycle_days: 0
  CRITICAL DISTINCTION — do not confuse silence with an explicit statement of \
  zero: these rules apply ONLY when the document explicitly uses words like "no \
  advance payment" or "lump sum". If the document simply never mentions advance \
  payment or payment cycle AT ALL — neither confirming nor denying it — you MUST \
  use null, NOT 0. A document that says nothing about advance payment is different \
  from one that explicitly says "no advance payment will be made." When in doubt, \
  search the full text for the literal words "advance" and "payment" — if neither \
  appears anywhere, the field is null, not 0.
- MULTI-ITEM TENDERS: some tenders list several separate work items/jobs in a \
table, each with its own estimated cost and sometimes its own bid security/earnest \
money amount, rather than one single contract value. When you see a table like this:
    - Set contract_value_pkr to the SUM of every individual item's estimated cost \
listed in the table (add them all together — show your addition correctly).
    - If each item also has its own earnest money/bid security amount listed, set \
bid_security_amount_pkr to the SUM of all of those individual amounts.
    - If a bid security RATE is also stated separately as a formula (e.g. "2% of \
estimated cost"), ALSO populate bid_security_percent with that rate, in addition to \
the summed amount — both fields can and should be filled in together in this case.
    - Double check your arithmetic before finalizing — sum errors are a common \
mistake with multi-row tables.
    - CRITICAL — do not confuse two different table patterns:
        (a) A SINGLE tender broken into multiple work packages/items that are ALL \
part of the SAME bidding process (one shared submission deadline, one shared \
earnest-money submission for the whole lot). In this case, SUM across all rows, \
as described above.
        (b) A BULLETIN listing MULTIPLE SEPARATE, independently-numbered tenders \
bundled into one notice (each row has its own distinct tender item number, often \
its own PEC category, own location/project name, sometimes its own deadline). In \
this case, you are extracting data for ONE SPECIFIC tender only — identified by \
the "THIS SPECIFIC TENDER" instruction given to you below — NOT the whole table. \
Find the ONE row whose project name/work description matches that specific \
tender, and use ONLY that row's figures. Do NOT sum unrelated rows together.
      If you are unsure which pattern applies, check: do all rows share the exact \
same submission deadline and the exact same tender reference number? If yes, it's \
pattern (a). If each row has its own distinct item/tender number, it's pattern (b).
- UNIT CONVERSION — this is critical and easy to get wrong: tables and text \
often state costs in "Million" (often abbreviated "M", "Mn", or a column header \
like "Rs. In (M)") or "Lakh"/"Lac" (abbreviated "L") rather than raw Rupees. \
contract_value_pkr, bid_security_amount_pkr, and every other *_pkr field MUST \
ALWAYS be the full raw Rupee amount, never a figure still in Million/Lakh units:
    - If a value is stated in Millions (e.g. "7.650" under a column header "Rs. \
In (M)", or "PKR 7.65 Million", or "7.65 Mn"): multiply by 1,000,000 before using \
it. "7.650" in that context becomes 7650000, NOT 7.650 or 7.65.
    - If a value is stated in Lakhs (e.g. "5 Lakh" or "5L"): multiply by 100,000. \
"5 Lakh" becomes 500000, NOT 5.
    - Before finalizing any *_pkr field, sanity-check it: Pakistani construction \
tenders are essentially never worth less than roughly PKR 100,000 in total. If \
your computed value is smaller than that (e.g. a number like "7.65" or "64.88"), \
you have almost certainly forgotten a unit conversion — go back and reapply it.
"""


def sanitize_amounts(extracted: dict) -> dict:
    """Turn impossible rupee amounts into None ("not found").

    A contract value or bid security under PKR 1,000 is almost certainly a
    missed unit conversion (e.g. "64.883" instead of 64,883,000) or a
    placeholder zero. A wrong number is worse than no number: the matching
    engine would run a check against it, while a missing value is simply
    skipped and reported in the coverage note."""
    for field in ("contract_value_pkr", "bid_security_amount_pkr"):
        value = extracted.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 1000:
            extracted[field] = None
    return extracted


def _call_llm(system_prompt: str, user_message: str) -> str:
    """One JSON-returning LLM call. Provider is chosen with LLM_PROVIDER ("openai" or "anthropic")."""
    import os
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()

    if provider == "openai":
        import openai
        # Longer timeout + more retries than the defaults: on slow or flaky
        # connections the default settings give up too early and just say
        # "Connection error". OPENAI_BASE_URL / HTTPS_PROXY env vars are
        # honoured automatically if you need to route through a proxy.
        client = openai.OpenAI(timeout=90.0, max_retries=5)  # reads OPENAI_API_KEY from env

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # fast + cheap; swap to "gpt-4o" if accuracy is weak
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},  # forces valid JSON, no fence-stripping needed
                temperature=0,   # extraction must be repeatable, not creative
                max_tokens=3000,  # the required_documents list can be long
            )
        except Exception as e:
            # The OpenAI library hides the real network error behind a vague
            # "Connection error". Walk down to the root cause so you can see
            # whether it's DNS, SSL/certificate, timeout, proxy, etc.
            root = e
            while getattr(root, "__cause__", None) is not None:
                root = root.__cause__
            raise RuntimeError(
                f"{e}\n  Underlying cause: {type(root).__name__}: {root}\n"
                f"  Run  python check_connection.py  to diagnose your connection step by step."
            ) from e
        raw_json = response.choices[0].message.content.strip()

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

        response = client.messages.create(
            model="claude-sonnet-4-6",
            temperature=0,
            max_tokens=3000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw_json = response.content[0].text.strip()
        # Strip markdown fences if the model adds them despite instructions
        if raw_json.startswith("```"):
            raw_json = raw_json.split("```")[1]
            if raw_json.startswith("json"):
                raw_json = raw_json[4:]

    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'openai' or 'anthropic'.")

    return raw_json


# ---------------------------------------------------------------- step 2: the requirements checklist

REQUIREMENTS_SYSTEM_PROMPT = """You turn a tender notice into a checklist of what a bidder must \
provide, meet or do. Answer with JSON only:
{"requirements": [{"text": "...", "evidence": "..."}]}

Rules:
1. Include only requirements the document states: documents and certificates to provide, eligibility \
conditions, past-experience and financial conditions, safety or compliance conditions, how and by when \
the bid must be submitted, and the form, beneficiary and validity of the bid security.
2. Keep every number, amount, percentage, period, year, name and place exactly as the document writes \
it. Never calculate, convert units, round, add up or invent a number. If a clause points to a figure given \
elsewhere (for example "the amount mentioned against this work" pointing to a table column), copy that \
figure as written in the row of THE SPECIFIC TENDER and say where it comes from. If its unit is not stated, \
write "unit not stated" instead of guessing "million".
3. One requirement per item, as one short plain sentence. Do not merge different requirements.
4. "evidence" must be copied word for word from the document: the sentence or clause that states the \
requirement (at most 300 characters). Do not fix its spelling or wording.
5. Leave out general information, contact details, bid-opening arrangements, grievance committees, and \
the procuring agency's right to reject bids.
6. If the document lists several tenders, use only the requirements that apply to the tender named in \
the user message.
7. If the document states no such requirements, answer {"requirements": []}.
"""

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)*(?::\d+)?")


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER.findall(text)}


def extract_requirements(text_for_model: str, title: str) -> list:
    """Step 2: ask the model for checklist lines, each with a verbatim evidence quote."""
    user_message = (
        f'THIS SPECIFIC TENDER: "{title}"\n\n'
        "List the requirements that apply to this tender only.\n\n"
        f"--- DOCUMENT TEXT ---\n{text_for_model}"
    )
    data = json.loads(_call_llm(REQUIREMENTS_SYSTEM_PROMPT, user_message))
    items = data.get("requirements") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def verify_requirements(items: list, source_text: str) -> tuple[list[dict], int]:
    """Keep only lines the document really supports. A line is dropped when its evidence quote is not
    in the document text, or when it contains a number that does not occur in the document (so a
    calculated or invented figure can never reach the checklist). Returns (kept, number_dropped)."""
    source_compact = _compact(source_text)
    source_numbers = _numbers(source_text)
    kept, dropped, seen = [], 0, set()
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        text = str(item.get("text") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        ev_compact = _compact(evidence)
        ok = (
            6 <= len(text) <= 400
            and len(ev_compact) >= 15
            and ev_compact in source_compact
            and _numbers(text) <= source_numbers
            and text.lower() not in seen
        )
        if ok:
            seen.add(text.lower())
            kept.append({"text": text, "evidence": evidence})
        else:
            dropped += 1
    return kept, dropped


def _attach_requirements(terms: TenderTerms, raw_text: str, text_for_model: str, title: str) -> None:
    """Fills terms.requirement_items. A failure here never breaks the decision: the matching engine
    does not use these lines, so we warn and carry on without them."""
    try:
        candidates = extract_requirements(text_for_model, title)
    except Exception as e:  # noqa: BLE001 - deliberately soft
        print(f"warning: could not build the requirements checklist ({e})", file=sys.stderr)
        return
    kept, dropped = verify_requirements(candidates, raw_text)
    terms.requirement_items = [k["text"] for k in kept]
    for i, k in enumerate(kept):
        terms.source_text_snippets[f"requirement_items[{i}]"] = k["evidence"]
    if dropped:
        print(f"note: {dropped} requirement line(s) were dropped because the document does not support them",
              file=sys.stderr)


def extract_fields_with_llm(raw_text: str, tender_id: str, title: str,
                              organization: str | None = None) -> TenderTerms:
    """Calls an LLM API to extract structured fields from raw tender text.

    Set LLM_PROVIDER to "openai" or "anthropic" (defaults to "openai" since
    that's what most people already have a key for). Needs the matching
    environment variable set:
        OPENAI_API_KEY      (if LLM_PROVIDER=openai)
        ANTHROPIC_API_KEY    (if LLM_PROVIDER=anthropic)
    """
    # Truncate very long documents to keep cost/latency reasonable. Some real
    # PPRA tenders run past 100,000 characters (multi-page bidding documents
    # with boilerplate, annexures, etc.) — a too-small limit here silently
    # cuts off clauses the model never gets a chance to see. gpt-4o-mini
    # comfortably handles far more than this, so err on the generous side.
    truncated = raw_text[:60000]

    # CRITICAL: tell the model which specific tender we care about. Some PPRA
    # notices bundle MANY separate, unrelated tenders into one document (see
    # the "two table patterns" rule above) — without this, the model has no
    # way to know which row/section is actually relevant and may blend data
    # from unrelated tenders together.
    user_message = (
        f"THIS SPECIFIC TENDER: \"{title}\"\n\n"
        f"If the document below lists only ONE tender, extract its fields "
        f"normally. If it lists MULTIPLE separate tenders in a table or "
        f"bulletin, find the ONE row/section whose project name matches "
        f"\"{title}\" above, and extract fields ONLY from that specific "
        f"row/section — ignore all other unrelated tenders in the document.\n\n"
        f"--- DOCUMENT TEXT ---\n{truncated}"
    )

    raw_json = _call_llm(EXTRACTION_SYSTEM_PROMPT, user_message)

    extracted = sanitize_amounts(json.loads(raw_json))

    # Defensive normalization: real documents sometimes write PEC categories
    # with zero-padding (e.g. "C-05", "C-01") while our schema only accepts
    # the unpadded form ("C-5", "C-1"). Fix this here so a formatting quirk
    # in the source document never crashes the whole extraction with an
    # unhandled Pydantic validation error.
    cat = extracted.get("pec_category_required")
    if cat and isinstance(cat, str):
        import re
        m = re.match(r"^C-0*(\d+|A)$", cat.strip().upper())
        if m:
            extracted["pec_category_required"] = f"C-{m.group(1)}"

    # organization / project_title come from the model but are not part of
    # the matching fields — pull them out so they don't collide with the
    # explicit arguments below. Caller-supplied values always win.
    docs = extracted.get("required_documents")
    if not isinstance(docs, list):
        docs = []
    extracted["required_documents"] = [str(d).strip() for d in docs if str(d).strip()]
    for code_field in ("pec_specialization_code", "addressee"):
        if extracted.get(code_field) is not None:
            extracted[code_field] = str(extracted[code_field]).strip() or None

    extracted_org = extracted.pop("organization", None)
    extracted_title = extracted.pop("project_title", None)
    organization = organization or extracted_org
    if (not title or title.lower().endswith(".pdf")) and extracted_title:
        title = extracted_title

    try:
        terms = TenderTerms(
            tender_id=tender_id,
            title=title,
            organization=organization,
            **extracted,
        )
    except Exception as e:
        raise RuntimeError(
            f"The AI's extracted data didn't match our expected format "
            f"(this usually means an unexpected value for one field, e.g. "
            f"an unrecognized category code). Raw extracted data was:\n"
            f"{json.dumps(extracted, indent=2)}\n\nOriginal error: {e}"
        ) from e

    _attach_requirements(terms, raw_text, truncated, title)
    return terms


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