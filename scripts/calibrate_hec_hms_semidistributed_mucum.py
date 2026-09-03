#!/usr/bin/env python3
"""Calibrate a two-zone, MDT-derived semidistributed Muçum HEC-HMS pilot.

The zones are the Thiessen partitions of the SRTM-delineated watershed for
ANA gages 86472000 and 02851072. Each zone receives its own observed hourly
rainfall series and drains directly to the observed outlet 86510000. A common
parameter set is used for both zones because one outlet hydrograph cannot
identify two independent parameter vectors without overfitting.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPoint, Point
from shapely.ops import voronoi_diagram

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import calibrate_hec_hms_mucum_multi_event as base  # noqa: E402


ROOT = base.ROOT
WATERSHED = ROOT / "assets" / "data" / "hec_hms_spatialized_mucum" / "watershed_86510000_srtm.geojson"
LOCAL_RAIN_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_local_rain_all_events.dss"
TARGET_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_target_multi_event.dss"
STATIONS = {
    "86472000": (-51.6997, -29.0978),
    "02851072": (-51.6331, -28.3811),
}
MONTHS = base.MONTHS


def zone_areas() -> dict[str, float]:
    if not WATERSHED.exists():
        raise SystemExit(f"missing watershed artifact: {WATERSHED}")
    watershed = gpd.read_file(WATERSHED).to_crs("EPSG:31982").geometry.iloc[0]
    points = gpd.GeoSeries(
        [Point(*STATIONS[code]) for code in STATIONS], crs="EPSG:4326"
    ).to_crs("EPSG:31982")
    cells = voronoi_diagram(MultiPoint(list(points)), envelope=watershed.envelope, edges=False)
    areas: dict[str, float] = {}
    for code, point in zip(STATIONS, points):
        cell = min(cells.geoms, key=lambda candidate: candidate.distance(point))
        areas[code] = watershed.intersection(cell).area / 1_000_000.0
    if abs(sum(areas.values()) - watershed.area / 1_000_000.0) > 0.1:
        raise RuntimeError("Thiessen zones do not cover the delineated watershed")
    return areas


def semidistributed_spec(event_id: int) -> dict[str, object] | None:
    """Return a source-backed continuous two-gage window for the score period.

    Missing local observations are not filled.  We select only a contiguous
    hourly run that starts at least 24 hours before the score window and
    covers it completely; otherwise the event remains blocked for this
    semidistributed experiment.
    """
    catalogue = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_eventos_usados.csv"
    with catalogue.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle, delimiter=";") if int(row["evento"]) == event_id and row.get("sempre_treino") == "0"]
    if not rows:
        return None
    row = rows[0]
    derived_path = base.SOURCE / "derived" / f"event_{event_id}_hourly.csv"
    with derived_path.open(encoding="utf-8", newline="") as handle:
        derived = list(csv.DictReader(handle))
    local = {}
    with base.LOCAL_RAIN_CSV.open(encoding="utf-8", newline="") as handle:
        for item in csv.DictReader(handle):
            local[item["COD_SEQUENCIAL"]] = item
    scored_start = datetime.strptime(row["inicio_recorte"], "%Y-%m-%d %H:%M:%S")
    scored_end = datetime.strptime(row["fim_recorte"], "%Y-%m-%d %H:%M:%S")
    runs: list[list[datetime]] = []
    current: list[datetime] = []
    for item in derived:
        dt = datetime.strptime(item["timestamp_label"], "%Y-%m-%d %H:00:00")
        local_item = local.get(dt.strftime("%Y%m%d%H00"), {})
        a = local_item.get("chuva_86472000", "").strip()
        b = local_item.get("chuva_02851072", "").strip()
        if a and b:
            if current and dt - current[-1] != timedelta(hours=1):
                runs.append(current)
                current = []
            current.append(dt)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    eligible = [run for run in runs if run[0] <= scored_start - timedelta(hours=24) and run[-1] >= scored_end]
    if not eligible:
        return None
    selected = max(eligible, key=len)
    return {
        "id": event_id,
        "score_start": scored_start,
        "score_end": scored_end,
        "input_start": selected[0],
        "input_end": selected[-1],
        "derived": derived,
    }


def basin_text_semidistributed(event_id: int, params: dict[str, float], area_km2: float, areas: dict[str, float]) -> str:
    text = base.basin_text(event_id, params, area_km2)
    start_marker = f"Subbasin: Bacia_86472000_E{event_id}"
    end_marker = f"Junction: Saida_E{event_id}"
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    blocks = []
    for code, area in areas.items():
        blocks.append(
            f"""Subbasin: Zona_{code}_E{event_id}
     Last Modified Date: 03 September 2026
     Last Modified Time: 20:30:00
     Area: {area:g}
     Downstream: Saida_E{event_id}

     Canopy: None
     Allow Simultaneous Precip Et: No
     Plant Uptake Method: None

     Surface: None

     LossRate: Initial+Constant
     Percent Impervious Area: 0.0
     Initial Loss: {params['initial_loss']:g}
     Constant Loss Rate: {params['constant_loss']:g}

     Transform: Clark
     Clark Method: Specified
     Time of Concentration: {params['tc_min']:g}
     Storage Coefficient: {params['storage_min']:g}
     Time Area Method: Default

     Baseflow: Recession
     Recession Factor: {params['recession_factor']:g}
     Initial Flow/Area Ratio: {params['initial_flow_area_ratio']:g}
     Threshold Flow to Peak Ratio: 0.1
End:

"""
        )
    return text[:start] + "".join(blocks) + text[end:]


def met_text_semidistributed(event_id: int, area_km2: float) -> str:
    return f"""Meteorology: Chuva E{event_id}
     Description: Chuva horária observada por zona Thiessen ANA 86472000 + 02851072
     Last Modified Date: 03 September 2026
     Last Modified Time: 20:30
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
     Use Basin Model: Bacia E{event_id} {area_km2:g}km2
End:

Precip Method Parameters: Specified Average
     Last Modified Date: 03 September 2026
     Last Modified Time: 20:30
     Allow Depth Override: Yes
End:

Subbasin: Zona_86472000_E{event_id}
     Gage: Chuva_86472000_E{event_id}
End:

Subbasin: Zona_02851072_E{event_id}
     Gage: Chuva_02851072_E{event_id}
End:
"""


def rain_gage(event_id: int, code: str, start, end) -> str:
    dpart = f"01{MONTHS[start.month - 1]}{start.year}"
    return f"""Gage: Chuva_{code}_E{event_id}
     Gage: Chuva_{code}_E{event_id}
     Gage Type: Precipitation
     Description: Chuva ANA {code} para a zona Thiessen {code}
     Last Modified Date: 03 September 2026
     Last Modified Time: 20:30
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: mucum_local_rain_all_events.dss
     Pathname: /MUCUM/RAIN_E{event_id}_{code}/PRECIP-INC/{dpart}/1Hour/OBS/
     Variant: Variant-1
       Start Time: {start.day} {MONTHS[start.month - 1]} {start.year}, {start:%H:%M}
       End Time: {end.day} {MONTHS[end.month - 1]} {end.year}, {end:%H:%M}
     End Variant: Variant-1
End:
"""


def gage_text_semidistributed(spec: dict[str, object]) -> str:
    event_id = int(spec["id"])
    start, end = spec["input_start"], spec["input_end"]
    return """Gage Manager: Mucum semidistributed
     Version: 4.13
     Filepath Separator: \\
End:

""" + rain_gage(event_id, "86472000", start, end) + "\n" + rain_gage(event_id, "02851072", start, end) + f"""
Gage: Q_E{event_id}
     Gage: Q_E{event_id}
     Gage Type: Flow
     Description: Vazão ANA 86510000 do evento E{event_id}
     Last Modified Date: 03 September 2026
     Last Modified Time: 20:30
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: mucum_target_multi_event.dss
     Pathname: /MUCUM/OBS_E{event_id}/FLOW/{'01' + MONTHS[start.month - 1] + str(start.year)}/1Hour/OBS/
     Variant: Variant-1
       Start Time: {start.day} {MONTHS[start.month - 1]} {start.year}, {start:%H:%M}
       End Time: {end.day} {MONTHS[end.month - 1]} {end.year}, {end:%H:%M}
     End Variant: Variant-1
End:
"""


def make_candidate(output_dir: Path, index: int, params: dict[str, float], spec: dict[str, object], areas: dict[str, float]) -> Path:
    event_id = int(spec["id"])
    candidate = output_dir / "search" / f"candidate_{index:04d}"
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LOCAL_RAIN_DSS, candidate / "mucum_local_rain_all_events.dss")
    shutil.copy2(TARGET_DSS, candidate / "mucum_target_multi_event.dss")
    area_km2 = sum(areas.values())
    (candidate / f"mucum_E{event_id}.hms").write_text(base.single_project_text(spec, area_km2), encoding="utf-8")
    (candidate / f"mucum_E{event_id}.run").write_text(base.single_run_text(spec, area_km2), encoding="utf-8")
    (candidate / f"mucum_E{event_id}.gage").write_text(gage_text_semidistributed(spec), encoding="utf-8")
    (candidate / f"bacia_E{event_id}.basin").write_text(basin_text_semidistributed(event_id, params, area_km2, areas), encoding="utf-8")
    (candidate / f"chuva_E{event_id}.met").write_text(met_text_semidistributed(event_id, area_km2), encoding="utf-8")
    (candidate / f"evento_E{event_id}.control").write_text(base.control_text(spec), encoding="utf-8")
    return candidate


def jython_script(candidate: Path, spec: dict[str, object]) -> Path:
    event_id = int(spec["id"])
    score_start, score_end, input_start = spec["score_start"], spec["score_end"], spec["input_start"]
    events = [[
        str(event_id),
        f"{score_start.day:02d}{MONTHS[score_start.month - 1]}{score_start.year}",
        f"{score_start:%H%M}",
        f"{score_end.day:02d}{MONTHS[score_end.month - 1]}{score_end.year}",
        f"{score_end:%H%M}",
        f"01{MONTHS[input_start.month - 1]}{input_start.year}",
        ".",
        f"mucum_E{event_id}",
    ]]
    text = base.JYTHON_TEMPLATE.replace("__PROJECT__", candidate.as_posix()).replace("__EVENTS__", repr(events))
    script = candidate / "compute_multi_event.script"
    script.write_text(text, encoding="utf-8")
    return script


def run_candidate(output_dir: Path, index: int, params: dict[str, float], spec: dict[str, object], areas: dict[str, float], timeout: int) -> dict[str, object]:
    candidate = make_candidate(output_dir, index, params, spec, areas)
    script = jython_script(candidate, spec)
    started = time.time()
    try:
        completed = subprocess.run(
            [str(base.HEC_CMD), "-s", str(script)],
            cwd=str(base.HEC_CMD.parent),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        parsed = base.parse_result(output)
        row: dict[str, object] = {
            "index": index,
            **params,
            "status": "ok" if parsed and completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "seconds": round(time.time() - started, 3),
        }
        if parsed:
            row.update(parsed)
        else:
            row["error_tail"] = output[-3000:]
        return row
    except Exception as exc:
        return {"index": index, **params, "status": "failed", "returncode": -1, "seconds": round(time.time() - started, 3), "error_tail": repr(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=int, choices=[19, 22, 24, 26, 27, 28], required=True)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    areas = zone_areas()
    (output_dir / "zones_area.json").write_text(json.dumps({"station": "86510000", "areas_km2": areas, "total_km2": sum(areas.values()), "method": "Thiessen clipped by SRTM watershed"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    spec = semidistributed_spec(args.event)
    if not spec:
        raise SystemExit(f"no continuous source-backed two-gage rainfall window covers the score period for E{args.event}")
    params_list = base.sampled_combinations(args.count)
    rows = []
    for index, params in enumerate(params_list, 1):
        row = run_candidate(output_dir, index, params, spec, areas, args.timeout)
        rows.append(row)
        if row.get("status") == "ok":
            print("PROGRESS E%d %d/%d lag=%sh NSE=%.5f peak_error=%.4f" % (args.event, index, len(params_list), row.get("mean_abs_peak_lag_hours"), row.get("mean_nse"), row.get("mean_peak_relative_error")), flush=True)
        else:
            print(f"PROGRESS E{args.event} {index}/{len(params_list)} FAILED", flush=True)
    valid = [row for row in rows if row.get("status") == "ok"]
    best = max(valid, key=lambda row: float(row.get("fitness", -1.0e99))) if valid else None
    fields = sorted({key for row in rows for key in row})
    with (output_dir / "semidistributed_search_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {"event_id": args.event, "candidates": len(rows), "successful": len(valid), "best": best, "areas_km2": areas, "model": "two Thiessen subbasins from SRTM watershed; common parameters"}
    (output_dir / f"E{args.event}_semidistributed_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
