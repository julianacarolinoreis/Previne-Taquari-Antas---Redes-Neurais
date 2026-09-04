#!/usr/bin/env python3
"""Build a station-distributed rainfall variant of the nested HEC-HMS network."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")
BASE = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_replay_all_events"
RAIN_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_santa_tereza_raw_rain_events.dss"
AUDIT = ROOT / "assets" / "data" / "hec_hms_audit" / "santa_tereza_event_input_audit_latest.json"
RAW_DSS_REPORT = ROOT / "assets" / "data" / "hec_hms_audit" / "derived" / "santa_tereza_raw_rain_dss_report.json"
DEFAULT_OUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_replay_station_distributed_all_events"
WINDOWS = {
    "E19": ("06May2023", "1000", "08May2023", "1400"),
    "E22": ("04Sep2023", "0000", "12Sep2023", "0700"),
    "E24": ("16Nov2023", "0000", "25Nov2023", "2300"),
    "E27": ("29Apr2024", "1600", "09May2024", "2000"),
    "E28": ("16Jun2024", "1000", "25Jun2024", "0200"),
}
DATE_PARTS = {"E19": "01May2023", "E22": "01Sep2023", "E24": "01Nov2023", "E27": "01Apr2024", "E28": "01Jun2024"}
COMMON_PARAMS = {"initial_loss": 1.0, "constant_loss": 4.0, "tc": 4.0, "storage": 90.0, "recession": 0.98, "initial_flow_ratio": 0.005, "k": 1.0}
EVENTWISE_PARAMS = {
    "E19": {"initial_loss": 10.0, "constant_loss": 1.0, "tc": 60.0, "storage": 60.0, "recession": 0.9, "initial_flow_ratio": 0.001, "k": 1.0},
    "E22": COMMON_PARAMS,
    "E24": {"initial_loss": 5.5, "constant_loss": 0.88, "tc": 22.5, "storage": 34.3, "recession": 0.7, "initial_flow_ratio": 0.001, "k": 1.0},
    "E27": COMMON_PARAMS,
    "E28": {"initial_loss": 2.5, "constant_loss": 2.0, "tc": 25.0, "storage": 45.0, "recession": 0.8, "initial_flow_ratio": 0.003, "k": 1.0},
}


def blocks(text: str, prefix: str) -> list[str]:
    found: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith(prefix):
            current = [line]
        elif current:
            current.append(line)
            if line.strip() == "End:":
                found.append("\n".join(current))
                current = []
    return found


def manager(text: str) -> str:
    match = re.search(r"(?ms)^Gage Manager: .+?^End:\s*$", text)
    return (match.group(0) if match else "Gage Manager: Taquari Antas network\n     Version: 4.13\n     Filepath Separator: \\\nEnd:").strip()


def gage_file(event_id: str, source: Path, use_stz_rain: bool) -> str:
    text = source.read_text(encoding="utf-8")
    gage_blocks = blocks(text, "Gage: ")
    direct = next(block for block in gage_blocks if f"Gage: Chuva_86472000_{event_id}" in block)
    flow = next(block for block in gage_blocks if f"Gage: Q_{event_id}" in block)
    date_part = DATE_PARTS[event_id]
    direct = re.sub(r"(?m)^\s*Filename: .*?$", "     Filename: rain.dss", direct)
    if use_stz_rain:
        direct = re.sub(r"(?m)^\s*Pathname: .*?$", f"     Pathname: /MUCUM/RAIN_{event_id}_86472000/PRECIP-INC/{date_part}/1Hour/OBS/", direct)
    flow = re.sub(r"(?m)^\s*Filename: .*?$", "     Filename: target.dss", flow)
    flow = re.sub(r"(?m)^\s*Pathname: .*?$", f"     Pathname: /MUCUM/OBS_{event_id}/FLOW/{date_part}/1Hour/OBS/", flow)
    pieces = [manager(text), direct.strip()]
    if use_stz_rain:
        stz = direct.replace(f"Chuva_86472000_{event_id}", f"Chuva_86472600_{event_id}")
        stz = stz.replace("86472000", "86472600")
        stz = stz.replace("Chuva ANA 86472600 para a zona 86472600", "Chuva ANA 86472600 para os incrementos a jusante de Santa Tereza")
        pieces.append(stz.strip())
    pieces.append(flow.strip())
    return "\n\n".join(pieces) + "\n"


def set_gage(text: str, subbasin: str, gage: str) -> str:
    pattern = re.compile(r"(?ms)^(Subbasin: " + re.escape(subbasin) + r"\n.+?^End:\s*$)")
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"missing subbasin block {subbasin}")
    block = re.sub(r"(?m)^\s*Gage: .*?$", f"     Gage: {gage}", match.group(1))
    return text[: match.start()] + block + text[match.end() :]


def replace_fields(text: str, field: str, value: float, count: int) -> str:
    iterator = iter([value] * count)
    pattern = re.compile(r"(?m)^(\s*" + re.escape(field) + r":\s*)[-+0-9.eE]+$")

    def repl(match: re.Match[str]) -> str:
        return match.group(1) + f"{next(iterator):.3f}"

    return pattern.sub(repl, text)


def parameterize(basin: str, params: dict[str, float]) -> str:
    for field, key in (("Initial Loss", "initial_loss"), ("Constant Loss Rate", "constant_loss"), ("Time of Concentration", "tc"), ("Storage Coefficient", "storage"), ("Recession Factor", "recession"), ("Initial Flow/Area Ratio", "initial_flow_ratio")):
        basin = replace_fields(basin, field, params[key], 3)
    return replace_fields(basin, "Muskingum K", params["k"], 2)


def constrain_control_to_audited_window(text: str, event_id: str) -> str:
    """Keep a station-distributed run inside the window covered by raw rain."""
    start_date, start_time, end_date, end_time = WINDOWS[event_id]
    date_values = {
        "Start Date": datetime.strptime(start_date, "%d%b%Y").strftime("%d %B %Y"),
        "Start Time": f"{start_time[:2]}:{start_time[2:]}",
        "End Date": datetime.strptime(end_date, "%d%b%Y").strftime("%d %B %Y"),
        "End Time": f"{end_time[:2]}:{end_time[2:]}",
    }
    for field, value in date_values.items():
        text = re.sub(rf"(?m)^(\s*{re.escape(field)}:\s*).*$", rf"\g<1>{value}", text)
    return text


def audited_stz_events() -> set[str]:
    if not AUDIT.exists() or not RAW_DSS_REPORT.exists():
        return set()
    source_report = json.loads(AUDIT.read_text(encoding="utf-8"))
    dss_report = json.loads(RAW_DSS_REPORT.read_text(encoding="utf-8"))
    available = {item["event_id"] for item in source_report["events"] if item.get("rain_numeric_records", 0) > 0}
    complete = {event_id for event_id, item in dss_report["events"].items() if item.get("hours", 0) > 0 and item.get("missing_hours_inside", 1) == 0}
    return available & complete


def build_event(event_id: str, output: Path, stz_events: set[str], parameter_mode: str, params_override: dict[str, float] | None = None) -> dict:
    source = BASE / event_id
    target = output / event_id
    target.mkdir(parents=True, exist_ok=True)
    use_stz_rain = event_id in stz_events
    prefix = f"taquari_antas_{event_id}"
    for filename in (f"{prefix}.hms", f"{prefix}.run", f"chuva_{event_id}.met", f"evento_{event_id}.control"):
        shutil.copy2(source / filename, target / filename)
    if use_stz_rain:
        control_path = target / f"evento_{event_id}.control"
        control_path.write_text(
            constrain_control_to_audited_window(control_path.read_text(encoding="utf-8"), event_id),
            encoding="utf-8",
        )
    params = params_override or (COMMON_PARAMS if parameter_mode == "common" else EVENTWISE_PARAMS[event_id])
    basin = parameterize((source / f"bacia_{event_id}.basin").read_text(encoding="utf-8"), params)
    (target / f"bacia_{event_id}.basin").write_text(basin, encoding="utf-8")
    met = (target / f"chuva_{event_id}.met").read_text(encoding="utf-8")
    for subbasin in (f"SB_ANTAS_{event_id}", f"SB_INC_STZ_{event_id}", f"SB_INC_MUCUM_{event_id}"):
        met = set_gage(met, subbasin, f"Chuva_86472000_{event_id}")
    if use_stz_rain:
        for subbasin in (f"SB_INC_STZ_{event_id}", f"SB_INC_MUCUM_{event_id}"):
            met = set_gage(met, subbasin, f"Chuva_86472600_{event_id}")
    (target / f"chuva_{event_id}.met").write_text(met, encoding="utf-8")
    (target / f"{prefix}.gage").write_text(gage_file(event_id, source / f"{prefix}.gage", use_stz_rain), encoding="utf-8")
    rain_source = RAIN_DSS if use_stz_rain else (source / "rain.dss" if (source / "rain.dss").exists() else source / "event.dss")
    if not rain_source.exists():
        raise RuntimeError(f"missing rainfall DSS for {event_id}: {rain_source}")
    shutil.copy2(rain_source, target / "rain.dss")
    if (source / "target.dss").exists():
        shutil.copy2(source / "target.dss", target / "target.dss")
    elif (source / "event.dss").exists():
        shutil.copy2(source / "event.dss", target / "target.dss")
    else:
        raise RuntimeError(f"no observed flow DSS in {source}")
    manifest = {
        "event_id": event_id,
        "project": f"taquari_antas_{event_id}",
        "hec_hms_version": "4.13",
        "network": "ANA BHO6 nested incremental areas; 86472000 -> 86472600 -> 86510000",
        "rainfall_policy": "86472000 on Antas upstream area; 86472600 on both downstream increments when audited; explicit 86472000 fallback otherwise",
        "station_distributed": use_stz_rain,
        "rainfall_source": str(rain_source.relative_to(ROOT)) if rain_source.is_relative_to(ROOT) else str(rain_source),
        "control_window": {
            "start": f"{WINDOWS[event_id][0]} {WINDOWS[event_id][1]}",
            "end": f"{WINDOWS[event_id][2]} {WINDOWS[event_id][3]}",
        },
        "parameter_mode": parameter_mode,
        "parameters": params,
        "status": "built; not promoted; Santa Tereza flow target remains unavailable",
    }
    (target / "event_network_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def run_event(event_id: str, event_dir: Path) -> dict:
    project = f"taquari_antas_{event_id}"
    script = event_dir / "compute_network.script"
    script.write_text("from hms.model.JythonHms import *\n" f'OpenProject("{project}", "{event_dir.as_posix()}")\n' "Compute(\"Calibracao\")\n" f'print("STATION_DISTRIBUTED_{event_id}_COMPUTE_OK")\n' "Exit(1)\n", encoding="utf-8")
    result = subprocess.run([str(HEC_CMD), "-s", str(script)], cwd=HEC_CMD.parent, capture_output=True, text=True, timeout=180, check=False)
    (event_dir / "compute_stdout.txt").write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    return {"event_id": event_id, "returncode": result.returncode, "ok_marker": f"STATION_DISTRIBUTED_{event_id}_COMPUTE_OK" in result.stdout}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--parameter-mode", choices=("common", "eventwise"), default="common")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    stz_events = audited_stz_events()
    manifests = [build_event(event_id, out, stz_events, args.parameter_mode) for event_id in WINDOWS]
    runs = [run_event(event_id, out / event_id) for event_id in WINDOWS] if args.run else []
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "purpose": "teste de chuva distribuída por estação na rede HEC-HMS; não é calibração promovida", "parameter_mode": args.parameter_mode, "station_distributed_events": sorted(stz_events), "events": manifests, "runs": runs, "fallback_events": sorted(set(WINDOWS) - stz_events)}
    (out / "all_events_network_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if all(item.get("ok_marker", True) for item in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
