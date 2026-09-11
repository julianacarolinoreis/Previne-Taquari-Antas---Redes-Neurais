#!/usr/bin/env python3
"""Closed ~5-day Muçum forecast: rainfall forecast → HEC twin → how much level rises.

Product question: with forecast rain, how many cm does Muçum rise?
Santa Tereza: diagnostic Q only (no rating curve). Does not touch RNA. Research, not alert.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hec_twin_nested_v17 import NestedParams, ZoneParams  # noqa: E402
from run_hec_twin_stz_mucum_calibrate import run_network  # noqa: E402
import hec_twin_mucum_bacia_calibracao as bacia  # noqa: E402

OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
FORCING_DEFAULT = OUT / "hec_twin_ifs_forcing_5d_latest.json"
MODELO = OUT / "modelo_mucum_eventwise_v1_fechado_latest.json"
HEC = OUT / "hec_twin_stz_mucum_v1_latest.json"
ESTRUTURA = OUT / "estrutura_stz_mucum_latest.json"
CURVA_HUNT = OUT / "curva_chave_86472600" / "curva_chave_hunt_86472600_latest.json"
LIVE_MUCUM = ROOT / "previsao_ao_vivo_mucum.json"

SUBBASINS = [
    "SB_PRATA_7868",
    "SB_ANTAS_RESIDUAL",
    "SB_CARREIRO_7866",
    "SB_STZ_RESIDUAL",
    "SB_INC_MUCUM",
]
MUCUM_CODE = "86510000"
STZ_CODE = "86472600"
ANA_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA_MIRROR = "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_areas() -> dict[str, float]:
    estrutura = json.loads(ESTRUTURA.read_text(encoding="utf-8"))
    return {
        el["id"]: float(el["area_km2"])
        for el in estrutura["models"]["mucum"]["elements"]
        if el.get("type") == "subbasin"
    }


def params_from_library_row(row: dict[str, Any]) -> NestedParams:
    up = row["params"]["upstream"]
    dn = row["params"]["downstream"]
    return NestedParams(
        up=ZoneParams(
            initial_loss=float(up["initial_loss"]),
            constant_loss=float(up["constant_loss"]),
            tc=float(up["tc"]),
            storage=float(up["storage"]),
            recession=float(up["recession"]),
            initial_flow_ratio=float(up["initial_flow_ratio"]),
        ),
        dn=ZoneParams(
            initial_loss=float(dn["initial_loss"]),
            constant_loss=float(dn["constant_loss"]),
            tc=float(dn["tc"]),
            storage=float(dn["storage"]),
            recession=float(dn["recession"]),
            initial_flow_ratio=float(dn["initial_flow_ratio"]),
        ),
        k1=float(row["params"]["k1"]),
        k2=float(row["params"]["k2"]),
        k3=float(row["params"]["k3"]),
        x=float(row["params"].get("x", 0.2)),
    )


def event_core_rain_mm(hec_event: dict[str, Any]) -> float:
    return bacia.station_core_mean_mm(hec_event)


def choose_analogs(
    forecast_total_mm: float,
    library: list[dict[str, Any]],
    hec_events: list[dict[str, Any]],
    *,
    top_k: int = 3,
    fingerprints: dict[str, dict[str, Any]] | None = None,
    exclude_event_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Basin-calibrated analog transfer: AW rain fingerprint + loss-aware distance."""
    return bacia.choose_analogs(
        forecast_total_mm,
        library,
        hec_events,
        top_k=top_k,
        fingerprints=fingerprints,
        exclude_event_ids=exclude_event_ids,
    )


def scale_params_to_observed_q0(
    params: NestedParams,
    precip: dict[str, list[float]],
    areas: dict[str, float],
    q0_m3s: float | None,
) -> tuple[NestedParams, dict[str, Any]]:
    return bacia.scale_params_to_q0(
        params,
        precip,
        areas,
        q0_m3s,
        run_network=run_network,
        include_mucum_increment=True,
    )


def mucum_curve_segments() -> list[dict[str, Any]]:
    hunt = json.loads(CURVA_HUNT.read_text(encoding="utf-8"))
    block = (hunt.get("neighbors_official_curves_NOT_for_STZ") or {}).get(MUCUM_CODE) or {}
    segs = list(block.get("segments") or [])
    if not segs:
        raise RuntimeError("Muçum rating curve segments missing in hunt artifact")
    return segs


def q_to_stage_cm(q_m3s: float, segments: list[dict[str, Any]]) -> dict[str, Any]:
    if q_m3s is None or q_m3s != q_m3s or q_m3s < 0:
        return {"stage_cm": None, "ok": False, "reason": "invalid_q"}
    candidates: list[dict[str, Any]] = []
    for seg in segments:
        a = float(seg["a"])
        h0 = float(seg["h0_m"])
        n = float(seg["n"])
        if a <= 0 or n <= 0:
            continue
        h_m = h0 + (max(q_m3s, 0.0) / a) ** (1.0 / n)
        stage_cm = h_m * 100.0
        lo = float(seg["stage_min_cm"])
        hi = float(seg["stage_max_cm"])
        inside = lo - 1e-6 <= stage_cm <= hi + 1e-6
        candidates.append(
            {
                "stage_cm": stage_cm,
                "segment_number": seg.get("segment_number"),
                "inside": inside,
                "stage_min_cm": lo,
                "stage_max_cm": hi,
            }
        )
    if not candidates:
        return {"stage_cm": None, "ok": False, "reason": "no_segment"}
    inside = [c for c in candidates if c["inside"]]
    pick = inside[0] if inside else min(
        candidates,
        key=lambda c: abs(c["stage_cm"] - (c["stage_min_cm"] + c["stage_max_cm"]) / 2),
    )
    return {
        "stage_cm": round(float(pick["stage_cm"]), 2),
        "ok": True,
        "segment_number": pick["segment_number"],
        "inside_segment": bool(pick["inside"]),
        "extrapolated": not bool(pick["inside"]),
    }


def stage_to_q_m3s(stage_cm: float, segments: list[dict[str, Any]]) -> dict[str, Any]:
    if stage_cm is None or stage_cm != stage_cm:
        return {"q_m3s": None, "ok": False, "reason": "invalid_stage"}
    for seg in segments:
        lo = float(seg["stage_min_cm"])
        hi = float(seg["stage_max_cm"])
        if lo - 1e-6 <= stage_cm <= hi + 1e-6:
            h_m = stage_cm / 100.0
            q = float(seg["a"]) * max(h_m - float(seg["h0_m"]), 0.0) ** float(seg["n"])
            return {"q_m3s": round(q, 3), "ok": True, "segment_number": seg.get("segment_number")}
    return {"q_m3s": None, "ok": False, "reason": "stage_outside_curve"}


def _parse_ana_levels(xml_bytes: bytes) -> list[tuple[datetime, float]]:
    root = ET.fromstring(xml_bytes)
    rows: list[tuple[datetime, float]] = []
    for rec in root.iter():
        kids = {c.tag.split("}")[-1].lower(): (c.text or "").strip() for c in list(rec)}
        if not kids:
            continue
        ts_raw = kids.get("datahora") or kids.get("data_hora") or kids.get("data")
        nivel_raw = kids.get("nivel") or kids.get("nivelrio") or kids.get("cotaregua")
        if not ts_raw or not nivel_raw:
            continue
        try:
            nivel = float(str(nivel_raw).replace(",", "."))
        except ValueError:
            continue
        ts = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                ts = datetime.strptime(ts_raw[:19], fmt).replace(tzinfo=timezone(timedelta(hours=-3)))
                break
            except ValueError:
                continue
        if ts is None:
            continue
        rows.append((ts.astimezone(timezone.utc), nivel))
    rows.sort(key=lambda x: x[0])
    return rows


def fetch_mucum_level_now(*, allow_network: bool = True) -> dict[str, Any]:
    last_err = "not_tried"
    if allow_network:
        fim = datetime.now(timezone(timedelta(hours=-3)))
        ini = fim - timedelta(days=2)
        query = f"codEstacao={MUCUM_CODE}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}"
        for base in (ANA_URL, ANA_MIRROR):
            try:
                req = Request(f"{base}?{query}", headers={"User-Agent": "previne-hec-5d/1.0"})
                with urlopen(req, timeout=25) as resp:
                    series = _parse_ana_levels(resp.read())
                if series:
                    ts, nivel = series[-1]
                    return {
                        "ok": True,
                        "stage_cm": float(nivel),
                        "observed_at_utc": ts.isoformat().replace("+00:00", "Z"),
                        "source": "ANA_telemetria",
                        "station": MUCUM_CODE,
                    }
                last_err = "ana_empty"
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
    else:
        last_err = "network_disabled"

    if LIVE_MUCUM.exists():
        live = json.loads(LIVE_MUCUM.read_text(encoding="utf-8"))
        nivel = live.get("telemetria_ultima_nivel_cm")
        if nivel is not None:
            return {
                "ok": True,
                "stage_cm": float(nivel),
                "observed_at_utc": live.get("telemetria_ultima_em_utc") or live.get("telemetria_ultima_em"),
                "source": "previsao_ao_vivo_mucum.json",
                "station": str(live.get("estacao") or MUCUM_CODE),
                "fallback_reason": last_err,
            }
    return {"ok": False, "stage_cm": None, "observed_at_utc": None, "source": None, "station": MUCUM_CODE, "reason": last_err}


def member_rise(member: dict[str, Any], level_now_cm: float | None) -> dict[str, Any]:
    n_series = member["series"]["n_mucum_cm"]
    n0 = n_series[0] if n_series and n_series[0] is not None else None
    n_peak = member["peak_stage_mucum_cm"]
    rise_model = None if n0 is None or n_peak is None else round(float(n_peak) - float(n0), 2)
    anchored_peak = None if level_now_cm is None or rise_model is None else round(float(level_now_cm) + rise_model, 2)
    anchored_series = None
    if level_now_cm is not None and n0 is not None:
        anchored_series = [
            None if v is None else round(float(level_now_cm) + (float(v) - float(n0)), 2) for v in n_series
        ]
    return {
        "n_model_t0_cm": n0,
        "n_model_peak_cm": n_peak,
        "rise_model_cm": rise_model,
        "level_now_cm": level_now_cm,
        "peak_anchored_cm": anchored_peak,
        "n_anchored_cm": anchored_series,
        "peak_time_utc": member["peak_time_utc"],
    }


def build_quanto_sobe(
    members: list[dict[str, Any]],
    *,
    level_now: dict[str, Any],
    rain_mm: float,
    horizon_hours: int | None,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    now_cm = level_now.get("stage_cm") if level_now.get("ok") else None
    rises = [member_rise(m, now_cm) for m in members]
    for m, r in zip(members, rises):
        m["rise"] = {k: v for k, v in r.items() if k != "n_anchored_cm"}
        if r["n_anchored_cm"] is not None:
            m["series"]["n_mucum_anchored_cm"] = r["n_anchored_cm"]
            m["series"]["delta_n_from_now_cm"] = [
                None if v is None or now_cm is None else round(float(v) - float(now_cm), 2)
                for v in r["n_anchored_cm"]
            ]

    primary = rises[0]
    rise_vals = [r["rise_model_cm"] for r in rises if r["rise_model_cm"] is not None]
    q_now = stage_to_q_m3s(float(now_cm), segments) if now_cm is not None else {"ok": False}

    if primary["rise_model_cm"] is None:
        plain = "Não foi possível calcular a subida (série de nível do modelo vazia)."
    elif now_cm is None:
        plain = (
            f"Com ~{rain_mm:.1f} mm de chuva prevista em {horizon_hours or '?'} h, "
            f"o gêmeo HEC indica subida de ~{primary['rise_model_cm']:.0f} cm em Muçum "
            f"(banda {min(rise_vals):.0f}–{max(rise_vals):.0f} cm). "
            f"Pico do modelo em {primary['peak_time_utc']}. "
            "Nível observado atual indisponível — valor é ΔN do modelo, sem âncora."
        )
    else:
        plain = (
            f"Com ~{rain_mm:.1f} mm de chuva prevista em {horizon_hours or '?'} h e nível atual "
            f"{now_cm:.0f} cm em Muçum, o gêmeo HEC indica subida de ~{primary['rise_model_cm']:.0f} cm "
            f"(banda {min(rise_vals):.0f}–{max(rise_vals):.0f} cm), "
            f"pico ancorado ~{primary['peak_anchored_cm']:.0f} cm em {primary['peak_time_utc']}."
        )

    return {
        "question": "Com a chuva prevista, quanto sobe o nível em Muçum?",
        "method": "delta_n_model_applied_to_observed_stage",
        "method_note": (
            "ΔN = N_modelo(pico) − N_modelo(t0). Se há telemetria, "
            "N_ancorado(t) = N_obs + (N_modelo(t) − N_modelo(t0)). "
            "Não inventa curva STZ; não mexe na RNA."
        ),
        "rain_forecast_mm_area_weighted": round(float(rain_mm), 3),
        "horizon_hours": horizon_hours,
        "level_now": level_now,
        "q_now_from_rating_m3s": q_now,
        "primary": {
            "event_id": members[0]["event_id"],
            "rise_cm": primary["rise_model_cm"],
            "peak_time_utc": primary["peak_time_utc"],
            "peak_anchored_cm": primary["peak_anchored_cm"],
            "n_model_t0_cm": primary["n_model_t0_cm"],
            "n_model_peak_cm": primary["n_model_peak_cm"],
        },
        "ensemble_rise_cm": {
            "min": min(rise_vals) if rise_vals else None,
            "primary": primary["rise_model_cm"],
            "max": max(rise_vals) if rise_vals else None,
            "by_event": [
                {
                    "event_id": m["event_id"],
                    "rise_cm": r["rise_model_cm"],
                    "peak_anchored_cm": r["peak_anchored_cm"],
                }
                for m, r in zip(members, rises)
            ],
        },
        "plain_pt": plain,
    }


def build_package(
    forcing: dict[str, Any],
    *,
    event_id: str | None = None,
    allow_network: bool = True,
) -> dict[str, Any]:
    modelo = json.loads(MODELO.read_text(encoding="utf-8"))
    hec = json.loads(HEC.read_text(encoding="utf-8"))
    library = list(modelo.get("params_library_eventwise") or [])
    if not library:
        raise RuntimeError("empty eventwise params library")
    hec_events = list((hec.get("models") or {}).get("mucum", {}).get("events") or [])
    areas = load_areas()
    precip = forcing["precip_mm_by_subbasin"]
    for sb in SUBBASINS:
        if sb not in precip:
            raise RuntimeError(f"forcing missing {sb}")
        if sb not in areas:
            raise RuntimeError(f"area missing for {sb}")
    times = list(forcing["times_utc"])
    forecast_total = float(forcing["area_weighted_mean_mm"]["total_mm"])

    fingerprints = bacia.fingerprints_from_bacia_or_build(
        hec_events,
        areas,
        prepare_event_forcing=__import__(
            "run_hec_twin_stz_mucum_calibrate", fromlist=["prepare_event_forcing"]
        ).prepare_event_forcing,
    )

    if event_id:
        row = next((r for r in library if r["event_id"] == event_id), None)
        if row is None:
            raise RuntimeError(f"event {event_id} not in core library")
        he_ev = next((e for e in hec_events if e["event_id"] == event_id), {})
        fp = fingerprints.get(event_id) or {}
        analogs = [
            {
                "event_id": event_id,
                "historical_aw_full_mm": fp.get("aw_full_mm"),
                "historical_core_mean_mm": event_core_rain_mm(he_ev),
                "forecast_aw_total_mm": forecast_total,
                "abs_mm_gap": None,
                "distance": 0.0,
                "nse": row.get("nse"),
                "research_score": row.get("research_score"),
                "row": row,
            }
        ]
    else:
        analogs = choose_analogs(
            forecast_total,
            library,
            hec_events,
            top_k=3,
            fingerprints=fingerprints,
        )
        if not analogs:
            raise RuntimeError("no analogs scored")

    segments = mucum_curve_segments()
    level_now = fetch_mucum_level_now(allow_network=allow_network)
    q0 = None
    ic_meta_base: dict = {"applied": False, "reason": "no_observed_stage"}
    if level_now.get("ok") and level_now.get("stage_cm") is not None:
        q_from_stage = stage_to_q_m3s(float(level_now["stage_cm"]), segments)
        if q_from_stage.get("ok"):
            q0 = float(q_from_stage["q_m3s"])
            ic_meta_base = {"observed_stage_cm": level_now.get("stage_cm"), "q0_from_rating_m3s": q0}

    members: list[dict] = []
    for analog in analogs:
        params = params_from_library_row(analog["row"])
        params, ic_meta = scale_params_to_observed_q0(params, precip, areas, q0)
        ic_meta = {**ic_meta_base, **ic_meta}
        net = run_network(precip, areas, params, include_mucum_increment=True)
        q_mucum = net["at_mucum"]
        q_antas = net["at_antas"]
        q_stz = net["at_stz"]
        stages = [q_to_stage_cm(q, segments) for q in q_mucum]
        peak_i = max(range(len(q_mucum)), key=lambda i: q_mucum[i]) if q_mucum else 0
        members.append(
            {
                "event_id": analog["event_id"],
                "analog": {k: v for k, v in analog.items() if k != "row"},
                "params": params.to_dict(),
                "ic_scaling": ic_meta,
                "peak_q_mucum_m3s": round(float(q_mucum[peak_i]), 3),
                "peak_time_utc": times[peak_i] if times else None,
                "peak_stage_mucum_cm": stages[peak_i].get("stage_cm") if stages else None,
                "series": {
                    "time_utc": times,
                    "q_mucum_m3s": [round(float(x), 3) for x in q_mucum],
                    "q_antas_m3s": [round(float(x), 3) for x in q_antas],
                    "q_stz_diagnostic_m3s": [round(float(x), 3) for x in q_stz],
                    "n_mucum_cm": [s.get("stage_cm") for s in stages],
                    "n_mucum_meta": stages,
                },
            }
        )

    level_now = fetch_mucum_level_now(allow_network=allow_network)
    # Robust primary: member closest to median rise (before anchoring text)
    # Temporary rise from model series for ranking
    for m in members:
        n_series = m["series"]["n_mucum_cm"]
        n0 = n_series[0] if n_series else None
        npeak = m["peak_stage_mucum_cm"]
        m["rise"] = {
            "rise_model_cm": None if n0 is None or npeak is None else round(float(npeak) - float(n0), 2)
        }
    primary_idx = bacia.pick_primary_by_median_rise(members)
    if primary_idx != 0:
        members = [members[primary_idx]] + [m for i, m in enumerate(members) if i != primary_idx]

    quanto_sobe = build_quanto_sobe(
        members,
        level_now=level_now,
        rain_mm=forecast_total,
        horizon_hours=forcing.get("horizon_hours"),
        segments=segments,
    )
    primary = members[0]

    band_q = []
    band_n = []
    for i in range(len(times)):
        q_vals = [m["series"]["q_mucum_m3s"][i] for m in members]
        band_q.append({"min": min(q_vals), "max": max(q_vals), "primary": q_vals[0]})
        n_vals = []
        for m in members:
            series_n = m["series"].get("n_mucum_anchored_cm") or m["series"]["n_mucum_cm"]
            if series_n[i] is not None:
                n_vals.append(series_n[i])
        band_n.append(
            {"min": min(n_vals), "max": max(n_vals), "primary": n_vals[0]} if n_vals else {"min": None, "max": None, "primary": None}
        )

    return {
        "schema_version": "hec_twin_mucum_forward_5d_v2",
        "generated_at_utc": utc_now(),
        "status": "research_forward_5d_ready",
        "label": (
            "PESQUISA — com a chuva prevista, quanto sobe Muçum (~5 dias, gêmeo HEC + IFS). "
            "NÃO é alerta oficial."
        ),
        "purpose": (
            "Responder quanto o nível sobe em Muçum dado a chuva prevista. "
            "RNA permanece no curto prazo e não é alterada aqui."
        ),
        "quanto_sobe": quanto_sobe,
        "decision_alignment": {
            "primary_for_multiday": "HEC_twin_plus_IFS_QPF",
            "short_horizon_complement": "RNA_nivel_2h_4h_8h",
            "stz_rating_curve": "absent — no N@STZ from HEC; Q@STZ diagnostic only",
            "do_not": [
                "invent_stz_rating_curve",
                "promote_common_search_params",
                "call_this_official_alert",
                "modify_rna",
            ],
        },
        "forcing": {
            "artifact": "hec_twin_ifs_forcing_5d_latest.json",
            "model": forcing.get("model"),
            "horizon_hours": forcing.get("horizon_hours"),
            "area_weighted_total_mm": forecast_total,
            "generated_at_utc": forcing.get("generated_at_utc"),
            "point_proxy_not_areal_mask": True,
        },
        "param_selection": {
            "method": "analog_basin_calibrated_aw_fingerprint_v1" if event_id is None else "forced_event_id",
            "forced_event_id": event_id,
            "analogs": [{k: v for k, v in a.items() if k != "row"} for a in analogs],
            "common_search": "blocked_not_used",
            "basin_calibration": {
                "artifact": "modelo_mucum_bacia_calibrado_v1_latest.json",
                "rain_fingerprint": "area_weighted_full_window_mm",
                "ic_scaling": "observed_stage_to_q0_via_mucum_rating",
                "light_specialists": ["E30"],
                "primary_rule": "median_rise_member",
            },
        },
        "primary_member": {
            "event_id": primary["event_id"],
            "peak_q_mucum_m3s": primary["peak_q_mucum_m3s"],
            "peak_time_utc": primary["peak_time_utc"],
            "peak_stage_mucum_cm": primary["peak_stage_mucum_cm"],
            "rise_cm": primary.get("rise", {}).get("rise_model_cm"),
            "peak_anchored_cm": primary.get("rise", {}).get("peak_anchored_cm"),
            "params": primary["params"],
        },
        "ensemble_members": [
            {
                "event_id": m["event_id"],
                "analog": m["analog"],
                "peak_q_mucum_m3s": m["peak_q_mucum_m3s"],
                "peak_time_utc": m["peak_time_utc"],
                "peak_stage_mucum_cm": m["peak_stage_mucum_cm"],
                "rise_cm": m.get("rise", {}).get("rise_model_cm"),
                "peak_anchored_cm": m.get("rise", {}).get("peak_anchored_cm"),
            }
            for m in members
        ],
        "series_primary": primary["series"],
        "q_mucum_band_m3s": band_q,
        "n_mucum_anchored_band_cm": band_n,
        "rating_curve_mucum": {
            "station": MUCUM_CODE,
            "source": "curva_chave_hunt → neighbors_official_curves_NOT_for_STZ.86510000",
            "n_segments": len(segments),
        },
        "santa_tereza": {
            "station": STZ_CODE,
            "q_status": "diagnostic_only_not_calibrated",
            "n_status": "blocked_no_rating_curve",
            "note": "Sem curva-chave oficial: HEC não publica N em STZ. Curto prazo: RNA STZ.",
        },
        "artifacts": {
            "json": "hec_twin_mucum_forward_5d_latest.json",
            "html": "hec_twin_mucum_forward_5d.html",
            "csv": "hec_twin_mucum_forward_5d/primary_series.csv",
        },
        "_members_full": members,
    }


def write_csv(package: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    series = package["series_primary"]
    band = package["q_mucum_band_m3s"]
    anchored = series.get("n_mucum_anchored_cm") or [None] * len(series["time_utc"])
    delta = series.get("delta_n_from_now_cm") or [None] * len(series["time_utc"])
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "time_utc",
                "q_mucum_m3s",
                "q_mucum_band_min",
                "q_mucum_band_max",
                "n_mucum_cm",
                "n_mucum_anchored_cm",
                "delta_n_from_now_cm",
                "q_antas_m3s",
                "q_stz_diagnostic_m3s",
            ]
        )
        for i, t in enumerate(series["time_utc"]):
            w.writerow(
                [
                    t,
                    series["q_mucum_m3s"][i],
                    band[i]["min"],
                    band[i]["max"],
                    series["n_mucum_cm"][i],
                    anchored[i],
                    delta[i],
                    series["q_antas_m3s"][i],
                    series["q_stz_diagnostic_m3s"][i],
                ]
            )


def render_html(package: dict[str, Any]) -> str:
    p = package["primary_member"]
    qs = package["quanto_sobe"]
    analogs = "".join(
        (
            f"<li><code>{html.escape(m['event_id'])}</code> — sobe {m.get('rise_cm')} cm"
            f" · pico ancorado {m.get('peak_anchored_cm')} cm"
            f" · Q {m['peak_q_mucum_m3s']} m³/s"
            f" · gap chuva {m['analog'].get('abs_mm_gap')} mm</li>"
        )
        for m in package["ensemble_members"]
    )
    series = package["series_primary"]
    rows = []
    for i, t in enumerate(series["time_utc"]):
        if i % 6 != 0 and i != len(series["time_utc"]) - 1:
            continue
        anchored = (series.get("n_mucum_anchored_cm") or [None])[i]
        delta = (series.get("delta_n_from_now_cm") or [None])[i]
        rows.append(
            "<tr>"
            f"<td>{html.escape(t)}</td>"
            f"<td>{series['q_mucum_m3s'][i]}</td>"
            f"<td>{package['q_mucum_band_m3s'][i]['min']}–{package['q_mucum_band_m3s'][i]['max']}</td>"
            f"<td>{anchored}</td>"
            f"<td>{delta}</td>"
            f"<td>{series['q_stz_diagnostic_m3s'][i]}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<title>HEC · quanto sobe Muçum (~5d)</title>
<style>
:root {{ --ink:#14231c; --muted:#4d6358; --card:#f7fbf8; --ok:#1f6b4a; --warn:#8a5a12; }}
body {{ margin:0; font-family:"Source Serif 4",Georgia,serif; color:var(--ink);
  background:radial-gradient(900px 500px at 0% 0%, #cfe0d4, transparent), linear-gradient(160deg,#d9e6de,#f2f6f3); }}
main {{ max-width:960px; margin:0 auto; padding:2rem 1.1rem 3rem; }}
h1 {{ font-size:clamp(1.5rem,3vw,2.1rem); margin:0 0 .4rem; }}
.lead {{ color:var(--muted); }}
.pill {{ display:inline-block; padding:.2rem .65rem; border:1px solid #9bb8a8; color:var(--ok); font-size:.85rem; }}
.notice {{ padding:.85rem 1rem; margin:1rem 0; background:#e3f0e8; border-left:4px solid var(--ok); }}
.notice.warn {{ background:#f5ecda; border-left-color:var(--warn); }}
.hero {{ font-size:1.35rem; line-height:1.45; }}
section {{ margin-top:1.5rem; border-top:1px solid #c5d5cc; padding-top:1rem; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); font-size:.92rem; }}
th,td {{ text-align:left; padding:.4rem .5rem; border-bottom:1px solid #d5e0da; }}
th {{ color:var(--muted); font-size:.75rem; text-transform:uppercase; letter-spacing:.04em; }}
code {{ font-family:ui-monospace,monospace; font-size:.86em; }}
</style>
</head>
<body>
<main>
<p class="pill">{html.escape(package['status'])}</p>
<h1>Com a chuva prevista, quanto sobe Muçum?</h1>
<p class="lead">{html.escape(package['purpose'])}</p>
<div class="notice warn"><strong>{html.escape(package['label'])}</strong></div>
<div class="notice hero"><strong>Resposta:</strong> {html.escape(qs['plain_pt'])}</div>
<div class="notice">
  <strong>Números:</strong> chuva IFS ~{qs['rain_forecast_mm_area_weighted']} mm / {qs.get('horizon_hours')} h
  · ΔN principal <strong>{qs['primary']['rise_cm']}</strong> cm
  · banda {qs['ensemble_rise_cm']['min']}–{qs['ensemble_rise_cm']['max']} cm
  · pico ancorado <strong>{qs['primary']['peak_anchored_cm']}</strong> cm
  · análogo <code>{html.escape(p['event_id'])}</code>
  · em {html.escape(str(p['peak_time_utc']))}
</div>
<section>
<h2>Método (honesto)</h2>
<ul>
<li>Chuva prevista (IFS) → gêmeo HEC eventwise → Q Muçum → curva-chave → N.</li>
<li>ΔN = N_modelo(pico) − N_modelo(início); se há telemetria, ancora no nível atual.</li>
<li>RNA não é alterada. Santa Tereza sem curva: só Q diagnóstico.</li>
</ul>
</section>
<section>
<h2>Ensemble de análogos (top 3)</h2>
<ul>{analogs}</ul>
</section>
<section>
<h2>Série ancorada (amostra 6 h)</h2>
<table>
<thead><tr><th>UTC</th><th>Q Muçum</th><th>banda Q</th><th>N ancorado cm</th><th>ΔN cm</th><th>Q STZ diag.</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>
<section>
<h2>Disciplina</h2>
<ul>
<li>Params = biblioteca eventwise (análogo por chuva); common-search bloqueado.</li>
<li>Forçante IFS é proxy pontual por sub-bacia — não máscara areal fechada.</li>
<li>Não inventar curva STZ. Não chamar de alerta oficial.</li>
</ul>
<p><a href="hec_twin_mucum_forward_5d_latest.json">JSON</a> ·
<a href="hec_twin_mucum_forward_5d/primary_series.csv">CSV</a> ·
<a href="hec_twin_ifs_forcing_5d_latest.json">Forçante IFS</a></p>
</section>
</main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forcing", type=Path, default=FORCING_DEFAULT)
    parser.add_argument("--event-id", type=str, default=None)
    parser.add_argument("--offline", action="store_true", help="Do not call ANA; use live JSON fallback.")
    args = parser.parse_args()
    if not args.forcing.exists():
        raise SystemExit(
            f"missing forcing: {args.forcing} (run build_hec_twin_ifs_forcing_5d.py first)"
        )

    forcing = json.loads(args.forcing.read_text(encoding="utf-8"))
    package = build_package(forcing, event_id=args.event_id, allow_network=not args.offline)
    members_full = package.pop("_members_full")

    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "hec_twin_mucum_forward_5d_latest.json"
    html_path = OUT / "hec_twin_mucum_forward_5d.html"
    csv_path = OUT / "hec_twin_mucum_forward_5d" / "primary_series.csv"
    ens_path = OUT / "hec_twin_mucum_forward_5d" / "ensemble_members.json"

    json_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(package), encoding="utf-8")
    write_csv(package, csv_path)
    ens_path.parent.mkdir(parents=True, exist_ok=True)
    ens_path.write_text(json.dumps(members_full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    qs = package["quanto_sobe"]
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    print(f"wrote {csv_path}")
    print(
        f"primary={package['primary_member']['event_id']} "
        f"rise_cm={qs['primary']['rise_cm']} "
        f"peak_anchored_cm={qs['primary']['peak_anchored_cm']} "
        f"rain_mm={qs['rain_forecast_mm_area_weighted']}"
    )
    print(qs["plain_pt"])


if __name__ == "__main__":
    main()
