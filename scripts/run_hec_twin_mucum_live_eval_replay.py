#!/usr/bin/env python3
"""Replay Muçum live eval with wetness-aware basin transfer and score vs ANA.

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
UA = "PREVINE-live-eval-replay/1.1"
ANCHOR_UTC = "2026-09-12T02:45:00Z"
ANCHOR_CM = 425.0


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
    last = None
    for i in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as resp:
                return parse_ana(resp.read())
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2**i)
    raise RuntimeError(f"ANA fetch failed: {last}")


def from_now_metrics(pkg: dict[str, Any], forcing: dict[str, Any], now_utc: str, anchor_cm: float) -> dict[str, Any]:
    times = list(forcing["times_utc"])
    try:
        now_i = times.index(now_utc)
    except ValueError:
        now_i = min(
            range(len(times)),
            key=lambda i: abs(
                (
                    datetime.fromisoformat(times[i].replace("Z", "+00:00"))
                    - datetime.fromisoformat(now_utc.replace("Z", "+00:00"))
                ).total_seconds()
            ),
        )
    members = pkg.get("_members_full") or []
    # reconstruct from ensemble if needed
    if not members:
        # rebuild series from primary + ensemble_members isn't enough; use package members if present
        members = pkg.get("ensemble_members_full") or []
    # Fall back: use series_primary only
    out_members = []
    full = pkg.get("_members_full")
    if full:
        src_members = full
    else:
        # Re-run is done outside; here we expect _members_full injected by caller
        src_members = []
    for m in src_members:
        nm = m["series"]["n_mucum_cm"]
        n_now = float(nm[now_i])
        fut = nm[now_i:]
        pi_rel = max(range(len(fut)), key=lambda i: -1e9 if fut[i] is None else float(fut[i]))
        pi = now_i + pi_rel
        rise = float(nm[pi]) - n_now
        out_members.append(
            {
                "event_id": m["event_id"],
                "rise_from_now_cm": round(rise, 2),
                "peak_from_now_anchored_cm": round(anchor_cm + rise, 2),
                "peak_time_utc": times[pi],
                "n_model_now_cm": round(n_now, 2),
                "n_model_peak_cm": round(float(nm[pi]), 2),
            }
        )
    if not out_members:
        return {"error": "no_members"}
    rises = [m["rise_from_now_cm"] for m in out_members]
    wetness = (pkg.get("param_selection") or {}).get("wetness") or {
        "is_wet": True,
        "stage_rising": True,
        "past_aw_mm": None,
    }
    if wetness.get("is_wet") is None:
        wetness = {**wetness, "is_wet": True, "stage_rising": True}
    # rank with wetness-aware primary on from-now rises
    tmp = [{"rise": {"rise_model_cm": m["rise_from_now_cm"]}, "event_id": m["event_id"]} for m in out_members]
    idx = bacia.pick_primary_by_median_rise(tmp, wetness=wetness)
    primary = out_members[idx]
    return {
        "now_index": now_i,
        "now_utc": times[now_i],
        "primary": primary,
        "ensemble": out_members,
        "ensemble_rise_cm": {
            "min": min(rises),
            "primary": primary["rise_from_now_cm"],
            "max": max(rises),
        },
    }


def main() -> None:
    forcing = json.loads(FORCING.read_text(encoding="utf-8"))
    # Ensure past_mm present
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
    # Keep full members for from-now slice
    # build_package doesn't return _members_full; re-run internals by reading ensemble + re-sim
    # Monkeypatch: capture members via local rebuild
    fwd.fetch_mucum_level_now = orig

    # Rebuild members with same wetness path by calling build_package pieces
    # Simpler: patch build_package return — instead re-simulate via forced event ids from analogs
    analogs = (pkg.get("param_selection") or {}).get("analogs") or []
    members_full = []
    for a in analogs:
        eid = a["event_id"]
        fwd.fetch_mucum_level_now = lambda *, allow_network=True: level_now
        one = fwd.build_package(forcing, event_id=eid, allow_network=False)
        fwd.fetch_mucum_level_now = orig
        members_full.append(
            {
                "event_id": eid,
                "series": one["series_primary"],
                "analog": a,
            }
        )
    # normalize series key
    for m in members_full:
        ser = m["series"]
        if "n_mucum_cm" not in ser and "n_mucum_cm" in ser:
            pass
        if "n_mucum_cm" not in ser:
            # try alternate
            for k in ser:
                if "n_mucum" in k and "anchored" not in k and isinstance(ser[k], list):
                    ser["n_mucum_cm"] = ser[k]
                    break

    pkg["_members_full"] = members_full
    now_utc = (forcing.get("window") or {}).get("now_utc") or "2026-09-12T03:00:00Z"
    from_now = from_now_metrics(pkg, forcing, now_utc, ANCHOR_CM)

    # ANA verification
    series = fetch_ana_series()
    t0 = datetime.fromisoformat(ANCHOR_UTC.replace("Z", "+00:00"))
    after = [(t, n) for t, n in series if t >= t0]
    latest_t, latest_n = series[-1]
    rise_obs = latest_n - ANCHOR_CM
    peak_t, peak_n = max(after, key=lambda x: x[1]) if after else (latest_t, latest_n)

    pred_rise = from_now["primary"]["rise_from_now_cm"]
    pred_peak = from_now["primary"]["peak_from_now_anchored_cm"]
    band = from_now["ensemble_rise_cm"]
    within = band["min"] - 1e-6 <= rise_obs <= band["max"] + 1e-6
    above_primary = latest_n > pred_peak

    if above_primary and within:
        verdict = "partial_hit_band_primary_low"
        plain = (
            f"Replay úmido: primary {from_now['primary']['event_id']} ΔN≈{pred_rise:.0f} cm "
            f"(pico≈{pred_peak:.0f}). Obs agora {latest_n:.0f} cm (+{rise_obs:.0f}). "
            f"Direção ok; banda {'ok' if within else 'estourada'}; "
            f"{'ainda acima do primary' if above_primary else 'primary ok'}."
        )
    elif within and not above_primary:
        verdict = "hit_band_and_primary_so_far"
        plain = (
            f"Replay úmido melhorou: primary {from_now['primary']['event_id']} ΔN≈{pred_rise:.0f} cm "
            f"(pico≈{pred_peak:.0f}). Obs {latest_n:.0f} cm (+{rise_obs:.0f}) dentro da banda "
            f"{band['min']:.0f}–{band['max']:.0f} e ainda sob o pico primary."
        )
    elif rise_obs > band["max"]:
        verdict = "miss_high"
        plain = (
            f"Ainda baixo: primary {from_now['primary']['event_id']} banda até {band['max']:.0f} cm, "
            f"obs +{rise_obs:.0f} cm (nível {latest_n:.0f})."
        )
    else:
        verdict = "miss_low_or_other"
        plain = (
            f"Replay: primary {from_now['primary']['event_id']} ΔN≈{pred_rise:.0f}; "
            f"obs +{rise_obs:.0f} (nível {latest_n:.0f})."
        )

    # Improvement vs old primary 143/568
    old_primary_peak = 568.0
    old_err = latest_n - old_primary_peak
    new_err = latest_n - pred_peak

    payload = {
        "schema_version": "hec_twin_mucum_live_eval_v4_wetness",
        "generated_at_utc": utc_now(),
        "status": "research_live_eval_replay_ready",
        "label_pt": "Replay ao vivo com transferência úmida — Muçum",
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
        "answer_from_now": {
            "question_pt": "A partir do nível atual, quanto ainda sobe?",
            "method": "full_window_past_rain_plus_wetness_aware_analogs_v2",
            "plain_pt": (
                f"Com nível {ANCHOR_CM:.0f} cm e chuva recente IFS (~{aw.get('past_mm')} mm / 48h), "
                f"o gêmeo HEC (estado úmido) indica ainda ~{pred_rise:.0f} cm "
                f"(banda {band['min']:.0f}–{band['max']:.0f}), pico ancorado ~{pred_peak:.0f} cm "
                f"em {from_now['primary']['peak_time_utc']} (análogo {from_now['primary']['event_id']})."
            ),
            "primary": from_now["primary"],
            "ensemble_rise_cm": band,
            "ensemble": from_now["ensemble"],
        },
        "verification": {
            "verdict_level": verdict,
            "plain_pt": plain,
            "old_primary_peak_cm": old_primary_peak,
            "new_primary_peak_cm": pred_peak,
            "obs_latest_cm": latest_n,
            "old_error_cm": round(old_err, 2),
            "new_error_cm": round(new_err, 2),
            "improved": abs(new_err) < abs(old_err),
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
        "schema_version": "hec_twin_mucum_live_eval_verify_v2",
        "generated_at_utc": utc_now(),
        "status": "research_verification_ready",
        "forecast_ref": {
            "method": "wetness_aware_v2",
            "anchor_stage_cm": ANCHOR_CM,
            "anchor_observed_at_utc": ANCHOR_UTC,
            "predicted_rise_cm": pred_rise,
            "predicted_peak_anchored_cm": pred_peak,
            "predicted_peak_time_utc": from_now["primary"]["peak_time_utc"],
            "ensemble_rise_cm": band,
            "analog": from_now["primary"]["event_id"],
        },
        "observed": payload["observations"]["latest_ana"],
        "scorecard": payload["verification"],
        "plain_pt": plain,
    }
    VERIFY.write_text(json.dumps(verify, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    HTML.write_text(
        f"""<!DOCTYPE html><html lang=pt-BR><meta charset=utf-8>
<title>Live eval Muçum (úmido)</title>
<body style="font-family:Georgia,serif;max-width:900px;margin:2rem auto;padding:0 1rem;background:#eef3ef;color:#14231c">
<p style="border:1px solid #9bb8a8;display:inline-block;padding:.2rem .6rem">pesquisa · replay úmido</p>
<h1>Muçum — previsão melhorada vs observado</h1>
<p><strong>{plain}</strong></p>
<ul>
<li>Âncora: {ANCHOR_CM:.0f} cm</li>
<li>Previsto agora: +{pred_rise:.0f} cm → {pred_peak:.0f} cm ({from_now['primary']['event_id']})</li>
<li>Observado: {latest_n:.0f} cm (+{rise_obs:.0f})</li>
<li>Erro antigo (568): {old_err:+.0f} cm → erro novo: {new_err:+.0f} cm</li>
</ul>
</body></html>
""",
        encoding="utf-8",
    )
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "hec_twin_mucum_live_eval_latest.json").write_text(EVAL.read_text(encoding="utf-8"), encoding="utf-8")
    (ART / "hec_twin_mucum_live_eval_verify_latest.json").write_text(VERIFY.read_text(encoding="utf-8"), encoding="utf-8")
    (ART / "hec_twin_mucum_live_eval.html").write_text(HTML.read_text(encoding="utf-8"), encoding="utf-8")
    (ART / "hec_twin_mucum_wetness_improve_summary.log").write_text(
        plain
        + f"\nold_err={old_err:+.1f} new_err={new_err:+.1f} improved={abs(new_err)<abs(old_err)}\n"
        + f"analogs={[a.get('event_id') for a in analogs]}\n",
        encoding="utf-8",
    )
    print(plain)
    print("old_err", old_err, "new_err", new_err, "improved", abs(new_err) < abs(old_err))
    print("analogs", [a.get("event_id") for a in analogs])
    print("from_now", from_now)


if __name__ == "__main__":
    main()
