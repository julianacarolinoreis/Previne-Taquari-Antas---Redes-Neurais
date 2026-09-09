#!/usr/bin/env python3
"""Lock Juliana's decision: two target models (Santa Tereza + Muçum).

Defines hydrologic domains from existing study artifacts.
Does NOT build or calibrate HEC.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"

# Trusted nested areas from prior BHO6 clip study (not the noisy 8 km snap)
NESTED = {
    "86472000": {"name": "Linha Jose Julio / Antas", "area_km2": 12918.656},
    "86472600": {"name": "Santa Tereza", "area_km2": 15775.186},
    "86510000": {"name": "Muçum", "area_km2": 15965.207},
}

# Families that join upstream of Muçum (hence also available to STZ except timing)
UPSTREAM_OF_MUCUM_FAMILIES = {"786", "7868", "7866", "7860", "7861", "7863", "7865", "7867", "7869"}
# Guapore/Forqueta join AFTER Muçum
DOWNSTREAM_OF_MUCUM_FAMILIES = {"7864", "7862"}

UPGS_UPSTREAM_CORE = {
    "Alto Taquari-Antas",
    "Prata",
    "Carreiro",
    "Médio Taquari-Antas",  # contains Antas/STZ/Mucum controls; mixed but needed
}
UPGS_EXCLUDED_BOTH = {"Guaporé", "Forqueta", "Baixo Taquari-Antas"}


def compact_station(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "codigo": s.get("codigo"),
        "nome": s.get("nome"),
        "tipo": s.get("tipo"),
        "upg": s.get("upg"),
        "bho6_family": s.get("bho6_family"),
        "area_drenagem_km2": s.get("area_drenagem_km2"),
        "bho6_nuareamont_km2": (s.get("bho6") or {}).get("nuareamont_km2")
        if isinstance(s.get("bho6"), dict)
        else s.get("bho6_nuareamont_km2"),
        "in_previne_seed": s.get("in_previne_seed"),
        "previne_role": s.get("previne_role"),
        "lat": s.get("lat"),
        "lon": s.get("lon"),
    }


def station_drain_area(s: dict[str, Any]) -> float | None:
    """Prefer official ANA drainage area; ignore noisy nearest-reach snap."""
    area = s.get("area_drenagem_km2")
    if area is not None:
        return float(area)
    return None


def in_stz_domain(s: dict[str, Any]) -> bool:
    """Station plausibly upstream of / at Santa Tereza."""
    code = str(s.get("codigo") or "")
    if code in {"86472600", "86472000"}:
        return True
    upg = s.get("upg")
    fam = str(s.get("bho6_family") or "")
    if upg in UPGS_EXCLUDED_BOTH or fam in DOWNSTREAM_OF_MUCUM_FAMILIES:
        return False
    area = station_drain_area(s)
    # Only exclude when ANA drainage clearly exceeds STZ nested catchment
    if area is not None and area > NESTED["86472600"]["area_km2"] + 200:
        return False
    if upg in UPGS_UPSTREAM_CORE:
        return True
    if fam in UPSTREAM_OF_MUCUM_FAMILIES or (fam.startswith("786") and fam not in DOWNSTREAM_OF_MUCUM_FAMILIES):
        return upg not in UPGS_EXCLUDED_BOTH
    return False


def in_mucum_domain(s: dict[str, Any]) -> bool:
    """Station plausibly upstream of / at Muçum (superset of STZ + STZ→Muçum strip)."""
    code = str(s.get("codigo") or "")
    if code in {"86510000", "86472600", "86472000"}:
        return True
    upg = s.get("upg")
    fam = str(s.get("bho6_family") or "")
    if upg in UPGS_EXCLUDED_BOTH or fam in DOWNSTREAM_OF_MUCUM_FAMILIES:
        return False
    area = station_drain_area(s)
    if area is not None and area > NESTED["86510000"]["area_km2"] + 300:
        return False
    if upg in UPGS_UPSTREAM_CORE:
        return True
    if fam in UPSTREAM_OF_MUCUM_FAMILIES or (fam.startswith("786") and fam not in DOWNSTREAM_OF_MUCUM_FAMILIES):
        return True
    return False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    postos = json.loads((OUT / "postos_por_upg_latest.json").read_text(encoding="utf-8"))
    pluvio = json.loads((OUT / "pluviometria_g040_latest.json").read_text(encoding="utf-8"))
    fozes = json.loads((OUT / "subbacias_e_fozes_latest.json").read_text(encoding="utf-8"))
    recorte = json.loads((OUT / "recorte_modelo_latest.json").read_text(encoding="utf-8"))

    stations = postos["stations_inside_g040"]
    stz_flu = [compact_station(s) for s in stations if in_stz_domain(s)]
    muc_flu = [compact_station(s) for s in stations if in_mucum_domain(s)]

    def rain_in_domain(domain_fn):
        # reuse flu domain logic via upg/family on rain stations
        out = []
        for s in pluvio["stations"]:
            fake = {
                "upg": s.get("upg"),
                "bho6_family": "7866"
                if s.get("upg") == "Carreiro"
                else "7868"
                if s.get("upg") == "Prata"
                else "7864"
                if s.get("upg") == "Guaporé"
                else "7862"
                if s.get("upg") == "Forqueta"
                else "786",
                "area_drenagem_km2": None,
            }
            if domain_fn(fake):
                out.append(
                    {
                        "codigo": s.get("codigo"),
                        "nome": s.get("nome"),
                        "rede": s.get("rede"),
                        "upg": s.get("upg"),
                        "in_previne_rain": s.get("in_previne_rain"),
                        "situacao": s.get("situacao"),
                    }
                )
        return out

    stz_rain = rain_in_domain(in_stz_domain)
    muc_rain = rain_in_domain(in_mucum_domain)

    stz_previne = [s for s in stz_flu if s.get("in_previne_seed")]
    muc_previne = [s for s in muc_flu if s.get("in_previne_seed")]

    decision = {
        "schema_version": "estudo_dois_modelos_stz_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": {
            "by": "Juliana",
            "statement": "Quero um modelo pra Muçum e outro pra Santa Tereza.",
            "chosen": "dois_modelos_alvo_STZ_e_Mucum",
            "not_chosen": [
                "A_corredor_mucum como um unico modelo agregado",
                "B_g040_completa",
                "C_hibrido_explicito sem alvos",
            ],
            "locked_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "status": "dominios_definidos_aguardando_estrutura",
        "discipline_rule": (
            "Dois modelos-alvo no CORREDOR Ate Muçum. Nao sao a bacia G040. "
            "Guapore/Forqueta/Baixo ficam de fora dos dois. Ainda nao calibrar HEC."
        ),
        "shared_truths": {
            "g040_km2": 26430,
            "nested_bho6_km2": NESTED,
            "excluded_from_both": {
                "upgs": sorted(UPGS_EXCLUDED_BOTH),
                "bho6_families": sorted(DOWNSTREAM_OF_MUCUM_FAMILIES),
                "reason": "Fozes a jusante hidrologica de Muçum; nao observaveis pelos alvos STZ/Mucum.",
            },
            "fozes": [
                {
                    "family": j["family_code"],
                    "label": j["label"],
                    "position": j["position_vs_controls"],
                    "in_stz_model": j["position_vs_controls"]
                    in {"upstream_or_at_antas", "between_antas_and_santa_tereza"},
                    "in_mucum_model": j["position_vs_controls"]
                    in {
                        "upstream_or_at_antas",
                        "between_antas_and_santa_tereza",
                        "between_santa_tereza_and_mucum",
                    },
                }
                for j in fozes.get("fozes_principais", [])
            ],
        },
        "models": {
            "santa_tereza": {
                "target_station": "86472600",
                "target_name": "Santa Tereza",
                "nested_area_km2": NESTED["86472600"]["area_km2"],
                "predicts": "nivel/vazao em Santa Tereza",
                "includes": {
                    "controls_upstream": ["86472000 Antas"],
                    "major_inflows": ["sistema Prata 7868", "Rio Carreiro 7866", "tronco Antas"],
                    "upgs_core": sorted(UPGS_UPSTREAM_CORE),
                },
                "excludes": sorted(UPGS_EXCLUDED_BOTH) + ["Muçum como alvo"],
                "stations_flu_count": len(stz_flu),
                "stations_flu_previne_seed": stz_previne,
                "stations_rain_count": len(stz_rain),
                "stations_rain_previne": [r for r in stz_rain if r.get("in_previne_rain")],
                "note": (
                    "Carreiro entra entre Antas e STZ — critico para o modelo STZ. "
                    "Incremento STZ→Muçum NAO faz parte deste alvo."
                ),
            },
            "mucum": {
                "target_station": "86510000",
                "target_name": "Muçum",
                "nested_area_km2": NESTED["86510000"]["area_km2"],
                "predicts": "nivel/vazao em Muçum",
                "includes": {
                    "controls_upstream": ["86472000 Antas", "86472600 Santa Tereza"],
                    "major_inflows": [
                        "tudo do dominio STZ",
                        "faixa STZ→Muçum (~190 km2 de incremento aninhado)",
                    ],
                    "upgs_core": sorted(UPGS_UPSTREAM_CORE),
                },
                "excludes": sorted(UPGS_EXCLUDED_BOTH),
                "stations_flu_count": len(muc_flu),
                "stations_flu_previne_seed": muc_previne,
                "stations_rain_count": len(muc_rain),
                "stations_rain_previne": [r for r in muc_rain if r.get("in_previne_rain")],
                "delta_vs_stz_km2": round(
                    NESTED["86510000"]["area_km2"] - NESTED["86472600"]["area_km2"], 3
                ),
                "note": (
                    "Dominio quase igual ao STZ (+~190 km2). Guapore continua FORA "
                    "(foz ~+2495 km2 apos Muçum)."
                ),
            },
        },
        "relationship": {
            "mucum_contains_stz_upstream": True,
            "independent_calibrations": True,
            "shared_forcing_possible": (
                "Chuva/niveis de montante (Antas, Prata, Carreiro) podem alimentar os dois, "
                "mas cada modelo tem alvo e funcao objetivo proprios."
            ),
            "labeling_rule": (
                "Chamar de 'modelo Santa Tereza' e 'modelo Muçum' — nunca 'modelo da bacia Taquari-Antas'."
            ),
        },
        "next_steps": [
            "Congelar lista curta de forçantes por modelo (quais postos flu/plu entram em cada um).",
            "So depois desenhar estrutura HEC (ou manter RNA) alinhada a cada alvo.",
            "Nao misturar Guapore/Forqueta nestes dois modelos sem mudar o recorte.",
        ],
        "artifacts": {
            "json": "dois_modelos_stz_mucum_latest.json",
            "html": "dois_modelos_stz_mucum.html",
        },
    }

    # attach station lists (compact) for audit
    decision["models"]["santa_tereza"]["stations_flu"] = stz_flu
    decision["models"]["mucum"]["stations_flu"] = muc_flu
    decision["models"]["santa_tereza"]["stations_rain"] = stz_rain
    decision["models"]["mucum"]["stations_rain"] = muc_rain

    (OUT / "dois_modelos_stz_mucum_latest.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # update recorte status
    recorte["status"] = "decidido_dois_alvos_STZ_Mucum"
    recorte["human_decision"] = decision["decision"]
    recorte["superseded_options_note"] = (
        "Juliana nao escolheu A/B/C literalmente: pediu um modelo para Muçum e outro para Santa Tereza. "
        "Isso e um recorte de CORREDOR com dois alvos — nao G040 completa."
    )
    recorte["updated_at_utc"] = decision["generated_at_utc"]
    (OUT / "recorte_modelo_latest.json").write_text(
        json.dumps(recorte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    write_html(decision)
    merge_estudo(decision)
    print(
        json.dumps(
            {
                "ok": True,
                "stz_flu": len(stz_flu),
                "muc_flu": len(muc_flu),
                "stz_rain": len(stz_rain),
                "muc_rain": len(muc_rain),
                "stz_previne": [s["codigo"] for s in stz_previne],
                "muc_previne": [s["codigo"] for s in muc_previne],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_html(d: dict[str, Any]) -> None:
    stz = d["models"]["santa_tereza"]
    muc = d["models"]["mucum"]

    def seed_rows(seeds: list[dict]) -> str:
        return "".join(
            f"<tr><td>{s['codigo']}</td><td>{s.get('nome') or ''}</td>"
            f"<td>{s.get('upg') or ''}</td><td>{s.get('bho6_family') or ''}</td></tr>"
            for s in seeds
        )

    foz_rows = "".join(
        "<tr>"
        f"<td>{f['family']}</td><td>{f['label']}</td><td>{f['position']}</td>"
        f"<td>{'sim' if f['in_stz_model'] else 'nao'}</td>"
        f"<td>{'sim' if f['in_mucum_model'] else 'nao'}</td>"
        "</tr>"
        for f in d["shared_truths"]["fozes"]
    )
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dois modelos · Santa Tereza e Muçum</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --bad:#a33b35; --ok:#1b7a4a; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1100px; margin:auto; padding:28px 16px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,42px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--ok); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .ok {{ border-left-color:var(--ok); background:#eefaf3; color:#145c38; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
    .card {{ border:1px solid var(--line); border-radius:14px; padding:14px; background:#f7fcfc; }}
    .card strong.stat {{ display:block; font-size:28px; color:var(--accent); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:7px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Decisao registrada · Juliana</div>
    <h1>Um modelo para Santa Tereza. Outro para Muçum.</h1>
    <p class="muted">{d['generated_at_utc']}</p>
    <div class="notice ok"><strong>Escolha:</strong> {d['decision']['statement']}</div>
    <div class="notice bad"><strong>Rotulo honesto:</strong> {d['relationship']['labeling_rule']} Guapore/Forqueta/Baixo ficam fora dos dois.</div>
  </header>

  <section>
    <div class="grid">
      <div class="card">
        <h2>Modelo Santa Tereza</h2>
        <strong class="stat">{stz['nested_area_km2']:,.0f} km²</strong>
        <p>Alvo <code>{stz['target_station']}</code> · {stz['stations_flu_count']} flu · {stz['stations_rain_count']} chuva</p>
        <p>{stz['note']}</p>
        <p class="muted">Entra: Prata + Carreiro + tronco Antas. Nao entra: faixa STZ→Muçum, Guapore, Forqueta, Baixo.</p>
      </div>
      <div class="card">
        <h2>Modelo Muçum</h2>
        <strong class="stat">{muc['nested_area_km2']:,.0f} km²</strong>
        <p>Alvo <code>{muc['target_station']}</code> · {muc['stations_flu_count']} flu · {muc['stations_rain_count']} chuva</p>
        <p>{muc['note']}</p>
        <p class="muted">Inclui dominio STZ + ~{muc['delta_vs_stz_km2']} km² ate Muçum. Guapore ainda fora.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>Fozes principais vs os dois alvos</h2>
    <table>
      <thead><tr><th>Fam</th><th>Sistema</th><th>Posicao</th><th>No modelo STZ?</th><th>No modelo Mucum?</th></tr></thead>
      <tbody>{foz_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Seeds PREVINE no dominio STZ</h2>
    <table><thead><tr><th>Codigo</th><th>Nome</th><th>UPG</th><th>BHO6</th></tr></thead>
    <tbody>{seed_rows(stz['stations_flu_previne_seed'])}</tbody></table>
  </section>

  <section>
    <h2>Seeds PREVINE no dominio Muçum</h2>
    <table><thead><tr><th>Codigo</th><th>Nome</th><th>UPG</th><th>BHO6</th></tr></thead>
    <tbody>{seed_rows(muc['stations_flu_previne_seed'])}</tbody></table>
  </section>

  <section>
    <h2>Proximos passos (ainda disciplina)</h2>
    <ul>{''.join(f'<li>{x}</li>' for x in d['next_steps'])}</ul>
    <p><a href="dois_modelos_stz_mucum_latest.json">JSON</a> ·
       <a href="recorte_modelo.html">briefing A/B/C (supersedido)</a> ·
       <a href="index.html">estudo-base</a></p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "dois_modelos_stz_mucum.html").write_text(html, encoding="utf-8")


def merge_estudo(decision: dict[str, Any]) -> None:
    path = OUT / "estudo_bacia_latest.json"
    if not path.exists():
        return
    prev = json.loads(path.read_text(encoding="utf-8"))
    prev["recorte_modelo"] = {
        "status": "decidido_dois_alvos_STZ_Mucum",
        "decision": decision["decision"],
        "artifacts": decision["artifacts"],
        "updated_at_utc": decision["generated_at_utc"],
    }
    prev["dois_modelos_stz_mucum"] = {
        "status": decision["status"],
        "stz_km2": decision["models"]["santa_tereza"]["nested_area_km2"],
        "mucum_km2": decision["models"]["mucum"]["nested_area_km2"],
        "excluded": decision["shared_truths"]["excluded_from_both"],
        "artifacts": decision["artifacts"],
    }
    known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
    for item in [
        "Decisao Juliana: um modelo para Santa Tereza e outro para Muçum (corredor, nao G040).",
        "Guapore/Forqueta/Baixo excluidos dos dois modelos-alvo.",
        f"STZ nested ~{decision['models']['santa_tereza']['nested_area_km2']} km2; Mucum nested ~{decision['models']['mucum']['nested_area_km2']} km2.",
    ]:
        if item not in known:
            known.append(item)
    prev["next_study_steps_only"] = decision["next_steps"]
    path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    idx = OUT / "index.html"
    if idx.exists():
        html = idx.read_text(encoding="utf-8")
        if "dois_modelos_stz_mucum.html" not in html:
            html = html.replace(
                '<a href="recorte_modelo.html">recorte de modelo (decisao)</a></p>',
                '<a href="recorte_modelo.html">recorte A/B/C</a> ·\n'
                '       <a href="dois_modelos_stz_mucum.html">dois modelos STZ+Muçum (decidido)</a></p>',
            )
        block = """  <section>
    <h2>Decisao: dois modelos-alvo</h2>
    <div class="notice" style="border-left-color:#1b7a4a;background:#eefaf3;color:#145c38"><strong>Juliana:</strong> um modelo para Santa Tereza e outro para Muçum.
    Dominios no corredor (nao G040). Guapore/Forqueta fora. Ver <a href="dois_modelos_stz_mucum.html">dois_modelos_stz_mucum.html</a>.</div>
  </section>

"""
        if "Decisao: dois modelos-alvo" not in html:
            html = html.replace(
                "  <section>\n    <h2>Recorte de modelo",
                block + "  <section>\n    <h2>Recorte de modelo",
            )
        from html import escape
        import re

        steps = "".join(f"<li>{escape(x)}</li>" for x in decision["next_steps"])
        html = re.sub(
            r"(<h2>Proximos passos de ESTUDO \(sem HEC\)</h2>\s*<ul>)(.*?)(</ul>)",
            r"\1" + steps + r"\3",
            html,
            flags=re.S,
        )
        idx.write_text(html)


if __name__ == "__main__":
    main()
