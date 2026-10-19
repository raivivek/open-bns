import json
import re
import unittest

from bns.paths import DATA_DIR
from bns.site import Act, Linker, validate_stats


class CrossReferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.act = Act(json.loads((DATA_DIR / "bns.json").read_text(encoding="utf-8")))
        cls.linker = Linker(cls.act)

    def links(self, text: str, num: str = "1", nid: str = "1") -> list[tuple[str, str]]:
        html = self.linker.link(text, num, nid, lambda t: (t, t))
        return re.findall(r'<a class="xr" href="([^"]+)"[^>]*>([^<]+)</a>', html)

    def test_provision_chain_links_to_deepest_anchor(self):
        self.assertEqual(self.links("clause (f) of sub-section (2) of section 64"), [("64(2)(f)", "clause (f) of sub-section (2) of section 64")])

    def test_section_lists_link_each_number(self):
        self.assertEqual([t for t, _ in self.links("sections 103, 105 and 307")], ["103", "105", "307"])

    def test_other_enactments_stay_plain(self):
        for text in (
            "section 2 of the Mental Healthcare Act, 2017",
            "section 6 of the General Clauses Act, 1897",
            "section 82 of the Bharatiya Nagarik Suraksha Sanhita, 2023",
        ):
            self.assertEqual(self.links(text), [], text)

    def test_explanation_and_exception_references(self):
        self.assertEqual(self.links("Explanation 1 to section 63"), [("63-expl-1", "Explanation 1 to section 63")])
        self.assertEqual(self.links("the same proviso as Exception 1 of section 101"), [("101-exc-1", "Exception 1 of section 101")])

    def test_relative_subsection_resolves_within_current_section(self):
        self.assertEqual(self.links("referred to in sub-section (1)", num="189", nid="189(2)"), [("189(1)", "sub-section (1)")])

    def test_long_citation_names_levels(self):
        self.assertEqual(self.act.long["64(2)(f)"], "clause (f) of sub-section (2) of section 64")
        # Definitions in s. 2 open after lead-in words: numbered items are clauses.
        self.assertEqual(self.act.long["2(28)(k)(ii)"], "item (ii) of sub-clause (k) of clause (28) of section 2")
        self.assertEqual(self.act.long["101-exc-4-expl"], "the Explanation to Exception 4 to section 101")
        self.assertEqual(self.act.long["65(1)-proviso-2"], "the second proviso to sub-section (1) of section 65")


class StatsData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.act = Act(json.loads((DATA_DIR / "bns.json").read_text(encoding="utf-8")))

    def item(self, **kw):
        base = {"label": "L", "value": "1", "detail": "D", "provisions": ["103(2)"],
                "sources": [{"title": "T", "url": "https://pib.gov.in/x"}]}
        base.update(kw)
        return {"groups": [{"title": "G", "items": [base]}]}

    def test_published_stats_are_sourced_and_cite_real_provisions(self):
        validate_stats(json.loads((DATA_DIR / "stats.json").read_text(encoding="utf-8")), self.act)

    def test_rejects_unsourced_or_dangling_items(self):
        validate_stats(self.item(), self.act)
        for bad in (self.item(sources=[]), self.item(provisions=["999(9)"]),
                    self.item(sources=[{"title": "T", "url": "http://insecure"}])):
            with self.assertRaises(SystemExit):
                validate_stats(bad, self.act)


if __name__ == "__main__":
    unittest.main()
