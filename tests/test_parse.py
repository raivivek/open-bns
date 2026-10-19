import json
import unittest

from bns.parse import Para, ParseError, SectionBuilder, finalize
from bns.paths import DATA_DIR
from bns.reconcile import Block, classify


def build(num: str, paras: list[tuple[str, str]]) -> dict:
    """Run SectionBuilder over (indent, text) pairs; '@ILL' rows are illustration headings."""
    warnings: list[str] = []
    sec = SectionBuilder(num, "Heading.", 1, warnings.append)
    for kind, text in paras:
        if kind == "@ILL":
            sec.add_illustration_heading(text, 1)
        else:
            sec.add(Para(kind, text, 1))
    out = finalize(sec)
    out["warnings"] = warnings
    return out


def ids(nodes: list[dict], depth: int = 0) -> list[tuple[int, str]]:
    out = []
    for n in nodes:
        out.append((depth, n["id"]))
        out.extend(ids(n.get("children", []), depth + 1))
    return out


class LabelResolution(unittest.TestCase):
    def test_i_after_h_is_a_letter_but_deeper_i_is_roman(self):
        letters = [("P2", f"({c}) {c};") for c in "abcdefg"]
        s = build("9", [("P1", "(1) Lead-in—"), *letters, ("P2", "(h) h—"),
                        ("P3", "(i) first sub-clause;"), ("P3", "(ii) second;"),
                        ("P2", "(i) the letter i;")])
        tree = ids(s["content"])
        self.assertEqual(tree[-5:], [
            (1, "9(1)(g)"), (1, "9(1)(h)"), (2, "9(1)(h)(i)"), (2, "9(1)(h)(ii)"), (1, "9(1)(i)"),
        ])
        self.assertEqual(s["warnings"], [])

    def test_roman_list_continues_past_iii(self):
        s = build("75", [("P1", "(1) A man—"), ("P2", "(i) a;"), ("P2", "(ii) b;"), ("P2", "(iii) c;"), ("P2", "(iv) d,")])
        self.assertEqual([i for _, i in ids(s["content"])], ["75(1)", "75(1)(i)", "75(1)(ii)", "75(1)(iii)", "75(1)(iv)"])

    def test_chained_labels_open_two_levels(self):
        s = build("8", [("P1", "(5) Five."), ("P1", "(6) (a) The imprisonment shall terminate;"), ("P1", "(b) If, before expiry…")])
        self.assertEqual(ids(s["content"]), [(0, "8(5)"), (0, "8(6)"), (1, "8(6)(a)"), (1, "8(6)(b)")])
        self.assertEqual(s["content"][1]["text"], "")

    def test_section_line_numbering_is_subsections_lead_in_numbering_is_clauses(self):
        sub = build("1", [("P1", "(1) This Act may be called…"), ("P1", "(2) It shall come into force…")])
        defs = build("2", [("P1", "In this Sanhita,––"), ("P2", "(1) “act” …;"), ("P3", "(a) x;")])
        self.assertEqual(sub["content"][0]["kind"], "subsection")
        self.assertEqual([n["kind"] for n in defs["content"]], ["text", "clause"])
        self.assertEqual(defs["content"][1]["children"][0]["kind"], "subclause")
        self.assertEqual(defs["content"][1]["children"][0]["cite"], "Section 2(1)(a)")


class Attachment(unittest.TestCase):
    def test_resumed_words_after_clauses_belong_to_the_subsection(self):
        s = build("64", [("P1", "(2) Whoever,—"), ("P2", "(a) being a police officer;"), ("P2", "(b) being a public servant,"),
                         ("P0", "shall be punished with rigorous imprisonment."), ("P1", "(3) Next.")])
        sub2 = s["content"][0]
        self.assertEqual([c["id"] for c in sub2["children"]], ["64(2)(a)", "64(2)(b)", "64(2)-text-1"])
        self.assertIsNone(sub2["children"][2]["cite"])
        self.assertEqual(s["content"][1]["id"], "64(3)")

    def test_explanation_after_exception_is_explanation_to_that_exception(self):
        s = build("101", [("P1", "Except in the cases hereinafter excepted, culpable homicide is murder,—"),
                          ("P2", "(a) if …;"),
                          ("P1", "Exception 4.—Culpable homicide is not murder if …"),
                          ("P1", "Explanation.—It is immaterial …"),
                          ("P1", "Exception 5.—Culpable homicide is not murder when …")])
        tree = ids(s["content"])
        self.assertIn((1, "101-exc-4-expl"), tree)
        self.assertIn((0, "101-exc-5"), tree)
        expl = s["content"][2]["children"][0]
        self.assertEqual(expl["cite"], "Explanation to Exception 4 to Section 101")

    def test_provisos_are_ordinal_siblings(self):
        s = build("65", [("P1", "(1) Whoever … with fine:"), ("P1", "Provided that such fine shall be just:"),
                         ("P1", "Provided further that any fine shall be paid to the victim."), ("P1", "(2) Whoever …")])
        provisos = s["content"][0]["children"]
        self.assertEqual([p["cite"] for p in provisos], ["First proviso to Section 65(1)", "Second proviso to Section 65(1)"])
        self.assertEqual(s["content"][1]["id"], "65(2)")

    def test_numbered_provision_after_illustrations_closes_them(self):
        s = build("127", [("P1", "(1) Whoever wrongfully restrains …"), ("@ILL", "Illustrations."),
                          ("P1", "(a) A causes Z to go within a walled space."), ("P1", "(b) A places men with firearms."),
                          ("P1", "(2) Whoever wrongfully confines any person …")])
        self.assertEqual(ids(s["content"]), [
            (0, "127(1)"), (1, "127(1)-illustrations"), (2, "127(1)-illus-a"), (2, "127(1)-illus-b"), (0, "127(2)"),
        ])
        self.assertEqual(s["content"][0]["children"][0]["children"][1]["cite"], "Illustration (b) to Section 127(1)")

    def test_illustrations_after_single_explanation_illustrate_the_provision(self):
        s = build("316", [("P1", "(1) Whoever, being entrusted …"), ("P1", "Explanation 1.—A person …"),
                          ("P1", "Explanation 2.—A person …"), ("@ILL", "Illustrations."), ("P1", "(a) A, being executor …"),
                          ("P1", "(2) Whoever commits …")])
        self.assertIn((1, "316(1)-illustrations"), ids(s["content"]))

    def test_alternating_explanations_keep_their_own_illustrations(self):
        s = build("46", [("P1", "A person abets an offence …"), ("P1", "Explanation 1.—The abetment …"),
                         ("@ILL", "Illustrations."), ("P1", "(a) A instigates B …"),
                         ("P1", "Explanation 2.—It is not necessary …"), ("@ILL", "Illustration."), ("P1", "A instigates B …")])
        tree = ids(s["content"])
        self.assertIn((2, "46-expl-1-illus-a"), tree)
        self.assertIn((2, "46-expl-2-illus"), tree)

    def test_lone_unnumbered_exception_does_not_own_the_illustration(self):
        s = build("249", [("P1", "Whenever an offence …"), ("P1", "Exception.—This section shall not extend …"),
                          ("@ILL", "Illustration."), ("P1", "A, knowing that B has committed dacoity …")])
        self.assertEqual([n["id"] for n in s["content"]], ["249-text-1", "249-exc", "249-illustrations"])

    def test_closing_explanation_about_this_section_is_section_level(self):
        s = build("124", [("P1", "(1) Whoever causes …"), ("P1", "(2) Whoever throws …"),
                          ("P1", "Explanation 1.—For the purposes of this section, “acid” includes …"),
                          ("P1", "Explanation 2.—For the purposes of this section, …")])
        self.assertEqual([n["id"] for n in s["content"]], ["124(1)", "124(2)", "124-expl-1", "124-expl-2"])
        sub = build("64", [("P1", "(1) Whoever …"), ("P1", "(2) Whoever,—"), ("P1", "Explanation.—For the purposes of this sub-section,—")])
        self.assertEqual(sub["content"][1]["children"][0]["id"], "64(2)-expl")

    def test_tree_must_reproduce_print(self):
        sec = SectionBuilder("5", "H.", 1, lambda w: None)
        sec.add(Para("P1", "(1) Text.", 1))
        sec.source.append("a paragraph the tree never received")
        with self.assertRaises(ParseError):
            finalize(sec)


class Reconcile(unittest.TestCase):
    def test_punctuation_change_needs_review_but_dash_variant_does_not(self):
        self.assertEqual(classify(Block("P1", "Whoever, within India"), Block("P1", "Whoever within India")), "words")
        self.assertEqual(classify(Block("P1", "namely:––"), Block("P1", "namely:—")), "glyphs")
        self.assertEqual(classify(Block("P1", "abc"), Block("P2", "abc")), "indent")
        self.assertEqual(classify(Block("C", "abc"), Block("P1", "abc")), "boundary")


class PublishedData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((DATA_DIR / "bns.json").read_text(encoding="utf-8"))
        cls.nodes = {}

        def walk(nodes):
            for n in nodes:
                cls.nodes[n["id"]] = n
                walk(n.get("children", []))

        for num in cls.data["order"]:
            walk(cls.data["sections"][num]["content"])

    def test_every_section_and_chapter_present(self):
        self.assertEqual(self.data["order"], [str(i) for i in range(1, 359)])
        self.assertEqual(len(self.data["chapters"]), 20)
        self.assertEqual(sum(len(c["sections"]) for c in self.data["chapters"]), 358)

    def test_landmark_provisions(self):
        s103 = self.data["sections"]["103"]
        self.assertEqual((s103["heading"], s103["chapter"]), ("Punishment for murder.", "VI"))
        self.assertEqual(self.nodes["64(2)(f)"]["cite"], "Section 64(2)(f)")
        self.assertEqual(self.nodes["2(28)(k)(ii)"]["kind"], "item")
        self.assertTrue(self.nodes["358(1)"]["text"].startswith("The Indian Penal Code is hereby repealed."))
        self.assertEqual(self.nodes["358(1)"].get("refs"), ["45 of 1860."])

    def test_ids_are_unique_and_cites_present_on_citable_nodes(self):
        seen = set()
        for num in self.data["order"]:
            stack = list(self.data["sections"][num]["content"])
            while stack:
                n = stack.pop()
                self.assertNotIn(n["id"], seen)
                seen.add(n["id"])
                self.assertEqual(n["cite"] is None, n["kind"] == "text", n["id"])
                stack.extend(n.get("children", []))


if __name__ == "__main__":
    unittest.main()
