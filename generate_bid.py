"""
TenderGuard AI — end-to-end Bid Document Draft tool.

Give it a real tender PDF and a contractor's name: it extracts the
tender's terms, runs the Select/Reject match (same as
run_tender_decision.py), and — if the result is Select — generates a draft
bid document (.docx) ready for the contractor to fill in pricing and
attach their certificates.

Usage:
    python generate_bid.py tenders/TS0000016176E.pdf "Khyber Engineering & Construction Co."

    # Generate a draft even if the match result is Reject (e.g. to see
    # what the gaps are, or to override a borderline case manually):
    python generate_bid.py tenders/TS0000016176E.pdf "Khyber Engineering & Construction Co." --force

    # Supply the real project title explicitly (recommended for tenders
    # that bundle multiple separate projects into one document):
    python generate_bid.py tenders/X.pdf "Contractor Name" --title "Repair of Boundary Wall, XYZ"
"""

import os
import sys
import json

from extract_tender import extract_text_from_document, extract_fields_with_llm
from schema import ContractorCriteria
from matching_engine import match
from generate_bid_document import generate_bid_document


def load_contractor(name: str) -> ContractorCriteria:
    with open("contractor_profiles.json") as f:
        raw = json.load(f)
    for item in raw:
        if item["contractor_name"].strip().lower() == name.strip().lower():
            item = {k: v for k, v in item.items() if not k.startswith("_")}
            return ContractorCriteria(**item)
    available = [item["contractor_name"] for item in raw]
    raise ValueError(
        f"No contractor named '{name}' found.\nAvailable:\n" +
        "\n".join(f"  - {n}" for n in available)
    )


def main():
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    manual_title = None
    if "--title" in args:
        idx = args.index("--title")
        manual_title = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if len(args) < 2:
        print('Usage: python generate_bid.py <tender.pdf> "<Contractor Name>" [--force] [--title "Real Title"]')
        sys.exit(1)

    doc_path, contractor_name = args[0], args[1]

    print(f"Loading contractor: {contractor_name} ...")
    contractor = load_contractor(contractor_name)

    print(f"Reading tender: {doc_path} ...")
    try:
        text = extract_text_from_document(doc_path)
    except FileNotFoundError as e:
        print(f"\nERROR: {e}\n")
        sys.exit(1)
    print(f"  ({len(text)} characters extracted)")

    # Tender reference = the PDF's filename without extension (e.g. TS0000016176E)
    tender_id = os.path.splitext(os.path.basename(doc_path))[0]

    # Title priority: --title flag > title saved in ground_truth_tenders.json >
    # empty (the extractor then reads the real project title from the notice itself)
    title = manual_title or ""
    if not title:
        try:
            with open("ground_truth_tenders.json", encoding="utf-8") as f:
                for item in json.load(f):
                    if item["tender_id"] == tender_id:
                        title = item["title"]
                        break
        except FileNotFoundError:
            pass

    print("Extracting tender terms with AI ...")
    try:
        tender = extract_fields_with_llm(text, tender_id=tender_id, title=title)
    except Exception as e:
        print(f"ERROR: extraction failed — {e}")
        sys.exit(1)

    print("Running criteria match ...")
    decision = match(tender, contractor)

    print(f"\nDecision: {decision.decision}")
    for r in decision.results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.criterion_name}: {r.reason}")
    print(f"\nCoverage: {decision.confidence_note}")
    if tender.deadline_warning:
        print(f"DEADLINE WARNING: {tender.deadline_warning}")

    if decision.decision == "Reject" and not force:
        print(
            "\nThis tender was REJECTED for this contractor — no bid document "
            "generated. Re-run with --force if you want a draft anyway (e.g. "
            "to review what's missing, or because you're overriding the "
            "automated check manually)."
        )
        sys.exit(0)

    safe_name = tender.tender_id.replace("/", "-")
    output_path = f"Bid_Draft_{safe_name}.docx"
    failed_checks = [r.reason for r in decision.results if not r.passed]
    generate_bid_document(tender, contractor, output_path, failed_checks=failed_checks,
                          confidence_note=decision.confidence_note)

    print(f"\nBid document draft saved to: {output_path}")
    print("Remember: pricing, certificates, and bid security still need to be "
          "added by hand before this can actually be submitted.")


if __name__ == "__main__":
    main()