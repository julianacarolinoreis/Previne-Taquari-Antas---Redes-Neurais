#!/usr/bin/env python3
import json
import py_compile
import unittest
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config/g040_causal_frozen_benchmark_v1.json"

class TestCausalFrozenBenchmark(unittest.TestCase):
    def test_new_scripts_compile(self):
        for rel in (
            "scripts/build_g040_antecedent_wetness.py",
            "scripts/build_g040_ecmwf_single_run_forcing.py",
            "scripts/build_g040_causal_case.py",
            "scripts/evaluate_g040_causal_benchmark.py",
            "scripts/run_hec_hms_g040_e1_hindcast.py",
            "scripts/build_g040_target_event_parameter_library.py",
            "scripts/select_g040_adaptive_scenario.py",
        ):
            py_compile.compile(str(ROOT/rel),doraise=True)

    def test_frozen_split_and_decision_lag(self):
        j=json.loads(CFG.read_text(encoding="utf-8"))
        self.assertTrue(j["frozen_before_execution"])
        self.assertFalse(j["parameter_policy"]["validation_or_holdout_may_change_parameters"])
        self.assertFalse(j["parameter_policy"]["codex_posthoc_member_allowed"])
        self.assertEqual(j["forecast_horizon_hours"],72)
        for c in j["cases"]:
            run=datetime.fromisoformat(c["ecmwf_run_utc"].replace("Z","+00:00"))
            t0=datetime.fromisoformat(c["decision_time_utc"].replace("Z","+00:00"))
            self.assertEqual((t0-run).total_seconds()/3600,6)
            self.assertIn(c["split"],{"independent_validation","pseudo_operational_holdout"})
        self.assertEqual({c["event_id"] for c in j["cases"]},{"E27_MAY2024","E28_JUN2024","E2026_JUL"})

    def test_selector_uses_true_pre_event_wetness(self):
        src=(ROOT/"scripts/select_g040_adaptive_scenario.py").read_text(encoding="utf-8")
        self.assertIn('(hist.get("antecedent") or {}).get("rain_72h_mm")',src)
        self.assertNotIn('wet_hist=hr.get("first_24h_mm")',src)
        lib=(ROOT/"scripts/build_g040_target_event_parameter_library.py").read_text(encoding="utf-8")
        self.assertIn('ANTECEDENT=BASE/"historical_antecedent_wetness"',lib)
        self.assertIn('"strictly_pre_event":bool(ant_path.exists())',lib)

    def test_runner_separates_forcing_from_verification(self):
        src=(ROOT/"scripts/run_hec_hms_g040_e1_hindcast.py").read_text(encoding="utf-8")
        self.assertIn("--score-hydro-file",src)
        self.assertIn("--score-start-utc",src)
        self.assertIn("score_hydro=loadj(args.score_hydro_file)",src)
        self.assertIn("CAUSAL_FORECAST_RAIN_READY",src)

    def test_exact_ecmwf_is_single_run_not_live_stitched_endpoint(self):
        src=(ROOT/"scripts/build_g040_ecmwf_single_run_forcing.py").read_text(encoding="utf-8")
        self.assertIn("single-runs-api.open-meteo.com/v1/forecast",src)
        self.assertIn('"run":run_utc.strftime',src)
        self.assertIn("GRID_CELL_COUNT",src)

if __name__=="__main__":
    unittest.main()
