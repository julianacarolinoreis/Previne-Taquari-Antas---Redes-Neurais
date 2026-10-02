#!/usr/bin/env python3
"""Build one full-basin PREVINE snapshot for G040.

This is a presentation/integration layer, not a hydrologic model. It combines
the current distributed rainfall forcing, hydrometric controls, spatial-domain
contract and readiness state so downstream UI/agents can answer "how is the
basin?" without selecting a single endpoint such as Muçum.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/data/hec_hms_g040_full_basin"
STACK = ROOT / "assets/data/g040_hydro_stack"

DOMAIN = BASE / "g040_domain_contract_latest.json"
RAIN = BASE / "whole_basin_rain_forcing_latest.json"
HYDRO = BASE / "whole_basin_live_hydro_controls_latest.json"
READINESS = STACK / "master_readiness_latest.json"

OUT = BASE / "g040_basin_snapshot_latest.json"
OUTCSV = BASE / "g040_basin_controls_latest.csv"


def loadj(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def latest_trend(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    usable = [r for r in rows if r.get(key) is not None and r.get("time_utc")]
    if len(usable) < 2:
        return {"direction": "unknown", "delta": None, "hours": None}
    a, b = usable[-2], usable[-1]
    delta = float(b[key]) - float(a[key])
    eps = 1e-9
    direction = "rising" if delta > eps else "falling" if delta < -eps else "stable"
    return {
        "direction": direction,
        "delta": round(delta, 4),
        "from_time_utc": a["time_utc"],
        "to_time_utc": b["time_utc"],
    }


def series_sum(series: list[dict[str, Any]], source: str, hours: int) -> dict[str, Any]:
    vals = [r for r in series if r.get("source") == source and r.get("mm") is not None]
    vals = vals[-hours:]
    return {
        "mm": round(sum(float(r["mm"]) for r in vals), 3) if len(vals) == hours else None,
        "available_hours": len(vals),
        "required_hours": hours,
        "complete": len(vals) == hours,
    }


def main() -> int:
    domain = loadj(DOMAIN)
    rain = loadj(RAIN)
    hydro = loadj(HYDRO)
    readiness = loadj(READINESS)

    interval_by_downstream = {}
    for interval in rain.get("intervals") or []:
        iid = str(interval.get("interval_id") or "")
        parts = iid.split("_")
        downstream = parts[-1] if len(parts) >= 3 else None
        if downstream:
            interval_by_downstream[downstream] = interval

    controls = []
    for c in hydro.get("controls") or []:
        code = str(c.get("code") or "")
        rows = c.get("recent_rows") or []
        qtrend = latest_trend(rows, "flow_m3s")
        ltrend = latest_trend(rows, "level_source_unit")
        interval = interval_by_downstream.get(code) or {}
        series = interval.get("series") or []
        antecedent = {f"{h}h": series_sum(series, "observed", h) for h in (3, 6, 12, 24, 48, 72)}
        forecast = {f"{h}h": series_sum(series, "forecast", h) for h in (3, 6, 12, 24, 48, 72, 120)}

        controls.append({
            "code": code,
            "label": c.get("label"),
            "group": c.get("group"),
            "role": c.get("role"),
            "mass_balance": c.get("mass_balance"),
            "last_observation_utc": c.get("last_observation_utc"),
            "age_minutes": c.get("age_minutes"),
            "fresh_for_state": c.get("fresh_for_state"),
            "current_flow_m3s": c.get("latest_flow_m3s"),
            "current_level_source_unit": c.get("latest_level_source_unit"),
            "flow_trend": qtrend,
            "level_trend": ltrend,
            "rain_interval_id": interval.get("interval_id"),
            "antecedent_rain": antecedent,
            "forecast_rain": forecast,
            "model_forecast": None,
            "model_forecast_status": "pending distributed hydrologic compute/calibration",
            "soil_state": None,
            "soil_state_status": "SMA/continuous wetness state not yet calibrated for full G040",
        })

    stale = [c for c in controls if not c.get("fresh_for_state")]
    blockers = list(readiness.get("blockers") or [])
    payload = {
        "schema_version": "g040_basin_snapshot_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "scope": {
            "domain": "entire Taquari-Antas G040",
            "single_endpoint": False,
            "station_role": "distributed observation/assimilation/calibration/validation controls",
            "hydrologic_mask": (domain.get("hydrologic_mask") or {}).get("path"),
            "meteorological_download_buffer": (domain.get("meteorological_acquisition") or {}).get("path"),
            "buffer_km": (domain.get("meteorological_acquisition") or {}).get("buffer_km"),
        },
        "rain_forcing": {
            "status": rain.get("status"),
            "transition": rain.get("transition"),
            "grid_contract": rain.get("grid_contract"),
            "gates": rain.get("gates"),
        },
        "hydrometric_network": {
            "source": hydro.get("source"),
            "control_count": len(controls),
            "fresh_control_count": len(controls) - len(stale),
            "stale_control_count": len(stale),
        },
        "controls": controls,
        "distributed_model_status": {
            "ready_for_valid_forecast_at_all_controls": False,
            "blockers": blockers,
            "required_next": [
                "run/calibrate full-basin branch hydrology",
                "recover/verify 145-subbasin + 72-reach target",
                "calibrate continuous SMA/soil state",
                "validate multi-event and multi-station",
                "attach location-specific forecast only after model skill gate passes"
            ]
        }
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "code", "label", "group", "role", "last_observation_utc", "age_minutes",
        "fresh_for_state", "current_level_source_unit", "current_flow_m3s",
        "level_trend", "flow_trend", "rain_interval_id",
        "rain_obs_24h_mm", "rain_fcst_24h_mm", "rain_fcst_48h_mm", "rain_fcst_72h_mm",
        "soil_state_status", "model_forecast_status"
    ]
    with OUTCSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for c in controls:
            w.writerow({
                "code": c["code"],
                "label": c["label"],
                "group": c["group"],
                "role": c["role"],
                "last_observation_utc": c["last_observation_utc"],
                "age_minutes": c["age_minutes"],
                "fresh_for_state": c["fresh_for_state"],
                "current_level_source_unit": c["current_level_source_unit"],
                "current_flow_m3s": c["current_flow_m3s"],
                "level_trend": (c["level_trend"] or {}).get("direction"),
                "flow_trend": (c["flow_trend"] or {}).get("direction"),
                "rain_interval_id": c["rain_interval_id"],
                "rain_obs_24h_mm": ((c["antecedent_rain"].get("24h") or {}).get("mm")),
                "rain_fcst_24h_mm": ((c["forecast_rain"].get("24h") or {}).get("mm")),
                "rain_fcst_48h_mm": ((c["forecast_rain"].get("48h") or {}).get("mm")),
                "rain_fcst_72h_mm": ((c["forecast_rain"].get("72h") or {}).get("mm")),
                "soil_state_status": c["soil_state_status"],
                "model_forecast_status": c["model_forecast_status"]
            })

    print(json.dumps({
        "status": "G040_BASIN_SNAPSHOT_READY",
        "controls": len(controls),
        "fresh_controls": len(controls) - len(stale),
        "distributed_forecast_ready": False,
        "blockers": blockers
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
