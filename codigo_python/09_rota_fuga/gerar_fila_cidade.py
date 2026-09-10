#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fila de evacuação da cidade toda — grade IBGE × HAND × rota a pé.

Gera o JSON que a previsão ao vivo usa para contar PESSOAS (não 3 casas) e
pintar a grade no mapa. Rotas-exemplo (seca/fuga por HAND) entram se já
existirem no sidecar do estudo de caso.

Uso:
  py codigo_python/09_rota_fuga/gerar_fila_cidade.py
  py codigo_python/09_rota_fuga/gerar_fila_cidade.py --cidade mucum
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.ops import unary_union

RAIZ = Path(__file__).resolve().parents[2]
PASSO = 0.5
VEL_IDOSO = 0.9

CIDADES = {
    "mucum": {
        "cod": "4312609",
        "municipio": "Muçum",
        "zero_regua_m": 5.0,
        "contornos": RAIZ / "assets" / "data" / "mucum_inundacao" / "contornos_mancha.json",
        "rf": RAIZ / "assets" / "data" / "rota_fuga" / "rota_fuga_ruas_mucum_cenario.json",
        "casas": RAIZ / "assets" / "data" / "rota_fuga" / "fila_evacuacao_mucum.json",
        "saida": RAIZ / "assets" / "data" / "rota_fuga" / "fila_cidade_mucum.json",
    },
    "santa_tereza": {
        "cod": "4317251",
        "municipio": "Santa Tereza",
        "zero_regua_m": 4.0,
        "contornos": RAIZ / "assets" / "data" / "santa_tereza_inundacao" / "contornos_mancha.json",
        "rf": RAIZ / "assets" / "data" / "rota_fuga" / "rota_fuga_ruas_santa_tereza.json",
        "casas": None,
        "saida": RAIZ / "assets" / "data" / "rota_fuga" / "fila_cidade_santa_tereza.json",
    },
}


def unioes(contornos_path: Path):
    dc = json.loads(contornos_path.read_text(encoding="utf-8"))
    porn = {}
    for f in dc["features"]:
        nv = round(float(f["properties"]["nivel_m"]), 1)
        nb = round(int(nv / PASSO) * PASSO, 1)
        porn.setdefault(nb, []).append(shape(f["geometry"]).buffer(0))
    niveis = sorted(porn)
    return {nv: unary_union(porn[nv]) for nv in niveis}, niveis


def cota_de(ponto, U, niveis):
    for nv in niveis:
        if U[nv].covers(ponto):
            return nv
    return None


def no_prox(nos, lat, lon):
    best, bd = 0, 1e18
    clat = math.cos(math.radians(lat))
    for i, (la, lo) in enumerate(nos):
        dy = la - lat
        dx = (lo - lon) * clat
        d = dy * dy + dx * dx
        if d < bd:
            bd = d
            best = i
    return best


def simplifica(pts, max_pts=18):
    if len(pts) <= max_pts:
        return pts
    step = max(1, (len(pts) - 1) // (max_pts - 1))
    out = [pts[0]]
    for i in range(step, len(pts) - 1, step):
        out.append(pts[i])
    out.append(pts[-1])
    return out


def rota_no(rf, i):
    nos, prox = rf["nos"], rf["prox"]
    sh = {a["node"] for a in rf["abrigos"] if a.get("node") is not None}
    pts, seen = [], set()
    cur = i
    for _ in range(8000):
        la, lo = nos[cur]
        pts.append([round(la, 5), round(lo, 5)])
        if cur in sh or cur in seen:
            break
        seen.add(cur)
        n = prox[cur]
        if n is None or n < 0 or n == cur:
            break
        cur = n
    return simplifica(pts)


def casas_st(cells):
    """Três células-exemplo em cotas distintas, com a rota a pé do grafo."""
    cand = [c for c in cells if c.get("cota") is not None and 1.5 <= c["cota"] <= 10]
    if len(cand) < 3:
        cand = [c for c in cells if c.get("cota") is not None]
    cand = sorted(cand, key=lambda c: c["cota"])
    if len(cand) < 3:
        return []
    picks = [cand[0], cand[len(cand) // 2], cand[-1]]
    nomes = ("Casa na várzea", "Casa no centro baixo", "Casa na encosta")
    blurbs = (
        "A RNA alcança primeiro — sair cedo.",
        "Entra na fila quando o alerta sobe.",
        "Só vira prioridade na cheia alta.",
    )
    out = []
    for i, (c, nome, blurb) in enumerate(zip(picks, nomes, blurbs), 1):
        out.append({
            "id": f"c{i}",
            "nome": nome,
            "blurb": blurb,
            "lat": c["lat"],
            "lon": c["lon"],
            "cota_hand_m": c["cota"],
            "dist_m": c["dist_m"],
            "min_idoso": c["min_idoso"],
            "abrigo": c["abrigo"],
            "rota": c.get("rota") or [[c["lat"], c["lon"]]],
        })
    return out


def gerar(slug: str):
    cfg = CIDADES[slug]
    grade_path = RAIZ / "assets" / "data" / "vulnerabilidade" / "grade" / f"{cfg['cod']}.geojson"
    rf = json.loads(cfg["rf"].read_text(encoding="utf-8"))
    nos, distn, dest = rf["nos"], rf["dist_m"], rf["dest"]
    abrigos = rf["abrigos"]
    by_id = {a["id"]: a for a in abrigos}
    U, niveis = unioes(cfg["contornos"])

    grade = json.loads(grade_path.read_text(encoding="utf-8"))
    cells = []
    pop_total = 0
    pop_risco = 0
    for f in grade["features"]:
        pop = float(f["properties"].get("pop", 0) or 0)
        if pop <= 0:
            continue
        g = shape(f["geometry"])
        c = g.centroid
        lat, lon = round(c.y, 6), round(c.x, 6)
        cota = cota_de(Point(lon, lat), U, niveis)
        i = no_prox(nos, lat, lon)
        ab = by_id.get(dest[i]) if i < len(dest) else None
        rec = {
            "pop": round(pop),
            "cota": cota,
            "dist_m": round(distn[i]) if i < len(distn) else None,
            "min_idoso": round((distn[i] or 0) / VEL_IDOSO / 60) if i < len(distn) else None,
            "lat": lat,
            "lon": lon,
            "abrigo": (ab or {}).get("nome"),
            "rota": rota_no(rf, i),
        }
        cells.append(rec)
        pop_total += pop
        if cota is not None:
            pop_risco += pop

    casas = []
    if cfg["casas"] and cfg["casas"].exists():
        raw = json.loads(cfg["casas"].read_text(encoding="utf-8"))
        keys = (
            "id", "nome", "blurb", "lat", "lon", "cota_hand_m", "dist_m",
            "min_idoso", "abrigo", "abrigo_lat", "abrigo_lon", "rota",
            "rotas_seca", "rotas_fuga",
        )
        casas = [{k: c[k] for k in keys if k in c} for c in raw.get("casas") or []]
    elif slug == "santa_tereza":
        casas = casas_st(cells)

    doc = {
        "meta": {
            "municipio": cfg["municipio"],
            "zero_regua_m": cfg["zero_regua_m"],
            "vel_idoso_ms": VEL_IDOSO,
            "pop_total": round(pop_total),
            "pop_risco": round(pop_risco),
            "celulas": len(cells),
        },
        "abrigos": [{"lat": a["lat"], "lon": a["lon"], "nome": a["nome"]} for a in abrigos],
        "cells": cells,
        "casas": casas,
    }
    cfg["saida"].parent.mkdir(parents=True, exist_ok=True)
    cfg["saida"].write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{cfg['municipio']}: {len(cells)} celulas, pop {pop_total:.0f} "
          f"(risco HAND {pop_risco:.0f}), {len(casas)} casas-exemplo -> {cfg['saida']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cidade", choices=list(CIDADES), action="append")
    args = ap.parse_args()
    for slug in args.cidade or list(CIDADES):
        gerar(slug)


if __name__ == "__main__":
    main()
