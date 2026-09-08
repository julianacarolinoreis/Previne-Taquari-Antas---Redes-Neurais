#!/usr/bin/env python3
"""End-to-end Carreiro-split corridor: rain audit, policy, Python HMS twin, search.

HEC-HMS 4.13 is Windows-only in this project. This package runs a transparent
Initial+Constant / Clark / Recession / Muskingum twin of the proposed
4-subbasin structure so the multi-inflow hypothesis can be scored on Linux.

It never fills rainfall gaps and never claims operational authority.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = ROOT / "assets" / "data" / "hec_hms_carreiro_split" / "carreiro_split_structure_latest.json"
OUT = ROOT / "assets" / "data" / "hec_hms_carreiro_split"
RAW = OUT / "raw_ana"
SERIES_ROOT = ROOT / "assets" / "data" / "mucum_eventwise_replay_calibrated"
UA = "PREVINE-carreiro-split-end-to-end/1.0"

EVENTS = {
    "E19": ("2023-05-06 10:00:00", "2023-05-08 14:00:00"),
    "E22": ("2023-09-04 00:00:00", "2023-09-12 07:00:00"),
    "E24": ("2023-11-16 00:00:00", "2023-11-25 23:00:00"),
    "E27": ("2024-04-29 16:00:00", "2024-05-09 20:00:00"),
    "E28": ("2024-06-16 10:00:00", "2024-06-25 02:00:00"),
}

# Pad ANA pull a bit before/after score window for warm-up.
PAD_HOURS = 24

STATIONS = {
    "86472000": "Antas / Linha José Júlio",
    "86472600": "Santa Tereza",
    "86507000": "Carreiro / PCH Cotiporã Jusante",
    "86510000": "Muçum",
}

SUBBASIN_RAIN_PREF = {
    "SB_ANTAS_86472000": ["86472000"],
    "SB_CARREIRO_7866": ["86507000", "86472000"],
    "SB_STZ_RESIDUAL": ["86472600", "86472000"],
    "SB_INC_MUCUM": ["86510000", "86472600", "86472000"],
}


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def fmt_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def ana_day(value: datetime) -> str:
    return value.strftime("%d/%m/%Y")


def download(url: str, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            payload = response.read()
        path.write_bytes(payload)
        return {"ok": True, "path": str(path.relative_to(ROOT)), "bytes": len(payload), "url": url}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "path": str(path.relative_to(ROOT)), "error": str(exc), "url": url}


def fetch_station_event(station: str, event_id: str) -> dict[str, Any]:
    start = parse_ts(EVENTS[event_id][0]) - timedelta(hours=PAD_HOURS)
    end = parse_ts(EVENTS[event_id][1]) + timedelta(hours=PAD_HOURS)
    url = (
        "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos?"
        + urllib.parse.urlencode(
            {
                "codEstacao": station,
                "dataInicio": ana_day(start),
                "dataFim": ana_day(end),
            }
        )
    )
    path = RAW / f"telemetry_{station}_{event_id}.xml"
    meta = download(url, path)
    meta.update({"station": station, "event_id": event_id, "window_start": fmt_ts(start), "window_end": fmt_ts(end)})
    return meta


def parse_telemetry(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size < 50:
        return []
    root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    rows: list[dict[str, Any]] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "DadosHidrometereologicos":
            continue
        vals = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in el}
        rows.append(vals)
    return rows


def hourly_rain(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        raw = row.get("Chuva", "")
        if raw == "":
            continue
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        ts = row.get("DataHora") or ""
        if len(ts) < 13:
            continue
        # ANA already often hourly; keep label on the hour.
        hour = ts[:13].replace("T", " ") + ":00:00"
        if " " not in hour:
            continue
        buckets[hour].append(value)
    return {hour: round(sum(vals), 6) for hour, vals in sorted(buckets.items())}


def hourly_flow_from_ana(event_id: str) -> dict[str, float]:
    path = RAW / f"telemetry_86510000_{event_id}.xml"
    return hourly_mean_field(parse_telemetry(path), "Vazao")


def hourly_flow_from_hybrid_or_network(event_id: str) -> dict[str, float]:
    hybrid = (
        ROOT
        / "assets"
        / "data"
        / "hec_hms_integrated_taquari_antas"
        / "network_replay_hybrid_e28"
        / "E28"
        / "spatial_series_e28.csv"
    )
    if event_id == "E28" and hybrid.exists():
        out: dict[str, float] = {}
        with hybrid.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    out[row["time_local"][:19]] = float(row["mucum_observed_m3s"])
                except (KeyError, TypeError, ValueError):
                    continue
        return out
    return {}


def expected_hours(start: datetime, end: datetime) -> list[str]:
    hours: list[str] = []
    cur = start
    while cur <= end:
        hours.append(fmt_ts(cur))
        cur += timedelta(hours=1)
    return hours


def completeness(series: dict[str, float | None], hours: list[str]) -> dict[str, Any]:
    missing = [h for h in hours if h not in series or series[h] is None]
    values = [float(series[h]) for h in hours if h in series and series[h] is not None]
    return {
        "expected_hours": len(hours),
        "numeric_hours": len(values),
        "missing_hours": len(missing),
        "complete": len(missing) == 0 and len(values) == len(hours),
        "sum_mm": round(sum(values), 3) if values else 0.0,
        "max_mm": round(max(values), 3) if values else None,
        "first_missing": missing[0] if missing else None,
    }


def hourly_mean_field(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        raw = row.get(field, "")
        if raw == "":
            continue
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        ts = row.get("DataHora") or ""
        if len(ts) < 13:
            continue
        hour = ts[:13].replace("T", " ") + ":00:00"
        buckets[hour].append(value)
    return {hour: sum(vals) / len(vals) for hour, vals in sorted(buckets.items())}


def build_rain_bank() -> dict[str, Any]:
    downloads = []
    bank: dict[str, dict[str, dict[str, float | None]]] = {}
    audits: dict[str, Any] = {}
    for event_id, (start_s, end_s) in EVENTS.items():
        start, end = parse_ts(start_s), parse_ts(end_s)
        hours = expected_hours(start, end)
        audits[event_id] = {"score_window": {"start": start_s, "end": end_s}, "stations": {}}
        bank[event_id] = {}
        for station in STATIONS:
            meta = fetch_station_event(station, event_id)
            downloads.append(meta)
            rows = parse_telemetry(RAW / f"telemetry_{station}_{event_id}.xml") if meta.get("ok") else []
            series = hourly_rain(rows)
            bank[event_id][station] = series
            audits[event_id]["stations"][station] = {
                "name": STATIONS[station],
                "download_ok": bool(meta.get("ok")),
                "raw_records": len(rows),
                **completeness(series, hours),
            }
    return {"downloads": downloads, "bank": bank, "audit": audits}


def assign_policy(bank: dict[str, dict[str, dict[str, float | None]]], audit: dict[str, Any], structure: dict[str, Any]) -> dict[str, Any]:
    areas = {e["id"]: float(e["area_km2"]) for e in structure["elements"] if e["type"] == "subbasin"}
    policy: dict[str, Any] = {}
    for event_id, (start_s, end_s) in EVENTS.items():
        hours = expected_hours(parse_ts(start_s), parse_ts(end_s))
        event_policy: dict[str, Any] = {"subbasins": {}, "runnable": True, "blockers": []}
        for sb, prefs in SUBBASIN_RAIN_PREF.items():
            chosen = None
            mode = None
            for station in prefs:
                profile = audit[event_id]["stations"][station]
                if profile.get("complete"):
                    chosen = station
                    mode = "observed_complete"
                    break
            if chosen is None:
                # explicit proxy: first preference with any numeric coverage, else 86472000 if complete
                for station in prefs + ["86472000"]:
                    profile = audit[event_id]["stations"].get(station) or {}
                    if profile.get("complete"):
                        chosen = station
                        mode = "explicit_proxy_complete"
                        break
            if chosen is None:
                event_policy["runnable"] = False
                event_policy["blockers"].append(f"{sb}: no complete rain series")
                event_policy["subbasins"][sb] = {
                    "area_km2": areas[sb],
                    "station": None,
                    "mode": "blocked",
                }
                continue
            series = [float(bank[event_id][chosen][h]) for h in hours]
            event_policy["subbasins"][sb] = {
                "area_km2": areas[sb],
                "station": chosen,
                "mode": mode,
                "preferred": prefs[0],
                "is_proxy": mode != "observed_complete" or chosen != prefs[0],
                "sum_mm": round(sum(series), 3),
            }
        policy[event_id] = event_policy
    return policy


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
    """Discrete Clark UH: linear time-area translation + exponential reservoir."""
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
        # outflow_{t} = outflow_{t-1}*e^{-dt/R} + inflow*(1-e^{-dt/R})
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
        p = max(0.0, p - constant_loss)
        excess.append(p)
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
    # 1 mm over 1 km2 in 1 h = 1/3.6 m3/s
    runoff = convolute(excess_mm, uh)
    return [q * area_km2 / 3.6 for q in runoff]


def recession_baseflow(n: int, area_km2: float, ratio: float, k: float, direct: list[float]) -> list[float]:
    # Simple recession starting from initial flow, with threshold when direct declines.
    q0 = max(ratio, 0.0) * area_km2  # m3/s per note: ratio is flow/area
    base = [0.0] * n
    q = q0
    for i in range(n):
        base[i] = q
        q *= k
        # slight recharge from direct flow peak decay not modeled; keep pure recession
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
        out[i] = c0 * inflow[i] + c1 * inflow[i - 1] + c2 * out[i - 1]
        out[i] = max(0.0, out[i])
    return out


def run_network(
    precip_by_sb: dict[str, list[float]],
    areas: dict[str, float],
    params: Params,
) -> list[float]:
    uh = clark_uh(params.tc, params.storage)
    flows = {}
    for sb, precip in precip_by_sb.items():
        excess = apply_loss(precip, params.initial_loss, params.constant_loss)
        direct = excess_to_flow(excess, areas[sb], uh)
        base = recession_baseflow(len(precip), areas[sb], params.initial_flow_ratio, params.recession, direct)
        flows[sb] = [d + b for d, b in zip(direct, base)]

    # Topology:
    # Antas -> R1 -> J_Carreiro (+ Carreiro) -> R2 -> J_STZ (+ residual) -> R3 -> J_Mucum (+ mucum inc)
    antas = flows["SB_ANTAS_86472000"]
    carreiro = flows["SB_CARREIRO_7866"]
    residual = flows["SB_STZ_RESIDUAL"]
    mucum_inc = flows["SB_INC_MUCUM"]

    after_r1 = muskingum(antas, params.k1, params.x)
    at_carreiro = [a + c for a, c in zip(after_r1, carreiro)]
    after_r2 = muskingum(at_carreiro, params.k2, params.x)
    at_stz = [a + r for a, r in zip(after_r2, residual)]
    after_r3 = muskingum(at_stz, params.k3, params.x)
    at_mucum = [a + m for a, m in zip(after_r3, mucum_inc)]
    return at_mucum


def metrics(obs: list[float], sim: list[float]) -> dict[str, float]:
    n = min(len(obs), len(sim))
    obs = obs[:n]
    sim = sim[:n]
    if n < 3:
        return {"pairs": float(n), "nse": float("-inf"), "mae_m3s": float("nan"), "rmse_m3s": float("nan"), "peak_lag_hours": float("nan"), "peak_relative_error": float("nan"), "observed_peak_m3s": float("nan"), "simulated_peak_m3s": float("nan")}
    mean_o = sum(obs) / n
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - mean_o) ** 2 for o in obs) or 1e-9
    nse = 1.0 - ss_res / ss_tot
    mae = sum(abs(o - s) for o, s in zip(obs, sim)) / n
    rmse = math.sqrt(ss_res / n)
    i_obs = max(range(n), key=lambda i: obs[i])
    i_sim = max(range(n), key=lambda i: sim[i])
    peak_o = obs[i_obs]
    peak_s = sim[i_sim]
    pre = abs(peak_s - peak_o) / peak_o if peak_o else float("nan")
    return {
        "pairs": float(n),
        "nse": nse,
        "mae_m3s": mae,
        "rmse_m3s": rmse,
        "peak_lag_hours": float(i_sim - i_obs),
        "peak_relative_error": pre,
        "observed_peak_m3s": peak_o,
        "simulated_peak_m3s": peak_s,
    }


def candidate_grid() -> list[Params]:
    rows = []
    for il in (0.0, 1.0, 2.5, 5.5):
        for cl in (0.5, 1.0, 2.0, 4.0):
            for tc in (4.0, 10.0, 25.0):
                for storage in (25.0, 45.0, 90.0):
                    for rec in (0.7, 0.85, 0.98):
                        for ratio in (0.001, 0.0025, 0.005):
                            for k in (0.5, 1.0, 2.0):
                                rows.append(
                                    Params(il, cl, tc, storage, rec, ratio, k, k, k, 0.2)
                                )
    # Too many (4*4*3*3*3*3*3 = 3888). Thin systematically.
    thin = []
    for i, p in enumerate(rows):
        if i % 18 == 0:
            thin.append(p)
    # Ensure known-ish seeds from prior HMS work
    seeds = [
        Params(2.5, 2.0, 25.0, 25.0, 0.80, 0.003, 1.0, 1.0, 1.0, 0.2),
        Params(2.5, 2.0, 25.0, 45.0, 0.80, 0.0025, 1.0, 1.0, 1.0, 0.2),
        Params(5.5, 0.88, 22.5, 34.3, 0.70, 0.001, 1.0, 1.0, 1.0, 0.2),
        Params(1.0, 4.0, 4.0, 90.0, 0.98, 0.005, 1.0, 1.0, 1.0, 0.2),
        Params(0.0, 2.0, 10.0, 60.0, 0.85, 0.0025, 1.0, 1.0, 1.0, 0.2),
        Params(1.0, 2.0, 10.0, 45.0, 0.85, 0.0025, 0.5, 1.0, 1.0, 0.2),
        Params(2.5, 1.0, 20.0, 60.0, 0.80, 0.0025, 2.0, 2.0, 1.0, 0.2),
    ]
    # dedupe
    seen = set()
    out: list[Params] = []
    for p in seeds + thin:
        key = (
            p.initial_loss,
            p.constant_loss,
            p.tc,
            p.storage,
            p.recession,
            p.initial_flow_ratio,
            p.k1,
            p.k2,
            p.k3,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:220]


def research_score(m: dict[str, float]) -> float:
    # Prefer NSE, penalize lag and peak error.
    nse = m["nse"]
    lag = abs(m["peak_lag_hours"]) if m["peak_lag_hours"] == m["peak_lag_hours"] else 99
    pre = m["peak_relative_error"] if m["peak_relative_error"] == m["peak_relative_error"] else 9
    return nse - 0.05 * lag - 0.5 * pre


def event_precip(
    event_id: str,
    hours: list[str],
    bank: dict[str, dict[str, dict[str, float | None]]],
    policy: dict[str, Any],
) -> dict[str, list[float]] | None:
    ep = policy[event_id]
    if not ep["runnable"]:
        return None
    out = {}
    for sb, meta in ep["subbasins"].items():
        station = meta["station"]
        out[sb] = [float(bank[event_id][station][h]) for h in hours]
    return out


def main() -> None:
    structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    areas = {e["id"]: float(e["area_km2"]) for e in structure["elements"] if e["type"] == "subbasin"}

    rain_pack = build_rain_bank()
    bank = rain_pack["bank"]
    audit = rain_pack["audit"]
    policy = assign_policy(bank, audit, structure)

    observed: dict[str, dict[str, float]] = {}
    for eid in EVENTS:
        flow = hourly_flow_from_ana(eid)
        if len(flow) < 12:
            flow = hourly_flow_from_hybrid_or_network(eid)
        observed[eid] = flow

    # Eventwise search
    params_list = candidate_grid()
    event_results = []
    common_rows = []

    for event_id, (start_s, end_s) in EVENTS.items():
        hours = expected_hours(parse_ts(start_s), parse_ts(end_s))
        obs_series = [observed[event_id].get(h) for h in hours]
        if any(v is None for v in obs_series):
            # align only on available observed hours if dense enough
            paired_idx = [i for i, v in enumerate(obs_series) if v is not None]
        else:
            paired_idx = list(range(len(hours)))
        precip = event_precip(event_id, hours, bank, policy)
        row = {
            "event_id": event_id,
            "policy": policy[event_id],
            "observed_points": len(paired_idx),
            "status": "blocked",
        }
        if precip is None or len(paired_idx) < 12:
            row["reason"] = "missing rain policy or insufficient observed flow"
            event_results.append(row)
            continue

        best = None
        best_m = None
        best_score = float("-inf")
        for p in params_list:
            sim = run_network(precip, areas, p)
            obs = [float(obs_series[i]) for i in paired_idx]
            sim_p = [sim[i] for i in paired_idx]
            m = metrics(obs, sim_p)
            score = research_score(m)
            if score > best_score:
                best_score = score
                best = p
                best_m = m
                best_sim = sim_p
                best_obs = obs
                best_times = [hours[i] for i in paired_idx]
        assert best is not None and best_m is not None
        # save series
        series_path = OUT / "runs" / f"{event_id}_best_series.csv"
        series_path.parent.mkdir(parents=True, exist_ok=True)
        with series_path.open("w", encoding="utf-8", newline="") as handle:
            w = csv.DictWriter(handle, fieldnames=["time_local", "observed_m3s", "simulated_m3s"])
            w.writeheader()
            for t, o, s in zip(best_times, best_obs, best_sim):
                w.writerow({"time_local": t, "observed_m3s": o, "simulated_m3s": s})
        row.update(
            {
                "status": "eventwise_scored",
                "metrics": best_m,
                "research_score": best_score,
                "params": best.__dict__,
                "series": str(series_path.relative_to(ROOT)),
            }
        )
        event_results.append(row)

    # Common-parameter search on runnable events
    runnable = [r for r in event_results if r["status"] == "eventwise_scored"]
    runnable_ids = [r["event_id"] for r in runnable]
    best_common = None
    best_common_score = float("-inf")
    best_common_detail = None
    for p in params_list:
        details = []
        scores = []
        ok = True
        for event_id in runnable_ids:
            start_s, end_s = EVENTS[event_id]
            hours = expected_hours(parse_ts(start_s), parse_ts(end_s))
            precip = event_precip(event_id, hours, bank, policy)
            if precip is None:
                ok = False
                break
            obs_map = observed[event_id]
            paired_idx = [i for i, h in enumerate(hours) if h in obs_map]
            sim = run_network(precip, areas, p)
            m = metrics([obs_map[hours[i]] for i in paired_idx], [sim[i] for i in paired_idx])
            details.append({"event_id": event_id, **m})
            scores.append(research_score(m))
        if not ok or not scores:
            continue
        mean_score = sum(scores) / len(scores)
        common_rows.append({"params": p.__dict__, "mean_research_score": mean_score, "events": details})
        if mean_score > best_common_score:
            best_common_score = mean_score
            best_common = p
            best_common_detail = details

    report = {
        "schema_version": "hec_hms_carreiro_split_end_to_end_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "fim do caminho estrutural Carreiro-split com gêmeo Python IC/Clark/Recession/Muskingum; não é HEC-HMS 4.13 binário nem alerta",
        "engine": {
            "name": "python_hms_twin",
            "methods": ["Initial+Constant", "Clark", "Recession", "Muskingum"],
            "not_hec_hms_binary": True,
            "why": "HEC-HMS 4.13 do projeto é Windows-only (D:\\PREVINE\\...); este ambiente Linux executa o gêmeo auditável",
        },
        "structure_ref": str(STRUCTURE.relative_to(ROOT)),
        "areas_km2": areas,
        "rain_audit": audit,
        "rain_policy": policy,
        "downloads": rain_pack["downloads"],
        "eventwise": event_results,
        "common_search": {
            "candidates_evaluated": len(common_rows),
            "runnable_events": runnable_ids,
            "best_params": None if best_common is None else best_common.__dict__,
            "best_mean_research_score": best_common_score if best_common else None,
            "best_event_metrics": best_common_detail,
            "mean_nse": (
                None
                if not best_common_detail
                else sum(d["nse"] for d in best_common_detail) / len(best_common_detail)
            ),
        },
        "verdict": {
            "structure_complete": True,
            "carreiro_has_own_rain_input": any(
                policy[e]["subbasins"]["SB_CARREIRO_7866"].get("station") == "86507000"
                and not policy[e]["subbasins"]["SB_CARREIRO_7866"].get("is_proxy")
                for e in policy
                if policy[e]["subbasins"].get("SB_CARREIRO_7866", {}).get("station")
            ),
            "events_with_native_carreiro_rain": [
                e
                for e in policy
                if policy[e]["subbasins"].get("SB_CARREIRO_7866", {}).get("station") == "86507000"
                and policy[e]["subbasins"]["SB_CARREIRO_7866"].get("mode") == "observed_complete"
            ],
            "calibration_promoted": False,
            "reading": "Estrutura multi-entrada com Carreiro rodou até o hidrograma. Calibração comum ainda é diagnóstico; promoção bloqueada.",
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "end_to_end_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # compact CSV of eventwise best
    with (OUT / "eventwise_best_metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "event_id",
            "status",
            "nse",
            "peak_lag_hours",
            "peak_relative_error",
            "observed_peak_m3s",
            "simulated_peak_m3s",
            "carreiro_station",
            "carreiro_mode",
        ]
        w = csv.DictWriter(handle, fieldnames=fields)
        w.writeheader()
        for row in event_results:
            m = row.get("metrics") or {}
            car = row.get("policy", {}).get("subbasins", {}).get("SB_CARREIRO_7866", {})
            w.writerow(
                {
                    "event_id": row["event_id"],
                    "status": row["status"],
                    "nse": m.get("nse"),
                    "peak_lag_hours": m.get("peak_lag_hours"),
                    "peak_relative_error": m.get("peak_relative_error"),
                    "observed_peak_m3s": m.get("observed_peak_m3s"),
                    "simulated_peak_m3s": m.get("simulated_peak_m3s"),
                    "carreiro_station": car.get("station"),
                    "carreiro_mode": car.get("mode"),
                }
            )

    write_dashboard(report)
    print(
        json.dumps(
            {
                "ok": True,
                "events_scored": runnable_ids,
                "native_carreiro_events": report["verdict"]["events_with_native_carreiro_rain"],
                "best_common_mean_nse": report["common_search"]["mean_nse"],
                "out": str((OUT / "end_to_end_latest.json").relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_dashboard(report: dict[str, Any]) -> None:
    rows = []
    for item in report["eventwise"]:
        m = item.get("metrics") or {}
        car = item.get("policy", {}).get("subbasins", {}).get("SB_CARREIRO_7866", {})
        nse = m.get("nse")
        lag = m.get("peak_lag_hours")
        pre = m.get("peak_relative_error")
        nse_txt = "" if nse is None else f"{nse:.3f}"
        lag_txt = "" if lag is None else f"{lag:.0f} h"
        pre_txt = "" if pre is None else f"{100 * pre:.1f}%"
        rows.append(
            "<tr>"
            f"<td><strong>{item['event_id']}</strong></td>"
            f"<td>{item['status']}</td>"
            f"<td class='num'>{nse_txt}</td>"
            f"<td class='num'>{lag_txt}</td>"
            f"<td class='num'>{pre_txt}</td>"
            f"<td>{car.get('station') or '-'} | {car.get('mode') or '-'}</td>"
            "</tr>"
        )
    mean_nse = report["common_search"]["mean_nse"]
    mean_nse_txt = "" if mean_nse is None else f"{mean_nse:.3f}"
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Carreiro-split | fim do caminho</title>
  <style>
    :root {{ --ink:#143246; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --good:#0b7a68; --car:#c45c16; }}
    body {{ margin:0; font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif; color:var(--ink);
      background:linear-gradient(160deg,#eef8f8,#fff8f1); }}
    main {{ max-width:1100px; margin:auto; padding:28px 18px 60px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:22px; margin-bottom:14px; box-shadow:0 10px 26px #14324612; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,42px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--car); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .ok {{ border-left-color:var(--good); background:#eefaf6; color:#0d5c50; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:26px; color:var(--accent); }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th,td {{ padding:9px 8px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }}
    td.num {{ text-align:right; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Fim do caminho estrutural | gêmeo Python</div>
    <h1>Carreiro na rede, até o hidrograma</h1>
    <p>{report['generated_at_utc']}</p>
    <div class="notice"><strong>Não é HEC-HMS 4.13 binário</strong> e não é alerta. É a estrutura 4 sub-bacias rodada com IC/Clark/Recession/Muskingum para fechar o ciclo no Linux.</div>
  </header>
  <section>
    <div class="grid">
      <div class="stat"><strong>{len(report['common_search']['runnable_events'])}</strong><span>eventos escorados</span></div>
      <div class="stat"><strong>{len(report['verdict']['events_with_native_carreiro_rain'])}</strong><span>eventos com chuva nativa do Carreiro (86507000)</span></div>
      <div class="stat"><strong>{mean_nse_txt}</strong><span>NSE médio da melhor regra comum</span></div>
    </div>
    <div class="notice ok" style="margin-top:12px">{report['verdict']['reading']}</div>
  </section>
  <section>
    <h2>Eventwise</h2>
    <table>
      <thead><tr><th>Evento</th><th>Status</th><th class="num">NSE</th><th class="num">Atraso</th><th class="num">Erro pico</th><th>Chuva Carreiro</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>
  <section>
    <h2>Artefatos</h2>
    <ul>
      <li><a href="end_to_end_latest.json">end_to_end_latest.json</a></li>
      <li><a href="eventwise_best_metrics.csv">eventwise_best_metrics.csv</a></li>
      <li><a href="index.html">diagrama estrutural</a></li>
      <li><a href="../bacia_taquari_antas/index.html">compreensão da bacia</a></li>
    </ul>
  </section>
</main>
</body>
</html>
"""
    (OUT / "end_to_end.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
