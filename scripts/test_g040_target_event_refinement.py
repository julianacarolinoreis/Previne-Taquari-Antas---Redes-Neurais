#!/usr/bin/env python3
import json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class TestTargetEventRefinement(unittest.TestCase):
    def test_request_is_multi_target_multi_event(self):
        j=json.loads((ROOT/"config/g040_target_event_refinement_request_v1.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(j["events"]),2)
        self.assertGreaterEqual(len(j["targets"]),4)
        self.assertTrue(j["search"]["target_specific_selection"])
        self.assertEqual(j["search"]["hec_compute_interval_min"],3)
    def test_script_is_target_specific_and_no_promotion(self):
        s=(ROOT/"scripts/refine_g040_target_event_library.py").read_text(encoding="utf-8")
        self.assertIn("same_run_many_targets",s)
        self.assertIn("target-specific",s)
        self.assertIn('"promotion_allowed":False',s)
        self.assertIn("pseudo_operational_validation_required",s)

if __name__=="__main__":unittest.main()
