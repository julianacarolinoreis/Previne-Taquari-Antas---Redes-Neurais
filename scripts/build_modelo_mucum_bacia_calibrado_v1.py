#!/usr/bin/env python3
"""Build Muçum basin-calibrated transfer package (regimes + fingerprints + LOO skill).

Does not retune RNA. Does not invent STZ rating curve.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hec_twin_mucum_bacia_calibracao as bacia  # noqa: E402
import run_hec_twin_mucum_forward_5d as fwd  # noqa: E402
import run_hec_twin_mucum_hindcast_skill_5d as hind  # noqa: E402
import run_hec_twin_stz_mucum_calibrate as cal  # noqa: E402

OUT = bacia.OUT
MODELO = bacia.MODELO
HEC = bacia.HEC
BACIA = bacia.BACIA


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def regime_specialists(
    fingerprints: dict[str, dict[str, Any]],
    scored_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pick best transferable donor seen in LOO per forecast regime."""
    by_regime: dict[str, list[dict[str, Any]]] = {"light": [], "moderate": [], "heavy": []}
    for row in scored_rows:
        if row.get("status") != "scored":
            continue
        eid = row["event_id"]
        fp = fingerprints.get(eid) or {}
        regime = fp.get("regime") or bacia.classify_regime(float(row.get("rain_mm_aw") or float("nan")))
        if regime not in by_regime:
            continue
        by_regime[regime].append(row)

    out: dict[str, Any] = {}
    for regime, rows in by_regime.items():
        if not rows:
            out[regime] = {"status": "empty"}
            continue
        # Prefer donors with lower rise_n_rel_err when used as target? Better: count which analog wins.
        analog_scores: dict[str, list[float]] = {}
        for r in rows:
            aid = r.get("analog_event_id")
            err = r.get("rise_n_rel_err")
            if aid is None or err is None:
                continue
            # Expand BLEND into its top-weight donor for specialist recommendation.
            if aid == "BLEND":
                weights = r.get("blend_weights") or []
                if weights:
                    aid = max(weights, key=lambda w: float(w.get("weight") or 0.0)).get("event_id") or aid
            analog_scores.setdefault(str(aid), []).append(float(err))
        ranked = sorted(
            (
                {
                    "event_id": aid,
                    "n_targets": len(errs),
                    "mean_rise_n_rel_err": round(sum(errs) / len(errs), 4),
                }
                for aid, errs in analog_scores.items()
            ),
            key=lambda d: (d["mean_rise_n_rel_err"], -d["n_targets"]),
        )
        out[regime] = {
            "n_loo_targets": len(rows),
            "recommended_donor_event_id": ranked[0]["event_id"] if ranked else None,
            "donor_ranking": ranked[:5],
            "mean_target_rise_n_rel_err": round(
                sum(float(r["rise_n_rel_err"]) for r in rows if r.get("rise_n_rel_err") is not None)
                / max(1, sum(1 for r in rows if r.get("rise_n_rel_err") is not None)),
                4,
            ),
        }
    return out


def main() -> None:
    modelo = json.loads(MODELO.read_text(encoding="utf-8"))
    hec = json.loads(HEC.read_text(encoding="utf-8"))
    library = list(modelo.get("params_library_eventwise") or [])
    hec_events = list((hec.get("models") or {}).get("mucum", {}).get("events") or [])
    hec_by_id = {e["event_id"]: e for e in hec_events}
    areas = fwd.load_areas()
    segments = fwd.mucum_curve_segments()

    fingerprints = bacia.build_event_fingerprints(
        hec_events, areas, prepare_event_forcing=cal.prepare_event_forcing
    )

    rows: list[dict[str, Any]] = []
    for row in library:
        eid = row["event_id"]
        print(f"LOO {eid} ...", flush=True)
        rows.append(
            hind.score_event(
                eid,
                library=library,
                hec_by_id=hec_by_id,
                hec_events=hec_events,
                areas=areas,
                segments=segments,
                fingerprints=fingerprints,
            )
        )
    summary = hind.summarize(rows)
    verdict = hind.build_verdict(summary)
    specialists = regime_specialists(fingerprints, rows)

    payload = {
        "schema_version": "modelo_mucum_bacia_calibrado_v1",
        "generated_at_utc": utc_now(),
        "status": "research_basin_calibrated_ready",
        "label_pt": (
            "Calibração de transferência do gêmeo HEC Muçum por regime de chuva (leve/moderado/pesado). "
            "Não é alerta. Não altera RNA. Não inventa curva STZ."
        ),
        "method": {
            "rain_fingerprint": "area_weighted_full_window_mm",
            "analog_distance": "aw_rain + loss/efficiency penalties + regime match",
            "light_specialists": list(bacia.LIGHT_SPECIALIST_EVENTS),
            "ic_scaling": "observed_q0_scales_initial_flow_ratio",
            "primary_rule": "median_rise_ensemble_member",
            "not": ["rna", "stz_n", "common_search_params", "official_alert"],
        },
        "regimes": {
            "light_max_mm": bacia.REGIME_LIGHT_MAX_MM,
            "heavy_min_mm": bacia.REGIME_HEAVY_MIN_MM,
        },
        "fingerprints": fingerprints,
        "loo_skill": {"summary": summary, "verdict": verdict, "events": rows},
        "regime_specialists": specialists,
        "core_library_event_ids": [r["event_id"] for r in library],
        "artifacts": {
            "json": BACIA.name,
            "hindcast_skill_json": "hec_twin_mucum_hindcast_skill_5d_latest.json",
        },
    }
    BACIA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # also refresh hindcast artifacts from same LOO
    hind_path = OUT / "hec_twin_mucum_hindcast_skill_5d_latest.json"
    html_path = OUT / "hec_twin_mucum_hindcast_skill_5d.html"
    hind_payload = {
        "schema_version": "hec_twin_mucum_hindcast_skill_5d_v1",
        "generated_at_utc": utc_now(),
        "status": "research_hindcast_skill_ready",
        "purpose": "Skill LOO do quanto sobe Muçum com calibração de bacia v1.",
        "method": payload["method"],
        "summary": summary,
        "verdict": verdict,
        "events": rows,
        "artifacts": {"json": hind_path.name, "html": html_path.name, "bacia": BACIA.name},
    }
    hind_path.write_text(json.dumps(hind_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(hind.render_html(hind_payload), encoding="utf-8")
    print(f"wrote {BACIA}")
    print(f"wrote {hind_path}")
    print(json.dumps({"summary": summary, "verdict": verdict, "regime_specialists": specialists}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
