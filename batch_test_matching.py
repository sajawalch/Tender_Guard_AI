"""
TenderGuard AI — batch matching test.

Runs every tender in synthetic_ground_truth.json against every contractor
in contractor_profiles.json, and prints a summary table of Select/Reject
decisions. This is the quickest way to see your matching engine handling
real variety, not just one hardcoded example.

Usage:
    python batch_test_matching.py
"""

import json
from schema import TenderTerms, ContractorCriteria
from matching_engine import match


def load_tenders(path: str = "synthetic_ground_truth.json") -> list[TenderTerms]:
    with open(path) as f:
        raw = json.load(f)
    tenders = []
    for item in raw:
        item = {k: v for k, v in item.items() if not k.startswith("_")}
        tenders.append(TenderTerms(**item))
    return tenders


def load_contractors(path: str = "contractor_profiles.json") -> list[ContractorCriteria]:
    with open(path) as f:
        raw = json.load(f)
    contractors = []
    for item in raw:
        item = {k: v for k, v in item.items() if not k.startswith("_")}
        contractors.append(ContractorCriteria(**item))
    return contractors


def main():
    tenders = load_tenders()
    contractors = load_contractors()

    print(f"Loaded {len(tenders)} tenders and {len(contractors)} contractor profiles")
    print(f"Running {len(tenders) * len(contractors)} tender x contractor combinations...\n")

    select_count = 0
    reject_count = 0

    # Summary table: rows = tenders, columns = contractors
    header = "Tender ID".ljust(14) + "".join(c.contractor_name[:14].ljust(16) for c in contractors)
    print(header)
    print("-" * len(header))

    for tender in tenders:
        row = tender.tender_id.ljust(14)
        for contractor in contractors:
            decision = match(tender, contractor)
            mark = "SELECT" if decision.decision == "Select" else "reject"
            row += mark.ljust(16)
            if decision.decision == "Select":
                select_count += 1
            else:
                reject_count += 1
        print(row)

    total = select_count + reject_count
    print(f"\nTotal: {total} decisions -> {select_count} Select ({select_count/total:.0%}), "
          f"{reject_count} Reject ({reject_count/total:.0%})")

    if select_count == total or reject_count == total:
        print(
            "\nWARNING: every single decision came out the same way. That usually means "
            "either your contractor profiles are too similar to each other, or a check "
            "is too lenient/strict. Worth investigating before moving on."
        )

    # Show full detail for ONE interesting case: the first Reject found
    print("\n--- Full detail for first Reject decision found ---")
    for tender in tenders:
        for contractor in contractors:
            decision = match(tender, contractor)
            if decision.decision == "Reject":
                print(f"\nTender: {tender.tender_id} ({tender.title})")
                print(f"Contractor: {contractor.contractor_name}")
                print(f"Decision: {decision.decision}\n")
                for r in decision.results:
                    mark = "PASS" if r.passed else "FAIL"
                    print(f"  [{mark}] {r.criterion_name}: {r.reason}")
                return  # stop after first example


if __name__ == "__main__":
    main()