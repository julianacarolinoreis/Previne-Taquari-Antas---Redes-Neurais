#!/usr/bin/env python3
"""Contract tests for the consolidated research-catalogue status manifest."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "assets" / "data" / "research_catalog_status_latest.json"


def embedded_json(text: str, script_id: str) -> dict:
    match = re.search(
        rf'<script\s+id="{re.escape(script_id)}"\s+type="application/json">(.*?)</script>',
        text,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"script {script_id} ausente")
    return json.loads(match.group(1))


class CatalogStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.catalogue_html = (ROOT / "pesquisas.html").read_text(encoding="utf-8")

    def test_schema_and_research_boundary(self) -> None:
        self.assertEqual(self.data["schema_version"], "previne_research_catalog_status_v1")
        self.assertTrue(self.data["research_only"])
        self.assertFalse(self.data["official_alert"])
        self.assertIn("não é alerta", self.data["purpose"])

    def test_model_counts_match_both_embedded_city_feeds(self) -> None:
        source = (ROOT / "index.html").read_text(encoding="utf-8")
        santa = embedded_json(source, "data")
        mucum = embedded_json(source, "data-mucum")
        by_city = self.data["models"]["by_city"]
        self.assertEqual(by_city["santa_tereza"]["qualified_models"], len(santa["models"]))
        self.assertEqual(by_city["mucum"]["qualified_models"], len(mucum["models"]))
        self.assertEqual(self.data["models"]["qualified_total"], len(santa["models"]) + len(mucum["models"]))
        self.assertEqual(self.data["models"]["types"]["alt"], 237)
        self.assertEqual(self.data["models"]["types"]["conv"], 67)
        self.assertEqual(set(self.data["models"]["horizons"]), {"2h", "4h", "8h", "12h"})

    def test_round_and_catalogue_counts_have_their_own_grain(self) -> None:
        rounds = self.data["rounds"]
        self.assertEqual(rounds["round_folders"], 31)
        self.assertEqual(rounds["distinct_days"], 18)
        self.assertEqual(rounds["by_city"]["mucum"]["round_folders"], 10)
        self.assertEqual(rounds["by_city"]["santa_tereza"]["round_folders"], 21)

        catalogue = self.data["catalogue"]
        self.assertEqual(catalogue["catalogue_entries"], 58)
        self.assertGreaterEqual(catalogue["html_pages_in_worktree"], catalogue["catalogue_entries"])

    def test_spatial_and_response_are_not_operational(self) -> None:
        spatial = self.data["spatial"]["by_city"]
        self.assertEqual(spatial["mucum"]["published_level_range_m"], [0.0, 25.0])
        self.assertEqual(spatial["santa_tereza"]["published_level_range_m"], [0.0, 15.0])
        self.assertIn("pending", spatial["mucum"]["stage_conversion_status"])
        self.assertIn("pending", spatial["santa_tereza"]["stage_conversion_status"])
        self.assertEqual(self.data["events"]["operational_gate"]["status"], "blocked")
        self.assertEqual(self.data["response"]["by_city"]["santa_tereza"]["operational_gate"], "blocked")

    def test_hec_hms_is_scored_but_not_promoted(self) -> None:
        hec = self.data["hec_hms"]
        self.assertEqual(hec["scored_event_count"], 5)
        self.assertEqual(hec["complete_three_incremental_area_events"], [28])
        self.assertIn("bloqueado", hec["operational_promotion_gate"])
        self.assertIn("BHO6", hec["scope"])

    def test_quality_manifest_preserves_degraded_issues_and_sources(self) -> None:
        quality = self.data["data_quality"]
        self.assertEqual(quality["status"], "DEGRADED")
        self.assertEqual(
            {item["code"] for item in quality["issues"]},
            {"weather_feed_stale", "score_uncalibrated", "probability_proxy_source"},
        )
        self.assertEqual(len(quality["basin_gates"]), 6)
        for source in self.data["sources"]:
            self.assertTrue((ROOT / source).exists(), source)

    def test_catalogue_is_wired_to_manifest_and_keeps_spatial_caveat(self) -> None:
        html = self.catalogue_html
        self.assertIn('assets/data/research_catalog_status_latest.json', html)
        for element_id in (
            "archiveStatusPill",
            "archiveStatusGrid",
            "archiveSpatialSummary",
            "archiveNextGate",
            "archiveStatusDetails",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("Contornos publicados: 15 m em Santa Tereza e 18/20/25 m em Muçum", html)
        self.assertIn("A conversão cota–MDT ainda está pendente", html)
        self.assertNotIn("Cota oficial: 15 m em ST, 18 m em Muçum", html)


if __name__ == "__main__":
    unittest.main()
