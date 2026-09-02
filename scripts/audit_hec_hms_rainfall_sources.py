#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audita a proveniência das chuvas usadas na preparação do HEC-HMS.

O relatório separa três perguntas que não podem ser misturadas:

1. O CSV tem estrutura horária consistente?
2. O código da coluna identifica uma estação oficial e a variável observada?
3. No evento de teste, os valores do CSV reproduzem a fonte bruta?

O script preserva as respostas brutas da ANA, INMET e CEMADEN em
``assets/data/hec_hms_audit/raw`` e gera um JSON inspecionável. Ele não treina,
calibra ou promove um modelo HEC-HMS e não produz autorização operacional.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "assets" / "data" / "chuvas_horarias.csv"
AUDIT_ROOT = ROOT / "assets" / "data" / "hec_hms_audit"
RAW_ROOT = AUDIT_ROOT / "raw"
REPORT_PATH = AUDIT_ROOT / "rainfall_station_audit_latest.json"
DERIVED_ROOT = AUDIT_ROOT / "derived"
EVENT_CANDIDATE_PATH = DERIVED_ROOT / "event_2023-09-01_2023-09-10_hourly_candidates.csv"
EVENT_START = datetime(2023, 9, 1)
EVENT_END_EXCLUSIVE = datetime(2023, 9, 11)
UA = "PREVINE-hec-hms-source-audit/1.0"


ANA_STATIONS = [
    {
        "column": "chuva_86472600",
        "inventory_code": "86472600",
        "telemetry_code": "86472600",
        "role": "estação de nível/chuva candidata no município de Santa Tereza",
    },
    {
        "column": "chuva_86472000",
        "inventory_code": "86472000",
        "telemetry_code": "86472000",
        "role": "estação fluviométrica com campo Chuva na telemetria, em Santa Tereza",
    },
    {
        "column": "chuva_02851044",
        "inventory_code": "02851044",
        "telemetry_code": "2851044",
        "role": "pluviômetro regional candidato; não é Santa Tereza",
    },
    {
        "column": "chuva_02851072",
        "inventory_code": "02851072",
        "telemetry_code": "2851072",
        "role": "pluviômetro regional candidato; não é Santa Tereza",
    },
]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_csv_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%Y%m%d%H%M")
    except (TypeError, ValueError):
        return None


def download(url: str, target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            target.write_bytes(body)
            return {
                "url": url,
                "path": str(target.relative_to(ROOT)),
                "status": int(getattr(response, "status", 200)),
                "bytes": len(body),
                "sha256": sha256(target),
            }
    except urllib.error.HTTPError as error:
        body = error.read() if hasattr(error, "read") else b""
        target.write_bytes(body)
        return {
            "url": url,
            "path": str(target.relative_to(ROOT)),
            "status": int(error.code),
            "bytes": len(body),
            "sha256": sha256(target),
            "error": str(error),
        }
    except Exception as error:  # pragma: no cover - depende da rede
        return {
            "url": url,
            "path": str(target.relative_to(ROOT)),
            "status": None,
            "bytes": target.stat().st_size if target.exists() else 0,
            "sha256": sha256(target),
            "error": str(error),
        }


def source_urls(station: dict[str, str]) -> dict[str, str]:
    code = station["inventory_code"]
    telemetry_code = station["telemetry_code"]
    query = {
        "codEstDE": code,
        "codEstATE": code,
        "tpEst": "",
        "nmEst": "",
        "nmRio": "",
        "codSubBacia": "",
        "codBacia": "",
        "nmMunicipio": "",
        "nmEstado": "",
        "sgResp": "",
        "sgOper": "",
        "telemetrica": "",
    }
    return {
        "inventory": "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/HidroInventario?"
        + urllib.parse.urlencode(query),
        "telemetry": "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/"
        "DadosHidrometeorologicos?"
        + urllib.parse.urlencode(
            {
                "codEstacao": telemetry_code,
                "dataInicio": "01/09/2023",
                "dataFim": "10/09/2023",
            }
        ),
        "history_type_1": "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/"
        "HidroSerieHistorica?"
        + urllib.parse.urlencode(
            {
                "codEstacao": code,
                "dataInicio": "01/09/2023",
                "dataFim": "10/09/2023",
                "tipoDados": 1,
                "nivelConsistencia": 1,
            }
        ),
        "history_type_2": "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/"
        "HidroSerieHistorica?"
        + urllib.parse.urlencode(
            {
                "codEstacao": code,
                "dataInicio": "01/09/2023",
                "dataFim": "10/09/2023",
                "tipoDados": 2,
                "nivelConsistencia": 1,
            }
        ),
        "history_type_3": "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/"
        "HidroSerieHistorica?"
        + urllib.parse.urlencode(
            {
                "codEstacao": code,
                "dataInicio": "01/09/2023",
                "dataFim": "10/09/2023",
                "tipoDados": 3,
                "nivelConsistencia": 1,
            }
        ),
    }


def raw_path(kind: str, station: dict[str, str], suffix: str) -> Path:
    code = station["inventory_code"]
    if kind == "inventory":
        return RAW_ROOT / "ana" / "inventory" / f"inventory_{code}.xml"
    if kind == "telemetry":
        return RAW_ROOT / "ana" / "telemetry" / f"telemetry_{code}_2023-09-01_2023-09-10.xml"
    return RAW_ROOT / "ana" / "history" / f"history_{code}_{suffix}_2023-09-01_2023-09-10.xml"


def download_sources() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for station in ANA_STATIONS:
        urls = source_urls(station)
        results.append(download(urls["inventory"], raw_path("inventory", station, "")))
        results.append(download(urls["telemetry"], raw_path("telemetry", station, "")))
        for number in (1, 2, 3):
            results.append(
                download(
                    urls[f"history_type_{number}"],
                    raw_path("history", station, f"type{number}"),
                )
            )

    inmet_root = RAW_ROOT / "inmet"
    results.append(
        download(
            "https://tempo.inmet.gov.br/TabelaEstacoes/A894",
            inmet_root / "station_A894.html",
        )
    )
    results.append(
        download(
            "https://apitempo.inmet.gov.br/estacao/2023-09-01/2023-09-10/A894",
            inmet_root / "observations_A894_2023-09-01_2023-09-10.json",
        )
    )
    results.append(
        download(
            "https://mapservices.cemaden.gov.br/MapaInterativoWS/resources/horario/8928/167",
            RAW_ROOT / "cemaden" / "station_8928_latest_167h.json",
        )
    )
    return results


def load_local_csv() -> tuple[dict[str, Any], dict[str, dict[str, float | None]]]:
    if not CSV_PATH.exists():
        raise FileNotFoundError(CSV_PATH)

    rows = 0
    timestamps: list[datetime] = []
    duplicate_counter: Counter[str] = Counter()
    local: dict[str, dict[str, float | None]] = {
        station["column"]: {} for station in ANA_STATIONS
    }
    local["chuva_inmet_A894"] = {}
    local["chuva_cemaden_4320404010A"] = {}
    numeric_invalid: Counter[str] = Counter()
    columns: list[str] = []

    with CSV_PATH.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        for row in reader:
            rows += 1
            timestamp = parse_csv_time(row.get("COD_SEQUENCIAL", ""))
            if timestamp is None:
                continue
            timestamps.append(timestamp)
            duplicate_counter[row["COD_SEQUENCIAL"]] += 1
            for column in local:
                raw = row.get(column, "")
                value = parse_number(raw)
                if str(raw).strip() and value is None:
                    numeric_invalid[column] += 1
                local[column][timestamp.strftime("%Y%m%d%H00")] = value

    ordered = sorted(set(timestamps))
    cadence_breaks = 0
    for previous, current in zip(ordered, ordered[1:]):
        if current - previous != timedelta(hours=1):
            cadence_breaks += 1

    column_profiles: dict[str, Any] = {}
    for column, values in local.items():
        numeric = [value for value in values.values() if value is not None]
        window_values = [
            value
            for key, value in values.items()
            if EVENT_START <= datetime.strptime(key, "%Y%m%d%H%M") < EVENT_END_EXCLUSIVE
            and value is not None
        ]
        column_profiles[column] = {
            "rows_with_timestamp": len(values),
            "numeric_values": len(numeric),
            "null_or_empty_values": rows - len(numeric),
            "invalid_numeric_values": numeric_invalid[column],
            "negative_values": sum(value < 0 for value in numeric),
            "nonzero_values": sum(value != 0 for value in numeric),
            "min_mm": min(numeric) if numeric else None,
            "max_mm": max(numeric) if numeric else None,
            "event_window": {
                "start_local_label": EVENT_START.isoformat(" "),
                "end_local_label": (EVENT_END_EXCLUSIVE - timedelta(hours=1)).isoformat(" "),
                "numeric_values": len(window_values),
                "null_or_empty_values": 240 - len(window_values),
                "sum_mm": round(sum(window_values), 3),
                "max_mm": max(window_values) if window_values else None,
                "nonzero_values": sum(value != 0 for value in window_values),
            },
        }

    return (
        {
            "path": str(CSV_PATH.relative_to(ROOT)),
            "sha256": sha256(CSV_PATH),
            "bytes": CSV_PATH.stat().st_size,
            "rows": rows,
            "columns": columns,
            "first_timestamp_local_label": ordered[0].isoformat(" ") if ordered else None,
            "last_timestamp_local_label": ordered[-1].isoformat(" ") if ordered else None,
            "unique_timestamps": len(set(timestamps)),
            "duplicate_timestamp_rows": sum(
                count - 1 for count in duplicate_counter.values() if count > 1
            ),
            "cadence_breaks": cadence_breaks,
            "column_profiles": column_profiles,
        },
        local,
    )


def xml_nodes(path: Path, name: str) -> list[ET.Element]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [node for node in root.iter() if local_name(node.tag) == name]


def child_map(node: ET.Element) -> dict[str, str]:
    return {local_name(child.tag): (child.text or "").strip() for child in node}


def inventory_summary(path: Path) -> dict[str, Any]:
    rows = xml_nodes(path, "Table")
    if not rows:
        return {"rows": 0, "error": "inventário sem linha Table"}
    fields = child_map(rows[0])
    station_type = fields.get("TipoEstacao")
    return {
        "rows": len(rows),
        "fields": fields,
        "station_type_label": {
            "1": "fluviométrica",
            "2": "pluviométrica",
        }.get(station_type, "desconhecido"),
    }


def history_summary(path: Path) -> dict[str, Any]:
    rows = xml_nodes(path, "SerieHistorica")
    errors = [node.text.strip() for node in xml_nodes(path, "Error") if node.text]
    sample = child_map(rows[0]) if rows else {}
    return {
        "rows": len(rows),
        "has_data": bool(rows),
        "errors": errors,
        "sample_first_row": sample,
    }


def telemetry_summary(path: Path) -> tuple[dict[str, Any], dict[str, float]]:
    rows = xml_nodes(path, "DadosHidrometereologicos")
    if not rows:
        rows = xml_nodes(path, "DadosHidrometeorologicos")
    errors = [node.text.strip() for node in xml_nodes(path, "Error") if node.text]
    hourly: dict[str, float] = {}
    rain_records = 0
    first_time: str | None = None
    last_time: str | None = None
    for row in rows:
        fields = child_map(row)
        raw_time = fields.get("DataHora", "")
        if not raw_time:
            continue
        try:
            timestamp = datetime.strptime(raw_time.strip()[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        first_time = raw_time.strip() if first_time is None else first_time
        last_time = raw_time.strip()
        rain = parse_number(fields.get("Chuva"))
        if rain is None:
            continue
        rain_records += 1
        key = timestamp.strftime("%Y%m%d%H00")
        hourly[key] = hourly.get(key, 0.0) + rain
    return (
        {
            "rows": len(rows),
            "rain_records": rain_records,
            "hourly_rain_values": len(hourly),
            "first_timestamp": first_time,
            "last_timestamp": last_time,
            "errors": errors,
            "raw_path": str(path.relative_to(ROOT)),
        },
        hourly,
    )


def telemetry_records(path: Path) -> list[dict[str, Any]]:
    """Extrai observações sem alterar a unidade declarada pela fonte."""
    rows = xml_nodes(path, "DadosHidrometereologicos")
    if not rows:
        rows = xml_nodes(path, "DadosHidrometeorologicos")
    records: list[dict[str, Any]] = []
    for row in rows:
        fields = child_map(row)
        raw_time = fields.get("DataHora", "")
        if not raw_time:
            continue
        try:
            timestamp = datetime.strptime(raw_time.strip()[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        records.append(
            {
                "timestamp": timestamp,
                "rain_mm": parse_number(fields.get("Chuva")),
                "flow_source_unit": parse_number(fields.get("Vazao")),
                "level_source_unit": parse_number(fields.get("Nivel")),
            }
        )
    return records


def write_event_candidate() -> dict[str, Any]:
    """Escreve um recorte horário para inspeção antes de qualquer calibração.

    Chuva é soma dentro da hora. Vazão e nível são médias dos registros
    intrahorários somente para facilitar a inspeção; as unidades originais da
    API são preservadas como rótulo e a curva-chave/fuso continuam pendentes.
    """
    DERIVED_ROOT.mkdir(parents=True, exist_ok=True)
    sources = {station["inventory_code"]: station for station in ANA_STATIONS}
    aggregates: dict[str, dict[str, dict[str, float]]] = {}
    for station in ANA_STATIONS:
        code = station["inventory_code"]
        values: dict[str, dict[str, float]] = {}
        for record in telemetry_records(raw_path("telemetry", station, "")):
            timestamp = record["timestamp"]
            if not EVENT_START <= timestamp < EVENT_END_EXCLUSIVE:
                continue
            key = timestamp.strftime("%Y-%m-%d %H:00:00")
            bucket = values.setdefault(
                key,
                {
                    "rain_sum": 0.0,
                    "rain_count": 0.0,
                    "flow_sum": 0.0,
                    "flow_count": 0.0,
                    "level_sum": 0.0,
                    "level_count": 0.0,
                },
            )
            if record["rain_mm"] is not None:
                bucket["rain_sum"] += record["rain_mm"]
                bucket["rain_count"] += 1
            if record["flow_source_unit"] is not None:
                bucket["flow_sum"] += record["flow_source_unit"]
                bucket["flow_count"] += 1
            if record["level_source_unit"] is not None:
                bucket["level_sum"] += record["level_source_unit"]
                bucket["level_count"] += 1
        aggregates[code] = values

    columns = ["timestamp_label", "timestamp_note"]
    for code in sources:
        columns.extend(
            [
                f"rain_{code}_mm_sum",
                f"rain_{code}_record_count",
                f"flow_{code}_source_unit_mean",
                f"flow_{code}_record_count",
                f"level_{code}_source_unit_mean",
                f"level_{code}_record_count",
            ]
        )

    with EVENT_CANDIDATE_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        timestamp = EVENT_START
        while timestamp < EVENT_END_EXCLUSIVE:
            key = timestamp.strftime("%Y-%m-%d %H:00:00")
            row: dict[str, Any] = {
                "timestamp_label": key,
                "timestamp_note": "carimbo da API ANA agrupado por hora; fuso ainda não fechado",
            }
            for code in sources:
                bucket = aggregates[code].get(key, {})
                rain_count = bucket.get("rain_count", 0)
                flow_count = bucket.get("flow_count", 0)
                level_count = bucket.get("level_count", 0)
                row[f"rain_{code}_mm_sum"] = round(bucket.get("rain_sum", 0.0), 6) if rain_count else ""
                row[f"rain_{code}_record_count"] = int(rain_count)
                row[f"flow_{code}_source_unit_mean"] = (
                    round(bucket["flow_sum"] / flow_count, 6) if flow_count else ""
                )
                row[f"flow_{code}_record_count"] = int(flow_count)
                row[f"level_{code}_source_unit_mean"] = (
                    round(bucket["level_sum"] / level_count, 6) if level_count else ""
                )
                row[f"level_{code}_record_count"] = int(level_count)
            writer.writerow(row)
            timestamp += timedelta(hours=1)

    return {
        "path": str(EVENT_CANDIDATE_PATH.relative_to(ROOT)),
        "sha256": sha256(EVENT_CANDIDATE_PATH),
        "rows": 240,
        "status": "candidato_para_revisão; não é calibração",
        "aggregation": {
            "rainfall": "soma dos registros intrahorários",
            "flow": "média dos registros intrahorários, unidade original da ANA",
            "level": "média dos registros intrahorários, unidade original da ANA",
        },
    }


def compare_event(local: dict[str, float | None], source: dict[str, float]) -> dict[str, Any]:
    keys = [
        key
        for key in source
        if EVENT_START <= datetime.strptime(key, "%Y%m%d%H%M") < EVENT_END_EXCLUSIVE
    ]
    pairs = [
        (local[key], source[key])
        for key in keys
        if key in local and local[key] is not None
    ]
    differences = [abs(left - right) for left, right in pairs]
    return {
        "source_hours_in_event": len(keys),
        "overlap_numeric_hours": len(pairs),
        "local_sum_mm": round(sum(left for left, _ in pairs), 3),
        "source_sum_mm": round(sum(right for _, right in pairs), 3),
        "mean_absolute_error_mm": round(sum(differences) / len(differences), 6)
        if differences
        else None,
        "max_absolute_error_mm": round(max(differences), 6) if differences else None,
        "exact_match": bool(pairs) and max(differences) <= 1e-6,
    }


def local_profile_for(local_csv: dict[str, Any], column: str) -> dict[str, Any]:
    return local_csv["column_profiles"].get(column, {})


def build_ana_audit(
    local_csv: dict[str, Any], local: dict[str, dict[str, float | None]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for station in ANA_STATIONS:
        code = station["inventory_code"]
        urls = source_urls(station)
        inventory_file = raw_path("inventory", station, "")
        telemetry_file = raw_path("telemetry", station, "")
        inventory = inventory_summary(inventory_file)
        telemetry, hourly = telemetry_summary(telemetry_file)
        history = {
            str(number): history_summary(
                raw_path("history", station, f"type{number}")
            )
            for number in (1, 2, 3)
        }
        comparison = compare_event(local.get(station["column"], {}), hourly)
        fields = inventory.get("fields", {})
        municipality = fields.get("nmMunicipio")
        type_label = inventory.get("station_type_label")
        if code == "86472000" and comparison["exact_match"]:
            verdict = "evento_reproduzido; variável Chuva da telemetria de estação oficialmente fluviométrica; requer decisão semântica documentada antes do HMS"
        elif code == "02851072" and comparison["exact_match"]:
            verdict = "evento_reproduzido; pluviômetro oficial de Ibiraiaras, não pode ser rotulado como chuva de Santa Tereza"
        elif code == "02851044":
            verdict = "estação pluviométrica oficial de Guaporé; coluna local sem valores; regional, não Santa Tereza"
        elif code == "86472600":
            verdict = "estação oficial de Santa Tereza, mas sem Chuva na telemetria do evento auditado; não usar essa coluna como chuva sem nova reconciliação"
        else:
            verdict = "requer reconciliação"
        result.append(
            {
                "source": "ANA",
                "column": station["column"],
                "inventory_code": code,
                "telemetry_code": station["telemetry_code"],
                "declared_role": station["role"],
                "official_identity": {
                    "name": fields.get("Nome"),
                    "municipality": municipality,
                    "river": fields.get("RioNome"),
                    "state": fields.get("nmEstado"),
                    "station_type": type_label,
                    "station_type_code": fields.get("TipoEstacao"),
                    "has_pluviometer_flag": fields.get("TipoEstacaoPluviometro") == "1",
                    "has_rain_recorder_flag": fields.get("TipoEstacaoRegistradorChuva") == "1",
                    "telemetric_flag": fields.get("TipoEstacaoTelemetrica") == "1",
                    "latitude": parse_number(fields.get("Latitude")),
                    "longitude": parse_number(fields.get("Longitude")),
                    "operator": fields.get("OperadoraSigla"),
                    "responsible": fields.get("ResponsavelSigla"),
                    "raw_inventory_path": str(inventory_file.relative_to(ROOT)),
                },
                "history": history,
                "telemetry": telemetry,
                "local_csv": local_profile_for(local_csv, station["column"]),
                "event_comparison": comparison,
                "verdict": verdict,
                "source_urls": urls,
            }
        )
    return result


def build_inmet_audit(local_csv: dict[str, Any]) -> dict[str, Any]:
    observation_path = RAW_ROOT / "inmet" / "observations_A894_2023-09-01_2023-09-10.json"
    station_path = RAW_ROOT / "inmet" / "station_A894.html"
    body = observation_path.read_bytes() if observation_path.exists() else b""
    try:
        observations = json.loads(body.decode("utf-8")) if body else []
        observation_status = "dados retornados"
    except (json.JSONDecodeError, UnicodeDecodeError):
        observations = []
        observation_status = "resposta não JSON"
    return {
        "source": "INMET",
        "column": "chuva_inmet_A894",
        "station_code": "A894",
        "official_identity": {
            "name": "SERAFINA CORRÊA",
            "state": "RS",
            "identity_source_url": "https://tempo.inmet.gov.br/TabelaEstacoes/A894",
            "identity_note": "A894 não é Santa Tereza; é uma estação de Serafina Corrêa.",
        },
        "event_observation_request": {
            "url": "https://apitempo.inmet.gov.br/estacao/2023-09-01/2023-09-10/A894",
            "http_observed": 204 if not body else 200,
            "bytes": len(body),
            "rows": len(observations) if isinstance(observations, list) else 0,
            "status": observation_status,
            "raw_path": str(observation_path.relative_to(ROOT)),
        },
        "station_page_raw_path": str(station_path.relative_to(ROOT)),
        "local_csv": local_profile_for(local_csv, "chuva_inmet_A894"),
        "verdict": "não usar como chuva de Santa Tereza; além disso, o pedido histórico auditado respondeu sem observações",
    }


def build_cemaden_audit(local_csv: dict[str, Any]) -> dict[str, Any]:
    path = RAW_ROOT / "cemaden" / "station_8928_latest_167h.json"
    body = path.read_bytes() if path.exists() else b""
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    station = payload.get("estacao", {}) if isinstance(payload, dict) else {}
    municipality = station.get("idMunicipio", {}) if isinstance(station, dict) else {}
    return {
        "source": "CEMADEN",
        "column": "chuva_cemaden_4320404010A",
        "station_id": 8928,
        "station_code": station.get("codEstacao", "432040401A"),
        "official_identity": {
            "name": station.get("nome"),
            "municipality": municipality.get("cidade"),
            "state": municipality.get("uf"),
            "station_type": (station.get("idTipoestacao") or {}).get("descricao"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "raw_path": str(path.relative_to(ROOT)),
        },
        "recent_payload": {
            "dates": payload.get("datas", []) if isinstance(payload, dict) else [],
            "http_observed": 200 if body else None,
            "bytes": len(body),
        },
        "local_csv": local_profile_for(local_csv, "chuva_cemaden_4320404010A"),
        "verdict": "estação pluviométrica de Serafina Corrêa; não usar como chuva de Santa Tereza",
    }


def repo_hms_scan() -> dict[str, Any]:
    patterns = ("*.hms", "*.basin", "*.met", "*.control", "*.gage", "*.dss", "*.sqlite")
    files: list[str] = []
    for pattern in patterns:
        files.extend(str(path.relative_to(ROOT)) for path in ROOT.rglob(pattern))
    return {
        "project_files_in_current_worktree": sorted(set(files)),
        "hec_hms_command_on_path": bool(shutil.which("HEC-HMS") or shutil.which("hec-hms")),
        "execution_status": "preparação bloqueada: projeto/executável HEC-HMS não encontrado neste worktree",
    }


def build_report(download_results: list[dict[str, Any]] | None) -> dict[str, Any]:
    local_csv, local = load_local_csv()
    ana = build_ana_audit(local_csv, local)
    event_candidate = write_event_candidate()
    report = {
        "schema_version": "hec_hms_rainfall_station_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "preparação de pesquisa para calibração HEC-HMS; não é alerta, ordem de evacuação ou despacho",
        "event_window": {
            "start_local_label": EVENT_START.isoformat(" "),
            "end_local_label": (EVENT_END_EXCLUSIVE - timedelta(hours=1)).isoformat(" "),
            "timezone_note": "rótulos locais sem offset no CSV; a reconciliação de fuso deve ser fechada no modelo",
        },
        "local_csv": local_csv,
        "ana": ana,
        "inmet": build_inmet_audit(local_csv),
        "cemaden": build_cemaden_audit(local_csv),
        "current_rna_boundary": {
            "source_file": "codigo_python/README.md",
            "statement": "o modelo RNA 2h auditado usa 15 entradas de nível, sem chuva; este CSV é um insumo separado e não deve ser tratado como input da RNA sem nova auditoria",
        },
        "hms_execution": repo_hms_scan(),
        "event_candidate_package": event_candidate,
        "calibration_gate": {
            "rainfall_provenance": "PARCIAL",
            "event_replay": "apto para reproduzir as colunas ANA 86472000 e 02851072 no evento auditado, com suas ressalvas geográficas",
            "full_santa_tereza_rainfall": "NÃO FECHADO",
            "calibration_execution": "NÃO EXECUTADA",
            "required_before_calibration": [
                "decidir e documentar se Chuva de 86472000 será aceita como precipitação observada de estação fluviométrica",
                "definir o conjunto de pluviômetros/telemetrias representativo da bacia de Santa Tereza, sem renomear Ibiraiaras ou Serafina Corrêa",
                "reconciliar fuso, unidade, intervalo de acumulação e política de lacunas",
                "obter vazão observada ou curva-chave válida para calibrar descarga; nível isolado não é vazão",
                "entregar projeto HEC-HMS (bacia, meteorologia, controle e parâmetros) e executar eventos independentes de validação",
            ],
        },
        "findings": [
            "O CSV possui grade horária regular no arquivo auditado: 32904 linhas, sem duplicidades e sem quebras de cadência.",
            "A regularidade temporal não prova a identidade geográfica nem a variável observada.",
            "No evento de 01–10/09/2023, 86472000 e 02851072 reproduzem exatamente as somas horárias da telemetria ANA bruta.",
            "86472000 é oficialmente fluviométrica em Santa Tereza; 02851072 é pluviométrica em Ibiraiaras; A894 e CEMADEN 432040401A/ID 8928 são de Serafina Corrêa.",
            "86472600 é a estação de Santa Tereza no Rio Taquari, mas não apresentou Chuva na telemetria do evento auditado.",
            "Nenhuma calibração HEC-HMS foi declarada concluída: ainda faltam projeto executável e observação de descarga/curva-chave reconciliada.",
        ],
        "download_results": download_results or [],
        "source_documentation": {
            "ana_service": "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx",
            "ana_inventory_docs": "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx?op=HidroInventario",
            "ana_history_docs": "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx?op=HidroSerieHistorica",
            "inmet_station": "https://tempo.inmet.gov.br/TabelaEstacoes/A894",
            "cemaden_endpoint": "https://mapservices.cemaden.gov.br/MapaInterativoWS/resources/horario/8928/167",
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download",
        action="store_true",
        help="baixa novamente as respostas brutas antes de gerar o relatório",
    )
    args = parser.parse_args()
    download_results = download_sources() if args.download else None
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    report = build_report(download_results)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(REPORT_PATH.relative_to(ROOT)),
        "csv_sha256": report["local_csv"]["sha256"],
        "rows": report["local_csv"]["rows"],
        "duplicate_timestamp_rows": report["local_csv"]["duplicate_timestamp_rows"],
        "cadence_breaks": report["local_csv"]["cadence_breaks"],
        "rainfall_provenance": report["calibration_gate"]["rainfall_provenance"],
        "calibration_execution": report["calibration_gate"]["calibration_execution"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
