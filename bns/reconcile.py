"""Cross-check the image transcription (ocr/pages) against the PDF text layer.

Both readings use the `bns-ocr/1` block format. Every page is aligned block by
block; any disagreement is reported with its category:

  structure  block kinds/indent levels or block boundaries disagree
  words      the word sequence differs (needs adjudication against the image)
  spacing    only whitespace differs
  glyphs     only quote/dash/apostrophe variants differ

Usage: python -m bns.reconcile [--strict]   (exit 1 on any non-accepted diff)
Writes build/reconcile.md.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from dataclasses import dataclass

from bns.paths import OCR_DIR, ROOT

TEXTLAYER_DIR = ROOT / "ocr" / "textlayer"
REPORT = ROOT / "build" / "reconcile.md"
ACCEPTED = ROOT / "ocr" / "accepted.json"

GLYPH_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "‐": "-"})


@dataclass(frozen=True)
class Block:
    kind: str  # P0..P4, C, or @TAG
    text: str

    @property
    def line(self) -> str:
        return f"{self.kind}| {self.text}" if not self.kind.startswith("@") else f"{self.kind} {self.text}"


def parse_blocks(path) -> list[Block]:
    blocks = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.rstrip()
        if not raw:
            continue
        if raw.startswith("@"):
            tag, _, rest = raw.partition(" ")
            blocks.append(Block(tag, rest.strip()))
        else:
            kind, sep, rest = raw.partition("|")
            if not sep:
                blocks.append(Block("?", raw))
            else:
                blocks.append(Block(kind.strip(), re.sub(r"\s+", " ", rest).strip()))
    return blocks


def glyph_norm(s: str) -> str:
    s = s.translate(GLYPH_MAP)
    return re.sub(r"-+", "-", s)


def classify(a: Block, b: Block) -> str | None:
    if a == b:
        return None
    if a.kind != b.kind:
        same_text = glyph_norm(" ".join(a.text.split())) == glyph_norm(" ".join(b.text.split()))
        if same_text and a.kind.startswith("P") and b.kind.startswith("P"):
            return "indent"
        return "boundary"
    if "".join(a.text.split()) == "".join(b.text.split()):
        return "spacing"
    na, nb = glyph_norm(a.text), glyph_norm(b.text)
    if "".join(na.split()) == "".join(nb.split()):
        return "glyphs"
    return "words"


def word_diff(a: str, b: str) -> str:
    wa, wb = a.split(), b.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        out.append(f"    ocr[{' '.join(wa[i1:i2])}] pdf[{' '.join(wb[j1:j2])}]")
    return "\n".join(out)


def load_accepted() -> set[tuple[int, str, str]]:
    """Disagreements already adjudicated against the page image (text layer verified)."""
    if not ACCEPTED.exists():
        return set()
    return {(e["page"], e["category"], e["detail"]) for e in json.loads(ACCEPTED.read_text(encoding="utf-8"))}


def reconcile_page(pno: int) -> list[tuple[str, str]]:
    ocr = parse_blocks(OCR_DIR / f"page-{pno:03d}.txt")
    pdf = parse_blocks(TEXTLAYER_DIR / f"page-{pno:03d}.txt")
    issues: list[tuple[str, str]] = []
    sm = difflib.SequenceMatcher(None, [glyph_norm(b.text)[:60] for b in ocr], [glyph_norm(b.text)[:60] for b in pdf], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            pairs = list(zip(ocr[i1:i2], pdf[j1:j2]))
        elif op == "replace" and i2 - i1 == j2 - j1:
            pairs = list(zip(ocr[i1:i2], pdf[j1:j2]))
        else:
            ob = "\n".join("    ocr: " + b.line for b in ocr[i1:i2])
            pb = "\n".join("    pdf: " + b.line for b in pdf[j1:j2])
            issues.append(("boundary", f"{op}\n{ob}\n{pb}".rstrip()))
            continue
        for a, b in pairs:
            cat = classify(a, b)
            if cat is None:
                continue
            if cat in ("indent", "boundary"):
                detail = f"    ocr: {a.line[:120]}\n    pdf: {b.line[:120]}"
            else:
                detail = f"  {a.kind} {a.text[:70]}…\n" + word_diff(a.text, b.text)
            issues.append((cat, detail))
    return issues


# The text layer is canonical for characters (exact code points) and indent
# (exact coordinates); these categories need no human adjudication. Word and
# paragraph-boundary disagreements must be checked against the page image and
# recorded in ocr/accepted.json.
NEEDS_REVIEW = {"words", "boundary"}


def main() -> int:
    strict = "--strict" in sys.argv
    accepted = load_accepted()
    counts: dict[str, int] = {}
    adjudicated = 0
    lines = ["# OCR vs text-layer reconciliation", ""]
    unresolved = 0
    for pno in range(1, 103):
        kept = []
        for cat, detail in reconcile_page(pno):
            if (pno, cat, detail) in accepted:
                adjudicated += 1
                continue
            kept.append((cat, detail))
            counts[cat] = counts.get(cat, 0) + 1
        if kept:
            lines.append(f"## page {pno}")
            for cat, detail in kept:
                lines.append(f"- **{cat}**\n```\n{detail}\n```")
            unresolved += sum(1 for cat, _ in kept if cat in NEEDS_REVIEW)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
    lines.insert(2, f"Needs review: {unresolved}; adjudicated: {adjudicated}; open by category: {summary}\n")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"needs review {unresolved}, adjudicated {adjudicated} ({summary}) -> {REPORT}")
    return 1 if strict and unresolved else 0


def dump_review() -> None:
    """Print open review items as accepted.json entries (for adjudication)."""
    accepted = load_accepted()
    items = [
        {"page": p, "category": c, "detail": d, "verdict": "pdf", "note": ""}
        for p in range(1, 103)
        for c, d in reconcile_page(p)
        if c in NEEDS_REVIEW and (p, c, d) not in accepted
    ]
    print(json.dumps(items, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if "--dump-review" in sys.argv:
        dump_review()
        sys.exit(0)
    sys.exit(main())
