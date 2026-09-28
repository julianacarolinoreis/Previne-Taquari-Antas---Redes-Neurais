#!/usr/bin/env python3
"""Build an executable HEC-HMS 4.13 spatial forecast project for Muçum.

Inputs
------
* Full 0.25° ECMWF/IFS field already clipped to the Muçum catchment.
* The existing two-zone Thiessen HEC-HMS spatial pilot.
* Live Muçum stage, 48 h observed rainfall, and the published Muçum rating curve.

The full IFS field is intersected cell-by-cell with each Thiessen zone.  No
single basin-wide rain series is used as forcing. The run is warmed for 48 h with
observed rainfall and an observed Muçum state at the warm-up start. The latest
river level is kept at its exact telemetry timestamp for state validation.
No postprocessing bias shift is treated as HEC-HMS state assimilation: until a
true model-state restart/assimilation exists at t0, the HEC run is diagnostic
and publication as a forecast is blocked.

This is a research forecast, not an official alert.
"""

from __future__ import annotations

import csv
import json
import math
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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
CHUVAS = ROOT / "assets/data/chuvas_horarias.csv"
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
WARMUP_HOURS = 48
RAIN_COLUMNS = {"86472000": "chuva_86472000", "02851072": "chuva_02851072"}
ANA_RAIN_CODES = {"86472000": "86472000", "02851072": "2851072"}
ANA_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"


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


def _curve_segments():
    curve = load_json(CURVE)
    return (((curve.get("neighbors_official_curves_NOT_for_STZ") or {}).get("86510000") or {}).get("segments") or [])


def _stage_state(stage_cm: float, observed_at_utc: str, source: str) -> dict:
    q = stage_to_q(float(stage_cm), _curve_segments())
    if not q["ok"]:
        raise RuntimeError(f"Muçum stage {stage_cm} cm outside rating curve")
    return {
        "stage_cm": float(stage_cm),
        "q_m3s": float(q["q_m3s"]),
        "rating_segment": q.get("segment_number"),
        "observed_at_utc": observed_at_utc,
        "source": source,
    }


def live_context():
    """Current observed state plus an observed state 48 h earlier for warm-up."""
    live = load_json(LIVE)
    stage = live.get("telemetria_ultima_nivel_cm")
    when = live.get("telemetria_ultima_em_utc") or live.get("nivel_rio_agora_em_utc")
    if stage is None or not when:
        raise RuntimeError("Muçum live stage/time unavailable")

    current = _stage_state(
        float(stage), when,
        "ANA/SGB Hidrotelemetria via previsao_ao_vivo_mucum.json",
    )
    current_dt = iso_utc(when)
    # HEC warm-up starts on the full-hour rainfall grid. Use the observed
    # river state at that same full hour 48 h earlier; do not shift a :15/:30
    # state backwards to the top of the hour.
    target_warm = current_dt.replace(minute=0, second=0, microsecond=0) - timedelta(hours=WARMUP_HOURS)

    obs = []
    for row in (live.get("serie_observada_ana") or []):
        h = row.get("hora"); n = row.get("nivel_cm")
        if h is None or n is None:
            continue
        dt_local = datetime.fromisoformat(str(h))
        dt_utc = dt_local.replace(tzinfo=BRT).astimezone(timezone.utc)
        obs.append((dt_utc, float(n)))
    if not obs:
        raise RuntimeError("Muçum observed series unavailable for warm-up")
    obs.sort(key=lambda x: x[0])

    warm_dt, warm_stage = min(obs, key=lambda x: abs((x[0] - target_warm).total_seconds()))
    if abs((warm_dt - target_warm).total_seconds()) > 1800:
        raise RuntimeError("no Muçum observation within 30 min of 48 h warm-up start")
    warm = _stage_state(
        warm_stage, warm_dt.isoformat().replace("+00:00", "Z"),
        "ANA/SGB observed stage at warm-up start",
    )

    target_1h = current_dt - timedelta(hours=1)
    prev_dt, prev_stage = min(obs, key=lambda x: abs((x[0] - target_1h).total_seconds()))
    trend_1h = None
    if abs((prev_dt - target_1h).total_seconds()) <= 1800:
        trend_1h = float(stage) - float(prev_stage)

    current["trend_1h_cm"] = None if trend_1h is None else round(trend_1h, 2)
    current["trend_reference_utc"] = prev_dt.isoformat().replace("+00:00", "Z")
    return {"current": current, "warmup_start": warm}


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_ana_time(value: str):
    value = (value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            pass
    return None


def _fetch_ana_rain(station_code: str, start_local: datetime, end_local: datetime) -> dict:
    params = urllib.parse.urlencode({
        "codEstacao": station_code,
        "dataInicio": start_local.strftime("%d/%m/%Y"),
        "dataFim": end_local.strftime("%d/%m/%Y"),
    })
    req = urllib.request.Request(
        f"{ANA_URL}?{params}",
        headers={"User-Agent": "previne-hec-warmup/1.0"},
    )
    raw = urllib.request.urlopen(req, timeout=30).read()
    root = ET.fromstring(raw)
    roots = [root]
    if (root.text or "").strip().startswith("<"):
        try:
            roots.append(ET.fromstring(root.text))
        except Exception:
            pass
    series = {}
    for rt in roots:
        for row in rt.iter():
            fields = {_xml_local(ch.tag): (ch.text or "") for ch in row}
            stamp = fields.get("DataHora") or fields.get("Data_Hora")
            rain = fields.get("Chuva") or fields.get("chuva") or fields.get("Precipitacao")
            if not stamp or rain in (None, ""):
                continue
            t = _parse_ana_time(stamp)
            if t is None or t < start_local or t > end_local:
                continue
            try:
                value = float(str(rain).replace(",", "."))
            except ValueError:
                continue
            hour = t.replace(minute=0, second=0, microsecond=0)
            series[hour] = series.get(hour, 0.0) + value
    return series


def _load_observed_rain(start_local: datetime, end_local: datetime) -> tuple[dict, dict]:
    """Read stored hourly rain and refresh the live window directly from ANA.

    The direct query is especially important for the partially elapsed current
    hour. Failure of ANA does not create zeros: the stored value is kept, and
    completeness guards decide whether the HEC run can be published.
    """
    if not CHUVAS.exists():
        raise RuntimeError(f"missing observed rainfall file: {CHUVAS}")
    out = {sid: {} for sid in ZONE_IDS}
    with CHUVAS.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            cod = str(row.get("COD_SEQUENCIAL") or "")
            if len(cod) != 12:
                continue
            try:
                t = datetime.strptime(cod, "%Y%m%d%H%M")
            except ValueError:
                continue
            if t < start_local or t > end_local:
                continue
            for sid in ZONE_IDS:
                raw = row.get(RAIN_COLUMNS[sid])
                if raw in (None, ""):
                    continue
                try:
                    out[sid][t] = float(str(raw).replace(",", "."))
                except ValueError:
                    pass

    refresh = {}
    for sid in ZONE_IDS:
        try:
            live = _fetch_ana_rain(ANA_RAIN_CODES[sid], start_local, end_local)
            out[sid].update(live)
            refresh[sid] = {
                "ok": True,
                "hours_refreshed": len(live),
                "latest_hour_local": max(live).isoformat(timespec="minutes") if live else None,
            }
        except Exception as exc:
            refresh[sid] = {
                "ok": False,
                "error": str(exc),
                "fallback": "assets/data/chuvas_horarias.csv",
            }
    return out, refresh


def build_run_rain(zr: dict, ctx: dict) -> tuple[dict, dict]:
    """Prepend 48 h observed rain and blend the partially elapsed current hour.

    HEC remains hourly. The current river observation is kept at its exact
    timestamp and the HEC state is interpolated to that timestamp only for
    validation. This avoids pretending that a 14:15 observation occurred at
    14:00 and avoids calling a visual bias shift "state assimilation".
    """
    if not zr["times_utc"]:
        raise RuntimeError("empty IFS forecast")
    ifs0_utc = iso_utc(zr["times_utc"][0])
    ifs0_local = ifs0_utc.astimezone(BRT).replace(tzinfo=None)
    current_utc = iso_utc(ctx["current"]["observed_at_utc"])
    current_local = current_utc.astimezone(BRT).replace(tzinfo=None)
    if not (ifs0_local <= current_local < ifs0_local + timedelta(hours=1)):
        raise RuntimeError(
            f"latest observation {current_local} is not inside first IFS hour {ifs0_local}"
        )

    warm_start_local = ifs0_local - timedelta(hours=WARMUP_HOURS)
    observed, observed_refresh = _load_observed_rain(warm_start_local, current_local)
    warm_hours = [warm_start_local + timedelta(hours=i) for i in range(WARMUP_HOURS)]

    missing = {}
    for sid in ZONE_IDS:
        missing[sid] = [t for t in warm_hours if t not in observed[sid]]
    if any(missing[sid] for sid in ZONE_IDS):
        detail = "; ".join(
            f"{sid}: {len(missing[sid])} faltantes"
            for sid in ZONE_IDS if missing[sid]
        )
        raise RuntimeError(f"warm-up rainfall incomplete ({detail}); forecast blocked")

    elapsed = max(0.0, min(1.0, (current_local - ifs0_local).total_seconds() / 3600.0))
    run_times_local = list(warm_hours) + [
        iso_utc(t).astimezone(BRT).replace(tzinfo=None) for t in zr["times_utc"]
    ]
    run_times_utc = [
        t.replace(tzinfo=BRT).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for t in run_times_local
    ]

    run_zones = {}
    audit = {
        "hours": WARMUP_HOURS,
        "start_local": warm_start_local.isoformat(timespec="minutes"),
        "end_at_current_hour_local": ifs0_local.isoformat(timespec="minutes"),
        "current_observation_local": current_local.isoformat(timespec="minutes"),
        "current_hour_elapsed_fraction": round(elapsed, 4),
        "missing_hours": {sid: len(missing[sid]) for sid in ZONE_IDS},
        "complete": True,
        "method": (
            "48 h observed ANA rainfall; current partial hour = observed partial "
            "+ remaining fraction of ECMWF/IFS hour; future = ECMWF/IFS"
        ),
        "observed_totals_mm": {},
        "ana_live_refresh": observed_refresh,
    }
    for sid in ZONE_IDS:
        warm_values = [observed[sid][t] for t in warm_hours]
        obs_partial = observed[sid].get(ifs0_local)
        ifs_values = list(zr["zones"][sid]["hourly_mm"])
        if obs_partial is None:
            # A ausência do parcial da hora corrente não pode virar "0 mm
            # observado". Como o estado atual do rio é validado no timestamp
            # exato, usamos somente o IFS para esta hora e registramos a
            # degradação. As 48 h de warm-up continuam obrigatoriamente
            # observadas e já foram validadas acima.
            current_blend = float(ifs_values[0])
            current_source = "ifs_full_hour_fallback_no_observed_partial"
            observed_total = round(sum(warm_values), 3)
            observed_partial_audit = None
        else:
            current_blend = float(obs_partial) + (1.0 - elapsed) * float(ifs_values[0])
            current_source = "observed_partial_plus_remaining_ifs"
            observed_total = round(sum(warm_values) + float(obs_partial), 3)
            observed_partial_audit = round(float(obs_partial), 3)
        values = warm_values + [current_blend] + [float(v) for v in ifs_values[1:]]
        meta = dict(zr["zones"][sid])
        meta["hourly_mm"] = values
        meta["run_total_mm"] = sum(values)
        run_zones[sid] = meta
        audit["observed_totals_mm"][sid] = observed_total
        audit.setdefault("current_hour", {})[sid] = {
            "observed_partial_mm": observed_partial_audit,
            "ifs_full_hour_mm": round(float(ifs_values[0]), 3),
            "combined_hour_mm": round(current_blend, 3),
            "source": current_source,
            "degraded": obs_partial is None,
        }

    return {"times_utc": run_times_utc, "zones": run_zones}, audit


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
     Description: Muçum spatial IFS forecast with 48 h observed-rain warm-up; 2-zone HEC-HMS pilot
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
     Description: 48 h observed ANA warm-up + ECMWF IFS future rainfall by two Thiessen zones
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
     Description: observed warm-up plus IFS spatial forecast over zone {sid}
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
     Description: 48 h observed warm-up plus ECMWF IFS forecast window
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

# Never reuse a DSS file containing previous scheduled forecast windows.
# Otherwise the extractor sees old and current records in the same catalog.
output_dss_path = project_dir + "/output.dss"
if os.path.exists(output_dss_path):
    os.remove(output_dss_path)
    print("REMOVED_STALE_OUTPUT_DSS|" + output_dss_path)

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
    zr_forecast = spatial_rain_to_zones(spatial, zones)
    ctx = live_context()
    zr_run, warmup_audit = build_run_rain(zr_forecast, ctx)

    times = zr_run["times_utc"]
    start_local = iso_utc(times[0]).astimezone(BRT)
    end_local = iso_utc(times[-1]).astimezone(BRT)

    PROJECT.mkdir(parents=True, exist_ok=True)
    zone_csv = write_zone_csv(zr_run)

    (PROJECT / "mucum_spatial_live.hms").write_text(project_text(), encoding="utf-8")
    (PROJECT / "mucum_spatial_live.run").write_text(run_text(), encoding="utf-8")
    (PROJECT / "bacia_spatial_live.basin").write_text(
        basin_text(zr_run, ctx["warmup_start"]), encoding="utf-8"
    )
    (PROJECT / "chuva_spatial_live.met").write_text(met_text(), encoding="utf-8")
    (PROJECT / "evento_spatial_live.control").write_text(
        control_text(start_local, end_local), encoding="utf-8"
    )
    (PROJECT / "mucum_spatial_live.gage").write_text(
        gage_text(start_local, end_local), encoding="utf-8"
    )
    script = write_jython(zone_csv, start_local)

    total_area = sum(zr_forecast["zones"][s]["area_declared_km2"] for s in ZONE_IDS)
    basin_total = sum(
        zr_forecast["zones"][s]["total_mm"] * zr_forecast["zones"][s]["area_declared_km2"]
        for s in ZONE_IDS
    ) / total_area

    initial = {
        **ctx["warmup_start"],
        "method": "observed Muçum Q at 48 h warm-up start as HEC-HMS Recession initial flow/area ratio",
        "initial_flow_area_ratio_m3s_per_km2": round(
            ctx["warmup_start"]["q_m3s"] / total_area, 9
        ),
    }
    current = {
        **ctx["current"],
        "state_handling": (
            "exact observed timestamp retained for validation; HEC state interpolated "
            "within the hourly step for comparison only; no stage bias correction and "
            "no internal HEC-HMS state assimilation is claimed"
        ),
    }

    prep = {
        "schema_version": "hec_hms_spatial_forecast_mucum_input_v2_warmup",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "model": "HEC-HMS 4.13 two-zone spatial pilot",
        "parameter_source": PARAMS,
        "rain_source": "48 h ANA observed warm-up + ECMWF IFS 0.25 degree full field forecast",
        "all_spatial_cells_used": True,
        "spatial_cells": (spatial.get("grid") or {}).get("intersecting_cells"),
        "times_utc": times,
        "forecast_times_utc": zr_forecast["times_utc"],
        "forecast_start_utc": current["observed_at_utc"],
        "zones": {
            sid: {
                k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in zr_forecast["zones"][sid].items() if k != "hourly_mm"
            } | {"hourly_mm": [round(v,6) for v in zr_forecast["zones"][sid]["hourly_mm"]]}
            for sid in ZONE_IDS
        },
        "basin_equivalent_forecast_mm_for_audit": round(basin_total, 6),
        "warmup": warmup_audit,
        "initial_state": initial,
        "current_state": current,
        "runtime": {
            "project_dir": str(PROJECT.relative_to(ROOT)),
            "project": "mucum_spatial_live",
            "run": "Forecast",
            "jython_script": str(script.relative_to(ROOT)),
            "time_interval_minutes": 60,
        },
        "status": "input_ready_for_hec_hms_4_13_with_48h_warmup",
        "warning_pt": (
            "Pesquisa. O HEC usa 48 h de chuva observada para aquecimento e compara o estado "
            "modelado com o último nível observado em seu timestamp real. A saída não é ancorada "
            "por correção visual; sem assimilação real dos estados internos em t0, a rodada fica "
            "diagnóstica. Continua sendo o piloto de duas zonas, não o projeto completo de 145 sub-bacias."
        ),
    }
    (RUNTIME / "forecast_input.json").write_text(
        json.dumps(prep,ensure_ascii=False,indent=2)+"\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": prep["status"],
        "spatial_cells": prep["spatial_cells"],
        "forecast_rain_mm": round(basin_total,3),
        "warmup_hours": WARMUP_HOURS,
        "warmup_stage_cm": initial["stage_cm"],
        "current_stage_cm": current["stage_cm"],
        "current_time_utc": current["observed_at_utc"],
        "trend_1h_cm": current.get("trend_1h_cm"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
