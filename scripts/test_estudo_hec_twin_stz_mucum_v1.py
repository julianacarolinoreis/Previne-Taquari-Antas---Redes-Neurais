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
        self.assertEqual(self.data["status"], "hec_twin_mucum_v1_3_eventwise_scored_stz_q_blocked")
        self.assertTrue(self.data["engine"]["not_hec_hms_binary"])
        self.assertIn("research_score", self.data["engine"]["optimization_objective"])
        self.assertIn("Muçum", self.data["purpose"])
        muc = self.data["models"]["mucum"]
        self.assertEqual(muc.get("calibration_version"), "mucum_hec_twin_v1_3")
        self.assertIn("pad_selection", muc)
        self.assertEqual(muc.get("pad_hours"), muc["pad_selection"]["selected_pad_hours"])
        cs = muc["common_search"]
        self.assertIn("holdout_e27", cs)
        self.assertIn("leave_one_out", cs)
        self.assertTrue(cs.get("promotion_blocked"))
        self.assertLess(float(cs["holdout_e27"]["test_nse"]), 0.5)
        self.assertTrue(any(g["id"] == "e19_local_rain_underforced" for g in muc["gaps_remaining"]))

    def test_mucum_eventwise_and_common(self) -> None:
        muc = self.data["models"]["mucum"]
        by_id = {e["event_id"]: e for e in muc["events"]}
        self.assertEqual(by_id["E19"]["status"], "fit_failed_eventwise")
        self.assertIn("forcing_note", by_id["E19"])
        self.assertEqual(by_id["E22"]["status"], "eventwise_scored")
        # v1.3 selects PAD for headline E22–E28 (typically PAD=0 → E22 ~0.73)
        self.assertGreaterEqual(by_id["E22"]["metrics"]["nse"], 0.65)
        self.assertGreaterEqual(by_id["E28"]["metrics"]["nse"], 0.90)
        e28_rain = by_id["E28"]["rain"]
        # Preferred dry 86507000 must be rejected; wet backup may be 86472000 or 86510000
        self.assertNotEqual(e28_rain["subbasin_sources"]["SB_CARREIRO_7866"], "86507000")
        self.assertIn(e28_rain["subbasin_sources"]["SB_CARREIRO_7866"], {"86472000", "86510000"})
        self.assertTrue(e28_rain["fallback_notes"])
        self.assertGreater(muc["mean_nse_eventwise"], 0.75)
        self.assertIn("common_search", muc)
        self.assertIsNotNone(muc["common_search"]["mean_nse"])

    def test_e28_series_recomputes_nse(self) -> None:
        with (RUN / "mucum_E28_best_series.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertIn("in_core_window", rows[0])
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
        self.assertIn("O que ainda falta", self.html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", idx)
        pesquisas = (Path(__file__).resolve().parents[1] / "pesquisas.html").read_text(encoding="utf-8")
        self.assertIn("hec_twin_stz_mucum_v1.html", pesquisas)

    def test_catalog_not_contradictory(self) -> None:
        dois = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertNotIn("Ainda nao calibrar HEC", dois["discipline_rule"])
        self.assertEqual(dois["status"], self.data["status"])
        self.assertTrue(dois["status"].startswith("hec_twin_mucum"))
        est_html = (OUT / "estrutura_stz_mucum.html").read_text(encoding="utf-8")
        self.assertNotIn("ainda sem calibração", est_html.lower())
        self.assertIn("STZ Q bloqueado", est_html)
        idx = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Parar antes do HEC", idx)
        self.assertNotIn("Ainda sem HEC.", idx)
        forc = json.loads((OUT / "forcantes_stz_mucum_latest.json").read_text(encoding="utf-8"))
        self.assertFalse(any("So depois: calibracao" in s for s in forc["next_steps"]))
        self.assertIn("hec_twin_artifact", forc)

    def test_e28_fallback_changes_simulation(self) -> None:
        """Fallback must materially change Q vs dry preferred Carreiro gage."""
        import sys
        import types

        path = Path(__file__).resolve().parent / "run_hec_twin_stz_mucum_calibrate.py"
        mod = types.ModuleType("hec_twin_mod")
        mod.__file__ = str(path)
        sys.modules[mod.__name__] = mod
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
        areas = {
            e["id"]: float(e["area_km2"])
            for e in self.estrutura["models"]["mucum"]["elements"]
            if e["type"] == "subbasin"
        }
        hours = mod.expected_hours(mod.parse_ts(mod.EVENTS["E28"][0]), mod.parse_ts(mod.EVENTS["E28"][1]))
        subbasins = [
            "SB_PRATA_7868",
            "SB_ANTAS_RESIDUAL",
            "SB_CARREIRO_7866",
            "SB_STZ_RESIDUAL",
            "SB_INC_MUCUM",
        ]
        precip, meta = mod.build_precip_for_event(
            "E28", hours, subbasins, magnitude_hours=hours
        )
        self.assertIsNotNone(precip)
        self.assertNotEqual(meta["subbasin_sources"]["SB_CARREIRO_7866"], "86507000")
        self.assertIn(meta["subbasin_sources"]["SB_CARREIRO_7866"], {"86472000", "86510000"})
        self.assertTrue(meta["fallback_notes"])
        rain_by = {}
        for st in ("86472000", "86472600", "86507000", "86510000"):
            rows = mod.load_event_series(st, "E28")
            rain_by[st] = mod.hourly_field(rows, "Chuva", reduce="sum")
        dry = [float(rain_by["86507000"][h]) for h in hours]
        wet = precip["SB_CARREIRO_7866"]
        self.assertGreater(sum(wet), 5 * sum(dry))
        e28 = next(e for e in self.data["models"]["mucum"]["events"] if e["event_id"] == "E28")
        p = mod.Params(**{k: e28["params"][k] for k in mod.Params.__dataclass_fields__})
        sim_wet = mod.run_network(precip, areas, p, include_mucum_increment=True)["at_mucum"]
        precip_dry = dict(precip)
        precip_dry["SB_CARREIRO_7866"] = dry
        sim_dry = mod.run_network(precip_dry, areas, p, include_mucum_increment=True)["at_mucum"]
        max_delta = max(abs(a - b) for a, b in zip(sim_wet, sim_dry))
        self.assertGreater(max_delta, 100.0)


if __name__ == "__main__":
    unittest.main()
