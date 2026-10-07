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

    def test_osm_referrer_policy_survives_v3_generation(self) -> None:
        html = (
            ROOT
            / "assets"
            / "data"
            / "estudo_bacia_taquari_antas"
            / "plataforma_hec_twin_mucum.html"
        ).read_text(encoding="utf-8")
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", html)
        self.assertIn('referrerPolicy:"strict-origin-when-cross-origin"', html)

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
        self.assertIn('id="map"', html)
        self.assertIn("selectNode", html)
        self.assertIn("Bacia Taquari–Antas · G040", html)
        self.assertIn("Rede hidrológica da bacia", html)
        self.assertIn("Rede BHO6", html)
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

    def test_hec_feed_exposes_unanchored_state_diagnostics(self) -> None:
        rr = self.feed.get("rainfall_runoff_result") or {}
        if rr.get("available"):
            self.assertEqual(rr.get("stage_series_kind"), "raw_rating_no_visual_anchor")
            self.assertIn("n_mucum_rating_cm", rr)
            self.assertIn("model_stage_t0_cm", rr)
            self.assertIn("stage_error_at_t0_cm", rr)
            self.assertNotIn("48 h de aquecimento", str(rr.get("plain_pt") or ""))

    def test_dual_boundary_nodes_exist_when_dual_is_selected(self) -> None:
        rr = self.feed.get("rainfall_runoff_result") or {}
        if rr.get("status") != "hec_hms_4_13_dual_boundary_validated":
            return
        codes = {str(n.get("code")) for n in ((self.feed.get("hydro_nodes") or {}).get("nodes") or [])}
        self.assertIn("86472000", codes)
        self.assertIn("86500000", codes)
        self.assertIn("86510000", codes)
        model_codes = {str(n.get("code")) for n in (((rr.get("corridor_nodes") or {}).get("nodes")) or [])}
        self.assertIn("86472000", model_codes)
        self.assertIn("86500000", model_codes)
        self.assertIn("86510000", model_codes)

    def test_operational_hec_is_public_source(self) -> None:
        rr = self.feed.get("rainfall_runoff_result") or {}
        self.assertIn(
            rr.get("artifact_json"),
            {
                "hec_hms_operational_forecast_latest.json",
                "hec_hms_dual_boundary_mucum_latest.json",
            },
        )
        self.assertNotIn("targeted_now", str(rr.get("artifact_json") or ""))
        if rr.get("available"):
            self.assertIn(
                rr.get("status"),
                {
                    "hec_hms_4_13_spatial_ifs_warmup_ready",
                    "hec_hms_4_13_dual_boundary_validated",
                },
            )
            self.assertEqual((rr.get("validation") or {}).get("blocking_reasons_pt") or [], [])
            if rr.get("status") == "hec_hms_4_13_dual_boundary_validated":
                self.assertEqual(
                    (rr.get("dual_boundary_validation") or {}).get("status"),
                    "VALIDATED",
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
        self.assertIn("Sete UGs dentro do mesmo sistema", html)
        self.assertIn('id="ugGrid"', html)
        self.assertIn("Object.entries(units)", html)
        self.assertLess(html.find('id="rede"'), html.find('id="modelo"'))
        self.assertLess(html.find("Área oficial G040"), html.find("Checkpoint Muçum"))
        self.assertIn("Guaporé", html)
        self.assertIn("Forqueta", html)
        hero = html[html.find("<header") : html.find("</header>")]
        self.assertIn("G040", hero)
        self.assertIn("bacia inteira", hero.lower())


if __name__ == "__main__":
    unittest.main()
