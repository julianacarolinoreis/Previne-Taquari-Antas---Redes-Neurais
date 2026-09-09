#!/usr/bin/env python3
"""Freeze short forcing lists for STZ and Muçum target models.

Curated from PREVINE operational seeds + domain study.
Still NOT HEC structure / calibration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"


def station(codigo, nome, papel, rede="ANA", notes=None, status="ativo_proposto"):
    return {
        "codigo": codigo,
        "nome": nome,
        "papel": papel,
        "rede": rede,
        "status": status,
        "notes": notes,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    domains = json.loads((OUT / "dois_modelos_stz_mucum_latest.json").read_text(encoding="utf-8"))

    report = {
        "schema_version": "estudo_forcantes_stz_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "lista curta congelada de forçantes por modelo-alvo; nao e HEC",
        "status": "forcantes_congeladas_v1",
        "discipline_rule": (
            "Estas listas sao o contrato de ENTRADAS candidato. "
            "Ainda nao definem subbacias HEC, parametros, nem calibracao."
        ),
        "selection_rules": [
            "Priorizar seeds PREVINE ja usados em RNA/operacao.",
            "Cobrir tronco + Prata + Carreiro (entradas hidrologicas a montante dos dois alvos).",
            "Manter lista curta (<=6 nivel + <=5 chuva por modelo) para nao voltar ao inventario de 160 postos.",
            "Excluir Guapore/Forqueta/Baixo — fora do recorte decidido.",
            "Marcar backups e postos com pane/serie fraca sem promove-los a primario.",
        ],
        "excluded_from_both": {
            "upgs": ["Guaporé", "Forqueta", "Baixo Taquari-Antas"],
            "families": ["7864", "7862"],
            "examples_not_used": [
                "qualquer posto so na UPG Guapore/Forqueta/Baixo",
                "2851044 como chuva primaria (legado vazio no CSV; nome 'GUAPORE' confunde)",
            ],
        },
        "models": {
            "santa_tereza": {
                "target": station(
                    "86472600",
                    "Santa Tereza",
                    "alvo_predicao (nivel)",
                    notes="Predictand do modelo STZ — nao contar como forçante de montante.",
                ),
                "nested_area_km2": 15775.186,
                "level_forcings": [
                    station(
                        "86472000",
                        "Linha Jose Julio / Antas",
                        "nivel_montante_tronco",
                        notes="Controle primario do tronco Antas a montante de STZ.",
                    ),
                    station(
                        "86507000",
                        "PCH Cotipora Jusante / Carreiro",
                        "nivel_afluente_carreiro",
                        notes="Representa entrada Carreiro (7866) entre Antas e STZ.",
                    ),
                    station(
                        "86125500",
                        "PCH Jararaca Barramento / Prata",
                        "nivel_afluente_prata",
                        notes="Representa sistema Prata (7868). Backup: 86447000, 86125130.",
                    ),
                    station(
                        "86448000",
                        "UHE Monte Claro Barramento",
                        "nivel_tronco_intermediario",
                        notes="Opcional/secundario no tronco entre Prata e Antas-STZ.",
                        status="secundario",
                    ),
                ],
                "rain_forcings": [
                    station(
                        "86472000",
                        "Linha Jose Julio (sensor chuva)",
                        "chuva_tronco",
                        notes="Coluna chuva_86472000 do CSV operacional.",
                    ),
                    station(
                        "86472600",
                        "Santa Tereza (sensor chuva)",
                        "chuva_local_alvo",
                        notes="Coluna chuva_86472600; serie pode ter buracos — nao inventar zero.",
                    ),
                    station(
                        "2851072",
                        "Ibiraiaras / Carreiro-Prata",
                        "chuva_carreiro_prata",
                        notes="Coluna chuva_02851072 — primaria de afluente no Excel-mae 8h.",
                    ),
                    station(
                        "A894",
                        "INMET Serafina Correa",
                        "chuva_backup_inmet",
                        rede="INMET",
                        status="backup",
                        notes="Pode estar em Pane; ausencia != zero.",
                    ),
                    station(
                        "432040401A",
                        "CEMADEN Serafina Correa Centro",
                        "chuva_backup_cemaden",
                        rede="CEMADEN",
                        status="backup",
                        notes="Complemento espacial perto de Carreiro/Serafina.",
                    ),
                ],
                "not_in_this_model": [
                    "86510000 Muçum (alvo do outro modelo; jusante de STZ)",
                    "postos so Guapore/Forqueta/Baixo",
                ],
                "counts": {"level_primary": 3, "level_secondary": 1, "rain_primary": 3, "rain_backup": 2},
            },
            "mucum": {
                "target": station(
                    "86510000",
                    "Muçum",
                    "alvo_predicao (nivel)",
                    notes="Predictand do modelo Muçum.",
                ),
                "nested_area_km2": 15965.207,
                "level_forcings": [
                    station(
                        "86472600",
                        "Santa Tereza",
                        "nivel_montante_critico",
                        notes="Forçante principal: quase todo o dominio Muçum passa por STZ.",
                    ),
                    station(
                        "86472000",
                        "Linha Jose Julio / Antas",
                        "nivel_montante_tronco",
                        notes="Tronco Antas; util com STZ para separar onda de montante.",
                    ),
                    station(
                        "86507000",
                        "PCH Cotipora Jusante / Carreiro",
                        "nivel_afluente_carreiro",
                        notes="Mesma entrada Carreiro do modelo STZ.",
                    ),
                    station(
                        "86125500",
                        "PCH Jararaca Barramento / Prata",
                        "nivel_afluente_prata",
                        notes="Mesma entrada Prata do modelo STZ.",
                    ),
                    station(
                        "86448000",
                        "UHE Monte Claro Barramento",
                        "nivel_tronco_intermediario",
                        status="secundario",
                        notes="Opcional.",
                    ),
                ],
                "rain_forcings": [
                    station(
                        "86472000",
                        "Linha Jose Julio (sensor chuva)",
                        "chuva_tronco",
                    ),
                    station(
                        "86472600",
                        "Santa Tereza (sensor chuva)",
                        "chuva_faixa_stz_mucum",
                        notes="Chuva entre STZ e Mucum + contexto local.",
                    ),
                    station(
                        "2851072",
                        "Ibiraiaras / Carreiro-Prata",
                        "chuva_carreiro_prata",
                    ),
                    station(
                        "A894",
                        "INMET Serafina Correa",
                        "chuva_backup_inmet",
                        rede="INMET",
                        status="backup",
                        notes="Pane possivel; ausencia != zero.",
                    ),
                    station(
                        "432040401A",
                        "CEMADEN Serafina Correa Centro",
                        "chuva_backup_cemaden",
                        rede="CEMADEN",
                        status="backup",
                    ),
                ],
                "not_in_this_model": [
                    "postos so Guapore/Forqueta/Baixo",
                    "tratar Mucum como se visse Guapore (~+2495 km2 a jusante)",
                ],
                "counts": {"level_primary": 4, "level_secondary": 1, "rain_primary": 3, "rain_backup": 2},
            },
        },
        "shared_notes": {
            "stz_inside_mucum": (
                "O modelo Mucum reutiliza as forçantes de montante do STZ e acrescenta STZ como nivel critico. "
                "Nao sao o mesmo modelo: alvos e funcoes objetivo diferentes."
            ),
            "carreiro_is_not_optional_for_stz": (
                "Carreiro entra entre Antas e STZ — forçante de nivel/chuva de afluente e obrigatoria no desenho STZ."
            ),
            "naming": "Nunca rotular estas listas como 'bacia Taquari-Antas completa'.",
        },
        "next_steps": [
            "Com forçantes congeladas: desenhar estrutura HEC (ou confirmar RNA) separada por alvo.",
            "Validar disponibilidade de serie (buracos STZ chuva, A894 pane) antes de calibrar.",
            "Manter Guapore/Forqueta fora ate mudar o recorte explicitamente.",
        ],
        "artifacts": {
            "json": "forcantes_stz_mucum_latest.json",
            "html": "forcantes_stz_mucum.html",
        },
        "parent_decision": {
            "source": "dois_modelos_stz_mucum_latest.json",
            "chosen": domains.get("decision", {}).get("chosen"),
        },
    }

    (OUT / "forcantes_stz_mucum_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_html(report)
    merge(report, domains)
    print(
        json.dumps(
            {
                "ok": True,
                "stz_level": [s["codigo"] for s in report["models"]["santa_tereza"]["level_forcings"]],
                "muc_level": [s["codigo"] for s in report["models"]["mucum"]["level_forcings"]],
                "stz_rain": [s["codigo"] for s in report["models"]["santa_tereza"]["rain_forcings"]],
                "muc_rain": [s["codigo"] for s in report["models"]["mucum"]["rain_forcings"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def rows(items):
    return "".join(
        "<tr>"
        f"<td>{s['codigo']}</td><td>{s['nome']}</td><td>{s['papel']}</td>"
        f"<td>{s['status']}</td><td>{s.get('notes') or ''}</td>"
        "</tr>"
        for s in items
    )


def write_html(report: dict) -> None:
    stz = report["models"]["santa_tereza"]
    muc = report["models"]["mucum"]
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Forçantes congeladas · STZ e Muçum</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --ok:#1b7a4a; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1100px; margin:auto; padding:28px 16px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,42px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--ok); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
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
    <div class="eyebrow">Estudo · forçantes v1</div>
    <h1>Lista curta congelada — ainda sem HEC</h1>
    <p class="muted">{report['generated_at_utc']} · {report['status']}</p>
    <div class="notice ok"><strong>Contrato de entradas:</strong> {report['discipline_rule']}</div>
    <div class="notice bad"><strong>Fora:</strong> Guapore, Forqueta, Baixo. Nao rotular como bacia G040.</div>
  </header>

  <section>
    <h2>Modelo Santa Tereza · alvo {stz['target']['codigo']}</h2>
    <p class="muted">~{stz['nested_area_km2']:,.0f} km² · nivel primario {stz['counts']['level_primary']} · chuva primaria {stz['counts']['rain_primary']}</p>
    <h3>Nivel</h3>
    <table><thead><tr><th>Codigo</th><th>Nome</th><th>Papel</th><th>Status</th><th>Nota</th></tr></thead>
    <tbody>{rows(stz['level_forcings'])}</tbody></table>
    <h3>Chuva</h3>
    <table><thead><tr><th>Codigo</th><th>Nome</th><th>Papel</th><th>Status</th><th>Nota</th></tr></thead>
    <tbody>{rows(stz['rain_forcings'])}</tbody></table>
  </section>

  <section>
    <h2>Modelo Muçum · alvo {muc['target']['codigo']}</h2>
    <p class="muted">~{muc['nested_area_km2']:,.0f} km² · nivel primario {muc['counts']['level_primary']} · chuva primaria {muc['counts']['rain_primary']}</p>
    <h3>Nivel</h3>
    <table><thead><tr><th>Codigo</th><th>Nome</th><th>Papel</th><th>Status</th><th>Nota</th></tr></thead>
    <tbody>{rows(muc['level_forcings'])}</tbody></table>
    <h3>Chuva</h3>
    <table><thead><tr><th>Codigo</th><th>Nome</th><th>Papel</th><th>Status</th><th>Nota</th></tr></thead>
    <tbody>{rows(muc['rain_forcings'])}</tbody></table>
  </section>

  <section>
    <h2>Notas compartilhadas</h2>
    <ul>
      <li>{report['shared_notes']['stz_inside_mucum']}</li>
      <li>{report['shared_notes']['carreiro_is_not_optional_for_stz']}</li>
      <li>{report['shared_notes']['naming']}</li>
    </ul>
    <h2>Proximos</h2>
    <ul>{''.join(f'<li>{x}</li>' for x in report['next_steps'])}</ul>
    <p><a href="forcantes_stz_mucum_latest.json">JSON</a> ·
       <a href="dois_modelos_stz_mucum.html">dominios</a> ·
       <a href="index.html">estudo-base</a></p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "forcantes_stz_mucum.html").write_text(html, encoding="utf-8")


def merge(report: dict, domains: dict) -> None:
    path = OUT / "estudo_bacia_latest.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["forcantes_stz_mucum"] = {
            "status": report["status"],
            "artifacts": report["artifacts"],
            "stz_level": [s["codigo"] for s in report["models"]["santa_tereza"]["level_forcings"]],
            "mucum_level": [s["codigo"] for s in report["models"]["mucum"]["level_forcings"]],
            "updated_at_utc": report["generated_at_utc"],
        }
        known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
        for item in [
            "Forçantes v1 congeladas para modelo STZ e modelo Mucum (lista curta).",
            "Carreiro e Prata entram como forçantes de afluente nos dois alvos.",
        ]:
            if item not in known:
                known.append(item)
        prev["next_study_steps_only"] = report["next_steps"]
        path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # patch domains next steps + html link
    domains["status"] = "forcantes_congeladas_aguardando_estrutura"
    domains["next_steps"] = report["next_steps"]
    domains["forcantes_artifact"] = report["artifacts"]
    (OUT / "dois_modelos_stz_mucum_latest.json").write_text(
        json.dumps(domains, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    idx = OUT / "index.html"
    if idx.exists():
        html = idx.read_text(encoding="utf-8")
        if "forcantes_stz_mucum.html" not in html:
            html = html.replace(
                '<a href="dois_modelos_stz_mucum.html">dois modelos STZ+Muçum (decidido)</a></p>',
                '<a href="dois_modelos_stz_mucum.html">dois modelos STZ+Muçum</a> ·\n'
                '       <a href="forcantes_stz_mucum.html">forçantes congeladas</a></p>',
            )
        if "Forçantes congeladas" not in html:
            block = """  <section>
    <h2>Forçantes congeladas (v1)</h2>
    <div class="notice" style="border-left-color:#1b7a4a;background:#eefaf3;color:#145c38"><strong>Lista curta:</strong>
    STZ e Mucum com tronco + Carreiro + Prata; chuva operacional + backups INMET/CEMADEN.
    Ver <a href="forcantes_stz_mucum.html">forcantes_stz_mucum.html</a>. Ainda sem HEC.</div>
  </section>

"""
            html = html.replace(
                "  <section>\n    <h2>Decisao: dois modelos-alvo",
                block + "  <section>\n    <h2>Decisao: dois modelos-alvo",
            )
        from html import escape
        import re

        steps = "".join(f"<li>{escape(x)}</li>" for x in report["next_steps"])
        html = re.sub(
            r"(<h2>Proximos passos de ESTUDO \(sem HEC\)</h2>\s*<ul>)(.*?)(</ul>)",
            r"\1" + steps + r"\3",
            html,
            flags=re.S,
        )
        idx.write_text(html)


if __name__ == "__main__":
    main()
