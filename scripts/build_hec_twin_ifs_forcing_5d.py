#!/usr/bin/env python3
"""Build ~5-day hourly IFS precip forcing for the STZ–Muçum HEC twin subbasins.

Maps Open-Meteo ECMWF IFS 0.25° point rainfall to twin subbasin IDs.
This is an explicit point→subbasin proxy (not a catchment areal mask).
Research only — not an official alert product.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
POINTS = ROOT / "assets" / "data" / "basin_forecast_points.json"
ESTRUTURA = OUT / "estrutura_stz_mucum_latest.json"

# Twin subbasin → monitoring point used as IFS sample (honest proxy).
SUBBASIN_POINT = {
    "SB_PRATA_7868": "86472000",  # Antas / Prata trunk proxy
    "SB_ANTAS_RESIDUAL": "86472000",
    "SB_CARREIRO_7866": "86507000",
    "SB_STZ_RESIDUAL": "86472600",
    "SB_INC_MUCUM": "86510000",
}

HORIZON_HOURS = 120  # 5 days
USER_AGENT = "PREVINE-hec-twin-5d-research/1.0"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def load_points() -> dict[str, dict[str, Any]]:
    data = json.loads(POINTS.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for p in data.get("points", []):
        code = str(p.get("station_code") or "")
        if code:
            out[code] = p
    return out


def load_areas() -> dict[str, float]:
    estrutura = json.loads(ESTRUTURA.read_text(encoding="utf-8"))
    areas: dict[str, float] = {}
    for el in estrutura["models"]["mucum"]["elements"]:
        if el.get("type") == "subbasin":
            areas[el["id"]] = float(el["area_km2"])
    return areas


def fetch_hourly_precip(lat: float, lon: float, hours: int) -> dict[str, Any]:
    # forecast_days=6 keeps a full +120 h window after the current hour.
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "models": "ecmwf_ifs025",
        "hourly": "precipitation",
        "forecast_days": 6,
        "timezone": "UTC",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=45) as resp:
        payload = json.load(resp)
    hourly = payload.get("hourly") or {}
    times = list(hourly.get("time") or [])
    precip = list(hourly.get("precipitation") or [])
    if len(times) < hours or len(precip) < hours:
        raise RuntimeError(f"IFS hourly incomplete at {lat},{lon}: {len(times)} steps")
    series = []
    for t, mm in zip(times[:hours], precip[:hours]):
        series.append({"time_utc": f"{t}:00Z" if "Z" not in t else t, "precip_mm": float(mm or 0.0)})
    return {"url": url, "series": series, "model": "ecmwf_ifs025"}


def build_forcing(*, hours: int = HORIZON_HOURS) -> dict[str, Any]:
    points = load_points()
    areas = load_areas()
    missing = [sb for sb in SUBBASIN_POINT if sb not in areas]
    if missing:
        raise RuntimeError(f"subbasin areas missing: {missing}")

    by_station: dict[str, dict[str, Any]] = {}
    precip_by_sb: dict[str, list[float]] = {}
    meta_by_sb: dict[str, Any] = {}
    times: list[str] | None = None

    for sb, code in SUBBASIN_POINT.items():
        pt = points.get(code)
        if not pt or pt.get("latitude") is None or pt.get("longitude") is None:
            raise RuntimeError(f"missing coordinates for station {code} ({sb})")
        if code not in by_station:
            by_station[code] = fetch_hourly_precip(float(pt["latitude"]), float(pt["longitude"]), hours)
        fetched = by_station[code]
        series = fetched["series"]
        if times is None:
            times = [row["time_utc"] for row in series]
        precip_by_sb[sb] = [float(row["precip_mm"]) for row in series]
        meta_by_sb[sb] = {
            "proxy_station": code,
            "proxy_name": pt.get("name"),
            "latitude": pt.get("latitude"),
            "longitude": pt.get("longitude"),
            "area_km2": areas[sb],
            "fetch_url": fetched["url"],
            "total_mm": round(sum(precip_by_sb[sb]), 3),
            "max_hourly_mm": round(max(precip_by_sb[sb]) if precip_by_sb[sb] else 0.0, 3),
        }

    # Area-weighted basin mean (proxy points, not mask).
    area_sum = sum(areas[sb] for sb in precip_by_sb)
    weighted = []
    for i in range(hours):
        num = sum(precip_by_sb[sb][i] * areas[sb] for sb in precip_by_sb)
        weighted.append(num / area_sum)
    totals = {sb: sum(precip_by_sb[sb]) for sb in precip_by_sb}

    return {
        "schema_version": "hec_twin_ifs_forcing_5d_v1",
        "generated_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
        "status": "research_forcing_ready",
        "purpose": "Forçante IFS horária (~5 dias) para o gêmeo HEC STZ–Muçum — pesquisa, não alerta.",
        "horizon_hours": hours,
        "model": "ecmwf_ifs025_open_meteo",
        "discipline": {
            "point_proxy_not_areal_mask": True,
            "not_official_alert": True,
            "stz_rating_curve": "absent — forcing still valid; Q@STZ remains diagnostic only",
        },
        "times_utc": times,
        "precip_mm_by_subbasin": precip_by_sb,
        "subbasin_meta": meta_by_sb,
        "area_weighted_mean_mm": {
            "hourly": [round(x, 4) for x in weighted],
            "total_mm": round(sum(weighted), 3),
            "max_hourly_mm": round(max(weighted) if weighted else 0.0, 3),
            "totals_by_subbasin_mm": {k: round(v, 3) for k, v in totals.items()},
        },
        "artifacts": {
            "json": "hec_twin_ifs_forcing_5d_latest.json",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=HORIZON_HOURS)
    parser.add_argument("--from-json", type=Path, help="Reuse an existing forcing JSON (offline).")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.from_json:
        payload = json.loads(args.from_json.read_text(encoding="utf-8"))
    else:
        payload = build_forcing(hours=args.hours)
    out_path = OUT / "hec_twin_ifs_forcing_5d_latest.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"status={payload['status']} total_aw_mm={payload['area_weighted_mean_mm']['total_mm']}")


if __name__ == "__main__":
    main()
