# Data model and citation scheme

`data/bns.json` is produced by `python -m bns.parse` from the reconciled page
blocks (see `README.md` → Pipeline). It is the only input of the site build.

## Top level

```jsonc
{
  "meta": {
    "title": "The Bharatiya Nyaya Sanhita, 2023",
    "short": "BNS",
    "act": "Act No. 45 of 2023",
    "assented": "2023-12-25",            // date of Presidential assent / Gazette
    "in_force": "2024-07-01",
    "commencement": {                    // from the commencement notification, not the Gazette text
      "notification": "S.O. 850(E), dated 23 February 2024",
      "date": "2024-07-01",
      "not_in_force": ["106(2)"]         // node ids excluded by the notification
    },
    "text_as_of": "As enacted (Gazette of 25 December 2023); later amendments, if any, are not incorporated.",
    "source": {
      "file": "docs/BNS_2023_Act_45_of_2023_Gazette_English.pdf",
      "sha256": "…",
      "gazette": "The Gazette of India, Extraordinary, Part II—Section 1, No. 53, 25 December 2023 (CG-DL-E-25122023-250883)",
      "url": "https://prsindia.org/files/bills_acts/bills_parliament/2023/The%20Bharatiya%20Nyaya%20Sanhita%2C%202023.pdf",
      "pages": 102
    },
    "generated": "…ISO timestamp…"   // changes only when the rest of the file does
  },
  "preamble": {
    "act_no": "NO. 45 OF 2023",
    "date": "[25th December, 2023.]",
    "long_title": "An Act to consolidate and amend …",
    "enacting_formula": "BE it enacted by Parliament …",
    "page": 1
  },
  "chapters": [Chapter, …],             // 20, in order
  "sections": {"1": Section, …, "358": Section},
  "order": ["1", "2", …, "358"],        // reading order of section numbers
  "signature": "DIWAKAR SINGH, Joint Secretary & …"
}
```

### Chapter

```jsonc
{
  "id": "chapter-VI",                   // URL slug
  "num": "VI",                          // Roman numeral as printed
  "n": 6,                               // integer
  "title": "OF OFFENCES AFFECTING THE HUMAN BODY",   // as printed (small caps → upper)
  "page": 29,
  "sections": ["100", …],               // all sections of the chapter, in order
  "groups": [                            // centered italic headings inside the chapter
    {"title": "Of offences affecting life", "sections": ["100", …, "113"]}
  ]
}
```
Sections before a chapter's first group heading belong to no group.

### Section

```jsonc
{
  "num": "103",
  "id": "103",                          // = num; anchor `p-103` is the section itself
  "heading": "Punishment for murder.",  // marginal note, verbatim
  "chapter": "VI",
  "group": "Of offences affecting life", // or null
  "pages": [37, 38],                    // gazette pages the section spans
  "content": [Node, …],
  "refs": ["45 of 1860."]               // optional: margin Act citations beside the section's opening line
}
```

### Attachment rules

The Gazette prints provisos, Explanations, Exceptions and Illustrations at
sub-section indentation, so their parent is decided as follows (`bns/parse.py`):

- Proviso / Explanation / Exception → the nearest open provision at or above its
  indentation. An Explanation printed after an Exception belongs to that
  Exception (Explanation to Exception 4 of s. 101). An Exception closes earlier
  Exceptions; an Explanation or proviso closes earlier Explanations/provisos.
- An Explanation closing the section that speaks of "this section" is
  section-level (ss. 113, 122, 124, 330); "this sub-section" keeps it with the
  sub-section (s. 64(2)).
- Illustrations → the provision (or numbered Exception), skipping preceding
  Explanations, provisos and unnumbered Exceptions (ss. 126(1), 249, 309(3),
  316(1)) — except when two or more Explanations are each followed by their own
  Illustrations, which then belong to those Explanations (ss. 2(8), 46, 314, 335).

### Node

```jsonc
{
  "kind": "subsection" | "clause" | "subclause" | "item"   // numbered provisions
        | "text"          // unlabelled body text (section opening words, or words
                          //   that resume after a list of clauses)
        | "proviso"       // "Provided that …" / "Provided further that …"
        | "explanation"   // "Explanation.—…" / "Explanation 1.—…"
        | "exception"     // "Exception.—…" / "Exception 1.—…"
        | "illustrations" // the centered "Illustration(s)." heading; children are "illustration"
        | "illustration",
  "label": "(1)",          // printed label: "(1)", "(a)", "(i)", "(A)", "Explanation 1.—",
                           //   "Exception.—", "Illustrations."; null when none
  "text": "Whoever commits murder shall be punished with death …",
                           // verbatim text after the label (label + " " + text = print)
  "id": "103(1)",          // unique fragment key (HTML id is "p-" + id)
  "cite": "Section 103(1)",// short citation; null for "text" nodes
  "page": 38,              // gazette page where the node starts
  "refs": ["45 of 1860."], // marginal Act citations printed beside it (optional)
  "children": [Node, …]    // optional
}
```

## Citation scheme

Indian statutes cite as *section → sub-section (1) → clause (a) → sub-clause
(i)*; compact form `section 64(2)(a)`. Ids follow that compact form, so the id
**is** the citation:

| Provision | id | cite |
|---|---|---|
| Section 103 | `103` | `Section 103` |
| Sub-section (1) of section 103 | `103(1)` | `Section 103(1)` |
| Clause (f) of sub-section (2) of section 64 | `64(2)(f)` | `Section 64(2)(f)` |
| Clause (28), sub-clause (k)(ii) of section 2 (definitions) | `2(28)(k)(ii)` | `Section 2(28)(k)(ii)` |
| Explanation 1 to section 2(4) | `2(4)-expl-1` | `Explanation 1 to Section 2(4)` |
| The (only) Explanation to section 1(5) | `1(5)-expl` | `Explanation to Section 1(5)` |
| First proviso to section 8(5) | `8(5)-proviso-1` | `First proviso to Section 8(5)` |
| Exception 1 to section 101 | `101-exc-1` | `Exception 1 to Section 101` |
| Illustration (a) to section 3(8) | `3(8)-illus-a` | `Illustration (a) to Section 3(8)` |
| Unlettered illustration to section 126(1) | `126(1)-illus` | `Illustration to Section 126(1)` |
| Unlabelled text inside section 125 | `125-text-1` | — |

Provisos are numbered in order within their parent (`proviso-1`, `proviso-2`, …);
a sole proviso is still `proviso-1` but cites as `Proviso to Section …`.
Explanations/exceptions use their printed number, or none when unnumbered.

Level names: when a section's numbered divisions open on the section-number
line (`64. (1) …`) they are **sub-sections** and lettered divisions under them
are **clauses**; when the section opens with lead-in words and then lists
`(1)`, `(2)` (as in the definitions in section 2) the numbered divisions are
**clauses** and letters under them are **sub-clauses**.

The long form ("clause (f) of sub-section (2) of section 64 of the Bharatiya
Nyaya Sanhita, 2023") is derived from `kind` + labels along the path.

## URLs

| Path | Content |
|---|---|
| `/` | Act title, preamble, full table of contents (chapter → group → section) |
| `/chapter-VI/` | Chapter: groups, sections with full text |
| `/section-103/` | One section; paragraph anchors `#p-103(1)` |
| `/search/?q=…` | Full-text + citation search; a pure citation (`103(1)`, `s. 64(2)(f)`, `BNS 2(28)`) redirects to the provision |
| `/full/` | Whole Act on one page (print / find-in-page) |
| `/about/` | Source, method, verification, citation guide |
| `/stats/` | Sourced figures and reported changes, from `data/stats.json` (see below) |
| `/download/bns.json`, `/download/stats.json`, `/download/DATA_MODEL.md` | The full data behind the site (byte-identical to `data/`), CORS-enabled; listed with sizes and SHA-256 under About → Downloads |
| `/source/bns-2023-gazette.pdf` | The source Gazette (`#page=N` deep links) |

## `data/stats.json`

Hand-curated, neutral facts *reported* by official sources (PIB/MHA, PRS,
Parliament) or the press — not computed from the text. `groups[]` →
`{title, note?, items[]}`; each item `{label, value, detail, attribution?,
provisions[], verified_text?, sources[{title, publisher, date, url}], note?}`.
Counts that are the Ministry's own characterisation carry an `attribution`;
conflicting official figures are recorded in `note`, not reconciled. The site
build refuses items without an `https` source or with a provision id not in
`bns.json`. ISO-date `value`s render as dates.
