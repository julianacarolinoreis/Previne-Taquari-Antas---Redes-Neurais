#!/usr/bin/env python3
"""Smoke tests for the HEC/REC platform feed (anchors + automation)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = (
    ROOT
    / "assets"
    / "data"
    / "estudo_bacia_taquari_antas"
    / "plataforma_hec_twin_mucum_latest.json"
)


class PlataformaHecTwinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.feed = json.loads(FEED.read_text(encoding="utf-8"))

    def test_has_many_anchors(self) -> None:
        anchors = self.feed["spatial"]["anchors"]
        self.assertGreaterEqual(len(anchors), 25)
        roles = {a["role"] for a in anchors}
        self.assertIn("target", roles)
        self.assertIn("level_control", roles)
        self.assertIn("rain", roles)
        self.assertIn("upstream_monitor", roles)
        mucum = [a for a in anchors if a["code"] == "86510000"]
        self.assertEqual(len(mucum), 1)
        self.assertEqual(mucum[0]["role"], "target")
        # PREVINE seeds densified on the corridor map
        codes = {a["code"] for a in anchors}
        for code in ("86306000", "86430900", "86447000", "B859", "2851044"):
            self.assertIn(code, codes)

    def test_automation_robot_declared(self) -> None:
        auto = self.feed["automation"]
        self.assertIn("hec-twin-mucum-forward.yml", auto["workflow"])
        self.assertTrue(auto["does_not_touch_rna"])
        self.assertTrue(auto["research_not_alert"])
        self.assertGreaterEqual(len(auto["steps_pt"]), 3)

    def test_event_trace_and_freshness(self) -> None:
        trace = self.feed["event_trace"]
        self.assertGreaterEqual(trace["n_points"], 10)
        self.assertTrue(trace["series"])
        self.assertEqual(trace["series"][0].keys(), set(trace["series"][0].keys()) | {"t", "n_cm"})
        self.assertIn("t", trace["series"][0])
        self.assertIn("n_cm", trace["series"][0])
        fresh = self.feed["freshness"]
        self.assertIn("stale_forward", fresh)
        self.assertIn("preferred_source", fresh)
        self.assertIn("live_eval", self.feed["products"])
        self.assertIn("forward_5d", self.feed["products"])
        self.assertGreaterEqual(self.feed["spatial"]["anchor_count"], 25)
        self.assertIn("ug_rain_mm", self.feed["spatial"])

    def test_corridor_basin_calibration_not_stz_shortcut(self) -> None:
        corridor = self.feed["corridor"]
        self.assertTrue(corridor["not_full_g040"])
        self.assertTrue(corridor["not_only_stz_mucum_shortcut"])
        ids = [s["id"] for s in corridor["subbasins"]]
        self.assertEqual(
            ids,
            [
                "SB_PRATA_7868",
                "SB_ANTAS_RESIDUAL",
                "SB_CARREIRO_7866",
                "SB_STZ_RESIDUAL",
                "SB_INC_MUCUM",
            ],
        )
        self.assertIn("Guaporé", corridor["excluded_pt"])
        labels = " ".join(a["label"] for a in self.feed["spatial"]["anchors"])
        self.assertNotIn("Guaporé", labels)
        self.assertTrue(self.feed["discipline"]["basin_calibrated_analogs"])
        self.assertIn("corredor", self.feed["label_pt"].lower())
        framing = self.feed["spatial"]["basin_framing"]
        self.assertTrue(framing["not_full_basin_model"])
        self.assertIn("Alto Taquari-Antas", framing["twin_domain_ugs"])
        self.assertIn("Guaporé", framing["excluded_ugs"])
        self.assertEqual(len(framing["g040_ugs"]), 7)
        self.assertIn("Alto Taquari-Antas", self.feed["spatial"]["ug_filter"])
        self.assertIn("g040", self.feed["spatial"]["note_pt"].lower())
        html = (
            ROOT
            / "assets"
            / "data"
            / "estudo_bacia_taquari_antas"
            / "plataforma_hec_twin_mucum.html"
        ).read_text(encoding="utf-8")
        self.assertIn("pointInspector", html)
        self.assertIn("showInspector", html)
        self.assertIn("Bacia G040", html)
        self.assertIn("loadFozes", html)
        self.assertIn("Fozes BHO6", html)
        self.assertEqual(
            self.feed["spatial"].get("fozes_geojson"),
            "fozes_principais_bho6.geojson",
        )

    def test_hindcast_skill_events_and_corridor_network(self) -> None:
        skill = self.feed["products"]["hindcast_skill"]
        self.assertGreaterEqual(len(skill.get("events") or []), 9)
        cal = skill.get("calibration") or {}
        self.assertTrue(cal.get("lessons_pt"))
        self.assertEqual(cal.get("best_event_id"), "E22")
        self.assertEqual(cal.get("worst_rel_event_id"), "E25")
        self.assertEqual(cal.get("worst_peak_event_id"), "E27")
        net = self.feed["spatial"]["corridor_network"]
        self.assertGreaterEqual((net.get("counts") or {}).get("total", 0), 150)
        self.assertGreaterEqual(len(net.get("features") or []), 150)
        # curated anchors remain a subset signal — network is the dense inventory
        self.assertGreater(
            net["counts"]["total"], self.feed["spatial"]["anchor_count"]
        )

if __name__ == "__main__":
    unittest.main()
