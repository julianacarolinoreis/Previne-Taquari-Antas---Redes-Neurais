#!/usr/bin/env python3
"""Run the E28 HEC-HMS network with audited rainfall at each downstream station."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from build_hec_hms_network_station_distributed import (
    EVENTWISE_PARAMS,
    build_event,
    blocks,
    manager,
    run_event,
    set_gage,
)
from extract_hec_hms_network_all_events import extract_event, score


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "hec_hms_integrated_taquari_antas" / "network_replay_hybrid_e28"
HYBRID_DSS = ROOT / "assets" / "data" / "hec_hms_calibration" / "mucum_hybrid_e28_rain.dss"
RAIN_REPORT = ROOT / "assets" / "data" / "hec_hms_audit" / "derived" / "mucum_hybrid_e28_rain_dss_report.json"
REPORT = OUT / "hybrid_e28_metrics.json"
PARAMS = {
    "initial_loss": 2.5,
    "constant_loss": 2.0,
    "tc": 25.0,
    "storage": 25.0,
    "recession": 0.8,
    "initial_flow_ratio": 0.003,
    "k": 1.0,
}


def add_mucum_gage(gage_text: str) -> str:
    """Clone the audited Santa Tereza gage for the final Muçum increment."""
    gage_blocks = blocks(gage_text, "Gage: ")
    santa = next(block for block in gage_blocks if "Gage: Chuva_86472600_E28" in block)
    mucum = santa.replace("Chuva_86472600_E28", "Chuva_86510000_E28")
    mucum = mucum.replace("86472600", "86510000")
    mucum = re.sub(
        r"(?m)^\s*Description: .*?$",
        "     Description: Chuva ANA 86510000 para o incremento final de Muçum",
        mucum,
    )
    flow = next(block for block in gage_blocks if "Gage: Q_E28" in block)
    return gage_text.replace(flow, mucum.strip() + "\n\n" + flow, 1)


def main() -> int:
    if not HYBRID_DSS.exists():
        raise FileNotFoundError(HYBRID_DSS)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = build_event("E28", OUT, {"E28"}, "eventwise", params_override=PARAMS)
    event_dir = OUT / "E28"

    met_path = event_dir / "chuva_E28.met"
    met = set_gage(met_path.read_text(encoding="utf-8"), "SB_INC_MUCUM_E28", "Chuva_86510000_E28")
    met_path.write_text(met, encoding="utf-8")

    gage_path = event_dir / "taquari_antas_E28.gage"
    gage_path.write_text(add_mucum_gage(gage_path.read_text(encoding="utf-8")), encoding="utf-8")
    shutil.copy2(HYBRID_DSS, event_dir / "rain.dss")

    manifest.update(
        {
            "rainfall_policy": "86472000 no Antas a montante; 86472600 no incremento Santa Tereza; 86510000 no incremento final de Muçum",
            "station_distributed": True,
            "hybrid_station_distributed": True,
            "rainfall_source": str(HYBRID_DSS.relative_to(ROOT)),
            "gage_mapping": {
                "SB_ANTAS_E28": "Chuva_86472000_E28",
                "SB_INC_STZ_E28": "Chuva_86472600_E28",
                "SB_INC_MUCUM_E28": "Chuva_86510000_E28",
            },
            "status": "built; replay scored; not promoted; Santa Tereza flow target remains unavailable",
        }
    )
    (event_dir / "event_network_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run = run_event("E28", event_dir)
    pairs = extract_event("E28", event_dir) if run["ok_marker"] else []
    metrics = score("E28", pairs) if pairs else {"event_id": "E28", "status": "blocked_hec_compute"}
    rain_report = json.loads(RAIN_REPORT.read_text(encoding="utf-8")) if RAIN_REPORT.exists() else None
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "teste de replay HEC-HMS E28 com chuva ANA híbrida; não é calibração promovida nem operação",
        "network": "ANA BHO6 nested incremental areas 86472000 -> 86472600 -> 86510000",
        "rainfall_policy": manifest["rainfall_policy"],
        "gage_mapping": manifest["gage_mapping"],
        "parameters": PARAMS,
        "rainfall_input_audit": rain_report,
        "run": run,
        "metrics": metrics,
        "status": "replay_scored_not_promoted" if metrics.get("status") == "replay_scored_not_promoted" else "blocked",
        "artifacts": ["E28/event_network_manifest.json", "E28/network_pairs_scored.csv", "E28/rain.dss"],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "replay_scored_not_promoted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
