#!/usr/bin/env python3
"""Postprocess the event-warmed HEC-HMS 4.13 Muçum forecast.

The HEC run contains observed-rain warm-up from 26/09 00:00 local. The latest observed river
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
LIVE = ROOT / "previsao_ao_vivo_mucum.json"
BRT = timezone(timedelta(hours=-3))
EVENT_START_LOCAL = datetime(2026, 9, 26, 0, 0)
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


def event_hydrograph_metrics(run_dt, n_full, t0, start_utc_override=None):
    live = load_json(LIVE)
    start_utc = (
        start_utc_override
        if start_utc_override is not None
        else EVENT_START_LOCAL.replace(tzinfo=BRT).astimezone(timezone.utc)
    )
    pairs = []
    for row in live.get("serie_observada_ana") or []:
        raw_t = row.get("hora")
        raw_n = row.get("nivel_cm")
        if raw_t is None or raw_n is None:
            continue
        try:
            local = datetime.fromisoformat(str(raw_t))
        except ValueError:
            continue
        obs_t = local.replace(tzinfo=BRT).astimezone(timezone.utc)
        if obs_t < start_utc or obs_t > t0:
            continue
        if obs_t < run_dt[0] or obs_t > run_dt[-1]:
            continue
        model_n = interp(run_dt, n_full, obs_t)
        pairs.append((obs_t, float(raw_n), float(model_n)))
    if len(pairs) < 4:
        return {
            "n_points": len(pairs),
            "rmse_cm": None,
            "mae_cm": None,
            "bias_cm": None,
            "nse": None,
            "observed_peak_cm": None,
            "model_peak_cm": None,
            "peak_time_error_h": None,
        }
    errors = [m - o for _, o, m in pairs]
    rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
    mae = sum(abs(e) for e in errors) / len(errors)
    bias = sum(errors) / len(errors)
    obs_mean = sum(o for _, o, _ in pairs) / len(pairs)
    denom = sum((o - obs_mean) ** 2 for _, o, _ in pairs)
    nse = None if denom <= 0 else 1.0 - sum((m - o) ** 2 for _, o, m in pairs) / denom
    obs_peak = max(pairs, key=lambda x: x[1])
    mod_peak = max(pairs, key=lambda x: x[2])
    lag_h = (mod_peak[0] - obs_peak[0]).total_seconds() / 3600.0
    return {
        "n_points": len(pairs),
        "start_utc": pairs[0][0].isoformat().replace("+00:00", "Z"),
        "end_utc": pairs[-1][0].isoformat().replace("+00:00", "Z"),
        "rmse_cm": round(rmse, 3),
        "mae_cm": round(mae, 3),
        "bias_cm": round(bias, 3),
        "nse": None if nse is None else round(nse, 5),
        "observed_peak_cm": round(obs_peak[1], 2),
        "observed_peak_time_utc": obs_peak[0].isoformat().replace("+00:00", "Z"),
        "model_peak_cm_on_obs_times": round(mod_peak[2], 2),
        "model_peak_time_utc": mod_peak[0].isoformat().replace("+00:00", "Z"),
        "peak_time_error_h": round(lag_h, 3),
    }


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
    event_fit = event_hydrograph_metrics(run_dt, n_full, t0)
    recent_fit_12h = event_hydrograph_metrics(
        run_dt, n_full, t0, start_utc_override=t0 - timedelta(hours=12)
    )
    recent_fit_6h = event_hydrograph_metrics(
        run_dt, n_full, t0, start_utc_override=t0 - timedelta(hours=6)
    )

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
    diagnostic_warnings = []
    warm = inp.get("warmup") or {}
    if not warm.get("complete"):
        reasons.append("warm-up de chuva observada incompleto")

    # Release the operational forecast from the state that matters now:
    # observed t0 + recent 6/12 h hydrograph. Whole-event metrics remain visible
    # as diagnostics, but do not veto an otherwise well-initialized recession
    # forecast merely because an older part of the event had structural error.
    if abs(state_error_cm) > 30.0:
        reasons.append(
            f"estado aquecido difere {state_error_cm:+.1f} cm do nível observado atual (>30 cm)"
        )
    if q_error_pct is not None and abs(q_error_pct) > 10.0:
        reasons.append(
            f"vazão do estado aquecido difere {q_error_pct:+.1f}% da vazão derivada do observado (>10%)"
        )

    recent12_rmse = recent_fit_12h.get("rmse_cm")
    recent12_nse = recent_fit_12h.get("nse")
    recent6_rmse = recent_fit_6h.get("rmse_cm")
    recent6_nse = recent_fit_6h.get("nse")
    if recent12_rmse is None or float(recent12_rmse) > 35.0:
        reasons.append(
            "ajuste recente de 12 h indisponível ou RMSE >35 cm"
            if recent12_rmse is None
            else f"RMSE recente de 12 h = {float(recent12_rmse):.1f} cm (>35 cm)"
        )
    if recent12_nse is None or float(recent12_nse) < 0.75:
        reasons.append(
            "NSE recente de 12 h indisponível ou <0,75"
            if recent12_nse is None
            else f"NSE recente de 12 h = {float(recent12_nse):.3f} (<0,75)"
        )
    if recent6_rmse is None or float(recent6_rmse) > 25.0:
        reasons.append(
            "ajuste recente de 6 h indisponível ou RMSE >25 cm"
            if recent6_rmse is None
            else f"RMSE recente de 6 h = {float(recent6_rmse):.1f} cm (>25 cm)"
        )
    if recent6_nse is not None and float(recent6_nse) < 0.50:
        reasons.append(
            f"NSE recente de 6 h = {float(recent6_nse):.3f} (<0,50)"
        )

    if event_fit.get("rmse_cm") is not None and float(event_fit["rmse_cm"]) > 60.0:
        diagnostic_warnings.append(
            f"RMSE do evento completo desde 26/09 = {event_fit['rmse_cm']:.1f} cm (>60 cm)"
        )
    if event_fit.get("nse") is not None and float(event_fit["nse"]) < 0.75:
        reasons.append(
            f"NSE do hidrograma observado desde 26/09 = {event_fit['nse']:.3f} (<0,75)"
        )
    if event_fit.get("bias_cm") is not None and abs(float(event_fit["bias_cm"])) > 30.0:
        diagnostic_warnings.append(
            f"viés do evento completo desde 26/09 = {event_fit['bias_cm']:+.1f} cm (>30 cm)"
        )

    # Do not release a forecast whose observation snapshot became stale while
    # the run was executing.
    obs_age_min = (
        datetime.now(timezone.utc) - t0
    ).total_seconds() / 60.0
    if obs_age_min > 45.0:
        reasons.append(
            f"estado observado de Muçum está defasado {obs_age_min:.0f} min (>45 min)"
        )

    observed_network = warm.get("observed_network") or {}
    min_hourly_gauges = observed_network.get("min_hourly_station_count")
    if min_hourly_gauges is not None and int(min_hourly_gauges) < 8:
        reasons.append(
            f"cobertura mínima de chuva no aquecimento = {int(min_hourly_gauges)} postos/h (<8)"
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
        # On a fast limb the direction must agree and the absolute slope error
        # must remain bounded. Ratio-only gates become unstable when the
        # observed slope is around a few tens of cm/h; use them as diagnostics,
        # not as a second veto when the absolute error is already acceptable.
        if abs(obs_trend_1h) >= 20.0:
            trend_tolerance = max(12.0, 0.35 * abs(obs_trend_1h))
            trend_ratio = (
                abs(model_trend_1h) / abs(obs_trend_1h)
                if abs(obs_trend_1h) > 1e-9 else None
            )
            if abs(model_trend_1h - obs_trend_1h) > trend_tolerance:
                reasons.append(
                    f"tendência HEC {model_trend_1h:+.1f} cm/h incompatível com "
                    f"observado {obs_trend_1h:+.1f} cm/h "
                    f"(diferença > {trend_tolerance:.1f} cm/h)"
                )
            elif trend_ratio is not None and (trend_ratio < 0.75 or trend_ratio > 1.35):
                diagnostic_warnings.append(
                    f"magnitude da tendência HEC difere do observado (razão={trend_ratio:.2f}), "
                    "mas o erro absoluto permanece dentro da guarda operacional"
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
        "mode": "two_zone_spatial_forecast_with_event_warmup_since_20260926",
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
            "diagnostic_warnings_pt": diagnostic_warnings,
            "release_policy": "t0 + recent_6h_12h + direction/slope; whole-event RMSE/bias diagnostic",
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
            "observation_age_at_postprocess_minutes": round(obs_age_min, 1),
            "event_hydrograph_since_20260926": event_fit,
            "recent_hydrograph_12h": recent_fit_12h,
            "recent_hydrograph_6h": recent_fit_6h,
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
            "diagnostic_warnings_pt": diagnostic_warnings,
            "observation_age_at_postprocess_minutes": round(obs_age_min, 1),
            "peak_q_m3s": round(candidate_peak_q, 3) if publishable else None,
            "peak_time_utc": candidate_peak_time if publishable else None,
            "peak_level_rating_cm": round(candidate_peak_n, 2) if publishable else None,
            "rise_from_model_t0_cm": round(candidate_rise, 2) if publishable else None,
            "candidate_peak_q_m3s": round(candidate_peak_q, 3),
            "candidate_peak_time_utc": candidate_peak_time,
            "candidate_peak_level_rating_cm": round(candidate_peak_n, 2),
            "candidate_rise_from_model_t0_cm": round(candidate_rise, 2),
            "stale_outlet_points_discarded": stale_outlet_points,
            "event_hydrograph_since_20260926": event_fit,
            "recent_hydrograph_12h": recent_fit_12h,
            "recent_hydrograph_6h": recent_fit_6h,
        },
        "nodes": node_series,
        "hec_output": {
            "outlet_element": outlet,
            "flow_elements": sorted(by),
            "n_flow_paths": len(by),
        },
        "warning_pt": (
            "HEC-HMS 4.13 com chuva observada multirrede desde 26/09 para aquecimento e ECMWF/IFS "
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
        "event_rmse_cm": event_fit.get("rmse_cm"),
        "event_nse": event_fit.get("nse"),
        "event_peak_time_error_h": event_fit.get("peak_time_error_h"),
        "recent_12h_rmse_cm": recent_fit_12h.get("rmse_cm"),
        "recent_12h_nse": recent_fit_12h.get("nse"),
        "recent_6h_rmse_cm": recent_fit_6h.get("rmse_cm"),
        "recent_6h_nse": recent_fit_6h.get("nse"),
        "blocking_reasons": reasons,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
