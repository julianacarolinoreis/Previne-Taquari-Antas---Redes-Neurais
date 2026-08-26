import json
import tempfile
import unittest
from pathlib import Path

import build_binary_research_decision as binary


class BinaryResearchDecisionTests(unittest.TestCase):
    def test_threshold_is_explicit_and_inclusive(self):
        feed = {"horizons": [{"hours": 24, "flood_probability": 0.50}, {"hours": 48, "flood_probability": 0.4999}, {"hours": 72, "flood_probability": None}]}
        decisions = binary.current_decisions(feed)
        self.assertEqual([row["decision"] for row in decisions], ["VAI", "NAO_VAI", None])

    def test_probability_field_is_already_a_fraction(self):
        decisions = binary.current_decisions({"horizons": [{"hours": 168, "probability": 0.621227}]})
        self.assertAlmostEqual(decisions[0]["probability_percent"], 62.1227)
        self.assertEqual(decisions[0]["decision"], "VAI")

    def test_event_sensitivity_is_reported_without_inventing_accuracy(self):
        feed = {"validation": {"event_detection_summary": {"24h": {"held_out_events": 3, "detected_at_score_0_5": 1}, "72h": {"held_out_events": 3, "detected_at_score_0_5": 0}}}}
        result = binary.evaluation(feed, "mucum")
        self.assertAlmostEqual(result["by_horizon"][0]["sensitivity_percent"], 100 / 3)
        self.assertEqual(result["model_verdict"], "NAO_FUNCIONA_DE_FORMA_CONFIAVEL")
        self.assertIn("indisponíveis", result["false_positive_metrics"])

    def test_build_records_source_age_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "probability.json"
            output = Path(directory) / "binary.json"
            source.write_text(json.dumps({"generated_at_utc": "2026-08-25T00:00:00Z", "horizons": [{"hours": 24, "flood_probability": 0.1}], "forecast_source": "test", "calibration_status": "experimental_uncalibrated"}), encoding="utf-8")
            payload = binary.build("test", source, output)
            self.assertTrue(payload["research_only"])
            self.assertFalse(payload["official_alert"])
            self.assertIn("source_age_hours_at_generation", payload["source"])


if __name__ == "__main__":
    unittest.main()
