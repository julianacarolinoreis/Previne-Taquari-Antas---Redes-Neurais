#!/usr/bin/env python3
"""Build one full-basin PREVINE snapshot for G040.

This is an integration layer, not a hydrologic model. It combines:
- the strict G040 spatial domain + meteorological buffer;
- merged observed/forecast rainfall forcing;
- calibrated/assimilation hydro controls;
- the broad basin station network used to read conditions across G040;
- current research readiness/blockers.

The output never treats one city or gauge as the endpoint of the basin.
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
NETWORK = ROOT / "assets/data/basin_station_status_latest.json"

OUT = BASE / "g040_basin_snapshot_latest.json"
OUTCSV = BASE / "g040_basin_controls_latest.csv"
OUTNETWORK = BASE / "g040_basin_network_latest.csv"


def loadj(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def latest_trend(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    usable = [r for r in rows if r.get(key) is not None and r.get("time_utc")]
    if len(usable) < 2:
        return {"direction": "unknown", "delta": None}
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


def observed_window(station: dict[str, Any], hours: int) -> float | None:
    rain = station.get("observed_rain") or {}
    w = (rain.get("windows") or {}).get(f"{hours}h") or {}
    value = w.get("mm")
    return float(value) if value is not None else None


def forecast_windows(station: dict[str, Any], hours: int) -> dict[str, float | None]:
    out = {}
    models = ((station.get("forecast") or {}).get("models") or {})
    for model_id, model in models.items():
        windows = (model or {}).get("precipitation_windows_mm") or {}
        value = windows.get(f"{hours}h")
        out[str(model_id)] = float(value) if value is not None else None
    return out


def main() -> int:
    domain = loadj(DOMAIN)
    rain = loadj(RAIN)
    hydro = loadj(HYDRO)
    readiness = loadj(READINESS)
    network = loadj(NETWORK)

    interval_by_downstream = {}
    for interval in rain.get("intervals") or []:
        iid = str(interval.get("interval_id") or "")
        parts = iid.split("_")
        downstream = parts[-1] if len(parts) >= 3 else None
        if downstream:
            interval_by_downstream[downstream] = interval

    controls = []
    control_lookup = {}
    for c in hydro.get("controls") or []:
        code = str(c.get("code") or "")
        rows = c.get("recent_rows") or []
        interval = interval_by_downstream.get(code) or {}
        series = interval.get("series") or []
        item = {
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
            "flow_trend": latest_trend(rows, "flow_m3s"),
            "level_trend": latest_trend(rows, "level_source_unit"),
            "rain_interval_id": interval.get("interval_id"),
            "antecedent_rain": {
                f"{h}h": series_sum(series, "observed", h)
                for h in (3, 6, 12, 24, 48, 72)
            },
            "forecast_rain": {
                f"{h}h": series_sum(series, "forecast", h)
                for h in (3, 6, 12, 24, 48, 72, 120)
            },
            "model_forecast": None,
            "model_forecast_status": "pending distributed hydrologic compute/calibration",
            "soil_state": None,
            "soil_state_status": "SMA/continuous wetness state not yet calibrated for full G040",
        }
        controls.append(item)
        control_lookup[code] = item

    network_rows = []
    model_ids = [
        str(m.get("id"))
        for m in (network.get("models") or [])
        if isinstance(m, dict) and m.get("id")
    ]
    for st in network.get("stations") or []:
        code = str(st.get("code") or "")
        level = st.get("level") or {}
        rain_obs = st.get("observed_rain") or {}
        compact = {
            "id": st.get("id"),
            "code": code,
            "name": st.get("name"),
            "latitude": st.get("latitude"),
            "longitude": st.get("longitude"),
            "upg_label": st.get("upg_label"),
            "source_networks": st.get("source_networks") or [],
            "source_roles": st.get("source_roles") or [],
            "is_calibration_control": code in control_lookup,
            "control_role": (control_lookup.get(code) or {}).get("role"),
            "observed_rain_state": rain_obs.get("state"),
            "rain_observed_at_utc": rain_obs.get("last_observed_at_utc"),
            "rain_observed_age_minutes": rain_obs.get("observed_age_minutes"),
            "rain_observed_mm": {
                f"{h}h": observed_window(st, h)
                for h in (1, 3, 6, 12, 24, 48, 72)
            },
            "level_state": level.get("state"),
            "current_level_cm": level.get("current_cm"),
            "level_observed_at_utc": level.get("observed_at_utc"),
            "level_observed_age_minutes": level.get("observed_age_minutes"),
            "forecast_rain_by_model_mm": {
                f"{h}h": forecast_windows(st, h)
                for h in (3, 6, 12, 24, 48, 72)
            },
        }
        network_rows.append(compact)

    stale = [c for c in controls if not c.get("fresh_for_state")]
    blockers = list(readiness.get("blockers") or [])
    scope = network.get("scope") or {}
    payload = {
        "schema_version": "g040_basin_snapshot_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "scope": {
            "domain": "entire Taquari-Antas G040",
            "single_endpoint": False,
            "station_role": "broad distributed network for basin reading; calibrated controls are a marked subset",
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
        "broad_station_network": {
            "source_artifact": str(NETWORK.relative_to(ROOT)),
            "station_count": scope.get("station_count", len(network_rows)),
            "forecast_station_count": scope.get("forecast_station_count"),
            "observed_rain_station_count": scope.get("observed_rain_station_count"),
            "observed_rain_hourly_station_count": scope.get("observed_rain_hourly_station_count"),
            "level_station_count": scope.get("level_station_count"),
            "source_counts": network.get("source_counts") or {},
            "coverage": network.get("coverage") or {},
            "freshness": network.get("freshness") or {},
            "stations": network_rows,
        },
        "calibration_assimilation_controls": {
            "source": hydro.get("source"),
            "control_count": len(controls),
            "fresh_control_count": len(controls) - len(stale),
            "stale_control_count": len(stale),
            "controls": controls,
        },
        "distributed_model_status": {
            "ready_for_valid_forecast_at_all_controls": False,
            "blockers": blockers,
            "required_next": [
                "run/calibrate full-basin branch hydrology",
                "recover/verify 145-subbasin + 72-reach target",
                "calibrate continuous SMA/soil state",
                "validate multi-event and multi-station",
                "attach location-specific hydrologic forecast only after model skill gate passes",
            ],
        },
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    control_fields = [
        "code", "label", "group", "role", "last_observation_utc", "age_minutes",
        "fresh_for_state", "current_level_source_unit", "current_flow_m3s",
        "level_trend", "flow_trend", "rain_interval_id",
        "rain_obs_24h_mm", "rain_fcst_24h_mm", "rain_fcst_48h_mm", "rain_fcst_72h_mm",
        "soil_state_status", "model_forecast_status"
    ]
    with OUTCSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=control_fields)
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
                "model_forecast_status": c["model_forecast_status"],
            })

    network_fields = [
        "code", "name", "upg_label", "latitude", "longitude", "source_networks",
        "is_calibration_control", "control_role",
        "observed_rain_state", "rain_observed_at_utc", "rain_observed_age_minutes",
        "rain_obs_24h_mm", "rain_obs_48h_mm", "rain_obs_72h_mm",
        "level_state", "current_level_cm", "level_observed_at_utc", "level_observed_age_minutes",
    ]
    for model_id in model_ids:
        for h in (24, 48, 72):
            network_fields.append(f"{model_id}_rain_{h}h_mm")

    with OUTNETWORK.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=network_fields)
        w.writeheader()
        for st in network_rows:
            row = {
                "code": st["code"],
                "name": st["name"],
                "upg_label": st["upg_label"],
                "latitude": st["latitude"],
                "longitude": st["longitude"],
                "source_networks": "|".join(str(x) for x in st["source_networks"]),
                "is_calibration_control": st["is_calibration_control"],
                "control_role": st["control_role"],
                "observed_rain_state": st["observed_rain_state"],
                "rain_observed_at_utc": st["rain_observed_at_utc"],
                "rain_observed_age_minutes": st["rain_observed_age_minutes"],
                "rain_obs_24h_mm": st["rain_observed_mm"].get("24h"),
                "rain_obs_48h_mm": st["rain_observed_mm"].get("48h"),
                "rain_obs_72h_mm": st["rain_observed_mm"].get("72h"),
                "level_state": st["level_state"],
                "current_level_cm": st["current_level_cm"],
                "level_observed_at_utc": st["level_observed_at_utc"],
                "level_observed_age_minutes": st["level_observed_age_minutes"],
            }
            for model_id in model_ids:
                for h in (24, 48, 72):
                    row[f"{model_id}_rain_{h}h_mm"] = (
                        (st["forecast_rain_by_model_mm"].get(f"{h}h") or {}).get(model_id)
                    )
            w.writerow(row)

    print(json.dumps({
        "status": "G040_BASIN_SNAPSHOT_READY",
        "network_stations": len(network_rows),
        "calibration_controls": len(controls),
        "fresh_controls": len(controls) - len(stale),
        "distributed_forecast_ready": False,
        "blockers": blockers,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
