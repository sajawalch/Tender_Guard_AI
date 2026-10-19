"""
TenderGuard AI — real-tender extraction accuracy test.

Same idea as run_accuracy_test.py, but for your 10 real PPRA PDFs instead
of the synthetic tenders. Looks for a PDF per tender_id inside tenders/,
extracts it, and scores ONLY the fields you've actually confirmed by hand
in ground_truth_tenders.json (anything still listed in a tender's
"needs_pdf_review" is skipped, not scored as wrong — you haven't told the
script the right answer for that field yet).

Usage:
    python run_real_tenders_test.py                 # all tenders with a PDF present
    python run_real_tenders_test.py TS0000016176E    # just one, for quick debugging
"""

import json
import sys
from pathlib import Path

from extract_tender import extract_text_from_document, extract_fields_with_llm

TENDERS_DIR = Path("tenders")
GROUND_TRUTH_PATH = "ground_truth_tenders.json"

SCORED_FIELDS = [
    "contract_value_pkr", "bid_security_amount_pkr", "bid_security_percent",
    "liquidated_damages_rate_percent_per_day", "liquidated_damages_cap_percent",
    "advance_payment_percent", "payment_cycle_days", "pec_category_required",
    "requires_active_taxpayer_status", "min_years_experience_required",
    "completion_period_days",
]


def load_ground_truth() -> dict[str, dict]:
    with open(GROUND_TRUTH_PATH) as f:
        raw = json.load(f)
    return {item["tender_id"]: item for item in raw}


def values_match(expected, actual, tolerance=0.01) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if expected == 0:
            return abs(actual) < tolerance
        return abs(expected - actual) / abs(expected) < tolerance
    return str(expected).strip().upper() == str(actual).strip().upper()


def find_pdf_for_tender(tender_id: str) -> Path | None:
    candidate = TENDERS_DIR / f"{tender_id}.pdf"
    return candidate if candidate.exists() else None


def main():
    if not TENDERS_DIR.exists():
        print(f"ERROR: '{TENDERS_DIR}/' folder not found. Create it and put your "
              f"downloaded PDFs inside, named exactly like <tender_id>.pdf "
              f"(e.g. TS0000016176E.pdf).")
        sys.exit(1)

    ground_truth = load_ground_truth()

    only_id = sys.argv[1] if len(sys.argv) > 1 else None
    tender_ids = [only_id] if only_id else sorted(ground_truth.keys())

    total_correct = 0
    total_checked = 0
    tested_count = 0
    skipped_no_pdf = []

    for tender_id in tender_ids:
        truth = ground_truth.get(tender_id)
        if truth is None:
            print(f"Skipping {tender_id}: not found in {GROUND_TRUTH_PATH}")
            continue

        pdf_path = find_pdf_for_tender(tender_id)
        if pdf_path is None:
            skipped_no_pdf.append(tender_id)
            continue

        needs_review = set(truth.get("needs_pdf_review", []))
        # A field is scoreable only if it's NOT still pending manual review.
        scoreable_fields = [f for f in SCORED_FIELDS if f not in needs_review]

        if not scoreable_fields:
            print(f"Skipping {tender_id}: every field still marked needs_pdf_review "
                  f"— fill in ground_truth_tenders.json by hand first.")
            continue

        print(f"Extracting {tender_id} ({truth['title'][:50]}...)")
        text = extract_text_from_document(str(pdf_path))
        print(f"  ({len(text)} characters of text extracted from PDF)")

        try:
            extracted = extract_fields_with_llm(
                text, tender_id=tender_id, title=truth["title"],
                organization=truth.get("organization"),
            )
        except Exception as e:
            print(f"  ERROR extracting {tender_id}: {e}\n")
            continue

        extracted_dict = extracted.model_dump(mode="json")
        tender_correct = 0
        mismatches = []

        for field in scoreable_fields:
            expected = truth.get(field)
            actual = extracted_dict.get(field)
            total_checked += 1
            if values_match(expected, actual):
                total_correct += 1
                tender_correct += 1
            else:
                mismatches.append(f"{field}: expected={expected!r} got={actual!r}")

        tested_count += 1
        print(f"  Score: {tender_correct}/{len(scoreable_fields)} scoreable fields "
              f"({tender_correct/len(scoreable_fields):.0%}) "
              f"[{len(needs_review)} fields skipped — not yet confirmed by hand]")
        for m in mismatches:
            print(f"    MISMATCH -> {m}")
        print()

    if skipped_no_pdf:
        print(f"Skipped {len(skipped_no_pdf)} tender(s) with no PDF found in "
              f"tenders/: {', '.join(skipped_no_pdf)}\n")

    print("=" * 60)
    if total_checked:
        print(f"REAL-TENDER ACCURACY: {total_correct}/{total_checked} scoreable "
              f"fields correct ({total_correct/total_checked:.1%}) "
              f"across {tested_count} tender(s)")
    else:
        print("No scoreable fields found across any tested tenders — make sure "
              "you've filled in ground_truth_tenders.json by hand first.")
    print("=" * 60)


if __name__ == "__main__":
    main()