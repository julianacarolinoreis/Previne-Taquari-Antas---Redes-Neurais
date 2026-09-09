#!/usr/bin/env python3
import csv
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class MascaraChuvaNucleoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((OUT / "mascara_chuva_nucleo_latest.json").read_text(encoding="utf-8"))
        cls.csv_path = OUT / "mascara_chuva_nucleo_horaria.csv"
        with cls.csv_path.open(newline="", encoding="utf-8") as fh:
            cls.rows = list(csv.DictReader(fh))

    def test_status_and_counts(self) -> None:
        self.assertEqual(self.data["status"], "mascara_chuva_nucleo_gerada_v1")
        self.assertGreater(self.data["counts"]["usable_after_r6"], 10000)
        self.assertEqual(self.data["counts"]["rows_total"], len(self.rows))
        self.assertEqual(self.data["level_masks"]["status"], "nao_geradas_neste_passo")

    def test_r1_empty_not_imputed(self) -> None:
        missing = [
            r
            for r in self.rows
            if r["mask_chuva_86472600"] == "0"
        ]
        self.assertTrue(missing)
        self.assertTrue(all(r["chuva_86472600"] == "" for r in missing[:500]))

    def test_usable_requires_core_and_window(self) -> None:
        usable = [r for r in self.rows if r["usable_stz_rain_v1"] == "1"]
        self.assertTrue(usable)
        for r in usable[:200]:
            self.assertEqual(r["in_overlap_window_r6"], "1")
            self.assertEqual(r["core_rain_complete"], "1")
            self.assertEqual(r["mask_chuva_86472000"], "1")
            self.assertEqual(r["mask_chuva_86472600"], "1")
            self.assertEqual(r["mask_chuva_02851072"], "1")
            self.assertNotEqual(r["chuva_86472600"], "")

    def test_html_and_index(self) -> None:
        html = (OUT / "mascara_chuva_nucleo.html").read_text(encoding="utf-8")
        self.assertIn("buraco continua buraco", html.lower())
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("mascara_chuva_nucleo.html", idx)


if __name__ == "__main__":
    unittest.main()
