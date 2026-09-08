#!/usr/bin/env python3
"""Build the next HEC-HMS structure: split Carreiro out of SB_INC_STZ.

This is a structural design package derived from the BHO6 basin understanding.
It does NOT calibrate parameters, invent rainfall, or claim a finished model.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UNDERSTANDING = ROOT / "assets" / "data" / "bacia_taquari_antas" / "bacia_understanding_latest.json"
NETWORK_AUDIT = (
    ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_audit_latest.json"
)
OUT = ROOT / "assets" / "data" / "hec_hms_carreiro_split"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_structure(understanding: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    controls = understanding["controls"]
    antas = float(controls["86472000"]["area_km2"])
    stz = float(controls["86472600"]["area_km2"])
    mucum = float(controls["86510000"]["area_km2"])
    incr_stz = float(controls["incremental_km2"]["antas_to_stz"])
    incr_mucum = float(controls["incremental_km2"]["stz_to_mucum"])

    carreiro = next(
        j
        for j in understanding["major_tributary_joins"]
        if j.get("bho6_cocursodag") == "7866" or "Carreiro" in j.get("label", "")
    )
    marrecao = next(
        (
            j
            for j in understanding["major_tributary_joins"]
            if "Marrecao" in j.get("label", "")
        ),
        None,
    )
    carreiro_area = float(carreiro["join_area_km2"])
    residual = round(incr_stz - carreiro_area, 3)
    if residual <= 0:
        raise RuntimeError("residual STZ area must be positive after Carreiro split")

    elements = [
        {
            "id": "SB_ANTAS_86472000",
            "type": "subbasin",
            "area_km2": antas,
            "outlet": "J_ANTAS_86472000",
            "rainfall_candidate_stations": ["86472000"],
            "notes": "Bacia a montante de Linha José Júlio (Rio das Antas). Ainda agrega sistemas ≥500 km² a montante.",
        },
        {
            "id": "J_ANTAS_86472000",
            "type": "junction",
            "station": "86472000",
            "status": "observed_control_level_available_flow_not_required_here",
        },
        {
            "id": "R_ANTAS_TO_CARREIRO",
            "type": "reach",
            "from": "J_ANTAS_86472000",
            "to": "J_CARREIRO_CONFLUENCE",
            "status": "routing_parameters_blocked_until_channel_evidence",
            "geometry_hint": "mainstem segment between Antas gauge and Carreiro confluence (~mainstem area 15485 km²)",
        },
        {
            "id": "SB_CARREIRO_7866",
            "type": "subbasin",
            "area_km2": carreiro_area,
            "outlet": "J_CARREIRO_CONFLUENCE",
            "bho6_cocursodag": "7866",
            "join_fid": carreiro["join_fid"],
            "confluence_lonlat": carreiro.get("confluence_lonlat"),
            "named_components": carreiro.get("named_components_top", []),
            "rainfall_candidate_stations": ["86507000"],
            "level_station": {
                "code": "86507000",
                "name": "PCH Cotiporã Jusante",
                "river": "Rio Carreiro",
                "role": "âncora de nível já usada na RNA; chuva/vazão ainda precisam de auditoria explícita",
            },
            "notes": "Entrada dominante do incremento Antas→Santa Tereza (~90%).",
        },
        {
            "id": "J_CARREIRO_CONFLUENCE",
            "type": "junction",
            "status": "geometric_confluence_no_observed_flow_target",
            "inflows": ["R_ANTAS_TO_CARREIRO", "SB_CARREIRO_7866"],
        },
        {
            "id": "R_CARREIRO_TO_STZ",
            "type": "reach",
            "from": "J_CARREIRO_CONFLUENCE",
            "to": "J_SANTA_TEREZA_86472600",
            "status": "routing_parameters_blocked_until_channel_evidence",
        },
        {
            "id": "SB_STZ_RESIDUAL",
            "type": "subbasin",
            "area_km2": residual,
            "outlet": "J_SANTA_TEREZA_86472600",
            "rainfall_candidate_stations": ["86472600"],
            "includes_named_joins": (
                [
                    {
                        "label": marrecao["label"],
                        "join_area_km2": marrecao["join_area_km2"],
                        "bho6_cocursodag": marrecao["bho6_cocursodag"],
                    }
                ]
                if marrecao
                else []
            ),
            "notes": "Residual lateral Antas→STZ depois de retirar o Carreiro. Contém Marrecao (~222 km²) e laterais menores.",
        },
        {
            "id": "J_SANTA_TEREZA_86472600",
            "type": "junction",
            "station": "86472600",
            "status": "control_point_no_reconciled_flow_target",
            "inflows": ["R_CARREIRO_TO_STZ", "SB_STZ_RESIDUAL"],
            "accumulated_area_km2": stz,
        },
        {
            "id": "R_STZ_TO_MUCUM",
            "type": "reach",
            "from": "J_SANTA_TEREZA_86472600",
            "to": "J_MUCUM_86510000",
            "source_path": "86472600_to_86510000",
            "length_km_bho6": audit["topology"]["paths"]["86472600_to_86510000"]["length_km"],
            "status": "routing_parameters_blocked_until_channel_evidence",
        },
        {
            "id": "SB_INC_MUCUM",
            "type": "subbasin",
            "area_km2": incr_mucum,
            "outlet": "J_MUCUM_86510000",
            "rainfall_candidate_stations": ["86510000"],
            "notes": "Incremento curto STZ→Muçum; sem afluente ≥100 km² no clip.",
        },
        {
            "id": "J_MUCUM_86510000",
            "type": "junction",
            "station": "86510000",
            "status": "calibration_target_candidate",
            "inflows": ["R_STZ_TO_MUCUM", "SB_INC_MUCUM"],
            "accumulated_area_km2": mucum,
        },
    ]

    previous = {
        "subbasins": 3,
        "reaches": 2,
        "ids": [
            "SB_ANTAS_86472000",
            "SB_INC_STZ (undifferentiated)",
            "SB_INC_MUCUM",
            "R_ANTAS_SANTA_TEREZA",
            "R_SANTA_TEREZA_MUCUM",
        ],
    }
    now = {
        "subbasins": 4,
        "reaches": 3,
        "junctions": 4,
        "ids": [e["id"] for e in elements],
    }

    return {
        "schema_version": "hec_hms_carreiro_split_structure_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "estrutura HEC-HMS com Carreiro separado; não é calibração nem alerta",
        "status": "structure_proposed_not_calibrated",
        "sources": {
            "bacia_understanding": {
                "path": str(UNDERSTANDING.relative_to(ROOT)),
                "sha256": sha256(UNDERSTANDING),
            },
            "network_audit": {
                "path": str(NETWORK_AUDIT.relative_to(ROOT)),
                "sha256": sha256(NETWORK_AUDIT),
            },
        },
        "area_check": {
            "antas_km2": antas,
            "carreiro_km2": carreiro_area,
            "stz_residual_km2": residual,
            "stz_increment_km2": incr_stz,
            "carreiro_fraction_of_stz_increment": round(carreiro_area / incr_stz, 4),
            "antas_plus_carreiro_km2": round(antas + carreiro_area, 3),
            "mainstem_area_at_carreiro_join_km2": carreiro.get("mainstem_area_at_join_km2"),
            "mucum_increment_km2": incr_mucum,
            "sum_subbasin_areas_km2": round(antas + carreiro_area + residual + incr_mucum, 3),
            "mucum_nested_area_km2": mucum,
            "area_closure_ok": abs((antas + carreiro_area + residual + incr_mucum) - mucum) < 0.02,
        },
        "compared_to_previous_skeleton": {
            "previous": previous,
            "proposed": now,
            "what_changed": [
                "SB_INC_STZ foi partido em SB_CARREIRO_7866 + SB_STZ_RESIDUAL",
                "Novo junction geométrico na confluência do Carreiro",
                "Reach Antas→STZ partido em Antas→Carreiro e Carreiro→STZ",
            ],
        },
        "elements": elements,
        "connectivity": [
            "SB_ANTAS_86472000 -> J_ANTAS_86472000 -> R_ANTAS_TO_CARREIRO -> J_CARREIRO_CONFLUENCE",
            "SB_CARREIRO_7866 -> J_CARREIRO_CONFLUENCE",
            "J_CARREIRO_CONFLUENCE -> R_CARREIRO_TO_STZ -> J_SANTA_TEREZA_86472600",
            "SB_STZ_RESIDUAL -> J_SANTA_TEREZA_86472600",
            "J_SANTA_TEREZA_86472600 -> R_STZ_TO_MUCUM -> J_MUCUM_86510000",
            "SB_INC_MUCUM -> J_MUCUM_86510000",
        ],
        "gates_before_calibration": [
            "Auditar se 86507000 tem série de chuva horária utilizável nos eventos; senão buscar pluviômetro no sistema Carreiro.",
            "Não reusar a chuva de 86472000 em SB_CARREIRO sem declarar proxy explícita.",
            "Manter Santa Tereza sem target de vazão até curva-chave/série reconciliada.",
            "Não promover parâmetros comuns enquanto a estrutura nova não rodar em ≥2 eventos com chuva auditada.",
            "Routing continua bloqueado sem evidência de calha.",
        ],
        "explicitly_not_done": [
            "Nenhuma busca de parâmetros",
            "Nenhum projeto .hms executado nesta proposta",
            "Nenhuma métrica NSE inventada para a estrutura nova",
        ],
    }


def write_basin_text(structure: dict[str, Any], path: Path) -> None:
    """Human/HEC-readable element list (not a runnable HMS binary project)."""
    lines = [
        "Basin: Taquari_Antas_CarreiroSplit",
        "Last Modified Date: " + structure["generated_at_utc"],
        "Description: Structural proposal only. Not calibrated.",
        "",
    ]
    for el in structure["elements"]:
        lines.append(f"{el['type'].title()}: {el['id']}")
        if el["type"] == "subbasin":
            lines.append(f"     Area: {el['area_km2']}")
            lines.append(f"     Downstream: {el['outlet']}")
            rains = ", ".join(el.get("rainfall_candidate_stations") or [])
            lines.append(f"     Rainfall Candidates: {rains}")
        elif el["type"] == "reach":
            lines.append(f"     From: {el['from']}")
            lines.append(f"     To: {el['to']}")
            lines.append(f"     Status: {el['status']}")
        elif el["type"] == "junction":
            if el.get("station"):
                lines.append(f"     Station: {el['station']}")
            lines.append(f"     Status: {el['status']}")
        lines.append("End:")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(structure: dict[str, Any], path: Path) -> None:
    a = structure["area_check"]
    elems = {e["id"]: e for e in structure["elements"]}
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HEC-HMS · estrutura com Carreiro separado</title>
  <style>
    :root {{ --ink:#143246; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --good:#0b7a68; --car:#c45c16; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif;
      background:radial-gradient(900px 500px at 80% -10%,#ffe8d2 0%,transparent 50%), linear-gradient(165deg,#eef8f8,#fff); }}
    main {{ max-width:1100px; margin:auto; padding:28px 18px 60px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:22px; margin-bottom:14px; box-shadow:0 10px 26px #14324612; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,42px)/1.08 "Fraunces",Georgia,serif; }}
    h2 {{ margin:0 0 10px; font-size:1.2rem; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .meta {{ color:var(--muted); font-size:14px; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .ok {{ border-left-color:var(--good); background:#eefaf6; color:#0d5c50; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:24px; color:var(--accent); }}
    .stat.car strong {{ color:var(--car); }}
    .stat span {{ color:var(--muted); font-size:12px; }}
    svg {{ width:100%; height:auto; display:block; background:linear-gradient(180deg,#f5fbfd,#eef5f8); border-radius:14px; border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ text-align:left; padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ background:#eef6f7; color:#355468; }}
    td.num {{ text-align:right; white-space:nowrap; }}
    ul {{ margin:8px 0 0; padding-left:20px; color:#27495a; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid {{ grid-template-columns:1fr 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Próxima estrutura HEC · não calibrada</div>
    <h1>Carreiro sai do balde genérico</h1>
    <p class="meta">Gerado em {structure['generated_at_utc']} · status: {structure['status']}</p>
    <div class="notice"><strong>Isto não é calibração.</strong> É o desenho estrutural que o modelo precisa ter antes de buscar parâmetros de novo.</div>
  </header>

  <section>
    <div class="grid">
      <div class="stat"><strong>{a['antas_km2']:,.0f}</strong><span>km² · SB_ANTAS</span></div>
      <div class="stat car"><strong>{a['carreiro_km2']:,.0f}</strong><span>km² · SB_CARREIRO ({a['carreiro_fraction_of_stz_increment']*100:.0f}% do incr. STZ)</span></div>
      <div class="stat"><strong>{a['stz_residual_km2']:,.0f}</strong><span>km² · SB_STZ_RESIDUAL</span></div>
      <div class="stat"><strong>{a['mucum_increment_km2']:,.0f}</strong><span>km² · SB_INC_MUCUM</span></div>
    </div>
    <p class="meta" style="margin-top:12px">Fechamento de área: soma das sub-bacias = {a['sum_subbasin_areas_km2']:,.3f} km² vs Muçum aninhado {a['mucum_nested_area_km2']:,.3f} km² · {'OK' if a['area_closure_ok'] else 'FALHOU'}</p>
  </section>

  <section>
    <h2>Diagrama</h2>
    <svg viewBox="0 0 920 420" role="img" aria-label="Diagrama HEC com Carreiro separado">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="#7a93a0"/>
        </marker>
      </defs>
      <!-- reaches -->
      <line x1="150" y1="90" x2="330" y2="160" stroke="#8fb8c4" stroke-width="10" marker-end="url(#arrow)"/>
      <line x1="430" y1="180" x2="560" y2="250" stroke="#8fb8c4" stroke-width="10" marker-end="url(#arrow)"/>
      <line x1="650" y1="270" x2="780" y2="340" stroke="#8fb8c4" stroke-width="10" marker-end="url(#arrow)"/>
      <!-- carreiro inflow -->
      <line x1="300" y1="40" x2="370" y2="150" stroke="#c45c16" stroke-width="8" marker-end="url(#arrow)"/>
      <!-- residual inflow -->
      <line x1="520" y1="120" x2="590" y2="240" stroke="#0b7a68" stroke-width="7" marker-end="url(#arrow)"/>
      <!-- mucum residual -->
      <line x1="760" y1="220" x2="810" y2="320" stroke="#0a6f9c" stroke-width="6" marker-end="url(#arrow)"/>

      <rect x="40" y="55" width="150" height="70" rx="12" fill="#8764c4" />
      <text x="115" y="85" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">SB_ANTAS</text>
      <text x="115" y="105" text-anchor="middle" fill="#f2e9ff" font-size="12">{a['antas_km2']:,.0f} km²</text>

      <rect x="220" y="8" width="180" height="70" rx="12" fill="#c45c16" />
      <text x="310" y="38" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">SB_CARREIRO</text>
      <text x="310" y="58" text-anchor="middle" fill="#ffe8d5" font-size="12">{a['carreiro_km2']:,.0f} km² · NOVO</text>

      <circle cx="390" cy="175" r="28" fill="#fff" stroke="#c45c16" stroke-width="4"/>
      <text x="390" y="171" text-anchor="middle" font-size="11" font-weight="800">J</text>
      <text x="390" y="185" text-anchor="middle" font-size="10">Carreiro</text>

      <rect x="470" y="55" width="170" height="70" rx="12" fill="#0b7a68" />
      <text x="555" y="85" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">SB_STZ_RESID</text>
      <text x="555" y="105" text-anchor="middle" fill="#d7fff4" font-size="12">{a['stz_residual_km2']:,.0f} km²</text>

      <circle cx="620" cy="265" r="28" fill="#0b7a68" stroke="#fff" stroke-width="4"/>
      <text x="620" y="260" text-anchor="middle" fill="#fff" font-size="11" font-weight="800">STZ</text>
      <text x="620" y="275" text-anchor="middle" fill="#dffaf3" font-size="10">86472600</text>

      <rect x="700" y="150" width="150" height="60" rx="12" fill="#0a6f9c" />
      <text x="775" y="175" text-anchor="middle" fill="#fff" font-size="12" font-weight="800">SB_INC_MUCUM</text>
      <text x="775" y="193" text-anchor="middle" fill="#d8efff" font-size="12">{a['mucum_increment_km2']:,.0f} km²</text>

      <circle cx="830" cy="350" r="30" fill="#0a6f9c" stroke="#fff" stroke-width="4"/>
      <text x="830" y="345" text-anchor="middle" fill="#fff" font-size="11" font-weight="800">Muçum</text>
      <text x="830" y="360" text-anchor="middle" fill="#d8efff" font-size="10">86510000</text>

      <text x="230" y="140" fill="#5d7380" font-size="11">R_ANTAS→CARREIRO</text>
      <text x="470" y="230" fill="#5d7380" font-size="11">R_CARREIRO→STZ</text>
      <text x="680" y="320" fill="#5d7380" font-size="11">R_STZ→MUCUM</text>
    </svg>
  </section>

  <section>
    <h2>Antes → depois</h2>
    <div class="notice ok">Antes: 3 sub-bacias / 2 reaches, com <code>SB_INC_STZ</code> genérico de {a['stz_increment_km2']:,.0f} km². Agora: 4 sub-bacias / 3 reaches, com Carreiro explícito.</div>
    <div style="overflow:auto;margin-top:12px">
      <table>
        <thead><tr><th>Elemento</th><th>Tipo</th><th class="num">Área (km²)</th><th>Chuva candidata</th><th>Status</th></tr></thead>
        <tbody>
          <tr><td><code>SB_ANTAS_86472000</code></td><td>subbasin</td><td class="num">{elems['SB_ANTAS_86472000']['area_km2']:,.1f}</td><td>86472000</td><td>ainda agregado a montante</td></tr>
          <tr><td><code>SB_CARREIRO_7866</code></td><td>subbasin</td><td class="num">{elems['SB_CARREIRO_7866']['area_km2']:,.1f}</td><td>86507000 (auditar)</td><td><strong>NOVO</strong></td></tr>
          <tr><td><code>SB_STZ_RESIDUAL</code></td><td>subbasin</td><td class="num">{elems['SB_STZ_RESIDUAL']['area_km2']:,.1f}</td><td>86472600</td><td>Marrecao + laterais</td></tr>
          <tr><td><code>SB_INC_MUCUM</code></td><td>subbasin</td><td class="num">{elems['SB_INC_MUCUM']['area_km2']:,.1f}</td><td>86510000</td><td>igual ao esqueleto anterior</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Gates antes de calibrar</h2>
    <ul>
      {''.join(f'<li>{g}</li>' for g in structure['gates_before_calibration'])}
    </ul>
    <p class="meta" style="margin-top:12px">Artefatos: <a href="carreiro_split_structure_latest.json">JSON</a> · <a href="Taquari_Antas_CarreiroSplit.basin.txt">lista de elementos</a> · <a href="../bacia_taquari_antas/index.html">compreensão da bacia</a></p>
  </section>
</main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    understanding = load(UNDERSTANDING)
    audit = load(NETWORK_AUDIT)
    structure = build_structure(understanding, audit)

    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "carreiro_split_structure_latest.json"
    json_path.write_text(json.dumps(structure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_basin_text(structure, OUT / "Taquari_Antas_CarreiroSplit.basin.txt")
    write_html(structure, OUT / "index.html")
    (OUT / "README.md").write_text(
        """# HEC-HMS · split do Carreiro

Proposta estrutural: separar `SB_CARREIRO_7866` do antigo `SB_INC_STZ`.

- `index.html` — diagrama
- `carreiro_split_structure_latest.json` — schema auditável
- `Taquari_Antas_CarreiroSplit.basin.txt` — lista de elementos (não é projeto binário HMS)

**Não calibrado.** Não gera NSE. Não é alerta.

```bash
python scripts/build_hec_hms_carreiro_split_structure.py
```
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "carreiro_km2": structure["area_check"]["carreiro_km2"],
                "residual_km2": structure["area_check"]["stz_residual_km2"],
                "fraction": structure["area_check"]["carreiro_fraction_of_stz_increment"],
                "area_closure_ok": structure["area_check"]["area_closure_ok"],
                "subbasins": structure["compared_to_previous_skeleton"]["proposed"]["subbasins"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
