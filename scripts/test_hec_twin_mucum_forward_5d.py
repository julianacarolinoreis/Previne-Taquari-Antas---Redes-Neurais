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

        package = fwd.build_package(_synthetic_forcing(48), allow_network=False)
        self.assertEqual(package["status"], "research_forward_5d_ready")
        lib = json.loads((OUT / "modelo_mucum_eventwise_v1_fechado_latest.json").read_text(encoding="utf-8"))
        self.assertIn(
            package["primary_member"]["event_id"],
            {r["event_id"] for r in lib["params_library_eventwise"]},
        )
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
