#!/usr/bin/env python3
"""Test E28 physical parameters on the observed, gap-free E24 prefix.

The E24 scoring interval ends before the first missing hourly rainfall/flow
record. This is a censored transfer test, never a full-event calibration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import build_hec_hms_network_station_distributed as network
from build_hec_hms_hybrid_e28 import PARAMS as E28_PARAMS
from build_hybrid_e28_rain_dss import read_station
from build_santa_tereza_raw_rain_dss import read_event
from extract_hec_hms_network_all_events import extract_event, score


ROOT = Path(__file__).resolve().parents[1]
END = datetime(2023, 11, 24, 19)
START = datetime(2023, 11, 16)
AREA_KM2 = 15965.207
SOURCE_DSS = ROOT / "assets/data/hec_hms_calibration/mucum_santa_tereza_raw_rain_events.dss"
MUCUM_RAW = ROOT / "assets/data/hec_hms_audit/raw/ana/supplemental/telemetry_86510000_E24.xml"
DEFAULT_OUTPUT = ROOT / "assets/data/hec_hms_integrated_taquari_antas/network_replay_e24_censored_transfer"
UPSTREAM_PATH = "/MUCUM/RAIN_E24_86472000/PRECIP-INC/01Nov2023/1Hour/OBS/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_hours() -> list[datetime]:
    return [START + timedelta(hours=index) for index in range(int((END - START).total_seconds() // 3600) + 1)]


def write_rain_csv(output: Path) -> dict[str, object]:
    series = {"86472600": read_event("E24"), "86510000": read_station(MUCUM_RAW)}
    hours = expected_hours()
    for station, values in series.items():
        missing = [stamp.isoformat(sep=" ") for stamp in hours if stamp not in values]
        if missing:
            raise RuntimeError(f"{station} missing inside censored prefix: {missing[:5]}")
    path = output / "rain_e24_prefix.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["station", "timestamp_local", "rain_mm", "source_record_count"])
        for station, values in series.items():
            for stamp in hours:
                rain, count = values[stamp]
                writer.writerow([station, stamp.isoformat(sep=" "), f"{rain:.6f}", count])
    return {"path": path, "hours_per_station": len(hours),
            "total_mm": {station: round(sum(values[t][0] for t in hours), 3)
                         for station, values in series.items()}}


def build_rain_dss(output: Path, csv_path: Path) -> Path:
    destination = output / "rain_e24_prefix.dss"
    script = output / "write_rain_e24_prefix.script"
    script.write_text(
        "from hec.heclib.dss import HecDss\n"
        "from hec.heclib.util import HecTime\n"
        "from hec.io import TimeSeriesContainer\n"
        "import csv\n"
        f'base = HecDss.open("{SOURCE_DSS.as_posix()}")\n'
        f'target = HecDss.open("{destination.as_posix()}")\n'
        f'upstream = base.get("{UPSTREAM_PATH}")\n'
        "if upstream.numberValues <= 0:\n    raise RuntimeError('upstream E24 DSS is empty')\n"
        f'upstream.fullName = "{UPSTREAM_PATH}"\n'
        "target.put(upstream)\n"
        f'with open(r"{csv_path.as_posix()}", "rb") as handle:\n    rows = list(csv.DictReader(handle))\n'
        "months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']\n"
        "for station in ['86472600', '86510000']:\n"
        "    selected = [row for row in rows if row['station'] == station]\n"
        "    times, values = [], []\n"
        "    for row in selected:\n"
        "        date, clock = row['timestamp_local'].split(' ')\n"
        "        year, month, day = [int(value) for value in date.split('-')]\n"
        "        hour = int(clock.split(':')[0]) * 100\n"
        "        stamp = HecTime('%02d%s%04d' % (day, months[month-1], year), '%04d' % hour)\n"
        "        times.append(stamp.value())\n        values.append(float(row['rain_mm']))\n"
        "    if len(times) != 212 or any(times[i] - times[i-1] != 60 for i in range(1, len(times))):\n"
        "        raise RuntimeError('E24 prefix DSS cadence failed for ' + station)\n"
        "    item = TimeSeriesContainer()\n"
        "    item.fullName = '/MUCUM/RAIN_E24_%s/PRECIP-INC/01Nov2023/1Hour/OBS/' % station\n"
        "    item.interval = 60\n    item.times = times\n    item.values = values\n"
        "    item.numberValues = len(values)\n    item.units = 'MM'\n    item.type = 'PER-CUM'\n"
        "    target.put(item)\n"
        "base.close()\ntarget.close()\n"
        "print('E24_PREFIX_RAIN_DSS_OK')\n"
        "from hms.model.JythonHms import Exit\nExit(1)\n",
        encoding="utf-8",
    )
    result = subprocess.run([str(network.HEC_CMD), "-s", str(script)], cwd=network.HEC_CMD.parent,
                            capture_output=True, text=True, timeout=180, check=False)
    (output / "write_rain_e24_prefix.log").write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr,
                                                    encoding="utf-8")
    if "E24_PREFIX_RAIN_DSS_OK" not in result.stdout or not destination.exists():
        raise RuntimeError(f"HEC rainfall DSS write failed, returncode={result.returncode}")
    return destination


def add_mucum_gage(source: str) -> str:
    gages = network.blocks(source, "Gage: ")
    santa = next(block for block in gages if "Gage: Chuva_86472600_E24" in block)
    flow = next(block for block in gages if "Gage: Q_E24" in block)
    mucum = santa.replace("Chuva_86472600_E24", "Chuva_86510000_E24").replace("86472600", "86510000")
    return source.replace(flow, mucum.strip() + "\n\n" + flow, 1)


def make_case(output: Path, case: str, params: dict[str, float], rain_dss: Path) -> dict:
    use_local = case == "three_station"
    case_dir = output / case
    old_rain = network.RAIN_DSS
    network.RAIN_DSS = rain_dss
    try:
        manifest = network.build_event("E24", case_dir, {"E24"} if use_local else set(),
                                       "eventwise", params_override=params)
    finally:
        network.RAIN_DSS = old_rain
    event_dir = case_dir / "E24"
    control_path = event_dir / "evento_E24.control"
    control = control_path.read_text(encoding="utf-8")
    control = re.sub(r"(?m)^(\s*End Date:\s*).*$", r"\g<1>24 November 2023", control)
    control = re.sub(r"(?m)^(\s*End Time:\s*).*$", r"\g<1>19:00", control)
    control_path.write_text(control, encoding="utf-8")
    # The inherited three Muskingum steps trigger HEC WARNING 41169 with K=1 h
    # at a one-hour compute interval. One step keeps the physical K and X but
    # satisfies the numerical stability interval for this discretization.
    basin_path = event_dir / "bacia_E24.basin"
    basin, step_count = re.subn(r"(?m)^(\s*Muskingum Steps:\s*)3$", r"\g<1>1",
                                basin_path.read_text(encoding="utf-8"))
    if step_count != 2:
        raise RuntimeError(f"Expected two Muskingum reaches, found {step_count}")
    basin_path.write_text(basin, encoding="utf-8")
    if use_local:
        met = event_dir / "chuva_E24.met"
        met.write_text(network.set_gage(met.read_text(encoding="utf-8"), "SB_INC_MUCUM_E24",
                                        "Chuva_86510000_E24"), encoding="utf-8")
        gage = event_dir / "taquari_antas_E24.gage"
        gage.write_text(add_mucum_gage(gage.read_text(encoding="utf-8")), encoding="utf-8")
        # build_event has copied the custom rain DSS into this isolated case.
    manifest["score_policy"] = "censored_before_first_missing_hour; 16 Nov 00 to 24 Nov 19"
    manifest["excluded_tail"] = "24 Nov 20 to 25 Nov 23; no metrics claimed there"
    manifest["initial_state_policy"] = "initial_flow_per_area_from_first_observed_Mucum_score_hour"
    (event_dir / "event_network_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run = network.run_event("E24", event_dir)
    if not run["ok_marker"]:
        raise RuntimeError(f"HEC compute failed in {case}: {run}")
    log = (event_dir / "Calibracao.log").read_text(encoding="utf-8", errors="replace")
    warnings = [line for line in log.splitlines() if line.startswith(("WARNING", "ERROR"))]
    if warnings:
        raise RuntimeError(f"HEC compute warnings/errors in {case}: {warnings}")
    pairs = [row for row in extract_event("E24", event_dir)
             if datetime(1899, 12, 31) + timedelta(minutes=row[0]) <= END]
    return {"case": case, "run": run, "compute_warning_count": len(warnings),
            "muskingum_steps_per_reach": 1, "metrics": score("E24", pairs),
            "pairs": pairs,
            "manifest": str((event_dir / "event_network_manifest.json").relative_to(ROOT))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True,
                        help="Existing, read-only E24 HEC-HMS base project directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    base = args.base_dir.resolve()
    if not (base / "E24" / "taquari_antas_E24.hms").exists():
        raise FileNotFoundError(base / "E24" / "taquari_antas_E24.hms")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    csv_info = write_rain_csv(output)
    rain_dss = build_rain_dss(output, csv_info["path"])
    with (base / "E24" / "network_pairs_scored.csv").open(encoding="utf-8", newline="") as handle:
        first = next(csv.DictReader(handle))
    initial_ratio = float(first["observed_m3s"]) / AREA_KM2
    params = {**E28_PARAMS, "initial_flow_ratio": initial_ratio}
    old_base = network.BASE
    network.BASE = base
    try:
        cases = [make_case(output, case, params, rain_dss)
                 for case in ("proxy_upstream", "three_station")]
    finally:
        network.BASE = old_base
    proxy, distributed = (case.pop("pairs") for case in cases)
    if len(proxy) != len(distributed) or any(a[0] != b[0] or a[1] != b[1]
                                              for a, b in zip(proxy, distributed)):
        raise RuntimeError("Cases are not paired on identical observed hours")
    series_path = output / "e24_censored_transfer_series.csv"
    with series_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_local", "observed_m3s", "proxy_upstream_m3s",
                         "three_station_m3s"])
        for baseline, local in zip(proxy, distributed):
            stamp = datetime(1899, 12, 31) + timedelta(minutes=baseline[0])
            writer.writerow([stamp.isoformat(sep=" "), baseline[1], baseline[2], local[2]])
    baseline_metrics = cases[0]["metrics"]
    local_metrics = cases[1]["metrics"]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "censored_independent_event_transfer_not_promoted",
        "research_only": True,
        "event": "E24",
        "score_window": {"start": START.isoformat(sep=" "), "end": END.isoformat(sep=" "),
                         "hours": len(expected_hours())},
        "full_event_coverage": "incomplete; tail after 24 Nov 19 excluded explicitly",
        "model_domain": "Three nested incremental subbasins ending at ANA 86510000; not the reconstructed full-basin model",
        "source_base_project": str(base),
        "input_sha256": {
            "base_project_hms": sha256(base / "E24" / "taquari_antas_E24.hms"),
            "base_project_basin": sha256(base / "E24" / "bacia_E24.basin"),
            "base_observed_pairs": sha256(base / "E24" / "network_pairs_scored.csv"),
            "upstream_rain_dss": sha256(SOURCE_DSS),
            "santa_tereza_raw_xml": sha256(ROOT / "assets/data/hec_hms_audit/raw/ana/events/telemetry_86472600_E24.xml"),
            "mucum_raw_xml": sha256(MUCUM_RAW),
        },
        "rainfall": {"upstream": str(SOURCE_DSS), "local_csv": str(csv_info["path"]),
                     "local_dss": str(rain_dss), "totals_mm": csv_info["total_mm"]},
        "parameters": params,
        "selection": "E28 hybrid candidate physical parameters transferred unchanged; E24 initial flow state from first observed hour; numerical Muskingum steps corrected from 3 to 1 in both cases after inherited WARNING 41169",
        "paired_series": str(series_path.relative_to(ROOT)),
        "comparison": {
            "mae_reduction_m3s": baseline_metrics["mae_m3s"] - local_metrics["mae_m3s"],
            "rmse_reduction_m3s": baseline_metrics["rmse_m3s"] - local_metrics["rmse_m3s"],
            "nse_increase": local_metrics["nse"] - baseline_metrics["nse"],
            "peak_absolute_error_increase_m3s": abs(local_metrics["simulated_peak_m3s"] - local_metrics["observed_peak_m3s"]) - abs(baseline_metrics["simulated_peak_m3s"] - baseline_metrics["observed_peak_m3s"]),
            "peak_lag_unchanged_hours": local_metrics["peak_lag_hours"],
            "interpretation": "Distributed rainfall improves whole-series fit but worsens peak magnitude; neither case removes the 2 h peak lag.",
        },
        "cases": cases,
        "limits": ["Censored window does not validate the full E24 tail.",
                   "Rainfall at the gauges is a spatial proxy for incremental areas.",
                   "Santa Tereza observed discharge remains unavailable.",
                   "No operational promotion or flood extent is implied."],
    }
    (output / "e24_censored_transfer_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": [(item["case"], item["metrics"])
                                                      for item in cases]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
