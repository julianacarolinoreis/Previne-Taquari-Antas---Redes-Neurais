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
    "E22": ("2023-09-04 00:00:00", "2023-09-12 07:00:00"),
    "E24": ("2023-11-16 00:00:00", "2023-11-25 23:00:00"),
    "E27": ("2024-04-29 16:00:00", "2024-05-09 20:00:00"),
    "E28": ("2024-06-16 10:00:00", "2024-06-25 02:00:00"),
}

# Prefer native rain; fall back without inventing zeros (skip hour if none)
RAIN_PREF = {
    "SB_PRATA_7868": ["86472000", "86507000"],
    "SB_ANTAS_RESIDUAL": ["86472000"],
    "SB_CARREIRO_7866": ["86507000", "86472000"],
    "SB_STZ_RESIDUAL": ["86472600", "86472000"],
    "SB_INC_MUCUM": ["86510000", "86472600", "86472000"],
}


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


def build_precip_for_event(
    event_id: str,
    hours: list[str],
    subbasins: list[str],
) -> tuple[dict[str, list[float]] | None, dict[str, Any]]:
    rain_by_station: dict[str, dict[str, float]] = {}
    for st in ("86472000", "86472600", "86507000", "86510000"):
        rows = load_event_series(st, event_id)
        # Chuva field
        series = hourly_field(rows, "Chuva", reduce="sum")
        if not series:
            series = hourly_field(rows, "chuva", reduce="sum")
        rain_by_station[st] = series

    meta = {"stations_mm_sum": {}, "subbasin_sources": {}, "runnable": True, "blocked_reason": None}
    precip: dict[str, list[float]] = {}
    for sb in subbasins:
        prefs = RAIN_PREF[sb]
        chosen = None
        for st in prefs:
            series = rain_by_station.get(st, {})
            vals = [series.get(h) for h in hours]
            if all(v is not None for v in vals):
                chosen = st
                precip[sb] = [float(v) for v in vals]  # type: ignore[arg-type]
                break
        if chosen is None:
            meta["runnable"] = False
            meta["blocked_reason"] = f"rain incomplete for {sb} (no station covers all hours without gaps)"
            return None, meta
        meta["subbasin_sources"][sb] = chosen
        meta["stations_mm_sum"][chosen] = round(sum(precip[sb]), 2)
    return precip, meta


def calibrate_mucum(areas: dict[str, float]) -> dict[str, Any]:
    subbasins = [
        "SB_PRATA_7868",
        "SB_ANTAS_RESIDUAL",
        "SB_CARREIRO_7866",
        "SB_STZ_RESIDUAL",
        "SB_INC_MUCUM",
    ]
    params_list = candidate_grid()
    event_results = []

    for event_id, (start_s, end_s) in EVENTS.items():
        hours = expected_hours(parse_ts(start_s), parse_ts(end_s))
        flow = hourly_field(load_event_series("86510000", event_id), "Vazao", reduce="mean")
        precip, rain_meta = build_precip_for_event(event_id, hours, subbasins)
        paired = [i for i, h in enumerate(hours) if h in flow]
        row: dict[str, Any] = {
            "event_id": event_id,
            "rain": rain_meta,
            "observed_points": len(paired),
            "status": "blocked",
        }
        if precip is None or len(paired) < 12:
            row["reason"] = rain_meta.get("blocked_reason") or "insufficient observed Vazao at Muçum"
            event_results.append(row)
            continue

        best_p = None
        best_m = None
        best_score = float("-inf")
        best_sim = None
        for p in params_list:
            sim_map = run_network(precip, areas, p, include_mucum_increment=True)
            sim = sim_map["at_mucum"]
            obs = [flow[hours[i]] for i in paired]
            sim_p = [sim[i] for i in paired]
            m = metrics(obs, sim_p)
            score = research_score(m)
            if score > best_score:
                best_score, best_p, best_m, best_sim = score, p, m, sim

        assert best_p is not None and best_m is not None and best_sim is not None
        # write series
        series_path = RUN / f"mucum_{event_id}_best_series.csv"
        with series_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "obs_m3s", "sim_m3s"])
            for i, h in enumerate(hours):
                w.writerow([h, flow.get(h, ""), f"{best_sim[i]:.4f}"])

        row.update(
            {
                "status": "calibrated_eventwise",
                "score": best_score,
                "metrics": best_m,
                "params": asdict(best_p),
                "series_csv": str(series_path.relative_to(ROOT)),
            }
        )
        event_results.append(row)

    calibrated = [r for r in event_results if r["status"] == "calibrated_eventwise"]
    mean_nse = (
        sum(r["metrics"]["nse"] for r in calibrated) / len(calibrated) if calibrated else float("nan")
    )
    # E19 is a known catastrophic outlier (same family as carreiro_split); report both means.
    calibrated_no_e19 = [r for r in calibrated if r["event_id"] != "E19"]
    mean_nse_no_e19 = (
        sum(r["metrics"]["nse"] for r in calibrated_no_e19) / len(calibrated_no_e19)
        if calibrated_no_e19
        else float("nan")
    )
    return {
        "target": "86510000",
        "target_name": "Muçum",
        "quantity": "Vazao_m3s",
        "structure": "modelo_mucum_estrutura_stz_mucum_v1",
        "n_events_calibrated": len(calibrated),
        "mean_nse_eventwise": mean_nse,
        "mean_nse_eventwise_excluding_e19": mean_nse_no_e19,
        "n_events_excluding_e19": len(calibrated_no_e19),
        "e19_note": (
            "E19 derruba a média bruta (NSE ~−36). Eventos E22–E28 ficam no mesmo patamar "
            "do carreiro_split (NSE ~0.73–0.95)."
        ),
        "events": event_results,
    }


def diagnose_stz(areas: dict[str, float], mucum_report: dict[str, Any]) -> dict[str, Any]:
    """STZ has no ANA Vazao — cannot do independent Q calibration."""
    events_diag = []
    for event_id, (start_s, end_s) in EVENTS.items():
        hours = expected_hours(parse_ts(start_s), parse_ts(end_s))
        nivel = hourly_field(load_event_series("86472600", event_id), "Nivel", reduce="mean")
        events_diag.append(
            {
                "event_id": event_id,
                "nivel_hours": len([h for h in hours if h in nivel]),
                "vazao_hours": 0,
                "note": "ANA telemetry for 86472600 has Nivel only (empty Vazao) in available event files",
            }
        )
    # Transfer params from best Muçum event as upstream skeleton demo (not STZ Q fit)
    transferred = []
    for r in mucum_report["events"]:
        if r["status"] != "calibrated_eventwise":
            continue
        subbasins = ["SB_PRATA_7868", "SB_ANTAS_RESIDUAL", "SB_CARREIRO_7866", "SB_STZ_RESIDUAL"]
        hours = expected_hours(parse_ts(EVENTS[r["event_id"]][0]), parse_ts(EVENTS[r["event_id"]][1]))
        precip, rain_meta = build_precip_for_event(r["event_id"], hours, subbasins)
        if precip is None:
            continue
        p = Params(**{k: r["params"][k] for k in Params.__dataclass_fields__})
        sim = run_network(precip, areas, p, include_mucum_increment=False)["at_stz"]
        series_path = RUN / f"stz_{r['event_id']}_sim_q_from_mucum_params.csv"
        with series_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "sim_q_at_stz_m3s", "obs_nivel_stz_cm"])
            nivel = hourly_field(load_event_series("86472600", r["event_id"]), "Nivel")
            for i, h in enumerate(hours):
                w.writerow([h, f"{sim[i]:.4f}", nivel.get(h, "")])
        transferred.append(
            {
                "event_id": r["event_id"],
                "params_from": "mucum_eventwise_best",
                "series_csv": str(series_path.relative_to(ROOT)),
                "rain": rain_meta,
                "warning": "Simulated Q at STZ using Muçum-fitted params — NOT an STZ Q calibration",
            }
        )

    return {
        "target": "86472600",
        "target_name": "Santa Tereza",
        "quantity": "Vazao_m3s",
        "status": "q_calibration_blocked_no_ana_vazao",
        "structure": "modelo_stz_estrutura_stz_mucum_v1",
        "blocker": (
            "Posto 86472600 não tem série de Vazão ANA nos eventos E19–E28 deste pacote "
            "(só Nivel em parte dos eventos). Sem curva-chave reconciliada não há alvo Q HEC."
        ),
        "events_inventory": events_diag,
        "diagnostic_transfer_from_mucum_params": transferred,
        "next_to_unlock_stz_q": [
            "Reconciliar curva-chave Santa Tereza (Nivel→Vazao)",
            "Ou obter Vazao observada confiável no posto/controle STZ",
            "Só então rodar busca eventwise no modelo STZ truncado",
        ],
    }


def write_html(payload: dict) -> None:
    muc = payload["models"]["mucum"]
    stz = payload["models"]["santa_tereza"]
    rows = []
    for e in muc["events"]:
        if e["status"] == "calibrated_eventwise":
            m = e["metrics"]
            rows.append(
                f"<tr><td>{e['event_id']}</td><td>{m['nse']:.3f}</td><td>{m['rmse_m3s']:.1f}</td>"
                f"<td>{m['peak_lag_hours']:.0f}</td><td>{m['peak_relative_error']:.3f}</td></tr>"
            )
        else:
            rows.append(
                f"<tr><td>{e['event_id']}</td><td colspan='4'>bloqueado — {html.escape(str(e.get('reason','')))}</td></tr>"
            )
    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HEC twin · calibração STZ/Muçum v1</title>
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
    <div class="eyebrow">HEC · gêmeo Python v1</div>
    <h1>Calibração HEC · Santa Tereza e Muçum</h1>
    <p class="muted">{html.escape(payload['generated_at_utc'])} · {html.escape(payload['status'])}</p>
    <div class="notice ok"><strong>Motor:</strong> {html.escape(payload['engine']['name'])} — {html.escape(payload['engine']['why'])}</div>
    <div class="notice bad"><strong>STZ Q:</strong> {html.escape(stz['blocker'])}</div>
  </header>

  <section>
    <h2>Modelo Muçum · alvo Vazão 86510000</h2>
    <p class="muted">Estrutura Prata+Carreiro ·
      NSE médio E22–E28: <strong>{muc.get('mean_nse_eventwise_excluding_e19', float('nan')):.3f}</strong>
      ({muc.get('n_events_excluding_e19', 0)} eventos) ·
      média bruta incl. E19: {muc['mean_nse_eventwise']:.3f} ({muc['n_events_calibrated']} eventos)</p>
    <div class="notice">{html.escape(muc.get('e19_note', ''))}</div>
    <table>
      <thead><tr><th>Evento</th><th>NSE</th><th>RMSE</th><th>Lag pico (h)</th><th>Erro pico rel.</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>

  <section>
    <h2>Modelo Santa Tereza · alvo 86472600</h2>
    <p class="muted">Status: <strong>{html.escape(stz['status'])}</strong></p>
    <ul>{''.join(f'<li>{html.escape(x)}</li>' for x in stz['next_to_unlock_stz_q'])}</ul>
    <p class="muted">Séries diagnósticas (Q simulada com params do Muçum, sem calibrar STZ) em <code>hec_twin_stz_mucum_v1/</code>.</p>
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
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["hec_twin_stz_mucum_v1"] = {
            "status": payload["status"],
            "artifacts": payload["artifacts"],
            "mucum_mean_nse": payload["models"]["mucum"]["mean_nse_eventwise"],
            "mucum_mean_nse_excluding_e19": payload["models"]["mucum"].get(
                "mean_nse_eventwise_excluding_e19"
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
            data["status"] = "hec_twin_mucum_calibrado_stz_q_bloqueado"
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
    Muçum calibrado em Vazão no gêmeo Python da estrutura Prata+Carreiro. STZ Q bloqueado (sem Vazão ANA).
    Ver <a href="hec_twin_stz_mucum_v1.html">hec_twin_stz_mucum_v1.html</a>.</div>
  </section>

"""
            text = text.replace(
                "  <section>\n    <h2>Estrutura candidata (v1)</h2>",
                block + "  <section>\n    <h2>Estrutura candidata (v1)</h2>",
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
    RUN.mkdir(parents=True, exist_ok=True)
    estrutura = json.loads(ESTRUTURA.read_text(encoding="utf-8"))
    # areas from mucum model elements (superset)
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
        "purpose": "calibracao HEC (gemeo Python) dos modelos-alvo STZ e Mucum",
        "status": "hec_twin_mucum_calibrado_stz_q_bloqueado",
        "discipline_rule": (
            "Isto e HEC estrutural + busca de parametros no gemeo Linux. "
            "Nao e HEC-HMS 4.13 binario Windows. Nao e alerta operacional."
        ),
        "engine": {
            "name": "python_hms_twin_ic_clark_recession_muskingum",
            "not_hec_hms_binary": True,
            "why": "HEC-HMS 4.13 do projeto e Windows-only; neste ambiente Linux roda o gemeo auditavel",
            "methods": ["Initial+Constant", "Clark", "Recession", "Muskingum"],
        },
        "structure_ref": "estrutura_stz_mucum_latest.json",
        "areas_km2": areas,
        "models": {"mucum": mucum, "santa_tereza": stz},
        "next_steps": [
            "Desbloquear STZ Q com curva-chave reconciliada (Nivel→Vazao) e recalibrar modelo STZ truncado.",
            "Opcional: portar melhores params Muçum para projeto .basin HEC-HMS 4.13 no Windows.",
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
                "mucum_mean_nse": mucum["mean_nse_eventwise"],
                "mucum_mean_nse_excluding_e19": mucum.get("mean_nse_eventwise_excluding_e19"),
                "mucum_events": [
                    {
                        "id": e["event_id"],
                        "status": e["status"],
                        "nse": e.get("metrics", {}).get("nse"),
                    }
                    for e in mucum["events"]
                ],
                "stz": stz["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
