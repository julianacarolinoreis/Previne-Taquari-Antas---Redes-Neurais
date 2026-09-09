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
        self.assertEqual(self.data["status"], "modelo_mucum_eventwise_v1_6_fechado_stz_q_blocked")
        self.assertIn("NÃO promover common-search", self.data["label_honest"])
        self.assertFalse(self.data["santa_tereza"]["in_this_package"])
        self.assertTrue(self.data["params_median_diagnostic_only"]["promotion_blocked"])
        self.assertGreaterEqual(len(self.data["included_events"]), 8)
        self.assertGreaterEqual(self.data["calibration_source"]["mean_nse_eventwise_ok"], 0.80)
        peak_errs = [e["metrics"]["peak_relative_error"] for e in self.data["params_library_eventwise"]]
        self.assertLessEqual(sum(peak_errs) / len(peak_errs), 0.025)
        self.assertIn("E22", self.data["included_events"])
        e22 = next(e for e in self.data["params_library_eventwise"] if e["event_id"] == "E22")
        self.assertLessEqual(e22["metrics"]["peak_relative_error"], 0.03)
        e27 = next(e for e in self.data["params_library_eventwise"] if e["event_id"] == "E27")
        self.assertLessEqual(e27["metrics"]["peak_relative_error"], 0.04)
        e21 = next(e for e in self.data["params_library_eventwise"] if e["event_id"] == "E21")
        self.assertLessEqual(e21["metrics"]["peak_relative_error"], 0.02)

    def test_params_csv(self) -> None:
        path = OUT / self.data["artifacts"]["params_csv"]
        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertGreaterEqual(len(rows), 8)
        self.assertIn("E28", {r["event_id"] for r in rows})
        self.assertIn("peak_relative_error", rows[0])

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
