import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_basin_research_feed as builder  # noqa: E402


class BasinResearchFeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feed = builder.build_feed(datetime(2026, 8, 29, 23, 0, tzinfo=timezone.utc))

    def test_public_scope_is_research_only(self):
        self.assertTrue(self.feed["research_only"])
        self.assertFalse(self.feed["official_alert"])
        self.assertEqual(set(self.feed["stations"]), {"santa_tereza", "mucum"})

    def test_all_long_horizons_are_normalized(self):
        for station in self.feed["stations"].values():
            self.assertEqual([row["hours"] for row in station["horizons"]], [24, 48, 72, 120, 168])
            for row in station["horizons"]:
                self.assertIn("rain", row)
                self.assertIn("risk", row)
                self.assertIn("coverage_expected_hours", row)

    def test_mucum_headwater_is_not_claimed_as_independent(self):
        santa = self.feed["stations"]["santa_tereza"]["horizons"][2]["rain"]["headwater"]
        mucum = self.feed["stations"]["mucum"]["horizons"][2]["rain"]["headwater"]
        self.assertTrue(santa["independent_for_station"])
        self.assertFalse(mucum["independent_for_station"])
        self.assertEqual(mucum["status"], "shared_santa_reference")

    def test_mucum_point_survives_unavailable_direct_grib_audit(self):
        weather = builder.load(ROOT / builder.STATIONS["mucum"]["weather"], {})
        source = next(row for row in weather["horizons"] if int(row["hours"]) == 24)
        normalized = self.feed["stations"]["mucum"]["horizons"][0]["rain"]
        if source.get("rain_ecmwf_direct_mm") is None:
            self.assertEqual(normalized["point_mm"], builder.number(source.get("rain_point_mm")))

    def test_geometry_is_boundary_reference_not_flow_mask(self):
        geometry = self.feed["basin"]
        self.assertEqual(geometry["boundary"]["status"], "boundary_reference_only")
        self.assertFalse(geometry["mdt"]["flow_accumulation_available"])
        self.assertEqual(geometry["hydrologic_delineation"]["status"], "not_validated")
        self.assertGreaterEqual(len(geometry["upstream_gauges"]["stations"]), 2)

    def test_current_level_prefers_the_newer_live_robot(self):
        for key in ("santa_tereza", "mucum"):
            raw = builder.load(ROOT / builder.STATIONS[key]["live"], {})
            expected = builder.number(raw.get("telemetria_ultima_nivel_cm", raw.get("nivel_rio_agora_cm")))
            current = self.feed["stations"][key]["current"]
            self.assertEqual(current["level_cm"], expected)
            self.assertIn(current["state"], {"fresh", "stale"})

    def test_gates_are_explicit(self):
        gate_ids = {gate["id"] for gate in self.feed["gates"]}
        self.assertTrue({"hydrologic_mask", "soil_observation", "probability_calibration"} <= gate_ids)
        self.assertTrue(all(gate.get("reason") for gate in self.feed["gates"]))

    def test_official_source_registry_is_research_only_and_actionable(self):
        registry = self.feed["source_registry"]
        self.assertEqual(registry["scope"], "research_only")
        self.assertGreaterEqual(len(registry["sources"]), 3)
        self.assertEqual(registry["artifact"]["path"], "assets/data/research_source_registry.json")
        source_ids = {item["id"] for item in registry["sources"]}
        self.assertTrue({"ana_bho_2017_50k", "inpe_topodata_dem", "cemaden_radar_santa_tereza", "ana_hidrowebservice"} <= source_ids)
        for item in registry["sources"]:
            self.assertIn(item["status"], {"identified", "conditional", "integrated"})
            self.assertTrue(item["url"].startswith("https://"))
            self.assertTrue(item["role"])
            self.assertTrue(item["next_step"])


if __name__ == "__main__":
    unittest.main()
