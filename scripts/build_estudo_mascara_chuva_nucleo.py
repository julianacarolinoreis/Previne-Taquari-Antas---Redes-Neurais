#!/usr/bin/env python3
"""Build hourly rain mask table for STZ/Muçum RNA core (v1).

Applies contrato RNA+máscara rules to assets/data/chuvas_horarias.csv.
Does NOT impute zeros, train models, or calibrate HEC.
Level masks are declared but not filled (no multi-station nivel CSV in-repo).
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
RAIN_CSV = ROOT / "assets" / "data" / "chuvas_horarias.csv"
CONTRACT = OUT / "contrato_rna_mascara_stz_mucum_latest.json"

RAIN_CORE = [
    ("chuva_86472000", "chuva_86472000"),
    ("chuva_86472600", "chuva_86472600"),
    ("chuva_02851072", "chuva_02851072"),
]
# Explicitly NOT written as core (R4)
RAIN_EXCLUDED = ["chuva_inmet_A894", "chuva_cemaden_4320404010A", "chuva_02851044"]


def present(val: str | None) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return s not in ("", "None", "nan", "NaN")


def parse_ts(row: dict) -> datetime:
    return datetime(int(row["ANO"]), int(row["MES"]), int(row["DIA"]), int(row["HORA"]))


def ts_label(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:00")


def build() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    window_start_s = contract["models"]["santa_tereza"]["train_window_hint"]["rain_csv_overlap_start"]
    # "2023-10-01 00:00"
    window_start = datetime.strptime(window_start_s[:16], "%Y-%m-%d %H:%M")

    out_csv = OUT / "mascara_chuva_nucleo_horaria.csv"
    with RAIN_CSV.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    fieldnames = [
        "timestamp_local",
        "COD_SEQUENCIAL",
        "in_overlap_window_r6",
        *[name for name, _ in RAIN_CORE],
        *[f"mask_{name}" for name, _ in RAIN_CORE],
        "core_rain_complete",
        "usable_stz_rain_v1",
        "usable_mucum_rain_v1",
    ]

    n = len(rows)
    n_complete = 0
    n_usable = 0
    n_in_window = 0
    per_mask = {name: 0 for name, _ in RAIN_CORE}
    first_usable = None
    last_usable = None

    with out_csv.open("w", newline="", encoding="utf-8") as out_fh:
        w = csv.DictWriter(out_fh, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            dt = parse_ts(row)
            in_window = 1 if dt >= window_start else 0
            if in_window:
                n_in_window += 1
            rec = {
                "timestamp_local": ts_label(dt),
                "COD_SEQUENCIAL": row["COD_SEQUENCIAL"],
                "in_overlap_window_r6": in_window,
            }
            masks = []
            for name, col in RAIN_CORE:
                raw = row.get(col, "")
                ok = present(raw)
                # R1: keep empty as empty — do NOT write 0 for missing
                rec[name] = raw.strip() if ok else ""
                rec[f"mask_{name}"] = 1 if ok else 0
                if ok:
                    per_mask[name] += 1
                masks.append(ok)
            core_ok = all(masks)
            usable = 1 if (core_ok and in_window) else 0
            rec["core_rain_complete"] = 1 if core_ok else 0
            rec["usable_stz_rain_v1"] = usable
            rec["usable_mucum_rain_v1"] = usable  # same rain core
            if core_ok:
                n_complete += 1
            if usable:
                n_usable += 1
                if first_usable is None:
                    first_usable = ts_label(dt)
                last_usable = ts_label(dt)
            w.writerow(rec)

    # monthly usable after window
    monthly = {}
    with out_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["in_overlap_window_r6"] != "1":
                continue
            ym = row["timestamp_local"][:7]
            m = monthly.setdefault(ym, {"hours": 0, "usable": 0})
            m["hours"] += 1
            if row["usable_stz_rain_v1"] == "1":
                m["usable"] += 1

    monthly_out = [
        {
            "ym": ym,
            "hours": v["hours"],
            "usable": v["usable"],
            "pct_usable": round(100.0 * v["usable"] / v["hours"], 1) if v["hours"] else 0.0,
        }
        for ym, v in sorted(monthly.items())
    ]

    payload = {
        "schema_version": "estudo_mascara_chuva_nucleo_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "tabela horaria de mascara do nucleo de chuva STZ/Mucum; nao e treino",
        "status": "mascara_chuva_nucleo_gerada_v1",
        "discipline_rule": (
            "Valores ausentes ficam vazios (nao viram 0). "
            "mask_*=1 so quando observado. usable_*=1 exige nucleo completo + janela R6."
        ),
        "parent_contract": "contrato_rna_mascara_stz_mucum_latest.json",
        "source_csv": str(RAIN_CSV.relative_to(ROOT)),
        "output_csv": str(out_csv.relative_to(ROOT)),
        "core_rain_columns": [name for name, _ in RAIN_CORE],
        "excluded_columns_r4": RAIN_EXCLUDED,
        "level_masks": {
            "status": "nao_geradas_neste_passo",
            "reason": (
                "Nao ha CSV multiestacao de nivel historico no repo cobrindo "
                "86472000/86507000/86125500/86472600/86510000 na mesma grade. "
                "Proximo: alinhar ANA/Excel e emitir mask_nivel_*."
            ),
            "schema_reserved": [
                "nivel_86472000",
                "mask_nivel_86472000",
                "nivel_86507000",
                "mask_nivel_86507000",
                "nivel_86125500",
                "mask_nivel_86125500",
                "nivel_86472600",
                "mask_nivel_86472600",
                "nivel_86510000",
                "mask_nivel_86510000",
            ],
        },
        "window_r6": {
            "start": window_start_s,
            "hours_in_window": n_in_window,
        },
        "counts": {
            "rows_total": n,
            "core_rain_complete_any_time": n_complete,
            "usable_after_r6": n_usable,
            "pct_usable_of_window": round(100.0 * n_usable / n_in_window, 1) if n_in_window else 0.0,
            "pct_usable_of_all_rows": round(100.0 * n_usable / n, 1) if n else 0.0,
            "per_feature_present": per_mask,
            "first_usable": first_usable,
            "last_usable": last_usable,
        },
        "monthly_usable_in_window": monthly_out,
        "rules_applied": ["R1", "R2", "R3_rain_core", "R4", "R6"],
        "not_done": [
            "mascara de nivel",
            "aplicacao de lags",
            "treino RNA",
            "NSE",
            "calibracao HEC",
        ],
        "next_steps": [
            "Gerar máscaras de nível na mesma grade horária (ANA/Excel).",
            "Montar tensor de treino só com usable_*=1 + lags do contrato.",
            "Experimento RNA controlado por alvo — ainda pesquisa, sem promover operacional.",
        ],
        "artifacts": {
            "csv": "mascara_chuva_nucleo_horaria.csv",
            "json": "mascara_chuva_nucleo_latest.json",
            "html": "mascara_chuva_nucleo.html",
        },
    }
    return payload


def write_html(payload: dict) -> None:
    months = "".join(
        f"<tr><td>{html.escape(m['ym'])}</td><td>{m['hours']}</td>"
        f"<td>{m['usable']}</td><td>{m['pct_usable']}%</td></tr>"
        for m in payload["monthly_usable_in_window"][-18:]  # last 18 months for readability
    )
    c = payload["counts"]
    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Máscara de chuva do núcleo · STZ/Muçum</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --ok:#1b7a4a; --warn:#9a5b12; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1000px; margin:auto; padding:28px 16px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,40px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--ok); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; margin:10px 0; }}
    .ok {{ border-left-color:var(--ok); background:#eefaf3; color:#145c38; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:22px; color:var(--ok); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:7px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid {{ grid-template-columns:1fr 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · máscara chuva v1</div>
    <h1>Tabela horária — buraco continua buraco</h1>
    <p class="muted">{html.escape(payload['generated_at_utc'])} · {html.escape(payload['status'])}</p>
    <div class="notice ok"><strong>Disciplina:</strong> {html.escape(payload['discipline_rule'])}</div>
    <div class="notice bad"><strong>Nível:</strong> {html.escape(payload['level_masks']['reason'])}</div>
  </header>

  <section>
    <div class="grid">
      <div class="stat"><strong>{c['rows_total']:,}</strong><span>horas no CSV</span></div>
      <div class="stat"><strong>{payload['window_r6']['hours_in_window']:,}</strong><span>horas na janela R6</span></div>
      <div class="stat"><strong>{c['usable_after_r6']:,}</strong><span>usable chuva (núcleo+R6)</span></div>
      <div class="stat"><strong>{c['pct_usable_of_window']}%</strong><span>da janela R6</span></div>
    </div>
    <p class="muted">1º usable: {html.escape(str(c['first_usable']))} · último: {html.escape(str(c['last_usable']))}</p>
    <p class="muted">Arquivo: <a href="mascara_chuva_nucleo_horaria.csv">mascara_chuva_nucleo_horaria.csv</a></p>
  </section>

  <section>
    <h2>Presentes por feature (todas as horas)</h2>
    <ul>
      {''.join(f"<li><code>{html.escape(k)}</code>: {v:,}</li>" for k,v in c['per_feature_present'].items())}
    </ul>
    <h2>Usable mensal (janela R6 · últimos meses)</h2>
    <table>
      <thead><tr><th>Mês</th><th>Horas</th><th>Usable</th><th>%</th></tr></thead>
      <tbody>{months}</tbody>
    </table>
  </section>

  <section>
    <h2>Não feito</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['not_done'])}</ul>
    <h2>Próximos</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['next_steps'])}</ul>
    <p>
      <a href="mascara_chuva_nucleo_latest.json">JSON</a> ·
      <a href="contrato_rna_mascara_stz_mucum.html">contrato</a> ·
      <a href="series_forcantes_stz_mucum.html">séries</a> ·
      <a href="index.html">estudo-base</a>
    </p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "mascara_chuva_nucleo.html").write_text(page, encoding="utf-8")


def merge(payload: dict) -> None:
    path = OUT / "estudo_bacia_latest.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["mascara_chuva_nucleo"] = {
            "status": payload["status"],
            "artifacts": payload["artifacts"],
            "usable_after_r6": payload["counts"]["usable_after_r6"],
            "pct_usable_of_window": payload["counts"]["pct_usable_of_window"],
            "updated_at_utc": payload["generated_at_utc"],
        }
        prev["next_study_steps_only"] = payload["next_steps"]
        known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
        for item in [
            "Máscara horária de chuva do núcleo gerada (usable só com 3 chuvas + janela R6).",
            "Máscaras de nível ainda não geradas (falta CSV multiestacao local).",
        ]:
            if item not in known:
                known.append(item)
        path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name in ("contrato_rna_mascara_stz_mucum_latest.json", "dois_modelos_stz_mucum_latest.json"):
        p = OUT / name
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        data["mascara_chuva_artifact"] = payload["artifacts"]
        data["next_steps"] = payload["next_steps"]
        if name.startswith("dois_"):
            data["status"] = "mascara_chuva_pronta_aguardando_mascara_nivel"
        if name.startswith("contrato_"):
            data["status"] = "contrato_com_mascara_chuva_gerada"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    idx = OUT / "index.html"
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        if "mascara_chuva_nucleo.html" not in text:
            text = text.replace(
                '<a href="contrato_rna_mascara_stz_mucum.html">contrato RNA+máscara</a></p>',
                '<a href="contrato_rna_mascara_stz_mucum.html">contrato RNA+máscara</a> ·\n'
                '       <a href="mascara_chuva_nucleo.html">máscara chuva núcleo</a></p>',
            )
        if "Máscara de chuva" not in text:
            block = """  <section>
    <h2>Máscara de chuva do núcleo (v1)</h2>
    <div class="notice" style="border-left-color:#1b7a4a;background:#eefaf3;color:#145c38"><strong>CSV horário:</strong>
    mask_* sem imputar zero; usable exige 3 chuvas + janela R6. Nível ainda pendente.
    Ver <a href="mascara_chuva_nucleo.html">mascara_chuva_nucleo.html</a>.</div>
  </section>

"""
            text = text.replace(
                "  <section>\n    <h2>Contrato RNA + máscara (v1)</h2>",
                block + "  <section>\n    <h2>Contrato RNA + máscara (v1)</h2>",
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
    payload = build()
    (OUT / "mascara_chuva_nucleo_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_html(payload)
    merge(payload)
    print(
        json.dumps(
            {
                "ok": True,
                "csv": payload["output_csv"],
                "usable_after_r6": payload["counts"]["usable_after_r6"],
                "pct_window": payload["counts"]["pct_usable_of_window"],
                "first_usable": payload["counts"]["first_usable"],
                "last_usable": payload["counts"]["last_usable"],
                "level_masks": payload["level_masks"]["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
