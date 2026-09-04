#!/usr/bin/env python3
"""Build a source-completeness gate for the Taquari-Antas HMS experiments.

The report is deliberately a gate, not a calibration result. It evaluates
whether the hourly inputs and the Muçum target are complete inside each
historical score window. Missing observations are never filled or silently
truncated.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENTS_CSV = ROOT / "assets" / "data" / "mucum_q62" / "mucum_q62_eventos_usados.csv"
DERIVED = ROOT / "assets" / "data" / "hec_hms_audit" / "multi_event" / "derived"
STZ_AUDIT = ROOT / "assets" / "data" / "hec_hms_audit" / "santa_tereza_event_input_audit_latest.json"
STZ_RAIN_AUDIT = ROOT / "assets" / "data" / "hec_hms_audit" / "derived" / "santa_tereza_raw_rain_dss_report.json"
OUT = ROOT / "assets" / "data" / "hec_hms_audit" / "calibration_input_gate_latest.json"

EVENT_IDS = {19, 22, 24, 26, 27, 28}


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def read_event_windows() -> dict[int, tuple[datetime, datetime]]:
    result: dict[int, tuple[datetime, datetime]] = {}
    with EVENTS_CSV.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            event_id = int(row["evento"])
            if event_id in EVENT_IDS and row.get("sempre_treino") == "0":
                result[event_id] = (parse_time(row["inicio_recorte"]), parse_time(row["fim_recorte"]))
    return result


def hourly_profile(event_id: int, start: datetime, end: datetime) -> dict[str, dict[str, object]]:
    path = DERIVED / f"event_{event_id}_hourly.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = [
        row
        for row in rows
        if start <= datetime.strptime(row["timestamp_label"], "%Y-%m-%d %H:00:00") <= end
    ]
    fields = {
        "86472000_rain_mm_sum": "rain_86472000",
        "86510000_rain_mm_sum": "rain_86510000",
        "86510000_flow_mean": "flow_86510000",
    }
    result: dict[str, dict[str, object]] = {}
    expected = int((end - start).total_seconds() // 3600) + 1
    for field, label in fields.items():
        missing_times = [
            row["timestamp_label"]
            for row in selected
            if not str(row.get(field, "")).strip()
        ]
        result[label] = {
            "field": field,
            "expected_hours": expected,
            "rows_in_score_window": len(selected),
            "numeric_hours": len(selected) - len(missing_times),
            "missing_hours": len(missing_times),
            "first_missing": missing_times[0] if missing_times else None,
            "last_missing": missing_times[-1] if missing_times else None,
            "complete": len(selected) == expected and not missing_times,
        }
    return result


def santa_tereza_profile() -> dict[int, dict[str, object]]:
    audit = json.loads(STZ_AUDIT.read_text(encoding="utf-8"))
    hourly = json.loads(STZ_RAIN_AUDIT.read_text(encoding="utf-8"))
    raw_by_event = {item["event_id"]: item for item in audit["events"]}
    hourly_by_event = hourly["events"]
    result: dict[int, dict[str, object]] = {}
    for event_id in EVENT_IDS:
        raw = raw_by_event.get(f"E{event_id}", {})
        dss = hourly_by_event.get(f"E{event_id}", {})
        numeric = int(raw.get("rain_numeric_records", 0))
        hours = int(dss.get("hours", 0))
        missing = int(dss.get("missing_hours_inside", 0))
        result[event_id] = {
            "station": "86472600",
            "raw_rows": int(raw.get("rows", 0)),
            "raw_numeric_rain_records": numeric,
            "hourly_hours": hours,
            "missing_hours_inside_input": missing,
            "rain_available": numeric > 0,
            "complete_hourly_input": hours > 0 and missing == 0,
            "status": (
                "complete_for_input_window" if hours > 0 and missing == 0 else
                "missing_or_incomplete"
            ),
        }
    return result


def main() -> int:
    windows = read_event_windows()
    stz = santa_tereza_profile()
    events = []
    target_rain_complete: list[int] = []
    three_incremental_area_complete: list[int] = []
    for event_id in sorted(EVENT_IDS):
        start, end = windows[event_id]
        hourly = hourly_profile(event_id, start, end)
        target_complete = hourly["rain_86510000"]["complete"] and hourly["flow_86510000"]["complete"]
        three_incremental_area = target_complete and hourly["rain_86472000"]["complete"] and stz[event_id]["complete_hourly_input"]
        if target_complete:
            target_rain_complete.append(event_id)
        if three_incremental_area:
            three_incremental_area_complete.append(event_id)
        blockers = []
        if not hourly["rain_86472000"]["complete"]:
            blockers.append("chuva 86472000 incompleta no recorte")
        if not hourly["rain_86510000"]["complete"]:
            blockers.append("chuva 86510000 incompleta no recorte")
        if not hourly["flow_86510000"]["complete"]:
            blockers.append("vazao-alvo 86510000 incompleta no recorte")
        if not stz[event_id]["complete_hourly_input"]:
            blockers.append("chuva Santa Tereza 86472600 ausente ou incompleta")
        events.append({
            "event_id": event_id,
            "score_window": {"start": start.isoformat(" "), "end": end.isoformat(" ")},
            "hourly_inputs": hourly,
            "santa_tereza_86472600": stz[event_id],
            "target_rain_and_flow_complete": target_complete,
            "three_incremental_areas_rainfall_and_target_flow_complete": three_incremental_area,
            "blockers": blockers,
        })
    report = {
        "schema_version": "hec_hms_calibration_input_gate_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "gate de qualidade de entradas para pesquisa HEC-HMS; não é calibração nem operação",
        "policy": {
            "missing_data": "não preencher, não interpolar, não truncar o recorte para esconder lacuna",
            "target": "vazão horária do posto ANA 86510000",
            "model_scope": "corredor BHO6 entre os controles 86472000, 86472600 e 86510000; não é a discretização integral da bacia Taquari-Antas",
            "three_incremental_areas": "86472000 ancora a área a montante; 86472600 representa o incremento até Santa Tereza; 86510000 representa o incremento final até Muçum",
            "not_full_taquari_antas_basin": True,
        },
        "events": events,
        "eligible_sets": {
            "target_rain_sensitivity_complete_events": target_rain_complete,
            "three_incremental_areas_complete_events": three_incremental_area_complete,
            "common_three_incremental_areas_calibration": {
                "status": "blocked",
                "reason": "apenas um evento tem chuva horária completa nos três postos e vazão-alvo completa; não há conjunto multi-evento para validar generalização",
            },
            "target_rain_sensitivity": {
                "events": target_rain_complete,
                "status": "diagnostic_only",
                "reason": "a chuva do posto de Muçum é uma hipótese de chuva representativa, não uma superfície espacial validada para toda a bacia",
            },
        },
        "sources": {
            "event_catalogue": str(EVENTS_CSV.relative_to(ROOT)),
            "multi_event_hourly": str(DERIVED.relative_to(ROOT)),
            "santa_tereza_event_audit": str(STZ_AUDIT.relative_to(ROOT)),
            "santa_tereza_hourly_rain_audit": str(STZ_RAIN_AUDIT.relative_to(ROOT)),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "target_rain_sensitivity_events": target_rain_complete, "three_incremental_area_events": three_incremental_area_complete}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
