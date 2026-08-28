"""Publica no catalogo de RNA apenas candidatos q70 ja executados e auditados.

Este script nao toca o feed/robo ao vivo. Ele copia os dois artefatos escolhidos,
registra a proveniencia e acrescenta os registros ao payload data-mucum do catalogo.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import scipy.io as sio


REPO = Path(__file__).resolve().parents[1]
Q70 = Path(r"D:\PREVINE\redes_neurais\mucum\PREPARACAO_RNA_MUC_CORRIGIDA_2026_08_08\70_FILA_MATLAB_MUCUM_MELHORIAS_20260827")
RESULTS = Q70 / "resultados" / "resultados_mucum_melhorias_70_metricas_completas.csv"
INDEX = REPO / "index.html"
SELECTED = {
    "070_alt_MUC_H08_NOACEL_LOCAL865_NH32_S02",
    "070_alt_MUC_H12_NOACEL_LOCAL865_NH72_S05",
}


def f(row, key):
    value = row.get(key, "")
    return None if value in (None, "") else float(value)


def i(row, key):
    value = row.get(key, "")
    return None if value in (None, "") else int(float(value))


def scalar(mat, key, default=None):
    value = mat.get(key, default)
    if value is None:
        return default
    arr = np.asarray(value).reshape(-1)
    return arr[0].item() if arr.size else default


def mat_meta(mat, path):
    wh = np.asarray(mat["wh"])
    bh = np.asarray(mat["bh"])
    return {
        "nh": int(scalar(mat, "nh")),
        "nit": int(scalar(mat, "nit")),
        "cic": int(scalar(mat, "Cic")),
        "J": float(scalar(mat, "J")),
        "NASH": float(scalar(mat, "NASH_TESTE")),
        "NASH_VAL": float(scalar(mat, "NASH_VALIDACAO")),
        "PERS": float(scalar(mat, "PERS_TESTE")),
        "e95": float(scalar(mat, "E95_TESTE")),
        "emed": float(scalar(mat, "MAE_TESTE")),
        "Prc": float(scalar(mat, "Prc")),
        "Mom": float(scalar(mat, "Mom")),
        "wh": list(wh.shape),
        "bh": list(bh.shape),
        "size": path.stat().st_size,
        "mod": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }


def input_names(xlsx):
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    header = list(next(wb["VAR"].iter_rows(values_only=True)))
    target = next(x for x in header if str(x).startswith("OUT"))
    return [str(x) for x in header[7:header.index(target)]]


def build_record(row, mat_path, wb_path, mat_url, wb_url):
    model = row["MODELO"]
    horizon = "8h" if "H08" in model else "12h"
    family = "8H_ALT" if horizon == "8h" else "12H_ALT"
    m = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
    names = input_names(wb_path)
    score = min(f(row, "PERS_TREINO"), f(row, "PERS_VALIDACAO"), f(row, "PERS_TESTE"))
    public_wb = REPO / "assets" / "audit_workbooks" / wb_path.name
    public_mat = REPO / "assets" / "mat" / mat_path.name
    return {
        "familia": family,
        "horizonte": horizon,
        "tipo": "alt",
        "rotacao": "NOACEL_LOCAL865_NH" + str(i(row, "nh")) + "_S" + str(i(row, "seed") % 10).zfill(2),
        "modelo": model,
        "combo_id": "MUC_H" + ("08" if horizon == "8h" else "12") + "_NOACEL_LOCAL865",
        "evento_teste": "31,33,34,35,37",
        "eventos_validacao": "18,20,21",
        "fonte_rodada": "70_FILA_MATLAB_MUCUM_MELHORIAS_20260827",
        "status_modelo": "CONCLUIDO_AUDITADO_Q70_EXPERIMENTAL",
        "n_inputs": len(names),
        "neuronios": i(row, "nh"),
        "nit": i(row, "nit"),
        "ciclos": i(row, "Cic"),
        "N_geral": i(row, "N_GERAL"),
        "N_treino": i(row, "N_TREINO"),
        "N_validacao": i(row, "N_VALIDACAO"),
        "N_teste": i(row, "N_TESTE"),
        "PERS_geral": f(row, "PERS_GERAL"),
        "PERS_treino": f(row, "PERS_TREINO"),
        "PERS_validacao": f(row, "PERS_VALIDACAO"),
        "PERS_teste": f(row, "PERS_TESTE"),
        "score_equilibrio": score,
        "MAE_geral_cm": f(row, "MAE_GERAL"),
        "MAE_validacao_cm": f(row, "MAE_VALIDACAO"),
        "MAE_teste_cm": f(row, "MAE_TESTE"),
        "E95_geral_cm": f(row, "E95_GERAL"),
        "E95_validacao_cm": f(row, "E95_VALIDACAO"),
        "E95_teste_cm": f(row, "E95_TESTE"),
        "NASH_geral_csv": f(row, "NASH_GERAL"),
        "NASH_treino_csv": f(row, "NASH_TREINO"),
        "NASH_validacao_csv": f(row, "NASH_VALIDACAO"),
        "NASH_teste_csv": f(row, "NASH_TESTE"),
        "correlacao_teste_csv": f(row, "CORR_TESTE"),
        "arquivo_auditavel": str(wb_path),
        "arquivo_mat": str(mat_path),
        "inputs": list(range(len(names))),
        "input_names": names,
        "J": float(scalar(m, "J")),
        "mat": mat_meta(m, public_mat),
        "mat_url": mat_url,
        "wb_url": wb_url,
        "novo": True,
        "selection_rank": None,
        "selection_rule": "Candidato q70 selecionado pela validação; publicação experimental no catálogo, sem promoção ao robô ao vivo.",
        "avisos": [
            "Fila 70 concluída: 20/20 modelos, sem erros numéricos ou marcadores fatais.",
            "Acelerações locais de Santa Teresa (86510000) removidas; demais entradas permaneceram conforme o contrato auditado.",
            "A planilha auditável publicada contém VAR/CONTRATO_INPUTS/FONTE_BASE, sem DADOS ponto a ponto; gráfico por evento ainda não disponível para este candidato.",
            "Não promovido ao robô ao vivo.",
        ] + (["Comparação com q68 deve considerar N de teste diferente (q70=345; q68=395)."] if horizon == "8h" else ["Escolhido pela validação; o melhor teste isolado da fila foi NH48, preservado como evidência exploratória, não como promoção."]),
    }


def main():
    rows = {}
    with RESULTS.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            if row["MODELO"] in SELECTED:
                rows[row["MODELO"]] = row
    if set(rows) != SELECTED:
        raise SystemExit(f"Selecionados ausentes no CSV: {sorted(SELECTED - set(rows))}")

    records = []
    for model in sorted(SELECTED):
        horizon = "8H_ALT" if "H08" in model else "12H_ALT"
        src_mat = Q70 / "mat" / f"{model}.mat"
        src_wb = Q70 / "planilhas" / f"{model}.xlsx"
        public_mat = REPO / "assets" / "mat" / f"{horizon}__{model}.mat"
        public_wb = REPO / "assets" / "audit_workbooks" / f"{horizon}__{model}.xlsx"
        public_mat.parent.mkdir(parents=True, exist_ok=True)
        public_wb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_mat, public_mat)
        shutil.copy2(src_wb, public_wb)
        records.append(build_record(rows[model], public_mat, public_wb,
                                    public_mat.relative_to(REPO).as_posix(),
                                    public_wb.relative_to(REPO).as_posix()))

    publication = {
        "queue": "70_FILA_MATLAB_MUCUM_MELHORIAS_20260827",
        "publishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "destination": "catalogo de redes neurais de Mucum; nao e robo ao vivo",
        "status": "Q70_CANDIDATOS_PUBLICADOS_EXPERIMENTAIS",
        "models": records,
        "series_graphs": "indisponiveis para os dois candidatos: os XLSX auditaveis q70 nao possuem aba DADOS ponto a ponto",
        "audit": {"expected": 20, "completed": 20, "numeric_errors": 0, "fatal_log_markers": 0},
    }
    (REPO / "assets" / "data" / "mucum_q70_publicacao.json").write_text(
        json.dumps(publication, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    html = INDEX.read_text(encoding="utf-8")
    match = re.search(r'(<script id="data-mucum"[^>]*>)(.*?)(</script>)', html, re.S)
    if not match:
        raise SystemExit("data-mucum nao encontrado")
    payload = json.loads(match.group(2))
    existing = {m.get("modelo"): m for m in payload.get("models", [])}
    for record in records:
        existing[record["modelo"]] = record
    payload["models"] = list(existing.values())
    new_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    INDEX.write_text(html[:match.start(2)] + new_json + html[match.end(2):], encoding="utf-8")
    print(f"Publicados no catalogo: {', '.join(r['modelo'] for r in records)}")
    print(f"Total de modelos no payload: {len(payload['models'])}")


if __name__ == "__main__":
    main()
