#!/usr/bin/env python3
"""HEC-HMS Python twin calibration for STZ and Muçum target models.

Uses estrutura_stz_mucum (Prata named + Carreiro split).
Linux has no HEC-HMS 4.13 binary — this is the auditável twin
(Initial+Constant / Clark / Recession / Muskingum), same family as carreiro_split.

- Muçum: calibrate vs ANA Vazao 86510000
- STZ: Q calibration BLOCKED (ANA has Nivel, empty Vazao) — reports diagnostic only

Not operational alert. Linux twin of HEC methods (not the Windows HEC-HMS 4.13 binary).
"""

from __future__ import annotations

import csv
import html
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ESTRUTURA = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas" / "estrutura_stz_mucum_latest.json"
CARREIRO_RAW = ROOT / "assets" / "data" / "hec_hms_carreiro_split" / "raw_ana"
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
RUN = OUT / "hec_twin_stz_mucum_v1"

EVENTS = {
    "E19": ("2023-05-06 10:00:00", "2023-05-08 14:00:00"),
    "E20": ("2023-06-15 20:00:00", "2023-06-19 12:00:00"),
    "E21": ("2023-07-10 09:00:00", "2023-07-16 22:00:00"),
    "E22": ("2023-09-04 00:00:00", "2023-09-12 07:00:00"),
    "E23": ("2023-09-19 19:00:00", "2023-09-22 16:00:00"),
    "E24": ("2023-11-16 00:00:00", "2023-11-25 23:00:00"),
    "E25": ("2024-01-18 17:00:00", "2024-01-21 06:00:00"),
    "E26": ("2024-04-14 12:00:00", "2024-04-15 18:00:00"),
    "E27": ("2024-04-29 16:00:00", "2024-05-09 20:00:00"),
    "E28": ("2024-06-16 10:00:00", "2024-06-25 02:00:00"),
    "E29": ("2024-08-24 09:00:00", "2024-08-25 08:00:00"),
    "E30": ("2024-10-11 20:00:00", "2024-10-14 17:00:00"),
    "E31": ("2025-06-28 19:00:00", "2025-07-04 02:00:00"),
}

# External hold-outs: never used to fit common-search; scored after the fact.
EXTERNAL_HOLDOUT_EVENTS = ("E26", "E30", "E31")
# PAD sweep uses a compact flood subset for speed/stability.
PAD_SWEEP_EVENTS = ("E21", "E22", "E24", "E27", "E28", "E31")

PAD_HOURS_DEFAULT = 0  # overwritten by select_pad(); score only on core event window
PAD_CANDIDATES = (0, 12, 24)

# Prefer native rain; fall back without inventing zeros (skip hour if none)
# 2851072 = Ibiraiaras (ANA) — densifica Prata/Antas; já em chuvas_horarias / telemetria.
RAIN_PREF = {
    "SB_PRATA_7868": ["86472000", "2851072", "86507000"],
    "SB_ANTAS_RESIDUAL": ["86472000", "2851072", "86507000"],
    "SB_CARREIRO_7866": ["86507000", "86472000", "86510000", "2851072"],
    "SB_STZ_RESIDUAL": ["86472600", "86472000", "86510000", "2851072"],
    "SB_INC_MUCUM": ["86510000", "86472600", "86472000"],
}

RAIN_STATIONS_LOAD = ("86472000", "86472600", "86507000", "86510000", "2851072")


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def fmt_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def expected_hours(start: datetime, end: datetime) -> list[str]:
    from datetime import timedelta

    out = []
    t = start
    while t <= end:
        out.append(fmt_ts(t))
        t += timedelta(hours=1)
    return out


def event_windows(event_id: str, pad_hours: int) -> tuple[list[str], list[str], int]:
    """Return (sim_hours, core_hours, core_offset).

    Tries pad_hours warm-up when rain coverage allows; otherwise core-only.
    """
    from datetime import timedelta

    start_s, end_s = EVENTS[event_id]
    core_start = parse_ts(start_s)
    core_end = parse_ts(end_s)
    core_hours = expected_hours(core_start, core_end)
    if pad_hours <= 0:
        return core_hours, core_hours, 0
    pad_start = core_start - timedelta(hours=pad_hours)
    sim_hours = expected_hours(pad_start, core_end)
    return sim_hours, core_hours, pad_hours


def prepare_event_forcing(
    event_id: str,
    subbasins: list[str],
    pad_hours: int,
) -> tuple[dict[str, list[float]] | None, dict[str, Any], list[str], dict[str, float], int, list[str]]:
    """Build precip + flow aligned to optional warm-up pad."""
    pad_sim, core_hours, pad = event_windows(event_id, pad_hours)
    flow = hourly_field(load_event_series("86510000", event_id), "Vazao", reduce="mean")
    precip, rain_meta = build_precip_for_event(
        event_id, pad_sim, subbasins, magnitude_hours=core_hours
    )
    core_offset = pad
    hours = pad_sim
    if precip is None:
        precip, rain_meta = build_precip_for_event(
            event_id, core_hours, subbasins, magnitude_hours=core_hours
        )
        core_offset = 0
        hours = core_hours
        if rain_meta is not None:
            rain_meta = dict(rain_meta)
            rain_meta["warm_up"] = {
                "requested_hours": pad_hours,
                "applied": False,
                "reason": "pad_rain_incomplete",
            }
    else:
        rain_meta = dict(rain_meta or {})
        rain_meta["warm_up"] = {
            "requested_hours": pad_hours,
            "applied": pad_hours > 0 and core_offset > 0,
            "sim_hours": len(hours),
        }
    return precip, rain_meta, hours, flow, core_offset, core_hours


def e19_forcing_note(rain_meta: dict[str, Any] | None, flow: dict[str, float], core_hours: list[str]) -> str:
    """Local rain on E19 is too light to explain Muçum peak without upstream routing mass."""
    obs = [flow[h] for h in core_hours if h in flow]
    peak = max(obs) if obs else float("nan")
    core_sums = list((rain_meta or {}).get("stations_mm_sum_core", {}).values())
    rain_mm = max(core_sums) if core_sums else float("nan")
    return (
        f"E19 fit_failed: chuva local core máx ~{rain_mm:.0f} mm vs pico obs ~{peak:.0f} m³/s. "
        "Forçamento pluviométrico insuficiente para a onda (provável massa de montante/routing). "
        "Headline = média NSE>=0 (E22–E28)."
    )


def select_pad(
    areas: dict[str, float],
    subbasins: list[str],
    params_list: list[Params],
) -> dict[str, Any]:
    """Pick PAD that maximizes mean eventwise research_score on E22–E28."""
    trials = []
    for pad in PAD_CANDIDATES:
        by_event_nse: dict[str, float] = {}
        by_event_score: dict[str, float] = {}
        for event_id in PAD_SWEEP_EVENTS + ("E19",):
            precip, _meta, hours, flow, core_offset, core_hours = prepare_event_forcing(
                event_id, subbasins, pad
            )
            if precip is None:
                by_event_nse[event_id] = float("nan")
                by_event_score[event_id] = float("nan")
                continue
            best_score = float("-inf")
            best_nse = float("-inf")
            for p in params_list:
                m, sc, _sim = score_event(
                    precip, areas, p, hours, flow, core_offset=core_offset, core_hours=core_hours
                )
                if sc > best_score:
                    best_score = sc
                    best_nse = m["nse"]
            by_event_nse[event_id] = best_nse
            by_event_score[event_id] = best_score
        ok_ids = tuple(e for e in PAD_SWEEP_EVENTS)
        ok_scores = [by_event_score[e] for e in ok_ids if by_event_nse.get(e, float("-inf")) >= 0]
        ok_nses = [by_event_nse[e] for e in ok_ids if by_event_nse.get(e, float("-inf")) >= 0]
        mean_score = sum(ok_scores) / len(ok_scores) if ok_scores else float("-inf")
        mean_ok = sum(ok_nses) / len(ok_nses) if ok_nses else float("-inf")
        trials.append(
            {
                "pad_hours": pad,
                "event_nse": {k: (None if v != v else round(v, 4)) for k, v in by_event_nse.items()},
                "event_research_score": {
                    k: (None if v != v else round(v, 4)) for k, v in by_event_score.items()
                },
                "mean_research_score_e22_e28_ok": None if mean_score != mean_score else round(mean_score, 4),
                "mean_nse_e22_e28_ok": None if mean_ok != mean_ok else round(mean_ok, 4),
            }
        )
    best = max(
        trials,
        key=lambda t: t["mean_research_score_e22_e28_ok"]
        if t["mean_research_score_e22_e28_ok"] is not None
        else -999,
    )
    return {
        "candidates": list(PAD_CANDIDATES),
        "trials": trials,
        "selected_pad_hours": best["pad_hours"],
        "selection_rule": "argmax mean research_score on E22–E28 (same objective as eventwise fit)",
        "note": "PAD=24 melhorava E19 mas regredia E22; v1.3 escolhe PAD pelo score E22–E28.",
    }


def score_event(
    precip: dict[str, list[float]],
    areas: dict[str, float],
    params: Params,
    hours: list[str],
    flow: dict[str, float],
    *,
    core_offset: int,
    core_hours: list[str],
) -> tuple[dict[str, float], float, list[float]]:
    sim_full = run_network(precip, areas, params, include_mucum_increment=True)["at_mucum"]
    # Align simulation to core window
    sim_core = sim_full[core_offset : core_offset + len(core_hours)]
    paired = [i for i, h in enumerate(core_hours) if h in flow]
    obs = [flow[core_hours[i]] for i in paired]
    sim_p = [sim_core[i] for i in paired]
    m = metrics(obs, sim_p)
    return m, research_score(m), sim_full


def evaluate_params_on_events(
    params: Params,
    event_ids: list[str],
    precip_cache: dict[str, Any],
    areas: dict[str, float],
) -> tuple[list[dict[str, Any]], float, float]:
    details = []
    scores = []
    nses = []
    for event_id in event_ids:
        precip, _rain, hours, flow, core_offset, core_hours = precip_cache[event_id]
        m, score, _sim = score_event(
            precip, areas, params, hours, flow, core_offset=core_offset, core_hours=core_hours
        )
        details.append({"event_id": event_id, **m})
        scores.append(score)
        nses.append(m["nse"])
    mean_score = sum(scores) / len(scores)
    mean_nse = sum(nses) / len(nses)
    return details, mean_score, mean_nse


def calibrate_mucum(areas: dict[str, float]) -> dict[str, Any]:
    subbasins = [
        "SB_PRATA_7868",
        "SB_ANTAS_RESIDUAL",
        "SB_CARREIRO_7866",
        "SB_STZ_RESIDUAL",
        "SB_INC_MUCUM",
    ]
    params_list = candidate_grid()
    pad_selection = select_pad(areas, subbasins, params_list)
    pad_hours = int(pad_selection["selected_pad_hours"])

    event_results = []
    precip_cache: dict[str, Any] = {}

    for event_id in EVENTS:
        precip, rain_meta, hours, flow, core_offset, core_hours = prepare_event_forcing(
            event_id, subbasins, pad_hours
        )
        paired = [i for i, h in enumerate(core_hours) if h in flow]
        row: dict[str, Any] = {
            "event_id": event_id,
            "rain": rain_meta,
            "observed_points": len(paired),
            "status": "blocked",
        }
        if precip is None or len(paired) < 12:
            row["reason"] = (rain_meta or {}).get("blocked_reason") or "insufficient observed Vazao at Muçum"
            event_results.append(row)
            continue

        precip_cache[event_id] = (precip, rain_meta, hours, flow, core_offset, core_hours)

        best_p = None
        best_m = None
        best_score = float("-inf")
        best_sim = None
        for p in params_list:
            m, score, sim_full = score_event(
                precip, areas, p, hours, flow, core_offset=core_offset, core_hours=core_hours
            )
            if score > best_score:
                best_score, best_p, best_m, best_sim = score, p, m, sim_full

        assert best_p is not None and best_m is not None and best_sim is not None
        series_path = RUN / f"mucum_{event_id}_best_series.csv"
        with series_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "obs_m3s", "sim_m3s", "in_core_window"])
            for i, h in enumerate(hours):
                in_core = 1 if i >= core_offset else 0
                obs = flow.get(h, "") if in_core else ""
                w.writerow([h, obs, f"{best_sim[i]:.4f}", in_core])

        status = "eventwise_scored"
        if best_m["nse"] < 0:
            status = "fit_failed_eventwise"
        row.update(
            {
                "status": status,
                "optimization_objective": "research_score = NSE - 0.05*|peak_lag| - 0.5*peak_relative_error",
                "score": best_score,
                "metrics": best_m,
                "params": asdict(best_p),
                "warm_up_hours_applied": core_offset,
                "series_csv": str(series_path.relative_to(ROOT)),
            }
        )
        if event_id == "E19":
            row["forcing_note"] = e19_forcing_note(rain_meta, flow, core_hours)
        event_results.append(row)

    scored = [r for r in event_results if r["status"] in ("eventwise_scored", "fit_failed_eventwise")]
    scored_ok = [r for r in scored if r["status"] == "eventwise_scored"]
    mean_nse_all = (
        sum(r["metrics"]["nse"] for r in scored) / len(scored) if scored else float("nan")
    )
    mean_nse_ok = (
        sum(r["metrics"]["nse"] for r in scored_ok) / len(scored_ok) if scored_ok else float("nan")
    )

    common_ids = [
        r["event_id"]
        for r in scored_ok
        if r["event_id"] not in EXTERNAL_HOLDOUT_EVENTS
    ]
    external_ids = [e for e in EXTERNAL_HOLDOUT_EVENTS if e in precip_cache]

    def best_common_for(ids: list[str]) -> dict[str, Any]:
        best_p = None
        best_score = float("-inf")
        best_detail = None
        best_mean_nse = None
        for p in params_list:
            details, mean_score, mean_nse = evaluate_params_on_events(p, ids, precip_cache, areas)
            if mean_score > best_score:
                best_score = mean_score
                best_p = p
                best_detail = details
                best_mean_nse = mean_nse
        return {
            "runnable_events": ids,
            "candidates_evaluated": len(params_list),
            "best_params": None if best_p is None else asdict(best_p),
            "best_mean_research_score": None if best_p is None else best_score,
            "best_event_metrics": best_detail,
            "mean_nse": best_mean_nse,
        }

    common_all = best_common_for(common_ids) if common_ids else {
        "runnable_events": [],
        "candidates_evaluated": len(params_list),
        "best_params": None,
        "best_mean_research_score": None,
        "best_event_metrics": None,
        "mean_nse": None,
    }

    # Hold-out E27 inside the calibration pool (excluding true externals)
    train_ids = [e for e in common_ids if e != "E27"]
    holdout: dict[str, Any] = {
        "train_events": train_ids,
        "test_event": "E27" if "E27" in common_ids else None,
    }
    if len(train_ids) >= 2 and "E27" in common_ids:
        fitted = best_common_for(train_ids)
        p = Params(**fitted["best_params"])
        test_details, test_score, test_nse = evaluate_params_on_events(
            p, ["E27"], precip_cache, areas
        )
        holdout.update(
            {
                "fit": fitted,
                "test_metrics": test_details[0],
                "test_research_score": test_score,
                "test_nse": test_nse,
                "note": "Params comuns no pool de calibração (sem E26/E30/E31); E27 é hold-out interno.",
            }
        )
    else:
        holdout["note"] = "Hold-out E27 indisponível"

    # True external validation: params from full common_ids (no externals in train)
    external_validation: dict[str, Any] = {
        "events": list(EXTERNAL_HOLDOUT_EVENTS),
        "train_events": common_ids,
        "results": [],
    }
    if common_all.get("best_params") and external_ids:
        p = Params(**common_all["best_params"])
        for eid in external_ids:
            det, sc, nse = evaluate_params_on_events(p, [eid], precip_cache, areas)
            external_validation["results"].append(
                {"event_id": eid, "research_score": sc, "nse": nse, "metrics": det[0]}
            )
        external_validation["mean_test_nse"] = sum(
            x["nse"] for x in external_validation["results"]
        ) / len(external_validation["results"])
        external_validation["note"] = (
            "E26/E30/E31 nunca entraram no fit do common-search; teste externo verdadeiro."
        )
    else:
        external_validation["mean_test_nse"] = None
        external_validation["note"] = "Sem params comuns ou sem eventos externos runnable"

    loo = []
    loo_pool = [e for e in common_ids if e in precip_cache]
    if common_all.get("best_params") and len(loo_pool) >= 3:
        # Cap LOO cost: prefer larger floods when pool is big
        if len(loo_pool) > 6:
            peaks = []
            for eid in loo_pool:
                _p, _r, _h, flow, _o, core_hours = precip_cache[eid]
                vals = [flow[h] for h in core_hours if h in flow]
                peaks.append((max(vals) if vals else 0.0, eid))
            peaks.sort(reverse=True)
            loo_pool = [eid for _pk, eid in peaks[:6]]
        for left in loo_pool:
            train = [e for e in loo_pool if e != left]
            fitted = best_common_for(train)
            p = Params(**fitted["best_params"])
            det, sc, nse = evaluate_params_on_events(p, [left], precip_cache, areas)
            loo.append(
                {
                    "left_out": left,
                    "train_events": train,
                    "train_mean_nse": fitted["mean_nse"],
                    "test_nse": nse,
                    "test_metrics": det[0],
                }
            )

    holdout_nse = holdout.get("test_nse")
    loo_mean = sum(x["test_nse"] for x in loo) / len(loo) if loo else None
    ext_mean = external_validation.get("mean_test_nse")
    promotion_blocked = True
    if (
        holdout_nse is not None
        and loo_mean is not None
        and ext_mean is not None
        and holdout_nse >= 0.5
        and loo_mean >= 0.5
        and ext_mean >= 0.4
    ):
        promotion_blocked = False

    e19_row = next((r for r in event_results if r["event_id"] == "E19"), None)
    e19_note = (
        e19_row.get("forcing_note")
        if e19_row and e19_row.get("forcing_note")
        else (
            "E19 tipicamente fit_failed (NSE fortemente negativo). "
            "Headline = média dos eventos com NSE>=0."
        )
    )

    common_search = {
        **common_all,
        "pad_hours": pad_hours,
        "holdout_e27": holdout,
        "external_holdout": external_validation,
        "leave_one_out": loo,
        "leave_one_out_mean_test_nse": loo_mean,
        "note": (
            "Common-search v1.4: pool sem E26/E30/E31; hold-out E27 + LOO + externos. "
            "Promover só se hold-out/LOO/externos forem aceitáveis."
        ),
        "promotion_blocked": promotion_blocked,
        "promotion_rule": (
            "holdout_E27_nse>=0.5 and loo_mean_test_nse>=0.5 and external_mean_nse>=0.4"
        ),
    }

    gaps = [
        {
            "id": "common_params_transfer",
            "status": "open" if promotion_blocked else "closed",
            "detail": (
                f"hold-out E27 NSE={holdout_nse}; LOO médio={loo_mean}; "
                f"externos E26/E30/E31 médio={ext_mean}. "
                "Usar params eventwise enquanto bloqueado."
            ),
        },
        {
            "id": "e19_local_rain_underforced",
            "status": "open" if (e19_row or {}).get("status") == "fit_failed_eventwise" else "closed",
            "detail": e19_note,
        },
        {
            "id": "spatial_rain_density",
            "status": "partial",
            "detail": (
                "v1.4: 2851072 (Ibiraiaras) + média aritmética dos pluviômetros completos "
                "em Prata/Antas. Carreiro ainda com fallback de magnitude."
            ),
        },
        {
            "id": "external_event_validation",
            "status": "partial",
            "detail": (
                f"Externos E26/E30/E31 rodados; mean_nse={ext_mean}. "
                "Continuar ampliando conforme novos eventos."
            ),
        },
        {
            "id": "stz_q_curve",
            "status": "open",
            "detail": (
                "86472600 sem Vazão ANA nos eventos; curva-chave oficial não está no pacote. "
                "Bloqueia calibração do modelo STZ."
            ),
        },
    ]

    return {
        "target": "86510000",
        "target_name": "Muçum",
        "quantity": "Vazao_m3s",
        "structure": "modelo_mucum_estrutura_stz_mucum_v1",
        "mode": "eventwise_plus_common_search_v1_4",
        "calibration_version": "mucum_hec_twin_v1_4",
        "hold_out": True,
        "external_holdout_events": list(EXTERNAL_HOLDOUT_EVENTS),
        "pad_hours": pad_hours,
        "pad_selection": pad_selection,
        "n_events_scored": len(scored),
        "n_events_fit_ok": len(scored_ok),
        "mean_nse_eventwise_including_failed": mean_nse_all,
        "mean_nse_eventwise": mean_nse_ok,
        "mean_nse_eventwise_excluding_e19": mean_nse_ok,
        "n_events_excluding_e19": len(scored_ok),
        "mean_nse_eventwise_including_e19": mean_nse_all,
        "e19_note": e19_note,
        "gaps_remaining": gaps,
        "common_search": common_search,
        "events": event_results,
    }


def parse_telemetry(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size < 50:
        return []
    root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    rows = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "DadosHidrometereologicos":
            continue
        rows.append({c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in el})
    return rows


def hourly_field(rows: list[dict[str, str]], field: str, *, reduce: str = "mean") -> dict[str, float]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        raw_t = row.get("DataHora") or row.get("dataHora") or ""
        raw_v = row.get(field, "")
        if not raw_t or raw_v == "":
            continue
        try:
            if "T" in raw_t[:20]:
                # 2024-06-16T10:00:00
                hour = raw_t[:13].replace("T", " ") + ":00:00"
            elif "/" in raw_t:
                dt = datetime.strptime(raw_t[:19], "%d/%m/%Y %H:%M:%S")
                hour = fmt_ts(dt.replace(minute=0, second=0))
            else:
                # 2024-06-16 10:00:00
                dt = datetime.strptime(raw_t[:19], "%Y-%m-%d %H:%M:%S")
                hour = fmt_ts(dt.replace(minute=0, second=0))
            buckets[hour].append(float(raw_v.replace(",", ".")))
        except ValueError:
            continue
    out = {}
    for h, vs in buckets.items():
        out[h] = (sum(vs) if reduce == "sum" else sum(vs) / len(vs))
    return out


def load_event_series(station: str, event_id: str) -> list[dict[str, str]]:
    path = CARREIRO_RAW / f"telemetry_{station}_{event_id}.xml"
    return parse_telemetry(path)


@dataclass
class Params:
    initial_loss: float
    constant_loss: float
    tc: float
    storage: float
    recession: float
    initial_flow_ratio: float
    k1: float
    k2: float
    k3: float
    x: float = 0.2


def clark_uh(tc_h: float, r_h: float, dt_h: float = 1.0) -> list[float]:
    tc = max(float(tc_h), dt_h)
    r = max(float(r_h), 0.1)
    n = int(math.ceil((tc + 5.0 * r) / dt_h)) + 3
    translated = [0.0] * n
    steps = max(1, int(round(tc / dt_h)))
    for i in range(steps):
        translated[i] += 1.0 / steps
    coef = math.exp(-dt_h / r)
    storage_outflow = 0.0
    out = [0.0] * n
    for i in range(n):
        storage_outflow = storage_outflow * coef + translated[i] * (1.0 - coef)
        out[i] = storage_outflow
    total = sum(out) or 1.0
    return [v / total for v in out]


def apply_loss(precip: list[float], initial_loss: float, constant_loss: float) -> list[float]:
    remaining = initial_loss
    excess = []
    for p in precip:
        if remaining > 0:
            used = min(remaining, p)
            remaining -= used
            p = p - used
        excess.append(max(0.0, p - constant_loss))
    return excess


def convolute(excess: list[float], uh: list[float]) -> list[float]:
    n = len(excess)
    m = len(uh)
    out = [0.0] * (n + m - 1)
    for i, e in enumerate(excess):
        if e == 0:
            continue
        for j, u in enumerate(uh):
            out[i + j] += e * u
    return out[:n]


def excess_to_flow(excess_mm: list[float], area_km2: float, uh: list[float]) -> list[float]:
    return [q * area_km2 / 3.6 for q in convolute(excess_mm, uh)]


def recession_baseflow(n: int, area_km2: float, ratio: float, k: float) -> list[float]:
    q = max(ratio, 0.0) * area_km2
    base = []
    for _ in range(n):
        base.append(q)
        q *= k
    return base


def muskingum(inflow: list[float], k_h: float, x: float, dt_h: float = 1.0) -> list[float]:
    k = max(k_h, dt_h * 0.1)
    x = min(max(x, 0.0), 0.5)
    denom = 2 * k * (1 - x) + dt_h
    c0 = (dt_h - 2 * k * x) / denom
    c1 = (dt_h + 2 * k * x) / denom
    c2 = (2 * k * (1 - x) - dt_h) / denom
    out = [0.0] * len(inflow)
    if not inflow:
        return out
    out[0] = inflow[0]
    for i in range(1, len(inflow)):
        out[i] = max(0.0, c0 * inflow[i] + c1 * inflow[i - 1] + c2 * out[i - 1])
    return out


def run_network(
    precip_by_sb: dict[str, list[float]],
    areas: dict[str, float],
    params: Params,
    *,
    include_mucum_increment: bool,
) -> dict[str, list[float]]:
    """Run twin.

    Prata + Antas residual share the same gage depth; applying Initial+Constant
    separately would double-count initial loss. They are runoff-lumped here,
    matching the Carreiro-split Antas bucket, while the structure still names Prata.
    """
    uh = clark_uh(params.tc, params.storage)
    n = len(next(iter(precip_by_sb.values())))

    antas_area = areas["SB_PRATA_7868"] + areas["SB_ANTAS_RESIDUAL"]
    # Prefer Antas residual rain series (86472000); identical to Prata prefs when complete
    antas_precip = precip_by_sb.get("SB_ANTAS_RESIDUAL") or precip_by_sb["SB_PRATA_7868"]
    antas_excess = apply_loss(antas_precip, params.initial_loss, params.constant_loss)
    antas_direct = excess_to_flow(antas_excess, antas_area, uh)
    antas_base = recession_baseflow(n, antas_area, params.initial_flow_ratio, params.recession)
    at_antas = [d + b for d, b in zip(antas_direct, antas_base)]

    def one(sb: str) -> list[float]:
        excess = apply_loss(precip_by_sb[sb], params.initial_loss, params.constant_loss)
        direct = excess_to_flow(excess, areas[sb], uh)
        base = recession_baseflow(n, areas[sb], params.initial_flow_ratio, params.recession)
        return [d + b for d, b in zip(direct, base)]

    carreiro = one("SB_CARREIRO_7866")
    residual = one("SB_STZ_RESIDUAL")

    after_r1 = muskingum(at_antas, params.k1, params.x)
    at_carreiro = [a + c for a, c in zip(after_r1, carreiro)]
    after_r2 = muskingum(at_carreiro, params.k2, params.x)
    at_stz = [a + r for a, r in zip(after_r2, residual)]

    result = {"at_antas": at_antas, "at_carreiro": at_carreiro, "at_stz": at_stz}
    if include_mucum_increment:
        mucum_inc = one("SB_INC_MUCUM")
        after_r3 = muskingum(at_stz, params.k3, params.x)
        result["at_mucum"] = [a + m for a, m in zip(after_r3, mucum_inc)]
    return result


def metrics(obs: list[float], sim: list[float]) -> dict[str, float]:
    n = min(len(obs), len(sim))
    obs, sim = obs[:n], sim[:n]
    if n < 3:
        return {"pairs": float(n), "nse": float("-inf"), "rmse_m3s": float("nan"), "peak_lag_hours": float("nan"), "peak_relative_error": float("nan")}
    mean_o = sum(obs) / n
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - mean_o) ** 2 for o in obs) or 1e-9
    i_obs = max(range(n), key=lambda i: obs[i])
    i_sim = max(range(n), key=lambda i: sim[i])
    peak_o, peak_s = obs[i_obs], sim[i_sim]
    return {
        "pairs": float(n),
        "nse": 1.0 - ss_res / ss_tot,
        "rmse_m3s": math.sqrt(ss_res / n),
        "mae_m3s": sum(abs(o - s) for o, s in zip(obs, sim)) / n,
        "peak_lag_hours": float(i_sim - i_obs),
        "peak_relative_error": abs(peak_s - peak_o) / peak_o if peak_o else float("nan"),
        "observed_peak_m3s": peak_o,
        "simulated_peak_m3s": peak_s,
    }


def research_score(m: dict[str, float]) -> float:
    lag = abs(m["peak_lag_hours"]) if m["peak_lag_hours"] == m["peak_lag_hours"] else 99
    pre = m["peak_relative_error"] if m["peak_relative_error"] == m["peak_relative_error"] else 9
    return m["nse"] - 0.05 * lag - 0.5 * pre


def candidate_grid() -> list[Params]:
    seeds = [
        Params(2.5, 2.0, 25.0, 25.0, 0.80, 0.003, 1.0, 1.0, 1.0),
        Params(2.5, 2.0, 25.0, 45.0, 0.80, 0.0025, 1.0, 1.0, 1.0),
        Params(5.5, 0.88, 22.5, 34.3, 0.70, 0.001, 1.0, 1.0, 1.0),
        Params(1.0, 4.0, 4.0, 90.0, 0.98, 0.005, 1.0, 1.0, 1.0),
        Params(0.0, 2.0, 10.0, 60.0, 0.85, 0.0025, 1.0, 1.0, 1.0),
        Params(1.0, 2.0, 10.0, 45.0, 0.85, 0.0025, 0.5, 1.0, 1.0),
        Params(2.5, 1.0, 20.0, 60.0, 0.80, 0.0025, 2.0, 2.0, 1.0),
        Params(2.5, 1.0, 4.0, 45.0, 0.98, 0.0025, 0.5, 0.5, 0.5),
        # High baseflow seeds (small / routed events like E19)
        Params(0.0, 0.5, 25.0, 90.0, 0.98, 0.02, 2.0, 2.0, 2.0),
        Params(0.0, 0.5, 10.0, 45.0, 0.98, 0.01, 1.0, 1.0, 1.0),
        Params(1.0, 0.5, 25.0, 60.0, 0.85, 0.015, 2.0, 2.0, 1.0),
    ]
    thin = []
    i = 0
    for il in (0.0, 1.0, 2.5, 5.5):
        for cl in (0.5, 1.0, 2.0, 4.0):
            for tc in (4.0, 10.0, 25.0):
                for storage in (25.0, 45.0, 90.0):
                    for rec in (0.7, 0.85, 0.98):
                        for ratio in (0.001, 0.0025, 0.005):
                            for k in (0.5, 1.0, 2.0):
                                if i % 21 == 0:
                                    thin.append(Params(il, cl, tc, storage, rec, ratio, k, k, k))
                                i += 1
    seen = set()
    out = []
    for p in seeds + thin:
        key = tuple(asdict(p).values())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:200]


RAIN_MAGNITUDE_FALLBACK_RATIO = 0.2  # if preferred sum < 0.2 * best complete backup, use backup


def build_precip_for_event(
    event_id: str,
    hours: list[str],
    subbasins: list[str],
    *,
    magnitude_hours: list[str] | None = None,
) -> tuple[dict[str, list[float]] | None, dict[str, Any]]:
    rain_by_station: dict[str, dict[str, float]] = {}
    for st in RAIN_STATIONS_LOAD:
        rows = load_event_series(st, event_id)
        series = hourly_field(rows, "Chuva", reduce="sum")
        if not series:
            series = hourly_field(rows, "chuva", reduce="sum")
        rain_by_station[st] = series

    mag_hours = magnitude_hours or hours
    meta: dict[str, Any] = {
        "stations_mm_sum": {},
        "stations_mm_sum_core": {},
        "subbasin_sources": {},
        "fallback_notes": [],
        "runnable": True,
        "blocked_reason": None,
        "contract": "hec_event_ana_raw_ana_only",
    }
    precip: dict[str, list[float]] = {}
    for sb in subbasins:
        prefs = RAIN_PREF[sb]
        complete: list[tuple[str, list[float], float, float]] = []
        for st in prefs:
            series = rain_by_station.get(st, {})
            vals = [series.get(h) for h in hours]
            if all(v is not None for v in vals):
                arr = [float(v) for v in vals]  # type: ignore[arg-type]
                # Index map for core magnitude
                hour_index = {h: i for i, h in enumerate(hours)}
                core_sum = 0.0
                core_ok = True
                for h in mag_hours:
                    i = hour_index.get(h)
                    if i is None:
                        core_ok = False
                        break
                    core_sum += arr[i]
                if not core_ok:
                    # If mag window not subset, fall back to full sum
                    core_sum = sum(arr)
                complete.append((st, arr, sum(arr), core_sum))
        if not complete:
            meta["runnable"] = False
            meta["blocked_reason"] = (
                f"rain incomplete for {sb} (no station covers all hours without gaps)"
            )
            return None, meta
        # Prefer order, but reject a "dry complete" preferred gage vs wetter backup
        # using CORE-window totals (not warm-up pad), so pad rain can't hide a dry event.
        chosen_st, chosen_arr, chosen_sum, chosen_core = complete[0]
        best_backup = max(complete, key=lambda t: t[3])
        if (
            len(complete) > 1
            and best_backup[0] != chosen_st
            and chosen_core < RAIN_MAGNITUDE_FALLBACK_RATIO * best_backup[3]
        ):
            meta["fallback_notes"].append(
                {
                    "subbasin": sb,
                    "rejected": chosen_st,
                    "rejected_mm_sum_full": round(chosen_sum, 2),
                    "rejected_mm_sum_core": round(chosen_core, 2),
                    "chosen": best_backup[0],
                    "chosen_mm_sum_full": round(best_backup[2], 2),
                    "chosen_mm_sum_core": round(best_backup[3], 2),
                    "rule": (
                        f"preferred_core_sum < {RAIN_MAGNITUDE_FALLBACK_RATIO} * "
                        "best_complete_backup_core"
                    ),
                }
            )
            chosen_st, chosen_arr, chosen_sum, chosen_core = best_backup

        # Densify Prata/Antas: arithmetic mean of all complete gages (incl. 2851072).
        if sb in ("SB_PRATA_7868", "SB_ANTAS_RESIDUAL") and len(complete) >= 2:
            n = len(hours)
            blended = [0.0] * n
            for _st, arr, _s, _c in complete:
                for i in range(n):
                    blended[i] += arr[i]
            inv = 1.0 / len(complete)
            chosen_arr = [v * inv for v in blended]
            chosen_st = "+".join(t[0] for t in complete)
            chosen_sum = sum(chosen_arr)
            hour_index = {h: i for i, h in enumerate(hours)}
            chosen_core = sum(chosen_arr[hour_index[h]] for h in mag_hours if h in hour_index)
            meta["fallback_notes"].append(
                {
                    "subbasin": sb,
                    "chosen": chosen_st,
                    "rule": "arithmetic_mean_of_complete_gages",
                    "n_gages": len(complete),
                    "chosen_mm_sum_core": round(chosen_core, 2),
                }
            )

        precip[sb] = chosen_arr
        meta["subbasin_sources"][sb] = chosen_st
        meta["stations_mm_sum"][chosen_st] = round(chosen_sum, 2)
        meta["stations_mm_sum_core"][chosen_st] = round(chosen_core, 2)
    return precip, meta


def diagnose_stz(areas: dict[str, float], mucum_report: dict[str, Any]) -> dict[str, Any]:
    """STZ has no ANA Vazao in this package — cannot do independent Q calibration."""
    events_diag = []
    for event_id, (start_s, end_s) in EVENTS.items():
        hours = expected_hours(parse_ts(start_s), parse_ts(end_s))
        rows = load_event_series("86472600", event_id)
        nivel = hourly_field(rows, "Nivel", reduce="mean")
        vazao = hourly_field(rows, "Vazao", reduce="mean")
        n_nivel = len([h for h in hours if h in nivel])
        n_vazao = len([h for h in hours if h in vazao])
        if n_nivel == 0 and n_vazao == 0:
            note = "Sem Nivel e sem Vazao preenchidos na telemetria de evento deste pacote"
        elif n_vazao == 0:
            note = "Nivel presente; Vazao vazia/ausente (precisa curva-chave Nivel→Vazao)"
        else:
            note = "Vazao presente — revisar bloqueio"
        events_diag.append(
            {
                "event_id": event_id,
                "nivel_hours": n_nivel,
                "vazao_hours": n_vazao,
                "note": note,
            }
        )

    # Prefer hold-out-trained common params when available; else full common; else eventwise.
    cs = mucum_report.get("common_search") or {}
    hold = cs.get("holdout_e27") or {}
    common_params = (hold.get("fit") or {}).get("best_params") or cs.get("best_params")
    pad_hours = int(mucum_report.get("pad_hours") or 0)
    transferred = []
    for r in mucum_report["events"]:
        if r["status"] not in ("eventwise_scored", "fit_failed_eventwise"):
            continue
        subbasins = ["SB_PRATA_7868", "SB_ANTAS_RESIDUAL", "SB_CARREIRO_7866", "SB_STZ_RESIDUAL"]
        precip, rain_meta, hours, _flow, core_offset, core_hours = prepare_event_forcing(
            r["event_id"], subbasins, pad_hours
        )
        if precip is None:
            continue
        src = "mucum_common_holdout_e27" if (hold.get("fit") or {}).get("best_params") else (
            "mucum_common_search" if cs.get("best_params") else "mucum_eventwise_best"
        )
        pdict = common_params if common_params else r["params"]
        p = Params(**{k: pdict[k] for k in Params.__dataclass_fields__})
        sim_full = run_network(precip, areas, p, include_mucum_increment=False)["at_stz"]
        sim = sim_full[core_offset : core_offset + len(core_hours)]
        series_path = RUN / f"stz_{r['event_id']}_sim_q_from_mucum_params.csv"
        with series_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "sim_q_at_stz_m3s", "obs_nivel_stz_cm"])
            nivel = hourly_field(load_event_series("86472600", r["event_id"]), "Nivel")
            for i, h in enumerate(core_hours):
                w.writerow([h, f"{sim[i]:.4f}", nivel.get(h, "")])
        transferred.append(
            {
                "event_id": r["event_id"],
                "params_from": src,
                "series_csv": str(series_path.relative_to(ROOT)),
                "rain": rain_meta,
                "warning": "Simulated Q at STZ using Muçum params — NOT an STZ Q calibration",
            }
        )

    return {
        "target": "86472600",
        "target_name": "Santa Tereza",
        "quantity": "Vazao_m3s",
        "status": "q_calibration_blocked_no_ana_vazao",
        "structure": "modelo_stz_estrutura_stz_mucum_v1",
        "blocker": (
            "Posto 86472600 não tem Vazão ANA preenchida nos eventos E19–E28 deste pacote. "
            "E24/E27/E28 têm Nivel; E19/E22 sem Nivel e sem Vazao. "
            "Sem curva-chave reconciliada (ou série Q externa) não há alvo Q HEC. "
            "Probe HIDROWEB type=3 neste ambiente também voltou vazio."
        ),
        "events_inventory": events_diag,
        "diagnostic_transfer_from_mucum_params": transferred,
        "next_to_unlock_stz_q": [
            "Anexar curva-chave oficial Santa Tereza (Nivel→Vazao) ou série Q horária reconciliada",
            "Converter Nivel→Q só em E24/E27/E28 (onde há Nivel)",
            "Só então rodar busca eventwise + common-search no modelo STZ truncado",
        ],
    }


def write_html(payload: dict) -> None:
    muc = payload["models"]["mucum"]
    stz = payload["models"]["santa_tereza"]
    common = muc.get("common_search") or {}
    rows = []
    for e in muc["events"]:
        if e["status"] in ("eventwise_scored", "fit_failed_eventwise"):
            m = e["metrics"]
            rows.append(
                f"<tr><td>{e['event_id']}</td><td>{html.escape(e['status'])}</td>"
                f"<td>{m['nse']:.3f}</td><td>{e.get('score', float('nan')):.3f}</td>"
                f"<td>{m['rmse_m3s']:.1f}</td><td>{m['peak_lag_hours']:.0f}</td>"
                f"<td>{m['peak_relative_error']:.3f}</td></tr>"
            )
        else:
            rows.append(
                f"<tr><td>{e['event_id']}</td><td colspan='6'>bloqueado — "
                f"{html.escape(str(e.get('reason','')))}</td></tr>"
            )
    common_rows = []
    for d in common.get("best_event_metrics") or []:
        common_rows.append(
            f"<tr><td>{d['event_id']}</td><td>{d['nse']:.3f}</td>"
            f"<td>{d.get('peak_lag_hours', float('nan')):.0f}</td>"
            f"<td>{d.get('peak_relative_error', float('nan')):.3f}</td></tr>"
        )
    mean_ok = muc.get("mean_nse_eventwise", float("nan"))
    mean_all = muc.get("mean_nse_eventwise_including_e19", muc.get("mean_nse_eventwise_including_failed", float("nan")))
    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HEC twin · Muçum eventwise + STZ diagnóstico</title>
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
    <div class="eyebrow">HEC · gêmeo Python v1 (auditoria)</div>
    <h1>HEC twin · busca Muçum · STZ diagnóstico</h1>
    <p class="muted">{html.escape(payload['generated_at_utc'])} · {html.escape(payload['status'])}</p>
    <div class="notice ok"><strong>Motor:</strong> {html.escape(payload['engine']['name'])} — {html.escape(payload['engine']['why'])}</div>
    <div class="notice"><strong>Objetivo da busca:</strong> research_score = NSE − 0.05·|lag| − 0.5·erro_pico.
      v1.4: eventos E19–E31 + chuva 2851072 + PAD auto={muc.get('pad_hours', '?')}h;
      externos E26/E30/E31; common-search <strong>não</strong> promovido sem testes ok.</div>
    <div class="notice bad"><strong>STZ Q:</strong> {html.escape(stz['blocker'])}</div>
  </header>

  <section>
    <h2>Modelo Muçum · alvo Vazão 86510000</h2>
    <p class="muted">Estrutura Prata+Carreiro · NSE médio dos fits OK (NSE≥0):
      <strong>{mean_ok:.3f}</strong> ({muc.get('n_events_fit_ok', 0)} eventos) ·
      média incluindo falhas: {mean_all:.3f}</p>
    <div class="notice">{html.escape(muc.get('e19_note', ''))}</div>
    <table>
      <thead><tr><th>Evento</th><th>Status</th><th>NSE</th><th>Score</th><th>RMSE</th><th>Lag pico (h)</th><th>Erro pico rel.</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>

  <section>
    <h2>Common-search (diagnóstico — NÃO promover)</h2>
    <p class="muted">Eventos: {', '.join(common.get('runnable_events') or [])} ·
      NSE médio comum: <strong>{(common.get('mean_nse') if common.get('mean_nse') is not None else float('nan')):.3f}</strong> ·
      LOO teste médio: <strong>{(common.get('leave_one_out_mean_test_nse') if common.get('leave_one_out_mean_test_nse') is not None else float('nan')):.3f}</strong> ·
      Hold-out E27 NSE: <strong>{(((common.get('holdout_e27') or {}).get('test_nse')) if (common.get('holdout_e27') or {}).get('test_nse') is not None else float('nan')):.3f}</strong> ·
      Externos E26/E30/E31: <strong>{(((common.get('external_holdout') or {}).get('mean_test_nse')) if (common.get('external_holdout') or {}).get('mean_test_nse') is not None else float('nan')):.3f}</strong></p>
    <div class="notice bad">{html.escape(common.get('note', ''))} PAD={common.get('pad_hours', '?')}h.</div>
    <table>
      <thead><tr><th>Evento</th><th>NSE</th><th>Lag</th><th>Erro pico</th></tr></thead>
      <tbody>{''.join(common_rows) if common_rows else '<tr><td colspan="4">sem common-search</td></tr>'}</tbody>
    </table>
  </section>

  <section>
    <h2>O que ainda falta (Muçum)</h2>
    <ul>{''.join(f"<li><strong>{html.escape(g['id'])}</strong> [{html.escape(g['status'])}]: {html.escape(g['detail'])}</li>" for g in (muc.get('gaps_remaining') or []))}</ul>
  </section>

  <section>
    <h2>Modelo Santa Tereza · alvo 86472600</h2>
    <p class="muted">Status: <strong>{html.escape(stz['status'])}</strong> — não calibrado em Q</p>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in stz['next_to_unlock_stz_q'])}</ul>
    <p class="muted">Séries diagnósticas (Q simulada com params do Muçum) em <code>hec_twin_stz_mucum_v1/</code>.</p>
  </section>

  <section>
    <h2>Próximos</h2>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in payload['next_steps'])}</ul>
    <p>
      <a href="hec_twin_stz_mucum_v1_latest.json">JSON</a> ·
      <a href="estrutura_stz_mucum.html">estrutura</a> ·
      <a href="index.html">estudo-base</a>
    </p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "hec_twin_stz_mucum_v1.html").write_text(page, encoding="utf-8")


def merge(payload: dict) -> None:
    path = OUT / "estudo_bacia_latest.json"
    muc = payload["models"]["mucum"]
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["hec_twin_stz_mucum_v1"] = {
            "status": payload["status"],
            "artifacts": payload["artifacts"],
            "mucum_mean_nse": muc.get("mean_nse_eventwise"),
            "mucum_mean_nse_excluding_e19": muc.get("mean_nse_eventwise_excluding_e19"),
            "mucum_mean_nse_including_e19": muc.get("mean_nse_eventwise_including_e19"),
            "mucum_common_mean_nse": (muc.get("common_search") or {}).get("mean_nse"),
            "mucum_holdout_e27_nse": ((muc.get("common_search") or {}).get("holdout_e27") or {}).get(
                "test_nse"
            ),
            "mucum_external_holdout_nse": ((muc.get("common_search") or {}).get("external_holdout") or {}).get(
                "mean_test_nse"
            ),
            "mucum_loo_mean_test_nse": (muc.get("common_search") or {}).get(
                "leave_one_out_mean_test_nse"
            ),
            "stz_status": payload["models"]["santa_tereza"]["status"],
            "updated_at_utc": payload["generated_at_utc"],
        }
        prev["next_study_steps_only"] = payload["next_steps"]
        path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name in ("dois_modelos_stz_mucum_latest.json", "estrutura_stz_mucum_latest.json"):
        p = OUT / name
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        data["hec_twin_artifact"] = payload["artifacts"]
        data["next_steps"] = payload["next_steps"]
        if name.startswith("dois_"):
            data["status"] = payload["status"]
        if name.startswith("estrutura_"):
            data["status"] = "estrutura_com_hec_twin_v1"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    idx = OUT / "index.html"
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        if "hec_twin_stz_mucum_v1.html" not in text:
            text = text.replace(
                '<a href="estrutura_stz_mucum.html">estrutura STZ+Muçum</a>',
                '<a href="estrutura_stz_mucum.html">estrutura STZ+Muçum</a> ·\n'
                '       <a href="hec_twin_stz_mucum_v1.html">HEC twin calibração</a>',
            )
        if "HEC twin" not in text:
            block = """  <section>
    <h2>HEC twin calibração (v1)</h2>
    <div class="notice" style="border-left-color:#1b7a4a;background:#eefaf3;color:#145c38"><strong>HEC twin:</strong>
    Muçum: busca eventwise + common-search no gêmeo Python. STZ Q bloqueado (sem Vazão ANA).
    Ver <a href="hec_twin_stz_mucum_v1.html">hec_twin_stz_mucum_v1.html</a>.</div>
  </section>

"""
            text = text.replace(
                "  <section>\n    <h2>Estrutura candidata (v1)</h2>",
                block + "  <section>\n    <h2>Estrutura candidata (v1)</h2>",
            )
        else:
            text = text.replace(
                "<strong>HEC (não MATLAB):</strong>",
                "<strong>HEC twin:</strong>",
            )
            text = text.replace(
                "Muçum calibrado em Vazão no gêmeo Python da estrutura Prata+Carreiro. STZ Q bloqueado (sem Vazão ANA).",
                "Muçum: busca eventwise + common-search no gêmeo Python. STZ Q bloqueado (sem Vazão ANA).",
            )
        steps = "".join(f"<li>{html.escape(x)}</li>" for x in payload["next_steps"])
        text = re.sub(
            r"(<h2>Proximos passos de ESTUDO(?: \(sem HEC\))?</h2>\s*<ul>)(.*?)(</ul>)",
            r"\1" + steps + r"\3",
            text,
            flags=re.S,
        )
        text = text.replace(
            "<h2>Proximos passos de ESTUDO (sem HEC)</h2>",
            "<h2>Proximos passos de ESTUDO</h2>",
        )
        idx.write_text(text, encoding="utf-8")


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    estrutura = json.loads(ESTRUTURA.read_text(encoding="utf-8"))
    areas = {
        e["id"]: float(e["area_km2"])
        for e in estrutura["models"]["mucum"]["elements"]
        if e["type"] == "subbasin"
    }

    mucum = calibrate_mucum(areas)
    stz = diagnose_stz(areas, mucum)

    payload = {
        "schema_version": "estudo_hec_twin_stz_mucum_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "busca eventwise + common-search HEC v1.4 (eventos E19–E31, 2851072, "
            "PAD auto, hold-out/LOO/externos) no modelo Muçum; STZ diagnostico (Q bloqueado)"
        ),
        "status": "hec_twin_mucum_v1_4_eventwise_scored_stz_q_blocked",
        "discipline_rule": (
            "Isto e HEC estrutural + busca de parametros no gemeo Linux/Python. "
            "Nao e HEC-HMS 4.13 binario Windows. Nao e alerta operacional. "
            "v1.4: pool ampliado + Ibiraiaras 2851072; externos E26/E30/E31; "
            "STZ Q bloqueado ate curva-chave oficial."
        ),
        "audit_fixes_v1_1": [
            "rain_stations HEC de evento separados dos aspiracionais RNA",
            "fallback de magnitude se pluvio preferido completo mas seco",
            "E19 como fit_failed quando NSE<0",
            "common-search portado do sibling carreiro_split",
            "rotulos: Muçum scored / STZ diagnostico",
            "inventario STZ mede Nivel e Vazao de verdade",
        ],
        "calibration_v1_2": [
            "PAD_HOURS=24 warm-up (score so na janela core)",
            "hold-out: treino E22/E24/E28, teste E27",
            "leave-one-out do common-search",
        ],
        "calibration_v1_3": [
            "PAD auto: argmax mean research_score em {0,12,24}",
            "diagnostico E19: chuva local insuficiente vs pico",
            "prefs de chuva Antas/Carreiro ampliadas",
            "gaps_remaining explicitos no JSON",
        ],
        "calibration_v1_4": [
            "Eventos E20–E21/E23/E25–E26/E29–E31 baixados da ANA",
            "Pluviômetro 2851072 (Ibiraiaras) no forçamento",
            "Hold-out externo E26/E30/E31 fora do fit common-search",
            "STZ: telemetria ampliada; Vazão continua vazia",
        ],
        "engine": {
            "name": "python_hms_twin_ic_clark_recession_muskingum",
            "not_hec_hms_binary": True,
            "why": "HEC-HMS 4.13 do projeto e Windows-only; neste ambiente Linux roda o gemeo auditavel",
            "methods": ["Initial+Constant", "Clark", "Recession", "Muskingum"],
            "optimization_objective": "research_score = NSE - 0.05*|peak_lag| - 0.5*peak_relative_error",
        },
        "structure_ref": "estrutura_stz_mucum_latest.json",
        "areas_km2": areas,
        "models": {"mucum": mucum, "santa_tereza": stz},
        "next_steps": [
            "Muçum: usar params eventwise (common-search só se testes externos/LOO ok).",
            "STZ: Juliana anexar curva-chave oficial 86472600 (HIDROWEB/ANA/SGB) — sem inventar N→Q.",
            "Após curva: converter Nivel→Q e calibrar modelo STZ truncado.",
            "Opcional: densificar chuva e revisar E19 com massa de montante.",
            "Manter Guaporé/Forqueta fora do recorte.",
        ],
        "artifacts": {
            "json": "hec_twin_stz_mucum_v1_latest.json",
            "html": "hec_twin_stz_mucum_v1.html",
            "runs_dir": "hec_twin_stz_mucum_v1/",
        },
    }

    (OUT / "hec_twin_stz_mucum_v1_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_html(payload)
    merge(payload)

    print(
        json.dumps(
            {
                "ok": True,
                "status": payload["status"],
                "mucum_mean_nse_fit_ok": mucum["mean_nse_eventwise"],
                "mucum_common_mean_nse": (mucum.get("common_search") or {}).get("mean_nse"),
                "mucum_events": [
                    {
                        "id": e["event_id"],
                        "status": e["status"],
                        "nse": e.get("metrics", {}).get("nse"),
                        "carreiro_rain": (e.get("rain") or {}).get("subbasin_sources", {}).get(
                            "SB_CARREIRO_7866"
                        ),
                        "fallback": (e.get("rain") or {}).get("fallback_notes") or [],
                    }
                    for e in mucum["events"]
                ],
                "stz": stz["status"],
                "stz_inventory": stz["events_inventory"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
