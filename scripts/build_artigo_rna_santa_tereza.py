#!/usr/bin/env python3
"""Build the auditable tables for the Santa Tereza RNA article draft.

Reads the qualified Santa Tereza recorte embedded in index.html and writes
assets/data/artigo_rna_santa_tereza.json. Research inventory only: this never
promotes a model to an operational alert.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
OUTPUT = ROOT / "assets" / "data" / "artigo_rna_santa_tereza.json"
HORIZONS = ("2h", "4h", "8h", "12h")


def embedded_json(text: str, script_id: str) -> dict[str, Any]:
    match = re.search(
        rf'<script\s+id="{re.escape(script_id)}"\s+type="application/json">(.*?)</script>',
        text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"JSON embutido não encontrado: {script_id}")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError(f"JSON embutido inválido: {script_id}")
    return value


def input_names(model: dict[str, Any], catalog: list[str]) -> list[str]:
    names: list[str] = []
    for item in model.get("inputs") or []:
        if isinstance(item, int) and 0 <= item < len(catalog):
            names.append(catalog[item])
        elif isinstance(item, str) and item.isdigit():
            idx = int(item)
            names.append(catalog[idx] if 0 <= idx < len(catalog) else item)
        else:
            names.append(str(item))
    return names


def uses_rain(names: list[str]) -> bool:
    return any("chuva" in name.lower() for name in names)


def r3(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def med(values: list[float]) -> float | None:
    return r3(median(values)) if values else None


def compact(model: dict[str, Any], catalog: list[str]) -> dict[str, Any]:
    names = input_names(model, catalog)
    return {
        "modelo": model.get("modelo"),
        "familia": model.get("familia"),
        "horizonte": model.get("horizonte"),
        "tipo": model.get("tipo"),
        "rotacao": model.get("rotacao") or None,
        "combo_id": model.get("combo_id"),
        "evento_teste": model.get("evento_teste"),
        "n_inputs": model.get("n_inputs"),
        "neuronios": model.get("neuronios"),
        "nit": model.get("nit"),
        "ciclos": model.get("ciclos"),
        "PERS_geral": r3(model.get("PERS_geral")),
        "PERS_treino": r3(model.get("PERS_treino")),
        "PERS_validacao": r3(model.get("PERS_validacao")),
        "PERS_teste": r3(model.get("PERS_teste")),
        "score_equilibrio": r3(model.get("score_equilibrio")),
        "MAE_teste_cm": r3(model.get("MAE_teste_cm")),
        "E95_teste_cm": r3(model.get("E95_teste_cm")),
        "NASH_teste": r3(model.get("NASH_teste_csv")),
        "chuva": uses_rain(names),
        "inputs": names,
    }


def group_rows(models: list[dict[str, Any]], catalog: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        for kind in ("alt", "conv"):
            pool = [m for m in models if m.get("horizonte") == horizon and m.get("tipo") == kind]
            if not pool:
                rows.append(
                    {
                        "horizonte": horizon,
                        "tipo": kind,
                        "n": 0,
                    }
                )
                continue
            eq = [m["score_equilibrio"] for m in pool if m.get("score_equilibrio") is not None]
            pers_t = [m["PERS_teste"] for m in pool if m.get("PERS_teste") is not None]
            pers_g = [m["PERS_geral"] for m in pool if m.get("PERS_geral") is not None]
            mae = [m["MAE_teste_cm"] for m in pool if m.get("MAE_teste_cm") is not None]
            e95 = [m["E95_teste_cm"] for m in pool if m.get("E95_teste_cm") is not None]
            nash = [m["NASH_teste_csv"] for m in pool if m.get("NASH_teste_csv") is not None]
            nin = [m["n_inputs"] for m in pool if m.get("n_inputs")]
            nh = [m["neuronios"] for m in pool if m.get("neuronios")]
            best = max(pool, key=lambda item: item.get("score_equilibrio") or -9)
            eq_gt = sum(1 for item in pool if (item.get("score_equilibrio") or 0) > 0.5)
            rows.append(
                {
                    "horizonte": horizon,
                    "tipo": kind,
                    "n": len(pool),
                    "n_equilibrio_gt_050": eq_gt,
                    "equilibrio_mediana": med(eq),
                    "equilibrio_max": r3(max(eq) if eq else None),
                    "PERS_teste_mediana": med(pers_t),
                    "PERS_geral_mediana": med(pers_g),
                    "MAE_teste_cm_mediana": med(mae),
                    "E95_teste_cm_mediana": med(e95),
                    "NASH_teste_mediana": med(nash),
                    "n_inputs_mediana": med([float(v) for v in nin]) if nin else None,
                    "neuronios_mediana": med([float(v) for v in nh]) if nh else None,
                    "melhor": compact(best, catalog),
                }
            )
    return rows


def rain_contrast(models: list[dict[str, Any]], catalog: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        pool = [m for m in models if m.get("horizonte") == horizon]
        named = [(m, input_names(m, catalog)) for m in pool]
        for label, pred in (("com_chuva", True), ("sem_chuva", False)):
            subset = [m for m, names in named if uses_rain(names) is pred]
            rows.append(
                {
                    "horizonte": horizon,
                    "grupo": label,
                    "n": len(subset),
                    "equilibrio_mediana": med([m["score_equilibrio"] for m in subset]),
                    "PERS_teste_mediana": med([m["PERS_teste"] for m in subset]),
                    "MAE_teste_cm_mediana": med([m["MAE_teste_cm"] for m in subset]),
                }
            )
    return rows


def unique_top(models: list[dict[str, Any]], catalog: list[str], horizon: str, n: int = 5) -> list[dict[str, Any]]:
    pool = sorted(
        [m for m in models if m.get("horizonte") == horizon],
        key=lambda item: item.get("score_equilibrio") or -9,
        reverse=True,
    )
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for model in pool:
        key = (
            round(float(model.get("score_equilibrio") or 0), 6),
            round(float(model.get("PERS_teste") or 0), 6),
            round(float(model.get("MAE_teste_cm") or 0), 4),
            model.get("n_inputs"),
            model.get("neuronios"),
            model.get("rotacao"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(compact(model, catalog))
        if len(out) >= n:
            break
    return out


def input_frequency(models: list[dict[str, Any]], catalog: list[str], top_frac: float = 0.25) -> list[dict[str, Any]]:
    ranked = sorted(models, key=lambda item: item.get("score_equilibrio") or -9, reverse=True)
    top_n = max(1, int(len(ranked) * top_frac))
    top = ranked[:top_n]
    all_c: Counter[str] = Counter()
    top_c: Counter[str] = Counter()
    for model in models:
        all_c.update(input_names(model, catalog))
    for model in top:
        top_c.update(input_names(model, catalog))
    rows = []
    for name, count in top_c.most_common(12):
        rows.append(
            {
                "input": name,
                "pct_melhor_quartil": r3(100.0 * count / len(top)),
                "pct_recorte": r3(100.0 * all_c[name] / len(models)),
            }
        )
    return rows


def eight_hour_extremes(models: list[dict[str, Any]], catalog: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind in ("alt", "conv"):
        cand = [
            m
            for m in models
            if m.get("horizonte") == "8h"
            and m.get("tipo") == kind
            and (m.get("score_equilibrio") or 0) > 0.5
        ]
        if not cand:
            out[kind] = {"n_equilibrio_gt_050": 0}
            continue
        best_e95 = min(cand, key=lambda item: item.get("E95_teste_cm") or 9e9)
        out[kind] = {
            "n_equilibrio_gt_050": len(cand),
            "menor_E95": compact(best_e95, catalog),
        }
    return out


def build() -> dict[str, Any]:
    payload = embedded_json(INDEX.read_text(encoding="utf-8"), "data")
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    catalog = payload.get("inputs") if isinstance(payload.get("inputs"), list) else []
    families = Counter(str(item.get("familia")) for item in models)
    types = Counter(str(item.get("tipo")) for item in models)
    horizons = Counter(str(item.get("horizonte")) for item in models)
    ratios = [
        item["neuronios"] / item["n_inputs"]
        for item in models
        if item.get("neuronios") and item.get("n_inputs")
    ]
    two_hour = [compact(item, catalog) for item in models if item.get("horizonte") == "2h"]
    two_hour.sort(key=lambda item: item.get("score_equilibrio") or -9, reverse=True)
    return {
        "schema_version": "previne_artigo_rna_santa_tereza_v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "official_alert": False,
        "purpose": "Tabelas do rascunho de artigo das RNAs consolidadas de Santa Tereza. Não é alerta, ordem de evacuação, rota ou despacho.",
        "source": "index.html#data",
        "station": {
            "name": "Santa Tereza",
            "code": "86472600",
            "agency": "ANA/SGB",
        },
        "qualification_rule": (payload.get("positivePersFilter") or {}).get("rule"),
        "n_models": len(models),
        "n_input_catalog": len(catalog),
        "types": dict(sorted(types.items())),
        "horizons": dict(sorted(horizons.items(), key=lambda item: HORIZONS.index(item[0]) if item[0] in HORIZONS else 99)),
        "families": dict(sorted(families.items())),
        "neuronios_por_input_mediana": r3(median(ratios) if ratios else None),
        "by_family": group_rows(models, catalog),
        "by_horizon": [
            {
                "horizonte": horizon,
                "n": sum(1 for item in models if item.get("horizonte") == horizon),
                "MAE_teste_cm_mediana": med(
                    [item["MAE_teste_cm"] for item in models if item.get("horizonte") == horizon]
                ),
                "equilibrio_mediana": med(
                    [item["score_equilibrio"] for item in models if item.get("horizonte") == horizon]
                ),
                "PERS_teste_mediana": med(
                    [item["PERS_teste"] for item in models if item.get("horizonte") == horizon]
                ),
                "n_equilibrio_gt_050": sum(
                    1
                    for item in models
                    if item.get("horizonte") == horizon and (item.get("score_equilibrio") or 0) > 0.5
                ),
            }
            for horizon in HORIZONS
        ],
        "rain_contrast": rain_contrast(models, catalog),
        "champions": {horizon: unique_top(models, catalog, horizon) for horizon in HORIZONS},
        "two_hour_models": two_hour,
        "eight_hour_extremes": eight_hour_extremes(models, catalog),
        "input_frequency_best_quartile": input_frequency(models, catalog),
        "live_principal_2h": "009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21",
        "codex_reports_superseded": [
            {
                "id": "rna-relatorio-geral",
                "href": "pesquisas/rna-relatorio-geral.html",
                "date": "2026-06-05",
                "scope": "20 rodadas prioritárias de 4h",
                "limit": "Ranking por NASH_TESTE de uma bateria pequena; não é o recorte consolidado de 117 modelos 4h.",
            },
            {
                "id": "relatorio-tecnico-8h",
                "href": "pesquisas/relatorio-tecnico-8h.html",
                "date": "2026-06-28",
                "scope": "Uma rodada 8h ALT/CONV (32 redes, 25 auditáveis)",
                "limit": "Ranking por PERS geral sem rotação completa; o recorte posterior muda o campeão conforme equilíbrio e E95.",
            },
            {
                "id": "plano-exploracao-8h",
                "href": "pesquisas/plano-exploracao-8h.html",
                "date": "2026-06-29",
                "scope": "Plano da primeira onda ALT 8h (48 redes previstas)",
                "limit": "Documento de fila, não resultado consolidado.",
            },
        ],
    }


def main() -> int:
    report = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT).as_posix()}")
    print(f"models={report['n_models']} 2h={report['horizons'].get('2h')} 4h={report['horizons'].get('4h')} 8h={report['horizons'].get('8h')} 12h={report['horizons'].get('12h')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
