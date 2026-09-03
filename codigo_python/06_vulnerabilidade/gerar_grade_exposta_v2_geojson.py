#!/usr/bin/env python3
"""Publica células grade 200 m expostas (v2 areal) como GeoJSON."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from calcular_exposicao_v2_areal import CIDADES, frac_exposta, hand_at_lonlat, load_hand  # noqa: E402

OUT = ROOT / "assets" / "data" / "exposicao_cruzada"
DEFAULT_HAND = {"mucum": 17.02, "santa_tereza": 15.0}


def gerar_v2(key: str, hand_thr: float) -> dict:
    cfg = CIDADES[key]
    hand_m, meta = load_hand(cfg["html"])
    cod = cfg["cod_mun"]
    grade = gpd.read_file(ROOT / "assets/data/vulnerabilidade/grade" / f"{cod}.geojson")
    features = []
    pop = dom = 0.0
    for _, row in grade.iterrows():
        f = frac_exposta(row.geometry, hand_m, meta, hand_thr)
        if f <= 0:
            continue
        p = float(row.get("pop") or 0) * f
        d = float(row.get("dom") or 0) * f
        pop += p
        dom += d
        pt = row.geometry.representative_point()
        h = hand_at_lonlat(hand_m, meta, pt.x, pt.y)
        geom = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]["geometry"]
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "id_grade": row.get("id_grade"),
                "pop": int(round(p)),
                "dom": int(round(d)),
                "frac_exposta": round(f, 3),
                "hand_m": round(h, 2) if h is not None else None,
                "hand_limite_m": hand_thr,
                "cod_mun": cod,
                "cidade": cfg["nome"],
            },
        })
    nivel_cm = cfg["bankfull_cm"] + hand_thr * 100
    collection = {
        "type": "FeatureCollection",
        "name": f"grade_exposta_{key}_v2",
        "metadata": {
            "schema_version": 2,
            "cidade": cfg["nome"],
            "cod_ibge": cod,
            "hand_limite_m": hand_thr,
            "nivel_rio_cm": round(nivel_cm, 0),
            "celulas": len(features),
            "pop": int(round(pop)),
            "dom": int(round(dom)),
            "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metodo": "Fração areal 4×4 da célula com HAND ≤ limiar (v2).",
            "limitacao": "População proporcional à fração exposta; sem Open Buildings.",
        },
        "features": features,
    }
    out_path = OUT / f"grade_exposta_{key}_v2.geojson"
    out_path.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    print(f"   -> {out_path.relative_to(ROOT)} ({len(features)} células, pop={int(round(pop))})")
    return collection


def main():
    keys = sys.argv[1:] if len(sys.argv) > 1 else list(CIDADES)
    OUT.mkdir(parents=True, exist_ok=True)
    for key in keys:
        if key not in CIDADES:
            continue
        thr = DEFAULT_HAND.get(key, 15.0)
        print(f"== v2 geojson {key} @ {thr} m ==")
        gerar_v2(key, thr)
    print("OK v2 geojson")


if __name__ == "__main__":
    main()
