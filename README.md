# BNS — browsable Bharatiya Nyaya Sanhita, 2023

A fast, static, eCFR-style reader for India's penal code, the **Bharatiya
Nyaya Sanhita, 2023 (Act No. 45 of 2023)**, built entirely from the official
Gazette of India publication. Chapter → group heading → section tree
navigation, paragraph-level anchors that follow Indian citation practice
(`Section 64(2)(f)`), citation-aware search, and deep links into the source
PDF page.

## Source

| | |
|---|---|
| Document | The Gazette of India, Extraordinary, Part II—Section 1, No. 53, New Delhi, 25 December 2023 (CG-DL-E-25122023-250883), digitally signed by the Government of India Press |
| File | `docs/BNS_2023_Act_45_of_2023_Gazette_English.pdf` (102 pp., English) |
| SHA-256 | `67c92f7869420685e6cdc29b1bdde19fff91312b10241b3ed3e1163c5399600b` |
| Obtained from | <https://prsindia.org/files/bills_acts/bills_parliament/2023/The%20Bharatiya%20Nyaya%20Sanhita%2C%202023.pdf> (India Code / MHA mirrors were unreachable) |

`docs/Bharatiya_Nyaya_Sanhita,_2023.pdf` is **Bill No. 121 of 2023 as
introduced in Lok Sabha (11 Aug 2023)**. That Bill was withdrawn and replaced
by Bill No. 173 of 2023, which was enacted as Act 45 of 2023; its clause
numbering differs from the Act (e.g. murder is clause 99 in the Bill, section
101 in the Act). It is kept for reference but is not used.

## Pipeline

```
docs/…Gazette.pdf
  ├─ bns.render_pages ─▶ build/pages/page-NNN.png ─▶ vision transcription ─▶ ocr/pages/page-NNN.txt
  └─ bns.textlayer ────▶ ocr/textlayer/page-NNN.txt
                         bns.reconcile --strict   (block-by-block diff of the two readings;
                                                    disagreements adjudicated in ocr/accepted.json)
                         bns.parse ──▶ data/bns.json   (provision tree + ids + citations)
                         bns.site  ──▶ dist/           (static site)
```

1. **Two independent readings.** Every page image was transcribed by a vision
   model (format: `ocr/SPEC.md`) and, separately, the PDF text layer was
   converted to the same block format from glyph coordinates.
2. **Reconciliation.** `bns.reconcile` aligns the two readings per page. Word
   or paragraph-boundary disagreements must be adjudicated against the page
   image; all 23 were, and in every case the text layer matched the print
   (`ocr/accepted.json` records each verdict). Quote/dash code points and
   indentation are taken from the text layer (exact glyphs and coordinates).
3. **Structure.** `bns.parse` builds section → sub-section → clause →
   sub-clause trees with provisos, Explanations, Exceptions and Illustrations
   attached to the provision they qualify. It fails the build if the tree,
   read in order, does not reproduce the printed text character for character
   (whitespace aside), if any section 1–358 or chapter I–XX is missing, or if
   any id repeats.
4. **Structural audit.** Every section's parsed tree (nesting, attachment of
   provisos/Explanations/Illustrations, margin notes, group headings) was
   compared against the page images; the 13 confirmed attachment errors were fixed
   by general rules (documented in `docs/DATA_MODEL.md` → Attachment rules,
   covered by `tests/test_parse.py`) and the affected sections re-audited clean.

Printed errors are kept verbatim — e.g. Illustration to s. 117(1) reads
"intending of knowing" in the Gazette.

Data model, id scheme and URL map: [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).

## Usage

```sh
make setup      # .venv + PyMuPDF (only needed for pages/textlayer)
make            # textlayer → reconcile --strict → data/bns.json → dist/
make serve      # http://localhost:8000
make test
make deploy     # Cloudflare Pages direct upload (needs `npx wrangler login` once)
```

Both readings (`ocr/pages`, `ocr/textlayer`), the adjudications and
`data/bns.json` are committed, so `make data site test` need only the Python
standard library; PyMuPDF is needed only to re-extract from the PDF. `dist/`
is plain static files with root-relative links, so serve it at a domain root.

### Cloudflare Pages

`wrangler.toml` names the project (`bns-in` → `bns-in.pages.dev`) and output
directory. Either run `make deploy`, or connect the Git repository in the
Pages dashboard with build command `make site`, output directory `dist`, and
`PYTHON_VERSION=3.12`. The build writes `dist/_headers` (from `web/_headers`):
a strict Content-Security-Policy that pins the one inline script by hash,
year-long caching for the content-hashed `style.css`/`app.js`, and
`404.html` is served for unknown paths.

## Stats page

`/stats/` lists headline figures (358 sections vs 511 in the IPC, the
Ministry's counts of new offences, increased penalties, community service),
the legislative timeline, and provisions that drew press coverage. Every item
cites its source, government counts are attributed to the Ministry, and
differing official figures are shown rather than reconciled. Data:
`data/stats.json`.

## Reading aids

Explanations, Exceptions, provisos and Illustrations are colour-coded (label
colour plus a faint rule along their extent); the legend is on `/about/`.
Both tables of contents (home page and sidebar) collapse per chapter and
group, with "Expand all" / "Collapse all".

## Citations and links

| You want | Link |
|---|---|
| Section 103 | `/section-103/` |
| Clause (f) of sub-section (2) of section 64 | `/section-64/#p-64(2)(f)` |
| Explanation to Exception 4 to section 101 | `/section-101/#p-101-exc-4-expl` |
| Any citation typed by a user | `/search/?q=s.%2064(2)(f)` (redirects) |

Every paragraph has a link button that copies the URL or the citation
(`Section 64(2)(f), BNS` or the long form "clause (f) of sub-section (2) of
section 64 of the Bharatiya Nyaya Sanhita, 2023").

## Disclaimer

**This is an unofficial edition and may contain mistakes** — in the text, its
structure, cross-reference links, search or the stats page. It is not legal
advice and is not affiliated with the Government of India. Check the
[Gazette of India](https://egazette.gov.in/) publication or
[India Code](https://www.indiacode.nic.in/) before relying on any provision.
The Sanhita came into force on 1 July 2024 (S.O. 850(E), 23 Feb 2024), except
section 106(2).

## Licence

Public domain. Everything made for this project — code, data, transcriptions,
docs — is dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) ([`LICENSE`](LICENSE)).
No rights are claimed in the Act's text or the Gazette PDFs, which are
reproduced unmodified; see [`NOTICE.md`](NOTICE.md).
