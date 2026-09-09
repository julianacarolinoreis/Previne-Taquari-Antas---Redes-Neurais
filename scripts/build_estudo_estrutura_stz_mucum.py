#!/usr/bin/env python3
"""Study-level HEC/RNA structure for STZ and Muçum target models.

Derived from frozen forcings + Carreiro-split areas + Prata (7868) named.
Does NOT calibrate parameters, invent rainfall, or claim a finished HMS project.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"

# Nested BHO6 / prior study closures (km²)
ANTAS = 12918.656
STZ = 15775.186
MUCUM = 15965.207
PRATA = 3775.99  # BHO6 7868 join area from multi_bacia / understanding
CARREIRO = 2564.19
STZ_RESIDUAL = 292.34
MUCUM_INC = 190.021
ANTAS_RESIDUAL = round(ANTAS - PRATA, 3)  # trunk residual after naming Prata


def node(nid, ntype, **kwargs):
    return {"id": nid, "type": ntype, **kwargs}


def build_stz_elements():
    # rain_stations = contrato HEC de evento (telemetria ANA no pacote raw_ana).
    # rain_stations_rna_aspirational = pluvios do contrato RNA/forçantes (ex. 2851072),
    # ainda sem série de evento no twin Linux.
    return [
        node(
            "SB_PRATA_7868",
            "subbasin",
            area_km2=PRATA,
            outlet="J_ANTAS_86472000",
            bho6_cocursodag="7868",
            level_station="86125500",
            rain_stations=["86472000", "86507000"],
            rain_stations_rna_aspirational=["2851072"],
            notes=(
                "Sistema Prata/Turvo-Humatã nomeado para casar com forçante 86125500. "
                "HEC twin eventwise usa telemetria ANA 86472000 (lumping com Antas residual). "
                "2851072 fica aspiracional até haver série de evento."
            ),
        ),
        node(
            "SB_ANTAS_RESIDUAL",
            "subbasin",
            area_km2=ANTAS_RESIDUAL,
            outlet="J_ANTAS_86472000",
            rain_stations=["86472000"],
            notes="Tronco Antas a montante de 86472000 depois de separar Prata. Pode abrir UP_* depois se necessário.",
        ),
        node(
            "J_ANTAS_86472000",
            "junction",
            station="86472000",
            role="controle_observado_nivel",
            nested_area_km2=ANTAS,
            notes="Controle do tronco Antas; forçante de nível nos dois modelos.",
        ),
        {
            "id": "R_ANTAS_TO_CARREIRO",
            "type": "reach",
            "from": "J_ANTAS_86472000",
            "to": "J_CARREIRO_CONFLUENCE",
            "status": "routing_blocked_until_channel_evidence",
        },
        node(
            "SB_CARREIRO_7866",
            "subbasin",
            area_km2=CARREIRO,
            outlet="J_CARREIRO_CONFLUENCE",
            bho6_cocursodag="7866",
            level_station="86507000",
            rain_stations=["86507000", "86472000"],
            rain_stations_rna_aspirational=["2851072", "A894", "432040401A"],
            notes=(
                "~90% do incremento Antas→STZ. HEC twin: preferir 86507000, com fallback "
                "de magnitude para 86472000 se a preferida estiver completa mas ~seca."
            ),
        ),
        node(
            "J_CARREIRO_CONFLUENCE",
            "junction",
            role="confluencia_geometrica",
            notes="Aqui o nome do rio passa de Antas para Taquari (estudo).",
        ),
        {
            "id": "R_CARREIRO_TO_STZ",
            "type": "reach",
            "from": "J_CARREIRO_CONFLUENCE",
            "to": "J_STZ_86472600",
            "status": "routing_blocked_until_channel_evidence",
        },
        node(
            "SB_STZ_RESIDUAL",
            "subbasin",
            area_km2=STZ_RESIDUAL,
            outlet="J_STZ_86472600",
            rain_stations=["86472600", "86472000"],
            notes="Residual local (ex.: Marrecão) entre Carreiro e STZ.",
        ),
        node(
            "J_STZ_86472600",
            "junction",
            station="86472600",
            role="ALVO_PREDICAO_modelo_STZ",
            nested_area_km2=STZ,
            rain_stations=["86472600"],
            notes="Predictand do modelo Santa Tereza.",
        ),
    ]


def build_mucum_elements():
    els = build_stz_elements()
    # Retarget STZ junction role for Muçum model
    for e in els:
        if e["id"] == "J_STZ_86472600":
            e["role"] = "forcante_nivel_montante_critico"
            e["notes"] = (
                "No modelo Muçum, STZ NÃO é o alvo — é a forçante crítica de montante "
                "(quase todo o domínio passa por aqui)."
            )
    els.extend(
        [
            {
                "id": "R_STZ_TO_MUCUM",
                "type": "reach",
                "from": "J_STZ_86472600",
                "to": "J_MUCUM_86510000",
                "status": "routing_blocked_until_channel_evidence",
            },
            node(
                "SB_INC_MUCUM",
                "subbasin",
                area_km2=MUCUM_INC,
                outlet="J_MUCUM_86510000",
                rain_stations=["86510000", "86472600", "86472000"],
                notes="Incremento curto STZ→Muçum (~190 km²). Não inclui Guaporé.",
            ),
            node(
                "J_MUCUM_86510000",
                "junction",
                station="86510000",
                role="ALVO_PREDICAO_modelo_Mucum",
                nested_area_km2=MUCUM,
                notes="Predictand do modelo Muçum. Corredor — não G040.",
            ),
        ]
    )
    return els


def area_check(elements, nested_target):
    sub = [e for e in elements if e["type"] == "subbasin"]
    total = round(sum(e["area_km2"] for e in sub), 3)
    return {
        "sum_subbasin_km2": total,
        "nested_target_km2": nested_target,
        "closure_ok": abs(total - nested_target) < 0.5,
        "subbasin_ids": [e["id"] for e in sub],
    }


def rna_hint(model_key: str) -> dict:
    if model_key == "santa_tereza":
        return {
            "predictand": "nivel_86472600",
            "features_nivel": ["86472000", "86507000", "86125500"],
            "features_chuva": ["86472000", "86472600", "2851072"],
            "optional": ["86448000", "A894", "432040401A"],
            "note": "Mesma topologia pode alimentar RNA sem abrir HMS; não misturar alvo Muçum.",
        }
    return {
        "predictand": "nivel_86510000",
        "features_nivel": ["86472600", "86472000", "86507000", "86125500"],
        "features_chuva": ["86472000", "86472600", "2851072"],
        "optional": ["86448000", "A894", "432040401A"],
        "note": "STZ (86472600) é feature crítica de montante, não predictand.",
    }


def build_payload() -> dict:
    stz_els = build_stz_elements()
    muc_els = build_mucum_elements()
    return {
        "schema_version": "estudo_estrutura_stz_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "estrutura candidata por modelo-alvo (HEC ou RNA); topologia e areas, nao parametros finais",
        "status": "estrutura_com_hec_twin_v1",
        "discipline_rule": (
            "Dois projetos/logicas separados. Nunca rotular como 'modelo da bacia G040'. "
            "rain_stations = contrato HEC de evento (ANA raw_ana). "
            "rain_stations_rna_aspirational = pluvios do trilho RNA/forçantes. "
            "HEC twin v1: busca eventwise Muçum + common-search; STZ Q ainda bloqueado."
        ),
        "parent_artifacts": {
            "forcantes": "forcantes_stz_mucum_latest.json",
            "dominios": "dois_modelos_stz_mucum_latest.json",
            "carreiro_split_ref": "assets/data/hec_hms_carreiro_split/carreiro_split_structure_latest.json",
            "prata_area_ref": "assets/data/hec_hms_multi_bacia/multi_bacia_structure_latest.json",
        },
        "excluded_from_both": {
            "upgs": ["Guaporé", "Forqueta", "Baixo Taquari-Antas"],
            "families": ["7864", "7862"],
            "elements_never": ["SB_GUAPORE", "SB_FORQUETA", "SB_BAIXO"],
        },
        "design_choices": [
            "Prata (7868) nomeado como SB_PRATA_7868 — casa com forçante 86125500.",
            "Carreiro (7866) separado — ~90% do incremento Antas→STZ.",
            "Modelo STZ para em J_STZ; nao inclui SB_INC_MUCUM.",
            "Modelo Muçum reusa esqueleto STZ e acrescenta R_STZ_TO_MUCUM + SB_INC_MUCUM.",
            "Ainda nao abrir os 3 UP_* extras a montante de Antas (multi_bacia) — opcional depois.",
            "Contrato de chuva HEC de evento separado do aspiracional RNA (2851072/A894).",
            "No twin, Prata+Antas residual sao runoff-lumped (mesma lamina ANA) para nao dobrar Initial+Constant.",
        ],
        "models": {
            "santa_tereza": {
                "label": "modelo STZ",
                "target": "86472600",
                "nested_area_km2": STZ,
                "counts": {
                    "subbasins": 4,
                    "reaches": 2,
                    "junctions": 3,
                },
                "elements": stz_els,
                "area_check": area_check(stz_els, STZ),
                "topology_ascii": (
                    "SB_PRATA_7868 ──┐\n"
                    "SB_ANTAS_RESIDUAL ┼→ J_ANTAS_86472000 → R_ANTAS_TO_CARREIRO → J_CARREIRO\n"
                    "SB_CARREIRO_7866 ─────────────────────→ J_CARREIRO\n"
                    "                                      → R_CARREIRO_TO_STZ → J_STZ_86472600 ★ ALVO\n"
                    "SB_STZ_RESIDUAL ──────────────────────→ J_STZ"
                ),
                "rna_mapping": rna_hint("santa_tereza"),
                "not_in_model": ["SB_INC_MUCUM", "J_MUCUM_86510000", "Guaporé/Forqueta/Baixo"],
            },
            "mucum": {
                "label": "modelo Muçum",
                "target": "86510000",
                "nested_area_km2": MUCUM,
                "counts": {
                    "subbasins": 5,
                    "reaches": 3,
                    "junctions": 4,
                },
                "elements": muc_els,
                "area_check": area_check(muc_els, MUCUM),
                "topology_ascii": (
                    "[mesmo esqueleto do modelo STZ até J_STZ_86472600]  ← forçante crítica\n"
                    "  → R_STZ_TO_MUCUM → J_MUCUM_86510000 ★ ALVO\n"
                    "SB_INC_MUCUM (~190) ─────→ J_MUCUM"
                ),
                "rna_mapping": rna_hint("mucum"),
                "not_in_model": ["Guaporé/Forqueta/Baixo", "tratar Muçum como se visse +2495 km² Guaporé"],
            },
        },
        "blocked_until_series_check": [
            "buracos chuva_86472600 em series longas",
            "A894 pane (ausencia != zero) no trilho RNA",
            "parametros de routing sem evidencia de canal",
            "STZ Q: curva-chave Nivel→Vazao reconciliada",
            "telemetria de evento para pluvios aspiracionais 2851072",
        ],
        "next_steps": [
            "Validar series das forçantes congeladas (nivel + chuva) por alvo.",
            "Escolher caminho: montar .basin HEC-HMS por alvo OU treinar/confirmar RNA com o mesmo grafo de features.",
            "So depois: calibracao — e apenas no modelo escolhido, nunca 'da bacia'.",
        ],
        "artifacts": {
            "json": "estrutura_stz_mucum_latest.json",
            "html": "estrutura_stz_mucum.html",
        },
    }


def write_html(payload: dict) -> None:
    stz = payload["models"]["santa_tereza"]
    muc = payload["models"]["mucum"]

    def rows(els):
        out = []
        for e in els:
            extra = e.get("station") or e.get("level_station") or e.get("area_km2") or ""
            if isinstance(extra, float):
                extra = f"{extra:,.2f} km²"
            out.append(
                "<tr>"
                f"<td>{html.escape(e['id'])}</td>"
                f"<td>{html.escape(e['type'])}</td>"
                f"<td>{html.escape(str(e.get('role') or e.get('outlet') or e.get('to') or '—'))}</td>"
                f"<td>{html.escape(str(extra))}</td>"
                f"<td>{html.escape(e.get('notes') or '')}</td>"
                "</tr>"
            )
        return "".join(out)

    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Estrutura candidata · STZ e Muçum</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --ok:#1b7a4a; --warn:#9a5b12; --bad:#a33b35; --accent:#0a6f9c; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1100px; margin:auto; padding:28px 16px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,40px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--ok); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; margin:10px 0; }}
    .ok {{ border-left-color:var(--ok); background:#eefaf3; color:#145c38; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
    pre {{ background:#0f1c24; color:#d7f5e8; padding:14px; border-radius:12px; overflow:auto; font:12px/1.45 ui-monospace,Menlo,monospace; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:7px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ background:#eef6f7; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · estrutura v1</div>
    <h1>Dois esqueletos — ainda sem calibração</h1>
    <p class="muted">{html.escape(payload['generated_at_utc'])} · {html.escape(payload['status'])}</p>
    <div class="notice ok"><strong>Disciplina:</strong> {html.escape(payload['discipline_rule'])}</div>
    <div class="notice bad"><strong>Fora:</strong> Guaporé, Forqueta, Baixo. Não rotular como bacia G040.</div>
  </header>

  <div class="grid">
    <section>
      <h2>Modelo Santa Tereza · alvo {stz['target']}</h2>
      <p class="muted">~{stz['nested_area_km2']:,.0f} km² · {stz['counts']['subbasins']} subbacias · fechamento {"OK" if stz['area_check']['closure_ok'] else "FALHOU"}</p>
      <pre>{html.escape(stz['topology_ascii'])}</pre>
      <p class="muted">RNA: predictand {html.escape(stz['rna_mapping']['predictand'])}; níveis {", ".join(stz['rna_mapping']['features_nivel'])}</p>
    </section>
    <section>
      <h2>Modelo Muçum · alvo {muc['target']}</h2>
      <p class="muted">~{muc['nested_area_km2']:,.0f} km² · {muc['counts']['subbasins']} subbacias · fechamento {"OK" if muc['area_check']['closure_ok'] else "FALHOU"}</p>
      <pre>{html.escape(muc['topology_ascii'])}</pre>
      <p class="muted">RNA: predictand {html.escape(muc['rna_mapping']['predictand'])}; STZ vira feature crítica</p>
    </section>
  </div>

  <section>
    <h2>Elementos — Santa Tereza</h2>
    <table>
      <thead><tr><th>ID</th><th>Tipo</th><th>Papel / destino</th><th>Área / posto</th><th>Nota</th></tr></thead>
      <tbody>{rows(stz['elements'])}</tbody>
    </table>
  </section>

  <section>
    <h2>Elementos — Muçum (delta em relação ao STZ)</h2>
    <table>
      <thead><tr><th>ID</th><th>Tipo</th><th>Papel / destino</th><th>Área / posto</th><th>Nota</th></tr></thead>
      <tbody>{rows([e for e in muc['elements'] if e['id'] in ('J_STZ_86472600','R_STZ_TO_MUCUM','SB_INC_MUCUM','J_MUCUM_86510000')])}</tbody>
    </table>
    <p class="muted">O restante do grafo Muçum é idêntico ao STZ (Prata + Antas residual + Carreiro + residual STZ).</p>
  </section>

  <section>
    <h2>Escolhas de desenho</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['design_choices'])}</ul>
    <h2>Bloqueado até checar séries</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['blocked_until_series_check'])}</ul>
    <h2>Próximos</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['next_steps'])}</ul>
    <p>
      <a href="estrutura_stz_mucum_latest.json">JSON</a> ·
      <a href="forcantes_stz_mucum.html">forçantes</a> ·
      <a href="dois_modelos_stz_mucum.html">domínios</a> ·
      <a href="index.html">estudo-base</a>
    </p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "estrutura_stz_mucum.html").write_text(page, encoding="utf-8")


def merge(payload: dict) -> None:
    # Update master study JSON
    path = OUT / "estudo_bacia_latest.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["estrutura_stz_mucum"] = {
            "status": payload["status"],
            "artifacts": payload["artifacts"],
            "stz_subbasins": payload["models"]["santa_tereza"]["area_check"]["subbasin_ids"],
            "mucum_subbasins": payload["models"]["mucum"]["area_check"]["subbasin_ids"],
            "updated_at_utc": payload["generated_at_utc"],
        }
        known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
        for item in [
            "Estrutura candidata v1: modelo STZ (4 SB) e modelo Muçum (5 SB) com Prata+Carreiro nomeados.",
            "Modelo STZ para em J_STZ; modelo Muçum acrescenta incremento ~190 km².",
        ]:
            if item not in known:
                known.append(item)
        prev["next_study_steps_only"] = payload["next_steps"]
        path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Domains status
    dom_path = OUT / "dois_modelos_stz_mucum_latest.json"
    if dom_path.exists():
        domains = json.loads(dom_path.read_text(encoding="utf-8"))
        domains["status"] = "estrutura_proposta_aguardando_series_ou_caminho_hec_rna"
        domains["estrutura_artifact"] = payload["artifacts"]
        domains["next_steps"] = payload["next_steps"]
        dom_path.write_text(json.dumps(domains, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Forcantes next steps
    forc_path = OUT / "forcantes_stz_mucum_latest.json"
    if forc_path.exists():
        forc = json.loads(forc_path.read_text(encoding="utf-8"))
        forc["next_steps"] = payload["next_steps"]
        forc["estrutura_artifact"] = payload["artifacts"]
        forc_path.write_text(json.dumps(forc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Index HTML links + section
    idx = OUT / "index.html"
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        if "estrutura_stz_mucum.html" not in text:
            text = text.replace(
                '<a href="forcantes_stz_mucum.html">forçantes congeladas</a></p>',
                '<a href="forcantes_stz_mucum.html">forçantes congeladas</a> ·\n'
                '       <a href="estrutura_stz_mucum.html">estrutura STZ+Muçum</a></p>',
            )
        if "Estrutura candidata" not in text:
            block = """  <section>
    <h2>Estrutura candidata (v1)</h2>
    <div class="notice" style="border-left-color:#1b7a4a;background:#eefaf3;color:#145c38"><strong>Dois esqueletos:</strong>
    STZ (Prata + Antas residual + Carreiro + residual) e Muçum (+ incremento ~190 km²).
    Ver <a href="estrutura_stz_mucum.html">estrutura_stz_mucum.html</a>. Ainda sem calibração.</div>
  </section>

"""
            text = text.replace(
                "  <section>\n    <h2>Forçantes congeladas (v1)</h2>",
                block + "  <section>\n    <h2>Forçantes congeladas (v1)</h2>",
            )
        steps = "".join(f"<li>{html.escape(x)}</li>" for x in payload["next_steps"])
        text = re.sub(
            r"(<h2>Proximos passos de ESTUDO \(sem HEC\)</h2>\s*<ul>)(.*?)(</ul>)",
            r"\1" + steps + r"\3",
            text,
            flags=re.S,
        )
        # Also try simpler heading if present
        if "Proximos passos de ESTUDO" not in text and "Próximos passos" in text:
            pass
        idx.write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    stz_ok = payload["models"]["santa_tereza"]["area_check"]["closure_ok"]
    muc_ok = payload["models"]["mucum"]["area_check"]["closure_ok"]
    if not stz_ok or not muc_ok:
        raise SystemExit(
            f"area closure failed: STZ={payload['models']['santa_tereza']['area_check']} "
            f"MUC={payload['models']['mucum']['area_check']}"
        )
    (OUT / "estrutura_stz_mucum_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_html(payload)
    merge(payload)
    print(
        json.dumps(
            {
                "ok": True,
                "status": payload["status"],
                "stz_subbasins": payload["models"]["santa_tereza"]["area_check"]["subbasin_ids"],
                "mucum_subbasins": payload["models"]["mucum"]["area_check"]["subbasin_ids"],
                "stz_sum": payload["models"]["santa_tereza"]["area_check"]["sum_subbasin_km2"],
                "mucum_sum": payload["models"]["mucum"]["area_check"]["sum_subbasin_km2"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
