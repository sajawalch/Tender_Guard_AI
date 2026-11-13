"""
TenderGuard AI — accuracy measurement.

One command that measures how well the extraction pipeline reads tenders:

  1. SYNTHETIC set  - the 15 tenders in synthetic_tenders.md, scored against
                      synthetic_ground_truth.json (every field has a known answer).
  2. REAL set       - the PDFs in tenders/, scored against ground_truth_tenders.json.
                      Only fields you have confirmed by hand are scored: anything
                      still listed under "needs_pdf_review" is skipped, never
                      counted as right or wrong.

It prints the results and saves accuracy_report.md and accuracy_results.json,
so the numbers in your README come from a real run and not from memory.

Usage:
    python measure_accuracy.py                 # both sets
    python measure_accuracy.py --synthetic     # synthetic only
    python measure_accuracy.py --real          # real only
    python measure_accuracy.py --limit 3       # first 3 synthetic tenders (cheap test run)
    python measure_accuracy.py --verbose       # also show EVERY field: expected vs got
                                               # (by default only the wrong ones are listed)

Needs your API key set in the terminal, e.g.  $env:OPENAI_API_KEY="..."
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from extract_tender import extract_text_from_document, extract_fields_with_llm

SYNTH_MD = "synthetic_tenders.md"
SYNTH_TRUTH = "synthetic_ground_truth.json"
REAL_TRUTH = "ground_truth_tenders.json"
TENDERS_DIR = Path("tenders")

SCORED_FIELDS = [
    "contract_value_pkr", "bid_security_amount_pkr", "bid_security_percent",
    "liquidated_damages_rate_percent_per_day", "liquidated_damages_cap_percent",
    "advance_payment_percent", "payment_cycle_days", "pec_category_required",
    "requires_active_taxpayer_status", "min_years_experience_required",
    "completion_period_days",
]


# ------------------------------------------------------------------ helpers
def values_match(expected, actual, tolerance=0.01) -> bool:
    """Numbers match within 1% (rounding); everything else must match exactly.
    None matches None: correctly leaving a field empty counts as correct."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return bool(expected) == bool(actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if expected == 0:
            return abs(actual) < tolerance
        return abs(expected - actual) / abs(expected) < tolerance
    return str(expected).strip().upper() == str(actual).strip().upper()


def to_dict(obj) -> dict:
    """Plain dict with enums turned into their string values (e.g. 'C-4')."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return dict(vars(obj))


def split_synthetic(md_path: str) -> dict[str, str]:
    """{tender_id: text} from synthetic_tenders.md. The file is divided by
    '## ST-01' style headings; the real ID is the 'Tender No:' line inside."""
    content = Path(md_path).read_text(encoding="utf-8")
    tenders = {}
    for block in re.split(r"\n## ST-\d{2}\n", content)[1:]:
        m = re.search(r"\*\*Tender No:\*\*\s*(ST-\d{4}-\d{3})", block)
        if m:
            tenders[m.group(1)] = block.strip()
    return tenders


def new_result(name: str) -> dict:
    return {
        "name": name, "tenders_tested": 0, "fields_correct": 0, "fields_total": 0,
        "per_field": {f: [0, 0] for f in SCORED_FIELDS},
        "mismatches": [], "errors": [], "skipped": [], "comparisons": [],
    }


def score_tender(result: dict, tender_id: str, truth: dict, extracted: dict, fields: list[str]):
    correct = 0
    for field in fields:
        expected, actual = truth.get(field), extracted.get(field)
        result["per_field"][field][1] += 1
        result["fields_total"] += 1
        ok = values_match(expected, actual)
        result["comparisons"].append((tender_id, field, expected, actual, ok))
        if ok:
            result["per_field"][field][0] += 1
            result["fields_correct"] += 1
            correct += 1
        else:
            result["mismatches"].append((tender_id, field, expected, actual))
    result["tenders_tested"] += 1
    return correct, len(fields)


# ------------------------------------------------------------------ the two runs
def run_synthetic(limit=None) -> dict:
    result = new_result("Synthetic (15 written tenders)")
    texts = split_synthetic(SYNTH_MD)
    truth_all = {t["tender_id"]: t for t in json.load(open(SYNTH_TRUTH, encoding="utf-8"))}
    ids = sorted(texts)[:limit] if limit else sorted(texts)

    print(f"\n=== SYNTHETIC: {len(ids)} tenders ===")
    for i, tid in enumerate(ids, 1):
        truth = truth_all[tid]
        try:
            extracted = to_dict(extract_fields_with_llm(
                texts[tid], tender_id=tid, title=truth["title"],
                organization=truth.get("organization")))
        except Exception as e:
            result["errors"].append((tid, str(e).splitlines()[0]))
            print(f"[{i}/{len(ids)}] {tid}  ERROR: {str(e).splitlines()[0]}")
            continue
        c, t = score_tender(result, tid, truth, extracted, SCORED_FIELDS)
        print(f"[{i}/{len(ids)}] {tid}  {c}/{t}")
    return result


def run_real() -> dict:
    result = new_result("Real PPRA tenders (confirmed fields only)")
    if not TENDERS_DIR.exists():
        print(f"\n=== REAL: skipped — no '{TENDERS_DIR}/' folder ===")
        result["skipped"].append(("(all)", f"no {TENDERS_DIR}/ folder"))
        return result

    truth_all = json.load(open(REAL_TRUTH, encoding="utf-8"))
    print(f"\n=== REAL: up to {len(truth_all)} tenders ===")
    for truth in truth_all:
        tid = truth["tender_id"]
        pdf = TENDERS_DIR / f"{tid}.pdf"
        pending = set(truth.get("needs_pdf_review", []))
        fields = [f for f in SCORED_FIELDS if f not in pending]

        if not pdf.exists():
            result["skipped"].append((tid, "PDF not found"))
            print(f"{tid}  skipped (no PDF in {TENDERS_DIR}/)")
            continue
        if not fields:
            result["skipped"].append((tid, "no confirmed fields yet"))
            print(f"{tid}  skipped (no fields confirmed by hand yet)")
            continue
        try:
            text = extract_text_from_document(str(pdf))
            extracted = to_dict(extract_fields_with_llm(
                text, tender_id=tid, title=truth["title"],
                organization=truth.get("organization")))
        except Exception as e:
            result["errors"].append((tid, str(e).splitlines()[0]))
            print(f"{tid}  ERROR: {str(e).splitlines()[0]}")
            continue
        c, t = score_tender(result, tid, truth, extracted, fields)
        print(f"{tid}  {c}/{t} confirmed fields")
    return result


# ------------------------------------------------------------------ reporting
def pct(c, t):
    return f"{c / t:.1%}" if t else "n/a"


def print_summary(result: dict):
    print(f"\n--- {result['name']} ---")
    print(f"Tenders scored : {result['tenders_tested']}")
    print(f"Fields correct : {result['fields_correct']}/{result['fields_total']} "
          f"({pct(result['fields_correct'], result['fields_total'])})")
    if result["errors"]:
        print(f"Errors         : {len(result['errors'])} tender(s) failed to extract")
    if result["mismatches"]:
        print("Mismatches:")
        for tid, field, exp, got in result["mismatches"]:
            print(f"  {tid}  {field}: expected={exp!r} got={got!r}")


def print_all_comparisons(result: dict):
    """Every scored field, right and wrong, grouped by tender."""
    print(f"\n--- ALL COMPARISONS: {result['name']} ---")
    current = None
    for tid, field, expected, actual, ok in result["comparisons"]:
        if tid != current:
            print(f"\n{tid}")
            current = tid
        print(f"  {'OK   ' if ok else 'WRONG'} {field}: expected={expected!r}  got={actual!r}")


def markdown_section(result: dict) -> str:
    lines = [f"## {result['name']}", ""]
    lines.append(f"- Tenders scored: **{result['tenders_tested']}**")
    lines.append(f"- Fields correct: **{result['fields_correct']}/{result['fields_total']} "
                 f"({pct(result['fields_correct'], result['fields_total'])})**")
    if result["errors"]:
        lines.append(f"- Tenders that failed to extract: {len(result['errors'])}")
    if result["skipped"]:
        lines.append(f"- Skipped: {len(result['skipped'])} "
                     f"({', '.join(t for t, _ in result['skipped'][:6])}"
                     f"{'...' if len(result['skipped']) > 6 else ''})")
    lines += ["", "| Field | Correct | Accuracy |", "|---|---|---|"]
    for field, (c, t) in result["per_field"].items():
        if t:
            lines.append(f"| {field} | {c}/{t} | {pct(c, t)} |")
    if result["mismatches"]:
        lines += ["", "**Mismatches**", ""]
        for tid, field, exp, got in result["mismatches"]:
            lines.append(f"- `{tid}` `{field}`: expected `{exp}`, got `{got}`")
    lines.append("")
    return "\n".join(lines)


def save_reports(results: list[dict]):
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    model = "claude-sonnet-4-6" if provider == "anthropic" else "gpt-4o-mini"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    md = [f"# TenderGuard AI — Accuracy Report", "",
          f"Measured on {stamp} with `{model}` (temperature 0).", ""]
    for r in results:
        md.append(markdown_section(r))
    md += [
        "## How to read these numbers", "",
        "- **Synthetic**: tenders written for testing, so every field has a known correct "
        "answer. It shows the pipeline logic works on clean documents.",
        "- **Real**: actual PPRA PDFs. Only fields confirmed by hand are scored, so the sample "
        "is small and the result is lower than the synthetic one. Scanned PDFs, multi-tender "
        "bulletins and tables are the hard cases.",
        "- A field correctly left empty (the tender does not state it) counts as correct.",
    ]
    Path("accuracy_report.md").write_text("\n".join(md), encoding="utf-8")
    Path("accuracy_results.json").write_text(
        json.dumps({"measured_at": stamp, "model": model, "results": results},
                   indent=2, default=str), encoding="utf-8")


def main():
    args = sys.argv[1:]
    only_synth, only_real = "--synthetic" in args, "--real" in args
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])

    results = []
    if not only_real:
        results.append(run_synthetic(limit))
    if not only_synth:
        results.append(run_real())

    for r in results:
        if "--verbose" in args:
            print_all_comparisons(r)
        print_summary(r)
    save_reports(results)

    print("\n" + "=" * 60)
    print("README line:")
    parts = []
    for r in results:
        if r["fields_total"]:
            parts.append(f"{r['name'].split(' (')[0]}: {r['fields_correct']}/{r['fields_total']} "
                         f"fields ({pct(r['fields_correct'], r['fields_total'])}) "
                         f"across {r['tenders_tested']} tenders"
                         + (f" ({len(r['errors'])} failed to extract and are NOT counted)"
                            if r["errors"] else ""))
    print("  " + "  |  ".join(parts) if parts else "  (nothing was scored)")
    print("Saved: accuracy_report.md, accuracy_results.json")


if __name__ == "__main__":
    main()