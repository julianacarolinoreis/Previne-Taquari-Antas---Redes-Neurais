#!/usr/bin/env python3
"""Tests for the ST→Muçum travel-time event audit."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_travel_time_event_audit as audit  # noqa: E402


class TravelTimeEventAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = audit.build_audit()

    def test_scores_three_paired_events_and_marks_missing_st(self):
        by_id = {item["event_id"]: item for item in self.payload["events"]}
        self.assertEqual(by_id["E19"]["status"], "st_series_missing")
        self.assertEqual(by_id["E22"]["status"], "st_series_missing")
        for event_id in ("E24", "E27", "E28"):
            self.assertEqual(by_id[event_id]["status"], "scored")
            self.assertIsInstance(by_id[event_id]["peak_to_peak_lag_h"], float)
        self.assertEqual(self.payload["summary"]["scored_events"], 3)

    def test_declared_16h_is_not_treated_as_validated_rule(self):
        self.assertEqual(self.payload["declared_model_lag"]["hours"], 16.0)
        self.assertEqual(self.payload["gate"]["status"], "research_partial")
        self.assertFalse(self.payload["gate"]["promotion_allowed"])
        median = self.payload["summary"]["peak_to_peak_lag_h"]["median"]
        self.assertIsNotNone(median)
        self.assertLess(abs(median), 12.0)
        self.assertNotAlmostEqual(median, 16.0, delta=1.0)

    def test_network_path_is_cited_without_converting_to_travel_time(self):
        network = self.payload["network_context"]
        self.assertEqual(network["status"], "available")
        self.assertAlmostEqual(network["path_length_km"], 23.652, places=2)


if __name__ == "__main__":
    unittest.main()
