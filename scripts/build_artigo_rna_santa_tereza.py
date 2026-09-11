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


LAG_PAREN = re.compile(r"\(([DA])[-\s]?(\d+)\s*h?\)", re.I)
LAG_WORD = re.compile(r"\b([DA])[-\s]?(\d+)\s*H\b", re.I)
LAG_UNDERSCORE = re.compile(r"_([DA])(\d+)h", re.I)
STATION_CODE = re.compile(r"\b(86\d{6})\b")
COMBO_CODE = re.compile(r"(C\d{4})")
METRIC_KEYS = frozenset(
    {
        "PERS_geral",
        "PERS_treino",
        "PERS_validacao",
        "PERS_teste",
        "score_equilibrio",
        "MAE_teste_cm",
        "E95_teste_cm",
        "NASH_teste",
        "equilibrio_mediana",
        "equilibrio_max",
        "PERS_teste_mediana",
        "PERS_geral_mediana",
        "MAE_teste_cm_mediana",
        "E95_teste_cm_mediana",
        "NASH_teste_mediana",
    }
)


def uses_rain(names: list[str]) -> bool:
    return any("chuva" in name.lower() for name in names)


def combo_code(combo_id: Any) -> str | None:
    match = COMBO_CODE.search(str(combo_id or ""))
    return match.group(1) if match else None


def _strip_lag(name: str) -> tuple[str, str]:
    for pattern in (LAG_PAREN, LAG_WORD, LAG_UNDERSCORE):
        match = pattern.search(name)
        if match:
            kind = match.group(1).upper()
            hours = int(match.group(2))
            stripped = f"{name[: match.start()]} {name[match.end():]}".strip()
            stripped = re.sub(r"[\s\-]+$", "", stripped)
            return stripped, f" {kind}–{hours} h"
    return name, ""


def short_label(name: str) -> str:
    """Compact label for the methodology quadro (variables only, no metrics)."""
    raw = " ".join(str(name).replace("—", " ").replace("–", "-").split())
    raw = raw.replace("Veranopolis", "Veranópolis")
    if "chuva" in raw.lower() or raw.lower().startswith("acum 36h"):
        return "chuva 36 h"
    stripped, lag = _strip_lag(raw)
    low = stripped.lower()
    if "montante" in low:
        return "montante" + lag
    if "carreiro" in low:
        return "Carreiro" + lag
    if "ituim" in low:
        return "Ituim" + lag
    if "veranóp" in low:
        return "Veranópolis" + lag
    if "prata" in low:
        return "Prata Caxias" + lag
    code = STATION_CODE.search(stripped) or STATION_CODE.search(raw)
    if code:
        number = code.group(1)
        if number == "86472600":
            return "ST" + lag
        return number + lag
    if "santa tereza" in low:
        return "ST" + lag
    return (stripped or raw) + lag


def canonical_key(names: list[str]) -> tuple[str, ...]:
    return tuple(sorted(short_label(item) for item in names))


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


def unique_sets_by_horizon(models: list[dict[str, Any]], catalog: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for horizon in HORIZONS:
        keys = {
            canonical_key(input_names(model, catalog))
            for model in models
            if model.get("horizonte") == horizon
        }
        counts[horizon] = len(keys)
    return counts


def combination_row(
    horizonte: str,
    combo_id: str,
    label: str,
    pool: list[dict[str, Any]],
    catalog: list[str],
    note: str | None = None,
) -> dict[str, Any]:
    if not pool:
        raise ValueError(f"combinação vazia: {horizonte} {combo_id}")
    groups: Counter[tuple[str, ...]] = Counter()
    samples: dict[tuple[str, ...], list[str]] = {}
    for model in pool:
        names = input_names(model, catalog)
        key = canonical_key(names)
        groups[key] += 1
        samples.setdefault(key, names)
    names = samples[groups.most_common(1)[0][0]]
    shorts = [short_label(item) for item in names]
    row = {
        "horizonte": horizonte,
        "id": combo_id,
        "label": label,
        "n_inputs": int(pool[0].get("n_inputs") or len(shorts)),
        "n_redes": len(pool),
        "chuva": uses_rain(names),
        "variables_short": shorts,
        "variables_full": names,
        "note": note,
    }
    leaked = METRIC_KEYS.intersection(row)
    if leaked:
        raise ValueError(f"quadro metodológico não pode carregar métricas: {leaked}")
    return row


def principal_combinations(models: list[dict[str, Any]], catalog: list[str]) -> list[dict[str, Any]]:
    """Main input sets for the methodology quadro — variables only, no scores."""

    def by_horizon(horizon: str) -> list[dict[str, Any]]:
        return [model for model in models if model.get("horizonte") == horizon]

    def by_code(horizon: str, code: str) -> list[dict[str, Any]]:
        return [model for model in by_horizon(horizon) if combo_code(model.get("combo_id")) == code]

    def by_n_inputs(horizon: str, n_inputs: int) -> list[dict[str, Any]]:
        return [model for model in by_horizon(horizon) if model.get("n_inputs") == n_inputs]

    return [
        combination_row(
            "2h",
            "2H",
            "Nível local e montante, sem chuva",
            by_horizon("2h"),
            catalog,
            "Única montagem do recorte 2 h (dez rotações).",
        ),
        combination_row(
            "4h",
            "núcleo",
            "Núcleo 4 h",
            by_n_inputs("4h", 13),
            catalog,
            "Menor conjunto das seis montagens aninhadas (13 ⊂ 14 ⊂ 15 ⊂ 16 ⊂ 20 ⊂ 24).",
        ),
        combination_row(
            "4h",
            "núcleo+86298000",
            "Núcleo + ST A–1 h + ST A–4 h + 86298000",
            by_n_inputs("4h", 16),
            catalog,
            None,
        ),
        combination_row(
            "4h",
            "ampliado",
            "Núcleo ampliado (Carreiro e mais defasagens)",
            by_n_inputs("4h", 24),
            catalog,
            "Montagem do modelo escolhido em 4 h.",
        ),
        combination_row(
            "8h",
            "C0289",
            "C0289",
            by_code("8h", "C0289"),
            catalog,
            "Combinação mais recorrente no 8 h (ALT e CONV).",
        ),
        combination_row(
            "8h",
            "C0078",
            "C0078",
            by_code("8h", "C0078"),
            catalog,
            None,
        ),
        combination_row(
            "8h",
            "C0265",
            "C0265",
            by_code("8h", "C0265"),
            catalog,
            "Montagem mais enxuta entre as frequentes do 8 h.",
        ),
        combination_row(
            "12h",
            "C0149",
            "C0149",
            by_code("12h", "C0149"),
            catalog,
            "Montagem do modelo escolhido em 12 h.",
        ),
    ]


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
    champions = {horizon: unique_top(models, catalog, horizon, n=1)[0] for horizon in HORIZONS}
    return {
        "schema_version": "previne_artigo_rna_santa_tereza_v2",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "official_alert": False,
        "purpose": "Quadro metodológico das combinações principais de variáveis e métricas só do melhor modelo de cada horizonte. Não é alerta, ordem de evacuação, rota ou despacho.",
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
        "n_unique_input_sets": unique_sets_by_horizon(models, catalog),
        "principal_combinations": principal_combinations(models, catalog),
        "champions": champions,
        "eight_hour_extremes": eight_hour_extremes(models, catalog),
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
