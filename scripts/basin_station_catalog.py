"""Official station catalog extensions for the Taquari--Antas map.

The basin map is a research inventory, not an alert system.  This module
fetches the public CEMADEN and SGB/SACE catalogues and merges their source
roles into the existing ANA/INMET catalogue.  ANA and SGB/SACE are not blindly
duplicated: SGB operates stations from the national ANA hydrometric network,
so matching codes are represented as one physical station with two source
roles.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
G040_GEOMETRY = ROOT / "assets/data/estudo_bacia_taquari_antas/ugs_g040.geojson"

CEMADEN_RAIN_URL = "https://resources.cemaden.gov.br/dados/311_24.json"
CEMADEN_HYDRO_URL = "https://resources.cemaden.gov.br/dados/327mi_24.json"
SGB_TAQUARI_URL = "https://sace.sgb.gov.br/estacoes_mapa.php?bacia=taquari"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _append_unique(values: list[Any], value: Any) -> None:
    if value not in (None, "") and value not in values:
        values.append(value)


def _request_text(url: str, *, timeout: float = 45.0, opener: Callable[..., Any] = urlopen) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "PREVINE-Taquari-Antas station catalogue/1.0",
            "Accept": "application/json,text/javascript,text/html,*/*;q=0.8",
        },
    )
    with opener(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def _jsonp_payload(text: str) -> dict[str, Any]:
    start = text.find("(")
    if start < 0:
        raise ValueError("Resposta do CEMADEN sem invólucro JSONP.")
    payload = text[start + 1 :].rstrip()
    if payload.endswith(")"):
        payload = payload[:-1]
    value = json.loads(payload)
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        raise ValueError("Resposta do CEMADEN sem bloco de estações.")
    return value[0]


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    previous = ring[-1]
    for current in ring:
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        intersects = ((y1 > lat) != (y2 > lat)) and (
            lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-30) + x1
        )
        if intersects:
            inside = not inside
        previous = current
    return inside


def _point_in_polygon_coordinates(lon: float, lat: float, coordinates: Any) -> bool:
    if not isinstance(coordinates, list) or not coordinates:
        return False
    # Polygon: [outer ring, hole, ...]
    if (
        isinstance(coordinates[0], list)
        and coordinates[0]
        and isinstance(coordinates[0][0], list)
        and coordinates[0][0]
        and isinstance(coordinates[0][0][0], (int, float))
    ):
        outer = coordinates[0]
        if not _point_in_ring(lon, lat, outer):
            return False
        return not any(_point_in_ring(lon, lat, hole) for hole in coordinates[1:])
    # MultiPolygon: [polygon, polygon, ...]
    return any(_point_in_polygon_coordinates(lon, lat, polygon) for polygon in coordinates)


def _load_g040_features(path: Path = G040_GEOMETRY) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Máscara G040 não encontrada: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    features = raw.get("features") if isinstance(raw, dict) else None
    if not isinstance(features, list) or not features:
        raise ValueError(f"Máscara G040 sem features: {path}")
    return [feature for feature in features if isinstance(feature, dict)]


def _inside_g040(lon: float, lat: float, features: list[dict[str, Any]]) -> bool:
    for feature in features:
        geometry = feature.get("geometry") or {}
        if _point_in_polygon_coordinates(lon, lat, geometry.get("coordinates")):
            return True
    return False


def _station_code(value: Any) -> str:
    text = str(value or "").strip()
    return text[:-2] if text.endswith(".0") else text


def _sbg_code_variants(code: str) -> set[str]:
    """Handle the seven-character SGB labels that omit the final zero."""

    variants = {code}
    if len(code) == 7 and code.startswith("86"):
        variants.add(code + "0")
    return variants


def _find_station(stations: list[dict[str, Any]], code: str, network: str) -> dict[str, Any] | None:
    variants = _sbg_code_variants(code)
    for station in stations:
        if str(station.get("code") or "") in variants and str(station.get("network") or "") == network:
            return station
    return None


def _ensure_source_fields(station: dict[str, Any]) -> None:
    station.setdefault("source_networks", [])
    station.setdefault("source_roles", [])
    station.setdefault("catalog_sources", [])
    station.setdefault("source_observations", [])


def _source_metadata_item(station: dict[str, Any], source: str, role: str) -> None:
    _ensure_source_fields(station)
    _append_unique(station["source_networks"], source)
    _append_unique(station["source_roles"], role)


def _new_station(
    *,
    station_id: str,
    code: str,
    name: str,
    network: str,
    latitude: float,
    longitude: float,
    station_type: str,
    source: str,
    role: str,
) -> dict[str, Any]:
    station = {
        "id": station_id,
        "code": code,
        "name": name or f"Estação {code}",
        "network": network,
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "types": [station_type],
        "type_label": station_type,
        "upgs": [],
        "upg_label": "UPG não informada",
        "catalog_sources": [source],
        "source_networks": [network],
        "source_roles": [role],
        "source_observations": [],
        "drainage_area_km2": None,
        "operating": None,
    }
    return station


def _add_cemaden_records(
    stations: list[dict[str, Any]],
    *,
    url: str,
    network_type: str,
    station_type: str,
    role: str,
    basin_features: list[dict[str, Any]],
    fetcher: Callable[[str], str],
) -> dict[str, Any]:
    block = _jsonp_payload(fetcher(url))
    records = block.get("estacao")
    if not isinstance(records, list):
        raise ValueError(f"Catálogo CEMADEN sem estacao: {url}")
    updated = block.get("atualizado")
    inside = 0
    added = 0
    merged = 0
    for raw in records:
        if not isinstance(raw, dict):
            continue
        latitude = _finite(raw.get("latitude"))
        longitude = _finite(raw.get("longitude"))
        code = _station_code(raw.get("codestacao"))
        if latitude is None or longitude is None or not code:
            continue
        if not _inside_g040(longitude, latitude, basin_features):
            continue
        inside += 1
        station = _find_station(stations, code, "CEMADEN")
        if station is None:
            station = _new_station(
                station_id=f"CEMADEN:{code}",
                code=code,
                name=str(raw.get("nomeestacao") or raw.get("cidade") or "").strip(),
                network="CEMADEN",
                latitude=latitude,
                longitude=longitude,
                station_type=station_type,
                source=url,
                role=role,
            )
            stations.append(station)
            added += 1
        else:
            merged += 1
            _ensure_source_fields(station)
            _append_unique(station["catalog_sources"], url)
            _append_unique(station["types"], station_type)
            station["type_label"] = " + ".join(station["types"])
            _source_metadata_item(station, "CEMADEN", role)
        _ensure_source_fields(station)
        _append_unique(station["source_networks"], "CEMADEN")
        _append_unique(station["source_roles"], role)
        if raw.get("status") is not None:
            station["source_operating"] = "operante" if str(raw.get("status")) == "0" else "não confirmado"
        source_observation = {
            "source": "CEMADEN",
            "source_url": url,
            "updated_at_utc": updated,
            "catalog_code": code,
            "metric": "chuva_acumulada_24h_mm" if network_type == "rain" else "nivel_cemaden",
            "value": _finite(raw.get("acumulado")) if network_type == "rain" else _finite(raw.get("nivel")),
            "unit": "mm" if network_type == "rain" else None,
            "source_status": raw.get("status"),
        }
        station["source_observations"] = [
            item
            for item in station["source_observations"]
            if not (item.get("source") == "CEMADEN" and item.get("metric") == source_observation["metric"])
        ]
        station["source_observations"].append(source_observation)
    return {
        "state": "available",
        "url": url,
        "updated_at_utc": updated,
        "total_station_count": len(records),
        "inside_basin_count": inside,
        "added_station_count": added,
        "merged_station_count": merged,
    }


def _decode_js_string(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return value


def _parse_sgb_stations(html: str) -> list[dict[str, Any]]:
    html = unescape(html)
    pattern = re.compile(
        r'src="relatorio\.php\?apenas_grafico=sim&bacia=taquari&pm=(?P<pm>\d+)&s=(?P<s>[^&]*)&sr=(?P<sr>\d+)"'
        r'.*?circleMarker\(\[(?P<lat>-?\d+\.\d+),\s*(?P<lon>-?\d+\.\d+)\].*?bindTooltip\("(?P<label>[^"\\]*(?:\\.[^"\\]*)*)"',
        flags=re.IGNORECASE | re.DOTALL,
    )
    records: list[dict[str, Any]] = []
    for match in pattern.finditer(html):
        label = _decode_js_string(match.group("label"))
        if " - " in label:
            code, name = label.split(" - ", 1)
        else:
            code, name = label, label
        code = _station_code(code)
        if not code:
            continue
        records.append(
            {
                "code": code,
                "name": name.strip(),
                "latitude": float(match.group("lat")),
                "longitude": float(match.group("lon")),
                "report_url": (
                    "https://sace.sgb.gov.br/sace/relatorio.php?apenas_grafico=sim"
                    f"&bacia=taquari&pm={match.group('pm')}&s={match.group('s')}&sr={match.group('sr')}"
                ),
            }
        )
    unique: dict[tuple[str, float, float], dict[str, Any]] = {}
    for record in records:
        unique[(record["code"], record["latitude"], record["longitude"])] = record
    return list(unique.values())


def _add_sgb_records(
    stations: list[dict[str, Any]],
    *,
    fetcher: Callable[[str], str],
) -> dict[str, Any]:
    html = fetcher(SGB_TAQUARI_URL)
    records = _parse_sgb_stations(html)
    if not records:
        raise ValueError("Painel SGB/SACE Taquari sem estações reconhecíveis.")
    added = 0
    merged = 0
    for raw in records:
        code = raw["code"]
        station = _find_station(stations, code, "ANA")
        if station is None:
            station = _new_station(
                station_id=f"SGB/SACE:{code}",
                code=code,
                name=raw["name"],
                network="SGB/SACE",
                latitude=raw["latitude"],
                longitude=raw["longitude"],
                station_type="hidrotelemetrica",
                source=SGB_TAQUARI_URL,
                role="hidrotelemetria SGB/SACE",
            )
            stations.append(station)
            added += 1
        else:
            merged += 1
            _ensure_source_fields(station)
            _append_unique(station["catalog_sources"], SGB_TAQUARI_URL)
            _append_unique(station["types"], "hidrotelemetrica")
            station["type_label"] = " + ".join(station["types"])
        _ensure_source_fields(station)
        _append_unique(station["source_networks"], "SGB/SACE")
        _append_unique(station["source_roles"], "hidrotelemetria SGB/SACE")
        station["sace_station_code"] = code
        station["sace_report_url"] = raw["report_url"]
        station["sace_catalog_name"] = raw["name"]
        station["sace_catalog_coordinates"] = {
            "latitude": raw["latitude"],
            "longitude": raw["longitude"],
        }
    return {
        "state": "available",
        "url": SGB_TAQUARI_URL,
        "station_count": len(records),
        "added_station_count": added,
        "merged_station_count": merged,
    }


def augment_station_catalog(
    stations: list[dict[str, Any]],
    *,
    geometry_path: Path = G040_GEOMETRY,
    fetcher: Callable[[str], str] | None = None,
    strict: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Add official CEMADEN and SGB/SACE roles to a G040 station list."""

    fetcher = fetcher or (lambda url: _request_text(url))
    for station in stations:
        _ensure_source_fields(station)
        if station.get("network") == "ANA":
            _append_unique(station["source_networks"], "ANA/HidroWeb")
            _append_unique(station["source_roles"], "inventário ANA/HidroWeb")
        else:
            _append_unique(station["source_networks"], station.get("network"))
            _append_unique(station["source_roles"], f"inventário {station.get('network')}")

    features = _load_g040_features(geometry_path)
    statuses: dict[str, Any] = {}
    errors: list[str] = []
    for key, kwargs in (
        (
            "cemaden_rain",
            {
                "url": CEMADEN_RAIN_URL,
                "network_type": "rain",
                "station_type": "pluviometrica_cemaden",
                "role": "pluviometria CEMADEN",
            },
        ),
        (
            "cemaden_hydro",
            {
                "url": CEMADEN_HYDRO_URL,
                "network_type": "hydro",
                "station_type": "hidrologica_cemaden",
                "role": "hidrologia CEMADEN",
            },
        ),
    ):
        try:
            statuses[key] = _add_cemaden_records(
                stations,
                basin_features=features,
                fetcher=fetcher,
                **kwargs,
            )
        except Exception as exc:  # pragma: no cover - live source failure path
            statuses[key] = {"state": "unavailable", "url": kwargs["url"], "error": str(exc)}
            errors.append(f"{key}: {exc}")
    try:
        statuses["sgb_hydrotelemetry"] = _add_sgb_records(stations, fetcher=fetcher)
    except Exception as exc:  # pragma: no cover - live source failure path
        statuses["sgb_hydrotelemetry"] = {"state": "unavailable", "url": SGB_TAQUARI_URL, "error": str(exc)}
        errors.append(f"sgb_hydrotelemetry: {exc}")

    if errors and strict:
        raise RuntimeError("Catálogo complementar indisponível: " + " | ".join(errors))
    stations.sort(key=lambda item: (str(item.get("network") or ""), str(item.get("name") or "").casefold(), str(item.get("code") or "")))
    return stations, {
        "basin_mask": "assets/data/estudo_bacia_taquari_antas/ugs_g040.geojson",
        "sources": statuses,
        "complete": not errors,
        "message": (
            "Catálogos ANA/INMET, CEMADEN e SGB/SACE integrados; ANA e SGB foram deduplicadas por código."
            if not errors
            else "Catálogo complementar incompleto; registros indisponíveis permanecem explicitamente sinalizados."
        ),
    }


__all__ = [
    "CEMADEN_HYDRO_URL",
    "CEMADEN_RAIN_URL",
    "G040_GEOMETRY",
    "SGB_TAQUARI_URL",
    "augment_station_catalog",
]
