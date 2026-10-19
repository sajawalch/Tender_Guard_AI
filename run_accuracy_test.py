"""
TenderGuard AI — full extraction accuracy test.

Splits synthetic_tenders.md into its 15 individual tender texts, runs your
LLM extraction on every one, compares every field against
synthetic_ground_truth.json, and prints a real, measured accuracy
percentage — the number that goes in your README / CV / presentation.

Usage:
    python run_accuracy_test.py            # runs all 15
    python run_accuracy_test.py 3          # runs only the first 3 (quick/cheap test)
"""

import json
import re
import sys
from schema import TenderTerms
from extract_tender import extract_fields_with_llm


def split_synthetic_tenders(md_path: str = "synthetic_tenders.md") -> dict[str, str]:
    """Splits the markdown file into {tender_id: full_text_block}.

    The file uses short '## ST-01'..'## ST-15' section headers as dividers,
    but the real tender ID used everywhere else (ground truth, schema) is
    the 'Tender No: ST-2026-XXX' line inside each block — so we split on
    the section headers, then pull the real ID out of each block's text."""
    content = open(md_path, encoding="utf-8").read()
    # Split on section headers like "## ST-01", keeping the blocks between them
    raw_blocks = re.split(r"\n## ST-\d{2}\n", content)
    tenders = {}
    for block in raw_blocks[1:]:  # raw_blocks[0] is the file intro — discard
        block = block.strip()
        match = re.search(r"\*\*Tender No:\*\*\s*(ST-\d{4}-\d{3})", block)
        if match:
            tender_id = match.group(1)
            tenders[tender_id] = block
    return tenders


def load_ground_truth(path: str = "synthetic_ground_truth.json") -> dict[str, dict]:
    with open(path) as f:
        raw = json.load(f)
    return {item["tender_id"]: item for item in raw}


# Fields we actually score (skip tender_id/title/organization/source_text_snippets —
# those aren't "extraction correctness" in the same sense)
SCORED_FIELDS = [
    "contract_value_pkr", "bid_security_amount_pkr", "bid_security_percent",
    "liquidated_damages_rate_percent_per_day", "liquidated_damages_cap_percent",
    "advance_payment_percent", "payment_cycle_days", "pec_category_required",
    "requires_active_taxpayer_status", "min_years_experience_required",
    "completion_period_days",
]


def values_match(expected, actual, tolerance=0.01) -> bool:
    """Numbers are compared with a small tolerance (rounding); everything
    else needs an exact match. None == None counts as a match."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if expected == 0:
            return abs(actual) < tolerance
        return abs(expected - actual) / abs(expected) < tolerance
    return str(expected).strip().upper() == str(actual).strip().upper()


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    tender_texts = split_synthetic_tenders()
    ground_truth = load_ground_truth()

    tender_ids = sorted(tender_texts.keys())
    if limit:
        tender_ids = tender_ids[:limit]

    print(f"Running extraction on {len(tender_ids)} synthetic tenders...\n")

    field_correct = {f: 0 for f in SCORED_FIELDS}
    field_total = {f: 0 for f in SCORED_FIELDS}
    per_tender_scores = []

    for tender_id in tender_ids:
        text = tender_texts[tender_id]
        truth = ground_truth[tender_id]

        print(f"Extracting {tender_id} ({truth['title'][:50]}...)")
        try:
            extracted = extract_fields_with_llm(
                text, tender_id=tender_id, title=truth["title"],
                organization=truth.get("organization"),
            )
        except Exception as e:
            print(f"  ERROR extracting {tender_id}: {e}\n")
            continue

        # mode="json" converts Enum fields (like pec_category_required) to
        # their plain string .value (e.g. "C-4") instead of leaving them as
        # PECCategory.C4 Python objects — without this, correct extractions
        # of enum fields show up as false mismatches during comparison.
        extracted_dict = extracted.model_dump(mode="json")
        tender_correct = 0
        tender_total = 0
        mismatches = []

        for field in SCORED_FIELDS:
            expected = truth.get(field)
            actual = extracted_dict.get(field)
            field_total[field] += 1
            tender_total += 1
            if values_match(expected, actual):
                field_correct[field] += 1
                tender_correct += 1
            else:
                mismatches.append(f"{field}: expected={expected!r} got={actual!r}")

        score = tender_correct / tender_total
        per_tender_scores.append(score)
        print(f"  Score: {tender_correct}/{tender_total} ({score:.0%})")
        if mismatches:
            for m in mismatches:
                print(f"    MISMATCH -> {m}")
        print()

    # Overall summary
    total_correct = sum(field_correct.values())
    total_checked = sum(field_total.values())
    overall_accuracy = total_correct / total_checked if total_checked else 0

    print("=" * 60)
    print(f"OVERALL ACCURACY: {total_correct}/{total_checked} fields correct "
          f"({overall_accuracy:.1%})")
    print("=" * 60)
    print("\nAccuracy by field (worst to best — fix these first):")
    field_rates = sorted(
        ((f, field_correct[f] / field_total[f] if field_total[f] else 0) for f in SCORED_FIELDS),
        key=lambda x: x[1],
    )
    for field, rate in field_rates:
        print(f"  {field}: {rate:.0%}")

    if overall_accuracy >= 0.80:
        print("\n>= 80% overall — meets the Success Criteria target in your PRD.")
    else:
        print(f"\nBelow the 80% target in your PRD. Look at the worst-performing "
              f"fields above and consider sharpening the extraction prompt for those.")


if __name__ == "__main__":
    main()