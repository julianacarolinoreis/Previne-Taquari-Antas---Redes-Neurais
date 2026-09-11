#!/usr/bin/env python3
"""Contract tests for the Santa Tereza RNA article draft and its tables."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from .build_artigo_rna_santa_tereza import build
except ImportError:
    from build_artigo_rna_santa_tereza import build


ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "assets" / "data" / "artigo_rna_santa_tereza.json"
PAGE = ROOT / "pesquisas" / "artigo-rna-santa-tereza.html"
MANUSCRIPT = ROOT / "docs" / "artigo_rna_santa_tereza.md"
ACERVO = ROOT / "assets" / "data" / "acervo_pesquisas.json"
INDEX = ROOT / "index.html"


class ArtigoRnaSantaTerezaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(TABLES.read_text(encoding="utf-8"))
        cls.rebuilt = build()
        cls.page = PAGE.read_text(encoding="utf-8")
        cls.manuscript = MANUSCRIPT.read_text(encoding="utf-8")
        cls.acervo = json.loads(ACERVO.read_text(encoding="utf-8"))

    def test_tables_match_the_embedded_santa_tereza_recorte(self) -> None:
        self.assertEqual(self.report["n_models"], self.rebuilt["n_models"])
        self.assertEqual(self.report["horizons"], self.rebuilt["horizons"])
        self.assertEqual(self.report["n_models"], 282)
        self.assertEqual(self.report["horizons"]["2h"], 10)
        self.assertEqual(self.report["horizons"]["4h"], 117)
        self.assertEqual(self.report["horizons"]["8h"], 111)
        self.assertEqual(self.report["horizons"]["12h"], 44)
        self.assertTrue(self.report["research_only"])
        self.assertFalse(self.report["official_alert"])

    def test_live_2h_champion_is_the_principal_feed_model(self) -> None:
        champion = self.report["champions"]["2h"][0]
        self.assertEqual(champion["modelo"], self.report["live_principal_2h"])
        self.assertGreater(champion["score_equilibrio"], 0.96)
        self.assertFalse(champion["chuva"])
        self.assertEqual(champion["n_inputs"], 15)

    def test_article_page_is_a_research_draft_and_loads_tables(self) -> None:
        self.assertIn("não é alerta oficial", self.page.lower())
        self.assertIn("artigo_rna_santa_tereza.json", self.page)
        self.assertIn("009_alt_STZ_2H_R09", self.page)
        self.assertIn("score de equilíbrio", self.page.lower())
        self.assertNotIn("alerta oficial da defesa civil emitido por este modelo", self.page.lower())

    def test_manuscript_keeps_the_consolidated_claims(self) -> None:
        self.assertIn("282", self.manuscript)
        self.assertIn("009_alt_STZ_2H_R09", self.manuscript)
        self.assertIn("C0289", self.manuscript)
        self.assertIn("Kitanidis", self.manuscript)
        self.assertIn("Finck", self.manuscript)

    def test_acervo_lists_the_draft_as_research(self) -> None:
        entries = self.acervo["entries"]
        self.assertEqual(self.acervo["count"], len(entries))
        match = [item for item in entries if item.get("href") == "pesquisas/artigo-rna-santa-tereza.html"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["category"], "RNA")
        self.assertEqual(match[0]["status"], "estudo")
        self.assertIn("não é alerta", match[0]["caveat"].lower())

    def test_index_recorte_still_has_the_source_script(self) -> None:
        self.assertRegex(
            INDEX.read_text(encoding="utf-8"),
            r'<script\s+id="data"\s+type="application/json">',
        )


if __name__ == "__main__":
    unittest.main()
