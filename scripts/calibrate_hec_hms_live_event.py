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
    "E19": dict(initial_loss_mm=10.0, constant_loss_mm_h=1.0, tc_h=60.0, storage_h=60.0, recession=0.9, initial_flow_multiplier=1.0),
    "E22": dict(initial_loss_mm=1.0, constant_loss_mm_h=4.0, tc_h=4.0, storage_h=90.0, recession=0.98, initial_flow_multiplier=1.0),
    "E27": dict(initial_loss_mm=2.5, constant_loss_mm_h=2.0, tc_h=10.0, storage_h=45.0, recession=0.8, initial_flow_multiplier=1.0),
    "E28": dict(initial_loss_mm=20.0, constant_loss_mm_h=2.0, tc_h=30.0, storage_h=30.0, recession=0.9, initial_flow_multiplier=1.0),
}

ENV_KEYS = {
    "initial_loss_mm": "HEC_INITIAL_LOSS_MM",
    "constant_loss_mm_h": "HEC_CONSTANT_LOSS_MM_H",
    "tc_h": "HEC_TC_H",
    "storage_h": "HEC_STORAGE_H",
    "recession": "HEC_RECESSION_DAILY",
    "initial_flow_multiplier": "HEC_INITIAL_FLOW_MULTIPLIER",
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
    fit12 = v.get("recent_hydrograph_12h") or {}
    fit6 = v.get("recent_hydrograph_6h") or {}
    stage = abs(fnum(v.get("stage_error_at_t0_cm")))
    qerr = abs(fnum(v.get("q_error_pct")))
    obs_tr = fnum(v.get("observed_trend_last_1h_cm"))
    mod_tr = fnum(v.get("model_trend_next_1h_cm"))
    trend = abs(mod_tr - obs_tr)

    rmse = fnum(fit.get("rmse_cm"))
    rmse12 = fnum(fit12.get("rmse_cm"), rmse)
    rmse6 = fnum(fit6.get("rmse_cm"), rmse12)
    lag_event = abs(fnum(fit.get("peak_time_error_h"), 24.0))
    lag12 = abs(fnum(fit12.get("peak_time_error_h"), 24.0))
    lag6 = abs(fnum(fit6.get("peak_time_error_h"), 12.0))
    nse = fnum(fit.get("nse"), -999.0)
    nse12 = fnum(fit12.get("nse"), -999.0)
    bias = abs(fnum(fit.get("bias_cm"), 0.0))
    obs_peak = fnum(fit.get("observed_peak_cm"), 1e9)
    mod_peak = fnum(fit.get("model_peak_cm_on_obs_times"), 1e9)
    peak_stage_error = abs(mod_peak - obs_peak) if obs_peak < 1e8 and mod_peak < 1e8 else 1e9

    # Two-tier objective:
    # 1) launch state + recent 6/12 h remain the operational priority;
    # 2) among candidates that can launch safely, explicitly improve the
    #    complete-event crest magnitude/timing instead of tolerating a good t0
    #    produced by a historically under-amplified hydrograph.
    score = (
        rmse12 / 80.0
        + rmse6 / 35.0
        + stage / 15.0
        + qerr / 12.0
        + trend / 5.0
        + lag12 / 12.0
        + lag6 / 4.0
        + rmse / 280.0
        + bias / 180.0
        + peak_stage_error / 100.0
        + lag_event / 8.0
    )
    if nse < -20:
        score += 3.0
    if nse12 < -5:
        score += 3.0
    metrics = {
        "score": round(score, 6),
        "event_rmse_cm": None if rmse >= 1e8 else round(rmse, 3),
        "event_nse": fit.get("nse"),
        "event_mae_cm": fit.get("mae_cm"),
        "event_bias_cm": fit.get("bias_cm"),
        "event_observed_peak_cm": fit.get("observed_peak_cm"),
        "event_model_peak_cm": fit.get("model_peak_cm_on_obs_times"),
        "event_peak_stage_error_cm": None if peak_stage_error >= 1e8 else round(mod_peak - obs_peak, 3),
        "event_peak_time_error_h": fit.get("peak_time_error_h"),
        "recent_12h_rmse_cm": fit12.get("rmse_cm"),
        "recent_12h_nse": fit12.get("nse"),
        "recent_12h_peak_time_error_h": fit12.get("peak_time_error_h"),
        "recent_6h_rmse_cm": fit6.get("rmse_cm"),
        "recent_6h_nse": fit6.get("nse"),
        "recent_6h_peak_time_error_h": fit6.get("peak_time_error_h"),
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
        "initial_flow_multiplier": min(3.0, max(0.1, round(float(p.get("initial_flow_multiplier", 1.0)), 4))),
    }


def key(p: dict) -> tuple:
    q = rounded_params(p)
    return tuple(q[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier"))


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
    # Prior live searches showed the 28/09 rising limb needs a materially
    # faster rainfall-runoff response than E19/E22, but the low-loss fast
    # candidates produced far too much volume. Search fast/moderate Clark
    # timing jointly with stronger Initial+Constant losses so timing and
    # magnitude can be reconciled instead of trading one error for the other.
    timing_pairs = [
        # Start from the response family that already reproduces the current
        # recession, then move progressively faster to correct the historical
        # crest that is still too low and several hours late.
        (30.0, 30.0), (28.0, 28.0), (26.0, 26.0), (24.0, 24.0),
        (22.0, 22.0), (20.0, 20.0), (18.0, 18.0), (16.0, 16.0),
        (28.0, 24.0), (24.0, 28.0), (26.0, 22.0), (22.0, 26.0),
        (24.0, 20.0), (20.0, 24.0), (22.0, 18.0), (18.0, 22.0),
        (20.0, 16.0), (16.0, 20.0), (15.0, 15.0), (12.0, 12.0),
        (10.0, 10.0), (8.0, 8.0),
    ]
    loss_profiles = [
        # Wet/saturated-basin candidates are essential after large recent
        # accumulations; high constant losses can suppress the second rise.
        (5.0, 0.8, 0.90),
        (10.0, 1.0, 0.90),
        (20.0, 1.5, 0.90),
        (10.0, 2.0, 0.90),
        (20.0, 2.0, 0.90),
        (20.0, 3.0, 0.90),
        (30.0, 3.0, 0.90),
        (30.0, 4.0, 0.90),
        (40.0, 4.0, 0.90),
        (50.0, 5.0, 0.90),
    ]

    candidates = []
    # Never lose the last accepted calibration while exploring a better one.
    if CAL_JSON.exists():
        try:
            prev = load(CAL_JSON)
            prev_params = prev.get("selected_parameters") or {}
            if all(k in prev_params for k in ENV_KEYS):
                candidates.append((
                    str((prev.get("selected") or {}).get("seed_event") or prev.get("seed_event") or selected_seed),
                    rounded_params(prev_params),
                    "previous_accepted_calibration",
                ))
        except Exception:
            pass

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
                    "initial_flow_multiplier": 1.0,
                }),
                f"broad_t{i:02d}_l{j:02d}",
            ))

    # Deduplicate. Keep the search operationally bounded; the focused grid
    # already covers the fast-response/high-loss combinations relevant now.
    uniq = {}
    for event, p, label in candidates:
        uniq[(event,) + key(p)] = (event, p, label)
    candidates = list(uniq.values())[:132]

    rows = []
    for event, p, label in candidates:
        try:
            rows.append(run_one(hec_sh, event, p, label))
        except Exception as exc:
            rows.append({"label": label, "seed_event": event, **p, "score": 1e9, "error": str(exc)})

    valid = [r for r in rows if fnum(r.get("score")) < 1e8]
    if not valid:
        raise RuntimeError("all coarse live-event HEC calibration candidates failed")

    # The two-zone pilot previously had one hidden constraint: initial recession
    # flow was fixed to the 26/09 observed Q. That made fast Clark candidates
    # miss t0 badly, so the optimizer preferred unrealistically slow responses.
    # Explore the HEC internal initial-flow state independently for a diverse
    # set of promising timing/shape candidates. This is a real HEC parameter
    # change, not a stage shift after simulation.
    def trend_gap(r):
        return abs(fnum(r.get("model_trend_cm_h")) - fnum(r.get("observed_trend_cm_h")))

    state_seeds = []
    for ranked in (
        sorted(valid, key=lambda r: fnum(r.get("score")))[:3],
        sorted(valid, key=trend_gap)[:3],
        sorted(valid, key=lambda r: fnum(r.get("event_rmse_cm")))[:2],
    ):
        for r in ranked:
            sig = (r.get("seed_event"),) + key(r)
            if not any((z.get("seed_event"),) + key(z) == sig for z in state_seeds):
                state_seeds.append(r)

    for sidx, r in enumerate(state_seeds, 1):
        base = {k: r[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}
        for mult in (0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.10):
            p = dict(base)
            p["initial_flow_multiplier"] = mult
            p = rounded_params(p)
            if any(key(p) == key(z) for z in rows if fnum(z.get("score")) < 1e8):
                continue
            try:
                rows.append(run_one(hec_sh, str(r.get("seed_event") or selected_seed), p, f"state_{sidx:02d}_m{mult:.2f}"))
            except Exception as exc:
                rows.append({"label": f"state_{sidx:02d}_m{mult:.2f}", "seed_event": r.get("seed_event"), **p, "score": 1e9, "error": str(exc)})

    valid = [r for r in rows if fnum(r.get("score")) < 1e8]
    preferred = [r for r in valid if bool(r.get("publishable"))]
    best = min(preferred or valid, key=lambda r: fnum(r.get("score")))
    seed_event = str(best.get("seed_event") or selected_seed)
    bp = {k: best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}

    # Fine coordinate search around coarse/state winner, plus coupled timing moves.
    fine = [rounded_params(bp)]
    perturb = {
        "initial_loss_mm": (-10.0, -5.0, 5.0, 10.0),
        "constant_loss_mm_h": (-0.75, -0.5, 0.5, 0.75),
        "tc_h": (-8.0, -6.0, -4.0, -2.0, 2.0, 4.0),
        "storage_h": (-8.0, -6.0, -4.0, -2.0, 2.0, 4.0),
        "recession": (-0.05, -0.03, 0.03, 0.05),
        "initial_flow_multiplier": (-0.25, -0.15, -0.1, 0.1, 0.15, 0.25),
    }
    for name, ds in perturb.items():
        for d in ds:
            p = dict(bp); p[name] = p[name] + d; fine.append(rounded_params(p))
    for dt, ds in ((-8,-8),(-8,-4),(-6,-6),(-6,-2),(-4,-8),(-4,-4),(-3,-1),(-1,-3),(-2,2),(2,-2),(2,2),(4,4)):
        p = dict(bp); p["tc_h"] += dt; p["storage_h"] += ds; fine.append(rounded_params(p))

    seen = {key({k:r[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}): True for r in valid}
    fine = [p for p in fine if key(p) not in seen]
    for i, p in enumerate(fine, 1):
        try:
            rows.append(run_one(hec_sh, seed_event, p, f"fine_{i:02d}"))
        except Exception as exc:
            rows.append({"label": f"fine_{i:02d}", "seed_event": seed_event, **p, "score": 1e9, "error": str(exc)})

    valid = [r for r in rows if fnum(r.get("score")) < 1e8]
    preferred = [r for r in valid if bool(r.get("publishable"))]
    best = min(preferred or valid, key=lambda r: fnum(r.get("score")))
    best_params = {k: best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}

    # Rerun the winner last so all generic files correspond to the selected calibration.
    final = run_one(hec_sh, seed_event, best_params, "selected_live_event_calibration")
    pkg = final.pop("_pkg")
    pkg["live_event_calibration"] = {
        "method": "operational_guarded_multiobjective_search_since_20260926",
        "seed_event": seed_event,
        "selected_parameters": best_params,
        "objective": "hard operational guards on t0 + recent 6h/12h; then minimize whole-event RMSE/bias and crest magnitude/timing error, with no visual stage anchoring",
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
