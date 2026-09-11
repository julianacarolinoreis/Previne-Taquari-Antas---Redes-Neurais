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
        analogs = bacia.choose_analogs(35.0, library, events, top_k=1, fingerprints=fps)
        self.assertTrue(analogs)
        primary = analogs[0]["event_id"]
        self.assertNotEqual(primary, "E31")
        # LOO for E25 should not pick E31 anymore
        loo = bacia.choose_analogs(
            fps["E25"]["aw_full_mm"], library, events, top_k=1, fingerprints=fps, exclude_event_ids={"E25"}
        )
        self.assertTrue(loo)
        self.assertNotEqual(loo[0]["event_id"], "E31")

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
