#!/usr/bin/env python3
"""STUDY: pluviometry inventory + model-scope decision brief (no HEC).

1) Rain stations inside G040: ANA plu (28*), INMET RS, PREVINE CEMADEN seed
2) Decision page comparing corredor-Muçum vs G040 completa vs hibrido

Does NOT build HEC structure or calibrate.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import Point, shape
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
UA = {"User-Agent": "PREVINE-estudo-pluvio-recorte/1.0"}
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx"

UPG_FAMILY_HINT = {
    "Prata": "7868",
    "Carreiro": "7866",
    "Guaporé": "7864",
    "Forqueta": "7862",
    "Alto Taquari-Antas": "786",
    "Médio Taquari-Antas": "786",
    "Baixo Taquari-Antas": "786",
}

PREVINE_RAIN = {
    "86472600": {"rede": "ANA_flu_como_chuva", "papel": "chuva STZ / Excel-mae"},
    "86472000": {"rede": "ANA_flu_como_chuva", "papel": "chuva Antas / Excel-mae"},
    "2851072": {"rede": "ANA_plu", "papel": "chuva Carreiro-Prata / Excel-mae 8h"},
    "2851044": {"rede": "ANA_plu", "papel": "chuva Carreiro legado (coluna vazia no CSV)"},
    "A894": {"rede": "INMET", "papel": "Serafina Correa automatica (pode estar em pane)"},
    "432040401A": {
        "rede": "CEMADEN",
        "papel": "Serafina Correa Centro",
        "lat": -28.7125,
        "lon": -51.8667,
        "nome": "Serafina Correa - Centro",
    },
}


def http_bytes(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def http_json(url: str) -> Any:
    return json.loads(http_bytes(url).decode("utf-8-sig"))


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_ana(raw: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    text = (root.text or "").strip()
    if text.startswith("<"):
        root = ET.fromstring(text)
    rows = []
    for table in root.iter():
        if local_tag(table.tag) != "Table":
            continue
        row = {local_tag(c.tag): (c.text or "").strip() for c in list(table)}
        if row.get("Codigo"):
            rows.append(row)
    return rows


def ana_inventario(**params: str) -> list[dict[str, str]]:
    q = {
        "codEstDE": "",
        "codEstATE": "",
        "tpEst": "",
        "nmEst": "",
        "nmRio": "",
        "codSubBacia": "",
        "codBacia": "",
        "nmMunicipio": "",
        "nmEstado": "",
        "sgResp": "",
        "sgOper": "",
        "telemetrica": "",
    }
    q.update(params)
    return parse_ana(http_bytes(ANA + "/HidroInventario?" + urllib.parse.urlencode(q)))


def fnum(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ugs = json.loads((OUT / "ugs_g040.geojson").read_text(encoding="utf-8"))
    bacias = json.loads((OUT / "bacias_rs_25.geojson").read_text(encoding="utf-8"))
    postos = json.loads((OUT / "postos_por_upg_latest.json").read_text(encoding="utf-8"))
    hier = json.loads((OUT / "hierarquia_rs_latest.json").read_text(encoding="utf-8"))
    fozes = json.loads((OUT / "subbacias_e_fozes_latest.json").read_text(encoding="utf-8"))

    g040 = shape(next(f for f in bacias["features"] if f["properties"]["codigo"] == "G040")["geometry"])
    if not g040.is_valid:
        g040 = g040.buffer(0)
    upg_polys, upg_props = [], []
    for f in ugs["features"]:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        upg_polys.append(g)
        upg_props.append(f["properties"])
    tree = STRtree(upg_polys)

    def assign_upg(lon: float, lat: float) -> str | None:
        pt = Point(lon, lat)
        if not g040.buffer(0.03).covers(pt):
            return None
        for i in tree.query(pt):
            if upg_polys[int(i)].covers(pt) or upg_polys[int(i)].intersects(pt.buffer(0.008)):
                return upg_props[int(i)].get("sub_bacia")
        if g040.buffer(0.03).covers(pt):
            i = min(range(len(upg_polys)), key=lambda j: upg_polys[j].distance(pt))
            return upg_props[i].get("sub_bacia")
        return None

    print("1/4 ANA pluviometricas 28* RS...")
    ana_plu = ana_inventario(
        codEstDE="2800000",
        codEstATE="2899999",
        tpEst="2",
        nmEstado="Rio Grande do Sul",
    )
    print(" ", len(ana_plu))

    print("2/4 INMET RS automaticas...")
    inmet = http_json("https://apitempo.inmet.gov.br/estacoes/T")
    inmet_rs = [d for d in inmet if (d.get("SG_ESTADO") or "") == "RS"]
    print(" ", len(inmet_rs))

    rain_in: list[dict[str, Any]] = []
    rain_near: list[dict[str, Any]] = []

    for r in ana_plu:
        lat, lon = fnum(r.get("Latitude")), fnum(r.get("Longitude"))
        if lat is None or lon is None:
            continue
        upg = assign_upg(lon, lat)
        item = {
            "codigo": r.get("Codigo"),
            "nome": r.get("Nome"),
            "rede": "ANA",
            "tipo": "pluviometrica",
            "lat": lat,
            "lon": lon,
            "altitude_m": fnum(r.get("Altitude")),
            "situacao": r.get("Operando"),
            "telemetrica": r.get("Telemetrica"),
            "upg": upg,
            "in_previne_rain": r.get("Codigo") in PREVINE_RAIN
            or str(int(r.get("Codigo") or 0)) in PREVINE_RAIN,
            "previne_papel": None,
        }
        code_norm = str(int(item["codigo"])) if str(item["codigo"]).isdigit() else item["codigo"]
        if code_norm in PREVINE_RAIN:
            item["in_previne_rain"] = True
            item["previne_papel"] = PREVINE_RAIN[code_norm]["papel"]
        if upg:
            rain_in.append(item)
        elif g040.buffer(0.15).covers(Point(lon, lat)):
            item["note"] = "fora_g040_mas_proximo"
            rain_near.append(item)

    for d in inmet_rs:
        lat, lon = fnum(d.get("VL_LATITUDE")), fnum(d.get("VL_LONGITUDE"))
        if lat is None or lon is None:
            continue
        code = d.get("CD_ESTACAO")
        upg = assign_upg(lon, lat)
        item = {
            "codigo": code,
            "nome": d.get("DC_NOME"),
            "rede": "INMET",
            "tipo": d.get("TP_ESTACAO") or "Automatica",
            "lat": lat,
            "lon": lon,
            "altitude_m": fnum(d.get("VL_ALTITUDE")),
            "situacao": d.get("CD_SITUACAO"),
            "telemetrica": "1",
            "upg": upg,
            "in_previne_rain": code in PREVINE_RAIN,
            "previne_papel": (PREVINE_RAIN.get(code) or {}).get("papel"),
            "inicio_operacao": d.get("DT_INICIO_OPERACAO"),
            "fim_operacao": d.get("DT_FIM_OPERACAO"),
        }
        if upg:
            rain_in.append(item)
        elif g040.buffer(0.15).covers(Point(lon, lat)):
            item["note"] = "fora_g040_mas_proximo"
            rain_near.append(item)

    # CEMADEN seed
    cem = PREVINE_RAIN["432040401A"]
    upg = assign_upg(cem["lon"], cem["lat"])
    rain_in.append(
        {
            "codigo": "432040401A",
            "nome": cem["nome"],
            "rede": "CEMADEN",
            "tipo": "pluviometrica",
            "lat": cem["lat"],
            "lon": cem["lon"],
            "upg": upg,
            "in_previne_rain": True,
            "previne_papel": cem["papel"],
            "note": "coordenada aproximada do municipio; inventario CEMADEN estadual nao baixado",
        }
    )

    # Flu stations that PREVINE also uses as rain columns
    for code in ("86472600", "86472000"):
        match = next((s for s in postos["stations_inside_g040"] if s["codigo"] == code), None)
        if match:
            rain_in.append(
                {
                    "codigo": code,
                    "nome": match.get("nome"),
                    "rede": "ANA",
                    "tipo": "fluviometrica_com_sensor_chuva",
                    "lat": match.get("lat"),
                    "lon": match.get("lon"),
                    "upg": match.get("upg"),
                    "in_previne_rain": True,
                    "previne_papel": PREVINE_RAIN[code]["papel"],
                    "bho6_family": match.get("bho6_family"),
                }
            )

    # dedupe by codigo keeping previne flag
    by_code: dict[str, dict[str, Any]] = {}
    for s in rain_in:
        c = str(s["codigo"])
        prev = by_code.get(c)
        if prev is None or (s.get("in_previne_rain") and not prev.get("in_previne_rain")):
            by_code[c] = s
    rain_in = sorted(by_code.values(), key=lambda s: (s.get("upg") or "", s.get("rede") or "", str(s["codigo"])))

    by_upg: dict[str, list] = defaultdict(list)
    by_rede: dict[str, int] = defaultdict(int)
    for s in rain_in:
        by_upg[s.get("upg") or "sem_upg"].append(
            {
                "codigo": s["codigo"],
                "nome": s.get("nome"),
                "rede": s.get("rede"),
                "tipo": s.get("tipo"),
                "in_previne_rain": s.get("in_previne_rain"),
                "situacao": s.get("situacao"),
            }
        )
        by_rede[s.get("rede") or "?"] += 1

    previne_rain_upgs = sorted(
        {s.get("upg") for s in rain_in if s.get("in_previne_rain") and s.get("upg")}
    )
    upgs_no_previne_rain = sorted(set(UPG_FAMILY_HINT) - set(previne_rain_upgs))

    pluvio_report = {
        "schema_version": "estudo_pluviometria_g040_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "completar inventario de chuva dentro de G040; nao e HEC",
        "method": {
            "ana_plu": "HidroInventario tpEst=2, codigos 2800000-2899999, RS, filtro poligono G040",
            "inmet": "apitempo.inmet.gov.br/estacoes/T filtrado SG_ESTADO=RS e G040",
            "cemaden": "apenas seed operacional PREVINE (432040401A); catalogo estadual nao baixado",
        },
        "counts": {
            "ana_plu_rs_fetched": len(ana_plu),
            "inmet_rs_fetched": len(inmet_rs),
            "rain_stations_inside_g040": len(rain_in),
            "by_rede": dict(by_rede),
            "previne_rain_seeds_inside": sum(1 for s in rain_in if s.get("in_previne_rain")),
            "near_but_outside": len(rain_near),
        },
        "coverage": {
            "by_upg_counts": {k: len(v) for k, v in sorted(by_upg.items())},
            "previne_rain_upgs": previne_rain_upgs,
            "upgs_without_previne_rain_seed": upgs_no_previne_rain,
        },
        "by_upg": {k: v for k, v in sorted(by_upg.items())},
        "stations": rain_in,
        "near_outside_g040": rain_near[:30],
        "reading": {
            "previne_rain_cluster": (
                "A chuva operacional PREVINE concentra-se em Carreiro/Prata/Médio "
                "(ANA 28*, flu-chuva Antas/STZ, INMET A894, CEMADEN Serafina). "
                f"UPGs sem seed de chuva PREVINE: {', '.join(upgs_no_previne_rain)}."
            ),
            "ana_plu_available": (
                "Ha centenas de pluviometricas ANA 28* no RS; dentro de G040 o inventario "
                "mostra cobertura bem maior que o seed operacional."
            ),
            "inmet_pane": (
                "A894 Serafina Correa pode constar como Pane no INMET — ausencia != zero."
            ),
        },
        "artifacts": {
            "json": "pluviometria_g040_latest.json",
            "geojson": "pluviometria_g040.geojson",
        },
    }
    (OUT / "pluviometria_g040_latest.json").write_text(
        json.dumps(pluvio_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "pluviometria_g040.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                        "properties": {
                            k: s.get(k)
                            for k in (
                                "codigo",
                                "nome",
                                "rede",
                                "tipo",
                                "upg",
                                "in_previne_rain",
                                "situacao",
                                "previne_papel",
                            )
                        },
                    }
                    for s in rain_in
                    if s.get("lon") is not None
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print("3/4 building scope decision brief...")
    decision = build_decision(postos, pluvio_report, fozes, hier)
    (OUT / "recorte_modelo_latest.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_decision_html(decision, postos, pluvio_report)
    merge_estudo(pluvio_report, decision)
    print(
        json.dumps(
            {
                "ok": True,
                "rain_inside": pluvio_report["counts"]["rain_stations_inside_g040"],
                "by_rede": pluvio_report["counts"]["by_rede"],
                "by_upg": pluvio_report["coverage"]["by_upg_counts"],
                "previne_rain_upgs": previne_rain_upgs,
                "decision_options": [o["id"] for o in decision["options"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_decision(postos: dict, pluvio: dict, fozes: dict, hier: dict) -> dict[str, Any]:
    upg_counts = {k: len(v) for k, v in postos.get("by_upg", {}).items()}
    fam_counts = {k: len(v) for k, v in postos.get("by_bho6_family", {}).items()}
    foz_pos = {
        j["family_code"]: {
            "label": j["label"],
            "position": j["position_vs_controls"],
            "delta_vs_mucum_km2": j["delta_vs_mucum_km2"],
        }
        for j in fozes.get("fozes_principais", [])
    }
    return {
        "schema_version": "estudo_recorte_modelo_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "briefing para Juliana escolher o recorte ANTES de qualquer HEC",
        "status": "aguardando_decisao",
        "discipline_rule": "Nao calibrar HEC nem inventar topologia ate o recorte estar escolhido.",
        "facts_locked": {
            "g040_km2": 26430,
            "mucum_nested_km2": 15965.207,
            "postos_ana_g040": postos["counts"]["inside_g040"],
            "postos_por_upg": upg_counts,
            "postos_por_familia_bho6": {
                k: fam_counts[k] for k in ("786", "7868", "7866", "7864", "7862") if k in fam_counts
            },
            "fozes": foz_pos,
            "previne_flu_seeds_upgs": list(
                (postos.get("coverage_gaps") or {}).get("previne_seeds_by_upg", {}).keys()
            ),
            "previne_rain_upgs": pluvio["coverage"]["previne_rain_upgs"],
            "rain_stations_g040": pluvio["counts"]["rain_stations_inside_g040"],
        },
        "options": [
            {
                "id": "A_corredor_mucum",
                "name": "Corredor ate Muçum",
                "area_km2_approx": 15965,
                "includes_upgs": ["Alto Taquari-Antas", "Médio Taquari-Antas", "Prata", "Carreiro"],
                "excludes_upgs": ["Guaporé", "Forqueta", "Baixo Taquari-Antas"],
                "sees_guapore_forqueta": False,
                "aligns_with_current_previne": True,
                "pros": [
                    "Casa com postos RNA/operacionais ja usados (Antas, STZ, Mucum, Prata, Carreiro).",
                    "Menor dominio: menos chuvas/parametros para calibrar depois.",
                    "Fozes de Guapore/Forqueta ficam a jusante — nao entram no balanco Ate Mucum.",
                ],
                "cons": [
                    "NAO e a bacia Taquari-Antas (G040). Nao chamar de 'modelo da bacia'.",
                    "Ignora ~10 mil km2 oficiais e as UPG Guapore/Forqueta/Baixo.",
                    "Nao representa inundacoes do Baixo Taquari (Encantado, Lajeado, Estrela, etc.).",
                ],
                "hec_implication_later": "HEC, se vier, seria do CORREDOR — nao de G040.",
            },
            {
                "id": "B_g040_completa",
                "name": "Bacia oficial G040 completa",
                "area_km2_approx": 26430,
                "includes_upgs": list(UPG_FAMILY_HINT.keys()),
                "excludes_upgs": [],
                "sees_guapore_forqueta": True,
                "aligns_with_current_previne": False,
                "pros": [
                    "Fala a verdade do nome: Taquari-Antas oficial (~26,4 mil km2).",
                    "Inclui Guapore (28 postos ANA) e Forqueta (20) ja inventariados.",
                    "Permite estudar Baixo Taquari ate o Jacui.",
                ],
                "cons": [
                    "Exige rede de chuva/nivel muito alem dos seeds PREVINE atuais.",
                    "Dominio maior: calibracao (quando houver) sera bem mais pesada.",
                    "RNA atual de Mucum/STZ nao cobre sozinha esse dominio.",
                ],
                "hec_implication_later": "HEC teria de abrir UPG/familias 7864/7862/Baixo — nao so Carreiro.",
            },
            {
                "id": "C_hibrido_explicito",
                "name": "Hibrido explicito (corredor + UPG escolhidas)",
                "area_km2_approx": None,
                "includes_upgs": "a definir com Juliana",
                "excludes_upgs": "a definir",
                "sees_guapore_forqueta": "talvez",
                "aligns_with_current_previne": "parcial",
                "pros": [
                    "Permite priorizar, por exemplo, Carreiro+Prata+tronco sem fingir G040 inteira.",
                    "Pode incluir Guapore se o alvo for Encantado/Muçum jusante — com rotulo honesto.",
                ],
                "cons": [
                    "Precisa nomear exatamente o que entra e o que fica de fora.",
                    "Risco de voltar a misturar 'bacia' com 'corredor' se o rotulo for frouxo.",
                ],
                "hec_implication_later": "HEC so depois da lista fechada de UPG/familias.",
            },
        ],
        "recommendation_engine_not_human": (
            "O agente NAO escolhe o recorte. Juliana decide. "
            "Enquanto status=aguardando_decisao, nao abrir HEC novo."
        ),
        "artifacts": {
            "json": "recorte_modelo_latest.json",
            "html": "recorte_modelo.html",
            "pluvio": "pluviometria_g040_latest.json",
        },
    }


def write_decision_html(decision: dict, postos: dict, pluvio: dict) -> None:
    facts = decision["facts_locked"]
    opt_html = []
    for o in decision["options"]:
        pros = "".join(f"<li>{p}</li>" for p in o["pros"])
        cons = "".join(f"<li>{c}</li>" for c in o["cons"])
        area = o["area_km2_approx"]
        area_txt = f"{area:,} km²" if isinstance(area, (int, float)) else "a definir"
        opt_html.append(
            f"""
<section class="opt">
  <h2>{o['id']}. {o['name']}</h2>
  <p><strong>Area:</strong> {area_txt} · <strong>Alinha ao PREVINE atual:</strong> {o['aligns_with_current_previne']}</p>
  <p><strong>Ve Guapore/Forqueta:</strong> {o['sees_guapore_forqueta']}</p>
  <div class="cols">
    <div><h3>Pros</h3><ul>{pros}</ul></div>
    <div><h3>Contras</h3><ul>{cons}</ul></div>
  </div>
  <p class="muted"><strong>Se um dia houver HEC:</strong> {o['hec_implication_later']}</p>
</section>"""
        )
    upg_rows = "".join(
        f"<tr><td>{u}</td><td class='num'>{n}</td>"
        f"<td class='num'>{pluvio['coverage']['by_upg_counts'].get(u, 0)}</td></tr>"
        for u, n in sorted(facts["postos_por_upg"].items())
    )
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Recorte de modelo · decisao pendente</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1100px; margin:auto; padding:28px 16px 64px; }}
    header, section, .opt {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,42px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:24px; color:var(--accent); }}
    .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th,td {{ padding:8px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }} td.num {{ text-align:right; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid,.cols {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · decisao de recorte</div>
    <h1>Antes do HEC: qual pedaco modelar?</h1>
    <p class="muted">{decision['generated_at_utc']} · status: {decision['status']}</p>
    <div class="notice bad"><strong>Regra:</strong> {decision['discipline_rule']}</div>
  </header>

  <section>
    <div class="grid">
      <div class="stat"><strong>26.430</strong><span>km² G040 oficial</span></div>
      <div class="stat"><strong>15.965</strong><span>km² corredor Mucum</span></div>
      <div class="stat"><strong>{facts['postos_ana_g040']}</strong><span>postos ANA em G040</span></div>
      <div class="stat"><strong>{facts['rain_stations_g040']}</strong><span>postos de chuva em G040</span></div>
    </div>
  </section>

  <section>
    <h2>Fatos ja fechados</h2>
    <ul>
      <li>Guapore entra no tronco <strong>depois</strong> de Mucum (~+2.495 km²).</li>
      <li>Forqueta entra ainda mais a jusante (~+6.540 km²).</li>
      <li>PREVINE flu seeds: {', '.join(facts['previne_flu_seeds_upgs']) or '—'}.</li>
      <li>PREVINE chuva seeds: {', '.join(facts['previne_rain_upgs']) or '—'}.</li>
      <li>So G040 escorre para o Taquari-Antas; vizinhas nao sao afluentes.</li>
    </ul>
    <table>
      <thead><tr><th>UPG</th><th class="num">postos ANA</th><th class="num">chuva inventariada</th></tr></thead>
      <tbody>{upg_rows}</tbody>
    </table>
  </section>

  {''.join(opt_html)}

  <section>
    <h2>O que o agente nao faz agora</h2>
    <div class="notice">{decision['recommendation_engine_not_human']}</div>
    <p>Responda com <strong>A</strong>, <strong>B</strong> ou <strong>C</strong> (e, se C, quais UPG). Ate la, o estudo para neste briefing.</p>
    <p><a href="pluviometria_g040_latest.json">pluviometria JSON</a> ·
       <a href="postos_por_upg_latest.json">postos JSON</a> ·
       <a href="mapa_hierarquia_rs.html">hierarquia</a> ·
       <a href="index.html">estudo-base</a></p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "recorte_modelo.html").write_text(html, encoding="utf-8")


def merge_estudo(pluvio: dict, decision: dict) -> None:
    path = OUT / "estudo_bacia_latest.json"
    if not path.exists():
        return
    prev = json.loads(path.read_text(encoding="utf-8"))
    prev["pluviometria_g040"] = {
        "status": "inventariado",
        "counts": pluvio["counts"],
        "coverage": pluvio["coverage"],
        "reading": pluvio["reading"],
        "artifacts": pluvio["artifacts"],
        "updated_at_utc": pluvio["generated_at_utc"],
    }
    prev["recorte_modelo"] = {
        "status": decision["status"],
        "options": [o["id"] for o in decision["options"]],
        "artifacts": decision["artifacts"],
        "updated_at_utc": decision["generated_at_utc"],
    }
    known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
    for item in [
        f"Pluviometria G040: {pluvio['counts']['rain_stations_inside_g040']} postos de chuva (ANA/INMET/CEMADEN seed).",
        f"Chuva PREVINE cobre UPG: {', '.join(pluvio['coverage']['previne_rain_upgs'])}.",
        "Briefing de recorte publicado; decisao humana pendente (A/B/C).",
    ]:
        if item not in known:
            known.append(item)
    prev["next_study_steps_only"] = [
        "Juliana escolhe o recorte: A corredor Mucum, B G040 completa, ou C hibrido (listar UPG).",
        "So depois discutir estrutura HEC alinhada ao recorte escolhido.",
    ]
    # refresh index links
    idx_path = OUT / "index.html"
    if idx_path.exists():
        idx = idx_path.read_text(encoding="utf-8")
        if "recorte_modelo.html" not in idx:
            idx = idx.replace(
                '<a href="mapa_postos_upg.html">postos por UPG</a></p>',
                '<a href="mapa_postos_upg.html">postos por UPG</a> ·\n'
                '       <a href="recorte_modelo.html">recorte de modelo (decisao)</a></p>',
            )
        if "Recorte de modelo" not in idx:
            block = """  <section>
    <h2>Recorte de modelo (decisao pendente)</h2>
    <div class="notice bad"><strong>Parar antes do HEC:</strong> escolher A corredor Mucum, B G040 completa, ou C hibrido.
    Fatos e opcoes em <a href="recorte_modelo.html">recorte_modelo.html</a>.</div>
  </section>

"""
            idx = idx.replace(
                "  <section>\n    <h2>Proximos passos",
                block + "  <section>\n    <h2>Proximos passos",
            )
        from html import escape
        import re

        steps = "".join(f"<li>{escape(x)}</li>" for x in prev["next_study_steps_only"])
        idx = re.sub(
            r"(<h2>Proximos passos de ESTUDO \(sem HEC\)</h2>\s*<ul>)(.*?)(</ul>)",
            r"\1" + steps + r"\3",
            idx,
            flags=re.S,
        )
        idx_path.write_text(idx, encoding="utf-8")
    path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = OUT / "README.md"
    if readme.exists():
        txt = readme.read_text(encoding="utf-8")
        if "recorte_modelo" not in txt:
            txt += "\n## Decisao de recorte\n\nLeia `recorte_modelo.html` antes de qualquer HEC.\n"
            txt = txt.replace(
                "python scripts/build_estudo_postos_por_upg.py\n```",
                "python scripts/build_estudo_postos_por_upg.py\n"
                "python scripts/build_estudo_pluvio_recorte.py\n```",
            )
            readme.write_text(txt)


if __name__ == "__main__":
    main()
