#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class SeriesForcantesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((OUT / "series_forcantes_stz_mucum_latest.json").read_text(encoding="utf-8"))
        cls.html = (OUT / "series_forcantes_stz_mucum.html").read_text(encoding="utf-8")

    def test_status_and_gates(self) -> None:
        self.assertEqual(self.data["status"], "series_auditadas_v1")
        self.assertFalse(self.data["readiness"]["pode_calibrar_HEC_agora"])
        self.assertTrue(self.data["readiness"]["pode_prototipar_RNA_com_mascaras"])

    def test_rain_verdicts(self) -> None:
        rain = self.data["rain"]
        self.assertGreaterEqual(rain["86472000"]["pct_present"], 90)
        self.assertEqual(rain["A894"]["verdict"], "vazio")
        self.assertEqual(rain["A894"]["present"], 0)
        self.assertIn(rain["86472600"]["verdict"], {"com_buracos", "fraca"})
        self.assertLess(rain["86472600"]["pct_present"], 90)

    def test_level_prata_and_targets(self) -> None:
        level = self.data["level"]
        self.assertTrue(level["86472000"]["in_live_robo_stz"])
        self.assertTrue(level["86472600"]["in_live_robo_stz"])
        self.assertFalse(level["86510000"]["in_live_robo_stz"])
        self.assertTrue(
            level["86510000"]["in_mucum_catalog"]
            or bool(level["86510000"]["excel_columns"])
            or bool(level["86510000"]["event_files"])
        )
        self.assertIn("previne_robo_ESTACOES_NIVEL_stz", level["86125500"]["sources"])

    def test_html(self) -> None:
        low = self.html.lower()
        self.assertIn("buraco", low)
        self.assertIn("calibrar hec agora", low)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("series_forcantes_stz_mucum.html", idx)


if __name__ == "__main__":
    unittest.main()
