#!/usr/bin/env python3
"""Tests for the Taquari–Antas basin understanding package."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_bacia_taquari_antas_understanding.py"
OUT = ROOT / "assets" / "data" / "bacia_taquari_antas"


class BasinUnderstandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run([sys.executable, str(SCRIPT)], check=True, cwd=ROOT)

    def test_artifacts_exist(self) -> None:
        self.assertTrue((OUT / "bacia_understanding_latest.json").exists())
        self.assertTrue((OUT / "index.html").exists())
        self.assertTrue((OUT / "major_tributary_joins.geojson").exists())
        self.assertTrue((OUT / "README.md").exists())

    def test_nested_controls_and_carreiro_dominance(self) -> None:
        report = json.loads((OUT / "bacia_understanding_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], "bacia_taquari_antas_understanding_v1")
        self.assertGreaterEqual(report["counts"]["tributaries_ge_100km2"], 20)
        incr = report["controls"]["incremental_km2"]["antas_to_stz"]
        self.assertGreater(incr, 2500)
        dominated = report["hec_structure_gap"]["current_hec_skeleton"]["buckets"][1][
            "dominated_by"
        ]
        self.assertIsNotNone(dominated)
        self.assertGreater(dominated["fraction_of_increment"], 0.85)
        self.assertIn("Carreiro", dominated["label"])

    def test_html_states_basin_is_not_one_bucket(self) -> None:
        html = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("não é um balde", html.lower())
        self.assertIn("Carreiro", html)
        self.assertIn("86472000", html)
        self.assertIn("86472600", html)
        self.assertIn("86510000", html)

    def test_joins_geojson_points(self) -> None:
        gj = json.loads((OUT / "major_tributary_joins.geojson").read_text(encoding="utf-8"))
        self.assertEqual(gj["type"], "FeatureCollection")
        self.assertGreaterEqual(len(gj["features"]), 20)
        self.assertTrue(all(f["geometry"]["type"] == "Point" for f in gj["features"]))


if __name__ == "__main__":
    unittest.main()
