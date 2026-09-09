#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class ForcantesStzMucumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((OUT / "forcantes_stz_mucum_latest.json").read_text(encoding="utf-8"))
        cls.html = (OUT / "forcantes_stz_mucum.html").read_text(encoding="utf-8")

    def test_status_and_discipline(self) -> None:
        self.assertEqual(self.data["status"], "forcantes_congeladas_v1")
        rule = self.data["discipline_rule"].lower().replace("ã", "a")
        self.assertIn("nao definem subbacias hec", rule)

    def test_stz_short_lists(self) -> None:
        stz = self.data["models"]["santa_tereza"]
        self.assertEqual(stz["target"]["codigo"], "86472600")
        level = [s["codigo"] for s in stz["level_forcings"]]
        rain = [s["codigo"] for s in stz["rain_forcings"]]
        self.assertEqual(level[:3], ["86472000", "86507000", "86125500"])
        self.assertIn("86448000", level)
        self.assertEqual(rain[:3], ["86472000", "86472600", "2851072"])
        self.assertEqual(stz["counts"]["level_primary"], 3)
        self.assertEqual(stz["counts"]["rain_primary"], 3)
        self.assertNotIn("86510000", level)

    def test_mucum_adds_stz_as_critical(self) -> None:
        muc = self.data["models"]["mucum"]
        self.assertEqual(muc["target"]["codigo"], "86510000")
        level = [s["codigo"] for s in muc["level_forcings"]]
        self.assertEqual(level[0], "86472600")
        self.assertIn("86472000", level)
        self.assertIn("86507000", level)
        self.assertIn("86125500", level)
        self.assertEqual(muc["counts"]["level_primary"], 4)

    def test_exclusions(self) -> None:
        excl = self.data["excluded_from_both"]
        self.assertTrue({"Guaporé", "Forqueta", "Baixo Taquari-Antas"} <= set(excl["upgs"]))
        self.assertTrue({"7864", "7862"} <= set(excl["families"]))
        joined = " ".join(excl["examples_not_used"]).lower()
        self.assertIn("2851044", joined)

    def test_html_and_index_link(self) -> None:
        self.assertIn("Lista curta congelada", self.html)
        self.assertIn("86472600", self.html)
        self.assertIn("86510000", self.html)
        self.assertIn("ainda sem hec", self.html.lower())
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("forcantes_stz_mucum.html", idx)
        domains = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(domains["status"], "forcantes_congeladas_aguardando_estrutura")


if __name__ == "__main__":
    unittest.main()
