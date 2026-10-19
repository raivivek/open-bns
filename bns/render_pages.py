"""Render gazette pages to grayscale PNGs for transcription (OCR input).

Usage: python -m bns.render_pages
"""

from pathlib import Path

import pymupdf

from bns.paths import GAZETTE_PDF, PAGES_DIR

ZOOM = 2.5  # 180 dpi: 10pt body text renders ~25px tall


def main() -> None:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(GAZETTE_PDF)
    for i, page in enumerate(doc):
        # Page 1 masthead (above y=190) is not part of the Act text.
        clip = pymupdf.Rect(45, 190 if i == 0 else 55, 555, 800)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=clip, colorspace=pymupdf.csGRAY)
        pix.save(PAGES_DIR / f"page-{i + 1:03d}.png")
    print(f"rendered {doc.page_count} pages to {PAGES_DIR}")


if __name__ == "__main__":
    main()
