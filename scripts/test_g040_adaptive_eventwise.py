#!/usr/bin/env python3
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"

class TestAdaptiveEventwise(unittest.TestCase):
    def test_contract_forbids_single_parameter_collapse(self):
        j=json.loads((ROOT/"config/g040_adaptive_eventwise_selection_v1.json").read_text(encoding="utf-8"))
        self.assertIn("Do not replace",j["no_single_parameter_rule"])
        self.assertFalse(j["selector"]["hard_pick"])
        self.assertEqual(j["selector"]["top_k"],3)

    def test_builder_generates_target_event_rows(self):
        subprocess.run([sys.executable,"-B",str(ROOT/"scripts/build_g040_target_event_parameter_library.py")],check=True,cwd=ROOT)
        j=json.loads((BASE/"g040_target_event_parameter_library_latest.json").read_text(encoding="utf-8"))
        rows=j["hec_target_event_candidates"]
        self.assertTrue(any(x["target_code"]=="86510000" and x["event_id"]=="E22_SEP2023" for x in rows))
        self.assertTrue(any(x["target_code"]=="86720000" and x["event_id"]=="E24_NOV2023" for x in rows))
        self.assertGreaterEqual(len(j["existing_mucum_eventwise_library"]),9)
        if (BASE/"g040_target_event_refinement_latest.json").exists():
            self.assertGreater(j["coverage"]["refined_target_event_rows_used"],0)
            self.assertTrue(any(x.get("selection_source")=="target_event_refinement" for x in rows))

    def test_selector_keeps_fallback_and_never_hard_picks(self):
        subprocess.run([sys.executable,"-B",str(ROOT/"scripts/select_g040_adaptive_scenario.py")],check=True,cwd=ROOT)
        j=json.loads((BASE/"g040_adaptive_scenario_latest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(j["targets"]),8)
        for t in j["targets"]:
            self.assertFalse(t["hard_parameter_pick"])
            self.assertIn("fallback",t)
            self.assertIn("confidence_before_data_quality_cap",t)
        rain=j["live_fingerprint"]["rain"]
        self.assertIn("freshness",rain)
        self.assertIn("forcing_age_hours",rain["freshness"])
        self.assertIn("latest_observed_rain_utc",rain["freshness"])
        self.assertTrue(
            rain["forecast_24h_basin_mm"] is None or rain["forecast_24h_basin_mm"] >= 0
        )
        self.assertTrue(j["governance"]["pseudo_operational_validation_required"])

if __name__=="__main__":
    unittest.main()
