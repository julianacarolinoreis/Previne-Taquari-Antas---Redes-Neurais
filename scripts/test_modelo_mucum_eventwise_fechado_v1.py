#!/usr/bin/env python3
import csv
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"


class ModeloMucumEventwiseFechadoV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(
            (OUT / "modelo_mucum_eventwise_v1_fechado_latest.json").read_text(encoding="utf-8")
        )
        cls.html = (OUT / "modelo_mucum_eventwise_v1_fechado.html").read_text(encoding="utf-8")

    def test_status_and_honesty(self) -> None:
        self.assertEqual(self.data["status"], "modelo_mucum_eventwise_v1_fechado_stz_q_blocked")
        self.assertIn("NÃO promover common-search", self.data["label_honest"])
        self.assertFalse(self.data["santa_tereza"]["in_this_package"])
        self.assertTrue(self.data["params_median_diagnostic_only"]["promotion_blocked"])
        self.assertTrue(self.data["common_search_verdict"]["promotion_blocked"])
        self.assertFalse(self.data["scope_discipline"]["is_g040_basin"])

    def test_library_has_eight_ok_events(self) -> None:
        ids = self.data["included_events"]
        self.assertEqual(
            ids, ["E20", "E21", "E22", "E24", "E25", "E27", "E28", "E31"]
        )
        self.assertEqual(len(self.data["params_library_eventwise"]), 8)
        self.assertGreaterEqual(self.data["calibration_source"]["mean_nse_eventwise_ok"], 0.85)
        for e in self.data["params_library_eventwise"]:
            self.assertGreaterEqual(e["nse"], 0.0)
            self.assertIn("tc", e["params"])

    def test_params_csv(self) -> None:
        path = OUT / self.data["artifacts"]["params_csv"]
        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 8)
        self.assertIn("E28", {r["event_id"] for r in rows})

    def test_html_and_catalog_links(self) -> None:
        self.assertIn("Modelo Muçum", self.html)
        self.assertIn("Biblioteca de parâmetros", self.html)
        self.assertIn("STZ fora", self.html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("modelo_mucum_eventwise_v1_fechado.html", idx)
        dois = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(dois["status"], self.data["status"])
        self.assertIn("modelo_mucum_fechado", dois)


if __name__ == "__main__":
    unittest.main()
