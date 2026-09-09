#!/usr/bin/env python3
"""Audit ST→Muçum travel-time candidates from local ANA event XML.

This does **not** close the ``travel_time`` gate.  It measures peak-to-peak
lags on the three events that have usable paired series (E24/E27/E28) and
contrasts them with the ~16 h feature lag declared in the Muçum RNA catalog.
E19/E22 keep Muçum series but Santa Tereza XML is an error stub.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ST_DIR = ROOT / "assets/data/hec_hms_audit/raw/ana/events"
MUC_DIR = ROOT / "assets/data/hec_hms_audit/raw/ana/supplemental"
MODEL_INPUTS = ROOT / "assets/data/mucum_modelo_inputs.json"
NETWORK_AUDIT = ROOT / "assets/data/hec_hms_integrated_taquari_antas/network_audit_latest.json"
OUTPUT = ROOT / "assets/data/research_travel_time_st_mucum_latest.json"

STATION_ST = "86472600"
STATION_MUC = "86510000"
EVENTS = ("E19", "E22", "E24", "E27", "E28")


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def number(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        result = float(str(value).replace(",", "."))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def iso_local(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def read_level_series(path: Path) -> list[tuple[datetime, float]]:
    if not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    rows: list[tuple[datetime, float]] = []
    for node in root.iter():
        if local_name(node.tag) not in ("DadosHidrometereologicos", "DadosHidrometeorologicos"):
            continue
        fields = {local_name(child.tag): (child.text or "").strip() for child in node}
        timestamp = parse_timestamp(fields.get("DataHora") or fields.get("Data"))
        level = number(fields.get("Nivel") or fields.get("Cota"))
        if timestamp is None or level is None:
            continue
        rows.append((timestamp, level))
    rows.sort(key=lambda item: item[0])
    return rows


def peak(rows: list[tuple[datetime, float]]) -> dict[str, Any] | None:
    if not rows:
        return None
    when, level = max(rows, key=lambda item: item[1])
    return {
        "time_local": iso_local(when),
        "level_cm": level,
        "n_samples": len(rows),
        "start_local": iso_local(rows[0][0]),
        "end_local": iso_local(rows[-1][0]),
    }


def lag_hours(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600.0, 2)


def declared_lag_h() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if MODEL_INPUTS.exists():
        try:
            payload = json.loads(MODEL_INPUTS.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            payload = {}
    montante = payload.get("estacao_montante_confirmada") if isinstance(payload.get("estacao_montante_confirmada"), dict) else {}
    lag = None
    papel = str(montante.get("papel") or "")
    for token in papel.replace(",", " ").split():
        cleaned = token.strip().lower().replace("~", "").replace("h", "")
        if cleaned.replace(".", "", 1).isdigit():
            lag = float(cleaned)
            break
    if lag is None:
        text = json.dumps(payload, ensure_ascii=False)
        if "16h" in text or "16 h" in text or "~16" in text:
            lag = 16.0
    return {
        "hours": lag if lag is not None else 16.0,
        "source": "assets/data/mucum_modelo_inputs.json",
        "sha256": sha256(MODEL_INPUTS),
        "papel": montante.get("papel"),
        "interpretation": "feature/model lag declared for Santa Tereza as Muçum upstream input — not a validated hydraulic travel-time rule",
    }


def network_context() -> dict[str, Any]:
    if not NETWORK_AUDIT.exists():
        return {"status": "not_available"}
    try:
        payload = json.loads(NETWORK_AUDIT.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"status": "not_available"}
    topology = payload.get("topology") if isinstance(payload.get("topology"), dict) else {}
    paths = topology.get("paths") if isinstance(topology.get("paths"), dict) else {}
    st_muc = paths.get("86472600_to_86510000") if isinstance(paths.get("86472600_to_86510000"), dict) else {}
    path_km = number(str(st_muc.get("length_km"))) if st_muc.get("length_km") is not None else None
    return {
        "status": "available",
        "path": "assets/data/hec_hms_integrated_taquari_antas/network_audit_latest.json",
        "sha256": sha256(NETWORK_AUDIT),
        "path_length_km": path_km,
        "path_segment_count": st_muc.get("segment_count"),
        "connected_order": topology.get("connected_order"),
        "note": "BHO6 path Santa Tereza→Muçum cited for geometric context only; distance is not converted into travel time here",
    }


def score_event(event_id: str) -> dict[str, Any]:
    st_path = ST_DIR / f"telemetry_{STATION_ST}_{event_id}.xml"
    muc_path = MUC_DIR / f"telemetry_{STATION_MUC}_{event_id}.xml"
    st_rows = read_level_series(st_path)
    muc_rows = read_level_series(muc_path)
    st_peak = peak(st_rows)
    muc_peak = peak(muc_rows)
    st_time = parse_timestamp(st_peak["time_local"]) if st_peak else None
    muc_time = parse_timestamp(muc_peak["time_local"]) if muc_peak else None
    lag = lag_hours(st_time, muc_time)
    status = "scored"
    notes: list[str] = []
    if not st_rows and not muc_rows:
        status = "missing_both_series"
    elif not st_rows:
        status = "st_series_missing"
        notes.append("Santa Tereza XML is empty or an ANA error stub")
    elif not muc_rows:
        status = "mucum_series_missing"
    elif lag is None:
        status = "incomplete_peaks"
    artifact = {
        "event_id": event_id,
        "status": status,
        "stations": {
            "santa_tereza": {
                "code": STATION_ST,
                "path": str(st_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(st_path),
                "peak": st_peak,
            },
            "mucum": {
                "code": STATION_MUC,
                "path": str(muc_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(muc_path),
                "peak": muc_peak,
            },
        },
        "peak_to_peak_lag_h": lag,
        "notes": notes,
    }
    return artifact


def summarize(events: list[dict[str, Any]], declared: dict[str, Any]) -> dict[str, Any]:
    scored = [item for item in events if item.get("status") == "scored" and item.get("peak_to_peak_lag_h") is not None]
    lags = [float(item["peak_to_peak_lag_h"]) for item in scored]
    lags_sorted = sorted(lags)
    median = None
    if lags_sorted:
        mid = len(lags_sorted) // 2
        if len(lags_sorted) % 2:
            median = lags_sorted[mid]
        else:
            median = round((lags_sorted[mid - 1] + lags_sorted[mid]) / 2.0, 2)
    declared_h = number(str(declared.get("hours")))
    contrasts = []
    for item in scored:
        lag = float(item["peak_to_peak_lag_h"])
        contrasts.append(
            {
                "event_id": item["event_id"],
                "peak_to_peak_lag_h": lag,
                "minus_declared_16h": round(lag - (declared_h or 16.0), 2),
            }
        )
    return {
        "scored_events": len(scored),
        "attempted_events": len(events),
        "peak_to_peak_lag_h": {
            "values": lags,
            "min": min(lags) if lags else None,
            "max": max(lags) if lags else None,
            "median": median,
            "mean": round(sum(lags) / len(lags), 2) if lags else None,
        },
        "declared_model_lag_h": declared_h,
        "contrast_vs_declared": contrasts,
        "interpretation": (
            "Observed peak-to-peak lags on paired ANA XML are hours, not ~16 h. "
            "The declared 16 h remains a model-feature lag / upstream timing cue, "
            "not a validated basin travel-time rule."
        ),
    }


def build_audit(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    declared = declared_lag_h()
    events = [score_event(event_id) for event_id in EVENTS]
    summary = summarize(events, declared)
    return {
        "schema_version": 1,
        "feed_type": "travel_time_event_audit",
        "research_only": True,
        "official_alert": False,
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "pair": {
            "upstream": {"code": STATION_ST, "name": "Santa Tereza"},
            "downstream": {"code": STATION_MUC, "name": "Muçum"},
            "metric": "peak_to_peak_lag_hours",
            "timezone_note": "ANA DataHora values are kept as local timestamps without inventing availability times",
        },
        "declared_model_lag": declared,
        "network_context": network_context(),
        "events": events,
        "summary": summary,
        "gate": {
            "id": "travel_time",
            "status": "research_partial",
            "promotion_allowed": False,
            "reason": (
                f"Measured peak-to-peak lags for {summary['scored_events']} paired events "
                f"(median {summary['peak_to_peak_lag_h']['median']} h). "
                "Declared ~16 h remains a Muçum RNA feature lag, not a closed basin rule."
            ),
        },
        "limitations": [
            "Peak-to-peak lag is not the same as hydraulic travel time of a flood wave.",
            "E19/E22 lack usable Santa Tereza XML in this repository.",
            "No interpolation of missing hours; incomplete pairs are marked, not filled.",
            "Does not change live RNA inputs or publish an operational alert.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    audit = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    partial.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "scored_events": audit["summary"]["scored_events"],
                "median_lag_h": audit["summary"]["peak_to_peak_lag_h"]["median"],
                "declared_model_lag_h": audit["declared_model_lag"]["hours"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
