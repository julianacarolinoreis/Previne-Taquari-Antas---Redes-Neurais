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


if __name__ == "__main__":
    unittest.main()
