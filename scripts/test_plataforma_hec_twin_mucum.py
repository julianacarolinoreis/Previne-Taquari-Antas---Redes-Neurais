#!/usr/bin/env python3
"""Smoke tests for the HEC/REC platform feed (anchors + automation)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = (
    ROOT
    / "assets"
    / "data"
    / "estudo_bacia_taquari_antas"
    / "plataforma_hec_twin_mucum_latest.json"
)


class PlataformaHecTwinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.feed = json.loads(FEED.read_text(encoding="utf-8"))

    def test_has_many_anchors(self) -> None:
        anchors = self.feed["spatial"]["anchors"]
        self.assertGreaterEqual(len(anchors), 12)
        roles = {a["role"] for a in anchors}
        self.assertIn("target", roles)
        self.assertIn("level_control", roles)
        self.assertIn("rain", roles)
        self.assertIn("upstream_monitor", roles)
        mucum = [a for a in anchors if a["code"] == "86510000"]
        self.assertEqual(len(mucum), 1)
        self.assertEqual(mucum[0]["role"], "target")

    def test_automation_robot_declared(self) -> None:
        auto = self.feed["automation"]
        self.assertIn("hec-twin-mucum-forward.yml", auto["workflow"])
        self.assertTrue(auto["does_not_touch_rna"])
        self.assertTrue(auto["research_not_alert"])
        self.assertGreaterEqual(len(auto["steps_pt"]), 3)

    def test_event_trace_and_freshness(self) -> None:
        trace = self.feed["event_trace"]
        self.assertGreaterEqual(trace["n_points"], 10)
        self.assertTrue(trace["series"])
        self.assertEqual(trace["series"][0].keys(), set(trace["series"][0].keys()) | {"t", "n_cm"})
        self.assertIn("t", trace["series"][0])
        self.assertIn("n_cm", trace["series"][0])
        fresh = self.feed["freshness"]
        self.assertIn("stale_forward", fresh)
        self.assertIn("preferred_source", fresh)
        self.assertIn("live_eval", self.feed["products"])
        self.assertIn("forward_5d", self.feed["products"])
        self.assertGreaterEqual(self.feed["spatial"]["anchor_count"], 12)
        self.assertIn("ug_rain_mm", self.feed["spatial"])


if __name__ == "__main__":
    unittest.main()
