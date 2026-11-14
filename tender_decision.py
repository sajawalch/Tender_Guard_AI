"""
TenderGuard AI — end-to-end decision tool.

This is the actual product, in one script: give it a real tender PDF and a
contractor's name, and it extracts the tender's terms, runs them against
that contractor's saved criteria, and prints a Select/Reject decision with
reasons — exactly what the final web app will do, just from the command
line for now.

Usage:
    python run_tender_decision.py tenders/TS0000016176E.pdf "Al-Hamd Builders (Pvt) Ltd"

    # For a NEW tender not already in ground_truth_tenders.json, optionally
    # give its real project title as a 3rd argument — this matters a lot if
    # the PDF lists several separate tenders in one bulletin/table, since
    # the AI needs to know which specific one you mean:
    python run_tender_decision.py new_tender.pdf "Sindh Horizon Builders" "Construction of Boundary Wall, XYZ Site"

    # List available contractor names:
    python run_tender_decision.py --list-contractors
"""

import json
import os
import sys

from extract_tender import extract_text_from_document, extract_fields_with_llm
from schema import ContractorCriteria, PECCategory, ProjectType
from matching_engine import match


def load_contractor(name: str) -> ContractorCriteria:
    with open("contractor_profiles.json") as f:
        raw = json.load(f)

    for item in raw:
        if item["contractor_name"].strip().lower() == name.strip().lower():
            item = {k: v for k, v in item.items() if not k.startswith("_")}
            return ContractorCriteria(**item)

    available = [item["contractor_name"] for item in raw]
    raise ValueError(
        f"No contractor named '{name}' found in contractor_profiles.json.\n"
        f"Available contractors:\n" + "\n".join(f"  - {n}" for n in available)
    )


def print_decision(tender_title: str, contractor_name: str, decision):
    bar = "=" * 64
    print(f"\n{bar}")
    print(f"TENDER:      {tender_title}")
    print(f"CONTRACTOR:  {contractor_name}")
    print(f"{bar}")

    verdict_symbol = {"Select": "\u2705 SELECT", "Reject": "\u274c REJECT"}.get(
        decision.decision, "\u2753 NOT ENOUGH DATA (no verdict)")
    print(f"\n  DECISION: {verdict_symbol}\n")

    if not decision.results:
        print("  (No criteria could be checked — not enough tender fields "
              "were extracted to compare against this contractor's profile.)")
    else:
        for r in decision.results:
            mark = "PASS" if r.passed else "FAIL"
            symbol = "\u2713" if r.passed else "\u2717"
            print(f"  [{symbol} {mark}] {r.criterion_name}")
            print(f"           {r.reason}")

    print(f"\n  COVERAGE: {decision.confidence_note}")
    print(f"\n{bar}\n")


def lookup_real_title(doc_path: str, fallback: str) -> str:
    """Tries to find the tender's real project title from ground_truth_tenders.json
    by matching the PDF's filename (without extension) to a tender_id. This
    matters a lot for multi-tender bulletin documents — the model needs the
    real project name, not just the filename, to find the right row in a
    table listing several unrelated tenders."""
    import os
    stem = os.path.splitext(os.path.basename(doc_path))[0]
    try:
        with open("ground_truth_tenders.json") as f:
            raw = json.load(f)
        for item in raw:
            if item["tender_id"] == stem:
                return item["title"]
    except FileNotFoundError:
        pass
    return fallback


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--list-contractors":
        with open("contractor_profiles.json") as f:
            raw = json.load(f)
        print("Available contractor profiles:")
        for item in raw:
            print(f"  - {item['contractor_name']}")
        return

    if len(sys.argv) < 3:
        print('Usage: python run_tender_decision.py <path_to_tender.pdf> "<Contractor Name>" ["<Real Project Title>"]')
        print("       python run_tender_decision.py --list-contractors")
        sys.exit(1)

    doc_path = sys.argv[1]
    contractor_name = sys.argv[2]
    manual_title = sys.argv[3] if len(sys.argv) > 3 else None

    print(f"Loading contractor profile: {contractor_name} ...")
    contractor = load_contractor(contractor_name)

    print(f"Reading tender document: {doc_path} ...")
    try:
        text = extract_text_from_document(doc_path)
    except FileNotFoundError as e:
        print(f"\nERROR: {e}\n")
        sys.exit(1)
    print(f"  ({len(text)} characters of text extracted)\n")

    if manual_title:
        real_title = manual_title
        print(f"  (Using the project title you provided: \"{real_title}\")")
    else:
        real_title = lookup_real_title(doc_path, fallback=doc_path.split("/")[-1])
        if real_title == doc_path.split("/")[-1]:
            print(f"  (No matching entry found in ground_truth_tenders.json for this "
                  f"file, and no title was given as a 3rd argument — using the "
                  f"filename as a fallback title. If this tender's PDF lists "
                  f"MULTIPLE separate projects in one table, extraction accuracy "
                  f"may suffer without the real project title. If results look "
                  f"wrong, re-run with the real title as a 3rd argument.)")

    print("Extracting tender terms with AI ...")
    try:
        tender = extract_fields_with_llm(
            text,
            tender_id=os.path.splitext(os.path.basename(doc_path))[0],
            title=real_title,
        )
    except Exception as e:
        print(f"\nERROR: extraction failed — {e}\n")
        sys.exit(1)

    print("Running criteria match ...")
    decision = match(tender, contractor)

    print_decision(tender.title, contractor.contractor_name, decision)
    if tender.deadline_warning:
        print(f"  DEADLINE WARNING: {tender.deadline_warning}\n")


if __name__ == "__main__":
    main()