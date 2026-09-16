#!/usr/bin/env python3
"""Calibrate G040 multi-outlet twins for every UG with official ANA Q.

Honest scope
------------
- Guaporé / Forqueta join the Taquari *downstream* of Muçum (86510000).
- Guaporé mouth (86595000) and Forqueta mouth (86746000): no ANA Q → gated.
- Capigui (86520100): partial Guaporé (~684 of ~2487 km²).
- Rastro de Auto (86743700): partial Forqueta (~564 of ~2864 km²).
- Porto Mariante (86895000): Baixo nested Q (~24 600 km²) =
  Encantado routed + Forqueta residual.
- Lumped twins prefer ANA telemetria *Chuva* when flu stations in the UG
  publish it; Open-Meteo areal mean is the fallback.
- Encantado (86720000): Muçum Q routed + Guaporé residual rain.
- Mouths 86595000 / 86746000: telemetria probed empty (Q=0) → stay gated.

Does not invent an STZ rating. Does not touch RNA.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
SERIES_DIR = OUT / "hec_twin_stz_mucum_v1"
CACHE = Path(__file__).resolve().parent / "__pycache__"
FETCH_CACHE = OUT / "_cache_multi_outlet_fetches"
UA = "PREVINE-G040-multi-outlet/4.0"

# Flu stations that publish Chuva on ANA telemetria (probed Apr/May 2024 window).
ANA_TELE_RAIN_CODES_BY_UG: dict[str, list[str]] = {
    "Forqueta": ["86780000", "86743800", "86748001"],
    "Guaporé": ["86520000"],
    "Baixo Taquari-Antas": [
        "86895000",
        "86720000",
        "86879300",
        "86881000",
        "86950000",
    ],
}

AREA_MUCUM_KM2 = 15965.207
AREA_GUAPORE_KM2 = 2487.5
AREA_ENCANTADO_KM2 = 19100.0
AREA_FORQUETA_KM2 = 2864.0
AREA_BAIXO_EXTRA_KM2 = 5141.1
AREA_G040_KM2 = 26430.0
AREA_MARIANTE_KM2 = 24600.0

CORE_EVENTS = ["E20", "E21", "E22", "E23", "E24", "E25", "E27", "E28", "E31"]
PLUV_JSON = OUT / "pluviometria_g040_latest.json"
POSTOS_JSON = OUT / "postos_por_upg_latest.json"

TRIBUTARIES: list[dict[str, Any]] = [
    {
        "outlet_id": "passo_tainhas",
        "station_code": "86160000",
        "label_pt": "Passo Tainhas (Alto)",
        "ugs": ["Alto Taquari-Antas"],
        "rain_ugs": ["Alto Taquari-Antas"],
        "nested_area_km2": 1120.0,
        "lat": -28.8681,
        "lon": -50.4561,
        "note_pt": "Tributário Alto: Open-Meteo areal (pluvios UG) → IC+Clark vs Q ANA.",
    },
    {
        "outlet_id": "cacador_carreiro",
        "station_code": "86488000",
        "label_pt": "PCH Caçador montante (Carreiro)",
        "ugs": ["Carreiro"],
        "rain_ugs": ["Carreiro"],
        "nested_area_km2": 2090.0,
        "lat": -28.6847,
        "lon": -51.8506,
        "note_pt": "Carreiro quase-foz: Open-Meteo areal → IC+Clark vs Q ANA.",
    },
    {
        "outlet_id": "balsa_prata",
        "station_code": "86447000",
        "label_pt": "Balsa do Prata (Prata)",
        "ugs": ["Prata"],
        "rain_ugs": ["Prata"],
        "nested_area_km2": 3750.0,
        "lat": -28.9714,
        "lon": -51.4611,
        "note_pt": "Prata quase-foz: Open-Meteo areal → IC+Clark vs Q ANA.",
    },
    {
        "outlet_id": "capigui_guapore",
        "station_code": "86520100",
        "label_pt": "PCH Capigui jusante (Guaporé parcial)",
        "ugs": ["Guaporé"],
        "rain_ugs": ["Guaporé"],
        "nested_area_km2": 684.0,
        "lat": -28.3825,
        "lon": -52.2586,
        "note_pt": "Guaporé parcial (~684/2487 km²). PCH — Q pode ser regulada. Foz 86595000 sem Q.",
    },
    {
        "outlet_id": "rastro_forqueta",
        "station_code": "86743700",
        "label_pt": "PCH Rastro de Auto (Forqueta parcial)",
        "ugs": ["Forqueta"],
        "rain_ugs": ["Forqueta"],
        "nested_area_km2": 564.0,
        "lat": -29.0419,
        "lon": -52.2222,
        "note_pt": "Forqueta parcial (~564/2864 km²). PCH montante. Foz 86746000 sem Q.",
    },
    {
        "outlet_id": "jose_julio",
        "station_code": "86472000",
        "label_pt": "Linha José Júlio (Médio aninhado)",
        "ugs": ["Alto Taquari-Antas", "Prata", "Médio Taquari-Antas"],
        "rain_ugs": ["Alto Taquari-Antas", "Prata", "Médio Taquari-Antas"],
        "nested_area_km2": 13000.0,
        "lat": -29.0978,
        "lon": -51.6997,
        "note_pt": "Tronco a montante de Muçum (~13 mil km²); lumped + chuva areal multi-UG.",
    },
]


def _load_pyc(name: str):
    pyc = next(CACHE.glob(f"{name}.cpython-*.pyc"), None)
    if pyc is None:
        raise ModuleNotFoundError(name)
    if name not in sys.modules:
        if name != "hec_twin_nested_v17":
            _load_pyc("hec_twin_nested_v17")
        spec = importlib.util.spec_from_file_location(name, pyc)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)
    return sys.modules[name]


cal = _load_pyc("run_hec_twin_stz_mucum_calibrate")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def nse(obs: list[float], sim: list[float]) -> float:
    pairs = [(o, s) for o, s in zip(obs, sim) if o == o and s is not None]
    if len(pairs) < 5:
        return float("nan")
    o = [p[0] for p in pairs]
    s = [p[1] for p in pairs]
    mean = sum(o) / len(o)
    num = sum((a - b) ** 2 for a, b in zip(o, s))
    den = sum((a - mean) ** 2 for a in o)
    return 1.0 - num / den if den > 0 else float("nan")


def peak_rel_err(obs: list[float], sim: list[float]) -> float | None:
    o = [x for x in obs if x == x]
    s = [x for x in sim if x is not None and x == x]
    if not o or not s or max(o) <= 0:
        return None
    return abs(max(s) - max(o)) / max(o)


def mean_or_none(vals: list[float]) -> float | None:
    ok = [v for v in vals if v == v]
    return round(sum(ok) / len(ok), 4) if ok else None


@dataclass
class ClarkParams:
    initial_loss_mm: float
    constant_loss_mm_h: float
    tc_h: float
    r_h: float
    baseflow_m3s: float


@dataclass
class RouteResidualParams:
    initial_loss_mm: float
    constant_loss_mm_h: float
    tc_h: float
    r_h: float
    musk_k_h: float
    musk_x: float
    baseflow_m3s: float


def load_mucum_obs(event_id: str) -> pd.DataFrame:
    path = SERIES_DIR / f"mucum_{event_id}_best_series.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"])
    cols = ["timestamp", "obs_m3s", "sim_m3s"]
    if "in_core_window" in df.columns:
        cols.append("in_core_window")
    return df[cols].copy()


def _cache_file(kind: str, key: str) -> Path:
    FETCH_CACHE.mkdir(parents=True, exist_ok=True)
    safe = key.replace("/", "_").replace(" ", "_")
    return FETCH_CACHE / f"{kind}_{safe}.json"


def fetch_open_meteo_rain(lat: float, lon: float, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    cache = _cache_file("rain", f"{lat:.4f}_{lon:.4f}_{t0.date()}_{t1.date()}")
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        times = pd.to_datetime(payload["time"], utc=True).tz_localize(None)
        return pd.Series(payload["precipitation"], index=times, dtype=float).fillna(0.0)
    q = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": t0.strftime("%Y-%m-%d"),
            "end_date": t1.strftime("%Y-%m-%d"),
            "hourly": "precipitation",
            "timezone": "UTC",
        }
    )
    url = "https://archive-api.open-meteo.com/v1/archive?" + q
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    hourly = payload["hourly"]
    cache.write_text(
        json.dumps({"time": hourly["time"], "precipitation": hourly["precipitation"]}),
        encoding="utf-8",
    )
    times = pd.to_datetime(hourly["time"], utc=True).tz_localize(None)
    return pd.Series(hourly["precipitation"], index=times, dtype=float).fillna(0.0)


def pluv_points_for_ugs(ugs: list[str], max_points: int = 5) -> list[tuple[float, float]]:
    """Spatial rain samples inside each UG.

    Prefer fluviometric station coords (polygon-assigned). Pluviometers labeled
    by UPG are often outside the actual drainage (e.g. Forqueta labels sit north
    of the flu bbox) — keep only those inside the flu bounding box.
    """
    want = set(ugs)
    flu_pts: list[tuple[float, float]] = []
    bbox: dict[str, tuple[float, float, float, float]] = {}
    if POSTOS_JSON.exists():
        postos = json.loads(POSTOS_JSON.read_text(encoding="utf-8"))
        for ug in want:
            sts = [
                s
                for s in (postos.get("by_upg") or {}).get(ug, [])
                if s.get("lat") is not None and s.get("lon") is not None
            ]
            if not sts:
                continue
            lats = [float(s["lat"]) for s in sts]
            lons = [float(s["lon"]) for s in sts]
            bbox[ug] = (min(lats), max(lats), min(lons), max(lons))
            for s in sts:
                flu_pts.append((float(s["lat"]), float(s["lon"])))

    pluv_pts: list[tuple[float, float]] = []
    if PLUV_JSON.exists():
        payload = json.loads(PLUV_JSON.read_text(encoding="utf-8"))
        for s in payload.get("stations") or []:
            ug = s.get("upg")
            if ug not in want or s.get("lat") is None or s.get("lon") is None:
                continue
            la, lo = float(s["lat"]), float(s["lon"])
            if ug in bbox:
                la0, la1, lo0, lo1 = bbox[ug]
                # small pad
                if not (la0 - 0.05 <= la <= la1 + 0.05 and lo0 - 0.05 <= lo <= lo1 + 0.05):
                    continue
            pluv_pts.append((la, lo))

    pts = flu_pts + pluv_pts
    if not pts:
        return []
    pts = sorted(set((round(la, 4), round(lo, 4)) for la, lo in pts))
    if len(pts) <= max_points:
        return pts
    idxs = [round(i * (len(pts) - 1) / (max_points - 1)) for i in range(max_points)]
    return [pts[i] for i in idxs]


def fetch_areal_rain(
    points: list[tuple[float, float]],
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    fallback: tuple[float, float] | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Mean Open-Meteo precipitation across sample points (areal proxy)."""
    use = list(points)
    if not use and fallback is not None:
        use = [fallback]
    if not use:
        raise ValueError("no rain points")
    series_list = [fetch_open_meteo_rain(lat, lon, t0, t1) for lat, lon in use]
    # union index
    idx = series_list[0].index
    for s in series_list[1:]:
        idx = idx.union(s.index)
    idx = idx.sort_values()
    stacked = pd.concat([s.reindex(idx, fill_value=0.0) for s in series_list], axis=1)
    mean = stacked.mean(axis=1)
    meta = {
        "n_points": len(use),
        "points": [{"lat": la, "lon": lo} for la, lo in use],
        "method": "open_meteo_mean_pluv_sample",
    }
    return mean.fillna(0.0), meta


def _ln(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _parse_ana_tele_field(code: str, t0: pd.Timestamp, t1: pd.Timestamp, field: str) -> pd.Series:
    """Fetch one ANA telemetria numeric field (Vazao / Chuva / Nivel), cached."""
    kind = {"Vazao": "tele_q", "Chuva": "tele_rain", "Nivel": "tele_n"}.get(field, f"tele_{field}")
    cache = _cache_file(kind, f"{code}_{t0.date()}_{t1.date()}")
    if cache.exists():
        rows = json.loads(cache.read_text(encoding="utf-8"))
        if not rows:
            return pd.Series(dtype=float)
        s = pd.Series({pd.Timestamp(t): v for t, v in rows}).sort_index()
        return s.resample("1h").mean() if field == "Vazao" else s.resample("1h").sum()
    start = t0.strftime("%d/%m/%Y")
    end = (t1 + pd.Timedelta(days=1)).strftime("%d/%m/%Y")
    q = urllib.parse.urlencode({"codEstacao": code, "dataInicio": start, "dataFim": end})
    url = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos?" + q
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read()
    root = ET.fromstring(body)
    rows: list[tuple[str, float]] = []
    for node in root.iter():
        if _ln(node.tag) not in ("DadosHidrometereologicos", "DadosHidrometeorologicos"):
            continue
        fields = {_ln(c.tag): (c.text or "").strip() for c in list(node)}
        ts = fields.get("DataHora")
        raw = fields.get(field)
        if not ts or not raw:
            continue
        try:
            t = pd.to_datetime(ts.strip(), format="%Y-%m-%d %H:%M:%S", errors="coerce")
            if pd.isna(t):
                t = pd.to_datetime(ts, dayfirst=True, errors="coerce")
            if pd.isna(t):
                continue
            v = float(raw.replace(",", "."))
        except ValueError:
            continue
        rows.append((str(t), v))
    cache.write_text(json.dumps(rows), encoding="utf-8")
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(t): v for t, v in rows}).sort_index()
    return s.resample("1h").mean() if field == "Vazao" else s.resample("1h").sum()


def fetch_ana_tele_rain(code: str, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    return _parse_ana_tele_field(code, t0, t1, "Chuva")


def fetch_ana_areal_rain(
    ugs: list[str],
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    min_hours: int = 24,
) -> tuple[pd.Series | None, dict[str, Any]]:
    """Mean ANA telemetria Chuva across known flu codes in the UGs (no zero-fill of stations)."""
    codes: list[str] = []
    for ug in ugs:
        codes.extend(ANA_TELE_RAIN_CODES_BY_UG.get(ug) or [])
    # unique preserve order
    seen: set[str] = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    used: list[dict[str, Any]] = []
    series_list: list[pd.Series] = []
    for code in codes:
        s = fetch_ana_tele_rain(code, t0, t1)
        n = int(s.notna().sum()) if not s.empty else 0
        if n < min_hours:
            continue
        series_list.append(s)
        used.append({"code": code, "n_hours": n, "sum_mm": round(float(s.sum()), 2)})
    if not series_list:
        return None, {"method": "ana_tele_chuva_mean", "n_stations": 0, "stations": []}
    idx = series_list[0].index
    for s in series_list[1:]:
        idx = idx.union(s.index)
    idx = idx.sort_values()
    stacked = pd.concat([s.reindex(idx) for s in series_list], axis=1)
    mean = stacked.mean(axis=1, skipna=True).fillna(0.0)
    meta = {
        "method": "ana_tele_chuva_mean",
        "n_stations": len(used),
        "stations": used,
        "ugs": list(ugs),
    }
    return mean, meta


def fetch_preferred_areal_rain(
    ugs: list[str],
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    fallback: tuple[float, float] | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Prefer ANA tele Chuva; fall back to Open-Meteo areal sample."""
    ana, ana_meta = fetch_ana_areal_rain(ugs, t0, t1)
    if ana is not None and int(ana_meta.get("n_stations") or 0) >= 1:
        return ana, ana_meta
    points = pluv_points_for_ugs(ugs)
    rain, meta = fetch_areal_rain(points, t0, t1, fallback=fallback)
    meta = dict(meta)
    meta["ana_attempt"] = ana_meta
    meta["fallback_from"] = "ana_tele_chuva_unavailable"
    return rain, meta


def fetch_ana_tele_flow(code: str, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    return _parse_ana_tele_field(code, t0, t1, "Vazao")


def clark_runoff(rain_mm: list[float], area_km2: float, params: ClarkParams) -> list[float]:
    excess = cal.apply_loss(rain_mm, params.initial_loss_mm, params.constant_loss_mm_h)
    uh = cal.clark_uh(params.tc_h, params.r_h, dt_h=1.0)
    q = cal.excess_to_flow(excess, area_km2, uh)
    return [max(0.0, x + params.baseflow_m3s) for x in q]


def route_plus_residual(
    upstream_q: list[float],
    rain_mm: list[float],
    residual_area_km2: float,
    params: RouteResidualParams,
) -> list[float]:
    routed = cal.muskingum(upstream_q, params.musk_k_h, params.musk_x, dt_h=1.0)
    residual = clark_runoff(
        rain_mm,
        residual_area_km2,
        ClarkParams(
            params.initial_loss_mm,
            params.constant_loss_mm_h,
            params.tc_h,
            params.r_h,
            params.baseflow_m3s,
        ),
    )
    n = min(len(routed), len(residual))
    return [routed[i] + residual[i] for i in range(n)]


def clark_grid(area_km2: float) -> list[ClarkParams]:
    bf_scale = max(5.0, area_km2 * 0.02)
    bfs = (0.4 * bf_scale, 1.0 * bf_scale, 2.0 * bf_scale)
    tcs = (4.0, 10.0, 18.0) if area_km2 < 5000 else (8.0, 16.0, 28.0)
    grid: list[ClarkParams] = []
    for init in (5.0, 15.0, 30.0):
        for const in (0.5, 1.5, 3.0):
            for tc in tcs:
                for r in (8.0, 16.0, 28.0):
                    for bf in bfs:
                        grid.append(ClarkParams(init, const, tc, r, bf))
    return grid


def route_grid(area_residual_km2: float) -> list[RouteResidualParams]:
    bf_scale = max(20.0, area_residual_km2 * 0.03)
    bfs = (0.5 * bf_scale, 1.2 * bf_scale)
    grid: list[RouteResidualParams] = []
    for init in (5.0, 15.0, 30.0):
        for const in (0.5, 1.5, 3.0):
            for tc in (6.0, 12.0, 20.0):
                for r in (10.0, 20.0, 30.0):
                    for k in (4.0, 8.0, 14.0):
                        for x in (0.2, 0.3):
                            for bf in bfs:
                                grid.append(
                                    RouteResidualParams(init, const, tc, r, k, x, bf)
                                )
    return grid


def score_series(
    obs: list[float],
    sim: list[float],
    core: list[int] | None = None,
) -> dict[str, float]:
    if core is None:
        core = [1] * len(obs)
    obs_c = [o for o, c in zip(obs, core) if c and o == o]
    sim_c = [s for s, o, c in zip(sim, obs, core) if c and o == o]
    n = min(len(obs_c), len(sim_c))
    obs_c, sim_c = obs_c[:n], sim_c[:n]
    ns = nse(obs_c, sim_c)
    pre = peak_rel_err(obs_c, sim_c)
    peak_pen = 1.25 * (pre if pre is not None else 1.0)
    score = (ns if ns == ns else -9.0) - peak_pen
    return {
        "nse": ns,
        "peak_rel_err": pre if pre is not None else float("nan"),
        "research_score": score,
        "n_pairs": float(n),
    }


def _core_flags(muc: pd.DataFrame, n: int) -> list[int]:
    if "in_core_window" in muc.columns:
        return muc["in_core_window"].astype(int).tolist()
    return [1] * n


def align_tributary(spec: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    muc = load_mucum_obs(event_id)
    t0, t1 = muc["timestamp"].iloc[0], muc["timestamp"].iloc[-1]
    rain_ugs = spec.get("rain_ugs") or spec["ugs"]
    rain, rain_meta = fetch_preferred_areal_rain(
        rain_ugs, t0, t1, fallback=(float(spec["lat"]), float(spec["lon"]))
    )
    q = fetch_ana_tele_flow(spec["station_code"], t0, t1)
    if q.empty or q.notna().sum() < 20:
        return None
    idx = pd.DatetimeIndex(muc["timestamp"])
    rain_h = rain.reindex(idx, fill_value=0.0)
    q_h = q.reindex(idx).interpolate(limit=3)
    obs = [float(x) if pd.notna(x) else float("nan") for x in q_h.tolist()]
    if sum(1 for x in obs if x == x) < 20:
        return None
    return {
        "event_id": event_id,
        "rain_mm": rain_h.tolist(),
        "obs_q": obs,
        "in_core_window": _core_flags(muc, len(idx)),
        "rain_sum_mm": float(rain_h.sum()),
        "peak_obs": float(pd.Series(obs).max(skipna=True)),
        "rain_meta": rain_meta,
    }


def fit_tributary(bundle: dict[str, Any], area_km2: float) -> dict[str, Any]:
    best = None
    best_score = -1e9
    for p in clark_grid(area_km2):
        sim = clark_runoff(bundle["rain_mm"], area_km2, p)
        sc = score_series(bundle["obs_q"], sim, bundle["in_core_window"])
        if sc["research_score"] > best_score:
            best_score = sc["research_score"]
            best = (p, sc, sim)
    assert best is not None
    p, sc, sim = best
    return {
        "event_id": bundle["event_id"],
        "params": asdict(p),
        "metrics": sc,
        "rain_sum_mm": bundle["rain_sum_mm"],
        "peak_obs": bundle["peak_obs"],
        "sim_peak": max(sim) if sim else None,
    }


def align_encantado(event_id: str) -> dict[str, Any] | None:
    muc = load_mucum_obs(event_id)
    t0, t1 = muc["timestamp"].iloc[0], muc["timestamp"].iloc[-1]
    rain, rain_meta = fetch_preferred_areal_rain(
        ["Guaporé"], t0, t1, fallback=(-28.95, -51.95)
    )
    enc = fetch_ana_tele_flow("86720000", t0, t1)
    if enc.empty or enc.notna().sum() < 10:
        return None
    idx = pd.DatetimeIndex(muc["timestamp"])
    rain_h = rain.reindex(idx, fill_value=0.0)
    enc_h = enc.reindex(idx).interpolate(limit=3)
    muc_q = muc["obs_m3s"].astype(float).tolist()
    sim = muc["sim_m3s"].astype(float).tolist()
    muc_filled = [o if o == o else s for o, s in zip(muc_q, sim)]
    enc_list = [float(x) if pd.notna(x) else float("nan") for x in enc_h.tolist()]
    return {
        "event_id": event_id,
        "upstream_q": muc_filled,
        "rain_mm": rain_h.tolist(),
        "obs_q": enc_list,
        "in_core_window": _core_flags(muc, len(idx)),
        "rain_sum_mm": float(rain_h.sum()),
        "peak_obs": float(pd.Series(enc_list).max(skipna=True)),
        "upstream_peak": float(pd.Series(muc_filled).max(skipna=True)),
        "rain_meta": rain_meta,
    }


def align_mariante(event_id: str) -> dict[str, Any] | None:
    muc = load_mucum_obs(event_id)
    t0, t1 = muc["timestamp"].iloc[0], muc["timestamp"].iloc[-1]
    rain, rain_meta = fetch_preferred_areal_rain(
        ["Forqueta"], t0, t1, fallback=(-29.2239, -52.1622)
    )
    enc = fetch_ana_tele_flow("86720000", t0, t1)
    mar = fetch_ana_tele_flow("86895000", t0, t1)
    if enc.empty or enc.notna().sum() < 10 or mar.empty or mar.notna().sum() < 20:
        return None
    idx = pd.DatetimeIndex(muc["timestamp"])
    rain_h = rain.reindex(idx, fill_value=0.0)
    enc_h = enc.reindex(idx).interpolate(limit=3)
    mar_h = mar.reindex(idx).interpolate(limit=3)
    enc_list = [float(x) if pd.notna(x) else float("nan") for x in enc_h.tolist()]
    muc_q = muc["obs_m3s"].astype(float).tolist()
    sim = muc["sim_m3s"].astype(float).tolist()
    muc_filled = [o if o == o else s for o, s in zip(muc_q, sim)]
    scale = AREA_ENCANTADO_KM2 / AREA_MUCUM_KM2
    upstream = [
        e if e == e else (m * scale if m == m else float("nan"))
        for e, m in zip(enc_list, muc_filled)
    ]
    last = None
    filled_up: list[float] = []
    for x in upstream:
        if x == x:
            last = x
        filled_up.append(last if last is not None else 0.0)
    obs = [float(x) if pd.notna(x) else float("nan") for x in mar_h.tolist()]
    if sum(1 for x in obs if x == x) < 20:
        return None
    return {
        "event_id": event_id,
        "upstream_q": filled_up,
        "rain_mm": rain_h.tolist(),
        "obs_q": obs,
        "in_core_window": _core_flags(muc, len(idx)),
        "rain_sum_mm": float(rain_h.sum()),
        "peak_obs": float(pd.Series(obs).max(skipna=True)),
        "upstream_peak": float(pd.Series(filled_up).max(skipna=True)),
        "rain_meta": rain_meta,
    }


def fit_route_residual(bundle: dict[str, Any], residual_area_km2: float) -> dict[str, Any]:
    best = None
    best_score = -1e9
    for p in route_grid(residual_area_km2):
        sim = route_plus_residual(
            bundle["upstream_q"], bundle["rain_mm"], residual_area_km2, p
        )
        sc = score_series(bundle["obs_q"], sim, bundle["in_core_window"])
        if sc["research_score"] > best_score:
            best_score = sc["research_score"]
            best = (p, sc, sim)
    assert best is not None
    p, sc, sim = best
    return {
        "event_id": bundle["event_id"],
        "params": asdict(p),
        "metrics": sc,
        "rain_sum_mm": bundle["rain_sum_mm"],
        "peak_obs": bundle["peak_obs"],
        "upstream_peak": bundle.get("upstream_peak"),
        "sim_peak": max(sim) if sim else None,
    }


def loo_blend(
    bundles: dict[str, dict[str, Any]],
    fits: dict[str, dict[str, Any]],
    simulate_fn: Callable[[dict[str, Any], dict[str, float]], list[float]],
) -> list[dict[str, Any]]:
    rows = []
    ids = list(fits.keys())
    for hold in ids:
        rain_h = bundles[hold]["rain_sum_mm"]
        donors = []
        for other in ids:
            if other == hold:
                continue
            gap = abs(fits[other]["rain_sum_mm"] - rain_h)
            donors.append((gap, other, fits[other]["params"]))
        donors.sort()
        top = donors[: min(5, len(donors))]
        if not top:
            continue
        weights = [(1.0 / (1.0 + gap), params) for gap, _, params in top]
        wsum = sum(w for w, _ in weights)
        keys = list(weights[0][1].keys())
        blend = {k: sum(w * p[k] for w, p in weights) / wsum for k in keys}
        sim = simulate_fn(bundles[hold], blend)
        sc = score_series(bundles[hold]["obs_q"], sim, bundles[hold]["in_core_window"])
        rows.append(
            {
                "event_id": hold,
                "rain_sum_mm": rain_h,
                "self_fit_nse": fits[hold]["metrics"]["nse"],
                "nse_loo": sc["nse"],
                "peak_rel_err": sc["peak_rel_err"],
                "donor_events": [d[1] for d in top],
                "blend_params": blend,
            }
        )
    return rows


def _summary(fits: dict[str, dict[str, Any]], loo: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n_events_fitted": len(fits),
        "mean_self_fit_nse": mean_or_none([f["metrics"]["nse"] for f in fits.values()]),
        "mean_nse_loo": mean_or_none([r["nse_loo"] for r in loo]),
        "mean_peak_rel_err_loo": mean_or_none([r["peak_rel_err"] for r in loo]),
    }


def calibrate_tributary(spec: dict[str, Any]) -> dict[str, Any]:
    print(f"\n=== {spec['outlet_id']} ({spec['station_code']}) ===")
    bundles: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    for eid in CORE_EVENTS:
        try:
            b = align_tributary(spec, eid)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"event_id": eid, "error": str(exc)})
            print(" skip", eid, exc)
            continue
        if b is None:
            skipped.append({"event_id": eid, "error": "q_series_thin"})
            print(" skip", eid, "thin Q")
            continue
        bundles[eid] = b
        print(f"  {eid}: rain={b['rain_sum_mm']:.1f} mm  peak={b['peak_obs']:.0f}")

    area = float(spec["nested_area_km2"])
    fits: dict[str, dict[str, Any]] = {}
    for eid, b in bundles.items():
        fit = fit_tributary(b, area)
        if fit["metrics"]["nse"] != fit["metrics"]["nse"]:
            skipped.append({"event_id": eid, "error": "fit_nan_nse"})
            continue
        fits[eid] = fit
        print(
            f"  fit {eid}: NSE={fit['metrics']['nse']:.3f} "
            f"peak_rel={fit['metrics']['peak_rel_err']:.3f}"
        )

    def sim_fn(bundle: dict[str, Any], params: dict[str, float]) -> list[float]:
        return clark_runoff(bundle["rain_mm"], area, ClarkParams(**params))

    loo = loo_blend(bundles, fits, sim_fn) if len(fits) >= 2 else []
    summary = _summary(fits, loo)
    print(" summary", summary)
    loo_mean = summary.get("mean_nse_loo")
    self_mean = summary.get("mean_self_fit_nse")
    if len(fits) >= 3 and loo_mean is not None and loo_mean > 0 and self_mean is not None and self_mean > 0.3:
        status = "calibrated_tributary_v1"
    elif len(fits) >= 3 and self_mean is not None and self_mean > 0.2:
        status = "fragile_self_fit_only"
    elif len(fits) >= 3:
        status = "fragile_no_transfer"
    else:
        status = "fragile_thin_events"
    return {
        "outlet_id": spec["outlet_id"],
        "station_code": spec["station_code"],
        "label_pt": spec["label_pt"],
        "ugs": spec["ugs"],
        "nested_area_km2": area,
        "quantity": "Q_ana_telemetria",
        "status": status,
        "note_pt": spec["note_pt"],
        "engine": "open_meteo_areal_ic_clark",
        "self_fit": fits,
        "loo": loo,
        "summary": summary,
        "skipped_events": skipped,
        "verdict": {
            "level": "usable_research" if (summary.get("mean_nse_loo") or -1) > 0 else "fragile",
            "plain_pt": (
                f"{spec['label_pt']}: self-fit NSE≈{summary.get('mean_self_fit_nse')}; "
                f"LOO NSE≈{summary.get('mean_nse_loo')}."
            ),
        },
    }


def calibrate_encantado() -> dict[str, Any]:
    print("\n=== encantado_guapore_join (86720000) ===")
    bundles: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    for eid in CORE_EVENTS:
        try:
            b = align_encantado(eid)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"event_id": eid, "error": str(exc)})
            print(" skip", eid, exc)
            continue
        if b is None:
            skipped.append({"event_id": eid, "error": "encantado_series_empty"})
            print(" skip", eid, "empty")
            continue
        bundles[eid] = b
        print(
            f"  {eid}: rain={b['rain_sum_mm']:.1f} up={b['upstream_peak']:.0f} "
            f"enc={b['peak_obs']:.0f}"
        )

    fits: dict[str, dict[str, Any]] = {}
    for eid, b in bundles.items():
        fit = fit_route_residual(b, AREA_GUAPORE_KM2)
        if fit["metrics"]["nse"] != fit["metrics"]["nse"]:
            skipped.append({"event_id": eid, "error": "fit_nan_nse"})
            continue
        fits[eid] = fit
        print(f"  fit {eid}: NSE={fit['metrics']['nse']:.3f}")

    def sim_fn(bundle: dict[str, Any], params: dict[str, float]) -> list[float]:
        return route_plus_residual(
            bundle["upstream_q"],
            bundle["rain_mm"],
            AREA_GUAPORE_KM2,
            RouteResidualParams(**params),
        )

    loo = loo_blend(bundles, fits, sim_fn) if len(fits) >= 2 else []
    summary = _summary(fits, loo)
    print(" summary", summary)
    return {
        "target_station": "86720000",
        "self_fit": fits,
        "loo": loo,
        "summary": summary,
        "skipped_events": skipped,
        "verdict": {
            "level": "usable_research" if (summary.get("mean_nse_loo") or -1) > 0 else "fragile",
            "plain_pt": (
                f"Self-fit Encantado médio NSE≈{summary.get('mean_self_fit_nse')}; "
                f"LOO NSE≈{summary.get('mean_nse_loo')}. "
                "Fecha Guaporé+corredor em Encantado; foz Guaporé isolada ainda gated."
            ),
        },
    }


def calibrate_mariante() -> dict[str, Any]:
    print("\n=== porto_mariante (86895000) ===")
    bundles: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    for eid in CORE_EVENTS:
        try:
            b = align_mariante(eid)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"event_id": eid, "error": str(exc)})
            print(" skip", eid, exc)
            continue
        if b is None:
            skipped.append({"event_id": eid, "error": "mariante_series_thin"})
            print(" skip", eid, "thin")
            continue
        bundles[eid] = b
        print(
            f"  {eid}: rain_forq={b['rain_sum_mm']:.1f} up={b['upstream_peak']:.0f} "
            f"mar={b['peak_obs']:.0f}"
        )

    fits: dict[str, dict[str, Any]] = {}
    for eid, b in bundles.items():
        fit = fit_route_residual(b, AREA_FORQUETA_KM2)
        if fit["metrics"]["nse"] != fit["metrics"]["nse"]:
            skipped.append({"event_id": eid, "error": "fit_nan_nse"})
            continue
        fits[eid] = fit
        print(f"  fit {eid}: NSE={fit['metrics']['nse']:.3f}")

    def sim_fn(bundle: dict[str, Any], params: dict[str, float]) -> list[float]:
        return route_plus_residual(
            bundle["upstream_q"],
            bundle["rain_mm"],
            AREA_FORQUETA_KM2,
            RouteResidualParams(**params),
        )

    loo = loo_blend(bundles, fits, sim_fn) if len(fits) >= 2 else []
    summary = _summary(fits, loo)
    print(" summary", summary)
    loo_mean = summary.get("mean_nse_loo")
    self_mean = summary.get("mean_self_fit_nse")
    if len(fits) >= 3 and loo_mean is not None and loo_mean > 0 and self_mean is not None and self_mean > 0.2:
        status = "calibrated_multi_outlet_v1"
    elif len(fits) >= 3 and self_mean is not None and self_mean > 0.2:
        status = "fragile_self_fit_only"
    elif len(fits) >= 3:
        status = "fragile_no_transfer"
    else:
        status = "fragile_thin_events"
    return {
        "outlet_id": "porto_mariante",
        "station_code": "86895000",
        "label_pt": "Porto Mariante (Baixo aninhado)",
        "ugs": [
            "Alto Taquari-Antas",
            "Prata",
            "Carreiro",
            "Médio Taquari-Antas",
            "Guaporé",
            "Forqueta",
            "Baixo Taquari-Antas",
        ],
        "nested_area_km2": AREA_MARIANTE_KM2,
        "quantity": "Q_ana_telemetria",
        "status": status,
        "note_pt": (
            "Encantado Q roteada + residual Forqueta (ANA tele Chuva quando houver; "
            "senão Open-Meteo). Quase-G040."
        ),
        "engine": "encantado_route_plus_forqueta_clark",
        "self_fit": fits,
        "loo": loo,
        "summary": summary,
        "skipped_events": skipped,
        "verdict": {
            "level": "usable_research" if (summary.get("mean_nse_loo") or -1) > 0 else "fragile",
            "plain_pt": (
                f"Porto Mariante: self-fit NSE≈{summary.get('mean_self_fit_nse')}; "
                f"LOO NSE≈{summary.get('mean_nse_loo')}. "
                "Baixo com Q; foz Forqueta isolada e Taquari (nível) ainda gated."
            ),
        },
    }


def outlet_catalog(
    trib_results: list[dict[str, Any]],
    mariante: dict[str, Any],
) -> list[dict[str, Any]]:
    trib_by_id = {t["outlet_id"]: t for t in trib_results}
    outlets: list[dict[str, Any]] = [
        {
            "outlet_id": "mucum",
            "station_code": "86510000",
            "label_pt": "Muçum",
            "ugs": ["Alto Taquari-Antas", "Prata", "Carreiro", "Médio Taquari-Antas"],
            "nested_area_km2": AREA_MUCUM_KM2,
            "quantity": "Q_and_stage_via_official_rating",
            "status": "calibrated_eventwise_v1",
            "calibration_artifact": "modelo_mucum_eventwise_v1_fechado_latest.json",
            "note_pt": "Corredor eventwise existente (self-fit ≠ LOO).",
        },
        {
            "outlet_id": "encantado_guapore_join",
            "station_code": "86720000",
            "label_pt": "Encantado (após foz Guaporé)",
            "ugs": [
                "Alto Taquari-Antas",
                "Prata",
                "Carreiro",
                "Médio Taquari-Antas",
                "Guaporé",
            ],
            "nested_area_km2": AREA_ENCANTADO_KM2,
            "quantity": "Q_ana_telemetria",
            "status": "calibrated_multi_outlet_v1",
            "note_pt": "Muçum Q roteada + residual Guaporé (Open-Meteo → Clark).",
        },
    ]
    for spec in TRIBUTARIES:
        t = trib_by_id[spec["outlet_id"]]
        outlets.append(
            {
                "outlet_id": t["outlet_id"],
                "station_code": t["station_code"],
                "label_pt": t["label_pt"],
                "ugs": t["ugs"],
                "nested_area_km2": t["nested_area_km2"],
                "quantity": t["quantity"],
                "status": t["status"],
                "note_pt": t["note_pt"],
                "skill": t["summary"],
            }
        )
    outlets.append(
        {
            "outlet_id": mariante["outlet_id"],
            "station_code": mariante["station_code"],
            "label_pt": mariante["label_pt"],
            "ugs": mariante["ugs"],
            "nested_area_km2": mariante["nested_area_km2"],
            "quantity": mariante["quantity"],
            "status": mariante["status"],
            "note_pt": mariante["note_pt"],
            "skill": mariante["summary"],
        }
    )
    outlets.extend(
        [
            {
                "outlet_id": "guapore_mouth",
                "station_code": "86595000",
                "label_pt": "Barra do Zeferino (foz Guaporé)",
                "ugs": ["Guaporé"],
                "nested_area_km2": AREA_GUAPORE_KM2,
                "quantity": "Q",
                "status": "blocked_no_ana_q_series",
                "blocker_pt": (
                    "Foz sondada na telemetria ANA (janela 2024-04/05): Vazao=0. "
                    "Proxy parcial calibrado em Capigui (86520100)."
                ),
            },
            {
                "outlet_id": "forqueta_mouth",
                "station_code": "86746000",
                "label_pt": "Rio Forqueta (Travesseiro)",
                "ugs": ["Forqueta"],
                "nested_area_km2": AREA_FORQUETA_KM2,
                "quantity": "Q",
                "status": "blocked_no_ana_q_series",
                "blocker_pt": (
                    "Foz sondada na telemetria ANA (janela 2024-04/05): Vazao=0. "
                    "Proxy parcial em Rastro (86743700); residual Forqueta também "
                    "entra em Porto Mariante (chuva ANA tele quando disponível)."
                ),
            },
            {
                "outlet_id": "baixo_taquari_stage",
                "station_code": "86950000",
                "label_pt": "Taquari (nível · Baixo)",
                "ugs": ["Baixo Taquari-Antas"],
                "nested_area_km2": AREA_G040_KM2,
                "quantity": "stage_only",
                "status": "stage_only_no_q_curve",
                "blocker_pt": "Só nível. Q Baixo calibrado em Porto Mariante (86895000).",
            },
        ]
    )
    return outlets


def _compact_fit_block(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": result["summary"],
        "verdict": result["verdict"],
        "loo": result["loo"],
        "self_fit": {
            eid: {
                "metrics": fit["metrics"],
                "params": fit["params"],
                "rain_sum_mm": fit["rain_sum_mm"],
                "peak_obs": fit["peak_obs"],
                "sim_peak": fit["sim_peak"],
            }
            for eid, fit in result["self_fit"].items()
        },
        "skipped_events": result["skipped_events"],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trib_results = [calibrate_tributary(spec) for spec in TRIBUTARIES]
    enc = calibrate_encantado()
    mariante = calibrate_mariante()

    outlets = outlet_catalog(trib_results, mariante)
    calibrated = [o for o in outlets if str(o.get("status", "")).startswith("calibrated")]
    report = {
        "schema_version": "hec_twin_g040_multi_outlet_v4",
        "generated_at_utc": utc_now(),
        "purpose_pt": (
            "Calibração multi-exutório G040 v4: chuva preferida = ANA telemetria Chuva "
            "(média nos flu com Chuva na UG); fallback Open-Meteo areal. "
            "Muçum + Encantado + Mariante + tributários com Q. "
            "Foz Guaporé/Forqueta sondadas sem Vazao na telemetria; Taquari-nível gated."
        ),
        "status": "research_multi_outlet_v4",
        "discipline": {
            "not_single_mucum_as_g040": True,
            "guapore_forqueta_downstream_of_mucum": True,
            "no_invented_stz_rating": True,
            "does_not_touch_rna": True,
            "research_not_alert": True,
            "calibrated_outlet_count": len(calibrated),
            "ana_tele_rain_preferred": True,
            "mouths_tele_q_probed_empty": True,
        },
        "areas_km2": {
            "g040": AREA_G040_KM2,
            "mucum_corridor": AREA_MUCUM_KM2,
            "guapore": AREA_GUAPORE_KM2,
            "encantado_after_guapore": AREA_ENCANTADO_KM2,
            "forqueta": AREA_FORQUETA_KM2,
            "baixo_extra": AREA_BAIXO_EXTRA_KM2,
            "porto_mariante": AREA_MARIANTE_KM2,
        },
        "outlets": outlets,
        "engine": {
            "name": "python_hms_twin_g040_multi_outlet_v4",
            "not_hec_hms_binary": True,
            "methods": [
                "Muçum eventwise library (existing)",
                "Muskingum + residual Clark (Encantado, Porto Mariante)",
                "ANA tele Chuva mean (prefer) / Open-Meteo areal fallback → IC+Clark",
            ],
        },
        "encantado_calibration": enc,
        "tributary_calibrations": {
            t["outlet_id"]: _compact_fit_block(t) for t in trib_results
        },
        "mariante_calibration": _compact_fit_block(mariante),
        "blocked_next": [
            "HidroSerieHistorica / curva oficial para 86595000 e 86746000 "
            "(telemetria Vazao vazia nestas fozes).",
            "Taquari 86950000: nível sem curva; Mariante já fecha Q Baixo aninhado.",
            "Ampliar rede ANA/INMET Chuva por UG (hoje poucos flu publicam Chuva).",
            "Capigui/Rastro: Q PCH — tratar regulação se LOO continuar frágil.",
        ],
        "artifacts": {
            "json": "modelo_g040_multi_exutorio_v1_latest.json",
            "html": "modelo_g040_multi_exutorio_v1.html",
        },
    }

    json_path = OUT / "modelo_g040_multi_exutorio_v1_latest.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    skill_rows = []
    enc_sum = enc["summary"]
    skill_rows.append(
        f"<tr><td>Encantado</td><td>86720000</td><td>{enc_sum.get('n_events_fitted')}</td>"
        f"<td>{enc_sum.get('mean_self_fit_nse')}</td><td>{enc_sum.get('mean_nse_loo')}</td></tr>"
    )
    for t in trib_results:
        s = t["summary"]
        skill_rows.append(
            f"<tr><td>{t['label_pt']}</td><td>{t['station_code']}</td>"
            f"<td>{s.get('n_events_fitted')}</td><td>{s.get('mean_self_fit_nse')}</td>"
            f"<td>{s.get('mean_nse_loo')}</td></tr>"
        )
    ms = mariante["summary"]
    skill_rows.append(
        f"<tr><td>Porto Mariante</td><td>86895000</td><td>{ms.get('n_events_fitted')}</td>"
        f"<td>{ms.get('mean_self_fit_nse')}</td><td>{ms.get('mean_nse_loo')}</td></tr>"
    )
    outlets_html = "\n".join(
        f"<li><strong>{o['label_pt']}</strong> ({o['station_code']}) — "
        f"<code>{o['status']}</code> · {o.get('blocker_pt') or o.get('note_pt') or ''}</li>"
        for o in outlets
    )
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"/>
<title>G040 multi-exutório v4</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;margin:1.5rem;max-width:960px;color:#12241c}}
table{{border-collapse:collapse;width:100%}} th,td{{border-bottom:1px solid #c5d5cb;padding:.4rem;text-align:left}}
.muted{{color:#4a6356}} code{{background:#eef3ef;padding:.1rem .35rem;border-radius:4px}}
</style></head><body>
<h1>Gêmeo G040 multi-exutório v4</h1>
<p class="muted">{report['purpose_pt']}</p>
<p>{len(calibrated)} exutórios calibrados · pesquisa, não alerta.</p>
<h2>Exutórios</h2>
<ul>{outlets_html}</ul>
<h2>Skill (self-fit vs LOO)</h2>
<table><thead><tr><th>Outlet</th><th>Posto</th><th>n</th><th>Self-fit NSE</th><th>NSE LOO</th></tr></thead>
<tbody>{''.join(skill_rows)}</tbody></table>
<p class="muted">Gerado {report['generated_at_utc']}</p>
</body></html>
"""
    (OUT / "modelo_g040_multi_exutorio_v1.html").write_text(html, encoding="utf-8")
    print("\nwrote", json_path.relative_to(ROOT))
    print("calibrated outlets:", len(calibrated))


if __name__ == "__main__":
    main()
