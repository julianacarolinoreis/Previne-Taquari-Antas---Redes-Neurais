#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestG040FullBasinContract(unittest.TestCase):
    def test_contract_is_full_basin_not_single_endpoint(self):
        p = ROOT / "config/g040_full_basin_operational_contract_v1.json"
        j = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(
            j["hydrology"]["domain"],
            "entire G040 from all headwaters and tributaries to the official basin outlet",
        )
        self.assertIn("station_role", j["hydrology"])
        self.assertEqual(j["spatial_domain"]["hydrologic_mask"], "strict_g040_union")
        self.assertGreater(j["spatial_domain"]["acquisition_buffer_km_default"], 0)

    def test_buffer_never_adds_hydrologic_area(self):
        p = ROOT / "config/g040_full_basin_operational_contract_v1.json"
        j = json.loads(p.read_text(encoding="utf-8"))
        rule = j["spatial_domain"]["outside_basin_policy"].lower()
        self.assertIn("never contributes area", rule)

    def test_spatial_builder_outputs_mask_and_buffer(self):
        src = (ROOT / "scripts/build_g040_spatial_domain.py").read_text(encoding="utf-8")
        self.assertIn("g040_basin_mask.geojson", src)
        self.assertIn("g040_download_buffer.geojson", src)
        self.assertIn("EPSG:31982", src)

    def test_ecmwf_grid_is_buffer_derived_and_basin_weighted(self):
        src = (ROOT / "scripts/build_g040_buffered_ecmwf_field.py").read_text(encoding="utf-8")
        self.assertIn("g040_download_buffer.geojson", src)
        self.assertIn("basin_intersection_km2", src)
        self.assertIn("buffer-only cells are meteorological context", src)

    def test_snapshot_explicitly_has_no_single_endpoint(self):
        src = (ROOT / "scripts/build_g040_basin_snapshot.py").read_text(encoding="utf-8")
        self.assertIn('"single_endpoint": False', src)
        self.assertIn("g040_basin_controls_latest.csv", src)
        self.assertIn("g040_basin_network_latest.csv", src)
        self.assertIn("basin_station_status_latest.json", src)


if __name__ == "__main__":
    unittest.main()
