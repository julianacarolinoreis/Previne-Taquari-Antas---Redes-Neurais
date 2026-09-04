#!/usr/bin/env python3
"""Build an audited two-station downstream rainfall DSS for E28."""

from __future__ import annotations

import csv
import json
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEC_CMD = Path(r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd")
RAW = ROOT / "assets" / "data" / "hec_hms_audit" / "raw" / "ana"
DERIVED = ROOT / "assets" / "data" / "hec_hms_audit" / "derived"
SOURCE_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_santa_tereza_raw_rain_events.dss"
OUT_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_hybrid_e28_rain.dss"
OUT_CSV = DERIVED / "mucum_hybrid_e28_rain_hourly.csv"
STATIONS = {"86472600": RAW / "events" / "telemetry_86472600_E28.xml", "86510000": RAW / "supplemental" / "telemetry_86510000_E28.xml"}
MONTH = "01Jun2024"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def read_station(path: Path) -> dict[datetime, tuple[float, int]]:
    root = ET.parse(path).getroot()
    buckets: dict[datetime, tuple[float, int]] = {}
    for node in root.iter():
        if local_name(node.tag) not in ("DadosHidrometereologicos", "DadosHidrometeorologicos"):
            continue
        values = {local_name(child.tag): (child.text or "").strip() for child in node}
        try:
            timestamp = datetime.strptime(values.get("DataHora", "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        rain = number(values.get("Chuva"))
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
        writer.writerow(["station", "timestamp_label", "rain_mm", "raw_record_count"])
        for station, values in series.items():
            for timestamp in sorted(values):
                rain, count = values[timestamp]
                writer.writerow([station, timestamp.strftime("%Y-%m-%d %H:00:00"), f"{rain:.6f}", count])


def write_jython() -> Path:
    script = DERIVED / "write_mucum_hybrid_e28_rain_dss.script"
    script.write_text(
        "from hec.heclib.dss import HecDss\n"
        "from hec.heclib.util import HecTime\n"
        "from hec.io import TimeSeriesContainer\n"
        "import csv\n"
        f'base = HecDss.open("{SOURCE_DSS.as_posix()}")\n'
        f'target = HecDss.open("{OUT_DSS.as_posix()}")\n'
        "for path in ['/MUCUM/RAIN_E28_86472000/PRECIP-INC/01Jun2024/1Hour/OBS/', '/MUCUM/RAIN_E28_86472600/PRECIP-INC/01Jun2024/1Hour/OBS/']:\n"
        "    item = base.get(path)\n    item.fullName = path\n    target.put(item)\n"
        f'with open(r"{OUT_CSV.as_posix()}", "rb") as handle:\n    rows = list(csv.DictReader(handle))\n'
        "months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']\n"
        "for station in ['86472600', '86510000']:\n"
        "    station_rows = [row for row in rows if row['station'] == station]\n"
        "    first = station_rows[0]['timestamp_label'].split(' ')\n"
        "    day, month, year = [int(value) for value in first[0].split('-')[2::-1]]\n"
        "    hour = int(first[1].split(':')[0]) * 100\n"
        "    start = HecTime('%02d%s%04d' % (day, months[month-1], year), '%04d' % hour)\n"
        "    values, times = [], []\n"
        "    for row in station_rows:\n        values.append(float(row['rain_mm']))\n        times.append(start.value())\n        start.add(60)\n"
        "    container = TimeSeriesContainer()\n"
        "    container.fullName = '/MUCUM/RAIN_E28_%s/PRECIP-INC/01Jun2024/1Hour/OBS/' % station\n"
        "    container.interval = 60\n    container.times = times\n    container.values = values\n    container.numberValues = len(values)\n    container.units = 'MM'\n    container.type = 'PER-CUM'\n    target.put(container)\n"
        "base.close()\n"
        "target.close()\n"
        f'print("WROTE_HYBRID_E28_RAIN_DSS|{OUT_DSS.as_posix()}")\n'
        "from hms.model.JythonHms import Exit\nExit(1)\n",
        encoding="utf-8",
    )
    return script


def main() -> int:
    series = {station: read_station(path) for station, path in STATIONS.items()}
    write_csv(series)
    script = write_jython()
    result = subprocess.run([str(HEC_CMD), "-s", str(script)], cwd=HEC_CMD.parent, capture_output=True, text=True, timeout=180, check=False)
    log = DERIVED / "write_mucum_hybrid_e28_rain_dss.log"
    log.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "chuva bruta ANA para teste híbrido E28; sem preenchimento",
        "stations": list(STATIONS),
        "events": {station: {"hours": len(values), "first": min(values).isoformat() if values else None, "last": max(values).isoformat() if values else None, "missing_hours_inside": sum(1 for left, right in zip(sorted(values), sorted(values)[1:]) if (right - left).total_seconds() != 3600)} for station, values in series.items()},
        "output_dss": str(OUT_DSS.relative_to(ROOT)),
        "output_csv": str(OUT_CSV.relative_to(ROOT)),
        "hec_returncode": result.returncode,
        "hec_ok_marker": "WROTE_HYBRID_E28_RAIN_DSS" in result.stdout,
    }
    (DERIVED / "mucum_hybrid_e28_rain_dss_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["hec_ok_marker"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
