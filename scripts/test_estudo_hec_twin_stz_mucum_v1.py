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
        self.assertEqual(self.data["status"], "modelo_mucum_eventwise_v1_fechado_stz_q_blocked")
        self.assertTrue(self.data["engine"]["not_hec_hms_binary"])
        muc = self.data["models"]["mucum"]
        self.assertEqual(muc.get("calibration_version"), "mucum_hec_twin_v1_4")
        self.assertIn("mucum_release", self.data)
        self.assertEqual(self.data["mucum_release"]["status"], self.data["status"])
        self.assertGreaterEqual(muc["n_events_scored"], 10)
        cs = muc["common_search"]
        self.assertIn("external_holdout", cs)
        self.assertTrue(cs.get("promotion_blocked") or cs.get("external_holdout", {}).get("mean_test_nse") is not None)
        self.assertTrue(any(g["id"] == "stz_q_curve" for g in muc["gaps_remaining"]))

    def test_mucum_eventwise_and_common(self) -> None:
        muc = self.data["models"]["mucum"]
        by_id = {e["event_id"]: e for e in muc["events"]}
        self.assertIn("E26", by_id)
        self.assertIn("E31", by_id)
        self.assertEqual(by_id["E19"]["status"], "fit_failed_eventwise")
        self.assertEqual(by_id["E28"]["status"], "eventwise_scored")
        self.assertGreaterEqual(by_id["E28"]["metrics"]["nse"], 0.85)
        self.assertGreater(muc["mean_nse_eventwise"], 0.5)
        # 2851072 should appear as a source somewhere when preferred wet
        sources = []
        for e in muc["events"]:
            sources.extend((e.get("rain") or {}).get("subbasin_sources", {}).values())
        self.assertTrue(any(s == "2851072" for s in sources) or any(
            (e.get("rain") or {}).get("fallback_notes") for e in muc["events"]
        ))

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
        self.assertGreaterEqual(len(by_id), 10)
        self.assertEqual(by_id["E28"]["vazao_hours"], 0)
        self.assertGreater(by_id["E28"]["nivel_hours"], 0)
        # expanded events still no Vazao
        self.assertEqual(by_id["E31"]["vazao_hours"], 0)

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
        self.assertIn("O que ainda falta", self.html)
        self.assertIn("Externos", self.html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", idx)
        pesquisas = (Path(__file__).resolve().parents[1] / "pesquisas.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", pesquisas)

    def test_catalog_not_contradictory(self) -> None:
        dois = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(dois["status"], self.data["status"])
        self.assertTrue(
            dois["status"].startswith("hec_twin_mucum")
            or dois["status"].startswith("modelo_mucum_eventwise")
        )
        est_html = (OUT / "estrutura_stz_mucum.html").read_text(encoding="utf-8")
        self.assertIn("STZ Q bloqueado", est_html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Parar antes do HEC", idx)

    def test_e28_fallback_or_ibiraiaras(self) -> None:
        import sys
        import types

        path = Path(__file__).resolve().parent / "run_hec_twin_stz_mucum_calibrate.py"
        mod = types.ModuleType("hec_twin_mod")
        mod.__file__ = str(path)
        sys.modules[mod.__name__] = mod
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
        hours = mod.expected_hours(mod.parse_ts(mod.EVENTS["E28"][0]), mod.parse_ts(mod.EVENTS["E28"][1]))
        subbasins = list(mod.RAIN_PREF.keys())
        precip, meta = mod.build_precip_for_event("E28", hours, subbasins, magnitude_hours=hours)
        self.assertIsNotNone(precip)
        self.assertNotEqual(meta["subbasin_sources"]["SB_CARREIRO_7866"], "86507000")
        self.assertIn("2851072", mod.RAIN_STATIONS_LOAD)


if __name__ == "__main__":
    unittest.main()
