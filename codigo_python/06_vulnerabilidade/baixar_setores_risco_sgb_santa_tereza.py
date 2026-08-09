#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa e valida os setores oficiais de risco do SGB para Santa Tereza/RS.

O arquivo publicado e uma copia byte a byte da resposta GeoJSON da API. O
script apenas valida o conteudo antes da gravacao; nenhum atributo, valor ou
classificacao e criado, removido ou transformado.

Uso:
    python codigo_python/06_vulnerabilidade/baixar_setores_risco_sgb_santa_tereza.py
    python codigo_python/06_vulnerabilidade/baixar_setores_risco_sgb_santa_tereza.py --check-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


MUNICIPIO_CODIGO = "4317251"
MUNICIPIO_NOME = "SANTA TEREZA"
UF = "RS"
EXPECTED_FEATURE_COUNT = 37
EXPECTED_GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}

# Teste de sanidade espacial, nao substitui uma validacao contra a malha
# municipal oficial. A caixa e deliberadamente mais ampla que os setores.
SANTA_TEREZA_ENVELOPE = (-52.0, -29.5, -51.4, -28.8)

SERVICE_ROOT = (
    "https://grd.defesacivil.rs.gov.br/server/rest/services/PRD/"
    "sgb_setor_risc/MapServer/1/query"
)
QUERY = {
    "where": f"cd_geocmu='{MUNICIPIO_CODIGO}'",
    "outFields": "*",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
}
SOURCE_URL = SERVICE_ROOT + "?" + urllib.parse.urlencode(QUERY)

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "assets"
    / "data"
    / "vulnerabilidade"
    / "perigo"
    / "setores_risco_sgb_santa_tereza.geojson"
)

REQUIRED_PROPERTIES = {
    "objectid",
    "cd_geocmu",
    "num_setor",
    "munic",
    "uf",
    "grau_risco",
    "grau_vulne",
    "tipolo_g1",
    "num_edif",
    "num_domi",
    "num_pess",
    "dt_atualizacao",
}


class ValidationError(RuntimeError):
    """Indica que a resposta nao corresponde ao recorte esperado."""


def download(timeout: float) -> bytes:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "Accept": "application/geo+json, application/json",
            "User-Agent": "PREVINE-vulnerabilidade/1.0 (dados oficiais SGB)",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"API respondeu HTTP {status}")
        content_type = response.headers.get_content_type().lower()
        if content_type not in {"application/geo+json", "application/json"}:
            raise RuntimeError(
                f"tipo de conteudo inesperado: {content_type!r}; recusando gravacao"
            )
        payload = response.read()
    if not payload:
        raise RuntimeError("API retornou corpo vazio")
    return payload


def iter_positions(coordinates: Any) -> Iterable[tuple[float, float]]:
    """Percorre posicoes GeoJSON, independentemente do nivel de aninhamento."""
    if not isinstance(coordinates, list) or not coordinates:
        raise ValidationError("coordenadas ausentes ou fora do formato GeoJSON")

    if (
        len(coordinates) >= 2
        and isinstance(coordinates[0], (int, float))
        and not isinstance(coordinates[0], bool)
        and isinstance(coordinates[1], (int, float))
        and not isinstance(coordinates[1], bool)
    ):
        lon = float(coordinates[0])
        lat = float(coordinates[1])
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValidationError("coordenada nao finita")
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValidationError(
                f"coordenada fora do dominio geografico: ({lon}, {lat})"
            )
        yield lon, lat
        return

    for child in coordinates:
        yield from iter_positions(child)


def geometry_rings(geometry: dict[str, Any]) -> Iterable[list[Any]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        yield from coordinates
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            yield from polygon


def validate(payload: bytes) -> dict[str, Any]:
    try:
        document = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"resposta nao e JSON UTF-8 valido: {exc}") from exc

    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise ValidationError("objeto raiz nao e uma FeatureCollection GeoJSON")

    features = document.get("features")
    if not isinstance(features, list):
        raise ValidationError("campo 'features' ausente ou invalido")
    if len(features) != EXPECTED_FEATURE_COUNT:
        raise ValidationError(
            f"contagem inesperada: {len(features)}; esperado: {EXPECTED_FEATURE_COUNT}"
        )

    object_ids: list[str] = []
    sector_ids: list[str] = []
    geometry_types: set[str] = set()
    positions: list[tuple[float, float]] = []
    reference_schema: set[str] | None = None

    for index, feature in enumerate(features, start=1):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValidationError(f"feicao {index} nao e um objeto Feature")

        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValidationError(f"feicao {index} sem objeto 'properties'")

        missing = REQUIRED_PROPERTIES - properties.keys()
        if missing:
            raise ValidationError(
                f"feicao {index} perdeu atributos obrigatorios: {sorted(missing)}"
            )

        schema = set(properties)
        if reference_schema is None:
            reference_schema = schema
        elif schema != reference_schema:
            raise ValidationError(f"esquema de atributos varia na feicao {index}")

        if str(properties["cd_geocmu"]) != MUNICIPIO_CODIGO:
            raise ValidationError(
                f"feicao {index} pertence ao codigo {properties['cd_geocmu']!r}"
            )
        if str(properties["munic"]).strip().upper() != MUNICIPIO_NOME:
            raise ValidationError(
                f"feicao {index} pertence ao municipio {properties['munic']!r}"
            )
        if str(properties["uf"]).strip().upper() != UF:
            raise ValidationError(f"feicao {index} pertence a UF {properties['uf']!r}")

        object_id = properties["objectid"]
        sector_id = properties["num_setor"]
        if object_id in (None, "") or sector_id in (None, ""):
            raise ValidationError(f"feicao {index} sem objectid ou num_setor")
        object_ids.append(str(object_id))
        sector_ids.append(str(sector_id))

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            raise ValidationError(f"feicao {index} sem geometria")
        geometry_type = geometry.get("type")
        if geometry_type not in EXPECTED_GEOMETRY_TYPES:
            raise ValidationError(
                f"feicao {index} tem geometria inesperada: {geometry_type!r}"
            )
        geometry_types.add(str(geometry_type))

        feature_positions = list(iter_positions(geometry.get("coordinates")))
        if not feature_positions:
            raise ValidationError(f"feicao {index} sem posicoes")
        positions.extend(feature_positions)

        for ring in geometry_rings(geometry):
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValidationError(f"feicao {index} contem anel com menos de 4 pontos")
            if ring[0][:2] != ring[-1][:2]:
                raise ValidationError(f"feicao {index} contem anel nao fechado")

    if len(set(object_ids)) != len(object_ids):
        raise ValidationError("objectid duplicado")
    if len(set(sector_ids)) != len(sector_ids):
        raise ValidationError("num_setor duplicado")

    xmin = min(position[0] for position in positions)
    ymin = min(position[1] for position in positions)
    xmax = max(position[0] for position in positions)
    ymax = max(position[1] for position in positions)
    bounds = (xmin, ymin, xmax, ymax)

    env_xmin, env_ymin, env_xmax, env_ymax = SANTA_TEREZA_ENVELOPE
    if not (
        env_xmin <= xmin < xmax <= env_xmax
        and env_ymin <= ymin < ymax <= env_ymax
    ):
        raise ValidationError(
            f"bounds {bounds!r} fora do envelope de sanidade de Santa Tereza "
            f"{SANTA_TEREZA_ENVELOPE!r}"
        )

    # GeoJSON RFC 7946 usa longitude/latitude WGS 84. Alem disso, a consulta
    # solicita explicitamente outSR=4326; a checagem de dominio acima detecta
    # respostas acidentais em coordenadas projetadas.
    if QUERY.get("outSR") != "4326":
        raise ValidationError("consulta nao esta fixada em EPSG:4326")

    return {
        "features": len(features),
        "properties": len(reference_schema or ()),
        "geometry_types": sorted(geometry_types),
        "unique_objectids": len(set(object_ids)),
        "unique_sector_ids": len(set(sector_ids)),
        "crs": "EPSG:4326 (outSR=4326; GeoJSON RFC 7946)",
        "bounds": bounds,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def print_report(report: dict[str, Any], output: Path, mode: str) -> None:
    bounds = ", ".join(f"{value:.6f}" for value in report["bounds"])
    print(f"[ok] modo: {mode}")
    print(f"[ok] feicoes: {report['features']}")
    print(f"[ok] municipio: {MUNICIPIO_CODIGO} - {MUNICIPIO_NOME}/{UF}")
    print(
        "[ok] identificadores unicos: "
        f"objectid={report['unique_objectids']}, num_setor={report['unique_sector_ids']}"
    )
    print(
        f"[ok] geometria: {', '.join(report['geometry_types'])}; "
        f"bounds=[{bounds}]"
    )
    print(f"[ok] CRS: {report['crs']}")
    print(f"[ok] atributos preservados: {report['properties']} campos por feicao")
    print(f"[ok] sha256: {report['sha256']}")
    print(f"[ok] arquivo: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"destino GeoJSON (padrao: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="valida o arquivo existente sem acessar a rede nem regrava-lo",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="timeout HTTP em segundos (padrao: 90)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()

    if args.check_only:
        if not output.is_file():
            raise SystemExit(f"arquivo nao encontrado para validacao: {output}")
        payload = output.read_bytes()
        report = validate(payload)
        print_report(report, output, "validacao local")
        return 0

    print(f"[download] {SOURCE_URL}")
    payload = download(args.timeout)
    report = validate(payload)
    atomic_write(output, payload)

    # Confere tambem os bytes efetivamente persistidos.
    persisted_report = validate(output.read_bytes())
    if persisted_report["sha256"] != report["sha256"]:
        raise RuntimeError("checksum do arquivo persistido diverge da resposta validada")

    print_report(persisted_report, output, "download e validacao")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
