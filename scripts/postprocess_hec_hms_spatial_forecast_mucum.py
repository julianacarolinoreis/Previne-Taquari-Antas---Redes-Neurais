#!/usr/bin/env python3
"""Postprocess the HEC-HMS 4.13 spatial Muçum forecast into platform artifacts."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
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


def q_to_stage(q_m3s: float, segments: list[dict], preferred_segment: int | None = None) -> dict:
    """Invert the published piecewise curve while preserving the active branch.

    The Muçum fitted segments overlap in Q and are not continuous if inversion
    jumps between equations by discharge alone. During a forecast that starts
    on segment 3, stay on that segment while its computed stage remains inside
    the segment's declared stage range; only then move to an adjacent branch.
    """
    ordered = list(segments)
    if preferred_segment is not None:
        ordered.sort(key=lambda seg: 0 if int(seg.get("segment_number") or -1) == int(preferred_segment) else 1)

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
            by.setdefault(el, []).append((int(row["time_value"]), float(row["q_m3s"]), row["pathname"]))
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


def main():
    inp = load_json(INPUT)
    by = read_hec()
    outlet = choose_outlet(by)
    times = list(inp["times_utc"])
    qraw = [x[1] for x in by[outlet]]
    if len(qraw) < len(times):
        raise RuntimeError(f"HEC outlet series too short: {len(qraw)} < {len(times)}")
    q = qraw[:len(times)]

    curve = load_json(CURVE)
    segs = (((curve.get("neighbors_official_curves_NOT_for_STZ") or {}).get("86510000") or {}).get("segments") or [])
    preferred_segment = int((inp.get("initial_state") or {}).get("rating_segment") or 3)
    stages_raw = [q_to_stage(v, segs, preferred_segment=preferred_segment) for v in q]
    n_abs = [x["stage_cm"] for x in stages_raw]
    n0_obs = float((inp.get("initial_state") or {})["stage_cm"])
    q0_obs = float((inp.get("initial_state") or {})["q_m3s"])

    # The HEC run is initialized from observed Q0, so absolute curve stage should
    # already agree. Anchor tiny initialization/numerical differences to the
    # observed stage without altering the hydrograph shape.
    first = n_abs[0] if n_abs and n_abs[0] is not None else n0_obs
    offset = n0_obs - float(first)
    n_anchor = [None if v is None else round(float(v) + offset, 2) for v in n_abs]
    delta = [None if v is None else round(float(v) - n0_obs, 2) for v in n_anchor]

    peak_i = max(range(len(q)), key=lambda i: q[i])
    peak_q = q[peak_i]
    peak_n = n_anchor[peak_i]
    rise = None if peak_n is None else peak_n - n0_obs

    node_series = {}
    for el, vals in by.items():
        v = [x[1] for x in vals[:len(times)]]
        if not v:
            continue
        node_series[el] = {
            "q_m3s": [round(x, 3) for x in v],
            "q0_m3s": round(v[0], 3),
            "peak_q_m3s": round(max(v), 3),
            "peak_time_utc": times[max(range(len(v)), key=lambda i: v[i])] if len(v) <= len(times) else None,
        }

    result = {
        "schema_version": "hec_hms_spatial_forecast_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "status": "hec_hms_4_13_spatial_ifs_ready",
        "model": "HEC-HMS 4.13",
        "mode": "two_zone_spatial_forecast_with_observed_q0_initialization",
        "research_only": True,
        "not_official_alert": True,
        "rain": {
            "source": inp.get("rain_source"),
            "all_spatial_cells_used": inp.get("all_spatial_cells_used"),
            "spatial_cells": inp.get("spatial_cells"),
            "zones": inp.get("zones"),
            "basin_equivalent_forecast_mm_for_audit": inp.get("basin_equivalent_forecast_mm_for_audit"),
        },
        "initial_state": inp.get("initial_state"),
        "parameter_source": inp.get("parameter_source"),
        "times_utc": times,
        "series": {
            "q_mucum_m3s": [round(v, 3) for v in q],
            "n_mucum_rating_cm": n_abs,
            "n_mucum_anchored_cm": n_anchor,
            "delta_n_from_now_cm": delta,
        },
        "summary": {
            "q_now_observed_rating_m3s": round(q0_obs, 3),
            "q_model_initial_m3s": round(q[0], 3),
            "q_initial_error_pct": round(100.0 * (q[0] - q0_obs) / q0_obs, 3) if q0_obs else None,
            "level_now_observed_cm": round(n0_obs, 2),
            "peak_q_m3s": round(peak_q, 3),
            "peak_time_utc": times[peak_i],
            "peak_level_anchored_cm": None if peak_n is None else round(peak_n, 2),
            "rise_from_now_cm": None if rise is None else round(rise, 2),
            "min_q_m3s": round(min(q), 3),
            "end_q_m3s": round(q[-1], 3),
        },
        "nodes": node_series,
        "hec_output": {
            "outlet_element": outlet,
            "flow_elements": sorted(by),
            "n_flow_paths": sum(1 for _ in by),
        },
        "warning_pt": (
            "Resultado executado no HEC-HMS 4.13 com chuva IFS espacializada nas duas zonas "
            "Thiessen do piloto existente e vazão observada de Muçum assimilada como condição "
            "inicial. Não é o projeto original de 145 sub-bacias e não deve ser tratado como "
            "alerta oficial."
        ),
        "artifacts": {
            "input": str(INPUT.relative_to(ROOT)),
            "series_csv": str(SERIES.relative_to(ROOT)),
            "runtime_dir": str(RUNTIME.relative_to(ROOT)),
        },
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with SERIES.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_utc","q_mucum_m3s","n_mucum_rating_cm","n_mucum_anchored_cm","delta_n_from_now_cm"])
        for i,t in enumerate(times):
            w.writerow([t, round(q[i],3), n_abs[i], n_anchor[i], delta[i]])

    print(json.dumps({
        "status": result["status"],
        "q0_obs": result["summary"]["q_now_observed_rating_m3s"],
        "q0_model": result["summary"]["q_model_initial_m3s"],
        "peak_q": result["summary"]["peak_q_m3s"],
        "peak_level_cm": result["summary"]["peak_level_anchored_cm"],
        "rise_cm": result["summary"]["rise_from_now_cm"],
        "peak_time_utc": result["summary"]["peak_time_utc"],
        "elements": result["hec_output"]["flow_elements"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
