#!/usr/bin/env python3
"""Build a multi-basin HEC structure for Taquari-Antas (not one bucket).

Opens every major tributary system >= 500 km2 upstream of Antas, keeps Carreiro
as its own basin between Antas and Santa Tereza, plus STZ residual and Muçum
increment. Structure only + areas; rainfall/execution live in the end-to-end runner.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UNDERSTANDING = ROOT / "assets" / "data" / "bacia_taquari_antas" / "bacia_understanding_latest.json"
CARREIRO = ROOT / "assets" / "data" / "hec_hms_carreiro_split" / "carreiro_split_structure_latest.json"
OUT = ROOT / "assets" / "data" / "hec_hms_multi_bacia"
MIN_UPSTREAM_KM2 = 500.0


def main() -> None:
    understanding = json.loads(UNDERSTANDING.read_text(encoding="utf-8"))
    carreiro_pack = json.loads(CARREIRO.read_text(encoding="utf-8"))
    controls = understanding["controls"]
    antas = float(controls["86472000"]["area_km2"])
    stz = float(controls["86472600"]["area_km2"])
    mucum = float(controls["86510000"]["area_km2"])
    incr_stz = float(controls["incremental_km2"]["antas_to_stz"])
    incr_mucum = float(controls["incremental_km2"]["stz_to_mucum"])

    upstream = [
        j
        for j in understanding["major_tributary_joins"]
        if j["position_vs_controls"] == "upstream_or_at_antas"
        and float(j["join_area_km2"]) >= MIN_UPSTREAM_KM2
    ]
    upstream.sort(key=lambda j: float(j.get("mainstem_area_at_join_km2") or 0))

    carreiro = next(
        j
        for j in understanding["major_tributary_joins"]
        if j.get("bho6_cocursodag") == "7866" or "Carreiro" in j.get("label", "")
    )
    carreiro_area = float(carreiro["join_area_km2"])
    stz_residual = round(incr_stz - carreiro_area, 3)

    opened_upstream_area = round(sum(float(j["join_area_km2"]) for j in upstream), 3)
    antas_residual = round(antas - opened_upstream_area, 3)
    if antas_residual <= 0:
        raise RuntimeError("Antas residual must stay positive")

    subbasins: list[dict[str, Any]] = []
    # Headwater residual of Antas (unnamed laterals + mainstem contribution)
    subbasins.append(
        {
            "id": "SB_ANTAS_RESIDUAL",
            "type": "subbasin",
            "area_km2": antas_residual,
            "joins_at": "J_ANTAS_86472000",
            "rainfall_candidate_stations": ["86472000"],
            "notes": "Residual a montante de Antas depois de abrir sistemas >=500 km2",
        }
    )
    for j in upstream:
        code = j["bho6_cocursodag"]
        sid = f"SB_UP_{code}"
        subbasins.append(
            {
                "id": sid,
                "type": "subbasin",
                "area_km2": float(j["join_area_km2"]),
                "joins_at": "J_ANTAS_86472000",
                "bho6_cocursodag": code,
                "label": j["label"],
                "named_components": j.get("named_components_top", []),
                "mainstem_area_at_join_km2": j.get("mainstem_area_at_join_km2"),
                "confluence_lonlat": j.get("confluence_lonlat"),
                "rainfall_candidate_stations": ["86472000", "86125500", "86125130"],
                "notes": "Sistema afluente aberto a montante do posto Antas",
            }
        )

    subbasins.extend(
        [
            {
                "id": "SB_CARREIRO_7866",
                "type": "subbasin",
                "area_km2": carreiro_area,
                "joins_at": "J_CARREIRO_CONFLUENCE",
                "bho6_cocursodag": "7866",
                "label": carreiro["label"],
                "rainfall_candidate_stations": ["86507000"],
                "notes": "Bacia do Carreiro entre Antas e Santa Tereza",
            },
            {
                "id": "SB_STZ_RESIDUAL",
                "type": "subbasin",
                "area_km2": stz_residual,
                "joins_at": "J_SANTA_TEREZA_86472600",
                "rainfall_candidate_stations": ["86472600"],
                "notes": "Laterais Antas-STZ fora do Carreiro",
            },
            {
                "id": "SB_INC_MUCUM",
                "type": "subbasin",
                "area_km2": incr_mucum,
                "joins_at": "J_MUCUM_86510000",
                "rainfall_candidate_stations": ["86510000"],
                "notes": "Incremento curto STZ-Muçum",
            },
        ]
    )

    elements = list(subbasins) + [
        {"id": "J_ANTAS_86472000", "type": "junction", "station": "86472600".replace("86472600", "86472000"), "status": "control_antas"},
        {
            "id": "R_ANTAS_TO_CARREIRO",
            "type": "reach",
            "from": "J_ANTAS_86472000",
            "to": "J_CARREIRO_CONFLUENCE",
            "status": "routing_pending_channel_evidence",
        },
        {
            "id": "J_CARREIRO_CONFLUENCE",
            "type": "junction",
            "status": "geometric_confluence",
        },
        {
            "id": "R_CARREIRO_TO_STZ",
            "type": "reach",
            "from": "J_CARREIRO_CONFLUENCE",
            "to": "J_SANTA_TEREZA_86472600",
            "status": "routing_pending_channel_evidence",
        },
        {
            "id": "J_SANTA_TEREZA_86472600",
            "type": "junction",
            "station": "86472600",
            "accumulated_area_km2": stz,
            "status": "control_no_reconciled_flow",
        },
        {
            "id": "R_STZ_TO_MUCUM",
            "type": "reach",
            "from": "J_SANTA_TEREZA_86472600",
            "to": "J_MUCUM_86510000",
            "status": "routing_pending_channel_evidence",
        },
        {
            "id": "J_MUCUM_86510000",
            "type": "junction",
            "station": "86510000",
            "accumulated_area_km2": mucum,
            "status": "response_target",
        },
    ]

    sum_sb = round(sum(s["area_km2"] for s in subbasins), 3)
    report = {
        "schema_version": "hec_hms_multi_bacia_structure_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "estrutura multi-bacia Taquari-Antas; nao e calibracao nem alerta",
        "status": "structure_proposed_not_calibrated",
        "principle": "A bacia e composta por varias bacias. O modelo precisa refletir isso.",
        "threshold_km2_for_upstream_split": MIN_UPSTREAM_KM2,
        "area_check": {
            "antas_nested_km2": antas,
            "opened_upstream_systems_km2": opened_upstream_area,
            "antas_residual_km2": antas_residual,
            "carreiro_km2": carreiro_area,
            "stz_residual_km2": stz_residual,
            "mucum_increment_km2": incr_mucum,
            "sum_subbasin_areas_km2": sum_sb,
            "mucum_nested_km2": mucum,
            "area_closure_ok": abs(sum_sb - mucum) < 0.05,
        },
        "counts": {
            "subbasins": len(subbasins),
            "upstream_systems_opened": len(upstream),
            "reaches": 3,
            "junctions": 4,
        },
        "compared_to_lumped": {
            "old": "1 sub-bacia de 16000 km2",
            "carreiro_only_split": "4 sub-bacias",
            "now": f"{len(subbasins)} sub-bacias",
        },
        "subbasins": subbasins,
        "elements": elements,
        "connectivity": [
            "SB_ANTAS_RESIDUAL + SB_UP_* -> J_ANTAS_86472000",
            "J_ANTAS -> R_ANTAS_TO_CARREIRO -> J_CARREIRO (+ SB_CARREIRO)",
            "J_CARREIRO -> R_CARREIRO_TO_STZ -> J_STZ (+ SB_STZ_RESIDUAL)",
            "J_STZ -> R_STZ_TO_MUCUM -> J_MUCUM (+ SB_INC_MUCUM)",
        ],
        "opened_upstream_labels": [
            {"id": f"SB_UP_{j['bho6_cocursodag']}", "label": j["label"], "area_km2": j["join_area_km2"]}
            for j in upstream
        ],
        "sources": {
            "understanding": str(UNDERSTANDING.relative_to(ROOT)),
            "carreiro_split": str(CARREIRO.relative_to(ROOT)),
        },
        "gates_before_promotion": [
            "Chuva propria (ou proxy explicita) por sub-bacia",
            "Nao promover parametros comuns com NSE medio negativo",
            "Validacao em Santa Tereza ainda bloqueada sem vazao reconciliada",
            "Routing fisico ainda pendente",
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "multi_bacia_structure_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # simple html
    rows = "".join(
        f"<tr><td><code>{s['id']}</code></td><td>{s.get('label') or s.get('notes','')}</td>"
        f"<td class='num'>{s['area_km2']:,.1f}</td><td>{s['joins_at']}</td></tr>"
        for s in subbasins
    )
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-bacia Taquari-Antas</title>
<style>
body{{margin:0;font:16px/1.5 Source Sans 3,Segoe UI,sans-serif;color:#143246;background:linear-gradient(160deg,#eef8f8,#fff8f1)}}
main{{max-width:1100px;margin:auto;padding:28px 18px 60px}}
header,section{{background:#fff;border:1px solid #d7e4e8;border-radius:18px;padding:22px;margin-bottom:14px;box-shadow:0 10px 26px #14324612}}
h1{{margin:0 0 8px;font:700 clamp(28px,4vw,42px)/1.08 Fraunces,Georgia,serif}}
.eyebrow{{color:#c45c16;font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}
.notice{{border-left:5px solid #9a5b12;background:#fff7e8;color:#6d4810;padding:12px 14px;border-radius:10px}}
.ok{{border-left-color:#0b7a68;background:#eefaf6;color:#0d5c50}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.stat{{border:1px solid #d7e4e8;border-radius:12px;padding:12px;background:#f7fcfc}}
.stat strong{{display:block;font-size:26px;color:#0a6f9c}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:9px 8px;border-bottom:1px solid #d7e4e8;text-align:left;vertical-align:top}}
th{{background:#eef6f7}} td.num{{text-align:right}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<header>
<div class="eyebrow">Varias bacias · estrutura</div>
<h1>Taquari-Antas nao e uma bacia so</h1>
<p>Gerado em {report['generated_at_utc']}</p>
<div class="notice"><strong>Principio:</strong> {report['principle']}</div>
</header>
<section>
<div class="grid">
<div class="stat"><strong>{report['counts']['subbasins']}</strong><span>sub-bacias</span></div>
<div class="stat"><strong>{report['counts']['upstream_systems_opened']}</strong><span>sistemas abertos a montante de Antas (>=500 km2)</span></div>
<div class="stat"><strong>{opened_upstream_area:,.0f}</strong><span>km2 tirados do balde Antas</span></div>
<div class="stat"><strong>{carreiro_area:,.0f}</strong><span>km2 Carreiro separado</span></div>
</div>
<div class="notice ok" style="margin-top:12px">Fechamento de area: soma das sub-bacias = {sum_sb:,.3f} km2 vs Muçum {mucum:,.3f} km2 · {'OK' if report['area_check']['area_closure_ok'] else 'FALHOU'}</div>
</section>
<section>
<h2>Sub-bacias</h2>
<table><thead><tr><th>ID</th><th>Nome / nota</th><th class="num">Area (km2)</th><th>Entra em</th></tr></thead>
<tbody>{rows}</tbody></table>
</section>
<section>
<h2>Artefatos</h2>
<ul>
<li><a href="multi_bacia_structure_latest.json">multi_bacia_structure_latest.json</a></li>
<li><a href="../hec_hms_carreiro_split/end_to_end.html">rodada Carreiro-split</a></li>
<li><a href="../bacia_taquari_antas/index.html">compreensao da bacia</a></li>
</ul>
</section>
</main></body></html>
"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / "README.md").write_text(
        """# Multi-bacia Taquari-Antas

A bacia e composta por varias bacias. Este pacote abre:

- sistemas afluentes >= 500 km2 a montante de Antas
- Carreiro entre Antas e Santa Tereza
- residual STZ e incremento Muçum

Nao e calibracao. Nao e alerta.

```bash
python scripts/build_hec_hms_multi_bacia_structure.py
```
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "subbasins": report["counts"]["subbasins"],
                "upstream_opened": report["counts"]["upstream_systems_opened"],
                "sum_km2": sum_sb,
                "closure_ok": report["area_check"]["area_closure_ok"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
