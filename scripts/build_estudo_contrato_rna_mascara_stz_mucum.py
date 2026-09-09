#!/usr/bin/env python3
"""RNA + mask contract for STZ and Muçum target models.

Locks feature lists and gap-handling rules from frozen forcings + series audit.
Does NOT train weights, claim NSE, or open HEC calibration.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"


def load(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def build_payload() -> dict:
    series = load("series_forcantes_stz_mucum_latest.json")
    forc = load("forcantes_stz_mucum_latest.json")
    estrutura = load("estrutura_stz_mucum_latest.json")

    rain = series["rain"]
    # Earliest safe overlapping rain window: STZ rain starts late
    stz_rain_start = rain["86472600"].get("first_present") or "2023-10-01 00:00"

    mask_rules = [
        {
            "id": "R1_buraco_nao_e_zero",
            "rule": "Célula vazia / None / pane NÃO vira 0.0 de chuva nem de nível.",
            "applies_to": "todas as features de chuva e nível",
        },
        {
            "id": "R2_mascara_por_feature",
            "rule": (
                "Para cada feature, gerar coluna irmã mask_<feature> (1=observado, 0=ausente). "
                "O valor numérico só entra no tensor quando mask=1."
            ),
            "applies_to": "chuva e nível",
        },
        {
            "id": "R3_linha_incompleta_no_nucleo",
            "rule": (
                "Se faltar QUALQUER feature do núcleo (core) no instante t (ou no lag exigido), "
                "a linha de treino/previsão é DESCARTADA — não interpolar chuva."
            ),
            "applies_to": "core features",
        },
        {
            "id": "R4_backup_fora_do_v1",
            "rule": (
                "A894 e CEMADEN ficam fora do núcleo v1 (CSV vazio/fraco). "
                "Podem voltar só com série preenchida por API e máscara própria."
            ),
            "applies_to": ["A894", "432040401A"],
        },
        {
            "id": "R5_nao_misturar_alvos",
            "rule": "Modelo STZ nunca usa 86510000 como feature; modelo Muçum usa 86472600 como feature, não como predictand.",
            "applies_to": "ambos",
        },
        {
            "id": "R6_janela_chuva_stz",
            "rule": (
                f"Não treinar com chuva_86472600 antes de {stz_rain_start} "
                "(coluna começa tarde no CSV). Preferir overlapping window."
            ),
            "applies_to": "86472600 chuva",
        },
    ]

    stz = {
        "label": "modelo STZ",
        "predictand": {
            "code": "86472600",
            "name": "nivel_86472600",
            "unit_hint": "cm (conferir escala do Excel-mãe / robô)",
        },
        "core_level_features": [
            {"code": "86472000", "name": "nivel_86472000", "role": "tronco_antas", "required": True},
            {"code": "86507000", "name": "nivel_86507000", "role": "afluente_carreiro", "required": True},
            {"code": "86125500", "name": "nivel_86125500", "role": "afluente_prata", "required": True},
        ],
        "core_rain_features": [
            {
                "code": "86472000",
                "name": "chuva_86472000",
                "csv_column": "chuva_86472000",
                "series_verdict": rain["86472000"]["verdict"],
                "required": True,
            },
            {
                "code": "86472600",
                "name": "chuva_86472600",
                "csv_column": "chuva_86472600",
                "series_verdict": rain["86472600"]["verdict"],
                "required": True,
                "note": "com buracos — máscara obrigatória",
            },
            {
                "code": "2851072",
                "name": "chuva_02851072",
                "csv_column": "chuva_02851072",
                "series_verdict": rain["2851072"]["verdict"],
                "required": True,
            },
        ],
        "optional_features": [
            {"code": "86448000", "name": "nivel_86448000", "role": "secundario_tronco", "required": False},
        ],
        "excluded_from_v1": [
            {"code": "A894", "reason": "CSV 0% presente"},
            {"code": "432040401A", "reason": "CSV ~1% presente / naming quirk"},
            {"code": "86510000", "reason": "alvo do outro modelo; jusante"},
            {"code": "2851044", "reason": "legado vazio; nome confunde com Guaporé"},
        ],
        "suggested_lags_hours": {
            "nivel": [0, 1, 2, 3, 4, 6, 8],
            "chuva": [0, 1, 2, 3, 6, 12, 24],
            "note": "Lags são hipótese de estudo alinhada ao robô 8h; não são hiperparâmetros calibrados aqui.",
        },
        "train_window_hint": {
            "rain_csv_overlap_start": stz_rain_start,
            "rain_csv_end": series["sources"]["rain_last"],
            "drop_if_core_mask_incomplete": True,
        },
        "topology_ref": estrutura["models"]["santa_tereza"]["topology_ascii"],
    }

    muc = {
        "label": "modelo Muçum",
        "predictand": {
            "code": "86510000",
            "name": "nivel_86510000",
            "unit_hint": "cm",
            "note": "Não está em ESTACOES_NIVEL do robô STZ — pipeline Muçum separado.",
        },
        "core_level_features": [
            {
                "code": "86472600",
                "name": "nivel_86472600",
                "role": "montante_critico_stz",
                "required": True,
                "note": "Forçante crítica; quase todo o domínio passa por STZ.",
            },
            {"code": "86472000", "name": "nivel_86472000", "role": "tronco_antas", "required": True},
            {"code": "86507000", "name": "nivel_86507000", "role": "afluente_carreiro", "required": True},
            {"code": "86125500", "name": "nivel_86125500", "role": "afluente_prata", "required": True},
        ],
        "core_rain_features": stz["core_rain_features"],
        "optional_features": stz["optional_features"],
        "excluded_from_v1": [
            {"code": "A894", "reason": "CSV 0% presente"},
            {"code": "432040401A", "reason": "CSV ~1% presente"},
            {"code": "Guaporé/Forqueta", "reason": "fora do domínio decidido"},
        ],
        "suggested_lags_hours": {
            "nivel": [0, 1, 2, 4, 8, 12, 16],
            "chuva": [0, 1, 2, 3, 6, 12, 24],
            "note": "Lag STZ→Muçum ~16h aparece no catálogo Muçum; confirmar no treino, não fixar NSE aqui.",
        },
        "train_window_hint": stz["train_window_hint"],
        "topology_ref": estrutura["models"]["mucum"]["topology_ascii"],
    }

    return {
        "schema_version": "estudo_contrato_rna_mascara_stz_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "contrato de features e mascaras RNA por alvo; nao e treino nem calibracao",
        "status": "contrato_rna_mascara_v1",
        "discipline_rule": (
            "Este artefato congela O QUE entra e COMO tratar buraco. "
            "Ainda nao treina pesos, nao publica NSE e nao libera HEC."
        ),
        "path_chosen_by_study_gate": "RNA_com_mascara",
        "hec_status": "ainda_bloqueado_ate_series_reconciliadas",
        "parent_artifacts": {
            "forcantes": "forcantes_stz_mucum_latest.json",
            "estrutura": "estrutura_stz_mucum_latest.json",
            "series": "series_forcantes_stz_mucum_latest.json",
            "forcantes_status": forc.get("status"),
            "series_status": series.get("status"),
        },
        "mask_rules": mask_rules,
        "models": {"santa_tereza": stz, "mucum": muc},
        "implementation_checklist": [
            "Gerar máscaras a partir de chuvas_horarias.csv (vazio → mask=0).",
            "Alinhar níveis ANA/Excel na mesma grade horária; mask=0 se faltar.",
            "Descartar linhas com core incompleto (R3).",
            "Treinar STZ e Muçum em experimentos SEPARADOS (dois predictands).",
            "Não promover a operacional sem validação por evento e baseline.",
        ],
        "explicitly_not_done": [
            "treino de rede",
            "busca de hiperparâmetros",
            "NSE / RMSE publicados",
            "arquivo .basin HEC calibrado",
        ],
        "next_steps": [
            "Implementar gerador de tabela máscara (CSV horário) para o núcleo STZ/Muçum.",
            "Ou: baixar histórico ANA de 86125500 em arquivo local antes de HEC por evento.",
            "Só depois: experimento de treino RNA controlado (ainda pesquisa).",
        ],
        "artifacts": {
            "json": "contrato_rna_mascara_stz_mucum_latest.json",
            "html": "contrato_rna_mascara_stz_mucum.html",
        },
    }


def feat_rows(items, kind: str) -> str:
    out = []
    for f in items:
        out.append(
            "<tr>"
            f"<td>{html.escape(f.get('code',''))}</td>"
            f"<td>{html.escape(f.get('name',''))}</td>"
            f"<td>{html.escape(f.get('role') or f.get('csv_column') or kind)}</td>"
            f"<td>{'sim' if f.get('required') else 'não'}</td>"
            f"<td>{html.escape(str(f.get('series_verdict') or f.get('note') or f.get('reason') or '—'))}</td>"
            "</tr>"
        )
    return "".join(out)


def write_html(payload: dict) -> None:
    stz = payload["models"]["santa_tereza"]
    muc = payload["models"]["mucum"]
    rules = "".join(
        f"<li><strong>{html.escape(r['id'])}:</strong> {html.escape(r['rule'])}</li>"
        for r in payload["mask_rules"]
    )
    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Contrato RNA + máscara · STZ e Muçum</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --ok:#1b7a4a; --warn:#9a5b12; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1100px; margin:auto; padding:28px 16px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,40px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--ok); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; margin:10px 0; }}
    .ok {{ border-left-color:var(--ok); background:#eefaf3; color:#145c38; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
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
    <div class="eyebrow">Estudo · contrato RNA v1</div>
    <h1>Features + máscara — ainda sem treino</h1>
    <p class="muted">{html.escape(payload['generated_at_utc'])} · {html.escape(payload['status'])}</p>
    <div class="notice ok"><strong>Caminho liberado:</strong> {html.escape(payload['path_chosen_by_study_gate'])}</div>
    <div class="notice bad"><strong>HEC:</strong> {html.escape(payload['hec_status'])}</div>
    <div class="notice"><strong>Disciplina:</strong> {html.escape(payload['discipline_rule'])}</div>
  </header>

  <section>
    <h2>Regras de máscara</h2>
    <ul>{rules}</ul>
  </section>

  <div class="grid">
    <section>
      <h2>Santa Tereza · predictand {html.escape(stz['predictand']['code'])}</h2>
      <p class="muted">Núcleo nível: {', '.join(f['code'] for f in stz['core_level_features'])}</p>
      <p class="muted">Núcleo chuva: {', '.join(f['code'] for f in stz['core_rain_features'])}</p>
      <p class="muted">Janela chuva a partir de {html.escape(str(stz['train_window_hint']['rain_csv_overlap_start']))}</p>
    </section>
    <section>
      <h2>Muçum · predictand {html.escape(muc['predictand']['code'])}</h2>
      <p class="muted">Núcleo nível: {', '.join(f['code'] for f in muc['core_level_features'])}</p>
      <p class="muted">STZ ({muc['core_level_features'][0]['code']}) é feature crítica, não alvo.</p>
      <p class="muted">Mesma chuva do STZ + máscaras idênticas.</p>
    </section>
  </div>

  <section>
    <h2>Núcleo STZ — nível</h2>
    <table><thead><tr><th>Código</th><th>Nome</th><th>Papel</th><th>Obrig.</th><th>Nota</th></tr></thead>
    <tbody>{feat_rows(stz['core_level_features'], 'nivel')}</tbody></table>
    <h2>Núcleo STZ — chuva</h2>
    <table><thead><tr><th>Código</th><th>Nome</th><th>Coluna</th><th>Obrig.</th><th>Veredito série</th></tr></thead>
    <tbody>{feat_rows(stz['core_rain_features'], 'chuva')}</tbody></table>
    <h2>Excluídos do v1</h2>
    <table><thead><tr><th>Código</th><th>Nome</th><th>—</th><th>—</th><th>Motivo</th></tr></thead>
    <tbody>{feat_rows(stz['excluded_from_v1'], 'excl')}</tbody></table>
  </section>

  <section>
    <h2>Checklist</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['implementation_checklist'])}</ul>
    <h2>Explicitamente NÃO feito</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['explicitly_not_done'])}</ul>
    <h2>Próximos</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['next_steps'])}</ul>
    <p>
      <a href="contrato_rna_mascara_stz_mucum_latest.json">JSON</a> ·
      <a href="series_forcantes_stz_mucum.html">séries</a> ·
      <a href="estrutura_stz_mucum.html">estrutura</a> ·
      <a href="index.html">estudo-base</a>
    </p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "contrato_rna_mascara_stz_mucum.html").write_text(page, encoding="utf-8")


def merge(payload: dict) -> None:
    path = OUT / "estudo_bacia_latest.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["contrato_rna_mascara_stz_mucum"] = {
            "status": payload["status"],
            "artifacts": payload["artifacts"],
            "path": payload["path_chosen_by_study_gate"],
            "hec_status": payload["hec_status"],
            "updated_at_utc": payload["generated_at_utc"],
        }
        prev["next_study_steps_only"] = payload["next_steps"]
        known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
        for item in [
            "Contrato RNA+máscara v1: núcleos STZ e Muçum definidos; A894/CEMADEN fora do v1.",
            "Caminho de estudo liberado = RNA com máscara; HEC ainda bloqueado.",
        ]:
            if item not in known:
                known.append(item)
        path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name in (
        "dois_modelos_stz_mucum_latest.json",
        "series_forcantes_stz_mucum_latest.json",
        "estrutura_stz_mucum_latest.json",
    ):
        p = OUT / name
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        data["contrato_rna_artifact"] = payload["artifacts"]
        data["next_steps"] = payload["next_steps"]
        if name.startswith("dois_"):
            data["status"] = "contrato_rna_mascara_aguardando_gerador_ou_treino"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    idx = OUT / "index.html"
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        if "contrato_rna_mascara_stz_mucum.html" not in text:
            text = text.replace(
                '<a href="series_forcantes_stz_mucum.html">séries das forçantes</a></p>',
                '<a href="series_forcantes_stz_mucum.html">séries das forçantes</a> ·\n'
                '       <a href="contrato_rna_mascara_stz_mucum.html">contrato RNA+máscara</a></p>',
            )
        if "Contrato RNA" not in text:
            block = """  <section>
    <h2>Contrato RNA + máscara (v1)</h2>
    <div class="notice" style="border-left-color:#1b7a4a;background:#eefaf3;color:#145c38"><strong>Caminho liberado:</strong>
    Features e regras de buraco por alvo. Sem treino/NSE. HEC ainda bloqueado.
    Ver <a href="contrato_rna_mascara_stz_mucum.html">contrato_rna_mascara_stz_mucum.html</a>.</div>
  </section>

"""
            text = text.replace(
                "  <section>\n    <h2>Séries das forçantes (v1)</h2>",
                block + "  <section>\n    <h2>Séries das forçantes (v1)</h2>",
            )
        steps = "".join(f"<li>{html.escape(x)}</li>" for x in payload["next_steps"])
        text = re.sub(
            r"(<h2>Proximos passos de ESTUDO \(sem HEC\)</h2>\s*<ul>)(.*?)(</ul>)",
            r"\1" + steps + r"\3",
            text,
            flags=re.S,
        )
        idx.write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    (OUT / "contrato_rna_mascara_stz_mucum_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_html(payload)
    merge(payload)
    print(
        json.dumps(
            {
                "ok": True,
                "status": payload["status"],
                "path": payload["path_chosen_by_study_gate"],
                "stz_core_level": [f["code"] for f in payload["models"]["santa_tereza"]["core_level_features"]],
                "stz_core_rain": [f["code"] for f in payload["models"]["santa_tereza"]["core_rain_features"]],
                "muc_core_level": [f["code"] for f in payload["models"]["mucum"]["core_level_features"]],
                "excluded_v1": [f["code"] for f in payload["models"]["santa_tereza"]["excluded_from_v1"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
