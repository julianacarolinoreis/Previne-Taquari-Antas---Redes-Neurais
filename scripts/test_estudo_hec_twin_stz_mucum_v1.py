#!/usr/bin/env python3
import csv
import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "data" / "estudo_bacia_taquari_antas"
RUN = OUT / "hec_twin_stz_mucum_v1"


class HecTwinStzMucumV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((OUT / "hec_twin_stz_mucum_v1_latest.json").read_text(encoding="utf-8"))
        cls.html = (OUT / "hec_twin_stz_mucum_v1.html").read_text(encoding="utf-8")

    def test_status_and_engine(self) -> None:
        self.assertEqual(self.data["status"], "hec_twin_mucum_calibrado_stz_q_bloqueado")
        self.assertTrue(self.data["engine"]["not_hec_hms_binary"])
        self.assertIn("Initial+Constant", self.data["engine"]["methods"])

    def test_mucum_eventwise_nse(self) -> None:
        muc = self.data["models"]["mucum"]
        by_id = {e["event_id"]: e for e in muc["events"]}
        self.assertAlmostEqual(by_id["E22"]["metrics"]["nse"], 0.73, places=2)
        self.assertAlmostEqual(by_id["E24"]["metrics"]["nse"], 0.80, places=2)
        self.assertAlmostEqual(by_id["E27"]["metrics"]["nse"], 0.82, places=2)
        self.assertAlmostEqual(by_id["E28"]["metrics"]["nse"], 0.95, places=2)
        self.assertLess(by_id["E19"]["metrics"]["nse"], -1.0)
        self.assertAlmostEqual(muc["mean_nse_eventwise_excluding_e19"], 0.823, places=2)

    def test_e28_series_recomputes_nse(self) -> None:
        rows = list(csv.DictReader((RUN / "mucum_E28_best_series.csv").open(encoding="utf-8")))
        obs = [float(r["obs_m3s"]) for r in rows]
        sim = [float(r["sim_m3s"]) for r in rows]
        mean_o = sum(obs) / len(obs)
        ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
        ss_tot = sum((o - mean_o) ** 2 for o in obs)
        nse = 1.0 - ss_res / ss_tot
        self.assertAlmostEqual(nse, 0.948289, places=4)

    def test_stz_q_blocked(self) -> None:
        stz = self.data["models"]["santa_tereza"]
        self.assertEqual(stz["status"], "q_calibration_blocked_no_ana_vazao")
        self.assertEqual(stz["target"], "86472600")
        self.assertTrue(all(e["vazao_hours"] == 0 for e in stz["events_inventory"]))

    def test_catalog_and_html(self) -> None:
        self.assertIn("Calibração HEC", self.html)
        self.assertIn("0.823", self.html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", idx)
        pesquisas = (Path(__file__).resolve().parents[1] / "pesquisas.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", pesquisas)


if __name__ == "__main__":
    unittest.main()
