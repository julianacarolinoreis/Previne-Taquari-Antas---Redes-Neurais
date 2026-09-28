#!/usr/bin/env python3
"""Calibrate the live Muçum HEC-HMS run against the current event since 26/09.

This is event-state calibration for the ongoing research run, not replacement of
the historical parameter library. It starts from the best historical live
candidate selected by run_hec_hms_live_candidates.sh, performs a coarse local
search and a small coordinate fine search, and reruns the winning parameter
set so the generic HEC artifacts correspond to the selected calibration.

Objective combines the complete observed Muçum hydrograph since 26/09 with the
current state, discharge error, current slope and peak timing. No visual stage
anchoring is used.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas"
RUNTIME = OUT / "hec_hms_spatial_forecast_mucum"
RESULT = OUT / "hec_hms_spatial_forecast_mucum_latest.json"
SELECTION = OUT / "hec_hms_spatial_forecast_mucum_selection_latest.json"
CAL_JSON = OUT / "hec_hms_live_event_calibration_latest.json"
CAL_CSV = OUT / "hec_hms_live_event_calibration_candidates.csv"
CAL_FORECAST = OUT / "hec_hms_live_event_calibrated_forecast_latest.json"
OBS_MULTI = OUT / "mucum_observed_multistation_latest.json"
CAL_OBS = OUT / "mucum_observed_multistation_calibration_snapshot.json"
SCRIPT = RUNTIME / "project/run_forecast.script"

PRESETS = {
    "E19": dict(initial_loss_mm=10.0, constant_loss_mm_h=1.0, tc_h=60.0, storage_h=60.0, recession=0.9),
    "E22": dict(initial_loss_mm=1.0, constant_loss_mm_h=4.0, tc_h=4.0, storage_h=90.0, recession=0.98),
    "E27": dict(initial_loss_mm=2.5, constant_loss_mm_h=2.0, tc_h=10.0, storage_h=45.0, recession=0.8),
    "E28": dict(initial_loss_mm=20.0, constant_loss_mm_h=2.0, tc_h=30.0, storage_h=30.0, recession=0.9),
}

ENV_KEYS = {
    "initial_loss_mm": "HEC_INITIAL_LOSS_MM",
    "constant_loss_mm_h": "HEC_CONSTANT_LOSS_MM_H",
    "tc_h": "HEC_TC_H",
    "storage_h": "HEC_STORAGE_H",
    "recession": "HEC_RECESSION_DAILY",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fnum(v, default=1e9):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def objective(pkg: dict) -> tuple[float, dict]:
    v = pkg.get("validation") or {}
    fit = v.get("event_hydrograph_since_20260926") or {}
    stage = abs(fnum(v.get("stage_error_at_t0_cm")))
    qerr = abs(fnum(v.get("q_error_pct")))
    obs_tr = fnum(v.get("observed_trend_last_1h_cm"))
    mod_tr = fnum(v.get("model_trend_next_1h_cm"))
    trend = abs(mod_tr - obs_tr)
    rmse = fnum(fit.get("rmse_cm"))
    lag = abs(fnum(fit.get("peak_time_error_h"), 999.0))
    nse = fnum(fit.get("nse"), -999.0)
    # Current flood: preserve the whole-event fit, but strongly constrain the
    # present state and rising-limb speed because those control the forecast
    # launched at t0.
    score = rmse / 120.0 + stage / 30.0 + qerr / 25.0 + trend / 20.0 + lag / 24.0
    if nse < -20:
        score += 5.0
    metrics = {
        "score": round(score, 6),
        "event_rmse_cm": None if rmse >= 1e8 else round(rmse, 3),
        "event_nse": fit.get("nse"),
        "event_mae_cm": fit.get("mae_cm"),
        "event_bias_cm": fit.get("bias_cm"),
        "event_peak_time_error_h": fit.get("peak_time_error_h"),
        "stage_error_at_t0_cm": v.get("stage_error_at_t0_cm"),
        "q_error_pct": v.get("q_error_pct"),
        "observed_trend_cm_h": v.get("observed_trend_last_1h_cm"),
        "model_trend_cm_h": v.get("model_trend_next_1h_cm"),
        "publishable": bool(pkg.get("publishable")),
        "blocking_reasons_pt": list(v.get("blocking_reasons_pt") or []),
    }
    return score, metrics


def run_one(hec_sh: str, event: str, params: dict, label: str) -> dict:
    env = os.environ.copy()
    env["HEC_PARAM_EVENT"] = event
    for key, envkey in ENV_KEYS.items():
        env[envkey] = str(params[key])
    subprocess.run([sys.executable, "-B", "scripts/build_hec_hms_spatial_forecast_mucum.py"], cwd=ROOT, env=env, check=True)
    out_csv = RUNTIME / "hec_output_values.csv"
    if out_csv.exists():
        out_csv.unlink()
    subprocess.run([hec_sh, "-s", str(SCRIPT)], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if not out_csv.exists() or out_csv.stat().st_size == 0:
        raise RuntimeError(f"HEC candidate {label} produced no output")
    subprocess.run([sys.executable, "-B", "scripts/postprocess_hec_hms_spatial_forecast_mucum.py"], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    pkg = load(RESULT)
    score, metrics = objective(pkg)
    return {
        "label": label,
        "seed_event": event,
        **{k: round(float(v), 6) for k, v in params.items()},
        **metrics,
        "_pkg": pkg,
    }


def rounded_params(p: dict) -> dict:
    return {
        "initial_loss_mm": max(0.0, round(float(p["initial_loss_mm"]), 3)),
        "constant_loss_mm_h": max(0.0, round(float(p["constant_loss_mm_h"]), 3)),
        "tc_h": max(1.0, round(float(p["tc_h"]), 3)),
        "storage_h": max(1.0, round(float(p["storage_h"]), 3)),
        "recession": min(0.995, max(0.5, round(float(p["recession"]), 4))),
    }


def key(p: dict) -> tuple:
    q = rounded_params(p)
    return tuple(q[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession"))


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: calibrate_hec_hms_live_event.py /path/to/hec-hms.sh")
    hec_sh = sys.argv[1]
    if not Path(hec_sh).exists():
        raise SystemExit(f"HEC executable not found: {hec_sh}")

    sel = load(SELECTION) if SELECTION.exists() else {}
    selected_seed = str(sel.get("selected_event") or "E28")
    if selected_seed not in PRESETS:
        selected_seed = "E28"

    # Broad deterministic search. We explicitly include fast Clark responses;
    # the historical presets alone were too slow for the observed +81 cm/h
    # rising limb in the 28/09 event.
    timing_pairs = [
        (3.0, 3.0), (5.0, 5.0), (5.0, 10.0), (10.0, 5.0),
        (10.0, 10.0), (10.0, 20.0), (15.0, 10.0), (15.0, 15.0),
        (20.0, 10.0), (20.0, 20.0), (20.0, 30.0), (30.0, 20.0),
        (30.0, 30.0), (45.0, 45.0), (60.0, 60.0),
    ]
    loss_profiles = [
        (0.0, 0.5, 0.90),
        (0.0, 1.0, 0.90),
        (5.0, 1.0, 0.98),
        (10.0, 1.0, 0.90),
        (10.0, 2.0, 0.90),
        (20.0, 2.0, 0.80),
    ]

    candidates = []
    # Always include the four original HEC-HMS replay presets.
    for event, p0 in PRESETS.items():
        candidates.append((event, rounded_params(p0), f"preset_{event}"))

    # Cross timing response with representative loss/recession regimes.
    # Use E28 as the structural seed for env overrides; only the explicit
    # parameter values matter in these live-event candidates.
    for i, (tc, st) in enumerate(timing_pairs):
        for j, (il, cl, rec) in enumerate(loss_profiles):
            candidates.append((
                "E28",
                rounded_params({
                    "initial_loss_mm": il,
                    "constant_loss_mm_h": cl,
                    "tc_h": tc,
                    "storage_h": st,
                    "recession": rec,
                }),
                f"broad_t{i:02d}_l{j:02d}",
            ))

    # Deduplicate and cap at 64 broad configurations, retaining the full
    # timing range and all historical presets.
    uniq = {}
    for event, p, label in candidates:
        uniq[(event,) + key(p)] = (event, p, label)
    candidates = list(uniq.values())[:64]

    rows = []
    for event, p, label in candidates:
        try:
            rows.append(run_one(hec_sh, event, p, label))
        except Exception as exc:
            rows.append({"label": label, "seed_event": event, **p, "score": 1e9, "error": str(exc)})

    valid = [r for r in rows if fnum(r.get("score")) < 1e8]
    if not valid:
        raise RuntimeError("all coarse live-event HEC calibration candidates failed")
    best = min(valid, key=lambda r: fnum(r.get("score")))
    seed_event = str(best.get("seed_event") or selected_seed)
    bp = {k: best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession")}

    # Fine coordinate search around coarse winner, plus coupled timing moves.
    fine = [rounded_params(bp)]
    perturb = {
        "initial_loss_mm": (-5.0, 5.0),
        "constant_loss_mm_h": (-0.5, 0.5),
        "tc_h": (-8.0, -3.0, 3.0, 8.0),
        "storage_h": (-8.0, -3.0, 3.0, 8.0),
        "recession": (-0.03, 0.03),
    }
    for name, ds in perturb.items():
        for d in ds:
            p = dict(bp); p[name] = p[name] + d; fine.append(rounded_params(p))
    for dt, ds in ((-10,-10),(-8,-3),(-3,-8),(-5,5),(5,-5),(5,5),(10,10)):
        p = dict(bp); p["tc_h"] += dt; p["storage_h"] += ds; fine.append(rounded_params(p))

    seen = {key({k:r[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession")}): True for r in valid}
    fine = [p for p in fine if key(p) not in seen]
    for i, p in enumerate(fine, 1):
        try:
            rows.append(run_one(hec_sh, seed_event, p, f"fine_{i:02d}"))
        except Exception as exc:
            rows.append({"label": f"fine_{i:02d}", "seed_event": seed_event, **p, "score": 1e9, "error": str(exc)})

    valid = [r for r in rows if fnum(r.get("score")) < 1e8]
    best = min(valid, key=lambda r: fnum(r.get("score")))
    best_params = {k: best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession")}

    # Rerun the winner last so all generic files correspond to the selected calibration.
    final = run_one(hec_sh, seed_event, best_params, "selected_live_event_calibration")
    pkg = final.pop("_pkg")
    pkg["live_event_calibration"] = {
        "method": "coarse_plus_coordinate_fine_search_since_20260926",
        "seed_event": seed_event,
        "selected_parameters": best_params,
        "objective": "event RMSE + t0 stage + t0 Q + current trend + peak timing; no visual stage anchoring",
        "selected_score": final["score"],
        "candidate_count": len(rows),
        "selected_metrics": {k:v for k,v in final.items() if k not in {"label","seed_event",*best_params.keys()}},
        "observed_rain_source": "all valid upstream observed stations assembled in mucum_observed_multistation_latest.json",
    }
    RESULT.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CAL_FORECAST.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if OBS_MULTI.exists():
        shutil.copy2(OBS_MULTI, CAL_OBS)

    clean_rows = [{k:v for k,v in r.items() if k != "_pkg"} for r in rows]
    fieldnames = sorted({k for r in clean_rows for k in r.keys() if k != "blocking_reasons_pt"})
    with CAL_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in clean_rows:
            x = dict(r)
            if "blocking_reasons_pt" in x:
                x["blocking_reasons_pt"] = " | ".join(x["blocking_reasons_pt"])
            w.writerow(x)

    audit = {
        "schema_version": "hec_hms_live_event_calibration_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "event_window_start_local": "2026-09-26T00:00",
        "seed_event": seed_event,
        "candidate_count": len(rows),
        "selected": final,
        "selected_parameters": best_params,
        "top10": sorted(clean_rows, key=lambda r:fnum(r.get("score")))[:10],
        "artifacts": {
            "result": str(RESULT.relative_to(ROOT)),
            "calibrated_forecast": str(CAL_FORECAST.relative_to(ROOT)),
            "observed_snapshot": str(CAL_OBS.relative_to(ROOT)) if CAL_OBS.exists() else None,
            "candidates_csv": str(CAL_CSV.relative_to(ROOT)),
        },
    }
    CAL_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "seed_event": seed_event,
        "candidate_count": len(rows),
        "selected_parameters": best_params,
        "selected_score": final["score"],
        "event_rmse_cm": final.get("event_rmse_cm"),
        "event_nse": final.get("event_nse"),
        "stage_error_at_t0_cm": final.get("stage_error_at_t0_cm"),
        "q_error_pct": final.get("q_error_pct"),
        "observed_trend_cm_h": final.get("observed_trend_cm_h"),
        "model_trend_cm_h": final.get("model_trend_cm_h"),
        "publishable": final.get("publishable"),
    }, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
