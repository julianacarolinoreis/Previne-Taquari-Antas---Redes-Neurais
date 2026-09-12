#!/usr/bin/env python3
"""Replay Muçum live eval with now-index blend transfer and score vs ANA.

Research only. Does not touch RNA. Does not invent STZ rating curve.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hec_twin_mucum_bacia_calibracao as bacia  # noqa: E402
import run_hec_twin_mucum_forward_5d as fwd  # noqa: E402

OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
FORCING = OUT / "hec_twin_ifs_forcing_live_eval_latest.json"
EVAL = OUT / "hec_twin_mucum_live_eval_latest.json"
VERIFY = OUT / "hec_twin_mucum_live_eval_verify_latest.json"
HTML = OUT / "hec_twin_mucum_live_eval.html"
ART = Path("/opt/cursor/artifacts")

MUCUM_CODE = "86510000"
UA = "PREVINE-live-eval-replay/1.3"
ANCHOR_UTC = "2026-09-12T02:45:00Z"
ANCHOR_CM = 425.0
OLD_PRIMARY_PEAK = 568.0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ana(xml_bytes: bytes) -> list[tuple[datetime, float]]:
    root = ET.fromstring(xml_bytes)
    rows: list[tuple[datetime, float]] = []
    for rec in root.iter():
        kids = {c.tag.split("}")[-1].lower(): (c.text or "").strip() for c in list(rec)}
        ts = kids.get("datahora") or kids.get("data")
        nv = kids.get("nivel") or kids.get("nivelrio")
        if not ts or not nv:
            continue
        try:
            nivel = float(nv.replace(",", "."))
        except ValueError:
            continue
        tsl = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                tsl = datetime.strptime(ts[:19], fmt).replace(tzinfo=timezone(timedelta(hours=-3)))
                break
            except ValueError:
                continue
        if tsl is None:
            continue
        rows.append((tsl.astimezone(timezone.utc), nivel))
    by = {t: n for t, n in rows}
    return sorted(by.items())


def fetch_ana_series() -> list[tuple[datetime, float]]:
    fim = datetime.now(timezone(timedelta(hours=-3)))
    ini = fim - timedelta(days=4)
    q = f"codEstacao={MUCUM_CODE}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}"
    url = f"https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos?{q}"
    last: Exception | None = None
    for i in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as resp:
                return parse_ana(resp.read())
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2**i)
    raise RuntimeError(f"ANA fetch failed: {last}")


def nearest_index(times: list[str], when: datetime) -> int:
    def parse(ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    return min(range(len(times)), key=lambda i: abs((parse(times[i]) - when).total_seconds()))


def mid_event_revision(
    pkg: dict[str, Any],
    *,
    obs_now_cm: float,
    obs_at: datetime,
) -> dict[str, Any]:
    series = pkg.get("series_primary") or {}
    times = list(series.get("time_utc") or [])
    n_model = list(series.get("n_mucum_cm") or [])
    if not times or not n_model:
        return {"applied": False, "reason": "missing_series"}

    basin = ((pkg.get("param_selection") or {}).get("basin_calibration") or {})
    now_index = int(basin.get("now_index") or 0)
    now_index = min(max(now_index, 0), len(n_model) - 1)
    obs_i = max(nearest_index(times, obs_at), now_index)

    n0 = n_model[now_index]
    n_at_obs = n_model[obs_i]
    if n0 is None or n_at_obs is None:
        return {"applied": False, "reason": "null_model_stage"}

    future = [float(v) for v in n_model[obs_i:] if v is not None]
    if not future:
        return {"applied": False, "reason": "no_future"}
    peak_model = max(future)
    peak_rel = max(
        range(len(n_model) - obs_i),
        key=lambda j: -1e18 if n_model[obs_i + j] is None else float(n_model[obs_i + j]),
    )
    peak_time = times[obs_i + peak_rel]

    remaining = max(0.0, peak_model - float(n_at_obs))
    under = float(obs_now_cm) - float(n_at_obs)
    model_peak_rise = max(0.0, peak_model - float(n0))
    revised = bacia.revise_remaining_rise_cm(remaining, under, model_peak_rise)
    peak_reanchor = float(obs_now_cm) + float(revised["remaining_cm"])

    return {
        "applied": True,
        "obs_index": obs_i,
        "obs_time_utc": times[obs_i],
        "n_model_at_obs_cm": round(float(n_at_obs), 2),
        "n_model_peak_cm": round(peak_model, 2),
        "remaining_model_cm": round(remaining, 2),
        "underprediction_cm": round(under, 2),
        "revision": revised,
        "peak_reanchored_cm": round(peak_reanchor, 2),
        "rise_from_obs_cm": round(float(revised["remaining_cm"]), 2),
        "peak_time_utc": peak_time,
    }


def main() -> None:
    forcing = json.loads(FORCING.read_text(encoding="utf-8"))
    aw = forcing.setdefault("area_weighted_mean_mm", {})
    if "past_mm" not in aw and forcing.get("window"):
        past_h = int(forcing["window"].get("past_hours") or 48)
        hourly = list(aw.get("hourly") or [])
        aw["past_mm"] = round(sum(hourly[:past_h]), 3)
        aw["future_mm"] = round(sum(hourly[past_h:]), 3)

    level_now = {
        "ok": True,
        "stage_cm": ANCHOR_CM,
        "observed_at_utc": ANCHOR_UTC,
        "source": "ANA_anchor_replay",
        "station": MUCUM_CODE,
    }
    forcing["stage_rising"] = True

    orig = fwd.fetch_mucum_level_now
    fwd.fetch_mucum_level_now = lambda *, allow_network=True: level_now
    pkg = fwd.build_package(forcing, allow_network=False)
    fwd.fetch_mucum_level_now = orig

    qs = pkg["quanto_sobe"]
    primary = qs["primary"]
    band = qs["ensemble_rise_cm"]
    pred_rise = float(primary["rise_cm"])
    pred_peak = float(primary["peak_anchored_cm"])

    series = fetch_ana_series()
    t0 = datetime.fromisoformat(ANCHOR_UTC.replace("Z", "+00:00"))
    after = [(t, n) for t, n in series if t >= t0]
    latest_t, latest_n = series[-1]
    rise_obs = latest_n - ANCHOR_CM
    peak_t, peak_n = max(after, key=lambda x: x[1]) if after else (latest_t, latest_n)

    mid = mid_event_revision(pkg, obs_now_cm=latest_n, obs_at=latest_t)

    within = band["min"] - 1e-6 <= rise_obs <= band["max"] + 1e-6
    above_primary = latest_n > pred_peak
    old_err = latest_n - OLD_PRIMARY_PEAK
    new_err = latest_n - pred_peak
    mid_err = None if not mid.get("applied") else latest_n - float(mid["peak_reanchored_cm"])

    if within and not above_primary:
        verdict = "hit_band_and_primary_so_far"
        plain = (
            f"Calibração v3 (now-index+blend): primary {primary['event_id']} ΔN≈{pred_rise:.0f} cm "
            f"(pico≈{pred_peak:.0f}). Obs {latest_n:.0f} cm (+{rise_obs:.0f}) dentro da banda "
            f"{band['min']:.0f}–{band['max']:.0f} e ainda sob o pico primary."
        )
    elif within and above_primary:
        verdict = "partial_hit_band_primary_low"
        plain = (
            f"Calibração v3: primary {primary['event_id']} ΔN≈{pred_rise:.0f} (pico≈{pred_peak:.0f}). "
            f"Obs {latest_n:.0f} (+{rise_obs:.0f}) na banda, mas já acima do primary."
        )
    elif rise_obs > band["max"]:
        verdict = "miss_high"
        plain = (
            f"Ainda baixo: primary {primary['event_id']} banda até {band['max']:.0f} cm, "
            f"obs +{rise_obs:.0f} cm (nível {latest_n:.0f})."
        )
    else:
        verdict = "miss_low_or_other"
        plain = (
            f"Replay v3: primary {primary['event_id']} ΔN≈{pred_rise:.0f}; "
            f"obs +{rise_obs:.0f} (nível {latest_n:.0f})."
        )

    if mid.get("applied"):
        plain += (
            f" Atualização no meio do evento (obs {latest_n:.0f}): ainda ~{mid['rise_from_obs_cm']:.0f} cm "
            f"(pico revisto ~{mid['peak_reanchored_cm']:.0f})."
        )

    payload = {
        "schema_version": "hec_twin_mucum_live_eval_v5_nowindex_blend",
        "generated_at_utc": utc_now(),
        "status": "research_live_eval_replay_ready",
        "label_pt": "Replay ao vivo com now-index + blend — Muçum",
        "observations": {
            "level_now": level_now,
            "latest_ana": {
                "stage_cm": latest_n,
                "observed_at_utc": latest_t.isoformat().replace("+00:00", "Z"),
                "rise_from_anchor_cm": round(rise_obs, 2),
                "peak_so_far_cm": peak_n,
                "peak_so_far_at_utc": peak_t.isoformat().replace("+00:00", "Z"),
            },
        },
        "rain_ifs": {
            "past_48h_mm": aw.get("past_mm"),
            "next_72h_mm": aw.get("future_mm"),
            "window_total_mm": aw.get("total_mm"),
        },
        "param_selection": pkg.get("param_selection"),
        "answer_from_anchor": {
            "question_pt": "A partir do nível na âncora, quanto sobe?",
            "method": "now_index_ic_plus_distance_weighted_blend_v3",
            "plain_pt": qs.get("plain_pt"),
            "primary": primary,
            "ensemble_rise_cm": band,
        },
        "answer_from_latest_obs": mid,
        "verification": {
            "verdict_level": verdict,
            "plain_pt": plain,
            "old_primary_peak_cm": OLD_PRIMARY_PEAK,
            "new_primary_peak_cm": pred_peak,
            "mid_event_peak_cm": mid.get("peak_reanchored_cm"),
            "obs_latest_cm": latest_n,
            "old_error_cm": round(old_err, 2),
            "new_error_cm": round(new_err, 2),
            "mid_event_error_cm": None if mid_err is None else round(mid_err, 2),
            "improved_vs_old": abs(new_err) < abs(old_err),
            "rise_within_band": within,
            "above_primary_peak": above_primary,
        },
        "interpretation_pt": plain,
        "plain_pt": plain,
        "discipline": {
            "not_official_alert": True,
            "rna_untouched": True,
            "stz_no_rating_curve": True,
        },
    }

    EVAL.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verify = {
        "schema_version": "hec_twin_mucum_live_eval_verify_v3",
        "generated_at_utc": utc_now(),
        "status": "research_verification_ready",
        "forecast_ref": {
            "method": "now_index_blend_v3",
            "anchor_stage_cm": ANCHOR_CM,
            "anchor_observed_at_utc": ANCHOR_UTC,
            "predicted_rise_cm": pred_rise,
            "predicted_peak_anchored_cm": pred_peak,
            "predicted_peak_time_utc": primary.get("peak_time_utc"),
            "ensemble_rise_cm": band,
            "analog": primary.get("event_id"),
            "mid_event": mid,
        },
        "observed": payload["observations"]["latest_ana"],
        "scorecard": payload["verification"],
        "plain_pt": plain,
    }
    VERIFY.write_text(json.dumps(verify, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mid_err_txt = "n/a" if mid_err is None else f"{mid_err:+.0f}"
    HTML.write_text(
        f"""<!DOCTYPE html><html lang=pt-BR><meta charset=utf-8>
<title>Live eval Muçum (v3 now+blend)</title>
<body style="font-family:Georgia,serif;max-width:900px;margin:2rem auto;padding:0 1rem;background:#eef3ef;color:#14231c">
<p style="border:1px solid #9bb8a8;display:inline-block;padding:.2rem .6rem">pesquisa · replay v3</p>
<h1>Muçum — previsão calibrada vs observado</h1>
<p><strong>{plain}</strong></p>
<ul>
<li>Âncora: {ANCHOR_CM:.0f} cm</li>
<li>Previsto (blend): +{pred_rise:.0f} cm → {pred_peak:.0f} cm</li>
<li>Observado: {latest_n:.0f} cm (+{rise_obs:.0f})</li>
<li>Erro antigo ({OLD_PRIMARY_PEAK:.0f}): {old_err:+.0f} cm → erro novo: {new_err:+.0f} cm</li>
<li>Meio do evento (revisto): pico ~{mid.get('peak_reanchored_cm')} (erro {mid_err_txt} cm)</li>
</ul>
</body></html>
""",
        encoding="utf-8",
    )
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "hec_twin_mucum_live_eval_latest.json").write_text(EVAL.read_text(encoding="utf-8"), encoding="utf-8")
    (ART / "hec_twin_mucum_live_eval_verify_latest.json").write_text(VERIFY.read_text(encoding="utf-8"), encoding="utf-8")
    (ART / "hec_twin_mucum_live_eval.html").write_text(HTML.read_text(encoding="utf-8"), encoding="utf-8")
    (ART / "hec_twin_mucum_v3_improve_summary.log").write_text(
        plain
        + f"\nold_err={old_err:+.1f} new_err={new_err:+.1f} mid_err={mid_err}\n"
        + f"primary={primary}\nband={band}\nmid={mid}\n",
        encoding="utf-8",
    )
    print(plain)
    print("old_err", old_err, "new_err", new_err, "mid_err", mid_err)
    print("primary", primary)
    print("band", band)
    print("mid", mid)


if __name__ == "__main__":
    main()
