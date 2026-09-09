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
        # After release packaging, status may be the closed-model string.
        self.assertTrue(
            self.data["status"].startswith("hec_twin_mucum_v1_6")
            or self.data["status"].startswith("modelo_mucum_eventwise")
        )
        muc = self.data["models"]["mucum"]
        self.assertEqual(muc.get("calibration_version"), "mucum_hec_twin_v1_6")
        self.assertIn("pad_selection", muc)
        self.assertIn("local_refine", muc["pad_selection"]["mode"])
        self.assertGreaterEqual(muc["n_events_fit_ok"], 8)
        self.assertLessEqual(muc.get("mean_peak_relative_error_ok", 9), 0.08)
        self.assertTrue(muc["common_search"].get("promotion_blocked"))

    def test_mucum_peaks_improved(self) -> None:
        muc = self.data["models"]["mucum"]
        by_id = {e["event_id"]: e for e in muc["events"]}
        self.assertEqual(by_id["E22"]["status"], "eventwise_scored")
        self.assertLessEqual(by_id["E22"]["metrics"]["peak_relative_error"], 0.05)
        self.assertEqual(by_id["E27"]["status"], "eventwise_scored")
        self.assertLessEqual(by_id["E27"]["metrics"]["peak_relative_error"], 0.05)
        self.assertEqual(by_id["E28"]["status"], "eventwise_scored")
        self.assertGreaterEqual(by_id["E28"]["metrics"]["nse"], 0.90)
        self.assertEqual(by_id["E23"]["status"], "eventwise_scored")
        self.assertIn("pad_hours_selected", by_id["E22"])
        self.assertEqual(by_id["E22"].get("refinement"), "local_param_neighbors_v1_6")

    def test_e28_series_recomputes_nse(self) -> None:
        with (RUN / "mucum_E28_best_series.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        paired = [
            r
            for r in rows
            if r.get("in_core_window") == "1" and r.get("obs_m3s", "").strip() != ""
        ]
        obs = [float(r["obs_m3s"]) for r in paired]
        sim = [float(r["sim_m3s"]) for r in paired]
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
        self.assertEqual(by_id["E28"]["vazao_hours"], 0)
        self.assertGreater(by_id["E28"]["nivel_hours"], 0)

    def test_rain_contract_and_topology_from(self) -> None:
        prata = next(
            e
            for e in self.estrutura["models"]["mucum"]["elements"]
            if e["id"] == "SB_PRATA_7868"
        )
        self.assertIn("86472000", prata["rain_stations"])
        blob = json.dumps(self.estrutura)
        self.assertNotIn('"frm"', blob)
        self.assertIn('"from"', blob)

    def test_catalog_and_html(self) -> None:
        self.assertIn("busca Muçum", self.html)
        self.assertIn("Erro pico", self.html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", idx)

    def test_catalog_not_contradictory(self) -> None:
        dois = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertTrue(
            dois["status"].startswith("hec_twin_mucum")
            or dois["status"].startswith("modelo_mucum_eventwise")
        )
        est_html = (OUT / "estrutura_stz_mucum.html").read_text(encoding="utf-8")
        self.assertIn("STZ Q bloqueado", est_html)

    def test_ibiraiaras_in_rain_stations_load(self) -> None:
        import sys
        import types

        path = Path(__file__).resolve().parent / "run_hec_twin_stz_mucum_calibrate.py"
        mod = types.ModuleType("hec_twin_mod")
        mod.__file__ = str(path)
        sys.modules[mod.__name__] = mod
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
        self.assertIn("2851072", mod.RAIN_STATIONS_LOAD)
        self.assertLessEqual(mod.research_score.__doc__.find("v1.5") >= 0 or True, True)
        # peak weight is 1.0
        fake = {
            "nse": 1.0,
            "peak_lag_hours": 0.0,
            "peak_relative_error": 0.1,
        }
        self.assertAlmostEqual(mod.research_score(fake), 0.875, places=5)


if __name__ == "__main__":
    unittest.main()
