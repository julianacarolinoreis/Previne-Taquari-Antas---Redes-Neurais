#!/usr/bin/env python3
"""Diagnostic parameter search for E28 with audited hybrid rainfall."""

from __future__ import annotations

import csv
import json
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_hec_hms_network_station_distributed import build_event, run_event, set_gage  # noqa: E402
from build_hec_hms_hybrid_e28 import add_mucum_gage  # noqa: E402
from extract_hec_hms_network_all_events import extract_event, score  # noqa: E402
from search_hec_hms_station_e28 import candidates  # noqa: E402


DEFAULT_OUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_hybrid_e28_calibration_search"
HYBRID_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_hybrid_e28_rain.dss"


def build_hybrid_candidate(candidate_dir: Path, params: dict[str, float]) -> None:
    build_event("E28", candidate_dir, {"E28"}, "eventwise", params_override=params)
    event_dir = candidate_dir / "E28"
    met_path = event_dir / "chuva_E28.met"
    met = set_gage(met_path.read_text(encoding="utf-8"), "SB_INC_MUCUM_E28", "Chuva_86510000_E28")
    met_path.write_text(met, encoding="utf-8")
    gage_path = event_dir / "taquari_antas_E28.gage"
    gage_path.write_text(add_mucum_gage(gage_path.read_text(encoding="utf-8")), encoding="utf-8")
    shutil.copy2(HYBRID_DSS, event_dir / "rain.dss")
    manifest_path = event_dir / "event_network_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "rainfall_policy": "86472000 no Antas a montante; 86472600 no incremento Santa Tereza; 86510000 no incremento final de Muçum",
            "hybrid_station_distributed": True,
            "rainfall_source": str(HYBRID_DSS.relative_to(ROOT)),
            "gage_mapping": {
                "SB_ANTAS_E28": "Chuva_86472000_E28",
                "SB_INC_STZ_E28": "Chuva_86472600_E28",
                "SB_INC_MUCUM_E28": "Chuva_86510000_E28",
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not HYBRID_DSS.exists():
        raise FileNotFoundError(HYBRID_DSS)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pool = candidates()[: args.limit or None]
    rows: list[dict] = []
    for index, params in enumerate(pool, start=1):
        candidate_dir = out / f"candidate_{index:03d}"
        build_hybrid_candidate(candidate_dir, params)
        run = run_event("E28", candidate_dir / "E28")
        if run["ok_marker"]:
            metric = score("E28", extract_event("E28", candidate_dir / "E28"))
            row = {"candidate_id": index, **params, **metric}
            row["research_score"] = metric["nse"] - 0.02 * abs(metric["peak_lag_hours"]) - 0.2 * metric["peak_relative_error"]
        else:
            row = {"candidate_id": index, **params, "status": "failed", "returncode": run["returncode"]}
        rows.append(row)
        print(f"candidate {index}/{len(pool)} complete")
    good = [row for row in rows if row.get("status") == "replay_scored_not_promoted"]
    good.sort(key=lambda row: row["research_score"], reverse=True)
    fields = sorted({key for row in rows for key in row})
    with (out / "hybrid_e28_search.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(good)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "busca diagnóstica de parâmetros no E28 com chuva ANA híbrida; não é calibração promovida",
        "rainfall_policy": "86472000 no alto Antas; 86472600 no incremento Santa Teresa; 86510000 no incremento final de Muçum",
        "candidate_count": len(pool),
        "successful_candidates": len(good),
        "best_by_research_score": good[0] if good else None,
        "artifacts": ["hybrid_e28_search.csv"],
    }
    (out / "hybrid_e28_search_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
