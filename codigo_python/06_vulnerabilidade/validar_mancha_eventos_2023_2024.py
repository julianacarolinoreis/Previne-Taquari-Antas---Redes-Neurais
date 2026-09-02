#!/usr/bin/env python3
"""Validação cruzada SGB × HAND para eventos ST 2023/2024."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "data" / "validacao_eventos"
sys.path.insert(0, str(ROOT / "codigo_python" / "06_vulnerabilidade"))
from calcular_exposicao_cruzada import hand_at_lonlat, load_hand  # noqa: E402

BANKFULL_CM = 400
SGB = ROOT / "assets" / "data" / "vulnerabilidade" / "perigo" / "setores_risco_sgb_santa_tereza.geojson"
HAND_HTML = ROOT / "santa_tereza_previsao_inundacao.html"
EVENTOS = ROOT / "assets" / "data" / "eventos_analise.json"
REPLAY = ROOT / "assets" / "data" / "research_event_replay_latest.json"

EVENTOS_ALVO = [
    {
        "id": "st-set-2023",
        "label": "Cheia setembro/2023 · ponte Santa Bárbara",
        "pico_data": "2023-09-04",
        "pico_cm_catalogo": 2365,
        "pico_cm_referencia": 2365,
        "fonte_pico": "assets/data/eventos_analise.json",
    },
    {
        "id": "st-mai-2024",
        "label": "Cheia maio/2024 · recorde recente",
        "pico_data": "2024-04-29",
        "pico_cm_catalogo": 2232,
        "pico_cm_referencia": 2582,
        "fonte_pico": "telemetria ANA + assets/data/servicos/abrigos.geojson (recorde mai/2024)",
        "nota_pico": "Catálogo RNA usa pico 2232 cm; telemetria bruta e cadastro DC citam ~2582 cm — ambos reportados.",
    },
]


def nivel_to_hand_m(nivel_cm: float) -> float:
    return max(0.0, (nivel_cm - BANKFULL_CM) / 100.0)


def avaliar_evento(gdf: gpd.GeoDataFrame, hand_m, meta: dict, evento: dict, use_ref: bool) -> dict:
    pico = evento["pico_cm_referencia"] if use_ref else evento["pico_cm_catalogo"]
    thr = nivel_to_hand_m(pico)
    inundacao = gdf[gdf["tipolo_g1"].astype(str).str.contains("Inunda", case=False, na=False)]
    setores = []
    expostos_hand = 0
    expostos_sgb = 0
    concordantes = 0
    for _, row in inundacao.iterrows():
        pt = row.geometry.representative_point()
        h = hand_at_lonlat(hand_m, meta, pt.x, pt.y)
        hand_exposto = h is not None and h <= thr
        sgb_exposto = True  # setor SGB de inundação = evidência de campo
        if hand_exposto:
            expostos_hand += 1
        if sgb_exposto:
            expostos_sgb += 1
        if hand_exposto and sgb_exposto:
            concordantes += 1
        setores.append({
            "num_setor": row.get("num_setor"),
            "local": row.get("local"),
            "grau_risco": row.get("grau_risco"),
            "num_pess": row.get("num_pess"),
            "hand_centroide_m": round(h, 2) if h is not None else None,
            "hand_limite_evento_m": round(thr, 2),
            "hand_indica_exposicao": hand_exposto,
            "sgb_inundacao": sgb_exposto,
            "concordancia": hand_exposto and sgb_exposto,
        })
    total = len(setores)
    taxa = round(100 * concordantes / total, 1) if total else None
    return {
        **evento,
        "pico_cm_usado": pico,
        "hand_limite_m": round(thr, 2),
        "nivel_rio_m": round(pico / 100, 2),
        "setores_inundacao_sgb": total,
        "concordantes_hand_sgb": concordantes,
        "taxa_concordancia_pct": taxa,
        "hand_expostos": expostos_hand,
        "interpretacao": (
            "Concordância = setor SGB de inundação com centroide HAND ≤ limiar do pico. "
            "Divergências esperadas: HAND tipo banheira, datum régua≠HAND, setor ≠ mancha contínua."
        ),
        "setores": setores,
    }


def main():
    hand_m, meta = load_hand(HAND_HTML)
    gdf = gpd.read_file(SGB)
    resultados = []
    for ev in EVENTOS_ALVO:
        resultados.append(avaliar_evento(gdf, hand_m, meta, ev, use_ref=False))
        if ev.get("pico_cm_referencia") != ev.get("pico_cm_catalogo"):
            alt = dict(ev)
            alt["id"] = ev["id"] + "-telemetria"
            alt["label"] = ev["label"] + " · pico telemetria"
            resultados.append(avaliar_evento(gdf, hand_m, meta, alt, use_ref=True))

    relatorio = {
        "schema_version": 1,
        "artifact_id": "validacao-mancha-st-2023-2024",
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "municipio": "Santa Tereza",
        "cod_ibge": "4317251",
        "bankfull_cm": BANKFULL_CM,
        "metodo": {
            "sgb": str(SGB.relative_to(ROOT)),
            "hand": "raster embutido em santa_tereza_previsao_inundacao.html",
            "criterio": "Centroide do setor SGB (inundação) vs HAND no pico do evento",
            "gate": "Pesquisa — não é validação operacional de mancha oficial",
        },
        "fontes": [
            str(EVENTOS.relative_to(ROOT)),
            str(REPLAY.relative_to(ROOT)),
            str(SGB.relative_to(ROOT)),
        ],
        "eventos": resultados,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "relatorio_2023_2024.json"
    out.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(ROOT)} ({len(resultados)} avaliações)")
    for r in resultados:
        print(f"   {r['id']}: concordância {r['taxa_concordancia_pct']}% ({r['concordantes_hand_sgb']}/{r['setores_inundacao_sgb']})")
    print("OK")


if __name__ == "__main__":
    main()
