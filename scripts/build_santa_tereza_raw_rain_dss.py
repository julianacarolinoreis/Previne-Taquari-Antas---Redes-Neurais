#!/usr/bin/env python3
"""Create a DSS rainfall file from the raw ANA Santa Tereza event XML."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")
RAW = ROOT / "assets" / "data" / "hec_hms_audit" / "raw" / "ana" / "events"
DERIVED = ROOT / "assets" / "data" / "hec_hms_audit" / "derived"
LOCAL_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_local_rain_all_events.dss"
OUT_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_santa_tereza_raw_rain_events.dss"
OUT_CSV = DERIVED / "santa_tereza_raw_rain_hourly.csv"
EVENTS = {"E24": "01Nov2023", "E27": "01Apr2024", "E28": "01Jun2024"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def read_event(event_id: str) -> dict[datetime, tuple[float, int]]:
    source = RAW / f"telemetry_86472600_{event_id}.xml"
    root = ET.parse(source).getroot()
    buckets: dict[datetime, tuple[float, int]] = {}
    for node in root.iter():
        if local_name(node.tag) not in ("DadosHidrometereologicos", "DadosHidrometeorologicos"):
            continue
        values = {local_name(child.tag): (child.text or "").strip() for child in node}
        try:
            timestamp = datetime.strptime(values.get("DataHora", "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        rain = parse_number(values.get("Chuva"))
        if rain is None:
            continue
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        total, count = buckets.get(hour, (0.0, 0))
        buckets[hour] = (total + rain, count + 1)
    return buckets


def write_csv(series: dict[str, dict[datetime, tuple[float, int]]]) -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["event_id", "timestamp_label", "rain_mm", "raw_record_count"])
        for event_id in series:
            for timestamp in sorted(series[event_id]):
                rain, count = series[event_id][timestamp]
                writer.writerow([event_id, timestamp.strftime("%Y-%m-%d %H:00:00"), f"{rain:.6f}", count])


def write_jython() -> Path:
    script = DERIVED / "write_santa_tereza_raw_rain_dss.script"
    script.write_text(
        "from hec.heclib.dss import HecDss\n"
        "from hec.heclib.util import HecTime\n"
        "from hec.io import TimeSeriesContainer\n"
        "import csv\n"
        f'local = HecDss.open("{LOCAL_DSS.as_posix()}")\n'
        f'target = HecDss.open("{OUT_DSS.as_posix()}")\n'
        "# Preserve the audited upstream station series already used by the network.\n"
        "months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']\n"
        "direct_paths = ['/MUCUM/RAIN_E19_86472000/PRECIP-INC/01May2023/1Hour/OBS/', '/MUCUM/RAIN_E22_86472000/PRECIP-INC/01Sep2023/1Hour/OBS/', '/MUCUM/RAIN_E24_86472000/PRECIP-INC/01Nov2023/1Hour/OBS/', '/MUCUM/RAIN_E27_86472000/PRECIP-INC/01Apr2024/1Hour/OBS/', '/MUCUM/RAIN_E28_86472000/PRECIP-INC/01Jun2024/1Hour/OBS/']\n"
        "for path in direct_paths:\n    item = local.get(path)\n    item.fullName = path\n    target.put(item)\n"
        "rows = {}\n"
        f'with open(r"{OUT_CSV.as_posix()}", "rb") as handle:\n    for row in csv.DictReader(handle):\n        rows.setdefault(row["event_id"], []).append(row)\n'
        "for event_id, event_rows in rows.items():\n"
        "    first = event_rows[0]['timestamp_label'].split(' ')\n"
        "    day, month, year = [int(value) for value in first[0].split('-')[2::-1]]\n"
        "    hour = int(first[1].split(':')[0]) * 100\n"
        "    start = HecTime('%02d%s%04d' % (day, months[month-1], year), '%04d' % hour)\n"
        "    values, times = [], []\n"
        "    for row in event_rows:\n        values.append(float(row['rain_mm']))\n        times.append(start.value())\n        start.add(60)\n"
        "    container = TimeSeriesContainer()\n"
        "    container.fullName = '/MUCUM/RAIN_%s_86472600/PRECIP-INC/%s/1Hour/OBS/' % (event_id, {'E24':'01Nov2023','E27':'01Apr2024','E28':'01Jun2024'}[event_id])\n"
        "    container.interval = 60\n    container.times = times\n    container.values = values\n    container.numberValues = len(values)\n    container.units = 'MM'\n    container.type = 'PER-CUM'\n    target.put(container)\n"
        "local.close()\n"
        "target.close()\n"
        f'print("WROTE_SANTA_TEREZA_RAW_RAIN_DSS|{OUT_DSS.as_posix()}")\n'
        "from hms.model.JythonHms import Exit\nExit(1)\n",
        encoding="utf-8",
    )
    return script


def main() -> int:
    series = {event_id: read_event(event_id) for event_id in EVENTS}
    write_csv(series)
    script = write_jython()
    result = subprocess.run([str(HEC_CMD), "-s", str(script)], cwd=HEC_CMD.parent, capture_output=True, text=True, timeout=180, check=False)
    log = DERIVED / "write_santa_tereza_raw_rain_dss.log"
    log.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "purpose": "chuva horária agregada diretamente da API ANA para teste de espacialização; sem preenchimento", "source_station": "86472600", "events": {event_id: {"hours": len(values), "first": min(values).isoformat() if values else None, "last": max(values).isoformat() if values else None, "missing_hours_inside": sum(1 for left, right in zip(sorted(values), sorted(values)[1:]) if (right-left).total_seconds() != 3600)} for event_id, values in series.items()}, "output_dss": str(OUT_DSS.relative_to(ROOT)), "output_csv": str(OUT_CSV.relative_to(ROOT)), "hec_returncode": result.returncode, "hec_ok_marker": "WROTE_SANTA_TEREZA_RAW_RAIN_DSS" in result.stdout}
    (DERIVED / "santa_tereza_raw_rain_dss_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["hec_ok_marker"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
