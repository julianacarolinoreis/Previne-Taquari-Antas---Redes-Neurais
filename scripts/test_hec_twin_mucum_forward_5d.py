#!/usr/bin/env python3
"""Tests for HEC twin ~5-day Muçum forward forecast package."""

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
    times = [f"2026-09-11T{h:02d}:00:00Z" for h in range(hours)]
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
    def test_q_to_stage_and_forward_offline(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import run_hec_twin_mucum_forward_5d as fwd

        segs = fwd.mucum_curve_segments()
        stage = fwd.q_to_stage_cm(1000.0, segs)
        self.assertTrue(stage["ok"])
        self.assertIsNotNone(stage["stage_cm"])
        self.assertGreater(stage["stage_cm"], 0)

        package = fwd.build_package(_synthetic_forcing(48))
        self.assertEqual(package["status"], "research_forward_5d_ready")
        lib = json.loads((OUT / "modelo_mucum_eventwise_v1_fechado_latest.json").read_text(encoding="utf-8"))
        self.assertIn(
            package["primary_member"]["event_id"],
            {r["event_id"] for r in lib["params_library_eventwise"]},
        )
        series = package["series_primary"]
        self.assertEqual(len(series["q_mucum_m3s"]), 48)
        self.assertTrue(max(series["q_mucum_m3s"]) > 0)
        self.assertEqual(package["santa_tereza"]["n_status"], "blocked_no_rating_curve")
        self.assertEqual(package["decision_alignment"]["primary_for_multiday"], "HEC_twin_plus_IFS_QPF")
        for i, b in enumerate(package["q_mucum_band_m3s"]):
            self.assertLessEqual(b["min"], series["q_mucum_m3s"][i] + 1e-6)
            self.assertGreaterEqual(b["max"], series["q_mucum_m3s"][i] - 1e-6)

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
