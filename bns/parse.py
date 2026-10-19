"""Build the provision tree (data/bns.json) from reconciled page blocks.

Input: ocr/textlayer/page-NNN.txt (`bns-ocr/1` format, see ocr/SPEC.md),
which `bns.reconcile --strict` has verified against the image transcription.
Output schema and citation ids: docs/DATA_MODEL.md.

Usage: python -m bns.parse
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bns.paths import DATA_DIR, GAZETTE_PDF, ROOT
from bns.reconcile import TEXTLAYER_DIR, Block, parse_blocks

PAGES = 102
SOURCE_URL = "https://prsindia.org/files/bills_acts/bills_parliament/2023/The%20Bharatiya%20Nyaya%20Sanhita%2C%202023.pdf"

LABEL_RE = re.compile(r"^\((\d+[A-Z]?|[ivxlc]+|[a-z]{1,2}|[A-Z]{1,2})\)\s*")
EXPL_RE = re.compile(r"^(Explanation)(?:\s+(\d+))?\s*\.?\s*([—–-]+|:)\s*")
EXC_RE = re.compile(r"^(Exception)(?:\s+(\d+))?\s*\.?\s*([—–-]+|:)\s*")
ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth"]


def roman_value(s: str) -> int | None:
    if not s or any(ch not in ROMAN for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        v = ROMAN[ch]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    return total


def int_to_roman(n: int) -> str:
    out = ""
    for v, sym in ((100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += sym
            n -= v
    return out


def label_kind_candidates(v: str) -> list[str]:
    if re.fullmatch(r"\d+[A-Z]?", v):
        return ["num"]
    if re.fullmatch(r"[A-Z]{1,2}", v):
        return ["upper"]
    kinds = []
    if re.fullmatch(r"[a-z]", v) or re.fullmatch(r"([a-z])\1", v):
        kinds.append("alpha")
    if roman_value(v) is not None and int_to_roman(roman_value(v)) == v:
        kinds.append("roman")
    return kinds


def ordinal(kind: str, v: str) -> int:
    if kind == "num":
        return int(re.match(r"\d+", v).group())
    if kind == "roman":
        return roman_value(v)
    if kind == "alpha":
        return (ord(v[0]) - 96) + (26 if len(v) == 2 else 0)
    return ord(v[0]) - 64 + (26 if len(v) == 2 else 0)


def is_successor(kind: str, prev: str, v: str) -> bool:
    return ordinal(kind, v) == ordinal(kind, prev) + 1


INDENT = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


@dataclass
class Node:
    kind: str
    label: str | None
    text: str
    page: int
    indent: int
    num: str | None = None  # label value for numbered nodes
    lkind: str | None = None  # num/alpha/roman/upper for numbered nodes
    children: list["Node"] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    container: bool = False  # explanation/exception/proviso/illustrations: scopes nested lists
    parent: "Node | None" = None
    id: str = ""
    cite: str | None = None
    xnum: str | None = None  # printed number of explanation/exception


@dataclass
class Para:
    kind: str  # P0..P4
    text: str
    page: int


class ParseError(Exception):
    pass


class SectionBuilder:
    """Turns the paragraphs of one section into a provision tree."""

    def __init__(self, num: str, heading: str, page: int, warn):
        self.root = Node("section", None, "", page, indent=1)
        self.num = num
        self.heading = heading
        self.pages = [page]
        self.stack: list[Node] = [self.root]
        self.warn = warn
        self.illus_pending: tuple[str, int] | None = None
        self.illus: Node | None = None
        self.first = True
        self.source: list[str] = []  # every printed string fed in, for the completeness check

    # -- helpers ---------------------------------------------------------
    def attach(self, parent: Node, node: Node) -> Node:
        node.parent = parent
        parent.children.append(node)
        while self.stack[-1] is not parent:
            self.stack.pop()
        self.stack.append(node)
        return node

    def deepest(self, pred) -> Node:
        for n in reversed(self.stack):
            if pred(n):
                return n
        return self.root

    def end_illustrations(self) -> None:
        if self.illus is not None:
            while self.stack[-1] is not self.illus:
                self.stack.pop()
            self.stack.pop()
        self.illus = None
        self.illus_pending = None

    # -- paragraph dispatch ----------------------------------------------
    def add_illustration_heading(self, label: str, page: int) -> None:
        self.end_illustrations()
        self.illus_pending = (label, page)
        self.source.append(label)

    def add_ref(self, ref: str) -> None:
        self.stack[-1].refs.append(ref)

    def add(self, p: Para) -> None:
        if p.page not in self.pages:
            self.pages.append(p.page)
        indent = INDENT[p.kind]
        self.source.append(p.text)
        text = p.text
        first = self.first
        self.first = False

        m = LABEL_RE.match(text)
        if m:
            self.add_labelled(m.group(1), text[m.end():], p.page, indent, first)
            return
        if EXPL_RE.match(text) or EXC_RE.match(text):
            self.end_illustrations()
            mm = EXPL_RE.match(text) or EXC_RE.match(text)
            kind = "explanation" if mm.group(1) == "Explanation" else "exception"
            # An Exception closes earlier explanations/provisos/exceptions; an
            # Explanation closes provisos/explanations but stays inside an Exception
            # (e.g. the Explanation to Exception 4 of section 101).
            closes = {"explanation", "exception", "proviso"} if kind == "exception" else {"explanation", "proviso"}
            self.pop_containers(indent, kinds=closes)
            parent = self.deepest(lambda n: n.indent <= indent)
            label = text[: mm.end()].rstrip()
            node = Node(kind, label, text[mm.end():], p.page, indent, container=True, xnum=mm.group(2))
            self.attach(parent, node)
            return
        if text.startswith("Provided"):
            self.end_illustrations()
            self.pop_containers(indent, kinds={"explanation", "proviso"})
            parent = self.deepest(lambda n: n.indent <= indent)
            self.attach(parent, Node("proviso", None, text, p.page, indent, container=True))
            return
        if self.illus_pending or self.illus is not None:
            self.add_illustration(None, text, p.page, indent)
            return
        # Unlabelled text: a node's wrapped lines sit one level left of its first
        # line, so text resuming at level k belongs to the node opened at k+1.
        parent = self.deepest(lambda n: n.indent == indent + 1 and n.kind != "illustrations")
        if parent is self.root and indent + 1 != self.root.indent:
            parent = self.deepest(lambda n: n.indent <= indent + 1 and n.kind != "illustrations")
        node = Node("text", None, text, p.page, indent)
        node.parent = parent
        parent.children.append(node)
        while self.stack[-1] is not parent:
            self.stack.pop()

    def pop_containers(self, indent: int, kinds: set[str]) -> None:
        """Close numbered nodes indented deeper than `indent`, then the given containers at/below it."""
        while len(self.stack) > 1:
            top = self.stack[-1]
            if (not top.container and top.indent > indent) or (top.kind in kinds and top.indent >= indent):
                self.stack.pop()
            else:
                break

    def add_illustration(self, label: str | None, text: str, page: int, indent: int) -> None:
        if self.illus is None:
            heading, hpage = self.illus_pending
            # Illustrations illustrate the provision itself even when printed after
            # its Explanations, provisos or a lone unnumbered Exception (ss. 126(1),
            # 249, 309(3), 316(1)); numbered Exceptions keep their own (ss. 101, 356).
            parent = self.deepest(
                lambda n: n.indent <= indent
                and n.kind not in ("illustration", "explanation", "proviso")
                and not (n.kind == "exception" and n.xnum is None)
            )
            self.illus = self.attach(parent, Node("illustrations", heading, "", hpage, indent, container=True))
            self.illus_pending = None
        while self.stack[-1] is not self.illus:
            self.stack.pop()
        if label is None and self.illus.children and self.illus.children[-1].label is not None:
            # Further paragraph of a lettered illustration.
            item = self.illus.children[-1]
            item.children.append(Node("text", None, text, page, indent, parent=item))
            return
        item = Node("illustration", f"({label})" if label else None, text, page, indent, num=label)
        item.parent = self.illus
        self.illus.children.append(item)

    def add_labelled(self, v: str, rest: str, page: int, indent: int, first: bool) -> None:
        # Chained labels: "(6) (a) The imprisonment …" opens two levels at once.
        chain = [v]
        while True:
            m = LABEL_RE.match(rest)
            if not m:
                break
            chain.append(m.group(1))
            rest = rest[m.end():]
        for i, lv in enumerate(chain):
            self.add_one_label(lv, rest if i == len(chain) - 1 else "", page, indent if i == 0 else indent + 1, first and i == 0)

    def is_illustration_item(self, v: str, cands: list[str]) -> bool:
        items = [c for c in self.illus.children if c.num] if self.illus else []
        if not items:
            return v in ("a", "1")
        last = items[-1].num
        kind = "num" if last.isdigit() else "alpha"
        return kind in cands and is_successor(kind, last, v)

    def add_one_label(self, v: str, text: str, page: int, indent: int, first: bool) -> None:
        cands = label_kind_candidates(v)
        if not cands:
            raise ParseError(f"s.{self.num}: unrecognised label ({v})")

        # Inside illustrations, (a)/(b)… or (1)/(2)… paragraphs are illustration
        # items unless they continue a provision list opened outside the block.
        if self.illus_pending or self.illus is not None:
            outer = self.find_sibling(v, cands, indent, stop_at=self.illus)
            if outer is None and self.is_illustration_item(v, cands):
                self.add_illustration(v, text, page, indent)
                return
            self.end_illustrations()

        sib = self.find_sibling(v, cands, indent)
        if sib is not None:
            node = Node("", f"({v})", text, page, indent, num=v, lkind=sib.lkind)
            self.attach(sib.parent, node)
            return
        # New list: must start at its first value.
        kinds = [k for k in cands if ordinal(k, v) == 1]
        if not kinds:
            self.warn(f"s.{self.num}: ({v}) does not continue any open list; nested under {self.stack[-1].id or self.stack[-1].kind}")
            kinds = cands
        # Prefer roman for (i) when an alpha list is open but (i) is not its successor.
        kind = "roman" if "roman" in kinds and v == "i" else kinds[0]
        parent = self.stack[-1]
        # A list cannot open beneath a deeper-indented node: climb to the indent.
        while parent is not self.root and parent.indent >= indent and not parent.container:
            parent = parent.parent
        if parent.container and parent.indent > indent:
            parent = self.deepest(lambda n: n.indent < indent or n is self.root)
        node = Node("", f"({v})", text, page, indent, num=v, lkind=kind)
        if first:
            node.indent = 1
        self.attach(parent, node)

    def find_sibling(self, v: str, cands: list[str], indent: int, stop_at: Node | None = None) -> Node | None:
        """Open numbered node that `(v)` continues (same kind, previous value)."""
        best = None
        for n in reversed(self.stack):
            if n is stop_at:
                break
            if n.lkind in cands and is_successor(n.lkind, n.num, v):
                # Indentation must not contradict (allow ±1 for the section-line case).
                if abs(n.indent - indent) <= 1:
                    best = n
                    break
        if best is None:
            return None
        # (i) after (h) is a letter; (i) opening a sub-list under (h) is roman —
        # decided by indent: a sub-list is indented deeper than its parent.
        if v in ("i", "v", "x") and best.lkind == "alpha" and indent > best.indent:
            return None
        return best


# ---------------------------------------------------------------------------
# id / cite assignment


def level_names(sec_root: Node) -> list[str]:
    first_numbered = next((c for c in sec_root.children if c.lkind), None)
    if first_numbered is not None and sec_root.children and sec_root.children[0] is first_numbered:
        return ["subsection", "clause", "subclause", "item", "item"]
    return ["clause", "subclause", "item", "item", "item"]


def regroup_explanation_illustrations(node: Node) -> None:
    """Give alternating Explanation/Illustrations blocks to their Explanations.

    Illustrations attach to the provision by default: printed after a single
    Explanation they still illustrate the provision (ss. 309(3), 316(1), 318(1),
    Exception 1 of s. 101). When two or more Explanations are each followed by
    their own Illustrations (ss. 2(8), 46), each block belongs to the
    Explanation just before it.
    """
    kids = node.children
    pairs = [i for i in range(1, len(kids)) if kids[i].kind == "illustrations" and kids[i - 1].kind == "explanation"]
    if len(pairs) >= 2:
        for i in reversed(pairs):
            block = kids.pop(i)
            block.parent = kids[i - 1]
            kids[i - 1].children.append(block)
    for c in kids:
        regroup_explanation_illustrations(c)

SECTION_WIDE_RE = re.compile(r"\bthis section\b", re.I)


def hoist_section_explanations(root: Node) -> None:
    """Explanations closing a section that speak of "this section" belong to it.

    They are printed after the last sub-section at sub-section indentation, so
    layout alone files them under that sub-section (ss. 122, 124). Text that
    names "this sub-section" stays where it is (s. 64(2)).
    """
    if not root.children or not root.children[-1].lkind:
        return
    last = root.children[-1]
    for k, c in enumerate(last.children):
        if c.kind == "explanation" and SECTION_WIDE_RE.search(c.text):
            moved = last.children[k:]
            del last.children[k:]
            for m in moved:
                m.parent = root
            root.children.extend(moved)
            return



def finalize(sec: SectionBuilder) -> dict:
    hoist_section_explanations(sec.root)
    regroup_explanation_illustrations(sec.root)
    names = level_names(sec.root)
    seen: set[str] = set()

    def uniq(i: str) -> str:
        base, n = i, 2
        while i in seen:
            i = f"{base}-{n}"
            n += 1
        seen.add(i)
        return i

    def walk(node: Node, base_id: str, base_cite: str, depth: int, under_container: bool) -> list[dict]:
        out = []
        counts: dict[str, int] = {}
        provisos = [c for c in node.children if c.kind == "proviso"]
        text_n = 0
        illus_items = [c for c in node.children if c.kind == "illustration"]
        for c in node.children:
            d: dict = {}
            if c.lkind:
                lvl = names[min(depth, len(names) - 1)] if not under_container else ["clause", "subclause", "item", "item"][min(depth, 3)]
                c.kind = lvl
                cid = uniq(f"{base_id}({c.num})")
                if base_cite.startswith("Section "):
                    cite = f"{base_cite}({c.num})"
                else:
                    cite = f"{base_cite}, ({c.num})" if under_container else f"{base_cite}({c.num})"
                kids = walk(c, cid, cite, depth + 1, under_container)
            elif c.kind == "proviso":
                i = provisos.index(c) + 1
                cid = uniq(f"{base_id}-proviso-{i}")
                word = "Proviso" if len(provisos) == 1 else f"{ORDINALS[i - 1]} proviso"
                cite = f"{word} to {base_cite}"
                kids = walk(c, cid, cite, 0, True)
            elif c.kind in ("explanation", "exception"):
                tag = "expl" if c.kind == "explanation" else "exc"
                cid = uniq(f"{base_id}-{tag}" + (f"-{c.xnum}" if c.xnum else ""))
                word = "Explanation" if c.kind == "explanation" else "Exception"
                cite = f"{word}{' ' + c.xnum if c.xnum else ''} to {base_cite}"
                kids = walk(c, cid, cite, 0, True)
            elif c.kind == "illustrations":
                cid = uniq(f"{base_id}-illustrations")
                cite = f"Illustrations to {base_cite}"
                kids = walk(c, base_id, base_cite, depth, under_container)
            elif c.kind == "illustration":
                if c.num:
                    cid = uniq(f"{base_id}-illus-{c.num}")
                    cite = f"Illustration ({c.num}) to {base_cite}"
                elif len(illus_items) == 1:
                    cid = uniq(f"{base_id}-illus")
                    cite = f"Illustration to {base_cite}"
                else:
                    k = illus_items.index(c) + 1
                    cid = uniq(f"{base_id}-illus-{k}")
                    cite = f"Illustration {k} to {base_cite}"
                kids = walk(c, cid, cite, 0, True)
            elif c.kind == "text":
                text_n += 1
                cid = uniq(f"{base_id}-text-{text_n}")
                cite = None
                kids = []
            else:
                raise ParseError(f"unknown node kind {c.kind}")
            d = {"kind": c.kind, "label": c.label, "text": c.text, "id": cid, "cite": cite, "page": c.page}
            if c.refs:
                d["refs"] = c.refs
            if kids:
                d["children"] = kids
            out.append(d)
        return out

    seen.add(sec.num)
    content = walk(sec.root, sec.num, f"Section {sec.num}", 0, False)
    check_complete(sec, content)
    return {"num": sec.num, "id": sec.num, "heading": sec.heading, "pages": sec.pages, "content": content, "refs": sec.root.refs}


def check_complete(sec: SectionBuilder, content: list[dict]) -> None:
    """The tree, read depth-first, must reproduce the printed text exactly."""

    def flat(nodes):
        for n in nodes:
            yield (n["label"] or "") + n["text"]
            yield from flat(n.get("children", []))

    squash = lambda parts: re.sub(r"\s+", "", "".join(parts))
    got, want = squash(flat(content)), squash(sec.source)
    if got != want:
        i = next((k for k, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        raise ParseError(f"s.{sec.num}: tree text diverges from print at …{want[max(0, i - 40):i + 40]}… (tree: …{got[max(0, i - 40):i + 40]}…)")


# ---------------------------------------------------------------------------


def load_paragraphs() -> list[tuple[Block, int]]:
    """All blocks in order with their page; `C|` blocks merged into their predecessor."""
    out: list[tuple[Block, int]] = []
    for pno in range(1, PAGES + 1):
        for b in parse_blocks(TEXTLAYER_DIR / f"page-{pno:03d}.txt"):
            if b.kind == "C":
                for k in range(len(out) - 1, -1, -1):
                    prev, ppage = out[k]
                    if not prev.kind.startswith("@") or prev.kind == "@SECTION":
                        break
                if out[k][0].kind.startswith("@"):
                    raise ParseError(f"page {pno}: continuation without a paragraph to continue")
                joined = prev.text + b.text if prev.text.endswith("-") else prev.text + " " + b.text
                out[k] = (Block(prev.kind, joined), ppage)
                continue
            out.append((b, pno))
    return out


def build() -> tuple[dict, list[str]]:
    warnings: list[str] = []
    data: dict = {"preamble": {}, "chapters": [], "sections": {}, "order": []}
    chapter: dict | None = None
    group: dict | None = None
    sec: SectionBuilder | None = None

    def close_section() -> None:
        nonlocal sec
        if sec is None:
            return
        s = finalize(sec)
        s["chapter"] = chapter["num"]
        s["group"] = group["title"] if group else None
        if not s["refs"]:
            del s["refs"]
        data["sections"][s["num"]] = s
        data["order"].append(s["num"])
        chapter["sections"].append(s["num"])
        if group:
            group["sections"].append(s["num"])
        sec = None

    paras = load_paragraphs()
    for b, page in paras:
        k = b.kind
        if k == "@TITLE":
            data["preamble"]["title"] = b.text
        elif k == "@ACTNO":
            data["preamble"]["act_no"] = b.text
        elif k == "@DATE":
            data["preamble"]["date"] = b.text
            data["preamble"]["page"] = page
        elif k == "@CHAPTER":
            close_section()
            group = None
            chapter = {"id": f"chapter-{b.text}", "num": b.text, "n": len(data["chapters"]) + 1, "title": "", "page": page, "sections": [], "groups": []}
            data["chapters"].append(chapter)
        elif k == "@CHAPTER-TITLE":
            chapter["title"] = b.text
        elif k == "@HEADING":
            close_section()
            group = {"title": b.text, "sections": []}
            chapter["groups"].append(group)
        elif k == "@SECTION":
            close_section()
            num, _, heading = b.text.partition("|")
            num, heading = num.strip(), heading.strip()
            if not heading:
                raise ParseError(f"s.{num}: missing marginal heading")
            sec = SectionBuilder(num, heading, page, warnings.append)
        elif k == "@ILLUSTRATION":
            sec.add_illustration_heading(b.text, page)
        elif k == "@REF":
            if sec is None:
                raise ParseError(f"page {page}: margin ref outside a section")
            sec.add_ref(b.text)
        elif k == "@SIGNATURE":
            close_section()
            data["signature"] = b.text
        elif k.startswith("@"):
            raise ParseError(f"page {page}: unexpected tag {k}")
        else:
            if sec is None:
                if "long_title" not in data["preamble"]:
                    data["preamble"]["long_title"] = b.text
                else:
                    data["preamble"]["enacting_formula"] = b.text
                continue
            sec.add(Para(k, b.text, page))
    close_section()
    return data, warnings


def validate(data: dict) -> list[str]:
    errors = []
    order = data["order"]
    expect = [str(i) for i in range(1, 359)]
    if order != expect:
        errors.append(f"section order mismatch: {len(order)} sections")
    romans = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]
    if [c["num"] for c in data["chapters"]] != romans:
        errors.append("chapter numbering mismatch")
    ids: set[str] = set()

    def walk(nodes, sec):
        for n in nodes:
            if n["id"] in ids:
                errors.append(f"duplicate id {n['id']}")
            ids.add(n["id"])
            if n["kind"] in ("text", "illustration") and n["label"] is None and LABEL_RE.match(n["text"]):
                errors.append(f"{n['id']}: unlabelled node starts with a label")
            if not n["text"] and not n.get("children") and n["kind"] != "illustrations":
                errors.append(f"empty node {n['id']}")
            walk(n.get("children", []), sec)

    for num in order:
        s = data["sections"][num]
        ids.add(s["id"])
        if not s["content"]:
            errors.append(f"s.{num}: no content")
        walk(s["content"], num)
    for c in data["chapters"]:
        if not c["title"]:
            errors.append(f"chapter {c['num']}: no title")
    for key in ("title", "act_no", "date", "long_title", "enacting_formula"):
        if key not in data["preamble"]:
            errors.append(f"preamble.{key} missing")
    return errors


def main() -> int:
    data, warnings = build()
    errors = validate(data)
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    for e in errors:
        print("error:", e, file=sys.stderr)
    if errors:
        return 1
    meta = {
        "title": "The Bharatiya Nyaya Sanhita, 2023",
        "short": "BNS",
        "act": "Act No. 45 of 2023",
        "assented": "2023-12-25",
        "in_force": "2024-07-01",
        # Commencement notification; not part of the Gazette text itself.
        "commencement": {
            "notification": "S.O. 850(E), dated 23 February 2024",
            "date": "2024-07-01",
            "not_in_force": ["106(2)"],
        },
        "text_as_of": "As enacted (Gazette of 25 December 2023); later amendments, if any, are not incorporated.",
        "source": {
            "file": str(GAZETTE_PDF.relative_to(ROOT)),
            "sha256": hashlib.sha256(GAZETTE_PDF.read_bytes()).hexdigest(),
            "gazette": "The Gazette of India, Extraordinary, Part II—Section 1, No. 53, New Delhi, 25 December 2023 (CG-DL-E-25122023-250883)",
            "url": SOURCE_URL,
            "pages": PAGES,
        },
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    out = {"meta": meta, **data}
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / "bns.json"
    # Keep the previous timestamp when nothing else changed, so rebuilds are byte-identical.
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        stamp = prev.get("meta", {}).get("generated")
        if stamp and {**prev, "meta": {**prev["meta"], "generated": meta["generated"]}} == out:
            meta["generated"] = stamp
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n_nodes = sum(1 for _ in iter_nodes(out))
    print(f"{len(out['order'])} sections, {len(out['chapters'])} chapters, {n_nodes} nodes, {len(warnings)} warnings -> {path}")
    return 0


def iter_nodes(data: dict):
    def walk(nodes):
        for n in nodes:
            yield n
            yield from walk(n.get("children", []))

    for num in data["order"]:
        yield from walk(data["sections"][num]["content"])


if __name__ == "__main__":
    sys.exit(main())
