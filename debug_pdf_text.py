"""
Quick standalone debug tool — isolates PDF text extraction from everything
else (LLM, matching, ground truth) so we can see exactly what PyMuPDF is
actually pulling out of a specific file.

Usage:
    python debug_pdf_text.py tenders/TS0000015708E.pdf
"""

import sys

if len(sys.argv) < 2:
    print("Usage: python debug_pdf_text.py path/to/file.pdf")
    sys.exit(1)

pdf_path = sys.argv[1]

import fitz  # PyMuPDF

doc = fitz.open(pdf_path)
print(f"PDF opened OK. Page count: {len(doc)}")
print(f"PDF is encrypted: {doc.is_encrypted}")
print(f"PDF needs password: {doc.needs_pass}")
print()

total_chars = 0
for i, page in enumerate(doc):
    text = page.get_text()
    total_chars += len(text)
    print(f"--- Page {i + 1}: {len(text)} characters ---")
    print(repr(text[:300]))  # repr() shows hidden/odd characters clearly
    print()

doc.close()
print(f"TOTAL across all pages: {total_chars} characters")

if total_chars < 200:
    print("\nConfirmed: PyMuPDF is genuinely extracting almost nothing from "
          "this file, even though it has a real text layer visible in your "
          "PDF viewer. This usually means one of:")
    print("  1. The file path points to the WRONG file (empty/corrupted/wrong PDF)")
    print("  2. The PDF uses a font encoding PyMuPDF can't map to real "
          "characters (rare, but happens with some government-generated PDFs)")
    print("  3. The file didn't fully download and is truncated/corrupted")