#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Substitui as rodadas 2h de Santa Tereza no painel pela RNA_2H_ALT_ROTACAO_STZ."""
from __future__ import annotations

import csv
import json
import math
import re
import shutil
from collections import defaultdict
from pathlib import Path

import openpyxl

RAIZ = Path(__file__).resolve().parents[2]
SRC = Path("/tmp/rna_2h_inbox/RNA_2H_ALT_ROTACAO_STZ/RNA_2H_ALT_ROTACAO_STZ")
RODADA = "RNA_2H_ALT_ROTACAO_STZ"
INPUTS_VFINAL_15 = [0, 1, 11, 10, 13, 12, 14, 38, 27, 3, 17, 4, 22, 18, 24]
RAW_BASE = "https://raw.githubusercontent.com/julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais/main"


def r4(x):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), 4)


def r2(x):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), 2)


def read_csv_semi(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        return list(csv.DictReader(f, delimiter=delim))


def parse_evento_teste(raw: str) -> str:
    nums = re.findall(r"\d+", str(raw or ""))
    return ",".join(nums) if nums else str(raw or "").strip()


def parse_eventos_val(raw: str) -> str:
    nums = re.findall(r"\d+", str(raw or ""))
    return ", ".join(nums) if nums else str(raw or "").strip()


def is_old_st_2h_mat(name: str) -> bool:
    n = name
    if n.startswith("MUC_"):
        return False
    return bool(
        re.search(r"(^|_)2[Hh]_(alt|conv)_|2H_ALT|2H_CONV|STZ_H2|_2h_alt_|_2h_conv_", n, re.I)
        or n.startswith("rot_")
        and "2h" in n.lower()
        or re.match(r"T\d+_V.+_2h_(alt|conv)_", n)
        or n.startswith("NN_2h_")
        or n.startswith("01_2H_")
        or n.startswith("02_2H_")
        or n.startswith("03_2H_")
        or n.startswith("04_2H_")
        or n.startswith("05_2H_")
        or n.startswith("06_2H_")
        or n.startswith("12_2h_")
    )


def is_old_st_2h_wb(name: str) -> bool:
    if "MUC_" in name or name.startswith("12H_") or name.startswith("8H_") or name.startswith("4H_"):
        return False
    return (
        name.startswith("2H_ALT__")
        or name.startswith("2H_CONV__")
        or bool(re.search(r"_2h_(alt|conv)_", name))
        or "STZ_H2" in name
        or bool(re.search(r"T\d+_V.+_2h_(alt|conv)_", name))
    )


def build_models():
    manifesto = {r["name"]: r for r in read_csv_semi(SRC / "MANIFESTO_ROTACAO_2H_ALT_STZ.csv")}
    metricas = {r["MODELO"]: r for r in read_csv_semi(SRC / "resultados" / "resultados_2h_alt_stz_metricas_completas.csv")}
    models = []
    for name, man in sorted(manifesto.items()):
        met = metricas[name]
        mat_name = f"{name}.mat"
        wb_name = f"2H_ALT__{name}.xlsx"
        mat_path = SRC / "mat" / mat_name
        rot = man.get("rot_id") or ""
        models.append(
            {
                "usar_decisao": "NOVA_ROTACAO_2H_ALT_STZ",
                "familia": "2H_ALT",
                "horizonte": "2h",
                "tipo": "alt",
                "rotacao": rot,
                "modelo": name,
                "combo_id": f"STZ_2H_ALT_{rot}",
                "evento_teste": parse_evento_teste(man.get("evt_teste", "")),
                "eventos_validacao": parse_eventos_val(man.get("evt_valida", "")),
                "n_inputs": 15,
                "neuronios": int(float(met.get("nh") or man.get("nh") or 30)),
                "nit": int(float(met.get("nit") or man.get("nit") or 10)),
                "ciclos": int(float(met.get("Cic") or man.get("Cic") or 100000)),
                "J": float(met.get("J") or 0),
                "N_geral": int(float(met.get("N_GERAL") or 0)),
                "N_treino": int(float(met.get("N_TREINO") or man.get("n_treino") or 0)),
                "N_validacao": int(float(met.get("N_VALIDACAO") or man.get("n_validacao") or 0)),
                "N_teste": int(float(met.get("N_TESTE") or man.get("n_teste") or 0)),
                "NASH_validacao_csv": float(met["NASH_VALIDACAO"]),
                "NASH_teste_csv": float(met["NASH_TESTE"]),
                "correlacao_teste_csv": float(met["CORR_TESTE"]),
                "fim": "2026-08-04 19:18:22",
                "arquivo_auditavel": str(SRC / "auditaveis" / f"{name}_AUDITAVEL.xlsx"),
                "arquivo_mat": str(mat_path),
                "inputs": list(INPUTS_VFINAL_15),
                "novo": False,
                "rodada": RODADA,
                "PERS_geral": float(met["PERS_GERAL"]),
                "PERS_treino": float(met["PERS_TREINO"]),
                "PERS_validacao": float(met["PERS_VALIDACAO"]),
                "PERS_teste": float(met["PERS_TESTE"]),
                "score_equilibrio": float(met["PERS_TESTE"]),
                "MAE_geral_cm": float(met["MAE_GERAL"]),
                "MAE_validacao_cm": float(met["MAE_VALIDACAO"]),
                "MAE_teste_cm": float(met["MAE_TESTE"]),
                "E95_geral_cm": float(met["E95_GERAL"]),
                "E95_validacao_cm": float(met["E95_VALIDACAO"]),
                "E95_teste_cm": float(met["E95_TESTE"]),
                "wb_url": f"{RAW_BASE}/assets/audit_workbooks/{wb_name}",
                "mat_url": f"{RAW_BASE}/assets/mat/{mat_name}",
                "mat": {
                    "nh": float(met.get("nh") or 30),
                    "nit": float(met.get("nit") or 10),
                    "cic": float(met.get("Cic") or 100000),
                    "J": float(met.get("J") or 0),
                    "NASH": float(met["NASH_TESTE"]),
                    "NASH_VAL": float(met["NASH_VALIDACAO"]),
                    "PERS": float(met["PERS_TESTE"]),
                    "e95": float(met["E95_TESTE"]),
                    "emed": float(met["MAE_TESTE"]),
                    "size": mat_path.stat().st_size if mat_path.exists() else None,
                    "mod": "2026-08-04 19:18:22",
                    "wh": [30, 15],
                },
            }
        )
    return models


def conjunto_to_set(conjunto, serie):
    c = str(conjunto or "").strip().lower()
    if "teste" in c or "verific" in c:
        return 2
    if "valid" in c:
        return 1
    if "trein" in c:
        return 0
    try:
        s = int(float(serie))
    except Exception:
        return 0
    # manifesto: Treino=1, Validacao=2, Verificacao=3 -> metrics sets 0/1/2
    return {1: 0, 2: 1, 3: 2}.get(s, 0)


def metrics_of_pairs(pairs):
    if not pairs:
        return {"n": 0, "mae": None, "rmse": None, "bias": None, "maxAbs": None, "corr": None}
    errs = [rna - obs for obs, rna in pairs]
    mae = sum(abs(e) for e in errs) / len(errs)
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    bias = sum(errs) / len(errs)
    max_abs = max(abs(e) for e in errs)
    mo = sum(o for o, _ in pairs) / len(pairs)
    mr = sum(r for _, r in pairs) / len(pairs)
    num = sum((o - mo) * (r - mr) for o, r in pairs)
    den_o = math.sqrt(sum((o - mo) ** 2 for o, _ in pairs))
    den_r = math.sqrt(sum((r - mr) ** 2 for _, r in pairs))
    corr = (num / (den_o * den_r)) if den_o and den_r else None
    return {
        "n": len(pairs),
        "mae": r2(mae),
        "rmse": r2(rmse),
        "bias": r2(bias),
        "maxAbs": r2(max_abs),
        "corr": r4(corr) if corr is not None else None,
    }


def build_series_entry(name: str, mat_size: int):
    xlsx = SRC / "auditaveis" / f"{name}_AUDITAVEL.xlsx"
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb["VAR"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip() if h is not None else "" for h in rows[0]]
    ix = {h: i for i, h in enumerate(hdr)}
    series = defaultdict(list)
    events_acc = defaultdict(list)
    scatter = []
    scatter_by = defaultdict(list)
    all_pairs = []
    by_set_pairs = defaultdict(list)

    for row in rows[1:]:
        if not row or row[ix["EVENTO"]] is None:
            continue
        try:
            ev = int(float(row[ix["EVENTO"]]))
            ano, mes, dia, hora, minuto = [int(float(row[i])) for i in range(5)]
            obs = float(row[ix["OUT2H NIV"]])
            rna = float(row[ix["RNA FINAL"]])
        except Exception:
            continue
        conjunto = row[ix["CONJUNTO"]] if "CONJUNTO" in ix else None
        serie = row[ix["SERIE"]] if "SERIE" in ix else None
        set_code = conjunto_to_set(conjunto, serie)
        dh = f"{ano:04d}-{mes:02d}-{dia:02d} {hora:02d}:{minuto:02d}"
        conj_label = {0: "Treino", 1: "Validacao", 2: "Teste"}.get(set_code, "Treino")
        key = f"{ev}|{conj_label}"
        events_acc[key].append((dh, obs, rna, set_code))
        all_pairs.append((obs, rna))
        by_set_pairs[str(set_code)].append((obs, rna))
        by_set_pairs["all"].append((obs, rna))

    for key, pts in events_acc.items():
        obs0 = pts[0][1]
        rna0 = pts[0][2]
        seq = []
        for dh, obs, rna, set_code in pts:
            rise_o = obs - obs0
            rise_r = rna - rna0
            err = rna - obs
            seq.append([dh, obs, rna, set_code, r2(rise_o), r2(rise_r), r2(err)])
            scatter.append([obs, rna])
            scatter_by[str(set_code)].append([obs, rna])
        series[key] = seq

    events = []
    for key, pts in sorted(events_acc.items(), key=lambda kv: (int(kv[0].split("|")[0]), kv[0])):
        ev = int(key.split("|")[0])
        conj = key.split("|", 1)[1]
        set_code = pts[0][3]
        obs_vals = [p[1] for p in pts]
        rna_vals = [p[2] for p in pts]
        pairs = list(zip(obs_vals, rna_vals))
        met = metrics_of_pairs(pairs)
        events.append(
            {
                "key": key,
                "evento": ev,
                "conjunto": conj,
                "set": set_code,
                "n": len(pts),
                "start": pts[0][0],
                "end": pts[-1][0],
                "obsStart": obs_vals[0],
                "obsPeak": max(obs_vals),
                "rnaPeak": max(rna_vals),
                "riseObs": r2(max(obs_vals) - obs_vals[0]),
                "riseRna": r2(max(rna_vals) - rna_vals[0]),
                "mae": met["mae"],
                "maxErr": met["maxAbs"],
            }
        )

    rot = name.split("_STZ_2H_")[-1] if "_STZ_2H_" in name else name
    wb_name = f"2H_ALT__{name}.xlsx"
    mat_name = f"{name}.mat"
    return {
        "id": name,
        "name": name,
        "file": f"{name}_AUDITAVEL.xlsx",
        "family": "2H_ALT",
        "horizon": "2H",
        "type": "ALT",
        "target": "2h_alt",
        "combo": f"STZ_2H_ALT_{rot}",
        "rotation": rot,
        "matchKeys": [name.upper(), "2H_ALT", f"STZ_2H_ALT_{rot}".upper(), rot.upper(), name],
        "sourceRef": f"redes_neurais/santa tereza/RNA_2h_rotacoes/{RODADA}/auditaveis/{name}_AUDITAVEL.xlsx",
        "metrics": metrics_of_pairs(all_pairs),
        "metricsBySet": {
            "all": metrics_of_pairs(by_set_pairs.get("all", [])),
            "0": metrics_of_pairs(by_set_pairs.get("0", [])),
            "1": metrics_of_pairs(by_set_pairs.get("1", [])),
            "2": metrics_of_pairs(by_set_pairs.get("2", [])),
            "3": {"n": 0, "mae": None, "rmse": None, "bias": None, "maxAbs": None, "corr": None},
        },
        "events": events,
        "series": dict(series),
        "scatter": scatter,
        "scatterBySet": {k: v for k, v in scatter_by.items() if k in ("1", "2")},
        "workbookUrl": f"assets/audit_workbooks/{wb_name}",
        "workbookFile": wb_name,
        "matSourceRef": f"redes_neurais/santa tereza/RNA_2h_rotacoes/{RODADA}/mat/{mat_name}",
        "matUrl": f"assets/mat/{mat_name}",
        "matFile": mat_name,
        "matSize": mat_size,
        "positivePersMainModel": name,
    }


def replace_index_models(new_models):
    index = RAIZ / "index.html"
    text = index.read_text(encoding="utf-8")
    m = re.search(r'(<script id="data" type="application/json">)(.*?)(</script>)', text, re.S)
    if not m:
        raise SystemExit("script#data nao encontrado")
    payload = json.loads(m.group(2))
    kept = [x for x in payload["models"] if x.get("familia") not in ("2H_ALT", "2H_CONV")]
    payload["models"] = kept + new_models
    payload["positivePersFilter"] = {
        "applied": True,
        "sourceModels": len(payload["models"]),
        "keptModels": len(payload["models"]),
        "removedModels": 0,
        "rule": "all PERS_geral/treino/validacao/teste > 0 (renovacao 2h STZ 2026-08-06)",
    }
    new_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    text = text[: m.start(2)] + new_json + text[m.end(2) :]
    # atualiza titulo do bloco de aprendizados 2h
    text = text.replace(
        "{title:'O que o 2h ensinou · 49 modelos'",
        "{title:'O que o 2h ensinou · 10 modelos (nova rotacao STZ)'",
    )
    index.write_text(text, encoding="utf-8")
    print(f"index.html: {len(kept)} mantidos + {len(new_models)} novos 2H_ALT")


def sync_binaries(new_models):
    mat_dir = RAIZ / "assets" / "mat"
    wb_dir = RAIZ / "assets" / "audit_workbooks"
    removed_m = removed_w = 0
    for p in list(mat_dir.iterdir()):
        if p.is_file() and is_old_st_2h_mat(p.name):
            p.unlink()
            removed_m += 1
    for p in list(wb_dir.iterdir()):
        if p.is_file() and is_old_st_2h_wb(p.name):
            p.unlink()
            removed_w += 1
    for model in new_models:
        name = model["modelo"]
        shutil.copy2(SRC / "mat" / f"{name}.mat", mat_dir / f"{name}.mat")
        src_wb = SRC / "auditaveis" / f"{name}_AUDITAVEL.xlsx"
        dst_wb = wb_dir / f"2H_ALT__{name}.xlsx"
        shutil.copy2(src_wb, dst_wb)
    print(f"mats removidos={removed_m} workbooks removidos={removed_w} novos={len(new_models)}")


def rebuild_event_rise_top(data, limit=14):
    """Top subidas observadas, 1 entrada por evento canônico (start/end/nº/conjunto)."""
    rows = []
    for m in data.get("models") or []:
        for ev in m.get("events") or []:
            rise = ev.get("riseObs")
            if rise is None:
                continue
            rows.append(
                {
                    "evento": ev.get("evento"),
                    "conjunto": ev.get("conjunto"),
                    "riseObs": rise,
                    "obsPeak": ev.get("obsPeak"),
                    "start": ev.get("start"),
                    "end": ev.get("end"),
                    "model": m.get("name") or m.get("id"),
                    "sourceRef": m.get("sourceRef") or m.get("file") or "",
                }
            )
    rows.sort(key=lambda r: (-(r["riseObs"] or 0), -(r.get("obsPeak") or 0), str(r["model"])))
    seen = set()
    top = []
    for r in rows:
        key = (r["start"], r["end"], r["evento"], r["conjunto"])
        if key in seen:
            continue
        seen.add(key)
        top.append(r)
        if len(top) >= limit:
            break
    data["eventRiseTop"] = top
    return top


def sync_series(new_models):
    path = RAIZ / "assets" / "data" / "auditaveis_series.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    before = len(data["models"])
    data["models"] = [m for m in data["models"] if m.get("family") not in ("2H_ALT", "2H_CONV")]
    removed = before - len(data["models"])
    for model in new_models:
        entry = build_series_entry(model["modelo"], model["mat"]["size"] or 0)
        data["models"].append(entry)
    top = rebuild_event_rise_top(data)
    meta = data.setdefault("meta", {})
    meta["updatedAt"] = "2026-08-06"
    meta["note_2h_stz"] = f"Renovado com {len(new_models)} modelos {RODADA}; removidos {removed} series 2H antigas"
    meta["eventRiseTopUpdatedAt"] = "2026-08-06"
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"auditaveis_series: -{removed} +{len(new_models)} (total {len(data['models'])}); eventRiseTop={len(top)}")


def sync_light_json(new_models):
    # limpa novos_modelos / novos_series 2h antigos se existirem
    for rel in ("assets/data/novos_modelos_pos_planilhao.json", "assets/data/novos_series.json"):
        p = RAIZ / rel
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "modelos" in data:
            data["modelos"] = [
                m
                for m in data["modelos"]
                if not (str(m.get("horizonte", "")).startswith("2") or str(m.get("familia", "")).startswith("2H"))
            ]
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"atualizado {rel} modelos={len(data['modelos'])}")
        elif isinstance(data, dict):
            # novos_series: dict keyed by model id
            keys = [k for k in list(data) if re.search(r"2h_(alt|conv)|2H_(ALT|CONV)|STZ_H2", k)]
            for k in keys:
                data.pop(k, None)
            p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"atualizado {rel} removidas {len(keys)} chaves 2h")


def main():
    if not SRC.exists():
        raise SystemExit(f"fonte nao encontrada: {SRC}")
    new_models = build_models()
    assert len(new_models) == 10, len(new_models)
    replace_index_models(new_models)
    sync_binaries(new_models)
    sync_series(new_models)
    sync_light_json(new_models)
    # regenera Eventos sob a lupa + campeões (requer planilhas já sincronizadas)
    from subprocess import check_call
    import sys

    check_call([sys.executable, str(RAIZ / "codigo_python" / "05_eventos" / "analise_eventos.py")], cwd=RAIZ)
    # copia CSVs de resultados para referencia no repo
    dest = RAIZ / "assets" / "data" / "stz_2h_rotacao"
    dest.mkdir(parents=True, exist_ok=True)
    for fname in (
        "MANIFESTO_ROTACAO_2H_ALT_STZ.csv",
        "EVENTOS_USADOS_2H_ALT_STZ.csv",
    ):
        shutil.copy2(SRC / fname, dest / fname)
    shutil.copy2(SRC / "resultados" / "resultados_2h_alt_stz_metricas_completas.csv", dest / "resultados_2h_alt_stz_metricas_completas.csv")
    shutil.copy2(SRC / "resultados" / "resultados_2h_alt_stz.csv", dest / "resultados_2h_alt_stz.csv")
    print("ok")


if __name__ == "__main__":
    main()
