#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_g040_incremental_geometries.py"

spec = importlib.util.spec_from_file_location("g040_geom", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class GeometrySourcePolicyTests(unittest.TestCase):
    def test_same_version_bho6_source_is_required(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("GEOFT_BHO_AREA_DRENAGEM", source)
        self.assertIn("geoft_bho_area_drenagem.gpkg", source)
        self.assertNotIn("BHO2017_POLY", source)
        self.assertNotIn("arcgis/rest/services/SPR/BHO2017_50K_AREADRENAGEM", source)

    def test_missing_clip_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.geojson"
            by_code, meta = mod.load_bho6_polygon_clip(missing)
            self.assertEqual(by_code, {})
            self.assertFalse(meta["available"])
            self.assertEqual(meta["feature_count"], 0)

    def test_clip_loader_preserves_exact_cobacia(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "clip.geojson"
            path.write_text(
                json.dumps({
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"COBACIA": "786515"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[
                                    [-52.0, -29.0],
                                    [-51.9, -29.0],
                                    [-51.9, -29.1],
                                    [-52.0, -29.1],
                                    [-52.0, -29.0]
                                ]]
                            }
                        }
                    ]
                }),
                encoding="utf-8",
            )
            by_code, meta = mod.load_bho6_polygon_clip(path)
            self.assertTrue(meta["available"])
            self.assertEqual(meta["feature_count"], 1)
            self.assertIn("786515", by_code)
            self.assertEqual(len(by_code["786515"]), 1)


if __name__ == "__main__":
    unittest.main()
