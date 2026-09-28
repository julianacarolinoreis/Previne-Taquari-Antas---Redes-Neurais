#!/usr/bin/env python3
"""Postprocess the warmed HEC-HMS 4.13 Muçum forecast.

The HEC run contains a 48 h observed-rain warm-up. The latest observed river
level is retained at its real timestamp (including 15/30/45 min), not moved
back to the previous full hour. The warmed HEC state is interpolated to that
timestamp for validation only. No visual stage offset is promoted as state
assimilation or as a forecast. Until a true HEC-HMS state restart/assimilation
at t0 is implemented, this product remains diagnostic and non-publishable.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas"
RUNTIME = OUT / "hec_hms_spatial_forecast_mucum"
INPUT = RUNTIME / "forecast_input.json"
HEC_CSV = RUNTIME / "hec_output_values.csv"
CURVE = OUT / "curva_chave_86472600/curva_chave_hunt_86472600_latest.json"
RESULT = OUT / "hec_hms_spatial_forecast_mucum_latest.json"
SERIES = RUNTIME / "primary_series.csv"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iso_utc(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def q_to_stage(q_m3s: float, segments: list[dict], preferred_segment: int | None = None) -> dict:
    ordered = list(segments)
    if preferred_segment is not None:
        ordered.sort(
            key=lambda seg: 0
            if int(seg.get("segment_number") or -1) == int(preferred_segment)
            else 1
        )
    candidates = []
    for seg in ordered:
        a = float(seg["a"]); h0 = float(seg["h0_m"]); n = float(seg["n"])
        if a <= 0 or n <= 0:
            continue
        h = h0 + (max(float(q_m3s), 0.0) / a) ** (1.0 / n)
        stage_cm = h * 100.0
        lo, hi = float(seg["stage_min_cm"]), float(seg["stage_max_cm"])
        row = {
            "stage_cm": stage_cm,
            "inside": lo - 1e-6 <= stage_cm <= hi + 1e-6,
            "segment_number": seg.get("segment_number"),
            "lo": lo, "hi": hi,
        }
        candidates.append(row)
        if row["inside"] and (
            preferred_segment is None
            or int(seg.get("segment_number") or -1) == int(preferred_segment)
        ):
            return {
                "ok": True,
                "stage_cm": round(float(stage_cm), 2),
                "segment_number": seg.get("segment_number"),
                "extrapolated": False,
            }
    inside = [x for x in candidates if x["inside"]]
    if inside:
        p = inside[0]
    elif candidates:
        p = min(candidates, key=lambda x: abs(x["stage_cm"] - (x["lo"] + x["hi"]) / 2.0))
    else:
        return {"ok": False, "stage_cm": None}
    return {
        "ok": True,
        "stage_cm": round(float(p["stage_cm"]), 2),
        "segment_number": p["segment_number"],
        "extrapolated": not p["inside"],
    }


def read_hec():
    by = {}
    with HEC_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            el = row["element"]
            by.setdefault(el, []).append(
                (int(row["time_value"]), float(row["q_m3s"]), row["pathname"])
            )
    for el in by:
        by[el].sort(key=lambda x: x[0])
    return by


def choose_outlet(by):
    for key in by:
        if key.lower() == "saida_live":
            return key
    for key in by:
        if "saida_live" in key.lower():
            return key
    if not by:
        raise RuntimeError("HEC output has no FLOW series")
    return max(by, key=lambda k: len(by[k]))


def interp(times_dt, values, target):
    if not times_dt or len(times_dt) != len(values):
        raise RuntimeError("invalid interpolation arrays")
    if target <= times_dt[0]:
        return float(values[0])
    if target >= times_dt[-1]:
        return float(values[-1])
    for i in range(len(times_dt) - 1):
        a, b = times_dt[i], times_dt[i + 1]
        if a <= target <= b:
            span = (b - a).total_seconds()
            frac = 0.0 if span <= 0 else (target - a).total_seconds() / span
            return float(values[i]) + frac * (float(values[i + 1]) - float(values[i]))
    raise RuntimeError("target outside interpolation grid")


def main():
    inp = load_json(INPUT)
    by = read_hec()
    outlet = choose_outlet(by)

    run_times = list(inp["times_utc"])
    run_dt = [iso_utc(t) for t in run_times]
    qraw = [x[1] for x in by[outlet]]
    if len(qraw) < len(run_times):
        raise RuntimeError(f"HEC outlet series too short: {len(qraw)} < {len(run_times)}")
    stale_outlet_points = max(0, len(qraw) - len(run_times))
    q_full = qraw[-len(run_times):]

    curve = load_json(CURVE)
    segs = (
        ((curve.get("neighbors_official_curves_NOT_for_STZ") or {}).get("86510000") or {})
        .get("segments") or []
    )
    current = inp.get("current_state") or {}
    if not current.get("observed_at_utc"):
        raise RuntimeError("forecast input lacks exact current observed timestamp")

    preferred_segment = int(current.get("rating_segment") or 2)
    stage_meta_full = [
        q_to_stage(v, segs, preferred_segment=preferred_segment) for v in q_full
    ]
    n_full = [x["stage_cm"] for x in stage_meta_full]
    if any(v is None for v in n_full):
        raise RuntimeError("rating conversion produced missing stage")

    t0 = iso_utc(current["observed_at_utc"])
    n_obs = float(current["stage_cm"])
    q_obs = float(current["q_m3s"])
    q_model_t0 = interp(run_dt, q_full, t0)
    n_model_t0 = interp(run_dt, n_full, t0)

    # Keep the HEC-HMS output physically unshifted. The observation at t0 is
    # a validation target, not a visual anchor. A future operational product
    # must restart/assimilate the internal HEC states themselves.
    future_idx = [i for i, t in enumerate(run_dt) if t > t0]
    forecast_times = [t0.isoformat().replace("+00:00", "Z")] + [run_times[i] for i in future_idx]
    q_forecast = [q_model_t0] + [q_full[i] for i in future_idx]
    n_rating = [round(float(n_model_t0), 2)] + [round(float(n_full[i]), 2) for i in future_idx]
    observed_t0 = [round(n_obs, 2)] + [None for _ in future_idx]
    delta_from_model_t0 = [round(float(v) - float(n_model_t0), 2) for v in n_rating]

    # Compare observed 1 h trend with the unshifted warmed HEC state.
    obs_trend_1h = current.get("trend_1h_cm")
    model_n_plus_1h = interp(run_dt, n_full, t0 + timedelta(hours=1))
    model_trend_1h = float(model_n_plus_1h) - float(n_model_t0)
    state_error_cm = float(n_model_t0) - n_obs
    q_error_pct = 100.0 * (q_model_t0 - q_obs) / q_obs if q_obs else None

    reasons = []
    warm = inp.get("warmup") or {}
    if not warm.get("complete"):
        reasons.append("warm-up de chuva observada incompleto")
    if abs(state_error_cm) > 75.0:
        reasons.append(
            f"estado aquecido difere {state_error_cm:+.1f} cm do nível observado atual"
        )
    if q_error_pct is not None and abs(q_error_pct) > 40.0:
        reasons.append(
            f"vazão do estado aquecido difere {q_error_pct:+.1f}% da vazão derivada do observado"
        )
    if obs_trend_1h is not None:
        obs_trend_1h = float(obs_trend_1h)
        if obs_trend_1h >= 20.0 and model_trend_1h < -2.0:
            reasons.append(
                f"observado sobe {obs_trend_1h:.1f} cm/h, mas HEC aquecido indica queda "
                f"de {abs(model_trend_1h):.1f} cm na próxima hora"
            )
        if obs_trend_1h <= -20.0 and model_trend_1h > 2.0:
            reasons.append(
                f"observado cai {abs(obs_trend_1h):.1f} cm/h, mas HEC aquecido indica subida "
                f"de {model_trend_1h:.1f} cm na próxima hora"
            )

    # No visual anchoring is allowed. A candidate may only be published when
    # the observed-rain warm-up itself reaches a state consistent with the
    # observed t0. In that case no artificial state shift is needed.
    publishable = len(reasons) == 0
    candidate_peak_i = max(range(len(n_rating)), key=lambda i: n_rating[i])
    candidate_peak_n = n_rating[candidate_peak_i]
    candidate_peak_q = q_forecast[candidate_peak_i]
    candidate_peak_time = forecast_times[candidate_peak_i]
    candidate_rise = candidate_peak_n - n_model_t0

    node_series = {}
    for el, vals in by.items():
        full = [x[1] for x in vals[-len(run_times):]]
        if len(full) != len(run_times):
            continue
        v0 = interp(run_dt, full, t0)
        vf = [v0] + [full[i] for i in future_idx]
        node_series[el] = {
            "q_m3s": [round(float(x), 3) for x in vf],
            "q_at_observed_time_m3s": round(float(v0), 3),
            "peak_q_m3s": round(max(vf), 3),
            "peak_time_utc": forecast_times[max(range(len(vf)), key=lambda i: vf[i])],
        }

    status = (
        "hec_hms_4_13_spatial_ifs_warmup_ready"
        if publishable
        else "hec_hms_4_13_blocked_inconsistent_state"
    )
    result = {
        "schema_version": "hec_hms_spatial_forecast_mucum_v2_warmup",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "publishable": publishable,
        "model": "HEC-HMS 4.13",
        "mode": "two_zone_spatial_forecast_with_48h_observed_rain_warmup",
        "research_only": True,
        "not_official_alert": True,
        "rain": {
            "source": inp.get("rain_source"),
            "all_spatial_cells_used": inp.get("all_spatial_cells_used"),
            "spatial_cells": inp.get("spatial_cells"),
            "zones": inp.get("zones"),
            "basin_equivalent_forecast_mm_for_audit": inp.get(
                "basin_equivalent_forecast_mm_for_audit"
            ),
        },
        "warmup": inp.get("warmup"),
        "initial_state": inp.get("initial_state"),
        "current_state": current,
        "parameter_source": inp.get("parameter_source"),
        "times_utc": forecast_times,
        "series": {
            "q_mucum_m3s": [round(float(v), 3) for v in q_forecast],
            "n_mucum_rating_cm": n_rating,
            "n_mucum_observed_t0_cm": observed_t0,
            "delta_n_from_model_t0_cm": delta_from_model_t0,
        },
        "validation": {
            "publishable": publishable,
            "blocking_reasons_pt": reasons,
            "raw_warmed_stage_at_current_cm": round(n_model_t0, 2),
            "stage_error_at_t0_cm": round(state_error_cm, 2),
            "raw_warmed_q_at_current_m3s": round(q_model_t0, 3),
            "observed_rating_q_at_current_m3s": round(q_obs, 3),
            "q_error_pct": None if q_error_pct is None else round(q_error_pct, 2),
            "observed_trend_last_1h_cm": None if obs_trend_1h is None else round(obs_trend_1h, 2),
            "model_trend_next_1h_cm": round(model_trend_1h, 2),
            "state_assimilation_applied": False,
            "visual_stage_anchor_applied": False,
            "warmup_state_matches_observation": publishable,
            "forecast_validation_timestamp_is_exact_observation_time": True,
        },
        "summary": {
            "q_now_observed_rating_m3s": round(q_obs, 3),
            "q_model_at_observed_time_m3s": round(q_model_t0, 3),
            "q_current_error_pct": None if q_error_pct is None else round(q_error_pct, 3),
            "level_now_observed_cm": round(n_obs, 2),
            "observed_at_utc": current.get("observed_at_utc"),
            "observed_trend_1h_cm": None if obs_trend_1h is None else round(obs_trend_1h, 2),
            "model_trend_next_1h_cm": round(model_trend_1h, 2),
            "publishable": publishable,
            "blocking_reasons_pt": reasons,
            "peak_q_m3s": round(candidate_peak_q, 3) if publishable else None,
            "peak_time_utc": candidate_peak_time if publishable else None,
            "peak_level_rating_cm": round(candidate_peak_n, 2) if publishable else None,
            "rise_from_model_t0_cm": round(candidate_rise, 2) if publishable else None,
            "candidate_peak_q_m3s": round(candidate_peak_q, 3),
            "candidate_peak_time_utc": candidate_peak_time,
            "candidate_peak_level_rating_cm": round(candidate_peak_n, 2),
            "candidate_rise_from_model_t0_cm": round(candidate_rise, 2),
            "stale_outlet_points_discarded": stale_outlet_points,
        },
        "nodes": node_series,
        "hec_output": {
            "outlet_element": outlet,
            "flow_elements": sorted(by),
            "n_flow_paths": len(by),
        },
        "warning_pt": (
            "HEC-HMS 4.13 com 48 h de chuva observada para aquecimento e ECMWF/IFS "
            "espacial no futuro. O último nível de Muçum é usado no timestamp real para validar "
            "o estado aquecido; nenhuma correção visual de nível é aplicada. A rodada só é "
            "publicável quando o próprio aquecimento observado fecha com o estado atual dentro "
            "das guardas de nível, vazão e tendência. Continua sendo o piloto de duas zonas, "
            "não alerta oficial."
        ),
        "artifacts": {
            "input": str(INPUT.relative_to(ROOT)),
            "series_csv": str(SERIES.relative_to(ROOT)),
            "runtime_dir": str(RUNTIME.relative_to(ROOT)),
        },
    }
    RESULT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with SERIES.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "time_utc", "q_mucum_m3s", "n_mucum_rating_cm",
            "n_mucum_observed_t0_cm", "delta_n_from_model_t0_cm", "publishable"
        ])
        for i, t in enumerate(forecast_times):
            w.writerow([
                t, round(q_forecast[i], 3), n_rating[i],
                observed_t0[i], delta_from_model_t0[i], publishable
            ])

    print(json.dumps({
        "status": status,
        "publishable": publishable,
        "observed_stage_cm": n_obs,
        "observed_at_utc": current.get("observed_at_utc"),
        "observed_trend_1h_cm": obs_trend_1h,
        "model_trend_next_1h_cm": round(model_trend_1h, 2),
        "state_error_at_t0_cm": round(state_error_cm, 2),
        "q_error_pct": None if q_error_pct is None else round(q_error_pct, 2),
        "candidate_peak_level_cm": round(candidate_peak_n, 2),
        "blocking_reasons": reasons,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
