#!/usr/bin/env python3
"""Verify/tune the reconstructed 2026-09-21 Muçum HEC hydrograph experiment.

The selection rule is deliberately causal:
1. use the observed-rain pre-roll forcing;
2. match ANA Muçum levels to the model hourly grid;
3. reserve the LAST N matched observations as untouched holdout;
4. tune only rainfall-loss and response-time factors on the earlier observations;
5. select the candidate without looking at holdout errors;
6. evaluate the selected candidate on holdout afterwards.

No live parameter file is modified. No candidate is promoted automatically.
Research only — not an official alert product.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hec_twin_nested_v17 import NestedParams, ZoneParams  # noqa: E402
from run_hec_twin_stz_mucum_calibrate import run_network  # noqa: E402
import run_hec_twin_mucum_forward_5d as fwd  # noqa: E402

OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
FORCING_DEFAULT = OUT / "hec_twin_ifs_forcing_preroll_research_20260921.json"
MODEL_DEFAULT = OUT / "modelo_mucum_eventwise_v1_fechado_latest.json"
OUTPUT_DEFAULT = OUT / "hec_current_wave_fit_research_20260921.json"

ANA_URLS = (fwd.ANA_URL, fwd.ANA_MIRROR)
BRT = timezone(timedelta(hours=-3))
USER_AGENT = "PREVINE-hec-wave-fit-research/1.0"

LOSS_FACTORS = (0.65, 0.80, 1.00, 1.20, 1.40)
TC_FACTORS = (0.75, 0.90, 1.00, 1.15, 1.30)
STORAGE_FACTORS = (0.80, 1.00, 1.20)


def parse_utc(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_observed_levels(start_utc: datetime, end_utc: datetime) -> list[tuple[datetime, float]]:
    start_local = start_utc.astimezone(BRT)
    end_local = end_utc.astimezone(BRT)
    query = urllib.parse.urlencode(
        {
            "codEstacao": fwd.MUCUM_CODE,
            "dataInicio": start_local.strftime("%d/%m/%Y"),
            "dataFim": end_local.strftime("%d/%m/%Y"),
        }
    )
    errors = []
    for base in ANA_URLS:
        try:
            req = urllib.request.Request(f"{base}?{query}", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=70) as resp:
                rows = fwd._parse_ana_levels(resp.read())
            rows = [(t, v) for t, v in rows if start_utc - timedelta(hours=1) <= t <= end_utc + timedelta(hours=1)]
            if rows:
                return rows
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    raise RuntimeError("unable to fetch ANA Muçum levels: " + " | ".join(errors))


def match_observations(
    model_times: list[str],
    observations: list[tuple[datetime, float]],
    *,
    end_index: int,
    tolerance_minutes: float,
) -> list[dict[str, Any]]:
    used: set[datetime] = set()
    out: list[dict[str, Any]] = []
    tol = tolerance_minutes * 60.0
    for i, raw in enumerate(model_times[:end_index]):
        target = parse_utc(raw)
        candidates = [
            (abs((obs_t - target).total_seconds()), obs_t, value)
            for obs_t, value in observations
            if obs_t not in used
        ]
        if not candidates:
            continue
        delta_s, obs_t, value = min(candidates, key=lambda x: x[0])
        if delta_s > tol:
            continue
        used.add(obs_t)
        out.append(
            {
                "model_index": i,
                "model_time_utc": target.isoformat().replace("+00:00", "Z"),
                "observed_time_utc": obs_t.isoformat().replace("+00:00", "Z"),
                "offset_minutes": round((obs_t - target).total_seconds() / 60.0, 1),
                "observed_cm": float(value),
            }
        )
    return out


def adjusted_params(base: NestedParams, loss_factor: float, tc_factor: float, storage_factor: float) -> NestedParams:
    def zone(z: ZoneParams) -> ZoneParams:
        return ZoneParams(
            initial_loss=max(0.0, z.initial_loss * loss_factor),
            constant_loss=max(0.0, z.constant_loss * loss_factor),
            tc=max(0.25, z.tc * tc_factor),
            storage=max(0.25, z.storage * storage_factor),
            recession=z.recession,
            initial_flow_ratio=z.initial_flow_ratio,
        )

    return NestedParams(
        up=zone(base.up),
        dn=zone(base.dn),
        k1=base.k1,
        k2=base.k2,
        k3=base.k3,
        x=base.x,
    )


def metrics(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    if not rows:
        return {
            "n": 0,
            "mae_cm": None,
            "rmse_cm": None,
            "bias_cm": None,
            "nse": None,
            "peak_abs_error_cm": None,
            "peak_lag_hours": None,
        }
    obs = [float(r["observed_cm"]) for r in rows]
    sim = [float(r["simulated_cm"]) for r in rows]
    err = [s - o for s, o in zip(sim, obs)]
    n = len(rows)
    mae = sum(abs(e) for e in err) / n
    rmse = math.sqrt(sum(e * e for e in err) / n)
    bias = sum(err) / n
    mean_obs = sum(obs) / n
    den = sum((o - mean_obs) ** 2 for o in obs)
    nse = None if den <= 0 else 1.0 - sum((s - o) ** 2 for s, o in zip(sim, obs)) / den
    obs_peak_i = max(range(n), key=lambda i: obs[i])
    sim_peak_i = max(range(n), key=lambda i: sim[i])
    peak_abs = abs(sim[sim_peak_i] - obs[obs_peak_i])
    lag_h = (
        parse_utc(rows[sim_peak_i]["model_time_utc"])
        - parse_utc(rows[obs_peak_i]["model_time_utc"])
    ).total_seconds() / 3600.0
    return {
        "n": n,
        "mae_cm": round(mae, 4),
        "rmse_cm": round(rmse, 4),
        "bias_cm": round(bias, 4),
        "nse": None if nse is None else round(nse, 6),
        "peak_abs_error_cm": round(peak_abs, 4),
        "peak_lag_hours": round(lag_h, 3),
    }


def objective(m: dict[str, float | None]) -> float:
    if not m.get("n") or m.get("rmse_cm") is None:
        return float("inf")
    lag = abs(float(m.get("peak_lag_hours") or 0.0))
    return (
        float(m["rmse_cm"])
        + 0.20 * float(m["mae_cm"] or 0.0)
        + 0.25 * float(m["peak_abs_error_cm"] or 0.0)
        + 2.0 * lag
    )


def rows_with_sim(matched: list[dict[str, Any]], stage_series: list[float | None]) -> list[dict[str, Any]]:
    out = []
    for row in matched:
        idx = int(row["model_index"])
        sim = stage_series[idx] if 0 <= idx < len(stage_series) else None
        if sim is None or not math.isfinite(float(sim)):
            continue
        obs = float(row["observed_cm"])
        error = float(sim) - obs
        out.append(
            {
                **row,
                "simulated_cm": round(float(sim), 3),
                "error_cm": round(error, 3),
                "abs_error_cm": round(abs(error), 3),
                "abs_percent_difference": round(100.0 * abs(error) / obs, 5) if obs else None,
            }
        )
    return out


def run_candidate(
    base_row: dict[str, Any],
    forcing: dict[str, Any],
    matched: list[dict[str, Any]],
    *,
    loss_factor: float,
    tc_factor: float,
    storage_factor: float,
) -> dict[str, Any] | None:
    areas = fwd.load_areas()
    precip = forcing["precip_mm_by_subbasin"]
    segments = fwd.mucum_curve_segments()

    params = adjusted_params(
        fwd.params_from_library_row(base_row),
        loss_factor,
        tc_factor,
        storage_factor,
    )

    first = matched[0]
    first_q = fwd.stage_to_q_m3s(float(first["observed_cm"]), segments)
    if not first_q.get("ok"):
        return None

    params_scaled, ic_meta = fwd.scale_params_to_observed_q0(
        params,
        precip,
        areas,
        float(first_q["q_m3s"]),
        q0_index=int(first["model_index"]),
    )
    net = run_network(precip, areas, params_scaled, include_mucum_increment=True)
    stages = [fwd.q_to_stage_cm(float(q), segments).get("stage_cm") for q in net["at_mucum"]]
    all_rows = rows_with_sim(matched, stages)
    if len(all_rows) != len(matched):
        return None

    return {
        "event_id": base_row["event_id"],
        "factors": {
            "loss": loss_factor,
            "tc": tc_factor,
            "storage": storage_factor,
        },
        "params_scaled": params_scaled.to_dict(),
        "initial_condition": ic_meta,
        "rows": all_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forcing", type=Path, default=FORCING_DEFAULT)
    parser.add_argument("--model", type=Path, default=MODEL_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--holdout-hours", type=int, default=6)
    parser.add_argument("--tolerance-minutes", type=float, default=40.0)
    parser.add_argument(
        "--max-base-events",
        type=int,
        default=0,
        help="0 = all eventwise library rows; positive value limits for quick diagnostics.",
    )
    args = parser.parse_args()

    forcing = json.loads(args.forcing.read_text(encoding="utf-8"))
    model = json.loads(args.model.read_text(encoding="utf-8"))
    library = list(model.get("params_library_eventwise") or [])
    if args.max_base_events > 0:
        library = library[: args.max_base_events]
    if not library:
        raise RuntimeError("eventwise parameter library is empty")

    times = list(forcing.get("times_utc") or [])
    now_index = fwd.resolve_now_index(forcing, times)
    if now_index < 1:
        raise RuntimeError("forcing has no observed pre-roll (now_index < 1)")

    observations = fetch_observed_levels(parse_utc(times[0]), parse_utc(times[now_index]))
    matched = match_observations(
        times,
        observations,
        end_index=now_index + 1,
        tolerance_minutes=args.tolerance_minutes,
    )
    holdout_n = max(1, int(args.holdout_hours))
    if len(matched) < holdout_n + 6:
        raise RuntimeError(
            f"only {len(matched)} matched observations; need at least {holdout_n + 6} "
            "to keep a real training window plus holdout"
        )

    train_match = matched[:-holdout_n]
    holdout_match = matched[-holdout_n:]
    first_train = train_match[0]

    candidates = []
    for row in library:
        for lf in LOSS_FACTORS:
            for tf in TC_FACTORS:
                for sf in STORAGE_FACTORS:
                    result = run_candidate(
                        row,
                        forcing,
                        train_match,
                        loss_factor=lf,
                        tc_factor=tf,
                        storage_factor=sf,
                    )
                    if result is None:
                        continue
                    m = metrics(result["rows"])
                    candidates.append(
                        {
                            "event_id": result["event_id"],
                            "factors": result["factors"],
                            "train_metrics": m,
                            "train_objective": round(objective(m), 6),
                            "params_scaled": result["params_scaled"],
                            "initial_condition": result["initial_condition"],
                        }
                    )

    if not candidates:
        raise RuntimeError("no candidate produced a complete training comparison")
    candidates.sort(key=lambda x: x["train_objective"])
    best_train = candidates[0]

    # Re-run the selected parameter family on train+holdout. The holdout was not
    # read by the selection loop above.
    base_row = next(r for r in library if r["event_id"] == best_train["event_id"])
    selected = run_candidate(
        base_row,
        forcing,
        matched,
        loss_factor=float(best_train["factors"]["loss"]),
        tc_factor=float(best_train["factors"]["tc"]),
        storage_factor=float(best_train["factors"]["storage"]),
    )
    if selected is None:
        raise RuntimeError("selected candidate failed during final evaluation")
    selected_rows = selected["rows"]
    train_rows = selected_rows[:-holdout_n]
    holdout_rows = selected_rows[-holdout_n:]

    payload = {
        "schema_version": "hec_current_wave_fit_research_20260921_v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "candidate_research_only_holdout_evaluated",
        "purpose": (
            "Reconstruir a busca interrompida: perdas de chuva + tempos de resposta "
            "ajustados na subida observada, com as últimas horas reservadas para teste."
        ),
        "selection_discipline": {
            "holdout_hours": holdout_n,
            "holdout_used_in_selection": False,
            "selection_uses": "training timestamps only",
            "tuned": [
                "initial_loss factor",
                "constant_loss factor",
                "Clark tc factor",
                "Clark storage factor",
            ],
            "not_tuned": [
                "recession",
                "Muskingum k1/k2/k3/x",
                "rating curve",
                "observed data",
            ],
            "initial_state_anchor": {
                "model_time_utc": first_train["model_time_utc"],
                "observed_time_utc": first_train["observed_time_utc"],
                "observed_cm": first_train["observed_cm"],
                "rule": "only first training observation is used to scale initial flow state",
            },
            "no_auto_promotion": True,
            "research_only": True,
            "not_official_alert": True,
        },
        "forcing": {
            "path": str(args.forcing.relative_to(ROOT)) if args.forcing.is_relative_to(ROOT) else str(args.forcing),
            "schema_version": forcing.get("schema_version"),
            "window": forcing.get("window"),
            "area_weighted_mean_mm": forcing.get("area_weighted_mean_mm"),
            "coverage": forcing.get("observed_preroll_coverage"),
        },
        "observations": {
            "station": fwd.MUCUM_CODE,
            "matched_total": len(matched),
            "train_n": len(train_rows),
            "holdout_n": len(holdout_rows),
            "matching_tolerance_minutes": args.tolerance_minutes,
            "note": "ANA observations are matched to the nearest model hour; exact timestamp offsets are retained.",
        },
        "search": {
            "base_events": [r["event_id"] for r in library],
            "loss_factors": list(LOSS_FACTORS),
            "tc_factors": list(TC_FACTORS),
            "storage_factors": list(STORAGE_FACTORS),
            "candidates_evaluated": len(candidates),
            "objective": "RMSE + 0.20*MAE + 0.25*peak_abs_error + 2*|peak_lag_h|; training only",
            "top_training_candidates": candidates[:20],
        },
        "selected": {
            "event_id": selected["event_id"],
            "factors": selected["factors"],
            "params_scaled": selected["params_scaled"],
            "initial_condition": selected["initial_condition"],
            "train_metrics": metrics(train_rows),
            "holdout_metrics": metrics(holdout_rows),
            "train_rows": train_rows,
            "holdout_rows": holdout_rows,
        },
        "interpretation": (
            "This result is a current-wave research candidate. It may be compared with the "
            "existing eventwise/analog pipeline, but it must not replace live parameters unless "
            "the independent holdout and later events remain acceptable."
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hm = payload["selected"]["holdout_metrics"]
    tm = payload["selected"]["train_metrics"]
    print(f"wrote {args.output}")
    print(
        f"selected={payload['selected']['event_id']} factors={payload['selected']['factors']} "
        f"train_rmse={tm['rmse_cm']} cm holdout_rmse={hm['rmse_cm']} cm "
        f"holdout_mae={hm['mae_cm']} cm"
    )


if __name__ == "__main__":
    main()
