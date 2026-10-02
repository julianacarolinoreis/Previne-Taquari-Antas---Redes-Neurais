"""Contrato verificável do HAND de campo de Santa Tereza (rio principal).

Os hashes identificam os derivados usados, não certificam validação hidráulica
nem substituem a proveniência dos rasters de campo. NoData não é HAND zero.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
from bisect import bisect_left

FIELD_SOURCE_ID = "santa_tereza_lidar_campo_rio_principal_zero160_v1"
FIELD_SCOPE = "somente rio principal"
SURFACE_RAW = "CLIP_MOSAICO_LIDAR_RS.tif (LiDAR bruto)"
SURFACE_ROUTING = "FILL_CLIP_MOSAICO_LIDAR_RS.tif"
EXPECTED_LEVELS = [round(index / 10, 1) for index in range(251)]
# Graus quadrados (EPSG:4326); tolerância apenas para arredondamento numérico.
CUMULATIVE_REL_TOL = 1e-8
CUMULATIVE_ABS_TOL = 1e-16


def finite_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def gauge_to_hand(gauge_m: float) -> float:
    if not finite_number(gauge_m):
        raise ValueError("régua ausente ou não finita")
    return max(0.0, float(gauge_m) - 1.60)


def select_hand_level(levels: list[float], requested: float) -> float | None:
    """Triagem no nível superior disponível; nunca limita silenciosamente ao teto."""
    if not finite_number(requested) or requested < 0 or not levels:
        return None
    # Evita elevar um valor exato de decímetro por erro de ponto flutuante.
    index = bisect_left(levels, requested - 1e-10)
    return levels[index] if index < len(levels) else None


def validate_field_metadata(metadata: dict) -> None:
    expected = {
        "source_id": FIELD_SOURCE_ID,
        "cidade": "santa_tereza",
        "hand_zero_cm": 160,
        "rio": FIELD_SCOPE,
        "superficie_inundacao": SURFACE_RAW,
        "superficie_roteamento": SURFACE_ROUTING,
    }
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in expected.items()):
        raise RuntimeError("fonte HAND incompatível: esperado LiDAR bruto de Santa Tereza, zero 160 cm e somente rio principal")


def validate_field_contours(contours: dict) -> tuple[list[float], list, dict]:
    from shapely.geometry import shape

    validate_field_metadata(contours.get("metadata", {}))
    ordered = []
    for feature in contours.get("features", []):
        level = feature.get("properties", {}).get("nivel_m")
        if not finite_number(level) or not feature.get("geometry"):
            raise RuntimeError("contorno sem nível finito ou geometria")
        geometry = shape(feature["geometry"])
        if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise RuntimeError("geometria HAND vazia, inválida ou não poligonal")
        ordered.append((float(level), geometry))
    ordered.sort(key=lambda item: item[0])
    levels = [level for level, _ in ordered]
    geometries = [geometry for _, geometry in ordered]
    if levels != EXPECTED_LEVELS:
        raise RuntimeError("contornos de campo incompletos/duplicados: esperados 251 níveis HAND de 0 a 25 m")
    for level, previous, current in zip(levels[1:], geometries, geometries[1:]):
        loss = previous.difference(current).area
        tolerance = max(CUMULATIVE_ABS_TOL, previous.area * CUMULATIVE_REL_TOL)
        if loss > tolerance:
            raise RuntimeError(f"contornos não cumulativos em HAND {level:.1f} m: perda relativa {loss / previous.area:.3g}, tolerância {tolerance:.3g} graus²")
    digest = hashlib.sha256(json.dumps(contours, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    provenance = {"source_id": FIELD_SOURCE_ID, "contours_sha256": digest, "hash_encoding": "json_utf8_sorted_keys_compact", "scope": FIELD_SCOPE, "hand_zero_cm": 160, "max_hand_m": 25.0, "cumulative_relative_tolerance": CUMULATIVE_REL_TOL}
    return levels, geometries, provenance


def validate_raster_payload(payload: dict) -> dict:
    from PIL import Image

    validate_field_metadata(payload)
    expected = {"max_hand_m": 25.0, "nodata": 255, "saturated_value": 250, "crs": "EPSG:4326", "georeferencing": "reprojected_nearest_from_source_utm"}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise RuntimeError("contrato raster HAND incompatível: faixa, NoData ou georreferenciamento")
    if any(not finite_number(payload.get(key)) for key in ("S", "W", "N", "E")) or not (payload["S"] < payload["N"] and payload["W"] < payload["E"]):
        raise RuntimeError("limites espaciais do HAND inválidos")
    for key in ("cols", "rows"):
        if not isinstance(payload.get(key), int) or isinstance(payload[key], bool) or payload[key] <= 0:
            raise RuntimeError("dimensões raster inválidas")
    png = base64.b64decode(payload["hand_png_b64"], validate=True)
    digest = hashlib.sha256(png).hexdigest()
    if payload.get("hand_png_sha256") != digest:
        raise RuntimeError("hash do PNG HAND incompatível com a entrada declarada")
    with Image.open(io.BytesIO(png)) as raster:
        if raster.format != "PNG":
            raise RuntimeError("imagem HAND deve usar formato PNG")
        if raster.mode != "L" or raster.size != (payload["cols"], payload["rows"]):
            raise RuntimeError("PNG HAND não corresponde às dimensões/codificação declaradas")
        if any(raster.histogram()[251:255]):
            raise RuntimeError("PNG HAND contém valores reservados inválidos")
    return {"source_id": FIELD_SOURCE_ID, "hand_png_sha256": digest, "scope": FIELD_SCOPE, "hand_zero_cm": 160, "max_hand_m": 25.0}
