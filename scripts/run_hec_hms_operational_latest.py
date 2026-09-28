#!/usr/bin/env python3
"""Run one operational HEC-HMS 4.13 forecast with the latest accepted calibration.

Purpose:
- every fast cycle uses the newest observed basin data and newest Muçum t0;
- no expensive parameter search in the 10-minute loop;
- calibrated parameters come only from the latest hourly calibration product;
- the raw HEC result is postprocessed/validated at the exact observation time;
- no visual level shift is ever applied.

This keeps the forecast current while the heavy calibration remains hourly.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas"
CAL = OUT / "hec_hms_live_event_calibration_latest.json"
RESULT = OUT / "hec_hms_spatial_forecast_mucum_latest.json"
OP_RESULT = OUT / "hec_hms_operational_forecast_latest.json"
RUNTIME = OUT / "hec_hms_spatial_forecast_mucum"
SCRIPT = RUNTIME / "project/run_forecast.script"

ENV = {
    "initial_loss_mm": "HEC_INITIAL_LOSS_MM",
    "constant_loss_mm_h": "HEC_CONSTANT_LOSS_MM_H",
    "tc_h": "HEC_TC_H",
    "storage_h": "HEC_STORAGE_H",
    "recession": "HEC_RECESSION_DAILY",
    "initial_flow_multiplier": "HEC_INITIAL_FLOW_MULTIPLIER",
}

def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_hec_hms_operational_latest.py /path/to/hec-hms.sh")
    hec = Path(sys.argv[1])
    if not hec.exists():
        raise SystemExit(f"HEC executable not found: {hec}")
    if not CAL.exists():
        raise SystemExit("latest accepted live calibration is missing")

    cal = load(CAL)
    params = dict(cal.get("selected_parameters") or {})
    selected = cal.get("selected") or {}
    event = str(selected.get("seed_event") or cal.get("seed_event") or "E28")

    required = set(ENV)
    missing = sorted(required - set(params))
    if missing:
        raise SystemExit(f"calibration missing parameters: {missing}")

    env = os.environ.copy()
    env["HEC_PARAM_EVENT"] = event
    for key, env_name in ENV.items():
        env[env_name] = str(params[key])

    subprocess.run(
        [sys.executable, "-B", "scripts/build_hec_hms_spatial_forecast_mucum.py"],
        cwd=ROOT, env=env, check=True,
    )

    out_csv = RUNTIME / "hec_output_values.csv"
    if out_csv.exists():
        out_csv.unlink()

    subprocess.run(
        [str(hec), "-s", str(SCRIPT)],
        cwd=ROOT, env=env, check=True,
    )
    if not out_csv.exists() or out_csv.stat().st_size == 0:
        raise RuntimeError("HEC-HMS produced no operational outlet series")

    subprocess.run(
        [sys.executable, "-B", "scripts/postprocess_hec_hms_spatial_forecast_mucum.py"],
        cwd=ROOT, env=env, check=True,
    )

    pkg = load(RESULT)
    pkg["operational_cycle"] = {
        "mode": "latest_observed_state_plus_latest_accepted_calibration",
        "calibration_generated_at_utc": cal.get("generated_at_utc"),
        "calibration_parameters": params,
        "seed_event": event,
        "recalibration_performed_this_cycle": False,
        "visual_stage_anchor_applied": False,
    }
    OP_RESULT.write_text(
        json.dumps(pkg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Keep the generic result in sync with the operational product used by UI.
    RESULT.write_text(
        json.dumps(pkg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "publishable": pkg.get("publishable"),
        "observed_at_utc": (pkg.get("current_state") or {}).get("observed_at_utc"),
        "observed_stage_cm": (pkg.get("current_state") or {}).get("stage_cm"),
        "model_stage_t0_cm": (pkg.get("validation") or {}).get("raw_warmed_stage_at_current_cm"),
        "model_trend_cm_h": (pkg.get("validation") or {}).get("model_trend_next_1h_cm"),
        "observed_trend_cm_h": (pkg.get("validation") or {}).get("observed_trend_last_1h_cm"),
        "peak_level_cm": (pkg.get("summary") or {}).get("peak_level_rating_cm"),
        "peak_time_utc": (pkg.get("summary") or {}).get("peak_time_utc"),
    }, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
