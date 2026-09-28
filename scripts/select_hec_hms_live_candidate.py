#!/usr/bin/env python3
"""Select the live HEC-HMS spatial candidate against the observed warm-up state.

The live workflow executes the four semidistributed HEC-HMS 4.13 parameter
sets that already exist in the repository (E19, E22, E27, E28). This selector
does not shift stage series and does not recalibrate on future observations.
It only ranks candidates by how well the observed-rain warm-up reaches the
current observed state at t0.

If at least one candidate passes the existing publication guards, selection is
restricted to those candidates. Otherwise the least-inconsistent candidate is
kept as diagnostic and the public result remains blocked.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas"
RUNTIME = OUT / "hec_hms_spatial_forecast_mucum"
CANDIDATES = RUNTIME / "live_candidates"
LATEST = OUT / "hec_hms_spatial_forecast_mucum_latest.json"
SELECTION = OUT / "hec_hms_spatial_forecast_mucum_selection_latest.json"
EVENTS = ("E19", "E22", "E27", "E28")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value, default=1e9):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def metrics(pkg: dict) -> dict:
    v = pkg.get("validation") or {}
    obs_trend = finite(v.get("observed_trend_last_1h_cm"))
    mod_trend = finite(v.get("model_trend_next_1h_cm"))
    stage = abs(finite(v.get("stage_error_at_t0_cm")))
    qerr = abs(finite(v.get("q_error_pct")))
    trend = abs(mod_trend - obs_trend)
    # Normalize by the operational consistency gates so the terms have
    # comparable scale. Lower is better.
    score = stage / 75.0 + qerr / 40.0 + trend / 50.0
    return {
        "publishable": bool(pkg.get("publishable")),
        "stage_abs_error_cm": round(stage, 3),
        "q_abs_error_pct": round(qerr, 3),
        "trend_abs_error_cm_h": round(trend, 3),
        "selection_score": round(score, 6),
        "observed_stage_cm": (pkg.get("summary") or {}).get("level_now_observed_cm"),
        "observed_at_utc": (pkg.get("summary") or {}).get("observed_at_utc"),
        "observed_trend_cm_h": v.get("observed_trend_last_1h_cm"),
        "model_trend_cm_h": v.get("model_trend_next_1h_cm"),
        "blocking_reasons_pt": list(v.get("blocking_reasons_pt") or []),
    }


def main():
    rows = []
    packages = {}
    for event in EVENTS:
        result = CANDIDATES / event / "result.json"
        if not result.exists():
            rows.append({
                "event": event,
                "available": False,
                "publishable": False,
                "selection_score": 1e9,
                "blocking_reasons_pt": ["resultado do candidato ausente"],
            })
            continue
        pkg = load(result)
        packages[event] = pkg
        row = {"event": event, "available": True, **metrics(pkg)}
        rows.append(row)

    available = [r for r in rows if r.get("available")]
    if not available:
        raise RuntimeError("no live HEC-HMS candidate result available")

    passed = [r for r in available if r.get("publishable")]
    pool = passed or available
    chosen = min(pool, key=lambda r: finite(r.get("selection_score")))
    event = chosen["event"]
    selected = packages[event]

    selected["selection"] = {
        "method": "observed_warmup_state_match_no_visual_anchor",
        "selected_event": event,
        "selected_from_publishable_pool": bool(passed),
        "candidate_count": len(available),
        "candidates": rows,
        "rule_pt": (
            "Executar os quatro conjuntos HEC-HMS 4.13 já validados em replay e "
            "selecionar pelo menor erro normalizado de nível, vazão e tendência no "
            "t0 observado. Se houver candidato que passa as guardas, candidatos "
            "bloqueados não podem ser escolhidos."
        ),
    }
    selected.setdefault("artifacts", {})
    selected["artifacts"].update({
        "selected_candidate_dir": str((CANDIDATES / event).relative_to(ROOT)),
        "input": str((CANDIDATES / event / "forecast_input.json").relative_to(ROOT)),
        "series_csv": str((CANDIDATES / event / "primary_series.csv").relative_to(ROOT)),
        "hec_output_csv": str((CANDIDATES / event / "hec_output_values.csv").relative_to(ROOT)),
        "selection_json": str(SELECTION.relative_to(ROOT)),
    })

    LATEST.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Keep the generic runtime mirrors consistent with the selected candidate.
    for name in ("forecast_input.json", "primary_series.csv", "hec_output_values.csv"):
        src = CANDIDATES / event / name
        if src.exists():
            shutil.copy2(src, RUNTIME / name)

    audit = {
        "schema_version": "hec_hms_live_candidate_selection_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "selected_event": event,
        "selected_publishable": bool(selected.get("publishable")),
        "selected_from_publishable_pool": bool(passed),
        "candidates": rows,
    }
    SELECTION.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
