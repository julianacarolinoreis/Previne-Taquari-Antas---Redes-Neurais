#!/usr/bin/env python3
"""Publica células da grade 200 m expostas por limiar HAND como GeoJSON."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

# reutiliza helpers do cálculo de exposição
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from calcular_exposicao_cruzada import CIDADES, hand_at_lonlat, load_hand  # noqa: E402

OUT = ROOT / "assets" / "data" / "exposicao_cruzada"

DEFAULT_HAND = {
    "mucum": 17.02,
    "santa_tereza": 15.0,
}


def gerar(key: str, hand_thr: float) -> dict:
    cfg = CIDADES[key]
    hand_m, meta = load_hand(cfg["html"])
    cod = cfg["cod_mun"]
    grade = gpd.read_file(ROOT / "assets" / "data" / "vulnerabilidade" / "grade" / f"{cod}.geojson")
    features = []
    pop = dom = 0
    for _, row in grade.iterrows():
        pt = row.geometry.representative_point()
        h = hand_at_lonlat(hand_m, meta, pt.x, pt.y)
        if h is None or h > hand_thr:
            continue
        pop += int(row.get("pop") or 0)
        dom += int(row.get("dom") or 0)
        geom = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]["geometry"]
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "id_grade": row.get("id_grade"),
                "pop": int(row.get("pop") or 0),
                "dom": int(row.get("dom") or 0),
                "hand_m": round(h, 2),
                "hand_limite_m": hand_thr,
                "cod_mun": cod,
                "cidade": cfg["nome"],
            },
        })
    nivel_cm = cfg["bankfull_cm"] + hand_thr * 100
    collection = {
        "type": "FeatureCollection",
        "name": f"grade_exposta_{key}",
        "metadata": {
            "schema_version": 1,
            "cidade": cfg["nome"],
            "cod_ibge": cod,
            "hand_limite_m": hand_thr,
            "nivel_rio_cm": round(nivel_cm, 0),
            "celulas": len(features),
            "pop": pop,
            "dom": dom,
            "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metodo": "Centroide da célula 200 m com HAND ≤ limiar (mesma fonte raster da previsão).",
            "limitacao": "Não substitui mancha contínua nem interseção areal exata.",
        },
        "features": features,
    }
    out_path = OUT / f"grade_exposta_{key}.geojson"
    out_path.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    print(f"   -> {out_path.relative_to(ROOT)} ({len(features)} células, pop={pop})")
    return collection


def main():
    keys = sys.argv[1:] if len(sys.argv) > 1 else list(CIDADES)
    OUT.mkdir(parents=True, exist_ok=True)
    for key in keys:
        if key not in CIDADES:
            print(f"[aviso] cidade desconhecida: {key}")
            continue
        print(f"== {CIDADES[key]['nome']} @ HAND {DEFAULT_HAND.get(key, 15.0)} m ==")
        gerar(key, DEFAULT_HAND.get(key, 15.0))
    print("OK")


if __name__ == "__main__":
    main()
