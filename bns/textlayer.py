"""Independent second reading of the gazette: its embedded text layer.

Emits the same `bns-ocr/1` page format as the image transcription (see
ocr/SPEC.md) by using glyph coordinates, so the two readings can be diffed
block-by-block in `bns.reconcile`.

Usage: python -m bns.textlayer   -> ocr/textlayer/page-NNN.txt
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from bns.paths import GAZETTE_PDF, ROOT

OUT_DIR = ROOT / "ocr" / "textlayer"

BODY_X_MIN = 112.0
BODY_X_MAX = 484.0
PAGE_CENTER = 298.0
PARA_GAP = 14.5  # baseline gap; line pitch is 12, paragraph gap is >= 16
REF_RE = re.compile(r"^\d+\s+of\s+\d{4}\.?(\s+\d+\s+of\s+\d{4}\.?)*$")
ILLUS_RE = re.compile(r"^Illustrations?\s*\.?$")
CONT_START_RE = re.compile(r"^(\(|Provided|Explanation|Exception|Illustration)")


@dataclass
class Span:
    x0: float
    x1: float
    y: float
    text: str
    bold: bool
    italic: bool
    size: float


@dataclass
class Line:
    spans: list[Span] = field(default_factory=list)

    @property
    def x0(self) -> float:
        # First visible glyph: leading-space spans shift the apparent indent.
        for s in self.spans:
            if s.text.strip():
                lead = len(s.text) - len(s.text.lstrip())
                width = (s.x1 - s.x0) / max(len(s.text), 1)
                return s.x0 + lead * width
        return self.spans[0].x0

    @property
    def x1(self) -> float:
        return max(s.x1 for s in self.spans if s.text.strip())

    @property
    def y(self) -> float:
        return self.spans[0].y

    @property
    def text(self) -> str:
        out = ""
        prev: Span | None = None
        for s in self.spans:
            if prev is not None and s.x0 - prev.x1 > 1.5 and not out.endswith(" ") and not s.text.startswith(" "):
                out += " "
            out += s.text
            prev = s
        return re.sub(r"\s+", " ", out).strip()

    @property
    def centered(self) -> bool:
        mid = (self.x0 + self.x1) / 2
        return self.x0 > 145 and self.x1 < 470 and abs(mid - PAGE_CENTER) < 22

    @property
    def italic(self) -> bool:
        # Mostly-italic by letters: "Illustration" + "s." are sometimes split into
        # italic and roman spans.
        total = sum(len(re.findall(r"\w", s.text)) for s in self.spans)
        ital = sum(len(re.findall(r"\w", s.text)) for s in self.spans if s.italic)
        return total > 0 and ital / total >= 0.8


def page_spans(page: pymupdf.Page) -> list[Span]:
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                # Whitespace-only spans are kept: some word gaps exist only as a space glyph.
                # < 6.5pt: digital-signature stamp on the last page.
                if not s["text"] or s["size"] < 6.5:
                    continue
                font = s["font"]
                spans.append(
                    Span(
                        x0=s["bbox"][0],
                        x1=s["bbox"][2],
                        y=s["origin"][1],
                        text=s["text"],
                        bold="Bold" in font,
                        italic="Italic" in font,
                        size=s["size"],
                    )
                )
    return spans


def cluster_lines(spans: list[Span]) -> list[Line]:
    lines: list[Line] = []
    for s in sorted(spans, key=lambda s: (s.y, s.x0)):
        # Small-caps / italic glyphs sit up to ~2.5pt off the roman baseline.
        if lines and abs(lines[-1].y - s.y) <= 3.0:
            lines[-1].spans.append(s)
        else:
            lines.append(Line([s]))
    for ln in lines:
        ln.spans.sort(key=lambda s: s.x0)
        while ln.spans and not ln.spans[0].text.strip():
            ln.spans.pop(0)
        while ln.spans and not ln.spans[-1].text.strip():
            ln.spans.pop()
    return [ln for ln in lines if ln.spans]


def indent_level(x0: float) -> str:
    if x0 < 130:
        return "P0"
    if x0 < 160:
        return "P1"
    if x0 < 184:
        return "P2"
    if x0 < 205:
        return "P3"
    return "P4"


def join_text(a: str, b: str) -> str:
    if not a:
        return b
    if a.endswith("-") and not a.endswith("--"):
        return a + b
    return a + " " + b


def section_start(ln: Line) -> tuple[str, str] | None:
    """(number, remaining text) if the line opens a section: bold `N.` at the indent."""
    lead = ""
    i = 0
    while i < len(ln.spans) and ln.spans[i].bold:
        lead += ln.spans[i].text
        i += 1
    if ln.x0 >= 160 or not re.fullmatch(r"\s*\d+[A-Z]?\.?\s*", lead):
        return None
    whole = ln.text
    m = re.match(r"^(\d+[A-Z]?)\.\s*", whole)
    if not m:
        return None
    return m.group(1), whole[m.end():]


def assign_margin_notes(lines: list[Line], starts: list[float]) -> dict[float, str]:
    """Map section-start y -> joined side-note text (notes sit level with the section)."""
    notes: dict[float, str] = {}
    for ln in sorted(lines, key=lambda l: l.y):
        owner = max((y for y in starts if y - 5 <= ln.y), default=None)
        if owner is None:
            continue
        notes[owner] = join_text(notes.get(owner, ""), ln.text)
    return notes


def extract_page(page: pymupdf.Page, pno: int, prev_tail: tuple[str, str]) -> tuple[list[str], tuple[str, str]]:
    """Blocks for one page, plus (prefix, text) of its last paragraph for the next page."""
    spans = page_spans(page)
    top = 540 if pno == 1 else 75
    spans = [s for s in spans if s.y > top]
    body = [s for s in spans if BODY_X_MIN <= s.x0 < BODY_X_MAX]
    margin = [s for s in spans if not (BODY_X_MIN <= s.x0 < BODY_X_MAX)]

    lines = cluster_lines(body)
    lines = [ln for ln in lines if not re.match(r"^(UPLOADED BY|AND PUBLISHED BY|MGIPMRND)", ln.text)]

    margin_lines = cluster_lines([s for s in margin if s.x0 < BODY_X_MIN]) + cluster_lines(
        [s for s in margin if s.x0 >= BODY_X_MAX]
    )
    refs: list[tuple[float, str]] = []
    note_lines: list[Line] = []
    for ln in margin_lines:
        # Act citations ("45 of 1860.") are margin lines of their own, not side-notes.
        if REF_RE.match(ln.text):
            refs.append((ln.y, ln.text))
        elif not re.match(r"^(MGIPMRND|UPLOADED BY|AND PUBLISHED BY)", ln.text):
            note_lines.append(ln)
    starts = [ln.y for ln in lines if section_start(ln)]
    notes = assign_margin_notes(note_lines, starts)

    out: list[str] = []
    # Current paragraph: [prefix, text]
    para: list | None = None
    para_lines_y: list[float] = []
    pending_refs = sorted(refs)
    last_kind: str | None = None

    def flush() -> None:
        nonlocal para, para_lines_y
        if para is None:
            return
        out.append(f"{para[0]}| {para[1]}")
        lo, hi = para_lines_y[0] - 4, para_lines_y[-1] + 4
        for ref in list(pending_refs):
            if lo <= ref[0] <= hi:
                out.append(f"@REF {ref[1]}")
                pending_refs.remove(ref)
        para = None
        para_lines_y = []

    prev_y: float | None = None
    prev_x0 = 999.0
    first_block = True
    for ln in lines:
        text = ln.text
        gap = (ln.y - prev_y) if prev_y is not None else 999.0
        # Continuation lines are never indented deeper than the line above them.
        indent_jump = ln.x0 > prev_x0 + 12
        prev_y = ln.y
        prev_x0 = ln.x0
        if text == "—————" or re.fullmatch(r"[_—–-]+", text):
            flush()
            continue

        if pno == 1 and text.startswith("THE BHARATIYA NYAYA SANHITA"):
            flush(); out.append(f"@TITLE {text}"); continue
        if pno == 1 and re.fullmatch(r"NO\. ?\d+ OF \d{4}", text):
            flush(); out.append(f"@ACTNO {text}"); continue
        if pno == 1 and re.fullmatch(r"\[\d+th December, \d{4}\.\]", text):
            flush(); out.append(f"@DATE {text}"); continue
        if text.startswith("DIWAKAR SINGH"):
            flush(); out.append(f"@SIGNATURE {text}"); last_kind = "sig"; continue
        if last_kind == "sig":
            if gap <= PARA_GAP:
                out[-1] = out[-1] + " " + text
            continue

        m = re.fullmatch(r"CHAPTER ([IVXLC]+)", text) if ln.centered else None
        if m:
            flush(); out.append(f"@CHAPTER {m.group(1)}"); last_kind = "chapter"; first_block = False; continue
        # Chapter titles are small caps; long ones are too wide to pass the centering test.
        if last_kind in ("chapter", "chapter-title") and not ln.italic and text.upper() == text and not section_start(ln):
            if last_kind == "chapter-title":
                out[-1] = out[-1] + " " + text
            else:
                out.append(f"@CHAPTER-TITLE {text}")
            last_kind = "chapter-title"
            continue
        if ln.centered and ln.italic:
            if ILLUS_RE.match(text):
                flush(); out.append(f"@ILLUSTRATION {text}"); last_kind = "illus"; first_block = False; continue
            if last_kind == "heading" and gap <= PARA_GAP:
                out[-1] = join_text(out[-1], text)
            else:
                flush(); out.append(f"@HEADING {text}")
            last_kind = "heading"
            first_block = False
            continue

        sec = section_start(ln)
        if sec:
            flush()
            num, rest = sec
            out.append(f"@SECTION {num} | {notes.get(ln.y, '')}")
            para = ["P1", rest]
            para_lines_y = [ln.y]
            last_kind = "para"
            first_block = False
            continue

        # The long title on page 1 is set with a hanging indent.
        hanging = para is not None and para[1].startswith("An Act to") and pno == 1
        starts_new = gap > PARA_GAP or (indent_jump and not hanging) or para is None
        if first_block and para is None:
            # Top of page: an unlabelled block continues the previous page's last
            # paragraph if that stopped without closing punctuation, or if it is
            # set flush-left (fresh paragraphs open indented) after a P0/P1 block.
            first_block = False
            tail_kind, tail_text = prev_tail
            open_tail = bool(tail_text) and not re.search(r"[.;:—–]$", tail_text)
            flush_cont = ln.x0 < 130 and tail_kind in ("P0", "P1", "C")
            if tail_text and not CONT_START_RE.match(text) and (open_tail or flush_cont):
                para = ["C", text]
                para_lines_y = [ln.y]
                last_kind = "para"
                continue
        first_block = False
        if starts_new:
            flush()
            para = [indent_level(ln.x0), text]
            para_lines_y = [ln.y]
        else:
            para[1] = join_text(para[1], text)
            para_lines_y.append(ln.y)
        last_kind = "para"
    tail = (para[0], para[1]) if para is not None and last_kind == "para" else ("", "")
    if tail[0] == "C":
        tail = (prev_tail[0], tail[1])
    flush()
    for ref in pending_refs:
        out.append(f"@REF {ref[1]}")
    return out, tail


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(GAZETTE_PDF)
    prev_tail = ("", "")
    for i, page in enumerate(doc):
        blocks, prev_tail = extract_page(page, i + 1, prev_tail)
        (OUT_DIR / f"page-{i + 1:03d}.txt").write_text("\n".join(blocks) + "\n", encoding="utf-8")
    print(f"wrote {doc.page_count} pages to {OUT_DIR}")


if __name__ == "__main__":
    main()
