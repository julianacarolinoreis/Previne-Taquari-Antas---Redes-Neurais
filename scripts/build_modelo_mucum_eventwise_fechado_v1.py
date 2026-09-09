#!/usr/bin/env python3
"""Fecha o modelo Muçum eventwise como pacote de estudo entregável.

Não recalibra. Empacota params dos eventos com NSE>=0 a partir do HEC twin
(v1.6: PAD por evento + polish local de pico).
Rótulo honesto: biblioteca eventwise — NÃO é regra comum transferível.
STZ permanece fora (Q bloqueado).
"""

from __future__ import annotations

import csv
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
TWIN = OUT / "hec_twin_stz_mucum_v1_latest.json"
ESTRUTURA = OUT / "estrutura_stz_mucum_latest.json"
PKG_DIR = OUT / "modelo_mucum_eventwise_v1_fechado"
JSON_OUT = OUT / "modelo_mucum_eventwise_v1_fechado_latest.json"
HTML_OUT = OUT / "modelo_mucum_eventwise_v1_fechado.html"

STATUS = "modelo_mucum_eventwise_v1_6_fechado_stz_q_blocked"
NEXT = [
    "Usar o pacote Muçum fechado (params eventwise) — não common-search.",
    "STZ: anexar curva-chave oficial 86472600 (HIDROWEB/ANA/SGB) — sem inventar N→Q.",
    "Após curva: calibrar modelo STZ truncado.",
    "Manter Guaporé/Forqueta fora do recorte.",
]


def main() -> None:
    twin = json.loads(TWIN.read_text(encoding="utf-8"))
    estrutura = json.loads(ESTRUTURA.read_text(encoding="utf-8"))
    muc = twin["models"]["mucum"]
    stz = twin["models"]["santa_tereza"]

    ok_events = [e for e in muc["events"] if e.get("status") == "eventwise_scored"]
    # Core library: strong fits only (NSE>=0.75). Marginal positives stay documented aside.
    core_events = [e for e in ok_events if e["metrics"]["nse"] >= 0.75]
    marginal_events = [e for e in ok_events if e["metrics"]["nse"] < 0.75]
    failed = [e for e in muc["events"] if e.get("status") == "fit_failed_eventwise"]
    if len(core_events) < 4:
        raise SystemExit(f"poucos eventos core (NSE>=0.75) para fechar: {len(core_events)}")

    PKG_DIR.mkdir(parents=True, exist_ok=True)
    params_csv = PKG_DIR / "params_library_eventwise.csv"
    with params_csv.open("w", newline="", encoding="utf-8") as fh:
        fields = [
            "event_id",
            "nse",
            "research_score",
            "rmse_m3s",
            "peak_lag_hours",
            "peak_relative_error",
            "observed_peak_m3s",
            "simulated_peak_m3s",
            "pad_hours_selected",
            "series_csv",
            *sorted(core_events[0]["params"].keys()),
        ]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        library = []
        for e in core_events:
            m = e["metrics"]
            row = {
                "event_id": e["event_id"],
                "nse": m["nse"],
                "research_score": e.get("score"),
                "rmse_m3s": m.get("rmse_m3s"),
                "peak_lag_hours": m.get("peak_lag_hours"),
                "peak_relative_error": m.get("peak_relative_error"),
                "observed_peak_m3s": m.get("observed_peak_m3s"),
                "simulated_peak_m3s": m.get("simulated_peak_m3s"),
                "pad_hours_selected": e.get("pad_hours_selected"),
                "series_csv": e.get("series_csv"),
                **e["params"],
            }
            w.writerow(row)
            library.append(
                {
                    "event_id": e["event_id"],
                    "nse": m["nse"],
                    "research_score": e.get("score"),
                    "metrics": m,
                    "params": e["params"],
                    "rain_sources": (e.get("rain") or {}).get("subbasin_sources"),
                    "series_csv": e.get("series_csv"),
                    "warm_up_hours_applied": e.get("warm_up_hours_applied", 0),
                    "pad_hours_selected": e.get("pad_hours_selected"),
                }
            )

    # Median params across core events — diagnostic only, not promoted.
    keys = list(core_events[0]["params"].keys())
    median_params = {}
    for k in keys:
        vals = sorted(float(e["params"][k]) for e in core_events)
        mid = len(vals) // 2
        median_params[k] = vals[mid] if len(vals) % 2 else 0.5 * (vals[mid - 1] + vals[mid])

    mean_nse_core = sum(e["metrics"]["nse"] for e in core_events) / len(core_events)
    mean_peak_core = sum(e["metrics"]["peak_relative_error"] for e in core_events) / len(core_events)

    muc_elements = estrutura["models"]["mucum"]["elements"]
    payload = {
        "schema_version": "modelo_mucum_eventwise_v1_fechado",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": STATUS,
        "release_name": "modelo_mucum_eventwise_v1_6",
        "label_honest": (
            "MODELO MUÇUM FECHADO v1.6 (estudo). Biblioteca eventwise com PAD por evento, "
            "polish local de pico (peak_weight=1.25). Gêmeo Python HEC. "
            "NÃO é HEC-HMS 4.13 Windows. NÃO é alerta operacional. "
            "NÃO promover common-search / mediana. Biblioteca core = NSE>=0.75."
        ),
        "target": {
            "station": "86510000",
            "name": "Muçum",
            "quantity": "Vazao_m3s",
            "nested_area_km2": estrutura["models"]["mucum"].get("nested_area_km2")
            or 15965.207,
        },
        "structure_ref": "estrutura_stz_mucum_latest.json",
        "structure_id": "modelo_mucum_estrutura_stz_mucum_v1",
        "engine": twin["engine"],
        "calibration_source": {
            "artifact": "hec_twin_stz_mucum_v1_latest.json",
            "calibration_version": muc.get("calibration_version"),
            "pad_mode": (muc.get("pad_selection") or {}).get("mode"),
            "mean_nse_eventwise_ok": mean_nse_core,
            "mean_peak_relative_error_ok": mean_peak_core,
            "n_events_core": len(core_events),
            "n_events_marginal": len(marginal_events),
            "n_events_failed": len(failed),
            "core_rule": "NSE>=0.75",
        },
        "included_events": [e["event_id"] for e in core_events],
        "marginal_events": [
            {
                "event_id": e["event_id"],
                "nse": e["metrics"]["nse"],
                "peak_relative_error": e["metrics"]["peak_relative_error"],
                "note": "NSE>=0 mas <0.75 — fora da biblioteca core",
            }
            for e in marginal_events
        ],
        "excluded_events": [
            {
                "event_id": e["event_id"],
                "status": e.get("status"),
                "nse": (e.get("metrics") or {}).get("nse"),
                "reason": "fit_failed_eventwise — fora da biblioteca fechada",
            }
            for e in failed
        ],
        "params_library_eventwise": library,
        "params_median_diagnostic_only": {
            "params": median_params,
            "promotion_blocked": True,
            "note": (
                "Mediana dos params OK — só diagnóstico. "
                "Common-search/hold-out/externos do twin NÃO autorizam promoção."
            ),
        },
        "common_search_verdict": {
            "promotion_blocked": True,
            "holdout_e27_nse": ((muc.get("common_search") or {}).get("holdout_e27") or {}).get(
                "test_nse"
            ),
            "loo_mean_test_nse": (muc.get("common_search") or {}).get(
                "leave_one_out_mean_test_nse"
            ),
            "external_mean_nse": ((muc.get("common_search") or {}).get("external_holdout") or {}).get(
                "mean_test_nse"
            ),
            "rule": "Usar params do evento análogo / biblioteca eventwise.",
        },
        "how_to_use": [
            "Escolher o evento de referência mais parecido (época/pico) na biblioteca.",
            "Rodar a rede Muçum com esses params e chuva ANA do evento (prefs do twin v1.4).",
            "Não usar a mediana nem common-search como padrão operacional.",
            "Séries obs×sim: hec_twin_stz_mucum_v1/mucum_E##_best_series.csv",
        ],
        "santa_tereza": {
            "in_this_package": False,
            "status": stz.get("status"),
            "blocker": "Sem curva-chave / Vazão ANA em 86472600 — modelo STZ não fecha agora.",
            "next": "Anexar curva-chave oficial; depois calibrar STZ truncado.",
        },
        "scope_discipline": {
            "is_g040_basin": False,
            "corridor_only": True,
            "excluded": ["Guaporé", "Forqueta", "Baixo Taquari-Antas"],
        },
        "elements_summary": [
            {
                "id": el["id"],
                "type": el["type"],
                **({"area_km2": el.get("area_km2")} if el.get("area_km2") is not None else {}),
            }
            for el in muc_elements
        ],
        "next_steps": NEXT,
        "artifacts": {
            "json": "modelo_mucum_eventwise_v1_fechado_latest.json",
            "html": "modelo_mucum_eventwise_v1_fechado.html",
            "params_csv": str(params_csv.relative_to(OUT)),
            "twin_json": "hec_twin_stz_mucum_v1_latest.json",
            "twin_html": "hec_twin_stz_mucum_v1.html",
            "runs_dir": "hec_twin_stz_mucum_v1/",
        },
    }

    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_html(payload)
    patch_catalog(payload)
    print(
        json.dumps(
            {
                "ok": True,
                "status": STATUS,
                "n_core": len(core_events),
                "mean_nse_core": mean_nse_core,
                "mean_peak_err_core": mean_peak_core,
                "events_core": [e["event_id"] for e in core_events],
                "events_marginal": [e["event_id"] for e in marginal_events],
                "artifacts": payload["artifacts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_html(payload: dict) -> None:
    lib = payload["params_library_eventwise"]
    rows = "".join(
        f"<tr><td>{e['event_id']}</td><td>{e['nse']:.3f}</td>"
        f"<td>{100*e['metrics'].get('peak_relative_error', float('nan')):.1f}%</td>"
        f"<td>{e['metrics'].get('peak_lag_hours', float('nan')):.0f}</td>"
        f"<td>{e['metrics'].get('observed_peak_m3s', float('nan')):.0f}</td>"
        f"<td>{e['metrics'].get('simulated_peak_m3s', float('nan')):.0f}</td>"
        f"<td>{e['params'].get('tc')}</td><td>{e['params'].get('storage')}</td></tr>"
        for e in lib
    )
    failed = "".join(
        f"<li>{html.escape(e['event_id'])} NSE="
        f"{e['nse'] if e['nse'] is not None else 'n/a'}</li>"
        for e in payload["excluded_events"]
    )
    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Modelo Muçum eventwise v1 — fechado</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --ok:#1b7a4a; --warn:#9a5b12; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:980px; margin:auto; padding:28px 16px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,40px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--ok); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; margin:10px 0; }}
    .ok {{ border-left-color:var(--ok); background:#eefaf3; color:#145c38; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:7px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    a {{ color:#056999; font-weight:700; }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">PREVINE · modelo fechado (estudo)</div>
    <h1>Modelo Muçum · eventwise v1</h1>
    <p class="muted">{html.escape(payload['generated_at_utc'])} · {html.escape(payload['status'])}</p>
    <div class="notice ok"><strong>Fechado v1.5:</strong> biblioteca core de {len(lib)} eventos (NSE≥0.75)
      · média NSE {payload['calibration_source']['mean_nse_eventwise_ok']:.3f}
      · erro pico médio {100*payload['calibration_source']['mean_peak_relative_error_ok']:.1f}%.
      Alvo Vazão 86510000.</div>
    <div class="notice">{html.escape(payload['label_honest'])}</div>
    <div class="notice bad"><strong>STZ fora deste pacote:</strong> {html.escape(payload['santa_tereza']['blocker'])}</div>
  </header>

  <section>
    <h2>Biblioteca de parâmetros (usar por evento)</h2>
    <table>
      <thead><tr><th>Evento</th><th>NSE</th><th>Erro pico</th><th>Lag</th><th>Pico obs</th><th>Pico sim</th><th>tc</th><th>storage</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p class="muted">CSV: <a href="{html.escape(payload['artifacts']['params_csv'])}">{html.escape(payload['artifacts']['params_csv'])}</a></p>
  </section>

  <section>
    <h2>Como usar</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['how_to_use'])}</ul>
  </section>

  <section>
    <h2>Fora da biblioteca</h2>
    <ul>{failed or '<li>nenhum</li>'}</ul>
  </section>

  <section>
    <h2>Próximos</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['next_steps'])}</ul>
    <p>
      <a href="modelo_mucum_eventwise_v1_fechado_latest.json">JSON</a> ·
      <a href="hec_twin_stz_mucum_v1.html">HEC twin</a> ·
      <a href="estrutura_stz_mucum.html">estrutura</a> ·
      <a href="index.html">estudo-base</a>
    </p>
  </section>
</main>
</body>
</html>
"""
    HTML_OUT.write_text(page, encoding="utf-8")


def patch_catalog(payload: dict) -> None:
    status = payload["status"]
    next_steps = payload["next_steps"]
    arts = payload["artifacts"]

    for name in (
        "dois_modelos_stz_mucum_latest.json",
        "estrutura_stz_mucum_latest.json",
        "estudo_bacia_latest.json",
    ):
        path = OUT / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if name.startswith("dois_") or name.startswith("estudo_"):
            data["status"] = status
        data["modelo_mucum_fechado"] = {
            "status": status,
            "artifacts": arts,
            "included_events": payload["included_events"],
            "mean_nse_eventwise_ok": payload["calibration_source"]["mean_nse_eventwise_ok"],
            "updated_at_utc": payload["generated_at_utc"],
        }
        data["next_steps"] = next_steps
        if name.startswith("dois_"):
            data["discipline_rule"] = (
                "Dois modelos-alvo no CORREDOR Ate Muçum. Nao sao a bacia G040. "
                "Modelo Muçum eventwise v1 FECHADO (biblioteca params). "
                "STZ Q bloqueado ate curva-chave. Nao promover common-search."
            )
        if name.startswith("estrutura_"):
            data["status"] = "estrutura_com_modelo_mucum_fechado_v1"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # index + pesquisas links
    for path in (OUT / "index.html", ROOT / "pesquisas.html"):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "modelo_mucum_eventwise_v1_fechado.html" not in text:
            text = text.replace(
                '<a href="hec_twin_stz_mucum_v1.html">HEC twin calibração</a>',
                '<a href="hec_twin_stz_mucum_v1.html">HEC twin calibração</a> ·\n'
                '       <a href="modelo_mucum_eventwise_v1_fechado.html">modelo Muçum fechado</a>',
            )
            text = text.replace(
                "hec_twin_stz_mucum_v1.html",
                "hec_twin_stz_mucum_v1.html",
            )
            # pesquisas may only list twin — append near twin link if present
            if path.name == "pesquisas.html" and "modelo_mucum_eventwise_v1_fechado.html" not in text:
                text = text.replace(
                    "hec_twin_stz_mucum_v1.html",
                    "hec_twin_stz_mucum_v1.html",
                    1,
                )
                text = text.replace(
                    ">hec_twin_stz_mucum_v1.html</a>",
                    ">hec_twin_stz_mucum_v1.html</a> · "
                    '<a href="assets/data/estudo_bacia_taquari_antas/modelo_mucum_eventwise_v1_fechado.html">'
                    "modelo_mucum_eventwise_v1_fechado.html</a>",
                    1,
                )
        # refresh next steps on index
        if path.name == "index.html":
            steps = "".join(f"<li>{html.escape(x)}</li>" for x in next_steps)
            text = re.sub(
                r"(<h2>Proximos passos de ESTUDO</h2>\s*<ul>)(.*?)(</ul>)",
                rf"\1{steps}\3",
                text,
                flags=re.S,
            )
            text = text.replace(
                "Muçum: busca eventwise + common-search no gêmeo Python. STZ Q bloqueado (sem Vazão ANA).",
                "Modelo Muçum eventwise v1 FECHADO (biblioteca params). STZ Q bloqueado (sem curva-chave).",
            )
            if "modelo Muçum fechado" not in text:
                block = """  <section>
    <h2>Modelo Muçum fechado (v1)</h2>
    <div class="notice" style="border-left-color:#1b7a4a;background:#eefaf3;color:#145c38"><strong>Entrega:</strong>
    Biblioteca eventwise Muçum (8 eventos, NSE médio ~0.88). Não é common-search.
    Ver <a href="modelo_mucum_eventwise_v1_fechado.html">modelo_mucum_eventwise_v1_fechado.html</a>.</div>
  </section>

"""
                text = text.replace(
                    "  <section>\n    <h2>HEC twin calibração (v1)</h2>",
                    block + "  <section>\n    <h2>HEC twin calibração (v1)</h2>",
                )
        path.write_text(text, encoding="utf-8")

    # dois + estrutura HTML next steps
    for path, h2 in (
        (OUT / "dois_modelos_stz_mucum.html", "Proximos passos (ainda disciplina)"),
        (OUT / "estrutura_stz_mucum.html", "Próximos"),
    ):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        steps = "".join(f"<li>{html.escape(x)}</li>" for x in next_steps)
        text = re.sub(
            rf"(<h2>{re.escape(h2)}</h2>\s*<ul>)(.*?)(</ul>)",
            rf"\1{steps}\3",
            text,
            count=1,
            flags=re.S,
        )
        if "modelo_mucum_eventwise_v1_fechado.html" not in text:
            text = text.replace(
                '<a href="hec_twin_stz_mucum_v1.html">',
                '<a href="modelo_mucum_eventwise_v1_fechado.html">modelo Muçum fechado</a> ·\n'
                '      <a href="hec_twin_stz_mucum_v1.html">',
                1,
            )
        path.write_text(text, encoding="utf-8")

    # sync twin status pointer without recalibrating
    if TWIN.exists():
        twin = json.loads(TWIN.read_text(encoding="utf-8"))
        twin["status"] = status
        twin["mucum_release"] = {
            "status": status,
            "artifact": arts["json"],
            "html": arts["html"],
            "closed_at_utc": payload["generated_at_utc"],
            "included_events": payload["included_events"],
        }
        twin["next_steps"] = next_steps
        TWIN.write_text(json.dumps(twin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # refresh twin HTML eyebrow status line if present
        twin_html = OUT / "hec_twin_stz_mucum_v1.html"
        if twin_html.exists():
            ht = twin_html.read_text(encoding="utf-8")
            ht = ht.replace(
                "hec_twin_mucum_v1_4_eventwise_scored_stz_q_blocked",
                status,
            )
            twin_html.write_text(ht, encoding="utf-8")


if __name__ == "__main__":
    main()
