#!/usr/bin/env python3
"""Train controlled 8h MLP models for STZ and Muçum (research).

Uses event workbook levels + mascara_chuva_nucleo_horaria.csv.
Does NOT promote to operational, does NOT calibrate HEC.
"""

from __future__ import annotations

import csv
import html
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import openpyxl
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
RAIN_MASK = OUT / "mascara_chuva_nucleo_horaria.csv"
EXCEL = (
    ROOT
    / "assets"
    / "audit_workbooks"
    / "8H_CONV__MUC_H8_CONV_STC021_M015.xlsx"
)
RUN_DIR = OUT / "treino_rna_stz_mucum_v1"


def present_num(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x)


def load_rain_mask() -> dict[str, dict]:
    out = {}
    with RAIN_MASK.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            # timestamp_local like 2023-10-23 04:00
            out[row["timestamp_local"]] = row
    return out


def load_excel_rows() -> list[dict]:
    wb = openpyxl.load_workbook(EXCEL, read_only=True, data_only=True)
    ws = wb["DADOS"]
    headers = [str(x) if x is not None else None for x in next(ws.iter_rows(max_row=1, values_only=True))]
    idx = {h: i for i, h in enumerate(headers) if h}
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        rec = {h: row[idx[h]] for h in idx}
        rows.append(rec)
    wb.close()
    return rows


def ts_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:00")


def build_joined(rows: list[dict], rain: dict[str, dict]) -> list[dict]:
    # index by event for t+8 STZ target
    by_ev: dict = {}
    for r in rows:
        by_ev.setdefault(r["EVENTO"], []).append(r)
    stz_future = {}
    for ev, rs in by_ev.items():
        lookup = {x["DATA_HORA"]: x for x in rs}
        for r in rs:
            fut = lookup.get(r["DATA_HORA"] + timedelta(hours=8))
            if fut is not None:
                stz_future[(ev, r["DATA_HORA"])] = fut["nivel_86472600_D0h"]

    joined = []
    for r in rows:
        dt = r["DATA_HORA"]
        if not isinstance(dt, datetime):
            continue
        rk = ts_key(dt)
        rain_row = rain.get(rk)
        y_muc = r.get("OBSERVADO_CM")
        y_stz = stz_future.get((r["EVENTO"], dt))
        item = {
            "timestamp_local": rk,
            "evento": r["EVENTO"],
            "conjunto": r["CONJUNTO"],
            "nivel_86472000": r.get("nivel_86472000_D0h"),
            "nivel_86507000": r.get("nivel_86507000_D0h"),
            "nivel_86125130": r.get("nivel_86125130_D0h"),  # Prata proxy (contract prefers 86125500)
            "nivel_86472600": r.get("nivel_86472600_D0h"),
            "nivel_86510000": r.get("nivel_86510000_t"),
            "y_stz_tplus8": y_stz,
            "y_mucum_tplus8": y_muc,
        }
        if rain_row:
            for col in ("chuva_86472000", "chuva_86472600", "chuva_02851072"):
                item[col] = rain_row.get(col, "")
                item[f"mask_{col}"] = int(rain_row.get(f"mask_{col}", "0") or 0)
            item["usable_rain"] = int(rain_row.get("usable_stz_rain_v1", "0") or 0)
            item["in_overlap_window_r6"] = int(rain_row.get("in_overlap_window_r6", "0") or 0)
        else:
            for col in ("chuva_86472000", "chuva_86472600", "chuva_02851072"):
                item[col] = ""
                item[f"mask_{col}"] = 0
            item["usable_rain"] = 0
            item["in_overlap_window_r6"] = 0
        joined.append(item)
    return joined


def core_complete_stz(row: dict) -> bool:
    levels = [
        row["nivel_86472000"],
        row["nivel_86507000"],
        row["nivel_86125130"],
        row["nivel_86472600"],  # current target level for CONV absolute
    ]
    if not all(present_num(v) for v in levels):
        return False
    if not present_num(row["y_stz_tplus8"]):
        return False
    # Require the two better-covered rains; STZ rain may be masked (R2)
    if not (row["mask_chuva_86472000"] == 1 and row["mask_chuva_02851072"] == 1):
        return False
    return True


def core_complete_mucum(row: dict) -> bool:
    levels = [
        row["nivel_86472600"],
        row["nivel_86472000"],
        row["nivel_86507000"],
        row["nivel_86125130"],
        row["nivel_86510000"],
    ]
    if not all(present_num(v) for v in levels):
        return False
    if not present_num(row["y_mucum_tplus8"]):
        return False
    if not (row["mask_chuva_86472000"] == 1 and row["mask_chuva_02851072"] == 1):
        return False
    return True


def rain_value(row: dict, col: str) -> float:
    """Numeric placeholder 0.0 only when mask=0; model also receives the mask bit (R1/R2)."""
    if row.get(f"mask_{col}") == 1 and present_num(row.get(col)):
        return float(row[col])
    return 0.0


def feature_matrix_stz(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for r in rows:
        X.append(
            [
                float(r["nivel_86472600"]),
                float(r["nivel_86472000"]),
                float(r["nivel_86507000"]),
                float(r["nivel_86125130"]),
                rain_value(r, "chuva_86472000"),
                rain_value(r, "chuva_86472600"),
                rain_value(r, "chuva_02851072"),
                float(r["mask_chuva_86472000"]),
                float(r["mask_chuva_86472600"]),
                float(r["mask_chuva_02851072"]),
            ]
        )
        y.append(float(r["y_stz_tplus8"]))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=float)


def feature_matrix_mucum(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for r in rows:
        X.append(
            [
                float(r["nivel_86510000"]),
                float(r["nivel_86472600"]),
                float(r["nivel_86472000"]),
                float(r["nivel_86507000"]),
                float(r["nivel_86125130"]),
                rain_value(r, "chuva_86472000"),
                rain_value(r, "chuva_86472600"),
                rain_value(r, "chuva_02851072"),
                float(r["mask_chuva_86472000"]),
                float(r["mask_chuva_86472600"]),
                float(r["mask_chuva_02851072"]),
            ]
        )
        y.append(float(r["y_mucum_tplus8"]))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=float)


FEATURE_NAMES_STZ = [
    "nivel_86472600_t",
    "nivel_86472000",
    "nivel_86507000",
    "nivel_86125130_prata_proxy",
    "chuva_86472000",
    "chuva_86472600",
    "chuva_02851072",
    "mask_chuva_86472000",
    "mask_chuva_86472600",
    "mask_chuva_02851072",
]
FEATURE_NAMES_MUC = [
    "nivel_86510000_t",
    "nivel_86472600",
    "nivel_86472000",
    "nivel_86507000",
    "nivel_86125130_prata_proxy",
    "chuva_86472000",
    "chuva_86472600",
    "chuva_02851072",
    "mask_chuva_86472000",
    "mask_chuva_86472600",
    "mask_chuva_02851072",
]


def metrics(y_true: np.ndarray, y_pred: np.ndarray, y_pers: np.ndarray) -> dict:
    err = y_pred - y_true
    pers_err = y_pers - y_true
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    nse = float("nan") if ss_tot <= 0 else 1.0 - ss_res / ss_tot
    return {
        "n": int(len(y_true)),
        "rmse_cm": float(np.sqrt(np.mean(err**2))),
        "mae_cm": float(np.mean(np.abs(err))),
        "nse": nse,
        "persistencia_rmse_cm": float(np.sqrt(np.mean(pers_err**2))),
        "persistencia_mae_cm": float(np.mean(np.abs(pers_err))),
        "skill_rmse_vs_pers": float(
            1.0 - (np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(pers_err**2)))
            if np.mean(pers_err**2) > 0
            else float("nan")
        ),
    }


def assign_splits(usable: list[dict]) -> dict[str, list[dict]]:
    """Prefer Excel CONJUNTO; if val/test collapse after mask, use temporal holdout."""
    splits = {
        "Treino": [r for r in usable if r["conjunto"] == "Treino"],
        "Validacao": [r for r in usable if r["conjunto"] == "Validacao"],
        "Teste": [r for r in usable if r["conjunto"] == "Teste"],
    }
    if len(splits["Validacao"]) >= 30 and len(splits["Teste"]) >= 30:
        return splits, "excel_conjunto"

    ordered = sorted(usable, key=lambda r: r["timestamp_local"])
    n = len(ordered)
    n_test = max(40, int(0.15 * n))
    n_val = max(30, int(0.10 * n))
    teste = ordered[-n_test:]
    valid = ordered[-(n_test + n_val) : -n_test]
    treino = ordered[: -(n_test + n_val)]
    return (
        {"Treino": treino, "Validacao": valid, "Teste": teste},
        "temporal_holdout_por_mascara",
    )


def train_one(name: str, rows: list[dict], complete_fn, matrix_fn, pers_key: str, feature_names: list[str]) -> dict:
    usable = [r for r in rows if complete_fn(r)]
    splits, split_mode = assign_splits(usable)
    if len(splits["Treino"]) < 50:
        raise RuntimeError(f"{name}: treino insuficiente após máscara ({len(splits['Treino'])})")

    Xtr, ytr = matrix_fn(splits["Treino"])
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "mlp",
                MLPRegressor(
                    hidden_layer_sizes=(64, 32),
                    activation="relu",
                    solver="adam",
                    max_iter=800,
                    random_state=42,
                    early_stopping=True,
                    validation_fraction=0.15,
                    n_iter_no_change=25,
                    learning_rate_init=0.001,
                ),
            ),
        ]
    )
    pipe.fit(Xtr, ytr)

    result_splits = {}
    for split_name, split_rows in splits.items():
        if not split_rows:
            continue
        Xs, ys = matrix_fn(split_rows)
        pred = pipe.predict(Xs)
        pers = np.asarray([float(r[pers_key]) for r in split_rows], dtype=float)
        result_splits[split_name] = metrics(ys, pred, pers)

    model_path = RUN_DIR / f"modelo_{name}.joblib"
    joblib.dump(
        {
            "pipeline": pipe,
            "feature_names": feature_names,
            "target": f"nivel_tplus8_{name}",
            "horizon_h": 8,
            "split_mode": split_mode,
        },
        model_path,
    )

    return {
        "model": name,
        "split_mode": split_mode,
        "n_usable_total": len(usable),
        "n_by_conjunto_before_mask": {
            k: sum(1 for r in rows if r["conjunto"] == k) for k in ("Treino", "Validacao", "Teste")
        },
        "n_by_conjunto_after_mask": {k: len(v) for k, v in splits.items()},
        "feature_names": feature_names,
        "metrics": result_splits,
        "model_path": str(model_path.relative_to(ROOT)),
        "mlp": {"hidden_layer_sizes": [64, 32], "activation": "relu", "max_iter": 800},
    }


def write_html(payload: dict) -> None:
    def split_table(model_key: str) -> str:
        m = payload["models"][model_key]["metrics"]
        rows = []
        for split, met in m.items():
            rows.append(
                "<tr>"
                f"<td>{html.escape(split)}</td>"
                f"<td>{met['n']}</td>"
                f"<td>{met['rmse_cm']:.2f}</td>"
                f"<td>{met['mae_cm']:.2f}</td>"
                f"<td>{met['nse']:.3f}</td>"
                f"<td>{met['persistencia_rmse_cm']:.2f}</td>"
                f"<td>{met['skill_rmse_vs_pers']:.3f}</td>"
                "</tr>"
            )
        return "".join(rows)

    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Treino RNA controlado · STZ e Muçum v1</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --ok:#1b7a4a; --warn:#9a5b12; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1050px; margin:auto; padding:28px 16px 64px; }}
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
    <div class="eyebrow">Estudo · treino RNA v1</div>
    <h1>MLP 8h treinado — ainda pesquisa</h1>
    <p class="muted">{html.escape(payload['generated_at_utc'])} · {html.escape(payload['status'])}</p>
    <div class="notice ok"><strong>Feito:</strong> dois modelos separados (STZ e Muçum) com máscara de chuva e splits Treino/Validação/Teste do Excel de eventos.</div>
    <div class="notice bad"><strong>Não promover:</strong> {html.escape(payload['discipline_rule'])}</div>
  </header>

  <section>
    <h2>Santa Tereza · alvo 86472600 (+8h)</h2>
    <p class="muted">usable {payload['models']['santa_tereza']['n_usable_total']} · features {', '.join(payload['models']['santa_tereza']['feature_names'])}</p>
    <table>
      <thead><tr><th>Split</th><th>N</th><th>RMSE</th><th>MAE</th><th>NSE</th><th>Pers RMSE</th><th>Skill vs pers</th></tr></thead>
      <tbody>{split_table('santa_tereza')}</tbody>
    </table>
  </section>

  <section>
    <h2>Muçum · alvo 86510000 (+8h)</h2>
    <p class="muted">usable {payload['models']['mucum']['n_usable_total']} · STZ entra como feature crítica</p>
    <table>
      <thead><tr><th>Split</th><th>N</th><th>RMSE</th><th>MAE</th><th>NSE</th><th>Pers RMSE</th><th>Skill vs pers</th></tr></thead>
      <tbody>{split_table('mucum')}</tbody>
    </table>
  </section>

  <section>
    <h2>Notas</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['notes'])}</ul>
    <h2>Próximos</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['next_steps'])}</ul>
    <p>
      <a href="treino_rna_stz_mucum_v1_latest.json">JSON</a> ·
      <a href="mascara_chuva_nucleo.html">máscara chuva</a> ·
      <a href="contrato_rna_mascara_stz_mucum.html">contrato</a> ·
      <a href="index.html">estudo-base</a>
    </p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "treino_rna_stz_mucum_v1.html").write_text(page, encoding="utf-8")


def merge(payload: dict) -> None:
    path = OUT / "estudo_bacia_latest.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["treino_rna_stz_mucum_v1"] = {
            "status": payload["status"],
            "artifacts": payload["artifacts"],
            "stz_teste_rmse": payload["models"]["santa_tereza"]["metrics"].get("Teste", {}).get("rmse_cm"),
            "mucum_teste_rmse": payload["models"]["mucum"]["metrics"].get("Teste", {}).get("rmse_cm"),
            "updated_at_utc": payload["generated_at_utc"],
        }
        prev["next_study_steps_only"] = payload["next_steps"]
        path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dom = OUT / "dois_modelos_stz_mucum_latest.json"
    if dom.exists():
        data = json.loads(dom.read_text(encoding="utf-8"))
        data["status"] = "treino_rna_v1_pesquisa_nao_operacional"
        data["treino_artifact"] = payload["artifacts"]
        data["next_steps"] = payload["next_steps"]
        dom.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    idx = OUT / "index.html"
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        if "treino_rna_stz_mucum_v1.html" not in text:
            text = text.replace(
                '<a href="mascara_chuva_nucleo.html">máscara chuva núcleo</a></p>',
                '<a href="mascara_chuva_nucleo.html">máscara chuva núcleo</a> ·\n'
                '       <a href="treino_rna_stz_mucum_v1.html">treino RNA v1</a></p>',
            )
        if "Treino RNA v1" not in text:
            block = """  <section>
    <h2>Treino RNA v1 (pesquisa)</h2>
    <div class="notice" style="border-left-color:#9a5b12;background:#fff7e8;color:#6d4810"><strong>MLP 8h:</strong>
    STZ e Muçum treinados com máscara de chuva em eventos. Não promover a operacional.
    Ver <a href="treino_rna_stz_mucum_v1.html">treino_rna_stz_mucum_v1.html</a>.</div>
  </section>

"""
            text = text.replace(
                "  <section>\n    <h2>Máscara de chuva do núcleo (v1)</h2>",
                block + "  <section>\n    <h2>Máscara de chuva do núcleo (v1)</h2>",
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
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    rain = load_rain_mask()
    excel_rows = load_excel_rows()
    joined = build_joined(excel_rows, rain)

    stz = train_one(
        "stz",
        joined,
        core_complete_stz,
        feature_matrix_stz,
        "nivel_86472600",
        FEATURE_NAMES_STZ,
    )
    muc = train_one(
        "mucum",
        joined,
        core_complete_mucum,
        feature_matrix_mucum,
        "nivel_86510000",
        FEATURE_NAMES_MUC,
    )

    payload = {
        "schema_version": "estudo_treino_rna_stz_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "treino controlado MLP 8h STZ e Mucum com mascara de chuva; pesquisa",
        "status": "treino_rna_v1_concluido_nao_operacional",
        "discipline_rule": (
            "Artefato de pesquisa. Nao substitui MATLAB/.mat operacionais. "
            "Nao e alerta. Nao calibra HEC."
        ),
        "horizon_h": 8,
        "sources": {
            "excel_eventos": str(EXCEL.relative_to(ROOT)),
            "rain_mask": str(RAIN_MASK.relative_to(ROOT)),
            "contract": "contrato_rna_mascara_stz_mucum_latest.json",
        },
        "notes": [
            "Prata no Excel de eventos usa 86125130 (proxy); contrato preferia 86125500.",
            "Máscaras de chuva entram como features; valor 0 com mask=0 é placeholder (não chuva observada).",
            "Se Validacao/Teste do Excel zeram após máscara, usa holdout temporal nos usable.",
            "Baseline = persistência do nível atual do alvo.",
        ],
        "models": {"santa_tereza": stz, "mucum": muc},
        "next_steps": [
            "Comparar contra .mat operacional / Excel-mãe nos mesmos eventos.",
            "Trocar proxy 86125130 por 86125500 quando série local existir.",
            "Só promover se bater baseline e disciplina de auditoria PREVINE.",
        ],
        "artifacts": {
            "json": "treino_rna_stz_mucum_v1_latest.json",
            "html": "treino_rna_stz_mucum_v1.html",
            "models_dir": "treino_rna_stz_mucum_v1/",
        },
    }

    (OUT / "treino_rna_stz_mucum_v1_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_html(payload)
    merge(payload)

    summary = {
        "ok": True,
        "status": payload["status"],
        "stz_usable": stz["n_usable_total"],
        "muc_usable": muc["n_usable_total"],
        "stz_teste": stz["metrics"].get("Teste"),
        "muc_teste": muc["metrics"].get("Teste"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
