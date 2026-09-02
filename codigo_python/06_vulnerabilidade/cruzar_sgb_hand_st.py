#!/usr/bin/env python3
"""Cruzamento setores SGB Santa Tereza × HAND (centroide + faixas)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "data" / "vulnerabilidade" / "perigo"
SGB = OUT / "setores_risco_sgb_santa_tereza.geojson"
HAND_HTML = ROOT / "santa_tereza_previsao_inundacao.html"

sys.path.insert(0, str(ROOT / "codigo_python" / "06_vulnerabilidade"))
from calcular_exposicao_cruzada import hand_at_lonlat, load_hand  # noqa: E402

BANKFULL = 400
FAIXAS_HAND = [0.5, 2.0, 5.0, 10.0, 15.0, 18.0, 21.0]


def faixa_label(h: float | None) -> str:
    if h is None:
        return "fora_raster"
    for thr in FAIXAS_HAND:
        if h <= thr:
            return f"≤{thr}m"
    return f">{FAIXAS_HAND[-1]}m"


def main():
    hand_m, meta = load_hand(HAND_HTML)
    gdf = gpd.read_file(SGB)
    setores = []
    features = []
    for _, row in gdf.iterrows():
        pt = row.geometry.representative_point()
        h = hand_at_lonlat(hand_m, meta, pt.x, pt.y)
        nivel_cm = None if h is None else round(BANKFULL + h * 100, 0)
        rec = {
            "num_setor": row.get("num_setor"),
            "local": row.get("local"),
            "tipologia": row.get("tipolo_g1"),
            "grau_risco": row.get("grau_risco"),
            "grau_vulnerabilidade": row.get("grau_vulne"),
            "num_pess": row.get("num_pess"),
            "num_edif": row.get("num_edif"),
            "hand_centroide_m": round(h, 2) if h is not None else None,
            "nivel_rio_equiv_cm": nivel_cm,
            "faixa_hand": faixa_label(h),
            "inundacao": "Inunda" in str(row.get("tipolo_g1") or ""),
        }
        setores.append(rec)
        geom = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]["geometry"]
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": rec,
        })

    payload = {
        "schema_version": 1,
        "artifact_id": "sgb-hand-cruzamento-st",
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "municipio": "Santa Tereza",
        "cod_ibge": "4317251",
        "bankfull_cm": BANKFULL,
        "metodo": "Centroide do polígono SGB amostrado no raster HAND (mesma fonte da previsão).",
        "limitacao": "Não substitui visita de campo nem mancha contínua; deslizamentos usam a mesma amostra espacial.",
        "totais": {
            "setores": len(setores),
            "inundacao": sum(1 for s in setores if s["inundacao"]),
            "hand_ate_15m": sum(1 for s in setores if s["hand_centroide_m"] is not None and s["hand_centroide_m"] <= 15),
            "hand_acima_18m": sum(1 for s in setores if s["hand_centroide_m"] is not None and s["hand_centroide_m"] > 18),
        },
        "setores": setores,
    }
    json_path = OUT / "sgb_hand_cruzamento_st.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    geo = {
        "type": "FeatureCollection",
        "name": "sgb_hand_cruzamento_st",
        "metadata": {k: v for k, v in payload.items() if k != "setores"},
        "features": features,
    }
    geo_path = OUT / "sgb_hand_cruzamento_st.geojson"
    geo_path.write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    print(f"-> {json_path.relative_to(ROOT)}")
    print(f"-> {geo_path.relative_to(ROOT)} ({len(features)} setores)")
    print("OK")


if __name__ == "__main__":
    main()
