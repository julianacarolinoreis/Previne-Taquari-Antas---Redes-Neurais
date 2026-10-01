#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/"scripts/build_g040_stage2_master.py"

spec=importlib.util.spec_from_file_location("g040_stage2_master",MOD)
m=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

class Stage2MasterTests(unittest.TestCase):
    def test_master_outputs_are_fail_closed(self):
        payload=m.build_master()
        self.assertFalse(payload["promotion_allowed"])
        self.assertIn(payload["status"]["overall"],{
            "FOUNDATION_INCOMPLETE",
            "FOUNDATION_READY_COMPUTE_BLOCKED",
            "BRANCH_MODEL_CALIBRATABLE_RESEARCH_ONLY",
        })
        self.assertIn("native_hec145",payload["gates"])
        self.assertIn("sma_branch_parameters",payload["gates"])
        self.assertIn("sma_145_transfer",payload["gates"])
        self.assertFalse(payload["gates"]["native_hec145"]["pass"])
        self.assertFalse(payload["gates"]["sma_branch_parameters"]["pass"])
        self.assertFalse(payload["gates"]["sma_145_transfer"]["pass"])
        self.assertTrue(payload["gates"]["dynamic_boundary_mass_balance"]["pass"])
        self.assertTrue(payload["gates"]["rain_support"]["pass"])
        self.assertTrue(payload["gates"]["observed_full_grid"]["pass"])
        self.assertTrue(payload["gates"]["ifs_full_grid"]["pass"])
        self.assertTrue(payload["gates"]["merged_rain"]["pass"])
        # Exact ECMWF cycle provenance is still intentionally unavailable,
        # so operational promotion must remain blocked despite research forcing readiness.
        self.assertFalse(payload["gates"]["merged_rain"]["detail"]["operational_promotion_allowed"])

    def test_benchmark_is_fixed_before_results(self):
        bench=json.loads((ROOT/"assets/data/g040_hydro_stack/benchmark_matrix_latest.json").read_text(encoding="utf-8"))
        ids=[x["event_id"] for x in bench["events"]]
        self.assertEqual(ids,[
            "E19_MAY2023","E22_SEP2023","E24_NOV2023",
            "E27_MAY2024","E28_JUN2024","E2026_JUL",
        ])
        split=bench["split_policy"]
        self.assertTrue(split["proposal_only"])
        self.assertTrue(split["no_event_may_move_from_validation_to_calibration_after_results_are_seen"])

    def test_ensemble_requires_same_target_location_and_horizon(self):
        p=ROOT/"assets/data/g040_hydro_stack/ensemble_member_inventory_latest.json"
        if p.exists():
            inv=json.loads(p.read_text(encoding="utf-8"))
            compat=inv["compatibility"]
            for group in compat.get("compatible_groups") or []:
                if group.get("ensemble_ready"):
                    self.assertGreaterEqual(group.get("member_count",0),2)
            # Current research members span STZ 2h, STZ 8h and Mucum 8h;
            # they must not become one ensemble merely because all predict stage.
            self.assertFalse(inv["weighting_gate"]["stage_ensemble_ready"])

    def test_tributary_policy_never_zero_fills(self):
        trib=json.loads((ROOT/"assets/data/g040_hydro_stack/tributary_inventory_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(trib["tributaries"]),3)
        self.assertIn("return contributing area to rainfall-runoff",trib["policy"]["missing"])
        self.assertIn("zero-fill",trib["policy"]["forbidden"])

if __name__=="__main__":
    unittest.main()
