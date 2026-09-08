#!/usr/bin/env python3
"""Publish a source-backed STUDY of the Taquari-Antas basin.

This script deliberately does NOT build HEC structure, calibrate, or invent
subbasin parameters. It records what official sources say, what the local
PREVINE clip covers, and what remains unknown.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
NETWORK_AUDIT = (
    ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_audit_latest.json"
)
UNDERSTANDING = ROOT / "assets" / "data" / "bacia_taquari_antas" / "bacia_understanding_latest.json"


def main() -> None:
    network = json.loads(NETWORK_AUDIT.read_text(encoding="utf-8")) if NETWORK_AUDIT.exists() else {}
    understanding = (
        json.loads(UNDERSTANDING.read_text(encoding="utf-8")) if UNDERSTANDING.exists() else {}
    )

    nested = network.get("topology", {}).get("nested_catchment_area_km2_from_bho6", {})
    mucum_nested = nested.get("86510000")
    antas_nested = nested.get("86472000")
    stz_nested = nested.get("86472600")

    study = {
        "schema_version": "estudo_bacia_taquari_antas_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "estudo da bacia antes de qualquer modelo HEC; nao e calibracao nem alerta",
        "status": "estudo_em_andamento",
        "discipline_rule": "Nao subentender estrutura de modelo. Primeiro ler a bacia oficial; so depois discutir HEC.",
        "official_basin": {
            "name": "Bacia Hidrografica do Rio Taquari-Antas",
            "code_sema": "G040",
            "region": "Regiao Hidrografica do Guaiaba",
            "area_km2_sema": 26430,
            "area_km2_sgb_sace": 26372.76,
            "area_km2_wikipedia_compilation": 26491.82,
            "area_note": "Fontes oficiais/compiladas divergem em dezenas de km2; usar faixa ~26,3-26,5 mil km2 ate reconciliar shapefile SEMA com BHO6.",
            "outlet": "confluencia com o Rio Jacui (nao e Muçum)",
            "mainstem_naming": {
                "rule": "Chama-se Rio das Antas ate a foz do Rio Carreiro; depois Rio Taquari ate o Jacui",
                "sources": [
                    "https://pt.wikipedia.org/wiki/Bacia_do_rio_Taquari-Antas",
                    "SBRH 2013 - Plano de Bacia Taquari-Antas",
                ],
            },
            "sources": [
                {
                    "name": "SEMA-RS G040",
                    "url": "https://www.sema.rs.gov.br/g040-bh-taquari-antas",
                    "says": "area 26.430 km2; lista de municipios; plano de bacia e enquadramento",
                },
                {
                    "name": "SGB/SACE caracteristicas",
                    "url": "https://www.sgb.gov.br/sace/taquari_caracteristicas.php",
                    "says": "area 26.372,76 km2; afluentes principais listados; precipitacao 1400-1900 mm/ano",
                },
                {
                    "name": "Wikipedia / plano de bacia (compilacao)",
                    "url": "https://pt.wikipedia.org/wiki/Bacia_do_rio_Taquari-Antas",
                    "says": "7 UGs e 32 sub-bacias; principais cursos; geomorfologia",
                },
                {
                    "name": "UFRGS - inundacoes/enxurradas (tese)",
                    "url": "https://lume.ufrgs.br/bitstream/handle/10183/198553/001098788.pdf",
                    "says": "areas de drenagem citadas: Antas 12.964; Prata 3.775; Forqueta 2.845; Carreiro 2.565; Guapore 2.489 km2",
                },
            ],
        },
        "official_units_of_management": {
            "count_ug": 7,
            "count_subbasins": 32,
            "ugs": [
                {
                    "name": "Alto Taquari-Antas",
                    "subbasins": [
                        "Alto Rio das Antas",
                        "Rio Camisas",
                        "Rio Tainhas",
                        "Arroio Pinheiro Alto",
                        "Arroio Sao Tome/Bagual",
                        "Lajeado Grande",
                    ],
                },
                {
                    "name": "Medio Taquari-Antas",
                    "subbasins": [
                        "Arroio Marrecao",
                        "Rio Burati/Arroio Retiro",
                        "Arroio Biazus",
                        "Arroio Tega",
                        "Rio Sao Marcos",
                        "Arroio do Inferno",
                        "Rio Quebra dentes/Arroio Mulada",
                    ],
                },
                {
                    "name": "Prata",
                    "subbasins": ["Alto Rio Turvo", "Rio da Prata", "Baixo Rio Turvo"],
                },
                {
                    "name": "Carreiro",
                    "subbasins": ["Alto Rio Carreiro", "Medio Rio Carreiro", "Baixo Rio Carreiro"],
                },
                {
                    "name": "Guapore",
                    "subbasins": ["Alto Rio Guapore", "Medio Rio Guapore", "Baixo Rio Guapore"],
                },
                {
                    "name": "Forqueta",
                    "subbasins": ["Alto Rio Forqueta", "Rio Fao", "Rio Forqueta"],
                },
                {
                    "name": "Baixo Taquari-Antas",
                    "subbasins": [
                        "Arroio Jacare/Augusta",
                        "Arroio Seca",
                        "Arroio Boa Vista",
                        "Arroio Sampaio/Estrela",
                        "Arroio Castelhano",
                        "Rio Taquari-Mirim",
                        "Baixo Taquari",
                    ],
                },
            ],
            "source": "https://pt.wikipedia.org/wiki/Bacia_do_rio_Taquari-Antas (compilacao do plano/enquadramento)",
        },
        "main_tributaries_cited": [
            {"name": "Rio das Antas", "role": "tronco superior", "area_km2_cited": 12964, "area_source": "UFRGS tese inundacoes"},
            {"name": "Rio da Prata", "role": "afluente", "area_km2_cited": 3775, "area_source": "UFRGS tese inundacoes"},
            {"name": "Rio Forqueta", "role": "afluente", "area_km2_cited": 2845, "area_source": "UFRGS tese inundacoes"},
            {"name": "Rio Carreiro", "role": "afluente; marca mudanca de nome Antas->Taquari", "area_km2_cited": 2565, "area_source": "UFRGS tese inundacoes"},
            {"name": "Rio Guapore", "role": "afluente", "area_km2_cited": 2489, "area_source": "UFRGS tese inundacoes"},
            {"name": "Rio Tainhas", "role": "afluente de montante", "area_km2_cited": None, "area_source": None},
            {"name": "Camisas / Lajeado Grande / Quebra-Dentes / Taquari-Mirim", "role": "afluentes citados por SGB/SACE", "area_km2_cited": None, "area_source": "SGB SACE"},
        ],
        "critical_distinction": {
            "title": "Bacia oficial != trecho monitorado pelo PREVINE em Muçum/Santa Tereza",
            "full_basin_km2": 26430,
            "mucum_nested_bho6_km2": mucum_nested,
            "santa_tereza_nested_bho6_km2": stz_nested,
            "antas_nested_bho6_km2": antas_nested,
            "finding": (
                "O posto de Muçum (86510000) drena cerca de 16 mil km2 no BHO6 local. "
                "Isso NAO e a bacia Taquari-Antas inteira (~26,4 mil km2). "
                "Guapore e Forqueta NAO aparecem no recorte BHO6 a montante de Muçum: "
                "entram no tronco a jusante de Muçum. Portanto, qualquer HEC 'da bacia' "
                "feito so com Antas/STZ/Muçum esta estudando um CORREDOR, nao a bacia toda."
            ),
            "evidence_local": {
                "bho6_clip_path": "assets/data/hec_hms_integrated_taquari_antas/bho6_taquari_antas_network.geojson",
                "guapore_forqueta_in_mucum_upstream_clip": False,
            },
        },
        "previne_current_focus": {
            "stations": ["86472000 Antas", "86472600 Santa Tereza", "86510000 Muçum"],
            "what_it_is": "corredor hidrologico Antas -> Santa Tereza -> Muçum",
            "what_it_is_not": "modelo da bacia Taquari-Antas completa com 7 UGs / 32 sub-bacias",
        },
        "mistakes_to_stop_making": [
            "Tratar 16.000 km2 de Muçum como se fosse a bacia Taquari-Antas.",
            "Calibrar HEC agregado/eventwise e falar 'modelo da bacia'.",
            "Abrir so Carreiro e achar que ja representou as varias bacias (faltam Prata, Guapore, Forqueta, Tainhas, etc.).",
            "Inventar topologia HEC antes de fechar o mapa oficial das 32 sub-bacias e a posicao de cada foz.",
        ],
        "known_vs_unknown": {
            "known": [
                "Area oficial da bacia ~26,4 mil km2 (SEMA G040).",
                "Existem 7 UGs e 32 sub-bacias no plano/enquadramento.",
                "O nome muda de Antas para Taquari na foz do Carreiro.",
                "Muçum e Santa Tereza sao controles do tronco, nao o exutorio da bacia.",
                "No clip BHO6 a montante de Muçum, Guapore e Forqueta nao entram.",
                "Areas citadas (tese UFRGS) para Prata/Carreiro/Guapore/Forqueta/Antas.",
            ],
            "unknown_or_unreconciled": [
                "Shapefile oficial das 32 sub-bacias com areas reconciliadas no repo.",
                "Posicao exata (km / area acumulada BHO6) da foz de Guapore e Forqueta no tronco.",
                "Inventario unico de postos fluviometricos/pluviometricos por UG.",
                "Curva-chave reconciliada em Santa Tereza.",
                "Qual recorte o PREVINE quer modelar: bacia toda, corredor ate Muçum, ou outro.",
            ],
        },
        "next_study_steps_only": [
            "Baixar/anexar shapefiles SEMA das sub-bacias/enquadramento e calcular areas.",
            "Mapear foz de cada UG no tronco com BHO6 (incluindo jusante de Muçum).",
            "Montar inventario de postos por UG sem forcar uso em HEC.",
            "So depois escolher o recorte de modelo com a Juliana (bacia toda vs corredor).",
        ],
        "local_artifacts_related": {
            "iede_boundary": "assets/data/vulnerabilidade/bacia.geojson",
            "bho6_mucum_upstream_clip": "assets/data/hec_hms_integrated_taquari_antas/",
            "premature_hec_packages": [
                "assets/data/hec_hms_carreiro_split/",
                "assets/data/hec_hms_multi_bacia/",
                "assets/data/mucum_eventwise_replay_calibrated/",
            ],
            "note_on_premature_packages": "Podem ser uteis como experimentos de corredor, mas nao substituem o estudo da bacia oficial.",
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "estudo_bacia_latest.json").write_text(
        json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    ugs_html = "".join(
        f"<section class='ug'><h3>{ug['name']}</h3><ul>"
        + "".join(f"<li>{s}</li>" for s in ug["subbasins"])
        + "</ul></section>"
        for ug in study["official_units_of_management"]["ugs"]
    )
    trib_rows = "".join(
        "<tr>"
        f"<td>{t['name']}</td><td>{t['role']}</td>"
        f"<td class='num'>{'' if t['area_km2_cited'] is None else f'{t['area_km2_cited']:,}'}</td>"
        f"<td>{t.get('area_source') or '—'}</td>"
        "</tr>"
        for t in study["main_tributaries_cited"]
    )
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Estudo da bacia Taquari-Antas</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif;
      background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1100px; margin:auto; padding:28px 18px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:22px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,44px)/1.08 "Fraunces",Georgia,serif; }}
    h2 {{ margin:0 0 10px; font-size:1.25rem; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:28px; color:var(--accent); }}
    .ugs {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
    .ug {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f8fcfc; }}
    .ug h3 {{ margin:0 0 8px; font-size:1rem; }}
    .ug ul {{ margin:0; padding-left:18px; color:#27495a; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ text-align:left; padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ background:#eef6f7; }}
    td.num {{ text-align:right; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid,.ugs {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · antes do HEC</div>
    <h1>A Taquari-Antas e feita de varias bacias</h1>
    <p>Gerado em {study['generated_at_utc']}</p>
    <div class="notice"><strong>Regra:</strong> {study['discipline_rule']}</div>
  </header>

  <section>
    <div class="grid">
      <div class="stat"><strong>26.430</strong><span>km² oficiais SEMA (G040)</span></div>
      <div class="stat"><strong>7</strong><span>unidades de gestao</span></div>
      <div class="stat"><strong>32</strong><span>sub-bacias oficiais</span></div>
    </div>
  </section>

  <section>
    <h2>Distincao critica</h2>
    <div class="notice bad"><strong>Nao confundir:</strong> {study['critical_distinction']['finding']}</div>
    <p>Muçum BHO6 aninhado: <strong>{mucum_nested}</strong> km² · Santa Tereza: <strong>{stz_nested}</strong> km² · Antas: <strong>{antas_nested}</strong> km².</p>
    <p>Exutorio da bacia oficial: <strong>Rio Jacui</strong>, nao Muçum.</p>
  </section>

  <section>
    <h2>7 UGs e 32 sub-bacias</h2>
    <div class="ugs">{ugs_html}</div>
    <p class="meta" style="color:#5d7380;font-size:13px">Fonte compilada do plano/enquadramento via pagina da bacia. Shapefile SEMA ainda precisa ser anexado ao repo para areas por sub-bacia.</p>
  </section>

  <section>
    <h2>Afluentes principais (areas citadas)</h2>
    <table>
      <thead><tr><th>Curso</th><th>Papel</th><th class="num">Area (km²)</th><th>Fonte da area</th></tr></thead>
      <tbody>{trib_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>O que ja sabemos / o que nao</h2>
    <h3>Sabemos</h3>
    <ul>{''.join(f'<li>{x}</li>' for x in study['known_vs_unknown']['known'])}</ul>
    <h3>Ainda nao fechado</h3>
    <ul>{''.join(f'<li>{x}</li>' for x in study['known_vs_unknown']['unknown_or_unreconciled'])}</ul>
  </section>

  <section>
    <h2>Proximos passos de ESTUDO (sem HEC)</h2>
    <ul>{''.join(f'<li>{x}</li>' for x in study['next_study_steps_only'])}</ul>
    <p><a href="estudo_bacia_latest.json">JSON auditavel</a> · fontes: <a href="https://www.sema.rs.gov.br/g040-bh-taquari-antas">SEMA G040</a> · <a href="https://www.sgb.gov.br/sace/taquari_caracteristicas.php">SGB SACE</a></p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / "README.md").write_text(
        """# Estudo da bacia Taquari-Antas

Este pacote e **estudo**, nao modelo.

Leia `index.html` / `estudo_bacia_latest.json` antes de qualquer HEC.

## Regra

Nao subentender a estrutura. A bacia oficial (SEMA G040) tem ~26,4 mil km2,
7 UGs e 32 sub-bacias. O corredor Ate Muçum (~16 mil km2) nao e a bacia toda.

```bash
python scripts/build_estudo_bacia_taquari_antas.py
```
""",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "out": str(OUT.relative_to(ROOT)), "full_km2": 26430, "mucum_km2": mucum_nested}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
