"""
TenderGuard AI — Bid Document Draft generator.

Takes a tender's extracted terms + a contractor's profile, and produces a
draft bid letter (.docx) in a PEC-style format: company letterhead, bid
letter body, tender details, a price schedule table (left blank for the
contractor's own pricing), a checklist of supporting documents this
specific tender requires, and a signature block. A separate first page
holds the warnings and a to-do list for the contractor; it is meant to be
deleted before submitting, so none of it ends up in the letter itself.

This is explicitly a DRAFT, not a finished bid — pricing, certificates, and
the bid security instrument always need to be added by the contractor
themselves. The goal is to save the structural/formatting work, not to
submit a bid on anyone's behalf.

Requires:
    pip install python-docx
"""

import re

from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

from schema import TenderTerms, ContractorCriteria


def _set_cell_text(cell, text, bold=False, size=10):
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)


def format_closing_date(raw: str | None) -> str | None:
    """'2026-11-16 11:00' -> '16 November 2026, 11:00 AM'. If the text isn't in
    one of the expected formats, return it unchanged rather than guessing."""
    if not raw:
        return None
    from datetime import datetime
    for fmt, out in (("%Y-%m-%d %H:%M", "%d %B %Y, %I:%M %p"), ("%Y-%m-%d", "%d %B %Y")):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime(out)
        except ValueError:
            continue
    return raw


# Topics used to spot the same requirement written twice (once built from a
# structured field, once copied from the notice's own wording).
_TOPICS = {
    "similar_contracts": re.compile(r"completion certificate|same nature|similar (contract|work|project)", re.I),
    "experience": re.compile(r"years?'? (of )?(relevant |general |construction )?experience"
                             r"|experience (of|for) .*years?", re.I),
    "bid_security": re.compile(r"bid(s|ding)? security|\bcdr\b|call deposit|bank guarantee|earnest money", re.I),
}
# For these topics the notice's own wording is more useful (who the security is payable to, how long
# it stays valid), so it replaces the generic line. A second, different statement is kept as its own line.
_PREFER_NOTICE_WORDING = {"bid_security"}

_PEC = re.compile(r"\bpec\b|pakistan engineer", re.I)
_ATL = re.compile(r"active taxpayer|\batl\b", re.I)
_CNIC = re.compile(r"cnic|identity card|national identity", re.I)
_STOPWORDS = frozenset(
    "the a an of for and or to in on at by with from is are be been will shall must should may their its it "
    "this that these those all any per as under up bidder bidders provide provided submit submitted "
    "required require requires".split())


def _topic(text: str) -> str | None:
    for name, pattern in _TOPICS.items():
        if pattern.search(text):
            return name
    return None


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in _STOPWORDS and (len(w) > 1 or w.isdigit())}


def _same_requirement(a: str, b: str, threshold: float = 0.7) -> bool:
    """True when two lines say (almost) the same thing in different words."""
    wa, wb = _content_words(a), _content_words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= threshold


def build_document_checklist(tender: TenderTerms) -> list[str]:
    """Works out which supporting documents THIS tender requires, based on what was actually
    extracted - not on whether a particular contractor currently meets them. Lines come from the
    tender's own wording (tender.requirement_items, then tender.required_documents) so numbers,
    names and dates are kept as written. Each requirement appears once."""
    entries: list[dict] = []

    def add(text: str, topic: str | None = None, generic: bool = False) -> dict:
        entry = {"topic": topic, "text": text, "generic": generic}
        entries.append(entry)
        return entry

    pec_entry = pec_base = None
    if tender.pec_category_required:
        spec = (f", specialization code {tender.pec_specialization_code}"
                if tender.pec_specialization_code else "")
        pec_base = f"Valid PEC Registration Certificate (Category {tender.pec_category_required.value} or higher{spec})"
        pec_entry = add(pec_base + ", current and renewed for the relevant year")
    atl_listed = bool(tender.requires_active_taxpayer_status)
    if atl_listed:
        add("FBR Active Taxpayer List (ATL) certificate / screenshot")
    if tender.min_similar_contracts:
        period = (f" within the last {tender.similar_contracts_lookback_years} years"
                  if tender.similar_contracts_lookback_years else "")
        add(f"Completion certificates for at least {tender.min_similar_contracts} "
            f"similar contract(s) completed as main contractor{period}", "similar_contracts")
    if tender.min_years_experience_required:
        add(f"Proof of at least {tender.min_years_experience_required} years of "
            f"relevant experience", "experience")
    if tender.bid_security_amount_pkr or tender.bid_security_percent:
        add("Bid Security / Call Deposit Receipt (CDR) or bank guarantee, as specified",
            "bid_security", generic=True)

    pec_merged = False
    for item in list(tender.requirement_items) + list(tender.required_documents):
        item = item.strip()
        if not item:
            continue
        item = item[0].upper() + item[1:]

        if _CNIC.search(item):
            continue                                    # the ID-card line is always added below
        if _ATL.search(item) and atl_listed:
            continue                                    # already listed above
        if _PEC.search(item) and pec_entry is not None:
            # The notice's own wording (e.g. "renewed for the year 2026-27") replaces "relevant year".
            if not pec_merged and re.search(r"renew|20\d\d", item, re.I):
                pec_entry["text"] = f"{pec_base}: {item}"
                pec_merged = True
            continue

        topic = _topic(item)
        same = next((e for e in entries if topic and e["topic"] == topic), None)
        if same is not None:
            if topic in _PREFER_NOTICE_WORDING:
                if same["generic"]:
                    same["text"], same["generic"] = item, False
                elif not any(_same_requirement(item, e["text"]) for e in entries):
                    add(item, topic)
            continue                                    # same requirement already listed
        if any(item.lower() == e["text"].lower() or _same_requirement(item, e["text"]) for e in entries):
            continue
        add(item, topic)

    # The notice often says "half of the amount mentioned against this work" and gives the figure only in
    # its table. Put that figure, as written, next to the turnover requirement (never converted or halved).
    figure = (getattr(tender, "annual_turnover_figure", None) or "").strip()
    if figure:
        unit_note = "" if re.search(r"[A-Za-z]", figure) else "; unit not stated"
        note = f"figure stated against this work in the notice: {figure}{unit_note}"
        turnover = next((e for e in entries if re.search(r"turnover", e["text"], re.I)), None)
        if turnover is None:
            add(f"Average annual turnover ({note})")
        elif figure not in turnover["text"]:
            turnover["text"] = f"{turnover['text'].rstrip('. ')} ({note})."

    # These are always sensible to include regardless of what was extracted
    for basic in ("Company registration / incorporation certificate",
                  "National Tax Number (NTN) certificate",
                  "CNIC copy of authorized signatory"):
        if not any(_same_requirement(basic, e["text"]) for e in entries):
            add(basic)

    return [e["text"] for e in entries]


def _add_cover_page(doc, tender: TenderTerms, failed_checks, confidence_note) -> None:
    """First page: warnings and a to-do list for the contractor. It is NOT part
    of the bid and is meant to be deleted before submitting."""
    title = doc.add_paragraph()
    tr = title.add_run("DRAFT \u2014 NOT READY TO SUBMIT")
    tr.bold = True
    tr.font.size = Pt(18)
    intro = doc.add_paragraph()
    intro.add_run("This page is for you only. Delete it before you submit the bid.").italic = True

    if failed_checks:
        h = doc.add_paragraph()
        h.add_run("Issues flagged by the automated check. ").bold = True
        h.add_run("This draft was generated even though the check found the following. "
                  "Resolve or confirm each one before signing the declaration:")
        for reason in failed_checks:
            doc.add_paragraph(reason, style="List Bullet")

    if tender.deadline_warning:
        dl = doc.add_paragraph()
        dl.add_run("Deadline. ").bold = True
        dl.add_run(tender.deadline_warning.replace(
            f"({tender.bid_closing_date})", f"({format_closing_date(tender.bid_closing_date)})"))

    if confidence_note:
        note = doc.add_paragraph()
        note.add_run("How much was checked. ").bold = True
        note.add_run(confidence_note)

    todo = doc.add_paragraph()
    todo.add_run("Before you submit").bold = True
    for item in (
        "This checklist was produced by AI from the notice's text. It may leave out conditions and can "
        "differ from one run to the next. Read the notice's own clauses yourself before relying on it, "
        "especially those on bid security (who it is payable to, which bank, how long it stays valid), "
        "turnover and other financial requirements.",
        "Enter your bid amount in figures and in words in the letter, and fill in the price "
        "schedule. TenderGuard AI does not set prices.",
        "Enter the date of submission in the letter.",
        "Check every requirement in the Supporting Documents Checklist against your own records. "
        "TenderGuard AI does not check turnover, cash or cash equivalents, or the value of your "
        "past contracts.",
        "Arrange the bid security instrument and gather the certificates yourself. This draft "
        "contains none of them.",
        "Compare this draft with the forms in the bidding documents. If the bidding documents "
        "prescribe a format, use theirs.",
        "Delete this page and the drafting note above the signature block.",
    ):
        doc.add_paragraph(item, style="List Bullet")
    doc.add_page_break()


def generate_bid_document(tender: TenderTerms, contractor: ContractorCriteria,
                          output_path: str, failed_checks: list[str] | None = None,
                          confidence_note: str | None = None) -> str:
    doc = Document()

    # --- Base font ---
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Warnings and to-do list go on their own first page, not into the letter.
    _add_cover_page(doc, tender, failed_checks, confidence_note)

    # --- Letterhead ---
    heading = doc.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run(contractor.contractor_name)
    run.bold = True
    run.font.size = Pt(16)

    if contractor.company_address:
        addr = doc.add_paragraph(contractor.company_address)
        addr.alignment = WD_ALIGN_PARAGRAPH.CENTER
        addr.runs[0].font.size = Pt(9)

    contact_bits = []
    if contractor.phone:
        contact_bits.append(f"Tel: {contractor.phone}")
    if contractor.email:
        contact_bits.append(f"Email: {contractor.email}")
    if contractor.ntn_number:
        contact_bits.append(f"NTN: {contractor.ntn_number}")
    if contact_bits:
        contact_p = doc.add_paragraph(" | ".join(contact_bits))
        contact_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        contact_p.runs[0].font.size = Pt(9)

    doc.add_paragraph()  # spacer

    # --- Date and reference ---
    doc.add_paragraph("Date: [TO BE FILLED ON THE DAY OF SUBMISSION]")
    doc.add_paragraph(f"Tender Reference: {tender.tender_id}")
    # Address the bid to the named officer when the notice gives one; add the
    # organization on a second line only if the officer's title doesn't already name it.
    addressee = tender.addressee or tender.organization
    if addressee:
        doc.add_paragraph(f"To: {addressee}")
        if tender.addressee and tender.organization and \
                tender.organization.lower() not in tender.addressee.lower():
            doc.add_paragraph(tender.organization)

    doc.add_paragraph()

    # --- Subject line ---
    subject = doc.add_paragraph()
    subject_run = subject.add_run(f"Subject: Bid for \u201c{tender.title}\u201d")
    subject_run.bold = True
    subject_run.underline = True

    doc.add_paragraph()

    # --- Bid letter body (standard PEC-style wording) ---
    if tender.bid_validity_days:
        validity_sentence = (
            f"We agree to abide by this bid for a period of {tender.bid_validity_days} "
            f"days, as required by the bidding documents, and it shall remain binding "
            f"upon us and may be accepted at any time before the expiration of that period."
        )
    else:
        validity_sentence = (
            "We agree to abide by this bid for the bid validity period stated in "
            "the bidding documents, and it shall remain binding upon us and may "
            "be accepted at any time before the expiration of that period."
        )

    body_text = (
        "Dear Sir/Madam,\n\n"
        "We, the undersigned, having examined the bidding documents, including "
        "all addenda thereto, for the above-referenced tender, and having full "
        "knowledge of the conditions prevailing relative to the works, hereby "
        "offer to execute and complete the works described above and remedy "
        "any defects therein, in full conformity with the said bidding "
        "documents, for the sum of PKR [AMOUNT TO BE INSERTED BY BIDDER] "
        "(Pakistani Rupees [AMOUNT IN WORDS]) or such other sum as may be "
        "ascertained in accordance with the terms and conditions of the "
        "bidding documents.\n\n"
        "We undertake, if our bid is accepted, to commence the works and "
        "complete them within the time stated in the bidding documents.\n\n"
        + validity_sentence
    )
    doc.add_paragraph(body_text)

    doc.add_paragraph()

    # --- Tender details summary table ---
    doc.add_heading("Tender Summary", level=2)
    details_table = doc.add_table(rows=0, cols=2)
    details_table.style = "Light Grid Accent 1"

    def add_detail_row(label, value):
        row = details_table.add_row().cells
        _set_cell_text(row[0], label, bold=True)
        _set_cell_text(row[1], str(value) if value is not None else "Not specified in tender")

    add_detail_row("Organization", tender.organization or "Not specified")
    add_detail_row(
        "Estimated Contract Value",
        f"PKR {tender.contract_value_pkr:,.0f}" if tender.contract_value_pkr else None,
    )
    add_detail_row(
        "Bid Security",
        (f"PKR {tender.bid_security_amount_pkr:,.0f}" if tender.bid_security_amount_pkr
         else (f"{tender.bid_security_percent}% of bid value" if tender.bid_security_percent else None)),
    )
    add_detail_row(
        "Completion Period",
        f"{tender.completion_period_days} days" if tender.completion_period_days else None,
    )
    add_detail_row("Bid Submission Deadline", format_closing_date(tender.bid_closing_date))
    add_detail_row(
        "Bid Validity",
        f"{tender.bid_validity_days} days" if tender.bid_validity_days else None,
    )
    add_detail_row(
        "PEC Category Required",
        tender.pec_category_required.value if tender.pec_category_required else None,
    )
    add_detail_row(
        "FBR Active Taxpayer Required",
        "Yes" if tender.requires_active_taxpayer_status else "Not specified",
    )

    doc.add_paragraph()

    # --- Price schedule (left blank for contractor's own pricing) ---
    doc.add_heading("Price Schedule", level=2)
    doc.add_paragraph(
        "Note: rates and amounts below must be filled in by the bidder. "
        "TenderGuard AI does not set pricing on your behalf."
    )
    price_table = doc.add_table(rows=2, cols=4)
    price_table.style = "Light Grid Accent 1"
    header_cells = price_table.rows[0].cells
    for cell, text in zip(header_cells, ["Description", "Unit", "Rate (PKR)", "Amount (PKR)"]):
        _set_cell_text(cell, text, bold=True)
    body_cells = price_table.rows[1].cells
    _set_cell_text(body_cells[0], tender.title)
    _set_cell_text(body_cells[1], "Lot")
    _set_cell_text(body_cells[2], "[TO BE FILLED]")
    _set_cell_text(body_cells[3], "[TO BE FILLED]")

    doc.add_paragraph()

    # --- Supporting documents checklist ---
    doc.add_heading("Supporting Documents Checklist", level=2)
    doc.add_paragraph(
        "Based on this tender's stated requirements, the following documents "
        "should be attached to the bid submission:"
    )
    for item in build_document_checklist(tender):
        doc.add_paragraph(item, style="List Bullet")

    doc.add_paragraph()

    # --- Declaration + signature block ---
    # keep_with_next chains these paragraphs so Word never splits the signature
    # block across pages (it moves the whole group to the next page instead).
    decl_heading = doc.add_heading("Declaration", level=2)
    decl_heading.paragraph_format.keep_with_next = True
    decl = doc.add_paragraph(
        "We confirm that the information provided in this bid and its "
        "attachments is true and accurate to the best of our knowledge, and "
        "that our firm meets the eligibility criteria stated in the bidding "
        "documents."
    )
    decl.paragraph_format.keep_with_next = True
    dnote = doc.add_paragraph()
    dn = dnote.add_run(
        "[Drafting note \u2014 delete before submitting: sign this declaration only after you "
        "have checked each eligibility requirement in the checklist yourself, including "
        "turnover, cash and past contracts.]"
    )
    dn.italic = True
    dn.font.size = Pt(9)
    dnote.paragraph_format.keep_with_next = True

    sig_lines = [
        "Authorized Signatory: ______________________________",
        f"Name: {contractor.contact_person or '______________________________'}",
        f"Designation: {contractor.contact_designation or '______________________________'}",
        "Company Seal / Stamp:",
    ]
    for i, line in enumerate(sig_lines):
        sp = doc.add_paragraph(line)
        sp.paragraph_format.space_before = Pt(18 if i == 0 else 6)
        sp.paragraph_format.keep_with_next = i < len(sig_lines) - 1

    doc.save(output_path)
    return output_path


if __name__ == "__main__":
    # Quick standalone smoke test with dummy data — run this directly to
    # confirm python-docx is installed and generation works, before wiring
    # it into the full tender-reading pipeline.
    from schema import ProjectType, PECCategory

    sample_tender = TenderTerms(
        tender_id="TS0000016176E",
        title="Construction of 06 No. Cat-IV Flats at 132KV Grid Station Khurrianwala",
        organization="FESCO (Faisalabad Electric Supply Company)",
        contract_value_pkr=25831313,
        bid_security_amount_pkr=1291566,
        pec_category_required=PECCategory.C5,
        requires_active_taxpayer_status=True,
        min_similar_contracts=2,
        similar_contracts_lookback_years=10,
        completion_period_days=210,
    )
    sample_contractor = ContractorCriteria(
        contractor_name="Al-Hamd Builders (Pvt) Ltd",
        pec_category_held=PECCategory.C4,
        company_address="Plot 123, Industrial Area, Faisalabad",
        contact_person="Muhammad Ali",
        contact_designation="Managing Director",
        phone="+92-41-1234567",
        email="info@alhambuilders.example",
        ntn_number="1234567-8",
    )

    out = generate_bid_document(sample_tender, sample_contractor, "test_bid_output.docx")
    print(f"Generated: {out}")