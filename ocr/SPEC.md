# BNS page transcription format (`bns-ocr/1`)

Source: `docs/BNS_2023_Act_45_of_2023_Gazette_English.pdf` (Gazette of India
Extraordinary, Part II Section 1, No. 53, 25 Dec 2023, CG-DL-E-25122023-250883).
Page images: `build/pages/page-NNN.png` (rendered by `bns/render_pages.py`).
Output: one UTF-8 file per page, `ocr/pages/page-NNN.txt`.

Transcribe **exactly what is printed**. Never correct typos, grammar, spelling,
capitalisation or punctuation — this is a legal text and printed errors must be
preserved verbatim (e.g. "proceedings" where "proceeding" was meant stays
"proceedings").

## Skip

- Running header: page number, `THE GAZETTE OF INDIA EXTRAORDINARY`,
  `Sec. 1]`, `[Part II—`, the rule lines under it.
- Page 1 masthead (Hindi text, registration number, EXTRAORDINARY, PART II,
  PUBLISHED BY AUTHORITY, No. 53, NEW DELHI date line, "Separate paging…",
  MINISTRY OF LAW AND JUSTICE, Legislative Department, the "New Delhi, the
  25th December…" line and "The following Act of Parliament received the
  assent…" line). Page 1 transcription starts at the Act title.
- Last page printer imprint ("UPLOADED BY THE MANAGER…", "MGIPMRND…") and the
  digital-signature stamp.

## Line format

One logical block per line, in reading order (top to bottom). No blank lines.
Wrapped printed lines of one paragraph are joined into ONE output line with a
single space. If a printed line ends with a hyphen that belongs to the word
(e.g. `sub-` / `section`), keep the hyphen and join with no space
(`sub-section`). Collapse runs of spaces to one space.

| Prefix | Meaning |
|---|---|
| `@TITLE <text>` | Act title on page 1 (`THE BHARATIYA NYAYA SANHITA, 2023`) |
| `@ACTNO <text>` | `NO. 45 OF 2023` |
| `@DATE <text>` | `[25th December, 2023.]` |
| `@CHAPTER <roman>` | Centered `CHAPTER XVII` line → `@CHAPTER XVII` |
| `@CHAPTER-TITLE <text>` | The centered small-caps title under it, in UPPERCASE as printed (`OF OFFENCES AGAINST PROPERTY`). Join a 2-line title into one. |
| `@HEADING <text>` | Centered *italic* group heading inside a chapter (e.g. `Of wrongful restraint and wrongful confinement`) |
| `@ILLUSTRATION <text>` | Centered italic `Illustration.` / `Illustrations.` heading (text exactly as printed) |
| `@SECTION <n> \| <marginal note>` | Start of a section. `<n>` is the bold section number without the dot. `<marginal note>` is the side-note printed in the margin beside it, joined into one line. The section's own body text then follows on the next line(s) as paragraphs — do NOT repeat the number. |
| `@REF <text>` | A marginal Act citation like `45 of 1860.` or `10 of 1897.` printed in the margin (not a section side-note). Put it on the line right after the paragraph it sits beside. |
| `P0\| <text>` | Paragraph whose first line starts flush with the left edge of the text block. |
| `P1\| <text>` | Paragraph with normal first-line indent (most sub-sections, provisos, Explanations, illustrations). |
| `P2\| <text>` | Paragraph indented one step further (typically clauses `(a)`, `(b)` …). |
| `P3\| <text>` | Indented two steps further (typically sub-clauses `(i)`, `(ii)` …). |
| `P4\| <text>` | Any deeper indent. |
| `C\| <text>` | ONLY as the first block of a page: text that continues the last paragraph of the previous page mid-paragraph (the first printed line on the page is not a fresh paragraph start). |
| `@SIGNATURE <text>` | Signature block on the last page (`DIWAKAR SINGH, Joint Secretary & Legislative Counsel to the Govt. of India.`) |
| `@NOTE <text>` | Anything that does not fit the above (table, figure, unclear print). Describe it. |

Indentation is relative to the text block's left edge: P0 = flush, P1 ≈ one
em-indent (~0.33 in), P2 ≈ two, P3 ≈ three. Judge by the first printed line of
the paragraph.

## Characters

- Keep curly quotes `“ ” ‘ ’` as printed; apostrophes are `’`.
- Dashes: em dash `—`. Where two dashes are printed back-to-back (e.g.
  `namely:––`, `means,––`) write `––` (two en dashes U+2013). Hyphen `-` for
  compound words.
- Labels: write `(1)`, `(a)`, `(i)`, `(A)` plainly (no italics markup).
- No markdown, no italics/bold markers, no added commentary.
- Section numbers that are referenced in text (e.g. "section 103") are just text.

## Example — page 41

```
P1| Provided further that any fine imposed under this sub-section shall be paid to the victim.
P1| (2) Whoever throws or attempts to throw acid on any person or attempts to administer acid to any person, or attempts to use any other means, with the intention of causing permanent or partial damage or deformity or burns or maiming or disfigurement or disability or grievous hurt to that person, shall be punished with imprisonment of either description for a term which shall not be less than five years but which may extend to seven years, and shall also be liable to fine.
P1| Explanation 1.—For the purposes of this section, “acid” includes any substance which has acidic or corrosive character or burning nature, that is capable of causing bodily injury leading to scars or disfigurement or temporary or permanent disability.
P1| Explanation 2.—For the purposes of this section, permanent or partial damage or deformity or permanent vegetative state shall not be required to be irreversible.
@SECTION 125 | Act endangering life or personal safety of others.
P1| Whoever does any act so rashly or negligently as to endanger human life or the personal safety of others, shall be punished with imprisonment of either description for a term which may extend to three months or with fine which may extend to two thousand five hundred rupees, or with both, but—
P2| (a) where hurt is caused, shall be punished with imprisonment of either description for a term which may extend to six months, or with fine which may extend to five thousand rupees, or with both;
P2| (b) where grievous hurt is caused, shall be punished with imprisonment of either description for a term which may extend to three years, or with fine which may extend to ten thousand rupees, or with both.
@HEADING Of wrongful restraint and wrongful confinement
@SECTION 126 | Wrongful restraint.
P1| (1) Whoever voluntarily obstructs any person so as to prevent that person from proceeding in any direction in which that person has a right to proceed, is said wrongfully to restrain that person.
P1| Exception.—The obstruction of a private way over land or water which a person in good faith believes himself to have a lawful right to obstruct, is not an offence within the meaning of this section.
@ILLUSTRATION Illustration.
P1| A obstructs a path along which Z has a right to pass, A not believing in good faith that he has a right to stop the path. Z is thereby prevented from passing. A wrongfully restrains Z.
P1| (2) Whoever wrongfully restrains any person shall be punished with simple imprisonment for a term which may extend to one month, or with fine which may extend to five thousand rupees, or with both.
@SECTION 127 | Wrongful confinement.
P1| (1) Whoever wrongfully restrains any person in such a manner as to prevent that person from proceedings beyond certain circumscribing limits, is said “wrongfully to confine” that person.
@ILLUSTRATION Illustrations.
P1| (a) A causes Z to go within a walled space, and locks Z in. Z is thus prevented from proceeding in any direction beyond the circumscribing line of wall. A wrongfully confines Z.
P1| (b) A places men with firearms at the outlets of a building, and tells Z that they will fire at Z if Z attempts to leave the building. A wrongfully confines Z.
P1| (2) Whoever wrongfully confines any person shall be punished with imprisonment of either description for a term which may extend to one year, or with fine which may extend to five thousand rupees, or with both.
```
