"""
TenderGuard AI - end-to-end check of the whole web flow, without a browser.

It talks to the RUNNING backend exactly like the React app does:

    1. list firms            GET  /api/contractors
    2. save criteria         POST /api/contractors   (invalid data is refused,
                                                      valid data is accepted)
    3. check a tender        POST /api/decide        (real PDF, real OpenAI call)
    4. draft bid document    POST /api/generate-bid  (downloads a .docx)
    5. open the .docx        python-docx             (valid Word file? firm name inside?)
    6. error handling        unknown result id -> 404, Reject without force -> 409

Run (backend must already be running in another terminal, with OPENAI_API_KEY set there):

    python run_end_to_end.py tenders\\TS0000016176E.pdf
    python run_end_to_end.py tenders\\TS0000016176E.pdf --firm "Sindh Horizon Builders"
    python run_end_to_end.py tenders\\TS0000016176E.pdf --base http://localhost:5173   (also tests the Vite proxy)

Step 3 uses your OpenAI key (a few cents at most). Step 2 re-saves the chosen firm
with its own unchanged values, so contractor_profiles.json is rewritten but not changed in content.
"""

import argparse
import sys
import time
import zipfile
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("httpx is missing. Install it with:  pip install httpx")

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -  {detail}" if detail else ""))
    return ok


def error_detail(r: httpx.Response) -> str:
    """Server's error message for a failed request. Empty for success, because a
    successful response can be a binary .docx that must never be printed."""
    if r.status_code < 400:
        return ""
    try:
        return str(r.json().get("detail", r.text))[:200]
    except Exception:
        return r.text[:200]


def check_docx(path: Path, firm_name: str) -> None:
    """Is the downloaded file a real Word file, and does it mention the firm?"""
    if not zipfile.is_zipfile(path):
        record("Downloaded file is a valid .docx (zip) file", False, "not a zip archive")
        return
    try:
        from docx import Document
    except ImportError:
        record("python-docx installed", False, "run: pip install python-docx")
        return
    try:
        doc = Document(str(path))
    except Exception as e:
        record("Word file opens", False, str(e))
        return
    texts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            texts.extend(cell.text for cell in row.cells)
    blob = "\n".join(texts)
    record("Word file opens", True, f"{len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables")
    record("Draft names your firm", firm_name.lower() in blob.lower())
    record("Draft is not empty", len(blob.strip()) > 300, f"{len(blob)} characters")


def main() -> int:
    ap = argparse.ArgumentParser(description="End-to-end test of the TenderGuard web flow")
    ap.add_argument("pdf", help="path to a tender PDF")
    ap.add_argument("--firm", help="firm name (default: your own firm, else the first one)")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="backend (or Vite) address")
    ap.add_argument("--out", default="e2e_output", help="folder for the downloaded .docx")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.is_file():
        return print(f"PDF not found: {pdf}") or 2

    client = httpx.Client(base_url=args.base, timeout=httpx.Timeout(600.0, connect=5.0))

    # ---------- 1. firms ----------
    print("\n1. Firms")
    try:
        r = client.get("/api/contractors")
    except httpx.HTTPError as e:
        print(f"  Cannot reach {args.base}: {e}\n  Start the backend first:  uvicorn api_server:app --reload")
        return 2
    if not record("GET /api/contractors answers 200", r.status_code == 200, error_detail(r)):
        return 1
    firms = r.json()
    record("At least one firm exists", len(firms) > 0, f"{len(firms)} firms")
    if not firms:
        return 1
    if args.firm:
        firm = next((f for f in firms if f["name"].lower() == args.firm.lower()), None)
        if firm is None:
            print(f"  Firm '{args.firm}' not found. Available: {[f['name'] for f in firms]}")
            return 2
    else:
        firm = next((f for f in firms if f.get("mine")), firms[0])
    print(f"  Using firm: {firm['name']} (PEC {firm['pec_category']})")

    # ---------- 2. criteria ----------
    print("\n2. Save criteria")
    bad = dict(firm["profile"], min_contract_value_pkr=900_000_000, max_contract_value_pkr=1_000)
    r = client.post("/api/contractors", json={"original_name": firm["name"], "profile": bad})
    record("Impossible limits (min > max) are refused with 422", r.status_code == 422, error_detail(r))
    r = client.post("/api/contractors", json={"original_name": firm["name"], "profile": firm["profile"]})
    record("Valid criteria are saved", r.status_code == 200, error_detail(r))

    # ---------- 3. decision ----------
    print("\n3. Check the tender (reads the PDF, calls OpenAI; scanned PDFs can take minutes)")
    start = time.time()
    with pdf.open("rb") as f:
        r = client.post(
            "/api/decide",
            files={"file": (pdf.name, f, "application/pdf")},
            data={"contractor_name": firm["name"], "title": ""},
        )
    took = time.time() - start
    if not record("POST /api/decide answers 200", r.status_code == 200,
                  f"{took:.0f}s " + error_detail(r)):
        print("  Common causes: OPENAI_API_KEY not set in the backend terminal, Tesseract missing for a scanned PDF.")
        return 1
    d = r.json()
    needed = {"result_id", "decision", "criteria_checked", "criteria_total", "results", "extracted_fields"}
    record("Response has every field the UI needs", needed <= d.keys(), f"missing: {needed - d.keys() or 'none'}")
    record("Decision is Select or Reject", d["decision"] in ("Select", "Reject"), d["decision"])
    record("Checks are consistent",
           d["criteria_checked"] == len(d["results"]) and d["criteria_checked"] <= d["criteria_total"],
           f"{d['criteria_checked']} of {d['criteria_total']} run")
    print(f"\n  Tender : {d['tender_title'][:90]}")
    print(f"  Result : {d['decision']}  ({d['criteria_checked']} of {d['criteria_total']} checks)")
    for c in d["results"]:
        print(f"    {'PASS' if c['passed'] else 'FAIL'}  {c['criterion']}: {c['reason']}")
    if d["skipped_criteria"]:
        print(f"    not checked: {', '.join(d['skipped_criteria'])}")
    if d["deadline_warning"]:
        print(f"  Deadline: {d['deadline_warning']}")
    if d["low_confidence"]:
        print("  Low confidence: fewer than half of the checks could run.")
    print()

    # ---------- 4 + 5. bid document ----------
    print("4. Draft bid document")
    is_reject = d["decision"] == "Reject"
    if is_reject:
        r = client.post("/api/generate-bid", json={"result_id": d["result_id"], "force": False})
        record("Reject without force is refused with 409", r.status_code == 409, error_detail(r))
    r = client.post("/api/generate-bid", json={"result_id": d["result_id"], "force": is_reject})
    if record("POST /api/generate-bid answers 200", r.status_code == 200, error_detail(r)):
        record("Content type is Word",
               "wordprocessingml" in r.headers.get("content-type", ""), r.headers.get("content-type", ""))
        out_dir = Path(args.out)
        out_dir.mkdir(exist_ok=True)
        # A time stamp keeps every run in its own file, so an older copy that is
        # still open in Word (Windows locks open files) can never block a new run.
        out = out_dir / f"{pdf.stem}_{firm['name'].split()[0]}_{time.strftime('%H%M%S')}.docx"
        try:
            out.write_bytes(r.content)
        except OSError as e:
            record("Downloaded file can be saved", False,
                   f"{e}. Close the file in Word, or use --out with another folder.")
        else:
            print(f"  Saved: {out.resolve()}")
            print("\n5. Open the .docx")
            check_docx(out, firm["name"])

    # ---------- 6. errors ----------
    print("\n6. Error handling")
    r = client.post("/api/generate-bid", json={"result_id": "does-not-exist", "force": True})
    record("Unknown result id answers 404", r.status_code == 404, error_detail(r))
    r = client.post("/api/decide", files={"file": ("notes.exe", b"x", "application/octet-stream")},
                    data={"contractor_name": firm["name"]})
    record("Wrong file type answers 415", r.status_code == 415, error_detail(r))

    # ---------- summary ----------
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'=' * 50}\n{len(results) - len(failed)} of {len(results)} checks passed")
    for n in failed:
        print(f"  FAILED: {n}")
    print("\nStill to do by hand: open the .docx in Word and read it. These checks prove the file is valid,\n"
          "not that the content is good.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
    