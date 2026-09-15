#!/usr/bin/env python3
"""Calibrate the G040 multi-outlet twin — Muçum corridor + Encantado (Guaporé join).

Honest scope
------------
- Guaporé and Forqueta join the Taquari *downstream* of Muçum (86510000).
  They never enter the Muçum water balance.
- Guaporé mouth (86595000) and Forqueta (86746000) have no ANA flow/stage
  series in HydroBr / telemetria for the study windows → tributary-only
  outlets stay *gated* until official Q arrives.
- Encantado (86720000) has ANA Q. Nested area ≈ Muçum + Guaporé.
  We calibrate: route(Muçum Q) + Guaporé residual (Open-Meteo rain → loss/Clark)
  against Encantado Q on the Muçum event library (leave-one-out).

Does not invent an STZ rating curve. Does not touch RNA.
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
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
SERIES_DIR = OUT / "hec_twin_stz_mucum_v1"
CACHE = Path(__file__).resolve().parent / "__pycache__"
UA = "PREVINE-G040-multi-outlet/1.0"

# Nested areas (km²) — twin corridor + Guaporé residual to Encantado.
AREA_MUCUM_KM2 = 15965.207
AREA_GUAPORE_KM2 = 2487.5
AREA_ENCANTADO_KM2 = 19100.0  # Encantado inventory nested ≈ after Guaporé join
AREA_FORQUETA_KM2 = 2864.0
AREA_BAIXO_EXTRA_KM2 = 5141.1
AREA_G040_KM2 = 26430.0

CORE_EVENTS = ["E20", "E21", "E22", "E23", "E24", "E25", "E27", "E28", "E31"]
GUAPORE_CENTROID = (-28.95, -51.95)  # lat, lon


def _load_pyc(name: str):
    pyc = next(CACHE.glob(f"{name}.cpython-*.pyc"), None)
    if pyc is None:
        raise ModuleNotFoundError(name)
    if name not in sys.modules:
        # nested dep first
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
    pairs = [(o, s) for o, s in zip(obs, sim) if o is not None and s is not None and not math.isnan(o)]
    if len(pairs) < 5:
        return float("nan")
    o = [p[0] for p in pairs]
    s = [p[1] for p in pairs]
    mean = sum(o) / len(o)
    num = sum((a - b) ** 2 for a, b in zip(o, s))
    den = sum((a - mean) ** 2 for a in o)
    return 1.0 - num / den if den > 0 else float("nan")


def peak_rel_err(obs: list[float], sim: list[float]) -> float | None:
    o = [x for x in obs if x is not None and not math.isnan(x)]
    s = [x for x in sim if x is not None and not math.isnan(x)]
    if not o or not s or max(o) <= 0:
        return None
    return abs(max(s) - max(o)) / max(o)


@dataclass
class GuaporeParams:
    initial_loss_mm: float
    constant_loss_mm_h: float
    tc_h: float
    r_h: float
    musk_k_h: float
    musk_x: float
    baseflow_m3s: float


def event_window(event_id: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    path = SERIES_DIR / f"mucum_{event_id}_best_series.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df["timestamp"].iloc[0], df["timestamp"].iloc[-1]


def load_mucum_obs(event_id: str) -> pd.DataFrame:
    path = SERIES_DIR / f"mucum_{event_id}_best_series.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df[["timestamp", "obs_m3s", "sim_m3s", "in_core_window"]].copy()


def fetch_open_meteo_rain(lat: float, lon: float, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    start = t0.strftime("%Y-%m-%d")
    end = t1.strftime("%Y-%m-%d")
    q = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "hourly": "precipitation",
            "timezone": "UTC",
        }
    )
    url = "https://archive-api.open-meteo.com/v1/archive?" + q
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    times = pd.to_datetime(payload["hourly"]["time"], utc=True).tz_localize(None)
    rain = pd.Series(payload["hourly"]["precipitation"], index=times, dtype=float).fillna(0.0)
    return rain


def _ln(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def fetch_ana_tele_flow(code: str, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    """Hourly ANA telemetria flow (m³/s) for Encantado / Muçum windows."""
    start = t0.strftime("%d/%m/%Y")
    end = (t1 + pd.Timedelta(days=1)).strftime("%d/%m/%Y")
    q = urllib.parse.urlencode({"codEstacao": code, "dataInicio": start, "dataFim": end})
    url = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos?" + q
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read()
    root = ET.fromstring(body)
    rows = []
    for node in root.iter():
        if _ln(node.tag) not in ("DadosHidrometereologicos", "DadosHidrometeorologicos"):
            continue
        fields = {_ln(c.tag): (c.text or "").strip() for c in list(node)}
        ts = fields.get("DataHora")
        vaz = fields.get("Vazao")
        if not ts or not vaz:
            continue
        try:
            t = pd.to_datetime(ts, dayfirst=True)
            v = float(vaz.replace(",", "."))
        except ValueError:
            continue
        rows.append((t, v))
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({t: v for t, v in rows}).sort_index()
    # average to hourly
    return s.resample("1h").mean()


def guapore_runoff(rain_mm: list[float], params: GuaporeParams) -> list[float]:
    excess = cal.apply_loss(
        rain_mm, params.initial_loss_mm, params.constant_loss_mm_h
    )
    uh = cal.clark_uh(params.tc_h, params.r_h, dt_h=1.0)
    q = cal.excess_to_flow(excess, AREA_GUAPORE_KM2, uh)
    return [max(0.0, x + params.baseflow_m3s) for x in q]


def simulate_encantado(
    mucum_q: list[float],
    rain_guapore: list[float],
    params: GuaporeParams,
) -> list[float]:
    routed = cal.muskingum(mucum_q, params.musk_k_h, params.musk_x, dt_h=1.0)
    guap = guapore_runoff(rain_guapore, params)
    n = min(len(routed), len(guap))
    return [routed[i] + guap[i] for i in range(n)]


def align_event(event_id: str) -> dict[str, Any] | None:
    muc = load_mucum_obs(event_id)
    t0, t1 = muc["timestamp"].iloc[0], muc["timestamp"].iloc[-1]
    rain = fetch_open_meteo_rain(GUAPORE_CENTROID[0], GUAPORE_CENTROID[1], t0, t1)
    enc = fetch_ana_tele_flow("86720000", t0, t1)
    if enc.empty or enc.notna().sum() < 10:
        return None
    # index everything hourly on mucum timestamps
    idx = pd.DatetimeIndex(muc["timestamp"])
    rain_h = rain.reindex(idx, fill_value=0.0)
    enc_h = enc.reindex(idx).interpolate(limit=3)
    muc_q = muc["obs_m3s"].astype(float).tolist()
    # fill mucum gaps with sim when obs missing
    sim = muc["sim_m3s"].astype(float).tolist()
    muc_filled = [o if o == o else s for o, s in zip(muc_q, sim)]
    enc_list = [float(x) if pd.notna(x) else float("nan") for x in enc_h.tolist()]
    core = muc["in_core_window"].astype(int).tolist() if "in_core_window" in muc.columns else [1] * len(idx)
    return {
        "event_id": event_id,
        "timestamps": [str(t) for t in idx],
        "mucum_q": muc_filled,
        "rain_guapore_mm": rain_h.tolist(),
        "encantado_q": enc_list,
        "in_core_window": core,
        "rain_sum_mm": float(rain_h.sum()),
        "enc_peak": float(pd.Series(enc_list).max(skipna=True)),
        "muc_peak": float(pd.Series(muc_filled).max(skipna=True)),
    }


def param_grid() -> list[GuaporeParams]:
    grid = []
    for init in (5.0, 15.0, 30.0):
        for const in (0.5, 1.5, 3.0):
            for tc in (6.0, 12.0, 20.0):
                for r in (10.0, 20.0, 30.0):
                    for k in (4.0, 8.0, 14.0):
                        for x in (0.2, 0.3):
                            for bf in (40.0, 100.0):
                                grid.append(
                                    GuaporeParams(init, const, tc, r, k, x, bf)
                                )
    return grid


def score_params(bundle: dict[str, Any], params: GuaporeParams) -> dict[str, float]:
    sim = simulate_encantado(bundle["mucum_q"], bundle["rain_guapore_mm"], params)
    obs = bundle["encantado_q"]
    core = bundle["in_core_window"]
    obs_c = [o for o, c in zip(obs, core) if c and o == o]
    sim_c = [s for s, o, c in zip(sim, obs, core) if c and o == o]
    # pad lengths
    n = min(len(obs_c), len(sim_c))
    obs_c, sim_c = obs_c[:n], sim_c[:n]
    ns = nse(obs_c, sim_c)
    pre = peak_rel_err(obs_c, sim_c)
    # research score mirrors Muçum twin spirit
    peak_pen = 1.25 * (pre if pre is not None else 1.0)
    score = (ns if ns == ns else -9.0) - peak_pen
    return {
        "nse": ns,
        "peak_rel_err": pre if pre is not None else float("nan"),
        "research_score": score,
        "n_pairs": float(n),
    }


def fit_event(bundle: dict[str, Any]) -> dict[str, Any]:
    best = None
    best_score = -1e9
    for p in param_grid():
        sc = score_params(bundle, p)
        if sc["research_score"] > best_score:
            best_score = sc["research_score"]
            best = (p, sc)
    assert best is not None
    p, sc = best
    sim = simulate_encantado(bundle["mucum_q"], bundle["rain_guapore_mm"], p)
    return {
        "event_id": bundle["event_id"],
        "params": asdict(p),
        "metrics": sc,
        "rain_sum_mm": bundle["rain_sum_mm"],
        "enc_peak_obs": bundle["enc_peak"],
        "muc_peak_obs": bundle["muc_peak"],
        "sim_peak": max(sim) if sim else None,
    }


def loo_transfer(bundles: dict[str, dict[str, Any]], fits: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    ids = list(fits.keys())
    for hold in ids:
        # blend of other events' params by rain fingerprint distance
        rain_h = bundles[hold]["rain_sum_mm"]
        donors = []
        for other in ids:
            if other == hold:
                continue
            gap = abs(fits[other]["rain_sum_mm"] - rain_h)
            donors.append((gap, other, fits[other]["params"]))
        donors.sort()
        top = donors[:5]
        # inverse-gap weights
        weights = []
        for gap, eid, params in top:
            w = 1.0 / (1.0 + gap)
            weights.append((w, params))
        wsum = sum(w for w, _ in weights)
        blend = GuaporeParams(
            initial_loss_mm=sum(w * p["initial_loss_mm"] for w, p in weights) / wsum,
            constant_loss_mm_h=sum(w * p["constant_loss_mm_h"] for w, p in weights)
            / wsum,
            tc_h=sum(w * p["tc_h"] for w, p in weights) / wsum,
            r_h=sum(w * p["r_h"] for w, p in weights) / wsum,
            musk_k_h=sum(w * p["musk_k_h"] for w, p in weights) / wsum,
            musk_x=sum(w * p["musk_x"] for w, p in weights) / wsum,
            baseflow_m3s=sum(w * p["baseflow_m3s"] for w, p in weights) / wsum,
        )
        sc = score_params(bundles[hold], blend)
        self_fit = fits[hold]["metrics"]["nse"]
        rows.append(
            {
                "event_id": hold,
                "rain_sum_mm": rain_h,
                "self_fit_nse": self_fit,
                "nse_loo": sc["nse"],
                "peak_rel_err": sc["peak_rel_err"],
                "donor_events": [d[1] for d in top],
                "blend_params": asdict(blend),
            }
        )
    return rows


def outlet_catalog() -> list[dict[str, Any]]:
    return [
        {
            "outlet_id": "mucum",
            "station_code": "86510000",
            "label_pt": "Muçum",
            "ugs": ["Alto Taquari-Antas", "Prata", "Carreiro", "Médio Taquari-Antas"],
            "nested_area_km2": AREA_MUCUM_KM2,
            "quantity": "Q_and_stage_via_official_rating",
            "status": "calibrated_eventwise_v1",
            "calibration_artifact": "modelo_mucum_eventwise_v1_fechado_latest.json",
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
        {
            "outlet_id": "guapore_mouth",
            "station_code": "86595000",
            "label_pt": "Barra do Zeferino (foz Guaporé)",
            "ugs": ["Guaporé"],
            "nested_area_km2": AREA_GUAPORE_KM2,
            "quantity": "Q",
            "status": "blocked_no_ana_q_series",
            "blocker_pt": "HydroBr/telemetria sem série de vazão/nível no posto da foz.",
        },
        {
            "outlet_id": "forqueta_mouth",
            "station_code": "86746000",
            "label_pt": "Rio Forqueta (Travesseiro)",
            "ugs": ["Forqueta"],
            "nested_area_km2": AREA_FORQUETA_KM2,
            "quantity": "Q",
            "status": "blocked_no_ana_q_series",
            "blocker_pt": "HydroBr/telemetria sem série de vazão/nível no posto da foz.",
        },
        {
            "outlet_id": "baixo_taquari",
            "station_code": "86950000",
            "label_pt": "Taquari (exutório Baixo)",
            "ugs": ["Baixo Taquari-Antas"],
            "nested_area_km2": AREA_G040_KM2,
            "quantity": "stage_only",
            "status": "stage_only_no_q_curve",
            "blocker_pt": "Telemetria com nível; sem vazão consistente / curva-chave fechada no pacote.",
        },
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("aligning events…")
    bundles: dict[str, dict[str, Any]] = {}
    skipped = []
    for eid in CORE_EVENTS:
        try:
            b = align_event(eid)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"event_id": eid, "error": str(exc)})
            print(" skip", eid, exc)
            continue
        if b is None:
            skipped.append({"event_id": eid, "error": "encantado_series_empty"})
            print(" skip", eid, "empty encantado")
            continue
        bundles[eid] = b
        print(
            f"  {eid}: rain={b['rain_sum_mm']:.1f} mm  muc_peak={b['muc_peak']:.0f}  "
            f"enc_peak={b['enc_peak']:.0f}"
        )

    print(f"fitting {len(bundles)} events…")
    fits: dict[str, dict[str, Any]] = {}
    for eid, b in bundles.items():
        fit = fit_event(b)
        if fit["metrics"]["nse"] != fit["metrics"]["nse"]:
            skipped.append({"event_id": eid, "error": "fit_nan_nse"})
            print("  skip fit nan", eid)
            continue
        fits[eid] = fit
        print(
            f"  {eid}: NSE={fit['metrics']['nse']:.3f}  "
            f"peak_rel={fit['metrics']['peak_rel_err']:.3f}  "
            f"init={fit['params']['initial_loss_mm']} "
            f"const={fit['params']['constant_loss_mm_h']} tc={fit['params']['tc_h']}"
        )

    loo = loo_transfer(bundles, fits)
    self_nses = [f["metrics"]["nse"] for f in fits.values() if f["metrics"]["nse"] == f["metrics"]["nse"]]
    loo_nses = [r["nse_loo"] for r in loo if r["nse_loo"] == r["nse_loo"]]
    summary = {
        "n_events_fitted": len(fits),
        "mean_self_fit_nse": round(sum(self_nses) / len(self_nses), 4) if self_nses else None,
        "mean_nse_loo": round(sum(loo_nses) / len(loo_nses), 4) if loo_nses else None,
        "mean_peak_rel_err_loo": round(
            sum(r["peak_rel_err"] for r in loo if r["peak_rel_err"] == r["peak_rel_err"])
            / max(1, sum(1 for r in loo if r["peak_rel_err"] == r["peak_rel_err"])),
            4,
        ),
    }
    print("summary", summary)

    report = {
        "schema_version": "hec_twin_g040_multi_outlet_v1",
        "generated_at_utc": utc_now(),
        "purpose_pt": (
            "Calibração multi-exutório da G040: corredor Muçum + Encantado "
            "(Muçum roteado + residual Guaporé). Guaporé/Forqueta foz e Baixo "
            "ficam gated até haver Q oficial."
        ),
        "discipline": {
            "not_single_mucum_as_g040": True,
            "guapore_forqueta_downstream_of_mucum": True,
            "no_invented_stz_rating": True,
            "does_not_touch_rna": True,
            "research_not_alert": True,
        },
        "areas_km2": {
            "g040": AREA_G040_KM2,
            "mucum_corridor": AREA_MUCUM_KM2,
            "guapore": AREA_GUAPORE_KM2,
            "encantado_after_guapore": AREA_ENCANTADO_KM2,
            "forqueta": AREA_FORQUETA_KM2,
            "baixo_extra": AREA_BAIXO_EXTRA_KM2,
        },
        "outlets": outlet_catalog(),
        "engine": {
            "name": "python_hms_twin_mucum_route_plus_guapore_clark",
            "not_hec_hms_binary": True,
            "methods": [
                "Muçum Q boundary (obs/sim library)",
                "Muskingum Muçum→Encantado",
                "Initial+Constant + Clark on Guaporé (Open-Meteo point rain)",
            ],
        },
        "encantado_calibration": {
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
                    "Fecha Guaporé+corredor em Encantado; ainda não é foz Guaporé isolada "
                    "nem G040 completa."
                ),
            },
        },
        "blocked_next": [
            "Puxar curva-chave / vazão oficial 86595000 (foz Guaporé) e recalibrar tributário.",
            "Puxar curva-chave / vazão oficial 86746000 (Forqueta) e abrir outlet próprio.",
            "Baixo (Taquari 86950000): só nível hoje — precisa Q/curva antes de HMS-like.",
            "Trocar chuva Open-Meteo pontual por máscara areal ANA/INMET com coordenadas.",
        ],
        "artifacts": {
            "json": "modelo_g040_multi_exutorio_v1_latest.json",
            "html": "modelo_g040_multi_exutorio_v1.html",
        },
    }

    json_path = OUT / "modelo_g040_multi_exutorio_v1_latest.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # compact HTML
    rows_html = "\n".join(
        f"<tr><td>{r['event_id']}</td><td>{r['rain_sum_mm']:.0f}</td>"
        f"<td>{r['self_fit_nse']:.3f}</td><td>{r['nse_loo']:.3f}</td>"
        f"<td>{(r['peak_rel_err'] if r['peak_rel_err']==r['peak_rel_err'] else float('nan')):.2f}</td></tr>"
        for r in loo
    )
    outlets_html = "\n".join(
        f"<li><strong>{o['label_pt']}</strong> ({o['station_code']}) — "
        f"<code>{o['status']}</code> · {o.get('blocker_pt') or o.get('note_pt') or ''}</li>"
        for o in report["outlets"]
    )
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"/>
<title>G040 multi-exutório v1</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;margin:1.5rem;max-width:920px;color:#12241c}}
table{{border-collapse:collapse;width:100%}} th,td{{border-bottom:1px solid #c5d5cb;padding:.4rem;text-align:left}}
.muted{{color:#4a6356}} code{{background:#eef3ef;padding:.1rem .35rem;border-radius:4px}}
</style></head><body>
<h1>Gêmeo G040 multi-exutório v1</h1>
<p class="muted">{report['purpose_pt']}</p>
<p>Self-fit médio NSE <strong>{summary.get('mean_self_fit_nse')}</strong> ·
LOO NSE <strong>{summary.get('mean_nse_loo')}</strong> · pesquisa, não alerta.</p>
<h2>Exutórios</h2>
<ul>{outlets_html}</ul>
<h2>Encantado LOO</h2>
<table><thead><tr><th>Evento</th><th>Chuva Guaporé mm</th><th>Self-fit</th><th>NSE LOO</th><th>|err| pico</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<p class="muted">Gerado {report['generated_at_utc']}</p>
</body></html>
"""
    (OUT / "modelo_g040_multi_exutorio_v1.html").write_text(html, encoding="utf-8")
    print("wrote", json_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
