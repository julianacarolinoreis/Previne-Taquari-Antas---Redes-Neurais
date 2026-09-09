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

    def test_mucum_headwater_is_independent_proxy_not_hydrologic_mask(self):
        santa = self.feed["stations"]["santa_tereza"]["horizons"][2]["rain"]["headwater"]
        mucum = self.feed["stations"]["mucum"]["horizons"][2]["rain"]["headwater"]
        self.assertTrue(santa["independent_for_station"])
        self.assertTrue(mucum["independent_for_station"])
        self.assertNotEqual(mucum["status"], "shared_santa_reference")
        self.assertFalse(mucum["hydrologic_mask"])
        self.assertFalse(mucum["area_weighted"])
        gate = next(item for item in self.feed["gates"] if item["id"] == "mucum_independent_headwater")
        self.assertEqual(gate["status"], "research_partial")
        self.assertNotIn("shared_headwater_reference", self.feed["stations"]["mucum"]["quality"]["flags"])
        self.assertIn("mucum_independent_upstream_proxy_not_area_weighted", self.feed["stations"]["mucum"]["quality"]["flags"])

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
        mucum_poly = geometry["hydrologic_delineation"]["headwater_polygons"]["mucum_srtm"]
        self.assertEqual(mucum_poly["status"], "research_polygon_available")
        self.assertFalse(mucum_poly["area_weighted_rainfall"])
        self.assertGreaterEqual(len(geometry["upstream_gauges"]["stations"]), 2)

    def test_current_level_prefers_the_newer_live_robot(self):
        for key in ("santa_tereza", "mucum"):
            raw = builder.load(ROOT / builder.STATIONS[key]["live"], {})
            weather = builder.load(ROOT / builder.STATIONS[key]["weather"], {})
            # Mirror the production selector: a live export can be missing or
            # carry null level fields, in which case the newest weather
            # observation is the valid fallback used by the joined feed.
            expected = builder.live_current(raw, weather, datetime(2026, 8, 29, 23, tzinfo=timezone.utc))["level_cm"]
            current = self.feed["stations"][key]["current"]
            self.assertEqual(current["level_cm"], expected)
            self.assertIn(current["state"], {"fresh", "stale"})

    def test_live_horizon_audit_keeps_principal_and_comparative_candidates(self):
        mucum = builder.live_horizon_audit(builder.load(ROOT / "previsao_ao_vivo_mucum.json", {}))
        by_key = {row["key"]: row for row in mucum}
        self.assertIn("4h", by_key)
        self.assertIn("4h_versao_b", by_key)
        self.assertEqual(by_key["4h"]["role"], "principal")
        self.assertEqual(by_key["4h_versao_b"]["role"], "comparativo")
        self.assertTrue(by_key["4h"]["available"])
        self.assertTrue(by_key["4h_versao_b"]["available"])

        santa = builder.live_horizon_audit(builder.load(ROOT / "previsao_ao_vivo.json", {}))
        santa_by_key = {row["key"]: row for row in santa}
        self.assertTrue(santa_by_key["4h"]["available"])
        self.assertGreaterEqual(santa_by_key["4h"]["inputs_exact"] or 0, 1)
        self.assertIn(santa_by_key["8h"]["quality_status"], {"NORMAL", "ATENCAO", None})
        self.assertIn("available", santa_by_key["8h"])

    def test_travel_time_audit_is_embedded_without_promotion(self):
        propagation = self.feed["basin"]["propagation"]
        self.assertEqual(propagation["status"], "research_event_lags_published")
        self.assertFalse(propagation["promotion_allowed"])
        self.assertGreaterEqual(propagation["scored_events"], 3)
        self.assertIsInstance(propagation["peak_to_peak_lag_h"]["median"], float)
        gate = next(item for item in self.feed["gates"] if item["id"] == "travel_time")
        self.assertEqual(gate["status"], "research_partial")
        self.assertIn("peak-to-peak", gate["reason"])
        self.assertIn("16 h", gate["reason"])
        self.assertIn("event peak-to-peak lags", self.feed["signals"]["propagation"])

    def test_official_source_registry_is_research_only_and_actionable(self):
        registry = self.feed["source_registry"]
        self.assertEqual(registry["scope"], "research_only")
        self.assertGreaterEqual(len(registry["sources"]), 3)
        self.assertEqual(registry["artifact"]["path"], "assets/data/research_source_registry.json")
        source_ids = {item["id"] for item in registry["sources"]}
        self.assertTrue({"ana_bho_2017_50k", "inpe_topodata_dem", "cemaden_radar_santa_tereza", "ana_hidrowebservice"} <= source_ids)
        for item in registry["sources"]:
            self.assertIn(item["status"], {"identified", "conditional", "integrated", "partially_integrated_via_local_event_xml"})
            self.assertTrue(item["url"].startswith("https://"))
            self.assertTrue(item["role"])
            self.assertTrue(item["next_step"])

    def test_published_feed_embeds_the_current_registry_hash(self):
        published = builder.load(builder.OUTPUT, {})
        self.assertEqual(
            published.get("source_registry", {}).get("artifact", {}).get("sha256"),
            builder.sha256(builder.SOURCE_REGISTRY),
        )

    def test_text_hash_is_line_ending_invariant_but_binary_hash_is_not_normalized(self):
        import hashlib
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lf = root / "sample.json"
            crlf = root / "sample-crlf.json"
            lf.write_bytes(b'{"a": 1}\n')
            crlf.write_bytes(b'{"a": 1}\r\n')
            self.assertEqual(builder.sha256(lf), builder.sha256(crlf))

            binary = root / "sample.tif"
            binary.write_bytes(b"a\r\nb")
            self.assertEqual(builder.sha256(binary), hashlib.sha256(b"a\r\nb").hexdigest())


if __name__ == "__main__":
    unittest.main()
