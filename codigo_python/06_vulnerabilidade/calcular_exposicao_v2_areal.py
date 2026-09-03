#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exposição v2 — interseção areal proporcional HAND × grade 200 m (amostragem interna)."""
from __future__ import annotations

import json
import re
import base64
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image
from shapely.geometry import Point

RAIZ = Path(__file__).resolve().parents[2]
OUT = RAIZ / "assets" / "data" / "exposicao_cruzada"

CIDADES = {
    "mucum": {
        "html": RAIZ / "mucum_previsao_inundacao.html",
        "cod_mun": "4312609",
        "nome": "Muçum",
        "bankfull_cm": 500,
        "cenarios_hand_m": [0.5, 2.0, 5.0, 10.0, 15.0, 17.02, 20.0, 25.0],
    },
    "santa_tereza": {
        "html": RAIZ / "santa_tereza_previsao_inundacao.html",
        "cod_mun": "4317251",
        "nome": "Santa Tereza",
        "bankfull_cm": 400,
        "cenarios_hand_m": [0.5, 2.0, 5.0, 10.0, 15.0],
    },
}


def load_hand(html_path: Path):
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', text, re.S)
    if not m:
        raise SystemExit(f"hand-data ausente em {html_path}")
    d = json.loads(m.group(1))
    arr = np.array(Image.open(io.BytesIO(base64.b64decode(d["hand_png_b64"]))).convert("L"))
    meta = {
        "W": float(d["W"]), "S": float(d["S"]), "E": float(d["E"]), "N": float(d["N"]),
        "cols": int(d["cols"]), "rows": int(d["rows"]),
    }
    return arr.astype(np.float32) / 10.0, meta


def hand_at_lonlat(hand_m: np.ndarray, meta: dict, lon: float, lat: float) -> float | None:
    if not (meta["W"] <= lon <= meta["E"] and meta["S"] <= lat <= meta["N"]):
        return None
    col = int((lon - meta["W"]) / (meta["E"] - meta["W"]) * meta["cols"])
    row = int((meta["N"] - lat) / (meta["N"] - meta["S"]) * meta["rows"])
    col = max(0, min(meta["cols"] - 1, col))
    row = max(0, min(meta["rows"] - 1, row))
    return float(hand_m[row, col])


def frac_exposta(geom, hand_m, meta, threshold_m, samples=4):
    minx, miny, maxx, maxy = geom.bounds
    xs = np.linspace(minx, maxx, samples)
    ys = np.linspace(miny, maxy, samples)
    inside = exposed = 0
    for x in xs:
        for y in ys:
            pt = Point(float(x), float(y))
            if not geom.contains(pt):
                continue
            inside += 1
            h = hand_at_lonlat(hand_m, meta, float(x), float(y))
            if h is not None and h <= threshold_m:
                exposed += 1
    if inside == 0:
        pt = geom.representative_point()
        h = hand_at_lonlat(hand_m, meta, pt.x, pt.y)
        return 1.0 if h is not None and h <= threshold_m else 0.0
    return exposed / inside


def agregar_areal(gdf: gpd.GeoDataFrame, hand_m, meta, threshold_m, fields):
    pop = dom = 0.0
    cells = 0
    for _, row in gdf.iterrows():
        f = frac_exposta(row.geometry, hand_m, meta, threshold_m)
        if f <= 0:
            continue
        cells += 1
        pop += float(row.get("pop") or 0) * f
        dom += float(row.get("dom") or 0) * f
    extras = {}
    if "i70m" in gdf.columns:
        i70 = 0.0
        for _, row in gdf.iterrows():
            f = frac_exposta(row.geometry, hand_m, meta, threshold_m)
            if f > 0:
                i70 += float(row.get("i70m") or 0) * f
        extras = {"idosos_70_mais": int(round(i70))}
    return {"celulas_com_exposicao": cells, "pop": int(round(pop)), "dom": int(round(dom)), **extras}


def calcular(key: str, cfg: dict) -> dict:
    hand_m, meta = load_hand(cfg["html"])
    grade = gpd.read_file(RAIZ / "assets/data/vulnerabilidade/grade" / f"{cfg['cod_mun']}.geojson")
    setores = gpd.read_file(RAIZ / "assets/data/vulnerabilidade/setores" / f"{cfg['cod_mun']}.geojson")
    pop_mun = int(grade["pop"].sum())
    niveis = []
    for hand_thr in cfg["cenarios_hand_m"]:
        if hand_thr > float(hand_m.max()):
            continue
        g = agregar_areal(grade, hand_m, meta, hand_thr, ["pop", "dom"])
        s = agregar_areal(setores, hand_m, meta, hand_thr, ["i70m"])
        niveis.append({
            "hand_m": round(hand_thr, 2),
            "nivel_rio_cm": round(cfg["bankfull_cm"] + hand_thr * 100, 0),
            "grade_200m": g,
            "setores_censitarios": s,
            "pct_pop_municipio": round(100 * g["pop"] / pop_mun, 1) if pop_mun else None,
        })
    return {
        "schema_version": 2,
        "artifact_id": f"exposicao-v2-areal-{key}",
        "cidade": cfg["nome"],
        "cod_ibge": cfg["cod_mun"],
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": {
            "versao": "v2-areal",
            "criterio": "Fração da célula grade 200 m com HAND ≤ limiar (amostragem 4×4 interna)",
            "limitacao": "Ainda sem edificações Open Buildings; população uniforme na célula",
        },
        "bankfull_cm": cfg["bankfull_cm"],
        "niveis": niveis,
    }


def main():
    alvo = sys.argv[1:] if len(sys.argv) > 1 else list(CIDADES)
    OUT.mkdir(parents=True, exist_ok=True)
    for key in alvo:
        if key not in CIDADES:
            continue
        print(f"== v2 areal {key} ==")
        result = calcular(key, CIDADES[key])
        out = OUT / f"exposicao_{key}_v2.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        pico = next((n for n in result["niveis"] if abs(n["hand_m"] - (17.02 if key == "mucum" else 15.0)) < 0.5), result["niveis"][-1] if result["niveis"] else None)
        if pico:
            print(f"   @ {pico['hand_m']} m: pop={pico['grade_200m']['pop']}")
    print("OK v2")


if __name__ == "__main__":
    main()
