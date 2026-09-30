#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/build_g040_hydro_stack_scaffold.py"
CONFIG_PATH = ROOT / "config/g040_hydro_stack_v1.json"

spec = importlib.util.spec_from_file_location("g040_scaffold", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def fake_management_units():
    ug_names = [f"UG{i}" for i in range(1, 8)]
    rows = []
    for i in range(32):
        rows.append({
            "id": f"MGMT_{i+1:02d}",
            "name": f"Management {i+1}",
            "ug": ug_names[i % 7],
            "area_km2_epsg31982": 800.0 + i,
            "rain_station_count": 1,
            "flow_station_count": 1 if i % 3 == 0 else 0,
            "not_hec_computational_unit": True,
        })
    return rows


def fake_report_units():
    rows = []
    for i in range(145):
        rows.append({
            "id": i + 1,
            "area_km2": 10.0 + i,
            "cn_initial": 60.0,
            "main_channel_length_m": 1000.0 + i,
            "main_channel_slope_m_m": 0.01,
            "tc_kirpich_min": 30.0,
            "lag_scs_min": 18.0,
            "event2_calibration": {
                "cn_calibrated": 50.0,
                "initial_abstraction_mm": 20.0,
                "tc_kirpich_min": 25.0,
                "lag_min": 15.0,
            },
        })
    return rows


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.management = fake_management_units()
        self.report = fake_report_units()
        self.topology = {
            "topology_pass": False,
            "edge_count": 30,
            "cycles": [["A", "B"]],
        }

    def test_management_layer_is_not_hec_topology(self):
        units, topology = mod.validate_management_layer({
            "subbasins": self.management,
            "topology_audit": self.topology,
        })
        self.assertEqual(len(units), 32)
        self.assertFalse(topology["topology_pass"])
        self.assertTrue(all(u["not_hec_computational_unit"] for u in units))

    def test_report_145_is_target_inventory(self):
        units = mod.validate_report145({
            "scope": {"hec_subbasins": 145, "hec_reaches": 72},
            "subbasins": self.report,
        })
        self.assertEqual(len(units), 145)

    def test_sma_template_has_145_rows_and_no_invented_sma_parameters(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            mod.write_sma_template(out, self.report)
            rows = list(csv.DictReader((out / "sma_parameter_template.csv").open(encoding="utf-8")))
            self.assertEqual(len(rows), 145)
            sma_fields = [
                "canopy_storage_mm", "surface_storage_mm", "soil_storage_mm",
                "tension_storage_mm", "soil_percolation_mm_h",
                "gw1_storage_mm", "gw1_percolation_mm_h", "gw1_coefficient_h",
                "gw2_storage_mm", "gw2_percolation_mm_h", "gw2_coefficient_h",
                "initial_canopy_pct", "initial_surface_pct", "initial_soil_pct",
                "initial_gw1_pct", "initial_gw2_pct",
            ]
            for row in rows:
                self.assertNotEqual(row["legacy_cn_initial"], "")
                for field in sma_fields:
                    self.assertEqual(row[field], "")
                self.assertEqual(row["native_geometry_verified"], "NO")
                self.assertEqual(row["native_topology_verified"], "NO")

    def test_manifests_and_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            mod.write_mgb_manifest(out, self.management, self.report, self.cfg)
            mod.write_ras_manifest(out, self.cfg)
            mod.write_assimilation_ensemble(out, self.cfg)
            ready = mod.readiness(self.management, self.topology, self.report, self.cfg)

            mgb = json.loads((out / "mgb_prep_manifest.json").read_text(encoding="utf-8"))
            ras = json.loads((out / "hec_ras_coupling_manifest.json").read_text(encoding="utf-8"))
            ae = json.loads((out / "assimilation_ensemble_contract.json").read_text(encoding="utf-8"))

            self.assertEqual(mgb["reference_layers"]["management_polygons"], 32)
            self.assertEqual(mgb["reference_layers"]["report_hec_subbasins"], 145)
            self.assertGreaterEqual(len(ras["domains"]), 2)
            self.assertFalse(ae["ensemble"]["automatic_simple_mean"])
            self.assertFalse(ready["promotion_allowed"])
            self.assertTrue(ready["gates"]["management_layer_32"]["pass"])
            self.assertTrue(ready["gates"]["report_inventory_145"]["pass"])
            self.assertFalse(ready["gates"]["native_hec_145_geometry_topology"]["pass"])
            self.assertFalse(ready["gates"]["sma_parameters_sourced"]["pass"])


if __name__ == "__main__":
    unittest.main()
