#!/usr/bin/env python3
"""Lock the primary PREVINE path: multi-site river LEVEL via RNA — not HEC-first.

Juliana's product need: forecast river level (cota/nível) at several basin
locations. Santa Tereza has no rating curve; that blocks HEC Q at STZ and is
irrelevant for supervised nível models.

This script writes a decision artifact + candidate target inventory.
It does not train models, invent N→Q, or promote operational alerts.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
POSTOS = OUT / "postos_g040.geojson"
SERIES = OUT / "series_forcantes_stz_mucum_latest.json"
CONTRATO = OUT / "contrato_rna_mascara_stz_mucum_latest.json"
HEC = OUT / "hec_twin_stz_mucum_v1_latest.json"
MUCUM_INPUTS = ROOT / "assets" / "data" / "mucum_modelo_inputs.json"
STZ_ROBO = ROOT / "previne" / "robo" / "gerar_previsao_ao_vivo.py"

SCHEMA = "estudo_decisao_previsao_nivel_multi_alvo_v1"

# Live / catalog stations already used as nível features or targets.
KNOWN_NIVEL = {
    "86472600": {
        "name": "Santa Tereza",
        "tier": "alvo_operacional_rna",
        "role_now": "target_santa_tereza",
        "has_live_rna": True,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": True,
        "rating_curve_status": "ausente_oficial_publica",
        "note": "Alvo RNA de nível já publicado. Sem curva-chave — HEC Q bloqueado; RNA de N não precisa de curva.",
    },
    "86510000": {
        "name": "Muçum",
        "tier": "alvo_operacional_rna",
        "role_now": "target_mucum",
        "has_live_rna": True,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "existe_para_Q_ANA_em_eventos",
        "note": "Alvo RNA de nível já publicado. HEC twin Q eventwise existe como pesquisa paralela, não substitui RNA de N.",
    },
    "86472000": {
        "name": "Linha José Júlio / Antas",
        "tier": "candidato_alvo_nivel",
        "role_now": "upstream_feature",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "vizinha_com_curva_em_hunt",
        "note": "Hoje é forcante de nível. Pode virar alvo RNA próprio se houver interesse municipal/alerta no ponto.",
    },
    "86507000": {
        "name": "PCH Cotiporã Jusante / Carreiro",
        "tier": "candidato_alvo_nivel",
        "role_now": "upstream_feature",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_avaliado_como_alvo",
        "note": "Forcante Carreiro. Candidato a alvo RNA se o risco local for relevante.",
    },
    "86125500": {
        "name": "PCH Jararaca / Prata",
        "tier": "candidato_alvo_nivel",
        "role_now": "upstream_feature",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_avaliado_como_alvo",
        "note": "Entrada 4h/8h/12h. Auditar série histórica ANA antes de treinar alvo próprio.",
    },
    "86448000": {
        "name": "UHE Monte Claro / Antas",
        "tier": "candidato_alvo_nivel",
        "role_now": "upstream_feature",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_avaliado_como_alvo",
        "note": "Secundário no Excel. Só promover a alvo com série contínua e caso de uso claro.",
    },
    "86125130": {
        "name": "PCH Morro Grande / Ituim",
        "tier": "forcante_apenas",
        "role_now": "upstream_feature",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_aplicavel",
        "note": "Útil como input; raramente faz sentido como alvo de alerta de cidade do corredor.",
    },
    "86298000": {
        "name": "UHE Castro Alves",
        "tier": "forcante_apenas",
        "role_now": "upstream_feature",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_aplicavel",
        "note": "Barramento / montante Antas — forcante, não prioridade de mancha urbana.",
    },
    "86306000": {
        "name": "Estação 86306000",
        "tier": "forcante_apenas",
        "role_now": "upstream_feature_stz_robo",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_avaliado",
        "note": "No ESTACOES_NIVEL do robô STZ; auditar cobertura antes de qualquer promoção.",
    },
    "86430900": {
        "name": "Estação 86430900",
        "tier": "forcante_apenas",
        "role_now": "upstream_feature_stz_robo",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_avaliado",
        "note": "Input 8h V001; sem ficha municipal de previsão hoje.",
    },
    "86447000": {
        "name": "Estação 86447000",
        "tier": "forcante_apenas",
        "role_now": "upstream_feature_stz_robo",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_avaliado",
        "note": "Input 8h V002; sem ficha municipal de previsão hoje.",
    },
    "86505500": {
        "name": "Estação 86505500",
        "tier": "forcante_apenas",
        "role_now": "upstream_feature_stz_robo",
        "has_live_rna": False,
        "needs_rating_curve_for_nivel_rna": False,
        "needs_rating_curve_for_hec_q": False,
        "rating_curve_status": "nao_avaliado",
        "note": "Pode ser chuva/nível misto no robô; não tratar como alvo sem auditoria.",
    },
}

# Towns often asked about but without a dedicated RNA sheet today.
UNGAGED_OR_SHEETLESS = [
    {
        "name": "Encantado",
        "tier": "sem_alvo_rna_proprio",
        "path": "transferencia_espacial",
        "note": "Sem ficha RNA municipal. Não inventar com HEC. Opções: posto mais próximo com N + HAND/MDT, ou novo sensor.",
    },
    {
        "name": "Roca Sales",
        "tier": "sem_alvo_rna_proprio",
        "path": "transferencia_espacial",
        "note": "Sem ficha RNA municipal. Mesma lógica: N observado local ou transferência honesta a partir de Muçum/STZ.",
    },
    {
        "name": "Lajeado / Baixo Taquari",
        "tier": "fora_do_corredor_atual",
        "path": "novo_recorte",
        "note": "Fora do recorte Guaporé/Forqueta/Baixo excluído dos dois modelos. Só entra com decisão explícita de domínio.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_postos_index() -> dict[str, dict]:
    if not POSTOS.exists():
        return {}
    geo = json.loads(POSTOS.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for feat in geo.get("features", []):
        props = feat.get("properties") or {}
        code = str(props.get("codigo") or "").strip()
        if code:
            out[code] = props
    return out


def parse_stz_robo_stations() -> list[str]:
    text = STZ_ROBO.read_text(encoding="utf-8")
    start = text.find("ESTACOES_NIVEL = [")
    if start < 0:
        return []
    chunk = text[start : text.find("]", start) + 1]
    return [c.strip().strip('"') for c in chunk.split('"') if c.strip().isdigit()]


def build_candidates(postos: dict[str, dict]) -> list[dict]:
    rows = []
    for code, meta in KNOWN_NIVEL.items():
        p = postos.get(code, {})
        rows.append(
            {
                "station_code": code,
                **meta,
                "municipio": p.get("municipio"),
                "rio": p.get("rio"),
                "upg": p.get("upg"),
                "telemetrica": p.get("telemetrica"),
                "operando": p.get("operando"),
                "lat": p.get("lat"),
                "lon": p.get("lon"),
                "area_drenagem_km2": p.get("area_drenagem_km2"),
            }
        )
    # Keep stable order: targets first, then candidates, then features.
    order = {"alvo_operacional_rna": 0, "candidato_alvo_nivel": 1, "forcante_apenas": 2}
    rows.sort(key=lambda r: (order.get(r["tier"], 9), r["station_code"]))
    return rows


def build_payload(candidates: list[dict]) -> dict:
    hec_status = None
    if HEC.exists():
        hec_status = json.loads(HEC.read_text(encoding="utf-8")).get("status")
    contrato_status = None
    path_chosen = None
    if CONTRATO.exists():
        c = json.loads(CONTRATO.read_text(encoding="utf-8"))
        contrato_status = c.get("status")
        path_chosen = c.get("path_chosen_by_study_gate")
    series_ready = None
    if SERIES.exists():
        series_ready = json.loads(SERIES.read_text(encoding="utf-8")).get("readiness")

    mucum_inputs = None
    if MUCUM_INPUTS.exists():
        mi = json.loads(MUCUM_INPUTS.read_text(encoding="utf-8"))
        mucum_inputs = sorted(str(k) for k in (mi.get("estacoes_input") or {}).keys())

    return {
        "schema_version": SCHEMA,
        "generated_at_utc": utc_now(),
        "purpose": (
            "Decisão de produto: melhor forma de prever NÍVEL do rio em vários "
            "locais da bacia — e o que NÃO investir agora."
        ),
        "status": "decidido_rna_nivel_multi_alvo_hec_estacionado",
        "decision": {
            "by": "Juliana (pedido) + agente (recomendação técnica travada)",
            "question": "Qual a melhor forma de prever o nível do rio em vários locais da bacia?",
            "chosen_path": "RNA_nivel_por_estacao_com_mascara",
            "not_chosen_as_primary": [
                "HEC-HMS / gêmeo HEC como caminho principal de previsão de nível",
                "Inventar curva-chave N→Q para Santa Tereza",
                "Usar curva de vizinho (Antas/Muçum) como se fosse STZ",
                "Continuar entregas HEC pedaço a pedaço sem fechar a arquitetura de previsão",
            ],
            "why_rna": [
                "O produto PREVINE já prevê NÍVEL (cm) com RNA ao vivo em Santa Tereza e Muçum.",
                "Mancha/HAND consome cota/nível, não vazão HEC.",
                "RNA supervisionada de nível não exige curva-chave.",
                "Santa Tereza sem curva-chave: isso bloqueia HEC Q no alvo STZ e é irrelevante para RNA de N.",
                "Multi-local honesto = um modelo (ou cabeça) por estação com série de N observada — não um HEC único da bacia.",
            ],
            "why_not_hec_first": [
                "HEC calibra/simula Q; converter Q→N em cada ponto exige curva local.",
                "STZ (86472600) não tem curva oficial pública no estudo — hunt e checklist confirmam bloqueio.",
                "Pacote HEC twin Muçum eventwise é pesquisa de processo hidrológico, não previsão operacional de nível multi-site.",
                "Entregar mais polish HEC sem fechar a pergunta de produto atrasa o que importa.",
            ],
            "hec_role_now": "estacionado_pesquisa_q_onde_ha_vazao",
            "hec_may_return_when": [
                "Curva oficial STZ anexada (se um dia quiser Q física em STZ)",
                "Pergunta científica explícita sobre processo Q no corredor Muçum",
            ],
            "stz_rating_curve": {
                "exists": False,
                "impact_on_nivel_rna": "nenhum",
                "impact_on_hec_q_stz": "bloqueia_calibracao_alvo_Q",
                "rule": "Não inventar N→Q. Não pedir curva como pré-requisito da previsão de nível.",
            },
        },
        "architecture": {
            "unit": "um_modelo_RNA_por_estacao_alvo_com_serie_de_nivel",
            "predictand": "nivel_cm_ou_delta_nivel",
            "features": "niveis_montante + chuva_nucleo + mascaras (buraco != zero)",
            "existing_live_targets": ["86472600", "86510000"],
            "expansion_rule": (
                "Só promove estação a alvo se: (1) série de nível contínua/auditável, "
                "(2) caso de uso de alerta/mancha local, (3) contrato de features + máscara, "
                "(4) validação hold-out por evento antes de robô ao vivo."
            ),
            "ungaged_sites_rule": (
                "Município sem posto de nível: transferência espacial (N do posto âncora + HAND/MDT) "
                "ou novo sensor — não HEC inventado."
            ),
            "excluded_from_current_corridor_cut": ["Guaporé", "Forqueta", "Baixo Taquari-Antas"],
        },
        "investment_next": [
            {
                "priority": 1,
                "id": "fortalecer_stz_mucum_nivel",
                "action": "Manter e endurecer RNA STZ/Muçum (máscara, hold-out, multi-horizonte) — já é o produto.",
            },
            {
                "priority": 2,
                "id": "auditar_candidatos_alvo",
                "action": (
                    "Auditar série histórica de nível ANA para candidatos "
                    "(86472000, 86507000, 86125500) e decidir quais viram alvo."
                ),
            },
            {
                "priority": 3,
                "id": "contrato_multi_alvo",
                "action": "Generalizar contrato RNA+máscara para N alvos (não só STZ/Muçum).",
            },
            {
                "priority": 4,
                "id": "transferencia_sem_medidor",
                "action": "Para Encantado/Roca Sales: desenhar transferência N-âncora→HAND, sem fingir posto local.",
            },
            {
                "priority": 99,
                "id": "hec_estacionado",
                "action": "Não abrir nova rodada HEC salvo pedido explícito de processo Q.",
            },
        ],
        "candidates": candidates,
        "ungaged_or_sheetless": UNGAGED_OR_SHEETLESS,
        "context_artifacts": {
            "hec_twin_status": hec_status,
            "contrato_rna_status": contrato_status,
            "path_chosen_by_study_gate": path_chosen,
            "series_readiness": series_ready,
            "mucum_input_stations": mucum_inputs,
            "stz_robo_nivel_stations": parse_stz_robo_stations(),
        },
        "discipline_rules": [
            "Prever NÍVEL, não exigir vazão, salvo pergunta Q explícita.",
            "Santa Tereza sem curva-chave não bloqueia RNA de nível.",
            "Não inventar curva-chave; não copiar curva de vizinho para STZ.",
            "Não chamar corredor STZ–Muçum de modelo da bacia G040.",
            "Não entregar HEC em fatias como se fosse o produto de previsão multi-local.",
            "Alerta oficial continua bloqueado até validação institucional.",
        ],
        "artifacts": {
            "json": "decisao_previsao_nivel_multi_alvo_latest.json",
            "html": "decisao_previsao_nivel_multi_alvo.html",
        },
    }


def render_html(data: dict) -> str:
    d = data["decision"]
    rows = []
    for c in data["candidates"]:
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(c['station_code'])}</code></td>"
            f"<td>{html.escape(c['name'])}</td>"
            f"<td>{html.escape(c['tier'])}</td>"
            f"<td>{html.escape(str(c.get('role_now')))}</td>"
            f"<td>{'sim' if c.get('has_live_rna') else 'não'}</td>"
            f"<td>{html.escape(c.get('note') or '')}</td>"
            "</tr>"
        )
    ung = "".join(
        f"<li><strong>{html.escape(u['name'])}</strong> — {html.escape(u['note'])}</li>"
        for u in data["ungaged_or_sheetless"]
    )
    inv = "".join(
        f"<li><strong>P{html.escape(str(i['priority']))}</strong> — {html.escape(i['action'])}</li>"
        for i in data["investment_next"]
    )
    why = "".join(f"<li>{html.escape(x)}</li>" for x in d["why_rna"])
    why_not = "".join(f"<li>{html.escape(x)}</li>" for x in d["why_not_hec_first"])
    rules = "".join(f"<li>{html.escape(x)}</li>" for x in data["discipline_rules"])
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <title>Decisão: previsão de nível multi-alvo</title>
  <style>
    :root {{ --ink:#1a2421; --muted:#4a5a55; --bg:#e8f0ec; --card:#f7fbf8; --ok:#1f6b4a; --warn:#8a5a12; --bad:#8a2f2f; }}
    body {{ margin:0; font-family:"Source Serif 4", "Libre Baskerville", Georgia, serif; color:var(--ink);
      background: radial-gradient(1200px 600px at 10% -10%, #cfe3d8, transparent),
                  linear-gradient(165deg, #d5e6df, #eef3ef 55%, #f4f7f5); }}
    main {{ max-width: 920px; margin: 0 auto; padding: 2.2rem 1.2rem 3rem; }}
    h1 {{ font-size: clamp(1.6rem, 3vw, 2.2rem); margin: 0 0 .4rem; letter-spacing: -0.02em; }}
    .lead {{ color: var(--muted); font-size: 1.05rem; margin-bottom: 1.4rem; }}
    .pill {{ display:inline-block; padding:.25rem .7rem; border:1px solid #9bb8a8; color:var(--ok); font-size:.85rem; }}
    section {{ margin: 1.6rem 0; padding: 1rem 0; border-top: 1px solid #c5d5cc; }}
    h2 {{ font-size: 1.15rem; margin: 0 0 .7rem; }}
    ul {{ padding-left: 1.15rem; }}
    li {{ margin: .35rem 0; }}
    table {{ width:100%; border-collapse: collapse; font-size: .92rem; background: var(--card); }}
    th, td {{ text-align:left; padding: .45rem .5rem; border-bottom: 1px solid #d5e0da; vertical-align: top; }}
    th {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }}
    code {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .86em; }}
    .notice {{ padding: .8rem 1rem; margin: 1rem 0; background: #e3f0e8; border-left: 4px solid var(--ok); }}
    .notice.warn {{ background: #f5ecda; border-left-color: var(--warn); }}
    a {{ color: var(--ok); }}
  </style>
</head>
<body>
  <main>
    <p class="pill">{html.escape(data["status"])}</p>
    <h1>Prever nível em vários locais: RNA, não HEC-primeiro</h1>
    <p class="lead">{html.escape(d["question"])}</p>
    <div class="notice">
      <strong>Decisão travada:</strong> {html.escape(d["chosen_path"])}.
      HEC fica <em>{html.escape(d["hec_role_now"])}</em>.
      Santa Tereza sem curva-chave <strong>não</strong> bloqueia previsão de nível.
    </div>
    <section>
      <h2>Por que RNA de nível</h2>
      <ul>{why}</ul>
    </section>
    <section>
      <h2>Por que não HEC como caminho principal</h2>
      <ul>{why_not}</ul>
    </section>
    <section>
      <h2>Investimento (ordem)</h2>
      <ul>{inv}</ul>
    </section>
    <section>
      <h2>Estações: alvos, candidatos e forcantes</h2>
      <table>
        <thead><tr><th>Código</th><th>Nome</th><th>Tier</th><th>Papel hoje</th><th>RNA ao vivo</th><th>Nota</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </section>
    <section>
      <h2>Locais sem ficha de nível própria</h2>
      <ul>{ung}</ul>
    </section>
    <section>
      <h2>Disciplina</h2>
      <ul>{rules}</ul>
      <p class="notice warn">Artefato de decisão de estudo — não é alerta oficial.</p>
      <p><a href="decisao_previsao_nivel_multi_alvo_latest.json">JSON</a> ·
         <a href="contrato_rna_mascara_stz_mucum.html">Contrato RNA</a> ·
         <a href="hec_twin_stz_mucum_v1.html">HEC twin (estacionado)</a></p>
    </section>
  </main>
</body>
</html>
"""


def patch_stz_checklist() -> None:
    path = OUT / "stz_q_unlock_checklist_latest.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["primary_product_path"] = "RNA_nivel_nao_exige_curva"
    data["hec_primary"] = False
    data["note_for_nivel_forecast"] = (
        "Curva-chave STZ continua ausente e continua bloqueando HEC Q em STZ. "
        "Isso NÃO bloqueia previsão de nível por RNA. Pedido de produto = nível multi-local → investir em RNA."
    )
    data["ask_juliana_or_ops"] = (
        "Não é pré-requisito para previsão de nível. Só anexar curva oficial se quiser desbloquear HEC Q em STZ."
    )
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_readme() -> None:
    path = OUT / "README.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    block = (
        "\n## Decisão de previsão (nível multi-alvo)\n\n"
        "**Caminho principal:** RNA de nível por estação (`decisao_previsao_nivel_multi_alvo.html`).\n\n"
        "HEC/gêmeo HEC está **estacionado** como pesquisa de Q onde há vazão. "
        "Santa Tereza sem curva-chave não bloqueia RNA de nível.\n\n"
        "```bash\n"
        "python3 scripts/build_estudo_decisao_previsao_nivel_multi_alvo.py\n"
        "```\n"
    )
    marker = "## Decisão de previsão (nível multi-alvo)"
    if marker in text:
        # replace from marker to next ## or end
        import re

        text = re.sub(
            r"\n## Decisão de previsão \(nível multi-alvo\).*?(?=\n## |\Z)",
            block,
            text,
            count=1,
            flags=re.S,
        )
    else:
        # insert after "## Decisao de recorte" section end — append near top after recorte pointer
        if "Leia `recorte_modelo.html` antes de qualquer HEC." in text:
            text = text.replace(
                "Leia `recorte_modelo.html` antes de qualquer HEC.",
                "Leia `recorte_modelo.html` antes de qualquer HEC.\n"
                "Leia `decisao_previsao_nivel_multi_alvo.html` antes de qualquer nova rodada HEC.",
            )
        text = text.rstrip() + "\n" + block
    path.write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    postos = load_postos_index()
    candidates = build_candidates(postos)
    payload = build_payload(candidates)
    json_path = OUT / payload["artifacts"]["json"]
    html_path = OUT / payload["artifacts"]["html"]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(payload), encoding="utf-8")
    patch_stz_checklist()
    patch_readme()
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    print(f"status={payload['status']}")
    print(f"candidates={len(candidates)}")


if __name__ == "__main__":
    main()
