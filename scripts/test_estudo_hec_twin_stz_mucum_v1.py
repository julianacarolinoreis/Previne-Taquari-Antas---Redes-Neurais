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
        cls.estrutura = json.loads((OUT / "estrutura_stz_mucum_latest.json").read_text(encoding="utf-8"))

    def test_status_and_engine(self) -> None:
        self.assertEqual(self.data["status"], "hec_twin_mucum_eventwise_scored_stz_q_blocked")
        self.assertTrue(self.data["engine"]["not_hec_hms_binary"])
        self.assertIn("research_score", self.data["engine"]["optimization_objective"])
        self.assertIn("Muçum", self.data["purpose"])
        self.assertNotIn("calibracao HEC (gemeo Python) dos modelos-alvo STZ", self.data["purpose"])

    def test_mucum_eventwise_and_common(self) -> None:
        muc = self.data["models"]["mucum"]
        by_id = {e["event_id"]: e for e in muc["events"]}
        self.assertEqual(by_id["E19"]["status"], "fit_failed_eventwise")
        self.assertEqual(by_id["E22"]["status"], "eventwise_scored")
        self.assertAlmostEqual(by_id["E22"]["metrics"]["nse"], 0.73, places=2)
        self.assertAlmostEqual(by_id["E28"]["metrics"]["nse"], 0.95, places=2)
        # E28 must not keep dry preferred Carreiro gage
        e28_rain = by_id["E28"]["rain"]
        self.assertEqual(e28_rain["subbasin_sources"]["SB_CARREIRO_7866"], "86472000")
        self.assertTrue(e28_rain["fallback_notes"])
        self.assertGreater(muc["mean_nse_eventwise"], 0.7)
        self.assertIn("common_search", muc)
        self.assertIsNotNone(muc["common_search"]["mean_nse"])

    def test_e28_series_recomputes_nse(self) -> None:
        with (RUN / "mucum_E28_best_series.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        obs = [float(r["obs_m3s"]) for r in rows]
        sim = [float(r["sim_m3s"]) for r in rows]
        mean_o = sum(obs) / len(obs)
        ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
        ss_tot = sum((o - mean_o) ** 2 for o in obs)
        nse = 1.0 - ss_res / ss_tot
        reported = next(
            e["metrics"]["nse"]
            for e in self.data["models"]["mucum"]["events"]
            if e["event_id"] == "E28"
        )
        self.assertAlmostEqual(nse, reported, places=5)

    def test_stz_q_blocked_inventory_measured(self) -> None:
        stz = self.data["models"]["santa_tereza"]
        self.assertEqual(stz["status"], "q_calibration_blocked_no_ana_vazao")
        by_id = {e["event_id"]: e for e in stz["events_inventory"]}
        self.assertEqual(by_id["E19"]["nivel_hours"], 0)
        self.assertEqual(by_id["E19"]["vazao_hours"], 0)
        self.assertGreater(by_id["E28"]["nivel_hours"], 0)
        self.assertEqual(by_id["E28"]["vazao_hours"], 0)
        self.assertIn("Sem Nivel", by_id["E19"]["note"])

    def test_rain_contract_and_topology_from(self) -> None:
        prata = next(
            e
            for e in self.estrutura["models"]["mucum"]["elements"]
            if e["id"] == "SB_PRATA_7868"
        )
        self.assertIn("86472000", prata["rain_stations"])
        self.assertIn("2851072", prata["rain_stations_rna_aspirational"])
        blob = json.dumps(self.estrutura)
        self.assertNotIn('"frm"', blob)
        self.assertIn('"from"', blob)

    def test_catalog_and_html(self) -> None:
        self.assertIn("busca Muçum", self.html)
        self.assertIn("research_score", self.html)
        self.assertIn("Common-search", self.html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", idx)
        pesquisas = (Path(__file__).resolve().parents[1] / "pesquisas.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", pesquisas)


if __name__ == "__main__":
    unittest.main()
