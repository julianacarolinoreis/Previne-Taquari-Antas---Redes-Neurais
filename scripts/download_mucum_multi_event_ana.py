"""Download and aggregate ANA event telemetry for multi-event HMS calibration.

Raw XML is preserved. Hourly aggregation is only a transport layer: rain is
summed, flow and level are averaged, and the source semantics remain explicit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENTS_CSV = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_eventos_usados.csv"
OUT = ROOT / "assets" / "data" / "hec_hms_audit" / "multi_event"
RAW = OUT / "raw"
DERIVED = OUT / "derived"
UA = "PREVINE-hec-hms-multi-event-source-audit/1.0"
STATIONS = {
    "86510000": "estacao_alvo_mucum",
    "86472000": "estacao_fluviometrica_com_chuva_candidata",
    "02851044": "pluviometro_guapore",
    "02851072": "pluviometro_ibiraiaras",
}
EVENT_IDS = {19, 22, 24, 26, 27, 28}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def num(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def child_map(node: ET.Element) -> dict[str, str]:
    return {local(child.tag): (child.text or "").strip() for child in node}


def download(url: str, target: Path) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read()
    target.write_bytes(body)
    return {"url": url, "path": str(target.relative_to(ROOT)), "bytes": len(body), "sha256": sha256(target)}


def events() -> list[dict[str, object]]:
    selected = []
    with EVENTS_CSV.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            event_id = int(row["evento"])
            if event_id not in EVENT_IDS or row.get("sempre_treino") != "0":
                continue
            start = datetime.strptime(row["inicio_recorte"], "%Y-%m-%d %H:%M:%S")
            end = datetime.strptime(row["fim_recorte"], "%Y-%m-%d %H:%M:%S")
            selected.append({"event_id": event_id, "start": start, "end": end, "peak_cm": float(row["pico_cm"])})
    return selected


def fetch_events(warmup_hours: int, tail_hours: int) -> list[dict[str, object]]:
    results = []
    for event in events():
        event_id = int(event["event_id"])
        start = event["start"]
        end = event["end"]
        assert isinstance(start, datetime) and isinstance(end, datetime)
        input_start = start - timedelta(hours=warmup_hours)
        input_end = end + timedelta(hours=tail_hours)
        start_label = input_start.strftime("%d/%m/%Y")
        end_label = input_end.strftime("%d/%m/%Y")
        event_result = {
            "event_id": event_id,
            "start": start.isoformat(" "),
            "end": end.isoformat(" "),
            "input_start": input_start.isoformat(" "),
            "input_end": input_end.isoformat(" "),
            "stations": {},
        }
        for code in STATIONS:
            params = urllib.parse.urlencode({
                "codEstacao": code,
                "dataInicio": start_label,
                "dataFim": end_label,
            })
            url = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos?" + params
            target = RAW / f"telemetry_{code}_event_{event_id}_input_{input_start:%Y%m%d}_{input_end:%Y%m%d}.xml"
            try:
                event_result["stations"][code] = download(url, target)
            except Exception as exc:
                event_result["stations"][code] = {"url": url, "error": repr(exc), "path": str(target.relative_to(ROOT))}
        results.append(event_result)
    return results


def rows_from_xml(path: Path) -> list[dict[str, object]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    root = ET.parse(path).getroot()
    rows = [node for node in root.iter() if local(node.tag) in {"DadosHidrometereologicos", "DadosHidrometeorologicos"}]
    result = []
    for node in rows:
        fields = child_map(node)
        stamp = fields.get("DataHora", "")[:19]
        try:
            timestamp = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        result.append({
            "timestamp": timestamp,
            "rain_mm": num(fields.get("Chuva")),
            "flow_source_unit": num(fields.get("Vazao")),
            "level_source_unit": num(fields.get("Nivel")),
        })
    return result


def aggregate(download_results: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for event in download_results:
        event_id = int(event["event_id"])
        start = datetime.fromisoformat(str(event.get("input_start", event["start"])))
        end = datetime.fromisoformat(str(event.get("input_end", event["end"])))
        records: dict[str, list[dict[str, object]]] = {}
        for code in STATIONS:
            info = event["stations"].get(code, {})
            path = ROOT / str(info.get("path", ""))
            records[code] = rows_from_xml(path)
        buckets: dict[datetime, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        timestamp = start.replace(minute=0, second=0, microsecond=0)
        while timestamp <= end:
            buckets[timestamp]
            timestamp += timedelta(hours=1)
        for code, rows in records.items():
            for record in rows:
                stamp = record["timestamp"]
                if not isinstance(stamp, datetime) or stamp < start or stamp > end:
                    continue
                hour = stamp.replace(minute=0, second=0, microsecond=0)
                bucket = buckets[hour]
                for field in ("rain_mm", "flow_source_unit", "level_source_unit"):
                    value = record[field]
                    if value is not None:
                        count_key = f"{code}_{field}_count"
                        bucket[f"{code}_{field}_sum"] += float(value)
                        bucket[count_key] += 1.0
        path = DERIVED / f"event_{event_id}_hourly.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        columns = ["event_id", "timestamp_label"]
        for code in STATIONS:
            columns.extend([f"{code}_rain_mm_sum", f"{code}_rain_count", f"{code}_flow_mean", f"{code}_flow_count", f"{code}_level_mean", f"{code}_level_count"])
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for stamp in sorted(buckets):
                bucket = buckets[stamp]
                row: dict[str, object] = {"event_id": event_id, "timestamp_label": stamp.strftime("%Y-%m-%d %H:00:00")}
                for code in STATIONS:
                    rain_count = bucket.get(f"{code}_rain_mm_count", 0.0)
                    flow_count = bucket.get(f"{code}_flow_source_unit_count", 0.0)
                    level_count = bucket.get(f"{code}_level_source_unit_count", 0.0)
                    row[f"{code}_rain_mm_sum"] = round(bucket.get(f"{code}_rain_mm_sum", 0.0), 6) if rain_count else ""
                    row[f"{code}_rain_count"] = int(rain_count)
                    row[f"{code}_flow_mean"] = round(bucket.get(f"{code}_flow_source_unit_sum", 0.0) / flow_count, 6) if flow_count else ""
                    row[f"{code}_flow_count"] = int(flow_count)
                    row[f"{code}_level_mean"] = round(bucket.get(f"{code}_level_source_unit_sum", 0.0) / level_count, 6) if level_count else ""
                    row[f"{code}_level_count"] = int(level_count)
                writer.writerow(row)
        output.append({"event_id": event_id, "path": str(path.relative_to(ROOT)), "sha256": sha256(path), "rows": len(buckets)})
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--warmup-hours", type=int, default=72)
    parser.add_argument("--tail-hours", type=int, default=72)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = fetch_events(args.warmup_hours, args.tail_hours) if args.download else []
    derived = aggregate(results if results else [{"event_id": item["event_id"], "start": item["start"].isoformat(" "), "end": item["end"].isoformat(" "), "input_start": (item["start"] - timedelta(hours=args.warmup_hours)).isoformat(" "), "input_end": (item["end"] + timedelta(hours=args.tail_hours)).isoformat(" "), "stations": {code: {"path": str((RAW / f"telemetry_{code}_event_{item['event_id']}_input_{item['start'] - timedelta(hours=args.warmup_hours):%Y%m%d}_{item['end'] + timedelta(hours=args.tail_hours):%Y%m%d}.xml").relative_to(ROOT))} for code in STATIONS}} for item in events()])
    report = {"events": events(), "downloads": results, "derived": derived, "stations": STATIONS, "source": "ANA DadosHidrometeorologicos", "semantic_note": "rain is hourly sum; flow and level are hourly means; source units are not renamed"}
    (OUT / "multi_event_source_audit_latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"events": [item["event_id"] for item in events()], "derived": derived}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
