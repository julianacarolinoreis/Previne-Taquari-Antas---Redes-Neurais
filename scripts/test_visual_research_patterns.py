"""Deterministic checks for the compact feeds used by the visual dashboard."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HORIZONS = [24, 48, 72, 120, 168]


def load(name: str) -> dict:
    return json.loads((ROOT / "assets" / "data" / name).read_text(encoding="utf-8"))


class VisualResearchPatternFeedTests(unittest.TestCase):
    def test_mucum_feed_contains_events_and_comparable_horizons(self) -> None:
        feed = load("research_visual_patterns_mucum_latest.json")
        self.assertEqual(feed["location"], "mucum")
        self.assertEqual(feed["threshold_cm"], 1800)
        self.assertEqual([row["hours"] for row in feed["horizons"]], HORIZONS)
        self.assertEqual(len(feed["events"]), 4)
        self.assertGreaterEqual(len(feed["models"]), 4)
        for row in feed["horizons"]:
            self.assertIn("probability_percent", row)
            self.assertIn("gefs_proxy_mm", row)
            self.assertIn("soil_moisture_m3m3", row)

    def test_santa_feed_keeps_model_disagreement_explicit(self) -> None:
        feed = load("research_visual_patterns_santa_tereza_latest.json")
        self.assertEqual(feed["location"], "santa_tereza")
        self.assertEqual([row["hours"] for row in feed["horizons"]], HORIZONS)
        self.assertEqual(feed["summary"]["model_card_event_count"], 5)
        self.assertEqual(len(feed["events"]), 4)
        for row in feed["horizons"]:
            self.assertIn("rna_score_percent", row)
            self.assertIn("probability_percent", row)
            self.assertIn("ifs_mean_mm", row)
        self.assertEqual(feed["horizons"][-1]["decision"], "VAI")


if __name__ == "__main__":
    unittest.main()
