"""
Runs EVERY tender in a folder against one firm and shows, for each, the decision, the values the model
read, and why it was rejected - so you can tell a correct Reject from an extraction mistake.

    python check_all_tenders.py --firm "Al-sad Builders (Pvt) Ltd"
    python check_all_tenders.py --firm "Al-sad Builders (Pvt) Ltd" --refresh     # read the PDFs with the model again

The first run reads each PDF with the model (2 OpenAI calls per tender) and saves what it read in
extracted_cache\\. Later runs use that saved copy, so trying another firm or changed limits costs nothing.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from schema import ContractorCriteria, TenderTerms
from matching_engine import match

SUFFIXES = {".pdf", ".txt", ".md"}


def load_firm(name: str | None) -> ContractorCriteria:
    profiles = json.loads(Path("contractor_profiles.json").read_text(encoding="utf-8"))
    if name:
        raw = next((p for p in profiles if p["contractor_name"].strip().lower() == name.strip().lower()), None)
        if raw is None:
            sys.exit(f"Firm '{name}' not found. Available:\n  " + "\n  ".join(p["contractor_name"] for p in profiles))
    else:
        raw = next((p for p in profiles if p.get("_mine")), profiles[0])
    return ContractorCriteria(**{k: v for k, v in raw.items() if not k.startswith("_")})


def read_tender(path: Path, cache_dir: Path, refresh: bool) -> TenderTerms:
    cache = cache_dir / f"{path.stem}.json"
    if cache.exists() and not refresh:
        return TenderTerms(**json.loads(cache.read_text(encoding="utf-8")))
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("no saved copy and OPENAI_API_KEY is not set")
    from extract_tender import extract_fields_with_llm, extract_text_from_document
    text = extract_text_from_document(str(path))
    terms = extract_fields_with_llm(text, tender_id=path.stem, title=path.stem)
    cache_dir.mkdir(exist_ok=True)
    cache.write_text(json.dumps(terms.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    return terms


def money(value) -> str:
    return "-" if value is None else f"{value:,.0f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run every tender in a folder against one firm")
    ap.add_argument("--firm", help="firm name (default: your own firm, else the first one)")
    ap.add_argument("--tenders", default="tenders", help="folder with the tender files")
    ap.add_argument("--cache", default="extracted_cache", help="folder for the saved extractions")
    ap.add_argument("--refresh", action="store_true", help="read the tenders with the model again")
    args = ap.parse_args()

    firm = load_firm(args.firm)
    print(f"\nFirm: {firm.contractor_name}   PEC {firm.pec_category_held.value}   "
          f"experience {firm.years_experience} years   taxpayer {'yes' if firm.is_active_taxpayer else 'no'}")
    print(f"  contract value : {money(firm.min_contract_value_pkr)} to {money(firm.max_contract_value_pkr)}")
    print(f"  bid security   : up to {money(firm.max_bid_security_pkr)}")
    print(f"  LD per day     : up to {firm.max_acceptable_ld_rate_percent_per_day}%   "
          f"advance at least {firm.min_required_advance_payment_percent}%   "
          f"completion at least {firm.max_acceptable_completion_period_days} days\n")

    files = sorted(p for p in Path(args.tenders).glob("*") if p.suffix.lower() in SUFFIXES)
    if not files:
        sys.exit(f"No tender files in '{args.tenders}'.")

    decisions, failing = Counter(), Counter()
    for path in files:
        try:
            tender = read_tender(path, Path(args.cache), args.refresh)
        except Exception as e:  # noqa: BLE001 - report and carry on with the next tender
            print(f"{path.stem}\n   could not read: {e}\n")
            decisions["could not read"] += 1
            continue
        d = match(tender, firm)
        decisions[d.decision] += 1
        pec = tender.pec_category_required.value if tender.pec_category_required else "-"
        print(f"{path.stem}   ->  {d.decision.upper()}   ({d.criteria_checked} of {d.total_criteria} checks)")
        print(f"   read from the PDF: value {money(tender.contract_value_pkr)} | security "
              f"{money(tender.bid_security_amount_pkr)} (percent {tender.bid_security_percent}) | PEC {pec} | "
              f"{tender.completion_period_days or '-'} days | advance {tender.advance_payment_percent}")
        for r in d.results:
            if not r.passed:
                failing[r.criterion_name] += 1
                print(f"   FAIL {r.criterion_name}: {r.reason}")
        print()

    print("=" * 60)
    print("  ".join(f"{name}: {count}" for name, count in decisions.items()))
    if failing:
        print("Checks that failed, most common first:")
        for name, count in failing.most_common():
            print(f"   {name}: {count} tender(s)")
    print("\nA Reject is believable when the value 'read from the PDF' matches the PDF. Open the PDF for one\n"
          "tender and compare. If the model read a wrong value, the Reject is wrong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())