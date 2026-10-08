#!/usr/bin/env python3
"""Tests for HEC twin ~5-day Muçum forward forecast (chuva → quanto sobe)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
SCRIPTS = ROOT / "scripts"
SUBBASINS = [
    "SB_PRATA_7868",
    "SB_ANTAS_RESIDUAL",
    "SB_CARREIRO_7866",
    "SB_STZ_RESIDUAL",
    "SB_INC_MUCUM",
]


def _synthetic_forcing(hours: int = 48) -> dict:
    # Valid UTC hours across two days
    times = []
    for h in range(hours):
        day = 11 + h // 24
        hour = h % 24
        times.append(f"2026-09-{day:02d}T{hour:02d}:00:00Z")
    base = [0.2] * hours
    for i in range(12, 24):
        base[i] = 4.0 + (i - 12) * 0.3
    precip = {sb: list(base) for sb in SUBBASINS}
    precip["SB_CARREIRO_7866"] = [x * 1.2 for x in base]
    return {
        "schema_version": "hec_twin_ifs_forcing_5d_v1",
        "generated_at_utc": "2026-09-11T12:00:00Z",
        "status": "research_forcing_ready",
        "horizon_hours": hours,
        "model": "synthetic_test",
        "times_utc": times,
        "precip_mm_by_subbasin": precip,
        "area_weighted_mean_mm": {
            "hourly": base,
            "total_mm": float(sum(base)),
            "max_hourly_mm": float(max(base)),
            "totals_by_subbasin_mm": {sb: float(sum(precip[sb])) for sb in SUBBASINS},
        },
        "discipline": {"point_proxy_not_areal_mask": True, "not_official_alert": True},
    }


class Forward5dTests(unittest.TestCase):
    def test_q_to_stage_forward_and_rise_answer(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import run_hec_twin_mucum_forward_5d as fwd

        segs = fwd.mucum_curve_segments()
        stage = fwd.q_to_stage_cm(1000.0, segs)
        self.assertTrue(stage["ok"])
        self.assertGreater(stage["stage_cm"], 0)

        # Fail closed above the frozen 15 m research safety limit even though
        # the official mathematical segment extends higher.
        unsafe_q = fwd.q_to_stage_cm(6723.0, segs)
        self.assertFalse(unsafe_q["ok"])
        self.assertIsNone(unsafe_q["stage_cm"])
        self.assertEqual(unsafe_q["reason"], "above_frozen_rating_curve_safety_limit")
        self.assertEqual(unsafe_q["safety_limit_cm"], 1500.0)

        unsafe_stage = fwd.stage_to_q_m3s(1600.0, segs)
        self.assertFalse(unsafe_stage["ok"])
        self.assertIsNone(unsafe_stage["q_m3s"])
        self.assertEqual(unsafe_stage["reason"], "above_frozen_rating_curve_safety_limit")

        package = fwd.build_package(_synthetic_forcing(48), allow_network=False)
        self.assertEqual(package["status"], "research_forward_5d_ready")
        lib = json.loads((OUT / "modelo_mucum_eventwise_v1_fechado_latest.json").read_text(encoding="utf-8"))
        primary_id = package["primary_member"]["event_id"]
        lib_ids = {r["event_id"] for r in lib["params_library_eventwise"]}
        self.assertTrue(primary_id == "BLEND" or primary_id in lib_ids)
        self.assertEqual(package["schema_version"], "hec_twin_mucum_forward_5d_v5")
        self.assertIn("now_index", package["quanto_sobe"])
        qs = package["quanto_sobe"]
        self.assertIn("plain_pt", qs)
        self.assertIsNotNone(qs["primary"]["rise_cm"])
        self.assertGreater(qs["primary"]["rise_cm"], 0)
        self.assertEqual(qs["level_now"]["ok"], True)
        self.assertIsNotNone(qs["primary"]["peak_anchored_cm"])
        series = package["series_primary"]
        self.assertEqual(len(series["q_mucum_m3s"]), 48)
        self.assertIn("n_mucum_anchored_cm", series)
        self.assertIn("delta_n_from_now_cm", series)
        self.assertEqual(package["santa_tereza"]["n_status"], "blocked_no_rating_curve")
        self.assertEqual(package["decision_alignment"]["primary_for_multiday"], "HEC_twin_plus_IFS_QPF")
        html = fwd.render_html(package)
        self.assertIn("Resposta:", html)
        self.assertIn(str(int(qs["primary"]["rise_cm"])), html.replace(".", "").replace(",", "") or html)

    def test_forecast_only_rain_is_not_observed_wetness(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import run_hec_twin_mucum_forward_5d as fwd

        forecast = _synthetic_forcing(48)
        forecast["area_weighted_mean_mm"]["past_mm"] = None
        forecast["window"] = {"past_hours": 0}
        state = fwd.infer_forcing_wetness(forecast, now_index=0)
        self.assertIsNone(state["past_aw_mm"])
        self.assertEqual(state["antecedent_status"], "dry_not_confirmed")

        # A 72h observed window takes precedence over the forecast-only hourly array.
        forecast["area_weighted_mean_mm"]["past_mm"] = 31.5
        forecast["antecedent_rain"] = {
            "status": "representative", "representative_hours": 72, "window_hours": 72,
        }
        state = fwd.infer_forcing_wetness(forecast, now_index=0)
        self.assertEqual(state["past_aw_mm"], 31.5)
        self.assertTrue(state["is_wet"])

    def test_sparse_antecedent_does_not_become_dry_zeros(self) -> None:
        import importlib.util
        import tempfile
        from unittest.mock import patch
        from datetime import datetime, timedelta

        path = SCRIPTS / "build_hec_twin_ifs_spatial_forcing_5d.py"
        spec = importlib.util.spec_from_file_location("ifs_spatial_forcing_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        t0 = datetime(2026, 10, 8, 14, 0)
        rows = []
        for i in range(72, 0, -1):
            t = t0 - timedelta(hours=i)
            rows.append({
                "time_local": t.isoformat(timespec="minutes"),
                "valid_station_count": 4 if i == 8 else 45,
                "basin_mean_mm": 0.25,
            })
        with tempfile.TemporaryDirectory() as tmp:
            observed = Path(tmp) / "obs.json"
            observed.write_text(
                json.dumps({"generated_at_utc": "2026-10-08T16:00:00Z",
                            "rain": {"hourly_areal": rows}}), encoding="utf-8"
            )
            with patch.object(module, "OBSERVED", observed), patch.object(module, "ROOT", Path(tmp)):
                sparse = module.observed_antecedent_rain("2026-10-08T17:00:00Z")
                self.assertEqual(sparse["representative_hours"], 71)
                self.assertEqual(sparse["status"], "incomplete_observed_coverage")
                self.assertIsNone(sparse["past_mm"])
                self.assertAlmostEqual(sparse["partial_sum_mm"], 17.75)
                rows[64]["valid_station_count"] = 45
                observed.write_text(
                    json.dumps({"rain": {"hourly_areal": rows}}), encoding="utf-8"
                )
                complete = module.observed_antecedent_rain("2026-10-08T17:00:00Z")
                self.assertEqual(complete["representative_hours"], 72)
                self.assertEqual(complete["past_mm"], 18.0)

    def test_decision_builder(self) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "build_estudo_decisao_hec_5d_evacuacao.py")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads((OUT / "decisao_previsao_nivel_multi_alvo_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["decision"]["chosen_primary_multiday"], "HEC_twin_plus_IFS_QPF")
        self.assertFalse(data["decision"]["stz_rating_curve"]["exists"])


if __name__ == "__main__":
    unittest.main()
