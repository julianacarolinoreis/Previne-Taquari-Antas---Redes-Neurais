#!/usr/bin/env python3
"""Build source readiness for an independent G040 MGB model.

This does not fabricate HRUs or meteorological forcing. It marks exactly which
source classes are available and which remain blockers.

Research only.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STACK=ROOT/"assets/data/g040_hydro_stack"
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
SRC=STACK/"project_source_inventory_latest.json"
MET=STACK/"met_forcing_source_contract_latest.json"
OBS=BASE/"whole_basin_observed_rain_latest.json"
EVENTS=BASE/"whole_basin_historical_hydro_events_latest.json"
OUT=STACK/"mgb_input_readiness_latest.json"

def load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def main():
    src=load(SRC)
    met=load(MET)
    sources={x.get("id"):x for x in src.get("sources") or []}
    obs=load(OBS)
    events=load(EVENTS)

    gates={
        "dem_candidate_available":bool(sources.get("mde_tc_legacy")),
        "hydrologically_consistent_dem_selected":False,
        "soil_candidate_available":bool(sources.get("soil_ibge_2023") or sources.get("soil_embrapa_2011")),
        "land_cover_candidate_available":bool(sources.get("mapbiomas_crosswalk")),
        "current_precipitation_available":str(obs.get("status","")).startswith("OBSERVED_RAIN_READY"),
        "historical_discharge_events_available":len(events.get("events") or [])>=6,
        "historical_met_source_selected":bool((met.get("historical_hindcast") or {}).get("preferred_source")),
        "temperature_forcing_ready":False,
        "relative_humidity_forcing_ready":False,
        "wind_forcing_ready":False,
        "solar_or_sunshine_forcing_ready":False,
        "pressure_or_supported_equivalent_ready":False,
        "pet_or_energy_balance_strategy_selected":False,
        "mini_basins_generated":False,
        "hru_fractions_generated":False,
    }
    blockers=[k for k,v in gates.items() if not v]
    prep_can_start=all(gates[k] for k in [
        "dem_candidate_available","soil_candidate_available",
        "land_cover_candidate_available","current_precipitation_available",
        "historical_discharge_events_available",
    ])
    payload={
        "schema_version":"g040_mgb_input_readiness_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"MGB_PREPROCESSING_CAN_START_MET_FORCING_INCOMPLETE" if prep_can_start else "MGB_SOURCE_PREPARATION_INCOMPLETE",
        "gates":gates,
        "blockers":blockers,
        "source_notes":{
            "dem":"project legacy terrain/Tc evidence exists, but a hydrologically consistent DEM for MGB must be explicitly selected/generated",
            "soil":"IBGE 2023 1:250k is a primary candidate; Embrapa 2011 is an independent but coarse reference",
            "land_cover":"MapBiomas exists; the alternate ~166-unit workbook must not be treated as the MGB or HEC145 discretization",
            "precipitation":"current G040 observed field can support contemporary replay once stable; historical forcing still needs event-period source audit",
            "historical_meteorology":(met.get("historical_hindcast") or {}),
            "near_real_time_station_candidates":(met.get("near_real_time_observation_candidates") or {}),
            "discharge":"six historical/live benchmark events exist, but station-specific QC remains mandatory",
        },
        "preprocessing_plan":[
            "select/condition DEM and derive drainage/mini-basins independently",
            "spatialize soil and land-cover to MGB HRUs",
            "close continuous meteorological forcing variables/units/timezone",
            "generate initial parameter file with source provenance",
            "run continuous warmup",
            "calibrate on fixed calibration events and checkpoints",
            "freeze before independent validation/holdout",
        ],
        "discretization_rule":"derive MGB mini-basins/HRUs independently; never copy the 32 management polygons or 145 HEC inventory by assumption",
        "promotion_allowed":False,
    }
    STACK.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"blockers":blockers},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
