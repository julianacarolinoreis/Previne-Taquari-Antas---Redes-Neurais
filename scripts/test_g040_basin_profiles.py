#!/usr/bin/env python3
"""Smoke tests for G040 longitudinal basin profiles."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
JSON = OUT / "perfis_longitudinais_g040_latest.json"
HTML = OUT / "perfis_longitudinais_g040.html"
PAGES = ROOT / "pesquisas" / "perfis-g040-mdt.html"
CENTER = OUT / "perfis_longitudinais_g040_centerlines.geojson"


class G040BasinProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not JSON.exists():
            raise unittest.SkipTest("profiles artifact missing — run build_g040_basin_profiles.py")
        cls.report = json.loads(JSON.read_text(encoding="utf-8"))

    def test_three_profiles_present(self) -> None:
        ids = [p["id"] for p in self.report["profiles"]]
        self.assertEqual(ids, ["tronco_taquari_antas", "guapore", "forqueta"])

    def test_mainstem_longer_than_tributaries(self) -> None:
        by = {p["id"]: p for p in self.report["profiles"]}
        trunk = by["tronco_taquari_antas"]["summary"]["length_km"]
        gua = by["guapore"]["summary"]["length_km"]
        forq = by["forqueta"]["summary"]["length_km"]
        self.assertGreater(trunk, 150)
        self.assertGreater(gua, 40)
        self.assertGreater(forq, 40)
        self.assertGreater(trunk, gua)
        self.assertGreater(trunk, forq)

    def test_positive_drop_head_to_mouth(self) -> None:
        for p in self.report["profiles"]:
            s = p["summary"]
            self.assertGreater(s["elev_start_m"], s["elev_end_m"], p["id"])
            self.assertGreater(s["drop_m"], 50, p["id"])
            self.assertGreaterEqual(s["n"], 50, p["id"])

    def test_honesty_flags(self) -> None:
        d = self.report["discipline"]
        self.assertTrue(d["not_hydraulic_cross_section"])
        self.assertTrue(d["research_not_alert"])
        self.assertTrue(d.get("markers_are_axis_projections"))
        self.assertIn("SRTM", self.report["dem"]["source"])
        self.assertEqual(self.report["schema_version"], "g040_basin_profiles_v3")

    def test_axis_markers(self) -> None:
        markers = self.report.get("axis_markers") or []
        self.assertGreaterEqual(len(markers), 10)
        codes = {m["code"] for m in markers if m.get("kind") == "flu"}
        for required in ("86510000", "86472600", "86720000", "86895000"):
            self.assertIn(required, codes)
        foz_codes = {m["code"] for m in markers if m.get("kind") == "foz"}
        self.assertTrue({"7868", "7866", "7864", "7862"} <= foz_codes)
        by_axis = {p["id"]: p for p in self.report["profiles"]}
        for p in by_axis.values():
            self.assertIn("markers", p)
        mucum = next(m for m in markers if m.get("code") == "86510000")
        self.assertEqual(mucum["axis_id"], "tronco_taquari_antas")
        self.assertIsNotNone(mucum.get("distance_km"))
        self.assertLess(float(mucum.get("off_axis_m") or 1e9), 5000)
        html = PAGES.read_text(encoding="utf-8")
        self.assertIn("axisMap", html)
        self.assertIn("leaflet", html.lower())
        self.assertIn("Muçum", html)
        self.assertIn("Mapa dos eixos", html)

    def test_estudo_index_link(self) -> None:
        index = OUT / "index.html"
        text = index.read_text(encoding="utf-8")
        self.assertIn("perfis_longitudinais_g040.html", text)
        self.assertIn("Perfis longitudinais MDT", text)
        self.assertIn("../../../pesquisas/perfis-g040-mdt.html", text)

    def test_municipal_profiles(self) -> None:
        muns = self.report.get("municipal_profiles") or []
        self.assertGreaterEqual(len(muns), 40)
        names = {m["nome"] for m in muns}
        for required in ("Muçum", "Encantado", "Santa Tereza", "Lajeado", "Taquari"):
            self.assertIn(required, names)
        mucum = next(m for m in muns if m["nome"] == "Muçum")
        self.assertIn("tronco_taquari_antas", mucum["axes"])
        self.assertGreater(mucum["summary"]["length_km"], 1.0)
        html = PAGES.read_text(encoding="utf-8")
        self.assertIn("Perfis por município", html)
        self.assertIn("munSearch", html)
        self.assertIn("Muçum", html)

    def test_html_artifacts(self) -> None:
        for path in (HTML, PAGES):
            text = path.read_text(encoding="utf-8")
            self.assertIn("bacia Taquari–Antas (G040)", text)
            self.assertIn("Tronco Taquari–Antas", text)
            self.assertIn("Guaporé", text)
            self.assertIn("Forqueta", text)
            self.assertIn("não é seção hidráulica", text)
            self.assertIn("<polyline", text)

    def test_centerlines_geojson(self) -> None:
        geo = json.loads(CENTER.read_text(encoding="utf-8"))
        self.assertEqual(len(geo["features"]), 3)
        ids = {f["properties"]["id"] for f in geo["features"]}
        self.assertEqual(ids, {"tronco_taquari_antas", "guapore", "forqueta"})


if __name__ == "__main__":
    unittest.main()
