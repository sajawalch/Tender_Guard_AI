# TenderGuard AI — Starter Kit

This is the working skeleton for Weeks 1–3 of your build. It's not a finished
app — it's the schema, logic, and sample data that everything else gets built
on top of, already wired together and sanity-checked.

## What's in here

| File | What it is | Status |
|---|---|---|
| `schema.py` | Pydantic models: `TenderTerms`, `ContractorCriteria`, `MatchDecision` | **Done** — defines every field your system works with |
| `matching_engine.py` | Rule-based Select/Reject logic | **Done** — 8 criteria checks, deterministic, with a built-in smoke test |
| `contractor_profiles.json` | 8 fictional contractor profiles | **Done** — spans C-6 to C-1 PEC categories, different risk appetites |
| `ground_truth_tenders.json` | Your 10 real PPRA tenders, pre-filled with confirmed data | **Partial** — see "What you still need to do" below |
| `extract_tender.py` | PDF-to-text + LLM extraction pipeline | **Done, untested** — needs your API key and real PDFs to run |

## What you still need to do

**1. Download the actual 10 PDFs.**
I could only read PPRA's *summary* pages for your tenders (organization, bid
security where stated, closing dates) — not the full document text inside
each PDF, since I have no way to save binary files in this environment. Use
the links from your `PPRA_Construction_Tenders_Batch1.md` file to download
all 10 PDFs into a local `tenders/` folder.

**2. Fill in the missing ground-truth fields, by hand, from the real PDFs.**
Open each PDF and manually find: contract value, PEC category required,
liquidated damages rate, advance payment %, completion period. Fill these
into `ground_truth_tenders.json` wherever you see `null` and a
`needs_pdf_review` list. **This step cannot be skipped or automated** — it's
what lets you later measure your extraction accuracy honestly, by comparing
the LLM's output against what you know is actually correct.

One tender (`TS0000015708E`) already has confirmed data —
`requires_active_taxpayer_status: true` — straight from PPRA's own summary
text, so you have at least one fully-anchored example to start with.

**3. Install dependencies locally (this sandbox has no internet access).**
```bash
pip install pymupdf pdfplumber pydantic openai
```
(If you'd rather use Claude instead of ChatGPT, install `anthropic` instead of
`openai`, and set `LLM_PROVIDER=anthropic` — see step 4.)

**4. Set your API key and test the extraction pipeline.**
Using your existing OpenAI/ChatGPT key (default, no extra setup needed):
```bash
export OPENAI_API_KEY=your_key_here
python extract_tender.py sample_tender_ST-2026-001.txt ST-2026-001 "Construction of Staff Residential Quarters"
```
Or, if you switch to an Anthropic key later:
```bash
export ANTHROPIC_API_KEY=your_key_here
export LLM_PROVIDER=anthropic
python extract_tender.py sample_tender_ST-2026-001.txt ST-2026-001 "Construction of Staff Residential Quarters"
```
Once that works on the sample `.txt` file, move on to a real PDF:
```bash
python extract_tender.py tenders/TS0000016176E.pdf TS0000016176E "Construction of 06 No. Cat-IV Flats"
```
Compare its output field-by-field against what you filled into
`ground_truth_tenders.json` for that tender.

**5. Run the matching engine smoke test.**
```bash
python matching_engine.py
```
This runs against hardcoded dummy data to confirm the logic itself works —
you should see a `Decision: Select` or `Decision: Reject` with reasons
printed. Once step 2 is done, swap the dummy data for your real ground truth.

## A note on honesty in what's pre-filled

Every field in `ground_truth_tenders.json` that I populated is something I
actually confirmed from PPRA's website (bid security amounts, organizations,
closing dates, and the one explicit PEC/FBR requirement). Every field marked
`null` with a `needs_pdf_review` tag is something I do **not** have — I did
not fabricate contract values, LD rates, or PEC categories for fields the
summary pages didn't show. Trust the `null`s; they're accurate, not missing
laziness.

## Suggested order to keep building

1. Finish step 1–2 above (download PDFs, fill ground truth) — do this before
   writing more code.
2. Get `extract_tender.py` working end-to-end on 2–3 real tenders, compare to
   ground truth, fix the prompt if accuracy is poor.
3. Once extraction is solid, run it across all 10 + your synthetic tenders,
   and start building the Streamlit interface around `schema.py` and
   `matching_engine.py` — both are already interface-agnostic, so the web
   app just becomes a thin layer on top of what's here.