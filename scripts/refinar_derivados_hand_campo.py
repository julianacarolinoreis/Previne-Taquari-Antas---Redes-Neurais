"""Corrige apenas o aninhamento vetorial e identifica derivados de campo já existentes.

Não recalcula ou modifica PNG/MDT/LiDAR. A fonte antiga é registrada por hash,
e todas as entradas são conferidas antes de escrever qualquer produto.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.ops import transform
from pyproj import Transformer
from shapely import set_precision

from santa_tereza_hand_field_contract import (
    EXPECTED_LEVELS, FIELD_SOURCE_ID, FIELD_SCOPE, SURFACE_RAW, SURFACE_ROUTING,
    validate_field_contours, validate_field_metadata, validate_raster_payload,
)

ROOT = Path(__file__).resolve().parents[1]
CONTOURS = ROOT / "assets/data/santa_tereza_inundacao/contornos_mancha.json"
PAGES = [ROOT / "santa_tereza_inundacao.html", ROOT / "santa_tereza_previsao_inundacao.html"]
REPORT = ROOT / "assets/data/santa_tereza_inundacao/field_vector_refinement_diagnostic.json"
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True).transform


def main() -> None:
    original = CONTOURS.read_bytes()
    document = json.loads(original)
    metadata = document.setdefault("metadata", {})
    metadata.setdefault("source_id", FIELD_SOURCE_ID)
    validate_field_metadata(metadata)
    features = sorted(document["features"], key=lambda feature: feature["properties"]["nivel_m"])
    if [f["properties"]["nivel_m"] for f in features] != EXPECTED_LEVELS:
        raise RuntimeError("fonte de campo incompleta; refino abortado")
    previous, repaired = None, []
    for feature in features:
        geometry = shape(feature["geometry"])
        if not geometry.is_valid or geometry.is_empty:
            raise RuntimeError("fonte de campo inválida; refino abortado")
        # Grade vetorial de ~0,1 m: elimina microlascas numéricas de união,
        # muito abaixo da resolução ~10 m; não filtra buracos por área.
        geometry = set_precision(geometry, grid_size=1e-6, mode="valid_output")
        # A união usa precisão flutuante: encaixar novas interseções de volta
        # na grade poderia deslocar uma borda antiga e recriar retrações.
        geometry = set_precision(geometry, grid_size=0)
        if previous is not None:
            loss = previous.difference(geometry).area
            if loss > 0:
                repaired.append({"hand_m": feature["properties"]["nivel_m"], "relative_retraction_removed": loss / previous.area})
            geometry = unary_union([previous, geometry])
        feature["geometry"] = mapping(geometry)
        feature["properties"]["area_ha"] = round(transform(TO_UTM, geometry).area / 10000, 1)
        previous = geometry
    document["features"] = features
    metadata["aninhamento_vetorial"] = "união cumulativa após simplificação; não modifica o raster LiDAR"
    metadata["precisao_vetorial_entrada_graus"] = 1e-6
    metadata.setdefault("pre_refinement_file_sha256", hashlib.sha256(original).hexdigest())
    _, _, provenance = validate_field_contours(document)

    replacements, png_hashes = [], {}
    for page in PAGES:
        html = page.read_text(encoding="utf-8")
        match = re.search(r'(<script id="hand-data" type="application/json">)(.*?)(</script>)', html, re.S)
        if not match:
            raise RuntimeError(f"payload HAND ausente em {page}")
        payload = json.loads(match.group(2))
        if "CLIP_MOSAICO_LIDAR_RS.tif bruto" not in payload.get("fonte", ""):
            raise RuntimeError("PNG não identificado como derivado do LiDAR bruto")
        payload.setdefault("source_id", FIELD_SOURCE_ID)
        payload.setdefault("cidade", "santa_tereza")
        payload.setdefault("rio", FIELD_SCOPE)
        payload.setdefault("superficie_inundacao", SURFACE_RAW)
        payload.setdefault("superficie_roteamento", SURFACE_ROUTING)
        digest = hashlib.sha256(base64.b64decode(payload["hand_png_b64"], validate=True)).hexdigest()
        payload.setdefault("hand_png_sha256", digest)
        validate_raster_payload(payload)
        png_hashes[page.name] = digest
        replacement = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        replacements.append((page, html[:match.start(2)] + replacement + html[match.end(2):]))
    if len(set(png_hashes.values())) != 1:
        raise RuntimeError("as duas páginas não usam o mesmo PNG HAND")

    # Todas as entradas e os produtos foram validados acima; pixels preservados.
    CONTOURS.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for page, html in replacements:
        page.write_text(html, encoding="utf-8")
    report = {
        "status": "vector_nesting_repaired_rasters_unchanged",
        "original_contours_file_sha256": hashlib.sha256(original).hexdigest(),
        "output_contours_file_sha256": hashlib.sha256(CONTOURS.read_bytes()).hexdigest(),
        "provenance": provenance,
        "levels_with_retraction_removed": repaired,
        "hand_png_sha256_unchanged": png_hashes,
        "limit": "Refino de um proxy vetorial de pesquisa; não valida inundação observada ou rota segura.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "levels_repaired": len(repaired), "png_unchanged": True}))


if __name__ == "__main__":
    main()
