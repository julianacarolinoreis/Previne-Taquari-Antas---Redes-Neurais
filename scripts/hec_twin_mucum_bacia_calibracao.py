#!/usr/bin/env python3
"""Basin calibration helpers for Muçum HEC twin transfer (~5d quanto sobe).

Improves eventwise param transfer without touching RNA and without inventing STZ N.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from hec_twin_nested_v17 import NestedParams

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
MODELO = OUT / "modelo_mucum_eventwise_v1_fechado_latest.json"
HEC = OUT / "hec_twin_stz_mucum_v1_latest.json"
BACIA = OUT / "modelo_mucum_bacia_calibrado_v1_latest.json"

SUBBASINS = [
    "SB_PRATA_7868",
    "SB_ANTAS_RESIDUAL",
    "SB_CARREIRO_7866",
    "SB_STZ_RESIDUAL",
    "SB_INC_MUCUM",
]

REGIME_LIGHT_MAX_MM = 80.0
REGIME_HEAVY_MIN_MM = 160.0
LIGHT_SPECIALIST_EVENTS = ("E30",)


def area_weighted_total_mm(precip: dict[str, list[float]], areas: dict[str, float]) -> float:
    total_area = sum(areas[sb] for sb in precip if sb in areas)
    if total_area <= 0:
        return float("nan")
    acc = 0.0
    for sb, series in precip.items():
        if sb not in areas:
            continue
        acc += sum(series) * areas[sb]
    return acc / total_area


def station_core_mean_mm(hec_event: dict[str, Any]) -> float:
    rain = hec_event.get("rain") or {}
    core = rain.get("stations_mm_sum_core") or rain.get("stations_mm_sum") or {}
    if not core:
        return float("nan")
    return float(sum(core.values()) / len(core))


def classify_regime(aw_full_mm: float) -> str:
    if aw_full_mm != aw_full_mm:
        return "unknown"
    if aw_full_mm < REGIME_LIGHT_MAX_MM:
        return "light"
    if aw_full_mm >= REGIME_HEAVY_MIN_MM:
        return "heavy"
    return "moderate"


def loss_sum_mm(row: dict[str, Any]) -> float:
    p = row.get("params") or {}
    up = p.get("upstream") or {}
    dn = p.get("downstream") or {}
    return (
        float(up.get("initial_loss") or 0.0)
        + float(up.get("constant_loss") or 0.0)
        + float(dn.get("initial_loss") or 0.0)
        + float(dn.get("constant_loss") or 0.0)
    )


def build_event_fingerprints(
    hec_events: list[dict[str, Any]],
    areas: dict[str, float],
    *,
    prepare_event_forcing: Callable[..., tuple],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ev in hec_events:
        eid = ev["event_id"]
        pad = int(ev.get("pad_hours_selected") or 0)
        precip, _meta, _hours, flow, _fa, core_offset, core_hours = prepare_event_forcing(
            eid, SUBBASINS, pad
        )
        if precip is None:
            out[eid] = {
                "event_id": eid,
                "status": "blocked_rain",
                "aw_full_mm": None,
                "aw_core_mm": None,
                "station_core_mean_mm": station_core_mean_mm(ev),
                "regime": "unknown",
            }
            continue
        aw_full = area_weighted_total_mm(precip, areas)
        core_precip = {
            sb: series[core_offset : core_offset + len(core_hours)] for sb, series in precip.items()
        }
        aw_core = area_weighted_total_mm(core_precip, areas) if core_hours else float("nan")
        obs_core = [float(flow[h]) for h in core_hours if h in flow]
        peak_q = max(obs_core) if obs_core else float("nan")
        q0 = obs_core[0] if obs_core else float("nan")
        efficiency = (
            peak_q / aw_full if aw_full == aw_full and aw_full > 1e-6 and peak_q == peak_q else float("nan")
        )
        out[eid] = {
            "event_id": eid,
            "status": "ok",
            "pad_hours": pad,
            "aw_full_mm": round(aw_full, 3),
            "aw_core_mm": round(aw_core, 3) if aw_core == aw_core else None,
            "station_core_mean_mm": round(station_core_mean_mm(ev), 3),
            "peak_obs_q_m3s": round(peak_q, 2) if peak_q == peak_q else None,
            "q0_obs_m3s": round(q0, 2) if q0 == q0 else None,
            "peak_per_mm": round(efficiency, 3) if efficiency == efficiency else None,
            "regime": classify_regime(aw_full),
        }
    return out


def expand_library_with_light_specialists(
    core_library: list[dict[str, Any]],
    hec_events: list[dict[str, Any]],
    forecast_aw_mm: float,
) -> list[dict[str, Any]]:
    pool = list(core_library)
    if forecast_aw_mm >= REGIME_LIGHT_MAX_MM:
        return pool
    have = {r["event_id"] for r in pool}
    hec_by_id = {e["event_id"]: e for e in hec_events}
    for eid in LIGHT_SPECIALIST_EVENTS:
        if eid in have:
            continue
        ev = hec_by_id.get(eid)
        if not ev or not ev.get("params"):
            continue
        metrics = ev.get("metrics") or {}
        pool.append(
            {
                "event_id": eid,
                "nse": metrics.get("nse"),
                "research_score": metrics.get("nse"),
                "params": ev["params"],
                "pad_hours_selected": ev.get("pad_hours_selected"),
                "source": "marginal_light_specialist",
                "metrics": metrics,
            }
        )
    return pool


def analog_distance(
    forecast_aw_mm: float,
    hist_aw_mm: float,
    row: dict[str, Any],
    fp: dict[str, Any] | None,
) -> tuple[float, dict[str, Any]]:
    scale = max(forecast_aw_mm, hist_aw_mm, 25.0)
    rain_gap = abs(hist_aw_mm - forecast_aw_mm) / scale

    is_light = forecast_aw_mm < REGIME_LIGHT_MAX_MM
    is_specialist = row.get("source") == "marginal_light_specialist" or row["event_id"] in LIGHT_SPECIALIST_EVENTS

    # Efficiency: high peak/mm donors overstate light QPF rises.
    eff_gap = 0.0
    hist_eff = (fp or {}).get("peak_per_mm")
    if is_light and hist_eff is not None and hist_eff == hist_eff:
        if float(hist_eff) > 70.0:
            eff_gap = 0.85
        elif float(hist_eff) > 45.0:
            eff_gap = 0.45

    loss = loss_sum_mm(row)
    p = row.get("params") or {}
    up = p.get("upstream") or {}
    dn = p.get("downstream") or {}
    const_loss = float(up.get("constant_loss") or 0.0) + float(dn.get("constant_loss") or 0.0)

    loss_penalty = 0.0
    if is_light and not is_specialist:
        if const_loss < 0.5:
            loss_penalty += 1.1  # zero continuous loss tends to over-run light storms
        if loss < 0.75:
            loss_penalty += 0.4
        elif loss < 2.0:
            loss_penalty += 0.2

    donor_penalty = 0.0
    if row["event_id"] == "E25" and forecast_aw_mm > 60.0:
        donor_penalty += 0.8
    # Prefer same regime when fingerprints exist
    hist_regime = (fp or {}).get("regime") or classify_regime(hist_aw_mm)
    if hist_regime != classify_regime(forecast_aw_mm):
        donor_penalty += 0.25

    nse = row.get("nse")
    nse_term = 0.0 if nse is None else max(0.0, 0.15 * (1.0 - float(nse)))

    distance = rain_gap + eff_gap + loss_penalty + donor_penalty + nse_term
    detail = {
        "rain_gap": round(rain_gap, 4),
        "eff_gap": round(eff_gap, 4),
        "loss_penalty": round(loss_penalty, 4),
        "donor_penalty": round(donor_penalty, 4),
        "nse_term": round(nse_term, 4),
        "loss_sum_mm": round(loss, 3),
        "constant_loss_sum_mm": round(const_loss, 3),
        "hist_peak_per_mm": hist_eff,
        "is_light_specialist": is_specialist,
    }
    return distance, detail


def choose_analogs(
    forecast_aw_mm: float,
    library: list[dict[str, Any]],
    hec_events: list[dict[str, Any]],
    *,
    top_k: int = 3,
    fingerprints: dict[str, dict[str, Any]] | None = None,
    exclude_event_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude_event_ids = exclude_event_ids or set()
    fps = fingerprints or {}
    pool = expand_library_with_light_specialists(library, hec_events, forecast_aw_mm)
    by_id = {e["event_id"]: e for e in hec_events}
    scored: list[dict[str, Any]] = []
    for row in pool:
        eid = row["event_id"]
        if eid in exclude_event_ids:
            continue
        fp = fps.get(eid)
        if fp and fp.get("aw_full_mm") is not None:
            hist = float(fp["aw_full_mm"])
            hist_source = "aw_full_fingerprint"
        else:
            hist = station_core_mean_mm(by_id.get(eid) or {})
            hist_source = "station_core_mean_fallback"
        if hist != hist:
            continue
        dist, detail = analog_distance(forecast_aw_mm, hist, row, fp)
        scored.append(
            {
                "event_id": eid,
                "historical_aw_full_mm": round(hist, 3),
                "historical_core_mean_mm": round(station_core_mean_mm(by_id.get(eid) or {}), 3),
                "forecast_aw_total_mm": round(forecast_aw_mm, 3),
                "abs_mm_gap": round(abs(hist - forecast_aw_mm), 3),
                "distance": round(dist, 4),
                "distance_detail": detail,
                "hist_rain_source": hist_source,
                "regime_forecast": classify_regime(forecast_aw_mm),
                "regime_hist": (fp or {}).get("regime") or classify_regime(hist),
                "nse": row.get("nse"),
                "research_score": row.get("research_score"),
                "row": row,
            }
        )
    scored.sort(key=lambda r: (r["distance"], r["abs_mm_gap"], -(r["nse"] or -9)))
    return scored[:top_k]


def scale_params_to_q0(
    params: NestedParams,
    precip: dict[str, list[float]],
    areas: dict[str, float],
    q0_m3s: float | None,
    *,
    run_network: Callable[..., dict[str, list[float]]],
    include_mucum_increment: bool = True,
) -> tuple[NestedParams, dict[str, Any]]:
    if q0_m3s is None or q0_m3s != q0_m3s or q0_m3s <= 0:
        return params, {"applied": False, "reason": "invalid_q0"}
    net = run_network(precip, areas, params, include_mucum_increment=include_mucum_increment)
    q_series = net.get("at_mucum") or []
    if not q_series:
        return params, {"applied": False, "reason": "empty_sim"}
    q_sim0 = float(q_series[0])
    if q_sim0 <= 1e-3:
        return params, {"applied": False, "reason": "sim_q0_near_zero", "q_sim0": q_sim0}
    factor = min(max(float(q0_m3s) / q_sim0, 0.2), 5.0)
    scaled = NestedParams(
        up=replace(params.up, initial_flow_ratio=float(params.up.initial_flow_ratio) * factor),
        dn=replace(params.dn, initial_flow_ratio=float(params.dn.initial_flow_ratio) * factor),
        k1=params.k1,
        k2=params.k2,
        k3=params.k3,
        x=params.x,
    )
    return scaled, {
        "applied": True,
        "factor": round(factor, 4),
        "q0_target_m3s": round(float(q0_m3s), 3),
        "q_sim0_before_m3s": round(q_sim0, 3),
    }


def median(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    return ys[len(ys) // 2]


def pick_primary_by_median_rise(members: list[dict[str, Any]]) -> int:
    rises: list[tuple[int, float]] = []
    for i, m in enumerate(members):
        r = (m.get("rise") or {}).get("rise_model_cm")
        if r is None:
            series_n = (m.get("series") or {}).get("n_mucum_cm") or []
            valid = [v for v in series_n if v is not None]
            if series_n and series_n[0] is not None and valid:
                r = float(max(valid)) - float(series_n[0])
        if r is not None:
            rises.append((i, float(r)))
    if not rises:
        return 0
    med = median([r for _, r in rises])
    return min(rises, key=lambda t: abs(t[1] - med))[0]


def load_bacia_artifact() -> dict[str, Any]:
    if BACIA.exists():
        return json.loads(BACIA.read_text(encoding="utf-8"))
    return {}


def fingerprints_from_bacia_or_build(
    hec_events: list[dict[str, Any]],
    areas: dict[str, float],
    *,
    prepare_event_forcing: Callable[..., tuple],
) -> dict[str, dict[str, Any]]:
    cached = load_bacia_artifact().get("fingerprints") or {}
    if cached and len(cached) >= max(1, len(hec_events) - 2):
        return cached
    return build_event_fingerprints(hec_events, areas, prepare_event_forcing=prepare_event_forcing)
