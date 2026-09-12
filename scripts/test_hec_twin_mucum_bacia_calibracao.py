#!/usr/bin/env python3
"""Tests for Muçum basin-calibrated analog transfer."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"


class BasinCalibrationTests(unittest.TestCase):
    def test_light_qpf_avoids_zero_constant_loss_primary(self) -> None:
        import hec_twin_mucum_bacia_calibracao as bacia
        import run_hec_twin_mucum_forward_5d as fwd
        import run_hec_twin_stz_mucum_calibrate as cal

        modelo = json.loads((OUT / "modelo_mucum_eventwise_v1_fechado_latest.json").read_text(encoding="utf-8"))
        hec = json.loads((OUT / "hec_twin_stz_mucum_v1_latest.json").read_text(encoding="utf-8"))
        library = list(modelo["params_library_eventwise"])
        events = list(hec["models"]["mucum"]["events"])
        areas = fwd.load_areas()
        fps = bacia.build_event_fingerprints(events, areas, prepare_event_forcing=cal.prepare_event_forcing)
        dry = bacia.infer_wetness_state(forecast_aw_mm=35.0, past_aw_mm=2.0, stage_cm=180.0, stage_rising=False)
        analogs = bacia.choose_analogs(35.0, library, events, top_k=1, fingerprints=fps, wetness=dry)
        self.assertTrue(analogs)
        primary = analogs[0]["event_id"]
        self.assertNotEqual(primary, "E31")
        # LOO for E25 should not pick E31 anymore
        loo = bacia.choose_analogs(
            fps["E25"]["aw_full_mm"],
            library,
            events,
            top_k=1,
            fingerprints=fps,
            exclude_event_ids={"E25"},
            wetness=dry,
        )
        self.assertTrue(loo)
        self.assertNotEqual(loo[0]["event_id"], "E31")

    def test_wet_state_prefers_low_loss_donor(self) -> None:
        import hec_twin_mucum_bacia_calibracao as bacia
        import run_hec_twin_mucum_forward_5d as fwd
        import run_hec_twin_stz_mucum_calibrate as cal

        modelo = json.loads((OUT / "modelo_mucum_eventwise_v1_fechado_latest.json").read_text(encoding="utf-8"))
        hec = json.loads((OUT / "hec_twin_stz_mucum_v1_latest.json").read_text(encoding="utf-8"))
        library = list(modelo["params_library_eventwise"])
        events = list(hec["models"]["mucum"]["events"])
        areas = fwd.load_areas()
        fps = bacia.build_event_fingerprints(events, areas, prepare_event_forcing=cal.prepare_event_forcing)
        wet = bacia.infer_wetness_state(
            forecast_aw_mm=33.3, past_aw_mm=29.7, stage_cm=425.0, stage_rising=True
        )
        self.assertTrue(wet["is_wet"])
        analogs = bacia.choose_analogs(33.3, library, events, top_k=3, fingerprints=fps, wetness=wet)
        self.assertEqual(analogs[0]["event_id"], "E23")
        self.assertNotIn(analogs[0]["event_id"], {"E30", "E31"})
        # Wet primary among rises should prefer upper member (E23), not dry median cluster.
        members = [
            {"event_id": "E25", "rise": {"rise_model_cm": 143.0}},
            {"event_id": "E20", "rise": {"rise_model_cm": 143.0}},
            {"event_id": "E23", "rise": {"rise_model_cm": 262.0}},
        ]
        idx = bacia.pick_primary_by_median_rise(members, wetness=wet)
        self.assertEqual(members[idx]["event_id"], "E23")

    def test_strict_damp_and_blend_helpers(self) -> None:
        import hec_twin_mucum_bacia_calibracao as bacia
        from hec_twin_nested_v17 import NestedParams, ZoneParams

        soft_only = bacia.infer_wetness_state(
            forecast_aw_mm=40.0, past_aw_mm=25.0, stage_cm=200.0, stage_rising=False
        )
        self.assertTrue(soft_only["is_wet"])
        self.assertFalse(bacia.should_damp_losses(soft_only))

        strict = bacia.infer_wetness_state(
            forecast_aw_mm=33.0, past_aw_mm=29.0, stage_cm=425.0, stage_rising=True
        )
        self.assertTrue(bacia.should_damp_losses(strict))

        params = NestedParams(
            up=ZoneParams(1.0, 2.0, 10.0, 20.0, 0.8, 0.01),
            dn=ZoneParams(1.0, 2.0, 10.0, 20.0, 0.8, 0.01),
            k1=0.2, k2=1.0, k3=0.5, x=0.2,
        )
        damp, meta = bacia.damp_losses_for_wetness(params, strict, factor=0.5)
        self.assertTrue(meta["applied"])
        self.assertAlmostEqual(damp.up.initial_loss, 0.5)

        blend, weights = bacia.distance_weighted_blend([[1.0, 3.0], [3.0, 5.0]], [0.1, 0.5])
        self.assertEqual(len(blend), 2)
        self.assertAlmostEqual(sum(weights), 1.0, places=5)
        self.assertLess(blend[0], 3.0)

        rev = bacia.revise_remaining_rise_cm(80.0, 140.0, 280.0)
        self.assertTrue(rev["applied"])
        self.assertLessEqual(rev["remaining_cm"], 80.0 * 1.35 + 1e-6)

    def test_bacia_artifact_exists_with_regimes(self) -> None:
        path = OUT / "modelo_mucum_bacia_calibrado_v1_latest.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "modelo_mucum_bacia_calibrado_v1")
        self.assertIn("fingerprints", data)
        self.assertIn("regime_specialists", data)
        self.assertLessEqual(data["loo_skill"]["summary"]["mean_rise_n_rel_err"], 0.45)


if __name__ == "__main__":
    unittest.main()
