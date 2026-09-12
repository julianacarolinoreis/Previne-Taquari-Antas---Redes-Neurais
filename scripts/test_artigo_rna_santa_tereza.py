#!/usr/bin/env python3
"""Contract tests for the Santa Tereza RNA article draft and its tables."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from .build_artigo_rna_santa_tereza import METRIC_KEYS, build, short_label
except ImportError:
    from build_artigo_rna_santa_tereza import METRIC_KEYS, build, short_label


ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "assets" / "data" / "artigo_rna_santa_tereza.json"
PAGE = ROOT / "pesquisas" / "artigo-rna-santa-tereza.html"
MANUSCRIPT = ROOT / "docs" / "artigo_rna_santa_tereza.md"
ACERVO = ROOT / "assets" / "data" / "acervo_pesquisas.json"
INDEX = ROOT / "index.html"
HORIZONS = ("2h", "4h", "8h", "12h")
COMBO_IDS = (
    "2H",
    "núcleo",
    "núcleo+86298000",
    "ampliado",
    "C0289",
    "C0078",
    "C0265",
    "C0149",
)


class ArtigoRnaSantaTerezaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(TABLES.read_text(encoding="utf-8"))
        cls.rebuilt = build()
        cls.page = PAGE.read_text(encoding="utf-8")
        cls.manuscript = MANUSCRIPT.read_text(encoding="utf-8")
        cls.acervo = json.loads(ACERVO.read_text(encoding="utf-8"))
        cls.page_l = cls.page.lower()
        cls.ms_l = cls.manuscript.lower()

    def test_tables_match_the_embedded_santa_tereza_recorte(self) -> None:
        self.assertEqual(self.report["n_models"], self.rebuilt["n_models"])
        self.assertEqual(self.report["horizons"], self.rebuilt["horizons"])
        self.assertEqual(self.report["principal_combinations"], self.rebuilt["principal_combinations"])
        self.assertEqual(self.report["n_models"], 282)
        self.assertEqual(self.report["horizons"]["2h"], 10)
        self.assertEqual(self.report["horizons"]["4h"], 117)
        self.assertEqual(self.report["horizons"]["8h"], 111)
        self.assertEqual(self.report["horizons"]["12h"], 44)
        self.assertTrue(self.report["research_only"])
        self.assertFalse(self.report["official_alert"])
        self.assertEqual(self.report["schema_version"], "previne_artigo_rna_santa_tereza_v2")

    def test_live_2h_champion_is_the_principal_feed_model(self) -> None:
        champion = self.report["champions"]["2h"]
        self.assertIsInstance(champion, dict)
        self.assertNotIsInstance(champion, list)
        self.assertEqual(champion["modelo"], self.report["live_principal_2h"])
        self.assertGreater(champion["score_equilibrio"], 0.96)
        self.assertFalse(champion["chuva"])
        self.assertEqual(champion["n_inputs"], 15)

    def test_one_champion_per_horizon(self) -> None:
        self.assertEqual(set(self.report["champions"]), set(HORIZONS))
        self.assertEqual(self.report["champions"]["4h"]["modelo"], "V01_R10_T19-21_V1-3-5-15-17_nh48_nit10_cic100000")
        self.assertIn("C0289", str(self.report["champions"]["8h"]["modelo"]))
        self.assertEqual(self.report["champions"]["8h"]["tipo"], "alt")
        self.assertEqual(self.report["champions"]["12h"]["modelo"], "004_conv_C0149_R01_T2_V1_3")
        for horizon, row in self.report["champions"].items():
            self.assertEqual(row["horizonte"], horizon)
            self.assertIsInstance(row["modelo"], str)
            self.assertGreater(row["score_equilibrio"], 0)

    def test_principal_combinations_are_variables_without_metrics(self) -> None:
        rows = self.report["principal_combinations"]
        self.assertEqual([row["id"] for row in rows], list(COMBO_IDS))
        for row in rows:
            leaked = METRIC_KEYS.intersection(row)
            self.assertFalse(leaked, f"{row['id']} vazou métricas: {leaked}")
            self.assertIn("variables_short", row)
            self.assertTrue(row["variables_short"])
            self.assertNotIn("MAE_teste_cm", row)
            self.assertNotIn("score_equilibrio", row)
        two = rows[0]
        self.assertFalse(two["chuva"])
        self.assertIn("ST", two["variables_short"])
        self.assertNotIn("chuva 36 h", two["variables_short"])
        four_rain = [row for row in rows if row["horizonte"] == "4h"]
        self.assertTrue(all(row["chuva"] and "chuva 36 h" in row["variables_short"] for row in four_rain))
        ampliado = next(row for row in rows if row["id"] == "ampliado")
        self.assertIn("Carreiro", ampliado["variables_short"])
        c0289 = next(row for row in rows if row["id"] == "C0289")
        self.assertIn("86430900", c0289["variables_short"])
        self.assertEqual(self.report["n_unique_input_sets"]["2h"], 1)
        self.assertEqual(self.report["n_unique_input_sets"]["4h"], 6)

    def test_short_label_unifies_catalog_aliases(self) -> None:
        self.assertEqual(short_label("Santa Tereza — nível (D-1h)"), "ST D–1 h")
        self.assertEqual(short_label("chuva média acum 36h"), "chuva 36 h")
        self.assertEqual(short_label("acum 36h — chuva média"), "chuva 36 h")
        self.assertEqual(short_label("Veranopolis — nível D-14H"), "Veranópolis D–14 h")
        self.assertEqual(short_label("nível (D-14h) 86430900"), "86430900 D–14 h")
        self.assertEqual(short_label("Est. 86430900 — nível (D-14h)"), "86430900 D–14 h")

    def test_article_page_is_a_research_draft_and_loads_tables(self) -> None:
        self.assertIn("não é alerta oficial", self.page_l)
        self.assertIn("artigo_rna_santa_tereza.json", self.page)
        self.assertIn("009_alt_STZ_2H_R09", self.page)
        self.assertIn("score de equilíbrio", self.page_l)
        self.assertIn("tbl-combinations", self.page)
        self.assertIn("tbl-champions", self.page)
        self.assertNotIn("tbl-2h", self.page)
        self.assertNotIn("tbl-family", self.page)
        self.assertNotIn("tbl-inputs", self.page)
        self.assertNotIn("três melhores", self.page_l)
        self.assertNotIn("tres melhores", self.page_l)
        self.assertNotIn("alerta oficial da defesa civil emitido por este modelo", self.page_l)
        self.assertIn("data.champions", self.page)
        self.assertIn("principal_combinations", self.page)
        self.assertIn("row.MAE_teste_cm", self.page)
        self.assertNotIn("MAE_teste_cm_mediana", self.page)
        self.assertRegex(self.page, r"\.bar-fill\s*\{[^}]*display:\s*block")

    def test_manuscript_keeps_the_consolidated_claims(self) -> None:
        self.assertIn("282", self.manuscript)
        self.assertIn("009_alt_STZ_2H_R09", self.manuscript)
        self.assertIn("C0289", self.manuscript)
        self.assertIn("C0078", self.manuscript)
        self.assertIn("C0265", self.manuscript)
        self.assertIn("Kitanidis", self.manuscript)
        self.assertIn("Finck", self.manuscript)
        self.assertIn("Quadro 1", self.manuscript)
        self.assertNotIn("três melhores", self.ms_l)
        methods, results = self.manuscript.split("## 4. Resultados", 1)
        self.assertIn("C0289", methods)
        self.assertIn("C0078", methods)
        self.assertIn("sem métricas", methods.lower())
        self.assertIn("009_alt_STZ_2H_R09", results)
        self.assertIn("V01_R10_T19-21", results)
        self.assertIn("altR_004_08_8h_alt_8H_ALT_C0289", results)
        self.assertIn("004_conv_C0149", results)
        self.assertIn("OLIVEIRA, G. G.; PEDROLLO, O. C.; CASTRO, N. M. R. O desempenho das redes neurais", self.manuscript)
        self.assertIn("julianacarolinoreis@gmail.com", self.manuscript)
        self.assertIn("Campus Litoral Norte", self.manuscript)
        self.assertIn("Figura 1", self.manuscript)
        self.assertIn("Nash-Sutcliffe (NS)", self.manuscript)
        self.assertNotIn("Garcia de Oliveira et al", self.manuscript)

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
