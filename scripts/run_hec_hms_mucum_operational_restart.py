#!/usr/bin/env python3
"""Targeted HEC-HMS operational restart for the current Muçum rising limb.

Uses:
- configured recent warm-up start (HEC_WARM_START_LOCAL);
- observed multistation rainfall during restart window;
- full-event observed accumulation since 26/09 as wetness/antecedent audit;
- current observed Muçum stage/Q and recent hydrograph for candidate selection;
- ECMWF/IFS spatial forecast after t0.

Research/operational diagnosis only; not an official alert.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import calibrate_hec_hms_live_event as cal

OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
OBS = OUT / "mucum_observed_multistation_latest.json"
RESULT_JSON = OUT / "hec_hms_operational_restart_latest.json"
CAND_CSV = OUT / "hec_hms_operational_restart_candidates.csv"
SERIES_CSV = OUT / "hec_hms_operational_restart_series.csv"


def f(v, default=1e9):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def restart_score(r: dict) -> float:
    # Current operational limb dominates. Whole-event diagnostics are retained
    # only as a weak guard because this is a state restart, not an event replay.
    return (
        f(r.get("recent_6h_rmse_cm")) / 35.0
        + f(r.get("recent_12h_rmse_cm")) / 55.0
        + abs(f(r.get("stage_error_at_t0_cm"))) / 12.0
        + abs(f(r.get("q_error_pct"))) / 12.0
        + abs(f(r.get("model_trend_cm_h")) - f(r.get("observed_trend_cm_h"))) / 3.0
        + abs(f(r.get("recent_6h_peak_time_error_h"), 12.0)) / 3.0
    )


def antecedent_audit() -> dict:
    pkg = json.loads(OBS.read_text(encoding="utf-8"))
    rain = pkg.get("rain") or {}
    rows = rain.get("hourly_areal") or []
    basin_total = sum(float(x.get("basin_mean_mm") or 0.0) for x in rows if x.get("basin_mean_mm") is not None)
    z1 = sum(float(x.get("zone_86472000_mm") or 0.0) for x in rows if x.get("zone_86472000_mm") is not None)
    z2 = sum(float(x.get("zone_02851072_mm") or 0.0) for x in rows if x.get("zone_02851072_mm") is not None)

    station_totals = []
    for st in rain.get("stations") or []:
        vals = [float(x.get("mm") or 0.0) for x in st.get("series") or [] if x.get("mm") is not None]
        if not vals:
            continue
        station_totals.append({
            "code": str(st.get("code")),
            "name": st.get("name"),
            "network": st.get("network"),
            "upg": st.get("upg"),
            "valid_hours": int(st.get("valid_hours") or len(vals)),
            "accum_mm": round(sum(vals), 3),
        })
    continuous = [x for x in station_totals if x["valid_hours"] >= 80]
    vals = sorted(x["accum_mm"] for x in continuous)
    if vals:
        med = vals[len(vals)//2]
        mean = sum(vals)/len(vals)
        rng = [min(vals), max(vals)]
        station_sum = sum(vals)
    else:
        med = mean = station_sum = None
        rng = [None, None]
    return {
        "event_window": pkg.get("event_window"),
        "basin_areal_accum_mm": round(basin_total, 3),
        "zone_86472000_accum_mm": round(z1, 3),
        "zone_02851072_accum_mm": round(z2, 3),
        "continuous_station_count": len(continuous),
        "continuous_station_mean_accum_mm": None if mean is None else round(mean, 3),
        "continuous_station_median_accum_mm": med,
        "continuous_station_range_accum_mm": rng,
        "sum_of_continuous_station_accumulations_mm_audit_only": None if station_sum is None else round(station_sum, 3),
        "station_totals": sorted(continuous, key=lambda x: x["accum_mm"], reverse=True),
        "note": "A soma entre postos é apenas auditoria de observações; o forcing físico usa chuva espacial areal/zonas, sem somar mm de postos como se fossem uma única lâmina."
    }


def write_series(pkg: dict):
    series = pkg.get("series") or {}
    times = list(series.get("time_utc") or [])
    q = list(series.get("q_mucum_m3s") or [])
    n = list(series.get("n_mucum_rating_cm") or [])
    obs = list(series.get("n_mucum_observed_cm") or [])
    with SERIES_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_utc","q_mucum_m3s","n_mucum_rating_cm","n_mucum_observed_cm"])
        for i,t in enumerate(times):
            w.writerow([
                t,
                q[i] if i < len(q) else "",
                n[i] if i < len(n) else "",
                obs[i] if i < len(obs) else "",
            ])


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_hec_hms_mucum_operational_restart.py /path/to/hec-hms.sh")
    hec_sh = sys.argv[1]

    timing_pairs = [(12.0,12.0),(14.0,14.0),(16.0,16.0),(18.0,18.0),(20.0,20.0),(14.0,16.0),(16.0,14.0)]
    loss_profiles = [(5.0,1.0),(8.0,1.0),(10.0,1.2),(12.0,1.5)]
    rows = []
    for tc,storage in timing_pairs:
        for il,cl in loss_profiles:
            p = cal.rounded_params({
                "initial_loss_mm": il,
                "constant_loss_mm_h": cl,
                "tc_h": tc,
                "storage_h": storage,
                "recession": 0.90,
                "initial_flow_multiplier": 1.0,
            })
            label = f"restart_tc{tc:g}_s{storage:g}_il{il:g}_cl{cl:g}"
            try:
                r = cal.run_one(hec_sh, "E28", p, label)
                r["restart_score"] = round(restart_score(r), 6)
                rows.append(r)
            except Exception as exc:
                rows.append({"label": label, "seed_event": "E28", **p, "restart_score": 1e9, "error": str(exc)})

    valid = [r for r in rows if f(r.get("restart_score")) < 1e8]
    if not valid:
        raise RuntimeError("all restart candidates failed")

    coarse = min(valid, key=lambda r: f(r.get("restart_score")))
    base = {k: coarse[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}

    # Refine only the internal initial-flow state around the best dynamic shape.
    for mult in (0.45,0.55,0.65,0.70,0.75,0.85,1.15):
        p = dict(base)
        p["initial_flow_multiplier"] = mult
        p = cal.rounded_params(p)
        label = f"restart_refine_m{mult:.2f}"
        try:
            r = cal.run_one(hec_sh, "E28", p, label)
            r["restart_score"] = round(restart_score(r), 6)
            rows.append(r)
        except Exception as exc:
            rows.append({"label": label, "seed_event": "E28", **p, "restart_score": 1e9, "error": str(exc)})

    valid = [r for r in rows if f(r.get("restart_score")) < 1e8]
    best = min(valid, key=lambda r: f(r.get("restart_score")))
    best_params = {k: best[k] for k in ("initial_loss_mm","constant_loss_mm_h","tc_h","storage_h","recession","initial_flow_multiplier")}

    final = cal.run_one(hec_sh, "E28", best_params, "selected_operational_restart")
    pkg = final.pop("_pkg")
    final["restart_score"] = round(restart_score(final), 6)

    pkg["operational_restart"] = {
        "method": "recent observed-state restart with saturated-basin candidate search",
        "warm_start_local": __import__("os").environ.get("HEC_WARM_START_LOCAL"),
        "selected_parameters": best_params,
        "selected_metrics": final,
        "antecedent_rain": antecedent_audit(),
        "selection_note": "Selected against recent 6h/12h observed hydrograph, current stage/Q and 1h trend; full-event accumulation is used as wetness context while the dynamic restart window reconstructs current HEC states."
    }
    pkg["generated_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    RESULT_JSON.write_text(json.dumps(pkg, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    write_series(pkg)

    clean = [{k:v for k,v in r.items() if k != "_pkg"} for r in rows]
    fields = sorted({k for r in clean for k in r})
    with CAND_CSV.open("w", encoding="utf-8", newline="") as fh:
        w=csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in clean:
            x=dict(r)
            if isinstance(x.get("blocking_reasons_pt"), list):
                x["blocking_reasons_pt"]=" | ".join(x["blocking_reasons_pt"])
            w.writerow(x)

    print(json.dumps({
        "selected_parameters": best_params,
        "selected_metrics": final,
        "antecedent_rain": pkg["operational_restart"]["antecedent_rain"],
        "result": str(RESULT_JSON.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
