#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestG040MultieventCalibrationContract(unittest.TestCase):
    def test_fixed_split_is_frozen(self):
        cfg = json.loads(
            (ROOT / "config/g040_stage2_execution_v1.json").read_text(encoding="utf-8")
        )
        split = cfg["fixed_benchmark_split"]
        self.assertEqual(split["calibration"], ["E22_SEP2023", "E24_NOV2023"])
        self.assertEqual(
            split["independent_validation"], ["E27_MAY2024", "E28_JUN2024"]
        )
        self.assertEqual(split["pseudo_operational_holdout"], ["E2026_JUL"])
        self.assertIn("Do not move validation/holdout", cfg["no_leakage_rule"])

    def test_historical_forcing_never_zero_fills(self):
        src = (
            ROOT / "scripts/build_g040_historical_calibration_forcing.py"
        ).read_text(encoding="utf-8")
        self.assertIn("missing remains missing; never zero-filled", src)
        self.assertIn("E22_SEP2023", src)
        self.assertIn("E24_NOV2023", src)

    def test_calibrator_uses_only_calibration_events_for_selection(self):
        src = (
            ROOT / "scripts/calibrate_hec_hms_g040_e1_multievent.py"
        ).read_text(encoding="utf-8")
        self.assertIn('CAL_EVENTS = ("E22_SEP2023", "E24_NOV2023")', src)
        self.assertIn('VALIDATION_EVENTS = ("E27_MAY2024", "E28_JUN2024")', src)
        self.assertIn("no_leakage", src)
        self.assertIn("parameter_freeze_rule", src)

    def test_runner_accepts_event_specific_inputs(self):
        src = (
            ROOT / "scripts/run_hec_hms_g040_e1_hindcast.py"
        ).read_text(encoding="utf-8")
        for token in (
            "--event-id",
            "--rain-file",
            "--hydro-file",
            "--scenario-file",
            "--output-root",
        ):
            self.assertIn(token, src)


if __name__ == "__main__":
    unittest.main()
