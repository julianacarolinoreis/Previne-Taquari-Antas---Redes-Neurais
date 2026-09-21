#!/usr/bin/env python3
"""Contract tests for the station-reconciliation matrix."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "station_reconciliation_latest.json"


class StationReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(PATH.read_text(encoding="utf-8"))

    def test_research_boundary_and_station_order(self) -> None:
        self.assertEqual(self.data["schema_version"], "previne_station_reconciliation_v1")
        self.assertTrue(self.data["research_only"])
        self.assertFalse(self.data["official_alert"])
        self.assertEqual(self.data["network"]["station_order"], ["86472000", "86472600", "86510000"])
        self.assertIn("não três zonas", self.data["network"]["representation"])

    def test_event_coverage_is_explicit_and_not_filled(self) -> None:
        self.assertEqual(self.data["summary"]["event_count"], 6)
        self.assertEqual(self.data["summary"]["target_rain_and_flow_complete_events"], ["E19", "E26", "E28"])
        self.assertEqual(self.data["summary"]["three_incremental_areas_complete_events"], ["E28"])
        self.assertEqual(self.data["summary"]["santa_tereza_rain_available_events"], ["E24", "E27", "E28"])
        self.assertEqual(self.data["calibration_gate"]["current_status"], "blocked_common_calibration_single_complete_event")
        self.assertTrue(all(row["policy"] == "missing_data_not_filled_or_interpolated" for row in self.data["events"]))

    def test_station_provenance_is_present(self) -> None:
        for key in ("calibration_input_gate", "santa_tereza_event_audit", "santa_tereza_dss_report"):
            self.assertTrue(self.data["provenance"][key])
            self.assertEqual(len(self.data["provenance"][f"{key}_sha256"]), 64)
        e19 = next(row for row in self.data["events"] if row["event_id"] == "E19")
        self.assertFalse(e19["stations"]["86472600"]["rain"]["rain_available"])
        self.assertTrue(any("Santa Tereza" in blocker for blocker in e19["blockers"]))
        e28 = next(row for row in self.data["events"] if row["event_id"] == "E28")
        self.assertTrue(e28["three_incremental_areas_complete"])


if __name__ == "__main__":
    unittest.main()
