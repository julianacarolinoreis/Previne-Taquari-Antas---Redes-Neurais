#!/usr/bin/env python3
"""Run conservative Muçum rainfall stress test and restore baseline outputs."""
from __future__ import annotations
import json, os, shutil, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
OP=OUT/"hec_hms_operational_forecast_latest.json"
GEN=OUT/"hec_hms_spatial_forecast_mucum_latest.json"
DEST=OUT/"hec_hms_operational_forecast_conservative_latest.json"
SERIES=OUT/"hec_hms_spatial_forecast_mucum"/"primary_series.csv"
DEST_SERIES=OUT/"hec_hms_operational_forecast_conservative_series.csv"

def run(hec, env):
    subprocess.run([sys.executable,"-B","scripts/run_hec_hms_operational_latest.py",hec],cwd=ROOT,env=env,check=True)

def main():
    if len(sys.argv)<2: raise SystemExit("usage: run_hec_hms_operational_conservative.py /path/to/hec-hms.sh")
    hec=sys.argv[1]
    env=os.environ.copy()
    env["HEC_RAIN_SCENARIO"]="recent_accum_guard"
    env["HEC_CONSERVATIVE_HOURS"]="4"
    env["HEC_CONSERVATIVE_LOOKBACK_HOURS"]="6"
    run(hec,env)
    pkg=json.loads(OP.read_text(encoding="utf-8"))
    pkg["scenario_label"]="conservative_recent_accum_guard"
    pkg["scenario_note_pt"]="Cenário de estresse por acumulados: calcula janelas observadas de 3 h e 6 h, usa a maior taxa média como piso nas próximas 4 horas e ignora a hora corrente como chuva areal quando a cobertura de postos não é representativa."
    DEST.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if SERIES.exists(): shutil.copy2(SERIES,DEST_SERIES)

    # Restore official baseline products immediately after saving stress test.
    env2=os.environ.copy()
    env2.pop("HEC_RAIN_SCENARIO",None)
    env2.pop("HEC_CONSERVATIVE_HOURS",None)
    env2.pop("HEC_CONSERVATIVE_LOOKBACK_HOURS",None)
    run(hec,env2)
    print(json.dumps({"saved":str(DEST.relative_to(ROOT)),"baseline_restored":True},ensure_ascii=False))

if __name__=="__main__":
    main()
