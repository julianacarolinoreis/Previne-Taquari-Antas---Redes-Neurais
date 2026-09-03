"""Search one common HEC-HMS parameter set across Muçum flood events.

The data windows are source-backed ANA telemetry. Missing response values are
not imputed. The reported score penalizes peak-time error in addition to NSE.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(r"D:\PREVINE\worktrees\previne-catalogo-pesquisas-20260828")
BASE = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_event_2023"
SOURCE = ROOT / "assets" / "data" / "hec_hms_audit" / "multi_event"
MULTI_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_target_multi_event.dss"
LOCAL_RAIN_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_local_rain_candidates.dss"
LOCAL_RAIN_ALL_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_local_rain_all_events.dss"
LOCAL_AVERAGE_RAIN_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_local_rain_average.dss"
SPATIAL_THIESSEN_RAIN_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_spatial_rain_thiessen.dss"
LOCAL_RAIN_CSV = ROOT / "assets" / "data" / "chuvas_horarias.csv"
INPUT_DSS = MULTI_DSS
OUT_ROOT = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_multi_event_calibration"
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")
BASIN_AREA_KM2 = 16000.0

MISSING = -1.0e20
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GRID = {
    "initial_loss": [0.0, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0],
    "constant_loss": [0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0],
    "tc_min": [1.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 240.0, 360.0, 480.0, 720.0],
    "storage_min": [1.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 240.0, 360.0, 600.0, 720.0],
    "recession_factor": [0.5, 0.7, 0.8, 0.9, 0.95, 0.98],
    "initial_flow_area_ratio": [0.0005, 0.001, 0.0025, 0.005, 0.01, 0.02, 0.05],
}


def event_specs(wanted: set[int] | None = None, rain_source: str = "ana86472000") -> list[dict[str, object]]:
    wanted = wanted or {19, 22, 24, 26, 27, 28}
    catalogue = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_eventos_usados.csv"
    result = []
    with catalogue.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            event_id = int(row["evento"])
            if event_id not in wanted or row.get("sempre_treino") != "0":
                continue
            derived = SOURCE / "derived" / f"event_{event_id}_hourly.csv"
            with derived.open(encoding="utf-8", newline="") as derived_handle:
                derived_rows = list(csv.DictReader(derived_handle))
            local_rain = {}
            if rain_source in ("local86472600", "local02851072", "local_thiessen"):
                with LOCAL_RAIN_CSV.open(encoding="utf-8", newline="") as local_handle:
                    for local_row in csv.DictReader(local_handle):
                        if rain_source == "local86472600":
                            local_rain[local_row["COD_SEQUENCIAL"]] = local_row.get("chuva_86472600", "")
                        elif rain_source == "local02851072":
                            local_rain[local_row["COD_SEQUENCIAL"]] = local_row.get("chuva_02851072", "")
                        else:
                            a = local_row.get("chuva_86472000", "").strip()
                            b = local_row.get("chuva_02851072", "").strip()
                            local_rain[local_row["COD_SEQUENCIAL"]] = (
                                str(0.4550796672 * float(a) + 0.5449203328 * float(b))
                                if a and b else ""
                            )
            valid_rain_rows = []
            for rain_row in derived_rows:
                rain_value = rain_row.get("86472000_rain_mm_sum", "")
                if rain_source == "ana86510000":
                    rain_value = rain_row.get("86510000_rain_mm_sum", "")
                if rain_source == "ana_composite":
                    rain_value = rain_row.get("86510000_rain_mm_sum", "") or rain_row.get("86472000_rain_mm_sum", "")
                if rain_source in ("local86472600", "local02851072", "local_thiessen"):
                    rain_dt = datetime.strptime(rain_row["timestamp_label"], "%Y-%m-%d %H:00:00")
                    rain_value = local_rain.get(rain_dt.strftime("%Y%m%d%H00"), "")
                if not rain_value.strip():
                    break
                valid_rain_rows.append(rain_row)
            if not valid_rain_rows:
                continue
            input_end = datetime.strptime(valid_rain_rows[-1]["timestamp_label"], "%Y-%m-%d %H:00:00")
            if rain_source in ("local86472600", "local_average") and event_id == 27:
                # Local CSV source has its first missing value at 09 May 19:00;
                # stop before it rather than inventing a zero.
                input_end = datetime(2024, 5, 9, 18)
            result.append({
                "id": event_id,
                "score_start": datetime.strptime(row["inicio_recorte"], "%Y-%m-%d %H:%M:%S"),
                "score_end": datetime.strptime(row["fim_recorte"], "%Y-%m-%d %H:%M:%S"),
                "input_start": datetime.strptime(derived_rows[0]["timestamp_label"], "%Y-%m-%d %H:00:00"),
                # HEC-HMS cannot ingest a missing precipitation value. Do not
                # impute it; end the simulation at the last observed rainfall
                # hour. All score windows remain inside this interval.
                "input_end": input_end,
                "derived": derived,
            })
    return result


def hms_date(value: datetime) -> str:
    names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"{value.day} {names[value.month - 1]} {value.year}"


def basin_text(event_id: int, params: dict[str, float], area_km2: float) -> str:
    text = (BASE / "bacia_86472000.basin").read_text(encoding="utf-8")
    text = text.replace(
        "Description: Area de drenagem declarada no inventario ANA para a estacao 86472000",
        "Description: Area de drenagem declarada no inventario ANA para a estacao de resposta 86510000",
    )
    replacements = {
        "Basin: Bacia 86472000 13000km2": f"Basin: Bacia E{event_id} {area_km2:g}km2",
        "Subbasin: Bacia_86472000": f"Subbasin: Bacia_86472000_E{event_id}",
        "Downstream: Saida_86472000": f"Downstream: Saida_E{event_id}",
        "Junction: Saida_86472000": f"Junction: Saida_E{event_id}",
        "Observed Hydrograph Gage: Q_86472000": f"Observed Hydrograph Gage: Q_E{event_id}",
        "Computation Point: Saida_86472000": f"Computation Point: Saida_E{event_id}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text, area_count = re.subn(r"(?m)^(\s*Area:\s*)13000(?:\.0)?$", rf"\g<1>{area_km2:g}", text)
    if area_count != 1:
        raise ValueError("basin area not found")
    for label, value in {
        "Initial Loss": params["initial_loss"],
        "Constant Loss Rate": params["constant_loss"],
        "Time of Concentration": params["tc_min"],
        "Storage Coefficient": params["storage_min"],
        "Recession Factor": params["recession_factor"],
        "Initial Flow/Area Ratio": params["initial_flow_area_ratio"],
    }.items():
        text, count = re.subn(rf"(?m)^(\s*{re.escape(label)}:\s*)[^\r\n]+$", rf"\g<1>{value:g}", text)
        if count != 1:
            raise ValueError(f"parameter not found: {label}")
    return text


def control_text(spec: dict[str, object]) -> str:
    event_id = int(spec["id"])
    start = spec["input_start"]
    end = spec["input_end"]
    assert isinstance(start, datetime) and isinstance(end, datetime)
    return f"""Control: Evento E{event_id}
     Description: Janela com aquecimento e cauda da telemetria ANA
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30
     Version: 4.13
     Start Date: {hms_date(start)}
     Start Time: {start:%H:%M}
     End Date: {hms_date(end)}
     End Time: {end:%H:%M}
     Time Interval: 60
End:
"""


def met_text(spec: dict[str, object], area_km2: float, rain_source: str = "ana86472000") -> str:
    event_id = int(spec["id"])
    rain_description = "Chuva espacializada Thiessen: ANA 86472000 + 02851072" if rain_source == "local_thiessen" else "Chuva horaria candidata ANA 86472000"
    return f"""Meteorology: Chuva E{event_id}
     Description: {rain_description}
     Last Modified Date: 02 September 2026
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
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30
     Allow Depth Override: Yes
End:

Subbasin: Bacia_86472000_E{event_id}
     Gage: Chuva_E{event_id}
End:
"""


def gage_text(specs: list[dict[str, object]]) -> str:
    sections = ["Gage Manager: Mucum multi-event\n     Version: 4.13\n     Filepath Separator: \\\n+End:\n"]
    for spec in specs:
        event_id = int(spec["id"])
        start = spec["input_start"]
        end = spec["input_end"]
        assert isinstance(start, datetime) and isinstance(end, datetime)
        dpart = f"01{MONTHS[start.month - 1]}{start.year}"
        sections.append(f"""Gage: Chuva_E{event_id}
     Gage: Chuva_E{event_id}
     Gage Type: Precipitation
     Description: Chuva ANA 86472000 do evento E{event_id}
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: mucum_multi_event.dss
     Pathname: /MUCUM/RAIN_E{event_id}/PRECIP-INC/{dpart}/1Hour/OBS/
     Variant: Variant-1
       Start Time: {start.day} {MONTHS[start.month - 1]} {start.year}, {start:%H:%M}
       End Time: {end.day} {MONTHS[end.month - 1]} {end.year}, {end:%H:%M}
     End Variant: Variant-1
End:

Gage: Q_E{event_id}
     Gage: Q_E{event_id}
     Gage Type: Flow
     Description: Vazao ANA 86510000 do evento E{event_id}
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: mucum_multi_event.dss
     Pathname: /MUCUM/OBS_E{event_id}/FLOW/{dpart}/1Hour/OBS/
     Variant: Variant-1
       Start Time: {start.day} {MONTHS[start.month - 1]} {start.year}, {start:%H:%M}
       End Time: {end.day} {MONTHS[end.month - 1]} {end.year}, {end:%H:%M}
     End Variant: Variant-1
End:
""")
    return "\n".join(sections)


def project_text(specs: list[dict[str, object]]) -> str:
    sections = ["""Project: mucum_multi_event
     Description: Calibracao conjunta de eventos historicos de Mucum
     Version: 4.13
     Filepath Separator: \\
     DSS File Name: mucum_multi_event.dss
     Time Zone ID: America/Sao_Paulo
End:
"""]
    for spec in specs:
        event_id = int(spec["id"])
        sections.append(f"""Precipitation: Chuva E{event_id}
     Filename: chuva_E{event_id}.met
End:

Basin: Bacia E{event_id} 16000km2
     Filename: bacia_E{event_id}.basin
End:

Control: Evento E{event_id}
     FileName: evento_E{event_id}.control
End:
""")
    return "\n".join(sections)


def run_text(specs: list[dict[str, object]]) -> str:
    sections = []
    for spec in specs:
        event_id = int(spec["id"])
        sections.append(f"""Run: Calibracao E{event_id}
     Description: Execucao do evento E{event_id}
     Log File: multi_calibracao.log
     DSS File: multi_results.dss
     Is Save Spatial Results: No
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30:00
     Basin: Bacia E{event_id} 16000km2
     Precip: Chuva E{event_id}
     Control: Evento E{event_id}
     Save State Type: None
     Time-Series Output: Save All
End:
""")
    return "\n".join(sections)


def single_project_text(spec: dict[str, object], area_km2: float) -> str:
    event_id = int(spec["id"])
    return f"""Project: mucum_E{event_id}
     Description: Calibracao conjunta de eventos historicos de Mucum; projeto isolado E{event_id}
     Version: 4.13
     Filepath Separator: \\
     DSS File Name: mucum_multi_event.dss
     Time Zone ID: America/Sao_Paulo
End:

Precipitation: Chuva E{event_id}
     Filename: chuva_E{event_id}.met
End:

Basin: Bacia E{event_id} {area_km2:g}km2
     Filename: bacia_E{event_id}.basin
End:

Control: Evento E{event_id}
     FileName: evento_E{event_id}.control
End:
"""


def single_run_text(spec: dict[str, object], area_km2: float) -> str:
    event_id = int(spec["id"])
    return f"""Run: Calibracao
     Description: Execucao do evento E{event_id}
     Log File: calibracao.log
     DSS File: output.dss
     Is Save Spatial Results: No
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30:00
     Basin: Bacia E{event_id} {area_km2:g}km2
     Precip: Chuva E{event_id}
     Control: Evento E{event_id}
     Save State Type: None
     Time-Series Output: Save All
End:
"""


def single_gage_text(spec: dict[str, object], rain_source: str = "ana86472000") -> str:
    event_id = int(spec["id"])
    start = spec["input_start"]
    end = spec["input_end"]
    assert isinstance(start, datetime) and isinstance(end, datetime)
    dpart = f"01{MONTHS[start.month - 1]}{start.year}"
    rain_filename = "mucum_multi_event.dss"
    rain_path = f"/MUCUM/RAIN_E{event_id}/PRECIP-INC/{dpart}/1Hour/OBS/"
    if rain_source == "ana86510000":
        rain_path = f"/MUCUM/RAIN_E{event_id}_86510000/PRECIP-INC/{dpart}/1Hour/OBS/"
    if rain_source == "ana_composite":
        rain_path = f"/MUCUM/RAIN_E{event_id}_COMPOSITE/PRECIP-INC/{dpart}/1Hour/OBS/"
    if rain_source == "local86472600":
        rain_filename = "mucum_local_rain_all_events.dss"
        rain_path = f"/MUCUM/RAIN_E{event_id}_86472600/PRECIP-INC/{dpart}/1Hour/OBS/"
    if rain_source == "local02851072":
        rain_filename = "mucum_local_rain_all_events.dss"
        rain_path = f"/MUCUM/RAIN_E{event_id}_02851072/PRECIP-INC/{dpart}/1Hour/OBS/"
    if rain_source == "local_average" and event_id == 27:
        rain_filename = "mucum_local_rain_average.dss"
        rain_path = "/MUCUM/RAIN_E27_AVG_86472000_86472600/PRECIP-INC/01Apr2024/1Hour/OBS/"
    if rain_source == "local_thiessen":
        rain_filename = "mucum_spatial_rain_thiessen.dss"
        rain_path = f"/MUCUM/RAIN_E{event_id}_THIESSEN_86510000/PRECIP-INC/{dpart}/1Hour/OBS/"
    return f"""Gage Manager: Mucum E{event_id}
     Gage Manager: Mucum E{event_id}
     Version: 4.13
     Filepath Separator: \\
End: 

Gage: Chuva_E{event_id}
     Gage: Chuva_E{event_id}
     Gage Type: Precipitation
     Description: Chuva ANA 86472000 do evento E{event_id}
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: {rain_filename}
     Pathname: {rain_path}
     Variant: Variant-1
       Start Time: {start.day} {MONTHS[start.month - 1]} {start.year}, {start:%H:%M}
       End Time: {end.day} {MONTHS[end.month - 1]} {end.year}, {end:%H:%M}
     End Variant: Variant-1
End:

Gage: Q_E{event_id}
     Gage: Q_E{event_id}
     Gage Type: Flow
     Description: Vazao ANA 86510000 do evento E{event_id}
     Last Modified Date: 02 September 2026
     Last Modified Time: 20:30
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: mucum_multi_event.dss
     Pathname: /MUCUM/OBS_E{event_id}/FLOW/{dpart}/1Hour/OBS/
     Variant: Variant-1
       Start Time: {start.day} {MONTHS[start.month - 1]} {start.year}, {start:%H:%M}
       End Time: {end.day} {MONTHS[end.month - 1]} {end.year}, {end:%H:%M}
     End Variant: Variant-1
End:
"""


def make_candidate(index: int, params: dict[str, float], specs: list[dict[str, object]], rain_source: str = "ana86472000", area_km2: float = 16000.0) -> Path:
    candidate = OUT_ROOT / "search" / f"candidate_{index:04d}"
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        event_id = int(spec["id"])
        event_dir = candidate / f"event_E{event_id}"
        event_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(INPUT_DSS, event_dir / "mucum_multi_event.dss")
        if rain_source in ("local86472600", "local02851072"):
            shutil.copy2(LOCAL_RAIN_ALL_DSS, event_dir / "mucum_local_rain_all_events.dss")
        if rain_source == "local_thiessen":
            shutil.copy2(SPATIAL_THIESSEN_RAIN_DSS, event_dir / "mucum_spatial_rain_thiessen.dss")
        if rain_source == "local_average" and event_id == 27:
            shutil.copy2(LOCAL_AVERAGE_RAIN_DSS, event_dir / "mucum_local_rain_average.dss")
        (event_dir / f"mucum_E{event_id}.hms").write_text(single_project_text(spec, area_km2), encoding="utf-8")
        (event_dir / f"mucum_E{event_id}.run").write_text(single_run_text(spec, area_km2), encoding="utf-8")
        (event_dir / f"mucum_E{event_id}.gage").write_text(single_gage_text(spec, rain_source), encoding="utf-8")
        (event_dir / f"bacia_E{event_id}.basin").write_text(basin_text(event_id, params, area_km2), encoding="utf-8")
        (event_dir / f"chuva_E{event_id}.met").write_text(met_text(spec, area_km2, rain_source), encoding="utf-8")
        (event_dir / f"evento_E{event_id}.control").write_text(control_text(spec), encoding="utf-8")
    return candidate


JYTHON_TEMPLATE = r'''from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
import csv
import math

events = __EVENTS__

def values_by_time(series):
    return {int(series.times[i]): float(series.values[i]) for i in range(series.numberValues)}

def merged_by_event(dss, event_id, kind):
    prefix = "//Saida_E" + event_id + "/" + kind + "/"
    merged = {}
    for pathname in dss.getCatalogedPathnames():
        if pathname.startswith(prefix) and "/1Hour/RUN:Calibracao/" in pathname:
            merged.update(values_by_time(dss.get(pathname)))
    return merged

all_metrics = []
with open(r"__PROJECT__/multi_event_series.csv", "wb") as series_handle:
    series_writer = csv.writer(series_handle)
    series_writer.writerow(["event_id", "time_value", "observed_m3s", "simulated_m3s"])
    for event_id, score_start_date, score_start_time, score_end_date, score_end_time, dpart, event_dir, project_name in events:
        event_project = r"__PROJECT__/" + event_dir
        OpenProject(project_name, event_project)
        Compute("Calibracao")
        output = event_project + "/output.dss"
        dss = HecDss.open(output)
        sim_map = merged_by_event(dss, event_id, "FLOW")
        obs_map = merged_by_event(dss, event_id, "FLOW-OBSERVED")
        if not sim_map or not obs_map:
            dss.close()
            raise ValueError("missing HEC-HMS output for event " + event_id)
        start_value = HecTime(score_start_date, score_start_time).value()
        end_value = HecTime(score_end_date, score_end_time).value()
        pairs = [(t, obs_map[t], sim_map[t]) for t in sorted(set(sim_map).intersection(obs_map)) if start_value <= t <= end_value and obs_map[t] > -1.0e20 and sim_map[t] > -1.0e20]
        if len(pairs) < 24:
            dss.close()
            raise ValueError("less than 24 paired hours for event " + event_id)
        for pair in pairs:
            series_writer.writerow([event_id, pair[0], pair[1], pair[2]])
        mean_obs = sum(pair[1] for pair in pairs) / len(pairs)
        mae = sum(abs(pair[2] - pair[1]) for pair in pairs) / len(pairs)
        rmse = math.sqrt(sum((pair[2] - pair[1]) ** 2 for pair in pairs) / len(pairs))
        denominator = sum((pair[1] - mean_obs) ** 2 for pair in pairs)
        nse = 1.0 - sum((pair[2] - pair[1]) ** 2 for pair in pairs) / denominator
        observed_peak = max(pairs, key=lambda pair: pair[1])
        simulated_peak = max(pairs, key=lambda pair: pair[2])
        peak_lag_hours = (simulated_peak[0] - observed_peak[0]) / 60.0
        peak_relative_error = abs(simulated_peak[2] - observed_peak[1]) / observed_peak[1]
        all_metrics.append((event_id, len(pairs), mae, rmse, nse, observed_peak[1], simulated_peak[2], peak_lag_hours, peak_relative_error))
        dss.close()

with open(r"__PROJECT__/multi_event_metrics.csv", "wb") as metrics_handle:
    metrics_writer = csv.writer(metrics_handle)
    metrics_writer.writerow(["event_id", "pairs", "mae_m3s", "rmse_m3s", "nse", "observed_peak_m3s", "simulated_peak_m3s", "peak_lag_hours", "peak_relative_error"])
    for metric in all_metrics:
        metrics_writer.writerow(metric)

mean_nse = sum(metric[4] for metric in all_metrics) / len(all_metrics)
mean_abs_peak_lag_hours = sum(abs(metric[7]) for metric in all_metrics) / len(all_metrics)
mean_peak_relative_error = sum(metric[8] for metric in all_metrics) / len(all_metrics)
fitness = mean_nse - 0.01 * mean_abs_peak_lag_hours - 0.2 * mean_peak_relative_error
print("RESULT|events=%d|mean_nse=%.10f|mean_abs_peak_lag_hours=%.10f|mean_peak_relative_error=%.10f|fitness=%.10f" % (len(all_metrics), mean_nse, mean_abs_peak_lag_hours, mean_peak_relative_error, fitness))
Exit(1)
'''


def jython_script(candidate: Path, specs: list[dict[str, object]]) -> Path:
    events = []
    for spec in specs:
        score_start = spec["score_start"]
        score_end = spec["score_end"]
        input_start = spec["input_start"]
        assert isinstance(score_start, datetime) and isinstance(score_end, datetime) and isinstance(input_start, datetime)
        events.append([
            str(spec["id"]),
            f"{score_start.day:02d}{MONTHS[score_start.month - 1]}{score_start.year}",
            f"{score_start:%H%M}",
            f"{score_end.day:02d}{MONTHS[score_end.month - 1]}{score_end.year}",
            f"{score_end:%H%M}",
            f"01{MONTHS[input_start.month - 1]}{input_start.year}",
            f"event_E{spec['id']}",
            f"mucum_E{spec['id']}",
        ])
    text = JYTHON_TEMPLATE.replace("__PROJECT__", candidate.as_posix()).replace("__EVENTS__", repr(events))
    script = candidate / "compute_multi_event.script"
    script.write_text(text, encoding="utf-8")
    return script


def parse_result(output: str) -> dict[str, float] | None:
    match = re.search(r"RESULT\|([^\r\n]+)", output)
    if not match:
        return None
    result = {}
    for item in match.group(1).split("|"):
        key, value = item.split("=", 1)
        result[key] = float(value)
    return result


def run_candidate(index: int, params: dict[str, float], specs: list[dict[str, object]], timeout: int, rain_source: str, area_km2: float) -> dict[str, object]:
    candidate = make_candidate(index, params, specs, rain_source, area_km2)
    script = jython_script(candidate, specs)
    started = time.time()
    try:
        completed = subprocess.run([str(HEC_CMD), "-s", str(script)], cwd=str(HEC_CMD.parent), capture_output=True, text=True, timeout=timeout, check=False)
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        parsed = parse_result(output)
        row: dict[str, object] = {"index": index, **params, "status": "ok" if parsed and completed.returncode == 0 else "failed", "returncode": completed.returncode, "seconds": round(time.time() - started, 3)}
        if parsed:
            row.update(parsed)
        else:
            row["error_tail"] = output[-2500:]
        return row
    except Exception as exc:
        return {"index": index, **params, "status": "failed", "returncode": -1, "seconds": round(time.time() - started, 3), "error_tail": repr(exc)}


def sampled_combinations(samples: int) -> list[dict[str, float]]:
    keys = list(GRID)
    all_values = [dict(zip(keys, values)) for values in itertools.product(*(GRID[key] for key in keys))]
    anchors = [
        {"initial_loss": 2.5, "constant_loss": 1.0, "tc_min": 45.0, "storage_min": 5.0, "recession_factor": 0.7, "initial_flow_area_ratio": 0.005},
        {"initial_loss": 0.0, "constant_loss": 0.5, "tc_min": 60.0, "storage_min": 1.0, "recession_factor": 0.8, "initial_flow_area_ratio": 0.005},
        {"initial_loss": 5.0, "constant_loss": 0.5, "tc_min": 45.0, "storage_min": 5.0, "recession_factor": 0.7, "initial_flow_area_ratio": 0.005},
        # Best eventwise combinations from the first target-station scan;
        # keep them as reproducible seeds when the area/source is changed.
        {"initial_loss": 10.0, "constant_loss": 1.0, "tc_min": 60.0, "storage_min": 60.0, "recession_factor": 0.9, "initial_flow_area_ratio": 0.001},
        {"initial_loss": 10.0, "constant_loss": 0.1, "tc_min": 45.0, "storage_min": 30.0, "recession_factor": 0.7, "initial_flow_area_ratio": 0.001},
        {"initial_loss": 5.0, "constant_loss": 0.25, "tc_min": 15.0, "storage_min": 30.0, "recession_factor": 0.7, "initial_flow_area_ratio": 0.02},
        {"initial_loss": 5.0, "constant_loss": 0.25, "tc_min": 30.0, "storage_min": 30.0, "recession_factor": 0.5, "initial_flow_area_ratio": 0.001},
        {"initial_loss": 5.0, "constant_loss": 4.0, "tc_min": 5.0, "storage_min": 60.0, "recession_factor": 0.9, "initial_flow_area_ratio": 0.0025},
        {"initial_loss": 20.0, "constant_loss": 2.0, "tc_min": 30.0, "storage_min": 30.0, "recession_factor": 0.9, "initial_flow_area_ratio": 0.02},
        {"initial_loss": 5.0, "constant_loss": 0.25, "tc_min": 15.0, "storage_min": 30.0, "recession_factor": 0.7, "initial_flow_area_ratio": 0.02},
    ]
    # Fine timing neighborhood around the fast-response solution found for
    # the May 2024 replay.  These values are intentionally explicit rather
    # than a post-hoc time shift: the timing is still produced by HEC-HMS.
    for tc_min in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0):
        for storage_min in (60.0, 90.0, 120.0, 150.0, 180.0, 240.0):
            anchors.append({
                "initial_loss": 1.0,
                "constant_loss": 4.0,
                "tc_min": tc_min,
                "storage_min": storage_min,
                "recession_factor": 0.98,
                "initial_flow_area_ratio": 0.005,
            })
    # Local timing neighborhoods for the other replay events.  They refine
    # Tc/storage jointly; no synthetic timestamp offset is introduced.
    for tc_min in (10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 60.0):
        for storage_min in (30.0, 45.0, 60.0, 75.0, 90.0, 120.0):
            anchors.append({
                "initial_loss": 2.5,
                "constant_loss": 2.0,
                "tc_min": tc_min,
                "storage_min": storage_min,
                "recession_factor": 0.8,
                "initial_flow_area_ratio": 0.0025,
            })
    for tc_min in (10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 45.0):
        for storage_min in (15.0, 20.0, 30.0, 45.0, 60.0):
            anchors.append({
                "initial_loss": 5.0,
                "constant_loss": 0.5,
                "tc_min": tc_min,
                "storage_min": storage_min,
                "recession_factor": 0.7,
                "initial_flow_area_ratio": 0.0025,
            })
    for tc_min in (5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0):
        for storage_min in (30.0, 45.0, 60.0, 90.0, 120.0):
            anchors.append({
                "initial_loss": 20.0,
                "constant_loss": 0.75,
                "tc_min": tc_min,
                "storage_min": storage_min,
                "recession_factor": 0.9,
                "initial_flow_area_ratio": 0.01,
            })
    if samples >= len(all_values):
        return all_values
    remaining = [item for item in all_values if item not in anchors]
    rng = random.Random(20260903)
    return (anchors + rng.sample(remaining, max(0, samples - len(anchors))))[:samples]


def main() -> int:
    global OUT_ROOT, INPUT_DSS, BASIN_AREA_KM2
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=180)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--events", default="19,22,24,26,27,28")
    parser.add_argument("--rain-source", choices=["ana86472000", "ana86510000", "ana_composite", "local86472600", "local02851072", "local_average", "local_thiessen"], default="ana86472000")
    parser.add_argument("--output-dir", type=Path, default=OUT_ROOT)
    parser.add_argument("--input-dss", type=Path, default=MULTI_DSS)
    parser.add_argument("--area-km2", type=float, default=BASIN_AREA_KM2)
    args = parser.parse_args()
    if not HEC_CMD.exists() or not MULTI_DSS.exists():
        raise SystemExit("HEC-HMS or multi-event DSS is missing")
    wanted = {int(item.strip()) for item in args.events.split(",") if item.strip()}
    OUT_ROOT = args.output_dir.resolve()
    INPUT_DSS = args.input_dss.resolve()
    BASIN_AREA_KM2 = args.area_km2
    specs = event_specs(wanted, args.rain_source)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    params_list = sampled_combinations(args.samples)
    if args.limit:
        params_list = params_list[:args.limit]
    rows: list[dict[str, object]] = []
    result_path = OUT_ROOT / "multi_event_search_results.csv"
    for index, params in enumerate(params_list, 1):
        row = run_candidate(index, params, specs, args.timeout, args.rain_source, BASIN_AREA_KM2)
        rows.append(row)
        valid = [item for item in rows if item.get("status") == "ok"]
        if valid:
            best = max(valid, key=lambda item: float(item.get("fitness", -1.0e99)))
            print("PROGRESS index=%d/%d ok=%d best_fitness=%.6f mean_nse=%.6f abs_lag=%.3fh" % (index, len(params_list), len(valid), float(best["fitness"]), float(best["mean_nse"]), float(best["mean_abs_peak_lag_hours"])), flush=True)
        else:
            print("PROGRESS index=%d/%d ok=0" % (index, len(params_list)), flush=True)
        fields = sorted({key for item in rows for key in item})
        with result_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    valid = [item for item in rows if item.get("status") == "ok"]
    if valid:
        best = max(valid, key=lambda item: float(item.get("fitness", -1.0e99)))
        (OUT_ROOT / "multi_event_search_best.json").write_text(json.dumps(best, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("BEST", json.dumps(best, ensure_ascii=False), flush=True)
    print("DONE", len(rows), "candidates", len(valid), "successful", flush=True)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
