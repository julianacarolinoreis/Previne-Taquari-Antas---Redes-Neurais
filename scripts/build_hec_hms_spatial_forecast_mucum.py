#!/usr/bin/env python3
"""Build an executable HEC-HMS 4.13 spatial forecast project for Muçum.

Inputs
------
* Full 0.25° ECMWF/IFS field already clipped to the Muçum catchment.
* The existing two-zone Thiessen HEC-HMS spatial pilot.
* Live Muçum stage and the published Muçum rating curve.

The full IFS field is intersected cell-by-cell with each Thiessen zone.  No
single basin-wide rain series is used as forcing.  The current observed
discharge is assimilated as the initial Recession baseflow, which HEC-HMS
explicitly supports as an initial condition.

This is a research forecast, not an official alert.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas"
SPATIAL = OUT / "spatial_ifs_mucum/spatial_ifs_mucum_latest.json"
ZONES = ROOT / "assets/data/hec_hms_spatialized_mucum/thiessen_zones_86510000.geojson"
LIVE = ROOT / "previsao_ao_vivo_mucum.json"
CURVE = OUT / "curva_chave_86472600/curva_chave_hunt_86472600_latest.json"
RUNTIME = OUT / "hec_hms_spatial_forecast_mucum"
PROJECT = RUNTIME / "project"

GRID_DEG = 0.25
HALF = GRID_DEG / 2.0
BRT = timezone(timedelta(hours=-3))
PROJECT_CRS = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True).transform

# Best actual HEC-HMS 4.13 two-zone candidate currently available among the
# stored spatialized runs: E27 (NSE 0.8567; peak error 6.14%; lag +5 h).
PARAMS = {
    "source_event": "E27",
    "initial_loss_mm": 2.5,
    "constant_loss_mm_h": 2.0,
    "tc_h": 10.0,
    "storage_h": 45.0,
    "recession_constant_daily": 0.8,
    "threshold_ratio_to_peak": 0.1,
}
ZONE_IDS = ("86472000", "02851072")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iso_utc(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def fmt_hec_date(dt: datetime) -> str:
    return dt.strftime("%d %B %Y").lstrip("0")


def fmt_hec_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def dpart(dt: datetime) -> str:
    return "01" + dt.strftime("%b%Y")


def stage_to_q(stage_cm: float, segments: list[dict]) -> dict:
    for seg in segments:
        lo, hi = float(seg["stage_min_cm"]), float(seg["stage_max_cm"])
        if lo - 1e-6 <= stage_cm <= hi + 1e-6:
            h = stage_cm / 100.0
            q = float(seg["a"]) * max(h - float(seg["h0_m"]), 0.0) ** float(seg["n"])
            return {"ok": True, "q_m3s": q, "segment_number": seg.get("segment_number")}
    return {"ok": False, "q_m3s": None, "reason": "stage_outside_curve"}


def load_zone_geometries():
    data = load_json(ZONES)
    zones = {}
    declared = ((data.get("properties") or {}).get("areas_km2") or {})
    for feat in data.get("features", []):
        p = feat.get("properties") or {}
        if p.get("feature_type") != "thiessen_zone":
            continue
        sid = str(p.get("station"))
        if sid in ZONE_IDS:
            zones[sid] = {
                "geometry": shape(feat["geometry"]),
                "area_km2_declared": float(p.get("area_km2") or declared.get(sid) or 0),
                "name": p.get("name") or sid,
            }
    missing = [s for s in ZONE_IDS if s not in zones]
    if missing:
        raise RuntimeError(f"missing Thiessen zones: {missing}")
    return zones


def spatial_rain_to_zones(spatial: dict, zones: dict) -> dict:
    cells = list(spatial.get("cells") or [])
    if not cells:
        raise RuntimeError("spatial IFS package has no cells")
    times = list((spatial.get("window") or {}).get("times_utc") or [])
    # Current package stores time axis once implicitly in the cells. Rebuild from
    # start/end/hour count if needed.
    if not times:
        first = iso_utc((spatial.get("window") or {})["start_utc"])
        hours = int((spatial.get("window") or {}).get("hours") or len(cells[0].get("precip_mm") or []))
        times = [(first + timedelta(hours=i)).isoformat().replace("+00:00", "Z") for i in range(hours)]
    n = len(times)
    if n <= 0:
        raise RuntimeError("empty forecast time axis")
    for c in cells:
        if len(c.get("precip_mm") or []) != n:
            raise RuntimeError(f"rain length mismatch for {c.get('cell_id')}")

    # Project the Thiessen geometries once.
    zone_proj = {sid: transform(PROJECT_CRS, z["geometry"]) for sid, z in zones.items()}
    weights = {sid: [] for sid in ZONE_IDS}
    for c in cells:
        lat, lon = float(c["latitude"]), float(c["longitude"])
        cell = box(lon - HALF, lat - HALF, lon + HALF, lat + HALF)
        cp = transform(PROJECT_CRS, cell)
        for sid in ZONE_IDS:
            inter = cp.intersection(zone_proj[sid])
            a = inter.area / 1_000_000.0 if not inter.is_empty else 0.0
            if a > 1e-6:
                weights[sid].append((c, a))

    out = {}
    for sid in ZONE_IDS:
        parts = weights[sid]
        area = sum(a for _, a in parts)
        if area <= 0:
            raise RuntimeError(f"no IFS overlap for zone {sid}")
        hourly = []
        for i in range(n):
            hourly.append(sum(float(c["precip_mm"][i]) * a for c, a in parts) / area)
        out[sid] = {
            "name": zones[sid]["name"],
            "area_overlap_km2": area,
            "area_declared_km2": zones[sid]["area_km2_declared"],
            "coverage_ratio": area / zones[sid]["area_km2_declared"] if zones[sid]["area_km2_declared"] else None,
            "n_cells_touching": len(parts),
            "hourly_mm": hourly,
            "total_mm": sum(hourly),
        }
    return {"times_utc": times, "zones": out}


def live_state():
    live = load_json(LIVE)
    stage = live.get("telemetria_ultima_nivel_cm")
    if stage is None:
        stage = live.get("nivel_rio_agora_cm")
    if stage is None:
        raise RuntimeError("Muçum live stage unavailable")
    curve = load_json(CURVE)
    segs = (((curve.get("neighbors_official_curves_NOT_for_STZ") or {}).get("86510000") or {}).get("segments") or [])
    q = stage_to_q(float(stage), segs)
    if not q["ok"]:
        raise RuntimeError(f"Muçum stage {stage} cm outside rating curve")
    return {
        "stage_cm": float(stage),
        "q_m3s": float(q["q_m3s"]),
        "rating_segment": q.get("segment_number"),
        "observed_at_utc": live.get("telemetria_ultima_em_utc") or live.get("nivel_rio_agora_em_utc"),
        "source": "ANA/SGB Hidrotelemetria via previsao_ao_vivo_mucum.json",
    }


def basin_text(zone_rain: dict, state: dict) -> str:
    total_area = sum(zone_rain["zones"][sid]["area_declared_km2"] for sid in ZONE_IDS)
    q_ratio = state["q_m3s"] / total_area
    blocks = []
    for sid in ZONE_IDS:
        area = zone_rain["zones"][sid]["area_declared_km2"]
        blocks.append(f"""Subbasin: Zona_{sid}_LIVE
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00:00
     Area: {area:.6f}
     Downstream: Saida_LIVE

     Canopy: None
     Allow Simultaneous Precip Et: No
     Plant Uptake Method: None

     Surface: None

     LossRate: Initial+Constant
     Percent Impervious Area: 0.0
     Initial Loss: {PARAMS['initial_loss_mm']:.6f}
     Constant Loss Rate: {PARAMS['constant_loss_mm_h']:.6f}

     Transform: Clark
     Clark Method: Specified
     Time of Concentration: {PARAMS['tc_h']:.6f}
     Storage Coefficient: {PARAMS['storage_h']:.6f}
     Time Area Method: Default

     Baseflow: Recession
     Recession Factor: {PARAMS['recession_constant_daily']:.6f}
     Initial Flow/Area Ratio: {q_ratio:.9f}
     Threshold Flow to Peak Ratio: {PARAMS['threshold_ratio_to_peak']:.6f}
End:

""")
    return f"""Basin: Bacia Spatial LIVE 15690.7km2
     Description: Muçum spatial IFS forecast; 2-zone HEC-HMS pilot; observed Q assimilated as initial recession flow
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00:00
     Version: 4.13
     Filepath Separator: \\
     Unit System: Metric
     Missing Flow To Zero: No
     Enable Flow Ratio: No
     Compute Local Flow At Junctions: No
     Unregulated Output Required: No
     Enable Sediment Routing: No
End:

{''.join(blocks)}Junction: Saida_LIVE
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00:00
     Canvas X: 431912.619
     Canvas Y: 6780976.72
     Computation Point: Yes
End:

Basin Layer Properties:
     Element Layer:
          Name: Icons
          Layer shown: Yes
     End Layer:
End:

Basin Spatial Properties:
End:

Basin Schematic Properties:
     Extent Method: Elements
     Buffer: 0
     Draw Icons: Yes
     Draw Icon Labels: Name
     Draw Map Objects: No
     Draw Gridlines: No
     Draw Flow Direction: No
     Draw HillShade Layer: No
     Draw Elevation Layer: No
     Fix Element Locations: No
     Fix Hydrologic Order: No
End:
"""


def met_text():
    return """Meteorology: Chuva Spatial LIVE
     Description: ECMWF IFS 0.25 degree cell-overlap rainfall by two Thiessen zones
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00:00
     Version: 4.13
     Unit System: Metric
     Set Missing Data to Default: No
     Precipitation Method: Specified Average
     Air Temperature Method: None
     Atmospheric Pressure Method: None
     Dew Point Method: None
     Wind Speed Method: None
     Shortwave Radiation Method: None
     Longwave Radiation Method: None
     Snowmelt Method: None
     Evapotranspiration Method: No Evapotranspiration
     Use Basin Model: Bacia Spatial LIVE 15690.7km2
End:

Precip Method Parameters: Specified Average
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00:00
     Allow Depth Override: Yes
End:

Subbasin: Zona_86472000_LIVE
     Gage: Chuva_86472000_LIVE
End:

Subbasin: Zona_02851072_LIVE
     Gage: Chuva_02851072_LIVE
End:
"""


def gage_text(start_local: datetime, end_local: datetime):
    date_part = dpart(start_local)
    blocks = []
    for sid in ZONE_IDS:
        blocks.append(f"""Gage: Chuva_{sid}_LIVE
     Gage: Chuva_{sid}_LIVE
     Gage Type: Precipitation
     Description: IFS spatial overlap over Thiessen zone {sid}
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00:00
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: spatial_rain.dss
     Pathname: /MUCUM/IFS_{sid}/PRECIP-INC/{date_part}/1Hour/FORECAST/
     Variant: Variant-1
       Start Time: {fmt_hec_date(start_local)}, {fmt_hec_time(start_local)}
       End Time: {fmt_hec_date(end_local)}, {fmt_hec_time(end_local)}
     End Variant: Variant-1
End:

""")
    return """Gage Manager: Mucum spatial forecast
     Version: 4.13
     Filepath Separator: \\
End:

""" + "".join(blocks)


def project_text():
    return """Project: mucum_spatial_live
     Description: Spatial ECMWF IFS rainfall runoff forecast for Mucum
     Version: 4.13
     Filepath Separator: \\
     DSS File Name: spatial_rain.dss
     Time Zone ID: America/Sao_Paulo
End:

Precipitation: Chuva Spatial LIVE
     Filename: chuva_spatial_live.met
End:

Basin: Bacia Spatial LIVE 15690.7km2
     Filename: bacia_spatial_live.basin
End:

Control: Evento Spatial LIVE
     FileName: evento_spatial_live.control
End:
"""


def run_text():
    return """Run: Forecast
     Description: Spatial IFS rainfall-runoff forecast at Mucum
     Log File: forecast.log
     DSS File: output.dss
     Is Save Spatial Results: No
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00:00
     Basin: Bacia Spatial LIVE 15690.7km2
     Precip: Chuva Spatial LIVE
     Control: Evento Spatial LIVE
     Save State Type: None
     Time-Series Output: Save All
     Time Series Results Manager Start:
     Time Series Results Manager End:
End:
"""


def control_text(start_local: datetime, end_local: datetime):
    return f"""Control: Evento Spatial LIVE
     Description: 120 h ECMWF IFS forecast window
     Last Modified Date: 21 September 2026
     Last Modified Time: 22:00
     Version: 4.13
     Start Date: {fmt_hec_date(start_local)}
     Start Time: {fmt_hec_time(start_local)}
     End Date: {fmt_hec_date(end_local)}
     End Time: {fmt_hec_time(end_local)}
     Time Interval: 60
End:
"""


def write_zone_csv(zone_rain: dict):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    path = RUNTIME / "zone_hourly.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "time_local", "rain_86472000_mm", "rain_02851072_mm"])
        for i, t in enumerate(zone_rain["times_utc"]):
            dt = iso_utc(t).astimezone(BRT)
            w.writerow([
                t,
                dt.strftime("%Y-%m-%d %H:%M:%S"),
                f"{zone_rain['zones']['86472000']['hourly_mm'][i]:.6f}",
                f"{zone_rain['zones']['02851072']['hourly_mm'][i]:.6f}",
            ])
    return path


def write_jython(zone_csv: Path, start_local: datetime):
    date_part = dpart(start_local)
    script = PROJECT / "run_forecast.script"
    # Jython 2.x in HEC-HMS expects binary csv mode.
    script.write_text(f"""from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
from hec.io import TimeSeriesContainer
import csv
import os

project_dir = r"{PROJECT.as_posix()}"
rain_csv = r"{zone_csv.as_posix()}"
rain_dss_path = project_dir + "/spatial_rain.dss"
output_csv = r"{(RUNTIME / 'hec_output_values.csv').as_posix()}"
months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

with open(rain_csv, "rb") as handle:
    rows = list(csv.DictReader(handle))
if not rows:
    raise ValueError("empty zone rainfall CSV")

def put_rain(dss, station, field):
    first = rows[0]["time_local"]
    year, month, day = [int(x) for x in first[:10].split("-")]
    hour = int(first[11:13]) * 100
    current = HecTime("%02d%s%04d" % (day, months[month-1], year), "%04d" % hour)
    values = []
    times = []
    for row in rows:
        values.append(float(row[field]))
        times.append(current.value())
        current.add(60)
    c = TimeSeriesContainer()
    c.fullName = "/MUCUM/IFS_%s/PRECIP-INC/{date_part}/1Hour/FORECAST/" % station
    c.interval = 60
    c.times = times
    c.values = values
    c.numberValues = len(values)
    c.units = "MM"
    c.type = "PER-CUM"
    dss.put(c)

dss = HecDss.open(rain_dss_path)
put_rain(dss, "86472000", "rain_86472000_mm")
put_rain(dss, "02851072", "rain_02851072_mm")
dss.close()
print("SPATIAL_RAIN_DSS_WRITTEN|" + rain_dss_path)

OpenProject("mucum_spatial_live", project_dir)
Compute("Forecast")

dss = HecDss.open(project_dir + "/output.dss")
catalog = list(dss.getCatalogedPathnames())
flow_paths = [p for p in catalog if "/FLOW/" in p and "/1Hour/RUN:Forecast/" in p]
print("FLOW_PATHS|" + "|".join(flow_paths))

with open(output_csv, "wb") as handle:
    w = csv.writer(handle)
    w.writerow(["element","time_value","q_m3s","pathname"])
    for pathname in flow_paths:
        series = dss.get(pathname)
        parts = pathname.split("/")
        element = parts[2] if len(parts) > 2 else ""
        for i in range(series.numberValues):
            value = float(series.values[i])
            if value > -1.0e20:
                w.writerow([element, int(series.times[i]), value, pathname])
dss.close()
print("SPATIAL_FORECAST_OUTPUT|" + output_csv)
Exit(1)
""", encoding="utf-8")
    return script


def main():
    spatial = load_json(SPATIAL)
    zones = load_zone_geometries()
    zr = spatial_rain_to_zones(spatial, zones)
    state = live_state()
    times = zr["times_utc"]
    start_local = iso_utc(times[0]).astimezone(BRT)
    end_local = iso_utc(times[-1]).astimezone(BRT)

    PROJECT.mkdir(parents=True, exist_ok=True)
    zone_csv = write_zone_csv(zr)

    (PROJECT / "mucum_spatial_live.hms").write_text(project_text(), encoding="utf-8")
    (PROJECT / "mucum_spatial_live.run").write_text(run_text(), encoding="utf-8")
    (PROJECT / "bacia_spatial_live.basin").write_text(basin_text(zr, state), encoding="utf-8")
    (PROJECT / "chuva_spatial_live.met").write_text(met_text(), encoding="utf-8")
    (PROJECT / "evento_spatial_live.control").write_text(control_text(start_local, end_local), encoding="utf-8")
    (PROJECT / "mucum_spatial_live.gage").write_text(gage_text(start_local, end_local), encoding="utf-8")
    script = write_jython(zone_csv, start_local)

    total_area = sum(zr["zones"][s]["area_declared_km2"] for s in ZONE_IDS)
    basin_total = sum(
        zr["zones"][s]["total_mm"] * zr["zones"][s]["area_declared_km2"] for s in ZONE_IDS
    ) / total_area
    prep = {
        "schema_version": "hec_hms_spatial_forecast_mucum_input_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "model": "HEC-HMS 4.13 two-zone spatial pilot",
        "parameter_source": PARAMS,
        "rain_source": "ECMWF IFS 0.25 degree full field; cell-zone overlap weighting",
        "all_spatial_cells_used": True,
        "spatial_cells": (spatial.get("grid") or {}).get("intersecting_cells"),
        "times_utc": times,
        "zones": {
            sid: {
                k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in zr["zones"][sid].items() if k != "hourly_mm"
            } | {"hourly_mm": [round(v,6) for v in zr["zones"][sid]["hourly_mm"]]}
            for sid in ZONE_IDS
        },
        "basin_equivalent_forecast_mm_for_audit": round(basin_total, 6),
        "initial_state": {
            **state,
            "method": "observed Muçum Q distributed by zone area as HEC-HMS Recession initial flow/area ratio",
            "initial_flow_area_ratio_m3s_per_km2": round(state["q_m3s"] / total_area, 9),
        },
        "runtime": {
            "project_dir": str(PROJECT.relative_to(ROOT)),
            "project": "mucum_spatial_live",
            "run": "Forecast",
            "jython_script": str(script.relative_to(ROOT)),
        },
        "status": "input_ready_for_hec_hms_4_13",
        "warning_pt": (
            "Pesquisa. O projeto usa a espacialização HEC de duas zonas disponível no repositório; "
            "não é o projeto original de 145 sub-bacias. A chuva, porém, vem do campo IFS completo "
            "intersectado célula a célula com as zonas."
        ),
    }
    (RUNTIME / "forecast_input.json").write_text(json.dumps(prep,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status": prep["status"],
        "spatial_cells": prep["spatial_cells"],
        "zone_86472000_mm": round(zr["zones"]["86472000"]["total_mm"],3),
        "zone_02851072_mm": round(zr["zones"]["02851072"]["total_mm"],3),
        "basin_equiv_mm": round(basin_total,3),
        "stage0_cm": state["stage_cm"],
        "q0_m3s": round(state["q_m3s"],3),
        "initial_flow_area_ratio": prep["initial_state"]["initial_flow_area_ratio_m3s_per_km2"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
