"""Static site generator: ``python -m bns.site [--data PATH] [--out DIR]``.

Reads the structured Act (``data/bns.json``, see ``docs/DATA_MODEL.md``) and
writes a self-contained static site to ``dist/``. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
from datetime import date
from html import escape
from pathlib import Path

from .paths import DATA_DIR, DIST_DIR, GAZETTE_PDF, ROOT, WEB_DIR

SITE = "Bharatiya Nyaya Sanhita, 2023"
TITLE_SUFFIX = " | BNS 2023"
PDF_PATH = "/source/bns-2023-gazette.pdf"
# Appended in JS to the long citation form stored on every pilcrow (`data-l`).
LONG_SUFFIX = " of the Bharatiya Nyaya Sanhita, 2023"
# The only inline script (no-flash JS class + saved theme); its hash is pinned in the CSP (web/_headers).
INLINE_JS = 'document.documentElement.className="js";try{var t=localStorage.getItem("theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}'

NUMBERED = {"subsection": "sub-section", "clause": "clause", "subclause": "sub-clause", "item": "item"}
# Long-form connectors: "clause (a) OF sub-section (1)", "Explanation 1 TO section 2(4)".
ANNEX = {"proviso", "explanation", "exception", "illustration"}
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]
STRUCT_ID = re.compile(r"\d+(?:\([0-9A-Za-z]+\))*")
SMALL_WORDS = {"of", "the", "and", "to", "in", "for", "or", "a", "an", "by", "with", "on", "against", "relating", "at"}


def esc(s: str) -> str:
    return escape(s, quote=True)


def title_case(s: str) -> str:
    words = s.lower().split(" ")
    return " ".join(w if (i and w in SMALL_WORDS) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def sec_url(num: str) -> str:
    return f"/section-{num}/"


def node_url(num: str, nid: str) -> str:
    return sec_url(num) if nid == num else f"{sec_url(num)}#p-{nid}"


# --------------------------------------------------------------------------- data model


class Act:
    """Indexes the JSON: node lookup by id, ancestry, long-form citations."""

    def __init__(self, data: dict):
        self.data = data
        self.meta = data["meta"]
        self.sections: dict[str, dict] = data["sections"]
        self.order: list[str] = data["order"]
        self.chapters: list[dict] = data["chapters"]
        self.chapter_by_num = {c["num"]: c for c in self.chapters}
        self.sec_chapter: dict[str, dict] = {}
        self.sec_group: dict[str, str | None] = {}
        for c in self.chapters:
            for s in c["sections"]:
                self.sec_chapter[s] = c
                self.sec_group[s] = None
            for g in c.get("groups") or []:
                for s in g["sections"]:
                    self.sec_group[s] = g["title"]
        self.pos = {n: i for i, n in enumerate(self.order)}
        # id -> (node or None for sections, section num)
        self.nodes: dict[str, tuple[dict | None, str]] = {}
        self.ancestors: dict[str, list[str]] = {}  # id -> ancestor ids, outermost first (excl. itself)
        self.long: dict[str, str] = {}  # id -> long form without LONG_SUFFIX
        self.depth: dict[str, int] = {}
        com = self.meta.get("commencement") or {}
        self.notification: str = com.get("notification") or ""
        self.not_in_force: set[str] = set(com.get("not_in_force") or [])
        self.sec_ids: dict[str, list[str]] = {}
        for num in self.order:
            sec = self.sections[num]
            self.nodes[num] = (None, num)
            self.ancestors[num] = []
            self.long[num] = f"section {num}"
            self.depth[num] = 0
            self.sec_ids[num] = []
            self._walk(sec["content"], num, [num], [])

    def _walk(self, nodes: list[dict], num: str, chain: list[str], phrases: list[tuple[str, str]]):
        provisos = [n for n in nodes if n["kind"] == "proviso"]
        for n in nodes:
            nid = n["id"]
            if nid in self.nodes:
                raise ValueError(f"duplicate node id {nid!r}")
            self.nodes[nid] = (n, num)
            self.sec_ids[num].append(nid)
            self.ancestors[nid] = list(chain)
            self.depth[nid] = len(chain)
            ph = self._phrase(n, provisos)
            own = phrases + [(ph, n["kind"])] if ph else phrases
            if ph:
                self.long[nid] = self._long_form(own, num)
            self._walk(n.get("children") or [], num, chain + [nid], own)

    @staticmethod
    def _phrase(n: dict, provisos: list[dict]) -> str | None:
        kind, label = n["kind"], n.get("label")
        if kind in NUMBERED:
            return f"{NUMBERED[kind]} {label}" if label else None
        if kind == "proviso":
            if len(provisos) == 1:
                return "the proviso"
            i = next(i for i, p in enumerate(provisos) if p is n)
            return f"the {ORDINALS[i]} proviso" if i < len(ORDINALS) else f"proviso {i + 1}"
        if kind in ("explanation", "exception"):
            core = re.sub(r"[\s.—–-]+$", "", label or kind.title())
            return f"the {core}" if core.lower() == kind else core
        if kind == "illustration":
            return f"illustration {label}" if label else "the illustration"
        return None  # text, illustrations heading

    @staticmethod
    def _long_form(phrases: list[tuple[str, str]], num: str) -> str:
        out = ""
        for ph, kind in reversed(phrases):  # innermost first
            out += ph + (" to " if kind in ANNEX else " of ")
        return out + f"section {num}"

    def nif_text(self) -> str:
        by = f" by {self.notification}" if self.notification else ""
        return f"Not yet in force — excluded from commencement{by}."

    def cite(self, nid: str) -> str:
        node, num = self.nodes[nid]
        if node is None:
            return f"Section {num}"
        if node.get("cite"):
            return node["cite"]
        for a in reversed(self.ancestors[nid]):
            an, _ = self.nodes[a]
            if an is None or an.get("cite"):
                return self.cite(a)
        return f"Section {num}"

    def resolve(self, nid: str) -> str | None:
        """Exact id, else nearest existing ancestor by stripping trailing labels; None if no section."""
        while nid not in self.nodes:
            m = re.match(r"(.*)\([0-9A-Za-z]+\)$", nid)
            if not m:
                return None
            nid = m.group(1)
        return nid


# --------------------------------------------------------------------------- cross-references

_LBL = r"\(\s*[0-9A-Za-z]{1,6}\s*\)"
_SEP = r"(?:\s*,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+)"
_DIVKW = r"(?i:sub[-–]sections?|sub[-–]clauses?|clauses?|items?)"
# "(a), (b) and (c)", "(a) to (d)", "(i) or clause (ii)": a repeated keyword continues the same list.
_LSEP = rf"(?:{_SEP}|\s+to\s+)(?:{_DIVKW}\s+)?"
_LBLLIST = rf"{_LBL}(?:{_LSEP}{_LBL})*"
_DIVP = rf"{_DIVKW}\s+{_LBLLIST}"
_NUM = r"\d{1,3}(?!\d)(?:\([0-9A-Za-z]{1,6}\))*"
_SECP = rf"(?i:sections?)\s+{_NUM}(?:(?:{_SEP}|\s+to\s+){_NUM})*"
# "the Explanation to …", "Explanation 1 to section 63", "Exception 1 of section 101".
_EXPL = r"(?P<expl>(?:the\s+)?(?P<qual>Explanation|Exception)(?:\s+(?P<explno>\d+))?\s+(?:to|of)\s+)"
REF_RE = re.compile(
    rf"\b(?:(?P<sec>(?:{_DIVP}\s+of\s+)*(?:{_EXPL}(?:{_DIVP}\s+of\s+)*)?{_SECP})"
    rf"|(?P<rel>{_DIVP}(?:\s+of\s+{_DIVP})*)"
    r"|(?P<chap>(?i:chapter)\s+(?P<roman>[IVXL]+)\b))"
)
DIV_RE = re.compile(rf"({_DIVKW})\s+({_LBLLIST})")
LBL_RE = re.compile(_LBL)
SECKW_RE = re.compile(r"(?<![-\w])(?i:sections?)\s+")
NUM_RE = re.compile(r"(\d{1,3})((?:\([0-9A-Za-z]{1,6}\))*)")
# A provision "of" anything other than this Sanhita belongs to another enactment.
INTERNAL_AFTER = re.compile(r"\s*of\s+(?:this\s+Sanhita|the\s+Bharatiya\s+Nyaya\s+Sanhita)", re.I)
EXTERNAL_AFTER = re.compile(r"\s*,?\s*(?:of|thereof)\b", re.I)


def _norm_label(s: str) -> str:
    return "(" + s[1:-1].strip() + ")"


class Linker:
    """Turns provision mentions in node text into links to existing anchors."""

    def __init__(self, act: Act):
        self.act = act

    def link(self, text: str, num: str, nid: str, href) -> str:
        out, pos = [], 0
        for m in REF_RE.finditer(text):
            after = text[m.end():]
            if EXTERNAL_AFTER.match(after) and not INTERNAL_AFTER.match(after):
                continue
            spans = self._spans(m, num, nid)
            for s, e, target in spans:
                s += m.start()
                e += m.start()
                out.append(esc(text[pos:s]))
                url, title = href(target)
                out.append(f'<a class="xr" href="{esc(url)}" title="{esc(title)}">{esc(text[s:e])}</a>')
                pos = e
        out.append(esc(text[pos:]))
        return "".join(out)

    def _target(self, num: str, suf: str, exp: str, labels: str) -> str | None:
        """Id for `labels` under section `num` (+ compact suffix), optionally inside its Explanation.

        "the Explanation to section 64" may sit under a sub-section (64(2)-expl), so an
        Explanation id is matched anywhere in the section when unique."""
        act = self.act
        if not exp:
            return act.resolve(num + suf + labels)
        while True:
            want = num + suf + exp + labels
            if want in act.nodes:
                return want
            rx = re.compile(re.escape(num + suf) + r"(?:\([0-9A-Za-z]+\))*" + re.escape(exp + labels))
            hits = [i for i in act.sec_ids[num] if rx.fullmatch(i)]
            if len(hits) == 1:
                return hits[0]
            if not labels:
                return act.resolve(num + suf)
            labels = re.sub(r"\([^()]*\)$", "", labels)

    def _spans(self, m: re.Match, num: str, nid: str) -> list[tuple[int, int, str]]:
        act = self.act
        mt = m.group(0)
        if m.group("chap"):
            ch = act.chapter_by_num.get(m.group("roman"))
            return [(0, len(mt), "chapter:" + ch["num"])] if ch else []
        divs, kws = [], []  # innermost first: [(label, start, end)] per division part
        for d in DIV_RE.finditer(mt):
            base = d.start(2)
            kws.append(d.group(1).lower().replace("–", "-"))
            divs.append([(_norm_label(x.group(0)), base + x.start(), base + x.end()) for x in LBL_RE.finditer(d.group(2))])
        if m.group("sec"):
            kw = list(SECKW_RE.finditer(mt))[-1]
            nums = [(x.group(1), x.group(2), x.start(), x.end()) for x in NUM_RE.finditer(mt, kw.end())]
            first_ok = bool(nums) and nums[0][0] in act.sections
            nums = [t for t in nums if t[0] in act.sections]
            if not nums:
                return []
            exp, suf0 = "", nums[0][1]
            if m.group("expl"):
                # "clauses (b) and (d) of the Explanation to sub-section (2) of section 64":
                # divisions after the Explanation locate it; those before sit inside it.
                tag = "-expl" if m.group("qual") == "Explanation" else "-exc"
                exp = tag + (f"-{m.group('explno')}" if m.group("explno") else "")
                cut = m.start("expl") - m.start()
                outer_d = [x for x in divs if x[0][1] > cut]
                divs = [x for x in divs if x[0][1] < cut]
                if any(len(x) > 1 for x in outer_d):
                    outer_d = []
                suf0 += "".join(x[0][0] for x in reversed(outer_d))
            if len(nums) == 1 and first_ok and all(len(d) == 1 for d in divs):
                t = self._target(nums[0][0], suf0, exp, "".join(d[0][0] for d in reversed(divs)))
                return [(0, len(mt), t)] if t else []
            spans = []
            if divs and first_ok and all(len(d) == 1 for d in divs[1:]):
                outer = "".join(d[0][0] for d in reversed(divs[1:]))
                for lab, s, e in divs[0]:
                    t = self._target(nums[0][0], suf0, exp, outer + lab)
                    if t:
                        spans.append((s, e, t))
            for n, suf, s, e in nums:
                t = act.resolve(n + suf)
                if t:
                    spans.append((s, e, t))
            return sorted(spans)
        # Relative reference inside the current section.
        if kws[-1].startswith("sub-section"):
            prefixes = [num]
        else:
            chain = act.ancestors.get(nid, []) + [nid]
            prefixes = [a for a in reversed(chain) if STRUCT_ID.fullmatch(a)]

        def find(suffix: str) -> str | None:
            for p in prefixes:
                if p + suffix in act.nodes and p + suffix != nid:
                    return p + suffix
            return None

        if all(len(d) == 1 for d in divs):
            t = find("".join(d[0][0] for d in reversed(divs)))
            return [(0, len(mt), t)] if t else []
        if all(len(d) == 1 for d in divs[1:]):
            outer = "".join(d[0][0] for d in reversed(divs[1:]))
            spans = []
            for lab, s, e in divs[0]:
                t = find(outer + lab)
                if t:
                    spans.append((s, e, t))
            return spans
        return []


# --------------------------------------------------------------------------- rendering


def label_html(kind: str, label: str) -> str:
    if kind in ("explanation", "exception"):
        m = re.match(r"(.*?\.)(\s*[—–-]+\s*)?$", label)
        if m:
            return f'<span class="lbl"><i>{esc(m.group(1))}</i>{esc(m.group(2) or "")}</span>'
        return f'<span class="lbl"><i>{esc(label)}</i></span>'
    # Gazette style: parentheses upright, letters italic, digits upright.
    inner = re.sub(r"[A-Za-z]+", lambda x: f"<i>{x.group(0)}</i>", esc(label))
    return f'<span class="lbl">{inner}</span>'


class Renderer:
    def __init__(self, act: Act, local: set[str] | None = None):
        self.act = act
        self.local = local or set()  # sections present on the current page → in-page links
        self.linker = Linker(act)

    def href(self, target: str) -> tuple[str, str]:
        if target.startswith("chapter:"):
            ch = self.act.chapter_by_num[target[8:]]
            return f"/{ch['id']}/", f"Chapter {ch['num']}"
        _, num = self.act.nodes[target]
        url = f"#p-{target}" if num in self.local else node_url(num, target)
        return url, self.act.cite(target)

    def pil(self, nid: str, page: int | None) -> str:
        act = self.act
        _, num = act.nodes[nid]
        cite = act.cite(nid)
        attrs = f' data-c="{esc(cite)}" data-l="{esc(act.long[nid])}"' if nid in act.long else f' data-c="{esc(cite)}"'
        if page:
            attrs += f' data-p="{page}"'
        return (
            f'<a class="pil" href="{esc(node_url(num, nid))}"{attrs} '
            f'aria-label="Link and citation for {esc(cite)}">¶</a>'
        )

    def refs(self, refs: list[str] | None) -> str:
        if not refs:
            return ""
        items = "".join(f"<span>{esc(r)}</span>" for r in refs)
        return f'<aside class="refs" aria-label="Marginal citation">{items}</aside>'

    def node(self, n: dict, num: str) -> str:
        kind, nid = n["kind"], n["id"]
        label, text = n.get("label"), n.get("text") or ""
        kids = "".join(self.node(c, num) for c in n.get("children") or [])
        if kind == "illustrations":
            head = f'<p class="ih">{esc(label or "Illustration.")}</p>'
            return f'<div class="n k-illustrations" id="p-{esc(nid)}">{head}{kids}</div>'
        body = self.linker.link(text, num, nid, self.href)
        if kind == "proviso":
            body = re.sub(r"^Provided(?: further)?\b", lambda x: f"<i>{x.group(0)}</i>", body)
        parts = []
        if label:
            parts.append(label_html(kind, label))
        if body:
            parts.append(body)
        para = ""
        if parts:
            pil = self.pil(nid, n.get("page")) if n.get("cite") else ""
            sep = "" if label and re.search(r"[—–-]$", label) and body else " "
            para = f'<p class="t">{pil}{sep.join(parts)}</p>'
        nif = ""
        if nid in self.act.not_in_force:
            nif = f'<p class="nif" role="note">{esc(self.act.nif_text())}</p>'
        return f'<div class="n k-{kind}" id="p-{esc(nid)}">{nif}{para}{self.refs(n.get("refs"))}{kids}</div>'

    def section(self, num: str, level: int, own_page: bool) -> str:
        sec = self.act.sections[num]
        pages = sec.get("pages") or []
        lead = f"Section {num}."
        if not own_page:
            lead = f'<a href="{sec_url(num)}">{lead}</a>'
        head = (
            f'<h{level} class="sh" id="p-{num}">{self.pil(num, pages[0] if pages else None)}'
            f'<span class="sn">{lead}</span> {esc(sec["heading"])}</h{level}>'
        )
        meta = ""
        if pages:
            meta = f'<p class="smeta"><a href="{PDF_PATH}#page={pages[0]}">Gazette p. {pages[0]}</a></p>'
        for nid in sorted(self.act.not_in_force):
            if nid in self.act.nodes and self.act.nodes[nid][1] == num:
                url, cite = self.href(nid)
                meta += (
                    f'<p class="nif" role="note"><a href="{esc(url)}">{esc(cite)}</a>: '
                    f"{esc(self.act.nif_text())}</p>"
                )
        body = "".join(self.node(n, num) for n in sec["content"])
        return f'<article class="sec">{head}{meta}{self.refs(sec.get("refs"))}<div class="law">{body}</div></article>'

    def chapter_body(self, ch: dict, base: int, own_page: bool) -> str:
        """Sections of a chapter interleaved with their centered group headings."""
        out, current = [], None
        for num in ch["sections"]:
            g = self.act.sec_group.get(num)
            if g != current:
                current = g
                if g:
                    out.append(f'<h{base} class="grp">{esc(g)}</h{base}>')
            out.append(self.section(num, base + 1 if current else base, own_page))
        return "".join(out)


def first_text(sec: dict, limit: int = 155) -> str:
    words = []

    def walk(nodes):
        for n in nodes:
            if n.get("text"):
                words.append(n["text"])
            walk(n.get("children") or [])

    walk(sec["content"])
    s = " ".join(words)
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


# --------------------------------------------------------------------------- page shell


def fmt_stat_value(v: str) -> str:
    return fmt_date(v) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else v


def fmt_source_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return fmt_date(iso)
    except ValueError:
        return iso


def validate_stats(stats: dict, act: Act) -> None:
    """Every stat needs a source URL; every cited provision must exist in the Act."""
    errors = []
    for g in stats.get("groups") or []:
        for it in g.get("items") or []:
            where = f"stats: {g.get('title')!r} / {it.get('label')!r}"
            for key in ("label", "value", "detail"):
                if not it.get(key):
                    errors.append(f"{where}: missing {key}")
            srcs = it.get("sources") or []
            if not srcs or any(not str(s.get("url", "")).startswith("https://") or not s.get("title") for s in srcs):
                errors.append(f"{where}: every item needs sources with title and https url")
            for p in it.get("provisions") or []:
                if p not in act.nodes:
                    errors.append(f"{where}: unknown provision id {p!r}")
    if errors:
        raise SystemExit("\n".join(errors))


class Site:
    def __init__(self, act: Act, out: Path, stats_data: dict | None = None, data_path: Path = DATA_DIR / "bns.json"):
        self.act = act
        self.out = out
        self.stats_data = stats_data
        self.data_path = data_path
        self.downloads: list[tuple[str, str, str, int, str]] = []
        self.v_css = self.v_js = ""

    def toc(self, *, chapter: str | None = None, section: str | None = None, inpage: bool = False) -> str:
        act = self.act
        lines = [
            '<nav class="toc" id="toc" aria-label="Table of contents"><div class="toc-h"><a href="/">Contents</a>'
            '<p class="tgl" hidden><button type="button" data-tgl="open" aria-label="Expand all chapters">Expand all</button>'
            '<button type="button" data-tgl="close" aria-label="Collapse all chapters">Collapse all</button></p></div><ul class="tree">'
        ]
        for ch in act.chapters:
            is_cur = ch["num"] == chapter
            ch_href = f"#{ch['id']}" if inpage else f"/{ch['id']}/"
            cur = ' aria-current="page"' if is_cur and section is None and not inpage else ""
            lines.append(
                f'<li><details{" open" if is_cur else ""}><summary><a href="{ch_href}"{cur}>Chapter {ch["num"]}</a> '
                f'<span class="ct">{esc(title_case(ch["title"]))}</span></summary><ul>'
            )
            group, open_g = None, False
            for num in ch["sections"]:
                g = act.sec_group.get(num)
                if g != group:
                    if open_g:
                        lines.append("</ul></details></li>")
                        open_g = False
                    group = g
                    if g:
                        here = section is not None and act.sec_group.get(section) == g and section in ch["sections"]
                        lines.append(f'<li class="g"><details{" open" if here else ""}><summary>{esc(g)}</summary><ul>')
                        open_g = True
                sec = act.sections[num]
                href = f"#p-{num}" if inpage else sec_url(num)
                cur = ' aria-current="page"' if num == section else ""
                lines.append(f'<li><a href="{href}"{cur}><span class="sn">Section {num}.</span> {esc(sec["heading"])}</a></li>')
            if open_g:
                lines.append("</ul></details></li>")
            lines.append("</ul></details></li>")
        lines.append("</ul></nav>")
        return "".join(lines)

    def crumbs(self, items: list[tuple[str, str | None]]) -> str:
        lis = []
        for text, href in items:
            if href:
                lis.append(f'<li><a href="{href}">{esc(text)}</a></li>')
            else:
                lis.append(f'<li aria-current="page">{esc(text)}</li>')
        return f'<nav class="bc" aria-label="Breadcrumb"><ol>{"".join(lis)}</ol></nav>'

    def page(self, *, title: str, desc: str, main: str, kind: str, toc: str = "") -> str:
        act = self.act
        return f"""<!doctype html>
<html lang="en" class="no-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="stylesheet" href="/style.css?v={self.v_css}">
<link rel="icon" href="data:,">
<script>{INLINE_JS}</script>
<script src="/app.js?v={self.v_js}" defer></script>
</head>
<body data-page="{kind}">
<a class="skip" href="#main">Skip to content</a>
<div class="topbar" role="note">Unofficial edition — may contain mistakes. Verify against <a href="{PDF_PATH}">the Gazette of India</a> or <a href="https://www.indiacode.nic.in/">India Code</a>. <a href="/about/">Disclaimer</a></div>
<header class="site">
<div class="brand"><a href="/"><span class="bt">{esc(SITE)}</span> <span class="ba">{esc(act.meta["act"])}</span></a></div>
<nav class="sitenav" aria-label="Site"><a href="/full/">Full text</a>{'<a href="/stats/">Stats</a>' if self.stats_data else ""}<a href="/about/">About</a><a href="{PDF_PATH}">Gazette PDF</a></nav>
<button class="toc-btn" type="button" aria-controls="toc" aria-expanded="false" hidden>Contents</button>
<form class="hs" role="search" action="/search/" method="get">
<label for="hq" class="vh">Search the Sanhita or go to a section</label>
<input id="hq" name="q" type="search" placeholder="Search, or cite e.g. 103(1)" autocomplete="off" spellcheck="false">
<button type="submit">Search</button>
<ul id="hq-list" class="ta" role="listbox" aria-label="Suggestions" hidden></ul>
</form>
<button class="theme-btn" id="theme-btn" type="button" aria-label="Toggle color theme" title="Toggle light/dark mode" hidden>◐</button>
</header>
<div class="wrap{"" if toc else " no-toc"}">
<main id="main" tabindex="-1">
{main}
</main>
{toc}
</div>
<footer class="site"><p class="asof">{esc(act.meta.get("text_as_of") or "")}</p><p>Unofficial edition of {esc(act.meta["title"])} ({esc(act.meta["act"])}); it may contain mistakes — check <a href="{PDF_PATH}">the Gazette of India</a> or <a href="https://www.indiacode.nic.in/">India Code</a> before relying on it. Not legal advice. Site content is public domain (<a href="https://creativecommons.org/publicdomain/zero/1.0/" rel="license">CC0</a>). <a href="/about/">About</a>.</p></footer>
</body>
</html>
"""

    def commencement(self) -> str:
        m = self.act.meta
        com = m.get("commencement") or {}
        when = fmt_date(com.get("date") or m["in_force"])
        s = f"In force from {when}"
        if com.get("notification"):
            s += f" ({com['notification']})"
        nif = com.get("not_in_force") or []
        if nif:
            s += ", except " + ", ".join(f"section {x}" for x in nif) + ", which has not been brought into force"
        return s + "."

    def write(self, rel: str, html: str):
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    # ---- pages

    def pn(self, prev: tuple[str, str] | None, nxt: tuple[str, str] | None, label: str) -> str:
        a = f'<a rel="prev" href="{prev[0]}"><span class="pl">Previous</span> {esc(prev[1])}</a>' if prev else "<span></span>"
        b = f'<a rel="next" href="{nxt[0]}"><span class="pl">Next</span> {esc(nxt[1])}</a>' if nxt else "<span></span>"
        return f'<nav class="pn" aria-label="{label}">{a}{b}</nav>'

    def section_page(self, num: str):
        act = self.act
        sec = act.sections[num]
        ch = act.sec_chapter[num]
        i = act.pos[num]
        prev = act.order[i - 1] if i else None
        nxt = act.order[i + 1] if i + 1 < len(act.order) else None
        r = Renderer(act, {num})
        group = act.sec_group.get(num)
        ctx = f'<p class="kicker"><a href="/{ch["id"]}/">Chapter {ch["num"]} — {esc(ch["title"])}</a>'
        if group:
            ctx += f' <span class="kg">{esc(group)}</span>'
        ctx += "</p>"
        main = (
            self.crumbs([("BNS", "/"), (f"Chapter {ch['num']}", f"/{ch['id']}/"), (f"Section {num}", None)])
            + ctx
            + r.section(num, 1, True)
            + self.pn(
                (sec_url(prev), f"Section {prev}. {act.sections[prev]['heading']}") if prev else None,
                (sec_url(nxt), f"Section {nxt}. {act.sections[nxt]['heading']}") if nxt else None,
                "Previous and next section",
            )
        )
        self.write(
            f"section-{num}/index.html",
            self.page(
                title=f"Section {num} — {sec['heading']}{TITLE_SUFFIX}",
                desc=f"Section {num} of the Bharatiya Nyaya Sanhita, 2023 — {sec['heading']} {first_text(sec)}",
                main=main,
                kind="section",
                toc=self.toc(chapter=ch["num"], section=num),
            ),
        )

    def chapter_page(self, idx: int):
        act = self.act
        ch = act.chapters[idx]
        r = Renderer(act, set(ch["sections"]))
        secs = ch["sections"]
        span = f"Sections {secs[0]}–{secs[-1]}" if len(secs) > 1 else f"Section {secs[0]}"
        prev = act.chapters[idx - 1] if idx else None
        nxt = act.chapters[idx + 1] if idx + 1 < len(act.chapters) else None
        main = (
            self.crumbs([("BNS", "/"), (f"Chapter {ch['num']}", None)])
            + f'<header class="chh" id="{ch["id"]}"><h1><span class="cn">Chapter {ch["num"]}</span> '
            f'<span class="ctt">{esc(ch["title"])}</span></h1>'
            f'<p class="smeta">{span} · <a href="{PDF_PATH}#page={ch["page"]}">Gazette p. {ch["page"]}</a></p></header>'
            + r.chapter_body(ch, 2, False)
            + self.pn(
                (f"/{prev['id']}/", f"Chapter {prev['num']}. {title_case(prev['title'])}") if prev else None,
                (f"/{nxt['id']}/", f"Chapter {nxt['num']}. {title_case(nxt['title'])}") if nxt else None,
                "Previous and next chapter",
            )
        )
        self.write(
            f"{ch['id']}/index.html",
            self.page(
                title=f"Chapter {ch['num']} — {title_case(ch['title'])}{TITLE_SUFFIX}",
                desc=f"Chapter {ch['num']} of the Bharatiya Nyaya Sanhita, 2023: {title_case(ch['title'])} ({span}).",
                main=main,
                kind="chapter",
                toc=self.toc(chapter=ch["num"]),
            ),
        )

    def preamble(self) -> str:
        p = self.act.data.get("preamble") or {}
        out = ['<section class="pre" aria-label="Preamble">']
        if p.get("act_no"):
            out.append(f'<p class="actno">{esc(p["act_no"])}</p>')
        if p.get("date"):
            out.append(f'<p class="pdate">{esc(p["date"])}</p>')
        if p.get("long_title"):
            out.append(f'<p class="lt">{esc(p["long_title"])}</p>')
        if p.get("enacting_formula"):
            out.append(f'<p class="ef">{esc(p["enacting_formula"])}</p>')
        out.append("</section>")
        return "".join(out)

    def home(self):
        act = self.act
        m = act.meta
        toc = [
            '<section class="htoc" aria-labelledby="toc-h"><div class="htoc-h"><h2 id="toc-h">Table of contents</h2>'
            '<p class="tgl" hidden><button type="button" data-tgl="open">Expand all</button>'
            '<button type="button" data-tgl="close">Collapse all</button></p></div><ol class="chl">'
        ]
        for ch in act.chapters:
            secs = ch["sections"]
            span = f"Section {secs[0]}" if len(secs) == 1 else f"Sections {secs[0]}–{secs[-1]}"
            toc.append(
                f'<li><details><summary><h3><a href="/{ch["id"]}/"><span class="cn">Chapter {ch["num"]}</span> '
                f'<span class="ctt">{esc(ch["title"])}</span></a></h3><span class="cr">{span}</span></summary>'
            )
            group, open_g = None, False
            toc.append('<ul class="secl">')
            for num in secs:
                g = act.sec_group.get(num)
                if g != group:
                    if open_g:
                        toc.append("</ul></details></li>")
                        open_g = False
                    group = g
                    if g:
                        toc.append(f'<li class="g"><details><summary class="gt">{esc(g)}</summary><ul class="secl">')
                        open_g = True
                toc.append(
                    f'<li><a href="{sec_url(num)}"><span class="sn">Section {num}.</span> {esc(act.sections[num]["heading"])}</a></li>'
                )
            if open_g:
                toc.append("</ul></details></li>")
            toc.append("</ul></details></li>")
        toc.append("</ol></section>")
        title = (act.data.get("preamble") or {}).get("title") or m["title"].upper()
        main = (
            f'<header class="acth"><h1>{esc(title)}</h1>'
            f'<p class="smeta">{esc(m["act"])} · Assented {fmt_date(m["assented"])} · In force from {fmt_date(m["in_force"])} · '
            f'<a href="/full/">Full text</a> · <a href="{PDF_PATH}">Gazette PDF</a> · <a href="/about/">About</a></p></header>'
            + self.preamble()
            + "".join(toc)
            + (f'<p class="sig">{esc(act.data["signature"])}</p>' if act.data.get("signature") else "")
        )
        self.write(
            "index.html",
            self.page(
                title=f"{m['title']} ({m['act']}) — full text{TITLE_SUFFIX}",
                desc=f"Browsable text of {m['title']} ({m['act']}), India's penal code, with section links and citations, from the Gazette of India.",
                main=main,
                kind="home",
            ),
        )

    def full(self):
        act = self.act
        r = Renderer(act, set(act.order))
        parts = [
            self.crumbs([("BNS", "/"), ("Full text", None)]),
            f'<header class="acth"><h1>{esc((act.data.get("preamble") or {}).get("title") or act.meta["title"])}</h1>'
            f'<p class="smeta">{esc(act.meta["act"])} · <a href="{PDF_PATH}">Gazette PDF</a></p></header>',
            self.preamble(),
        ]
        for ch in act.chapters:
            parts.append(
                f'<section class="chs"><header class="chh" id="{ch["id"]}"><h2><a href="/{ch["id"]}/">'
                f'<span class="cn">Chapter {ch["num"]}</span> <span class="ctt">{esc(ch["title"])}</span></a></h2></header>'
            )
            parts.append(r.chapter_body(ch, 3, False))
            parts.append("</section>")
        if act.data.get("signature"):
            parts.append(f'<p class="sig">{esc(act.data["signature"])}</p>')
        self.write(
            "full/index.html",
            self.page(
                title=f"Full text — {act.meta['title']}{TITLE_SUFFIX}",
                desc=f"The whole of {act.meta['title']} on one page, for printing and find-in-page.",
                main="".join(parts),
                kind="full",
                toc=self.toc(inpage=True),
            ),
        )

    def search_page(self):
        main = (
            self.crumbs([("BNS", "/"), ("Search", None)])
            + '<h1>Search</h1>'
            '<form class="ps" role="search" action="/search/" method="get">'
            '<label for="sq">Words, a "quoted phrase", or a citation such as <code>64(2)(f)</code>, <code>s. 103</code>, <code>BNS 2(28)</code></label>'
            '<div class="psr"><input id="sq" name="q" type="search" autocomplete="off" spellcheck="false"><button type="submit">Search</button></div></form>'
            '<noscript><p class="note">Search needs JavaScript. Without it, browse the <a href="/">table of contents</a> '
            'or use your browser\'s find-in-page on the <a href="/full/">full text</a>.</p></noscript>'
            '<p id="sstatus" class="sstatus" role="status" aria-live="polite"></p><ol id="sresults" class="results"></ol>'
        )
        self.write(
            "search/index.html",
            self.page(
                title=f"Search{TITLE_SUFFIX}",
                desc="Full-text and citation search of the Bharatiya Nyaya Sanhita, 2023.",
                main=main,
                kind="search",
                toc=self.toc(),
            ),
        )

    def official_notice(self) -> str:
        """Prominent warning that this is unofficial, with links to the official texts."""
        return (
            '<aside class="notice" role="note"><p><strong>There may be mistakes.</strong> This is an unofficial, '
            "machine-readable (digital) reproduction of the source. Before relying on any provision, check it against an "
            "official source:</p><ul>"
            f'<li><a href="{PDF_PATH}">The Gazette of India publication</a> this site is built from '
            "(Extraordinary, Part II—Section 1, No. 53, 25 December 2023)</li>"
            '<li><a href="https://www.indiacode.nic.in/">India Code</a> (Legislative Department, Ministry of Law and Justice), '
            "which carries the consolidated text with any later amendments</li>"
            '<li><a href="https://egazette.gov.in/">e-Gazette of India</a> for notifications, including commencement</li>'
            "</ul><p>If you find an error, please report it with the section and the Gazette page number.</p></aside>"
        )

    def write_downloads(self):
        """Copy the machine-readable files to /download/ and remember their size and hash."""
        files = [
            (self.data_path, "bns.json", "The entire Act as structured JSON: preamble, chapters, group headings, sections and "
             "every sub-section, clause, proviso, Explanation, Exception and Illustration, with citation ids, citations "
             "and Gazette page numbers."),
            (self.data_path.parent / "stats.json", "stats.json", "The figures on the stats page, each with its sources."),
            (ROOT / "docs" / "DATA_MODEL.md", "DATA_MODEL.md", "Schema and citation-id scheme for bns.json."),
        ]
        self.downloads = []
        out = self.out / "download"
        out.mkdir(parents=True, exist_ok=True)
        for src, name, desc in files:
            if not src.exists():
                continue
            data = src.read_bytes()
            (out / name).write_bytes(data)
            self.downloads.append((f"/download/{name}", name, desc, len(data), hashlib.sha256(data).hexdigest()))

    def downloads_html(self) -> str:
        if not self.downloads:
            return ""
        rows = "".join(
            f'<tr><td><a href="{esc(href)}" download><code>{esc(name)}</code></a></td><td>{esc(desc)}</td>'
            f'<td class="num">{size / 1024:,.0f} KB</td></tr>'
            for href, name, desc, size, _ in self.downloads
        )
        sums = "".join(f"<li><code>{esc(name)}</code> <code class=\"hash\">{esc(sha)}</code></li>" for _, name, _, _, sha in self.downloads)
        return (
            "<h2 id=\"downloads\">Downloads</h2>"
            "<p>The entire content of this site is available as JSON, generated from the same data as these pages. "
            "Like the rest of the site it is public domain (CC0), and may contain mistakes — the Gazette is authoritative.</p>"
            f'<div class="tw"><table class="dl"><thead><tr><th>File</th><th>Contents</th><th>Size</th></tr></thead><tbody>{rows}'
            f'<tr><td><a href="{PDF_PATH}" download><code>bns-2023-gazette.pdf</code></a></td>'
            "<td>The source Gazette of India publication, unmodified.</td><td class=\"num\">"
            f"{GAZETTE_PDF.stat().st_size / 1024:,.0f} KB</td></tr></tbody></table></div>"
            f'<details class="sums"><summary>SHA-256 checksums</summary><ul>{sums}</ul></details>'
        )

    def about(self):
        act = self.act
        m = act.meta
        src = m["source"]
        n_adj = ""
        accepted = ROOT / "ocr" / "accepted.json"
        if accepted.exists():
            try:
                n = len(json.loads(accepted.read_text(encoding="utf-8")))
                n_adj = f" {n} such adjudications are recorded."
            except (ValueError, TypeError):
                pass
        rows = [
            ("Section 103", "103", "Section 103"),
            ("Sub-section (1) of section 103", "103(1)", "Section 103(1)"),
            ("Clause (f) of sub-section (2) of section 64", "64(2)(f)", "Section 64(2)(f)"),
            ("Clause (28), sub-clause (k)(ii) of section 2 (definitions)", "2(28)(k)(ii)", "Section 2(28)(k)(ii)"),
            ("Explanation 1 to section 2(4)", "2(4)-expl-1", "Explanation 1 to Section 2(4)"),
            ("The (only) Explanation to section 1(5)", "1(5)-expl", "Explanation to Section 1(5)"),
            ("First proviso to section 8(5)", "8(5)-proviso-1", "First proviso to Section 8(5)"),
            ("Exception 1 to section 101", "101-exc-1", "Exception 1 to Section 101"),
            ("Illustration (a) to section 3(8)", "3(8)-illus-a", "Illustration (a) to Section 3(8)"),
            ("Unlettered illustration to section 126(1)", "126(1)-illus", "Illustration to Section 126(1)"),
        ]
        trs = []
        for prov, nid, cite in rows:
            target = act.resolve(nid) if nid in act.nodes else None
            idc = f'<a href="{esc(node_url(act.nodes[target][1], target))}"><code>{esc(nid)}</code></a>' if target == nid else f"<code>{esc(nid)}</code>"
            trs.append(f"<tr><td>{esc(prov)}</td><td>{idc}</td><td>{esc(cite)}</td></tr>")
        main = (
            self.crumbs([("BNS", "/"), ("About", None)])
            + "<h1>About this site</h1>"
            + self.official_notice()
            + "<h2>Source document</h2><dl class=\"kv\">"
            f"<dt>Title</dt><dd>{esc(m['title'])} ({esc(m['act'])})</dd>"
            f"<dt>Published in</dt><dd>{esc(src['gazette'])}</dd>"
            f"<dt>Assent</dt><dd>{fmt_date(m['assented'])}</dd>"
            f"<dt>Commencement</dt><dd>{esc(self.commencement())}</dd>"
            f"<dt>Text as of</dt><dd>{esc(m.get('text_as_of') or '')}</dd>"
            f"<dt>File</dt><dd><a href=\"{PDF_PATH}\">bns-2023-gazette.pdf</a> ({src.get('pages', '?')} pages) — "
            f"original at <a href=\"{esc(src['url'])}\">{esc(src['url'].split('/')[2])}</a></dd>"
            f"<dt>SHA-256</dt><dd><code class=\"hash\">{esc(src['sha256'])}</code></dd>"
            f"<dt>Generated</dt><dd>{esc(m.get('generated', ''))}</dd></dl>"
            + self.downloads_html()
            + "<h2>Method</h2>"
            "<p>Text taken from the Gazette PDF text layer and independently transcribed from page images by a vision model; "
            "every word-level or paragraph-boundary disagreement was adjudicated against the page image "
            f"(<code>ocr/accepted.json</code>).{esc(n_adj)} The reconciled text was then parsed into chapters, sections and "
            "numbered provisions; labels, marginal headings and punctuation are kept as printed. Each paragraph links to the "
            "Gazette page on which it begins.</p>"
            "<h2>Citation guide</h2>"
            "<p>Indian statutes are cited as <em>section → sub-section (1) → clause (a) → sub-clause (i)</em>; the compact form "
            "is <code>section 64(2)(a)</code>. Every paragraph on this site has an anchor <code>#p-&lt;id&gt;</code> whose id is "
            "that compact citation, e.g. <a href=\"/section-103/#p-103(1)\"><code>/section-103/#p-103(1)</code></a>. "
            "Use the ¶ button beside a paragraph to copy its link, its short citation (<q>Section 103(1), BNS</q>) or its long "
            "form (<q>clause (f) of sub-section (2) of section 64 of the Bharatiya Nyaya Sanhita, 2023</q>).</p>"
            "<div class=\"tw\"><table><thead><tr><th scope=\"col\">Provision</th><th scope=\"col\">id</th><th scope=\"col\">Citation</th></tr></thead>"
            f"<tbody>{''.join(trs)}</tbody></table></div>"
            "<p>When a section's numbered divisions open on the section-number line (<q>64. (1) …</q>) they are "
            "<em>sub-sections</em> and lettered divisions under them are <em>clauses</em>; when the section opens with lead-in "
            "words and then lists (1), (2) (as in the definitions in section 2) the numbered divisions are <em>clauses</em> and "
            "letters under them are <em>sub-clauses</em>.</p>"
            "<p>The search box accepts citations directly: <code>103</code>, <code>s. 103(1)</code>, <code>sec 64(2)(f)</code>, "
            "<code>Section 2(28)(k)(ii)</code>, <code>BNS 103</code>, <code>§103</code>.</p>"
            "<h2>Reading the text</h2>"
            "<p>Provisions that qualify the main text are colour-coded, with a faint rule along their full extent: "
            '<span class="lg lg-expl"><i>Explanation.</i></span>, <span class="lg lg-exc"><i>Exception.</i></span>, '
            '<span class="lg lg-prov"><i>Provided</i></span> (proviso) and <span class="lg lg-ill"><i>Illustrations.</i></span> '
            "Colour is a reading aid only; the wording is exactly as printed in the Gazette.</p>"
            "<h2>Disclaimer</h2>"
            "<p>This is an unofficial rendering provided for convenience. It is not legal advice and is not affiliated with "
            "or endorsed by the Government of India. Despite the checks described above, it may contain mistakes — in "
            "the text, its structure, the cross-reference links, the search or the stats page. The text published in the "
            f"Gazette of India is authoritative; consult it for any legal purpose. {esc(self.commencement())} "
            f"The Sanhita replaced the Indian Penal Code (45 of 1860). {esc(m.get('text_as_of') or '')}</p>"
            "<h2>Public domain</h2>"
            "<p>Everything made for this site — code, structured data, transcriptions and the compiled stats — is dedicated "
            'to the public domain under <a href="https://creativecommons.org/publicdomain/zero/1.0/" rel="license">CC0 1.0</a>: '
            "use it for anything, no permission or attribution needed. No rights are claimed in the text of the Act or in "
            "the Gazette PDF, which are reproduced unmodified from the Government of India's publication. Sources cited on "
            "the stats page remain their publishers' works.</p>"
        )
        self.write(
            "about/index.html",
            self.page(
                title=f"About — source, method and citation guide{TITLE_SUFFIX}",
                desc="Source Gazette, transcription and verification method, and citation guide for this edition of the Bharatiya Nyaya Sanhita, 2023.",
                main=main,
                kind="about",
                toc=self.toc(),
            ),
        )

    def not_found(self):
        main = (
            "<h1>Page not found</h1><p>There is no page at this address. Try the search box, the "
            '<a href="/">table of contents</a> or the <a href="/full/">full text</a>. Sections live at '
            "<code>/section-&lt;number&gt;/</code>, e.g. <a href=\"/section-103/\">/section-103/</a>.</p>"
        )
        self.write("404.html", self.page(title=f"Not found{TITLE_SUFFIX}", desc="Page not found.", main=main, kind="404"))

    def search_index(self):
        act = self.act
        secs, nodes = [], []
        sidx = {}
        for i, num in enumerate(act.order):
            sec = act.sections[num]
            sidx[num] = i
            secs.append([num, sec["heading"], act.sec_chapter[num]["num"]])
        for nid, (node, num) in act.nodes.items():
            if node is None:
                continue
            text = " ".join(x for x in (node.get("label") if node["kind"] != "illustrations" else None, node.get("text")) if x)
            nodes.append([nid, sidx[num], act.cite(nid), text, act.depth[nid]])
        payload = {"s": secs, "n": nodes}
        (self.out / "search-index.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    def assets(self):
        for name in ("style.css", "app.js"):
            src = WEB_DIR / name
            data = src.read_bytes()
            (self.out / name).write_bytes(data)
            v = hashlib.sha256(data).hexdigest()[:10]
            if name == "style.css":
                self.v_css = v
            else:
                self.v_js = v
        # Cloudflare Pages headers; the CSP allows exactly the one inline script.
        csp_hash = base64.b64encode(hashlib.sha256(INLINE_JS.encode()).digest()).decode()
        headers = (WEB_DIR / "_headers").read_text(encoding="utf-8").replace("sha256-REPLACED_AT_BUILD", f"sha256-{csp_hash}")
        (self.out / "_headers").write_text(headers, encoding="utf-8")
        dst = self.out / "source" / "bns-2023-gazette.pdf"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if GAZETTE_PDF.exists():
            shutil.copyfile(GAZETTE_PDF, dst)
        else:
            print(f"warning: {GAZETTE_PDF} missing; {dst} not written", file=sys.stderr)

    def stats(self):
        """/stats/: sourced, neutral facts from data/stats.json (skipped if the file is absent)."""
        if self.stats_data is None:
            return
        act = self.act
        r = Renderer(act)
        out = [
            self.crumbs([("BNS", "/"), ("Stats", None)]),
            "<h1>Stats and highlights</h1>",
            '<p class="lede">Figures and changes as reported by the Government of India and the press, each with its source. '
            "Counts described by the Ministry of Home Affairs are its own characterisation and are attributed as such. "
            "Where a provision is named, it links to the text.</p>",
        ]
        for g in self.stats_data["groups"]:
            gnote = f'<p class="stgn">{esc(g["note"])}</p>' if g.get("note") else ""
            out.append(f'<section class="stg"><h2>{esc(g["title"])}</h2>{gnote}<ul class="stl">')
            for it in g["items"]:
                provs = "".join(
                    f'<a href="{esc(node_url(act.nodes[p][1], p))}">{esc(act.cite(p))}</a>' for p in it.get("provisions") or []
                )
                srcs = "; ".join(
                    f'<a href="{esc(s["url"])}" rel="noopener">{esc(s["title"])}</a>'
                    + esc(", " + ", ".join(x for x in (s.get("publisher"), fmt_source_date(s.get("date"))) if x))
                    for s in it["sources"]
                )
                attrib = f'<span class="sta">{esc(it["attribution"])}:</span> ' if it.get("attribution") else ""
                note = f'<p class="stn">Note: {esc(it["note"])}</p>' if it.get("note") else ""
                out.append(
                    f'<li class="st"><p class="stv">{esc(fmt_stat_value(it["value"]))}</p><div class="stb">'
                    f'<p class="stlbl">{esc(it["label"])}</p>'
                    f'<p class="std">{attrib}{esc(it["detail"])}</p>'
                    + (f'<p class="stp">{provs}</p>' if provs else "")
                    + note
                    + f'<p class="sts">Source: {srcs}</p></div></li>'
                )
            out.append("</ul></section>")
        out.append(f'<p class="stgen">Compiled {esc(fmt_source_date(self.stats_data.get("generated")) or "")}. '
                   "This page reports what was published; it does not assess the changes.</p>")
        self.write(
            "stats/index.html",
            self.page(
                title=f"Stats and highlights{TITLE_SUFFIX}",
                desc="Sourced figures and reported changes in the Bharatiya Nyaya Sanhita, 2023: sections, chapters, legislative history and provisions in the news.",
                main="".join(out),
                kind="stats",
            ),
        )

    def build(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self.assets()
        self.home()
        for i in range(len(self.act.chapters)):
            self.chapter_page(i)
        for num in self.act.order:
            self.section_page(num)
        self.full()
        self.search_page()
        self.write_downloads()
        self.about()
        self.stats()
        self.not_found()
        self.search_index()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=DATA_DIR / "bns.json", help="structured Act JSON (default: data/bns.json)")
    ap.add_argument("--out", type=Path, default=DIST_DIR, help="output directory (default: dist/)")
    args = ap.parse_args(argv)
    act = Act(json.loads(args.data.read_text(encoding="utf-8")))
    stats_path = args.data.parent / "stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else None
    if stats is not None:
        validate_stats(stats, act)
    Site(act, args.out, stats, args.data).build()
    print(f"built {len(act.order)} sections, {len(act.chapters)} chapters → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
