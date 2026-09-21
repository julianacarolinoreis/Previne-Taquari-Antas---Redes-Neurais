#!/usr/bin/env python3
"""Build one auditable station-reconciliation matrix for the HEC-HMS corridor.

This artifact joins the input gate with the Santa Tereza ANA event audit. It
does not fill, interpolate, truncate, or repair missing observations. Its
purpose is to make the station/episode contract explicit before a common
calibration or a spatial surrogate is attempted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "assets" / "data" / "hec_hms_audit" / "calibration_input_gate_latest.json"
STZ_AUDIT = ROOT / "assets" / "data" / "hec_hms_audit" / "santa_tereza_event_input_audit_latest.json"
STZ_DSS = ROOT / "assets" / "data" / "hec_hms_audit" / "derived" / "santa_tereza_raw_rain_dss_report.json"
OUTPUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "station_reconciliation_latest.json"


STATIONS = [
    {
        "code": "86472000",
        "label": "Rio das Antas · montante",
        "role": "upstream_anchor",
        "position": "montante",
    },
    {
        "code": "86472600",
        "label": "Santa Tereza · controle intermediário",
        "role": "intermediate_control",
        "position": "intermediário",
    },
    {
        "code": "86510000",
        "label": "Muçum · posto-alvo",
        "role": "downstream_target",
        "position": "jusante",
    },
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def availability(input_block: dict[str, Any] | None) -> dict[str, Any]:
    block = input_block or {}
    expected = int(block.get("expected_hours") or 0)
    numeric = int(block.get("numeric_hours") or 0)
    rows = int(block.get("rows_in_score_window") or 0)
    return {
        "field": block.get("field"),
        "expected_hours": expected,
        "rows_in_score_window": rows,
        "numeric_hours": numeric,
        "missing_hours": int(block.get("missing_hours") or 0),
        "complete": bool(block.get("complete")),
        "coverage_ratio": round(numeric / expected, 6) if expected else None,
        "first_missing": block.get("first_missing"),
        "last_missing": block.get("last_missing"),
    }


def stz_availability(block: dict[str, Any] | None) -> dict[str, Any]:
    value = block or {}
    expected = int(value.get("expected_hours") or 0)
    numeric = int(value.get("hourly_hours") or 0)
    return {
        "station": value.get("station", "86472600"),
        "raw_rows": int(value.get("raw_rows") or 0),
        "raw_numeric_rain_records": int(value.get("raw_numeric_rain_records") or 0),
        "expected_hours": expected,
        "hourly_hours": numeric,
        "missing_hours_inside_input": int(value.get("missing_hours_inside_input") or 0),
        "rain_available": bool(value.get("rain_available")),
        "complete": bool(value.get("complete_hourly_input")),
        "status": value.get("status"),
        "coverage_ratio": round(numeric / expected, 6) if expected else None,
    }


def main() -> None:
    gate = read_json(GATE)
    stz_audit = read_json(STZ_AUDIT)
    stz_by_event = {item["event_id"]: item for item in stz_audit.get("events", [])}
    dss = read_json(STZ_DSS)

    event_rows: list[dict[str, Any]] = []
    target_complete: list[str] = []
    three_area_complete: list[str] = []
    stz_rain_available: list[str] = []
    blocked: list[str] = []

    for source in gate.get("events", []):
        event_id = f"E{int(source['event_id'])}"
        inputs = source.get("hourly_inputs", {})
        upstream = availability(inputs.get("rain_86472000"))
        stz = stz_availability(source.get("santa_tereza_86472600"))
        downstream_rain = availability(inputs.get("rain_86510000"))
        downstream_flow = availability(inputs.get("flow_86510000"))
        target_ok = bool(source.get("target_rain_and_flow_complete"))
        three_area_ok = bool(source.get("three_incremental_areas_rainfall_and_target_flow_complete"))
        stz_raw = stz_by_event.get(event_id, {})
        dss_row = dss.get("events", {}).get(event_id, {})

        if target_ok:
            target_complete.append(event_id)
        if three_area_ok:
            three_area_complete.append(event_id)
        if stz.get("rain_available"):
            stz_rain_available.append(event_id)
        if source.get("blockers"):
            blocked.append(event_id)

        event_rows.append(
            {
                "event_id": event_id,
                "score_window": source.get("score_window"),
                "stations": {
                    "86472000": {"rain": upstream},
                    "86472600": {
                        "rain": stz,
                        "source_audit": {
                            "status": stz_raw.get("status"),
                            "rows": stz_raw.get("rows"),
                            "rain_numeric_records": stz_raw.get("rain_numeric_records"),
                            "rain_sum_mm": stz_raw.get("rain_sum_mm"),
                            "errors": stz_raw.get("errors", []),
                            "interpretation": stz_raw.get("interpretation"),
                        },
                        "dss_hourly": dss_row,
                    },
                    "86510000": {"rain": downstream_rain, "flow": downstream_flow},
                },
                "target_rain_and_flow_complete": target_ok,
                "three_incremental_areas_complete": three_area_ok,
                "status": "complete_three_incremental_areas"
                if three_area_ok
                else "target_replay_only"
                if target_ok
                else "blocked_by_input_quality",
                "blockers": source.get("blockers", []),
                "policy": "missing_data_not_filled_or_interpolated",
            }
        )

    payload = {
        "schema_version": "previne_station_reconciliation_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "research_only_station_reconciliation",
        "research_only": True,
        "official_alert": False,
        "purpose": (
            "Matriz única de cobertura e bloqueios das estações do corredor BHO6; "
            "não é calibração, previsão, alerta ou autorização operacional."
        ),
        "network": {
            "station_order": [item["code"] for item in STATIONS],
            "representation": "três controles e dois trechos de propagação; não três zonas da bacia",
            "target": "86510000",
        },
        "stations": STATIONS,
        "events": event_rows,
        "summary": {
            "event_count": len(event_rows),
            "target_rain_and_flow_complete_events": target_complete,
            "three_incremental_areas_complete_events": three_area_complete,
            "santa_tereza_rain_available_events": stz_rain_available,
            "events_with_blockers": blocked,
        },
        "calibration_gate": {
            "common_three_area_calibration": "blocked_if_fewer_than_two_independent_events",
            "current_complete_three_area_count": len(three_area_complete),
            "current_status": "blocked_common_calibration_single_complete_event"
            if len(three_area_complete) < 2
            else "candidate_for_independent_event_validation",
        },
        "provenance": {
            "calibration_input_gate": str(GATE.relative_to(ROOT)).replace("\\", "/"),
            "calibration_input_gate_sha256": sha256(GATE),
            "santa_tereza_event_audit": str(STZ_AUDIT.relative_to(ROOT)).replace("\\", "/"),
            "santa_tereza_event_audit_sha256": sha256(STZ_AUDIT),
            "santa_tereza_dss_report": str(STZ_DSS.relative_to(ROOT)).replace("\\", "/"),
            "santa_tereza_dss_report_sha256": sha256(STZ_DSS),
        },
        "limits": [
            "Não preencher ou interpolar lacunas para liberar um evento.",
            "Chuva disponível em uma estação não prova que a chuva representa toda a bacia.",
            "Vazão/nível de uma estação não deve ser transformado em mancha sem contrato vertical e hidráulico.",
            "A matriz não promove nenhum conjunto de parâmetros HEC-HMS.",
        ],
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} events={len(event_rows)} three_area={len(three_area_complete)}")


if __name__ == "__main__":
    main()
