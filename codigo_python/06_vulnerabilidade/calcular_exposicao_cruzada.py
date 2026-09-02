#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cruzamento espacial: mancha HAND (por cota) × grade 200 m e setores censitários.

Publica assets/data/exposicao_cruzada/exposicao_{cidade}.json com população e
domicílios dentro da mancha por nível HAND, mais idosos por setor (amostra no
centroide — ver nota de método).

Uso:
  python codigo_python/06_vulnerabilidade/calcular_exposicao_cruzada.py
  python codigo_python/06_vulnerabilidade/calcular_exposicao_cruzada.py mucum
"""
from __future__ import annotations

import json
import re
import base64
import io
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
        "W": float(d["W"]),
        "S": float(d["S"]),
        "E": float(d["E"]),
        "N": float(d["N"]),
        "cols": int(d["cols"]),
        "rows": int(d["rows"]),
        "bankfull_cm": int(d.get("bankfull_cm") or 0),
    }
    hand_m = arr.astype(np.float32) / 10.0
    return hand_m, meta


def hand_at_lonlat(hand_m: np.ndarray, meta: dict, lon: float, lat: float) -> float | None:
    if not (meta["W"] <= lon <= meta["E"] and meta["S"] <= lat <= meta["N"]):
        return None
    col = int((lon - meta["W"]) / (meta["E"] - meta["W"]) * meta["cols"])
    row = int((meta["N"] - lat) / (meta["N"] - meta["S"]) * meta["rows"])
    col = max(0, min(meta["cols"] - 1, col))
    row = max(0, min(meta["rows"] - 1, row))
    return float(hand_m[row, col])


def nivel_cm_to_hand_m(nivel_cm: float, bankfull_cm: int) -> float:
    return max(0.0, (nivel_cm - bankfull_cm) / 100.0)


def agregar_unidade(gdf: gpd.GeoDataFrame, hand_m: np.ndarray, meta: dict, threshold_m: float, fields: list[str]):
    pop = dom = 0
    cells = 0
    for _, row in gdf.iterrows():
        pt = row.geometry.representative_point()
        h = hand_at_lonlat(hand_m, meta, pt.x, pt.y)
        if h is None or h > threshold_m:
            continue
        cells += 1
        for f in fields:
            val = row.get(f)
            if f == "pop":
                pop += int(val or 0)
            elif f == "dom":
                dom += int(val or 0)
            elif f == "i60_69":
                pass  # handled below
    extras = {}
    if "i60_69" in fields or "i70m" in fields:
        i60 = i70 = 0
        for _, row in gdf.iterrows():
            pt = row.geometry.representative_point()
            h = hand_at_lonlat(hand_m, meta, pt.x, pt.y)
            if h is None or h > threshold_m:
                continue
            i60 += int(row.get("i60_69") or 0)
            i70 += int(row.get("i70m") or 0)
        extras = {"idosos_60_69": i60, "idosos_70_mais": i70}
    return {"celulas_ou_setores": cells, "pop": pop, "dom": dom, **extras}


def calcular_cidade(key: str, cfg: dict) -> dict:
    hand_m, meta = load_hand(cfg["html"])
    cod = cfg["cod_mun"]
    grade_path = RAIZ / "assets" / "data" / "vulnerabilidade" / "grade" / f"{cod}.geojson"
    setor_path = RAIZ / "assets" / "data" / "vulnerabilidade" / "setores" / f"{cod}.geojson"
    grade = gpd.read_file(grade_path)
    setores = gpd.read_file(setor_path)

    pop_mun = int(grade["pop"].sum())
    dom_mun = int(grade["dom"].sum())

    niveis = []
    for hand_thr in cfg["cenarios_hand_m"]:
        if hand_thr > float(hand_m.max()):
            continue
        g = agregar_unidade(grade, hand_m, meta, hand_thr, ["pop", "dom"])
        s = agregar_unidade(setores, hand_m, meta, hand_thr, ["i60_69", "i70m"])
        nivel_cm = cfg["bankfull_cm"] + hand_thr * 100
        niveis.append({
            "hand_m": round(hand_thr, 2),
            "nivel_rio_cm": round(nivel_cm, 0),
            "grade_200m": g,
            "setores_censitarios": s,
            "pct_pop_municipio": round(100 * g["pop"] / pop_mun, 1) if pop_mun else None,
            "pct_dom_municipio": round(100 * g["dom"] / dom_mun, 1) if dom_mun else None,
        })

    return {
        "schema_version": 1,
        "artifact_id": f"exposicao-cruzada-{key}",
        "cidade": cfg["nome"],
        "cod_ibge": cod,
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": {
            "mancha": "HAND raster embutido na página de previsão (mesma fonte do popup)",
            "unidade_grade": "Grade Estatística IBGE 2022 · células 200 m",
            "unidade_setor": "Setores censitários IBGE 2022",
            "criterio": "Centroide da unidade com HAND ≤ limiar (aproximação; não substitui interseção areal)",
            "limitacao": "Não inclui edificações Open Buildings; população diurna/noturna não diferenciada",
        },
        "bankfull_cm": cfg["bankfull_cm"],
        "hand_max_m": round(float(hand_m.max()), 1),
        "totais_municipio": {"pop_grade": pop_mun, "dom_grade": dom_mun},
        "niveis": niveis,
    }


def main():
    import sys

    alvo = sys.argv[1:] if len(sys.argv) > 1 else list(CIDADES)
    OUT.mkdir(parents=True, exist_ok=True)
    index = {"schema_version": 1, "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cidades": {}}

    for key in alvo:
        if key not in CIDADES:
            print(f"[aviso] cidade desconhecida: {key}")
            continue
        cfg = CIDADES[key]
        print(f"== {cfg['nome']} ==")
        result = calcular_cidade(key, cfg)
        out_path = OUT / f"exposicao_{key}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"   -> {out_path.relative_to(RAIZ)} ({len(result['niveis'])} níveis)")
        pico = next((n for n in result["niveis"] if abs(n["hand_m"] - 17.02) < 0.01), result["niveis"][-1] if result["niveis"] else None)
        if pico:
            print(f"   @ {pico['hand_m']} m: pop={pico['grade_200m']['pop']} dom={pico['grade_200m']['dom']}")
        index["cidades"][key] = {
            "nome": cfg["nome"],
            "cod_ibge": cfg["cod_mun"],
            "arquivo": f"assets/data/exposicao_cruzada/exposicao_{key}.json",
            "niveis_publicados": len(result["niveis"]),
        }

    (OUT / "indice.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK")


if __name__ == "__main__":
    main()
