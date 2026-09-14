#!/usr/bin/env python3
"""Smoke tests for the HEC/REC platform feed (basin G040 + Muçum twin product)."""

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
        self.assertIn("t", trace["series"][0])
        self.assertIn("n_cm", trace["series"][0])
        fresh = self.feed["freshness"]
        self.assertIn("stale_forward", fresh)
        self.assertIn("preferred_source", fresh)
        self.assertIn("live_eval", self.feed["products"])
        self.assertIn("forward_5d", self.feed["products"])
        self.assertGreaterEqual(self.feed["spatial"]["anchor_count"], 25)
        self.assertIn("ug_rain_mm", self.feed["spatial"])

    def test_basin_g040_is_spatial_subject(self) -> None:
        """Juliana: the page is the FULL Taquari–Antas basin, not Muçum-only."""
        label = self.feed["label_pt"].lower()
        self.assertIn("bacia", label)
        self.assertIn("g040", label.replace("–", "-").lower())
        self.assertNotIn("corredor calibrado", label)

        framing = self.feed["spatial"]["basin_framing"]
        self.assertEqual(framing.get("spatial_subject"), "g040_full_basin")
        self.assertEqual(len(framing["g040_ugs"]), 7)
        for ug in (
            "Alto Taquari-Antas",
            "Guaporé",
            "Forqueta",
            "Baixo Taquari-Antas",
            "Prata",
            "Carreiro",
            "Médio Taquari-Antas",
        ):
            self.assertIn(ug, framing["g040_ugs"])
            self.assertIn(ug, self.feed["spatial"]["ug_filter"])

        # Twin product remains corridor (honest HEC domain).
        corridor = self.feed["corridor"]
        self.assertTrue(corridor["not_full_g040"])
        self.assertTrue(corridor.get("is_product_inside_basin"))
        self.assertTrue(framing["hec_twin_not_full_basin"])
        self.assertIn("Alto Taquari-Antas", framing["twin_domain_ugs"])
        self.assertEqual(len(framing["twin_domain_ugs"]), 4)
        self.assertIn("Guaporé", framing["excluded_ugs"])

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
        labels = " ".join(a["label"] for a in self.feed["spatial"]["anchors"])
        self.assertNotIn("Guaporé", labels)
        self.assertTrue(self.feed["discipline"]["basin_calibrated_analogs"])
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
        self.assertIn("bacia Taquari–Antas (G040)", html)
        self.assertIn("Rede G040", html)
        self.assertIn("loadFozes", html)
        self.assertEqual(
            self.feed["spatial"].get("fozes_geojson"),
            "fozes_principais_bho6.geojson",
        )

    def test_basin_network_covers_all_seven_ugs(self) -> None:
        net = self.feed["spatial"].get("basin_network") or self.feed["spatial"][
            "corridor_network"
        ]
        self.assertGreaterEqual((net.get("counts") or {}).get("total", 0), 300)
        ugs = {
            (f.get("properties") or {}).get("ug")
            for f in (net.get("features") or [])
        }
        for ug in (
            "Alto Taquari-Antas",
            "Prata",
            "Carreiro",
            "Médio Taquari-Antas",
            "Guaporé",
            "Forqueta",
            "Baixo Taquari-Antas",
        ):
            self.assertIn(ug, ugs, f"missing UG in basin network: {ug}")
        self.assertGreater(
            net["counts"]["total"], self.feed["spatial"]["anchor_count"]
        )
        self.assertGreaterEqual(
            (net.get("counts") or {}).get("outside_twin_domain", 0), 50
        )

    def test_hindcast_skill_events(self) -> None:
        skill = self.feed["products"]["hindcast_skill"]
        self.assertGreaterEqual(len(skill.get("events") or []), 9)
        cal = skill.get("calibration") or {}
        self.assertTrue(cal.get("lessons_pt"))
        self.assertEqual(cal.get("best_event_id"), "E22")
        self.assertEqual(cal.get("worst_rel_event_id"), "E25")
        self.assertEqual(cal.get("worst_peak_event_id"), "E27")


    def test_inventory_stats_cover_excluded_ugs(self) -> None:
        inv = self.feed["spatial"]["inventory_stats"]
        totals = inv["totals"]
        self.assertEqual(totals["ugs"], 7)
        self.assertGreaterEqual(totals["outside_twin_domain"], 50)
        by = inv["by_ug"]
        for ug in ("Guaporé", "Forqueta", "Baixo Taquari-Antas"):
            self.assertIn(ug, by)
            self.assertFalse(by[ug]["in_twin_domain"])
            self.assertGreaterEqual(by[ug]["total"], 1)
            self.assertIsNotNone(by[ug].get("area_km2_approx"))

    def test_html_puts_basin_before_mucum_product(self) -> None:
        html = (
            ROOT
            / "assets"
            / "data"
            / "estudo_bacia_taquari_antas"
            / "plataforma_hec_twin_mucum.html"
        ).read_text(encoding="utf-8")
        self.assertIn("Bacia Taquari–Antas", html)
        self.assertIn("Inventário por UG", html)
        self.assertIn("renderUgInventory", html)
        self.assertIn("ugInventory", html)
        self.assertLess(html.find("basinMapSection"), html.find("corridorCard"))
        self.assertLess(html.find("basinMetrics"), html.find("productMetrics"))
        self.assertIn("Guaporé", html)
        self.assertIn("Forqueta", html)
        hero = html[html.find("<header") : html.find("</header>")]
        self.assertIn("G040", hero)
        self.assertTrue("26.430" in hero or "26,430" in hero or "26430" in hero)


    def test_methodology_is_honest(self) -> None:
        meth = self.feed["methodology"]
        self.assertTrue(meth.get("not_hec_hms_binary"))
        self.assertTrue(meth.get("not_hec_ras"))
        self.assertTrue(meth.get("not_cwms"))
        self.assertGreaterEqual(len(meth.get("events", {}).get("core") or []), 9)
        skill = meth.get("skill") or {}
        self.assertIsNotNone(skill.get("mean_self_fit_nse"))
        self.assertIsNotNone(skill.get("mean_nse_loo"))
        self.assertIn("Self-fit", skill.get("contrast_pt") or "")
        self.assertTrue(self.feed["discipline"].get("not_full_g040_calibrated"))

    def test_hindcast_exposes_self_fit_vs_loo(self) -> None:
        skill = self.feed["products"]["hindcast_skill"]
        summary = skill["summary"]
        self.assertIn("mean_self_fit_nse", summary)
        self.assertIn("mean_nse_loo", summary)
        ev0 = skill["events"][0]
        self.assertIn("self_fit_nse", ev0)
        self.assertIn("nse_loo", ev0)
        html = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "data"
            / "estudo_bacia_taquari_antas"
            / "plataforma_hec_twin_mucum.html"
        ).read_text(encoding="utf-8")
        self.assertIn("methodCard", html)
        self.assertIn("Self-fit", html)
        self.assertIn("NSE LOO", html)
        self.assertIn("networkLayer = L.layerGroup();", html)
        self.assertNotIn("networkLayer = L.layerGroup().addTo(map)", html)


if __name__ == "__main__":
    unittest.main()
