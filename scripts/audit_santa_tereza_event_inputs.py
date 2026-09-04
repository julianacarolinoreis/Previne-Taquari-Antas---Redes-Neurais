#!/usr/bin/env python3
"""Audit ANA observations at Santa Tereza for the historical HEC-HMS events."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "assets" / "data" / "hec_hms_audit" / "raw" / "ana" / "events"
OUT = ROOT / "assets" / "data" / "hec_hms_audit" / "santa_tereza_event_input_audit_latest.json"
STATION = "86472600"
EVENTS = {
    "E19": ("06/05/2023", "08/05/2023"),
    "E22": ("04/09/2023", "12/09/2023"),
    "E24": ("16/11/2023", "25/11/2023"),
    "E27": ("29/04/2024", "09/05/2024"),
    "E28": ("16/06/2024", "25/06/2024"),
}
UA = "PREVINE-santa-tereza-event-input-audit/1.0"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fields(node: ET.Element) -> dict[str, str]:
    return {local_name(child.tag): (child.text or "").strip() for child in node}


def numeric(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def fetch(event_id: str, start: str, end: str) -> dict:
    query = urllib.parse.urlencode({"codEstacao": STATION, "dataInicio": start, "dataFim": end})
    url = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos?" + query
    target = RAW / f"telemetry_{STATION}_{event_id}.xml"
    RAW.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            status = int(getattr(response, "status", 200))
        target.write_bytes(body)
    except Exception as error:
        return {"event_id": event_id, "url": url, "status": None, "bytes": 0, "error": str(error)}
    digest = hashlib.sha256(body).hexdigest()
    try:
        root = ET.fromstring(body)
        nodes = [node for node in root.iter() if local_name(node.tag) in ("DadosHidrometereologicos", "DadosHidrometeorologicos")]
        errors = [(node.text or "").strip() for node in root.iter() if local_name(node.tag) == "Error" and node.text]
    except ET.ParseError as error:
        nodes, errors = [], [f"XML inválido: {error}"]
    rows = [fields(node) for node in nodes]
    rain = [numeric(row.get("Chuva")) for row in rows]
    flow = [numeric(row.get("Vazao")) for row in rows]
    level = [numeric(row.get("Nivel")) for row in rows]
    rain_values = [value for value in rain if value is not None]
    flow_values = [value for value in flow if value is not None]
    level_values = [value for value in level if value is not None]
    return {
        "event_id": event_id,
        "station": STATION,
        "start": start,
        "end": end,
        "url": url,
        "status": status,
        "bytes": len(body),
        "sha256": digest,
        "raw_path": str(target.relative_to(ROOT)),
        "rows": len(rows),
        "rain_numeric_records": len(rain_values),
        "rain_sum_mm": round(sum(rain_values), 3),
        "rain_max_mm": max(rain_values) if rain_values else None,
        "flow_numeric_records": len(flow_values),
        "level_numeric_records": len(level_values),
        "level_min_source_unit": min(level_values) if level_values else None,
        "level_max_source_unit": max(level_values) if level_values else None,
        "errors": errors,
        "interpretation": "chuva disponível para uso como candidato espacial; vazão não disponível" if rain_values and not flow_values else ("sem chuva numérica no recorte; não usar como chuva" if not rain_values else "dados presentes; revisar unidade e semântica antes do HMS"),
    }


def main() -> int:
    report = {
        "schema_version": "santa_tereza_event_input_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "auditoria de inputs ANA para pesquisa HEC-HMS; não é calibração nem operação",
        "station": STATION,
        "source": "ANA DadosHidrometeorologicos",
        "events": [fetch(event_id, start, end) for event_id, (start, end) in EVENTS.items()],
        "gate": "chuva por evento pode ser candidata; vazão observada de Santa Tereza continua não reconciliada",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "events": report["events"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
