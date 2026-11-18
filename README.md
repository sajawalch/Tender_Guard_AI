# TenderGuard AI

A bid / no-bid screening tool for small and mid-sized **Pakistani construction contractors**.

A contractor saves their own limits once (PEC licence category, contract-value range, the most bid
security they can afford, tax status, penalty tolerance, ...). They then upload a tender PDF and get
**Select, Reject or Insufficient data, with a reason for every check**, a note on how much could be
checked, a deadline warning, and an optional **draft bid document** (.docx) to complete.

It does one decision reliably and transparently. It is not a general tender summariser.

## How it works

```
tender PDF -> read text (PyMuPDF -> pdfplumber -> OCR fallback)
           -> LLM step 1: extract the tender's terms into a fixed schema (literal, temperature 0)
           -> LLM step 2: list the bidder's requirements, each with a quote from the document
contractor limits + tender terms -> matching_engine.match()  (plain Python rules, no LLM)
                                 -> Select / Reject / Insufficient data + reasons
                                 -> draft bid .docx
```

The language model only **reads documents**. It never makes the decision.

- A check runs only when **both** the tender and the contractor's profile give a value. Otherwise it
  is skipped and listed in the coverage note ("5 of 8 criteria checked"). A skipped check never rejects.
- **Reject** = any check failed. **Select** = at least one check ran and none failed.
  **Insufficient data** = no check could run, so nothing was compared. It is neither approved nor rejected.
- A value the document does not state is `null`, never guessed. A bid security given only as a percentage is
  worked out by the matcher from the contract value; the extractor never calculates it.
- The 8 checks: contract value, PEC category, bid security, liquidated damages, advance payment,
  active taxpayer status, experience, completion period.

## Known limits (read this before relying on a result)

**The requirements checklist is made by AI and is not guaranteed complete.**
It can differ from one run to the next, and it does not catch every condition of a tender. Each line is
checked against the document (the quote must occur in the text and every number must occur in the text),
which stops invented lines, but **it cannot detect a line that was left out**. In testing, a run once
produced a bid-security line without the bank and the validity period that the notice states. The backend
prints a note when clauses with an obligation are not cited by any line, but the only safe rule is:
**always read the notice's own clauses.** Figures that appear only in the notice's table (for example the
turnover amount) may be missing from the checklist.

Other limits:

- **No financial eligibility checks yet.** Turnover, liquid cash and the value of past contracts are not
  compared, so a **Select** can still fail on them.
- **The decision is only as good as the extraction.** On real tenders, extraction is weaker than on
  synthetic ones (see Accuracy), especially for scanned pages, very long documents and tables with several lots.
- Documents longer than 60,000 characters are cut before they reach the model. The result screen warns when this happens.
- **The draft bid is a draft.** It is a generic bid letter, not the official format of a particular bidding
  document. Prices, certificates and the bid security are always the contractor's own job, and the
  declaration must only be signed after the contractor has checked every requirement.
- Results are kept in memory only (lost when the server restarts). There is no database and no login.
- The tender text is sent to OpenAI for extraction. Do not upload documents you are not allowed to share.
- This is a screening aid, not legal or financial advice.

## Accuracy

Measured with `accuracy.py` on the current extraction code. Both sets are reported separately on purpose, and
failed extractions are counted, not hidden.

| Set | Result |
|---|---|
| Synthetic tenders (15 written tenders, every field has a known answer) | 163 of 165 fields (98.8%) |
| Real PPRA tenders (7 tenders, hand-confirmed fields only) | 8 of 14 fields (57.1%) |

How to read these numbers:

- **The real-tender figure rests on only 14 fields**, because most fields of the real tenders have not been confirmed
  by hand (they are skipped, never counted as right or wrong). One field moves the figure by about 7 points. Read it as
  "extraction on real tenders is clearly weaker than on clean written ones", not as a precise rate.
- Only the **structured fields** the matching engine compares are scored. The requirements checklist lines and the
  turnover figure are **not** scored, and the checklist is not guaranteed complete (see Known limits).
- Real tenders are harder: scanned pages, very long documents, notices that bundle several tenders, and tables where a
  bid-security figure can be mistaken for the contract value.

The matching engine and the bid-document builder are tested separately and offline (see Tests).

## Setup (Windows PowerShell)

```powershell
conda activate tenderguard
pip install -r requirements.txt
$env:OPENAI_API_KEY="your_key"        # never put a key in code, in .env that is committed, or in a zip
```

Scanned PDFs need Tesseract OCR installed separately (a Windows installer).

Run the web app (two terminals):

```powershell
# terminal 1, project folder
uvicorn api_server:app --reload

# terminal 2
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, set your criteria, upload a tender, read the result.

Command-line tools:

```powershell
python tender_decision.py tenders\TS0000016176E.pdf "Sindh Horizon Builders"   # decision only
python generate_bid.py tenders\TS0000016176E.pdf "Sindh Horizon Builders"       # draft bid .docx
python run_end_to_end.py tenders\TS0000016176E.pdf --firm "Sindh Horizon Builders"   # whole web flow, no browser
python diagnose_checklist.py tenders\TS0000016176E.pdf "Project title"          # why the checklist looks as it does
python check_all_tenders.py --firm "Your Firm"                                    # every tender in tenders\ against one firm
python check_connection.py                                                        # diagnose the OpenAI connection
```

## Try it without a real PDF

`demo_tenders\` holds short written tenders and `DEMO.md` lists which firm to use with which one, and the result to expect.

## Tests

All tests run offline: no internet, no API key, no real PDFs.

```powershell
pip install pytest httpx
python -m pytest
```

GitHub Actions runs the same tests (and builds the frontend) on every push; see `.github/workflows/tests.yml`.

They cover the matching engine (every check, boundaries, skip rules, the three outcomes), the schema and
deadline logic, extraction post-processing with a fake model, the checklist and the draft document, the
result cache and the API.

## Files

| File | Purpose |
|---|---|
| `schema.py` | `TenderTerms`, `ContractorCriteria`, `MatchDecision`, PEC category ranking |
| `matching_engine.py` | The 8 rule checks and `match()`. No LLM here, by design |
| `extract_tender.py` | PDF / OCR reading, the extraction prompts, checks on the model's answers |
| `generate_bid_document.py` | Builds the draft .docx (cover page, letter, summary, price schedule, checklist, declaration) |
| `bid_service.py` | In-memory result cache and .docx building for the web app |
| `api_server.py` | FastAPI backend: contractors, decide, generate-bid |
| `frontend/` | React 18 + Vite web app |
| `contractor_profiles.json` | Firm profiles (8 fictional demo firms plus any you create) |
| `ground_truth_tenders.json`, `synthetic_*` | Answers used to measure extraction accuracy |
| `tests/` | The pytest suite |
| `demo_tenders/`, `DEMO.md` | Written tenders and a script for a 5-minute demo |
| `.github/workflows/tests.yml` | Runs the tests on every push |

## Rules this project keeps

- Matching stays deterministic: no LLM calls inside `matching_engine.py` (a test enforces this).
- Extraction stays literal: if the document does not state it, it is `null`.
- Amounts are full rupees. Impossible values (under PKR 1,000) become `null`.
- Accuracy is reported honestly, synthetic and real separately.