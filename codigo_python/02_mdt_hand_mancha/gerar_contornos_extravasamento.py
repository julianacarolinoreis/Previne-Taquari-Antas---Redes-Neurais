#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera a camada web que exclui o contorno-base HAND 0 do leito.

A fonte continua sendo ``contornos_mancha.json``. Para cada nível acima de
zero, o arquivo de saída contém somente ``contorno(nível) - contorno(0)``.
Isso evita que o rio permanente seja pintado como inundação. O HAND 0 ainda é
um proxy operacional; não substitui uma máscara observada do leito em período
seco nem valida o limiar físico de extravasamento.

Uso:
    python codigo_python/02_mdt_hand_mancha/gerar_contornos_extravasamento.py
"""

from __future__ import annotations

import json
from pathlib import Path

from pyproj import Transformer
from shapely import difference, set_precision
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform, unary_union
from shapely.validation import make_valid


RAIZ = Path(__file__).resolve().parents[2]
ARQUIVOS = {
    "santa_tereza": (
        RAIZ / "assets/data/santa_tereza_inundacao/contornos_mancha.json",
        RAIZ / "assets/data/santa_tereza_inundacao/contornos_extravasamento.json",
    ),
    "mucum": (
        RAIZ / "assets/data/mucum_inundacao/contornos_mancha.json",
        RAIZ / "assets/data/mucum_inundacao/contornos_extravasamento.json",
    ),
}
GRADE_GRAUS = 1e-6
PARA_UTM_22S = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True).transform


def somente_poligonos(geom):
    """Descarta linhas/pontos residuais de operações topológicas."""
    if geom.is_empty:
        return None
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    partes = [g for g in getattr(geom, "geoms", ()) if isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty]
    return unary_union(partes) if partes else None


def valida(geom):
    geom = set_precision(geom, GRADE_GRAUS, mode="valid_output")
    if not geom.is_valid:
        geom = make_valid(geom)
    return somente_poligonos(geom)


def area_ha(geom) -> float:
    return transform(PARA_UTM_22S, geom).area / 10_000


def gerar(cidade: str, origem: Path, destino: Path) -> None:
    dados = json.loads(origem.read_text(encoding="utf-8"))
    por_nivel = {round(float(f["properties"]["nivel_m"]), 1): f for f in dados["features"]}
    if 0.0 not in por_nivel:
        raise RuntimeError(f"{origem} não contém o contorno HAND 0")

    base_feature = por_nivel[0.0]
    base = valida(shape(base_feature["geometry"]))
    if base is None:
        raise RuntimeError(f"contorno HAND 0 inválido em {origem}")
    base_ha = area_ha(base)

    saida = []
    for nivel in sorted(n for n in por_nivel if n > 0):
        feature = por_nivel[nivel]
        total = valida(shape(feature["geometry"]))
        if total is None:
            continue
        extra = valida(difference(total, base, grid_size=GRADE_GRAUS))
        if extra is None or extra.is_empty:
            continue
        extra_ha = area_ha(extra)
        props = dict(feature.get("properties") or {})
        props.update(
            area_total_hand_ha=props.get("area_ha"),
            area_base_hand_ha=round(base_ha, 1),
            area_ha=round(extra_ha, 1),
            interpretacao="proxy de extravasamento relativo ao contorno HAND 0",
        )
        saida.append({"type": "Feature", "properties": props, "geometry": mapping(extra)})

    payload = {
        "type": "FeatureCollection",
        "features": saida,
        "metadata": {
            "cidade": cidade,
            "fonte": str(origem.relative_to(RAIZ)).replace("\\", "/"),
            "metodo": "diferenca vetorial contorno_HAND_nivel menos contorno_HAND_0",
            "area": "calculada em SIRGAS 2000 / UTM 22S (EPSG:31982)",
            "interpretacao": "proxy de extravasamento; o HAND 0 aproxima o leito e ainda requer validação com máscara observada",
            "nao_confundir_com": "cota oficial de inundação ou probabilidade de inundação",
        },
    }
    destino.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{cidade}: {len(saida)} níveis -> {destino} ({destino.stat().st_size / 1024 / 1024:.1f} MiB)")


def main() -> None:
    for cidade, (origem, destino) in ARQUIVOS.items():
        gerar(cidade, origem, destino)


if __name__ == "__main__":
    main()
