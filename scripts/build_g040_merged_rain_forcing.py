#!/usr/bin/env python3
"""Merge observed and ECMWF/IFS interval rainfall into one G040 forcing package.

Rules
-----
- observed rainfall is used only for hours strictly before the IFS start hour;
- IFS rainfall is used from the IFS start hour onward;
- no temporal overlap is averaged;
- missing observed hours remain missing and are not replaced by zero;
- the source of every hour is explicit.

Research only.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
OBS=BASE/"whole_basin_observed_rain_latest.json"
FCST=BASE/"whole_basin_ifs_forecast_latest.json"
OUT=BASE/"whole_basin_rain_forcing_latest.json"
OUTCSV=BASE/"whole_basin_rain_forcing_hourly.csv"
OUTCOMP=BASE/"whole_basin_rain_forcing_components_hourly.csv"
OBS_GRID=BASE/"whole_basin_observed_rain_fullgrid_hourly.csv"
FCST_GRID=BASE/"whole_basin_ifs_fullgrid_hourly.csv"
OUTGRID=BASE/"whole_basin_rain_forcing_fullgrid_hourly.csv"
BRT=timezone(timedelta(hours=-3))

def loadj(p: Path) -> dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def parse_utc(s: str) -> datetime:
    d=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def parse_local(s: str) -> datetime:
    d=datetime.fromisoformat(str(s))
    if d.tzinfo is None:
        d=d.replace(tzinfo=BRT)
    return d.astimezone(timezone.utc)

def merge_full_grid(forecast_start: datetime) -> dict[str,Any]:
    if not OBS_GRID.exists() or not FCST_GRID.exists():
        raise RuntimeError("observed/forecast full-grid CSV artifacts are required")
    with OBS_GRID.open(encoding="utf-8",newline="") as fh:
        ro=csv.DictReader(fh)
        obs_fields=list(ro.fieldnames or [])
        obs_cells=[x for x in obs_fields if x not in {"time_local","valid_station_count"}]
        obs_rows=[]
        for row in ro:
            t=parse_local(row["time_local"])
            if t < forecast_start:
                obs_rows.append({
                    "time_utc":t.isoformat().replace("+00:00","Z"),
                    "phase":"observed",
                    "valid_station_count":row.get("valid_station_count"),
                    **{cid:row.get(cid,"") for cid in obs_cells},
                })
    with FCST_GRID.open(encoding="utf-8",newline="") as fh:
        rf=csv.DictReader(fh)
        fc_fields=list(rf.fieldnames or [])
        fc_cells=[x for x in fc_fields if x!="time_utc"]
        fc_rows=[]
        for row in rf:
            t=parse_utc(row["time_utc"])
            if t >= forecast_start:
                fc_rows.append({
                    "time_utc":t.isoformat().replace("+00:00","Z"),
                    "phase":"ecmwf_ifs_fullgrid_0p1_sampling",
                    "valid_station_count":"",
                    **{cid:row.get(cid,"") for cid in fc_cells},
                })
    if obs_cells!=fc_cells:
        raise RuntimeError(
            f"observed/forecast full-grid cell headers differ: {len(obs_cells)} vs {len(fc_cells)}"
        )
    if len(obs_cells)!=600:
        raise RuntimeError(f"expected 600 full-grid cells, found {len(obs_cells)}")
    rows=obs_rows+fc_rows
    rows.sort(key=lambda x:parse_utc(x["time_utc"]))
    with OUTGRID.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_utc","phase","valid_station_count",*obs_cells]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k:row.get(k,"") for k in fields})
    forecast_complete=all(
        all(str(row.get(cid,"")).strip()!="" for cid in obs_cells)
        for row in fc_rows
    )
    return {
        "cell_count":len(obs_cells),
        "observed_rows":len(obs_rows),
        "forecast_rows":len(fc_rows),
        "forecast_all_cells_complete":forecast_complete,
        "output":str(OUTGRID.relative_to(ROOT)),
    }

def main() -> int:
    obs=loadj(OBS); fc=loadj(FCST)
    if obs.get("status") not in {"OBSERVED_RAIN_READY","OBSERVED_RAIN_PARTIAL"}:
        raise RuntimeError(f"observed forcing not usable: {obs.get('status')}")
    if fc.get("status") not in {"IFS_FULLGRID_FORCING_READY","IFS_FULLGRID_FORCING_READY_CYCLE_ID_UNVERIFIED"}:
        raise RuntimeError(f"IFS full-grid forcing not ready: {fc.get('status')}")

    og=obs.get("grid") or {}
    fg=fc.get("grid") or {}
    for key in ("resolution_deg","rows_latitude","cols_longitude","cells","edge_bounds","crs"):
        if og.get(key)!=fg.get(key):
            raise RuntimeError(
                f"observed/forecast grid contract mismatch for {key}: {og.get(key)} != {fg.get(key)}"
            )

    obs_scenario=(obs.get("boundary_scenario") or {}).get("name")
    fc_scenario=(fc.get("boundary_scenario") or {}).get("name")
    obs_active=sorted(str(x) for x in (obs.get("boundary_scenario") or {}).get("active_boundary_codes") or [])
    fc_active=sorted(str(x) for x in (fc.get("boundary_scenario") or {}).get("active_boundary_codes") or [])
    if obs_scenario!=fc_scenario or obs_active!=fc_active:
        raise RuntimeError(
            f"observed/IFS boundary scenario mismatch: {obs_scenario}/{obs_active} vs {fc_scenario}/{fc_active}"
        )
    forecast_start=parse_utc(fc["window"]["start_utc"])
    full_grid_merge=merge_full_grid(forecast_start)
    obs_by={x["interval_id"]:x for x in obs.get("intervals") or []}
    fc_by={x["interval_id"]:x for x in fc.get("intervals") or []}
    ids=sorted(set(obs_by)&set(fc_by))
    if len(ids)!=8:
        raise RuntimeError(f"expected 8 common intervals, found {len(ids)}")

    combined={}
    continuity=[]
    all_times=set()

    for iid in ids:
        oseries=[]
        for r in obs_by[iid].get("series") or []:
            t=parse_local(r["time_local"])
            if t < forecast_start:
                oseries.append({
                    "time_utc":t.isoformat().replace("+00:00","Z"),
                    "mm":r.get("mm"),
                    "source":"observed",
                    "valid_station_count":r.get("valid_station_count"),
                })
        fseries=[
            {
                "time_utc":r["time_utc"],
                "mm":r.get("mm"),
                "source":"ecmwf_ifs_fullgrid_0p1_sampling",
                "valid_station_count":None,
            }
            for r in fc_by[iid].get("series") or []
            if parse_utc(r["time_utc"]) >= forecast_start
        ]
        rows=oseries+fseries
        rows.sort(key=lambda x:parse_utc(x["time_utc"]))
        combined[iid]=rows
        all_times.update(x["time_utc"] for x in rows)

        last_obs=next((x for x in reversed(oseries) if x.get("mm") is not None),None)
        first_fc=next((x for x in fseries if x.get("mm") is not None),None)
        continuity.append({
            "interval_id":iid,
            "last_observed_time_utc":None if not last_obs else last_obs["time_utc"],
            "last_observed_mm":None if not last_obs else last_obs["mm"],
            "first_forecast_time_utc":None if not first_fc else first_fc["time_utc"],
            "first_forecast_mm":None if not first_fc else first_fc["mm"],
            "hourly_depth_jump_mm":None if not last_obs or not first_fc else round(float(first_fc["mm"])-float(last_obs["mm"]),4),
            "note":"diagnostic only; consecutive hourly precipitation depths are not expected to be equal",
        })

    obs_comp={x["component_id"]:x for x in obs.get("components") or []}
    fc_comp={x["component_id"]:x for x in fc.get("components") or []}
    component_ids=sorted(set(obs_comp)&set(fc_comp))
    if len(component_ids)!=11:
        raise RuntimeError(f"expected 11 common hydrologic rainfall components, found {len(component_ids)}")
    combined_components={}
    component_payload=[]
    component_continuity=[]
    for cid in component_ids:
        oseries=[]
        for rr in obs_comp[cid].get("series") or []:
            tt=parse_local(rr["time_local"])
            if tt < forecast_start:
                oseries.append({
                    "time_utc":tt.isoformat().replace("+00:00","Z"),
                    "mm":rr.get("mm"),"source":"observed",
                    "valid_station_count":rr.get("valid_station_count"),
                })
        fseries=[{
            "time_utc":rr["time_utc"],"mm":rr.get("mm"),
            "source":"ecmwf_ifs_fullgrid_0p1_sampling","valid_station_count":None,
        } for rr in fc_comp[cid].get("series") or [] if parse_utc(rr["time_utc"])>=forecast_start]
        rows=oseries+fseries
        rows.sort(key=lambda x:parse_utc(x["time_utc"]))
        combined_components[cid]=rows
        last_obs=next((x for x in reversed(oseries) if x.get("mm") is not None),None)
        first_fc=next((x for x in fseries if x.get("mm") is not None),None)
        component_continuity.append({
            "component_id":cid,
            "last_observed_time_utc":None if not last_obs else last_obs["time_utc"],
            "last_observed_mm":None if not last_obs else last_obs["mm"],
            "first_forecast_time_utc":None if not first_fc else first_fc["time_utc"],
            "first_forecast_mm":None if not first_fc else first_fc["mm"],
        })
        component_payload.append({
            "component_id":cid,
            "component_type":obs_comp[cid].get("component_type"),
            "tributary_boundary_code":obs_comp[cid].get("tributary_boundary_code"),
            "used_as_rainfall_runoff_in_current_scenario":bool(obs_comp[cid].get("used_as_rainfall_runoff_in_current_scenario")),
            "support_area_km2":obs_comp[cid].get("support_area_km2"),
            "observed_hours":len(oseries),
            "observed_available_hours":sum(x.get("mm") is not None for x in oseries),
            "forecast_hours":len(fseries),
            "forecast_available_hours":sum(x.get("mm") is not None for x in fseries),
            "series":rows,
        })

    times=sorted(all_times,key=parse_utc)
    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_utc","phase",*ids]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        maps={iid:{r["time_utc"]:r for r in rows} for iid,rows in combined.items()}
        for t in times:
            phases={maps[iid].get(t,{}).get("source") for iid in ids if t in maps[iid]}
            phase=next(iter(phases)) if len(phases)==1 else "mixed_or_missing"
            row={"time_utc":t,"phase":phase}
            for iid in ids:
                v=maps[iid].get(t,{}).get("mm")
                row[iid]="" if v is None else v
            w.writerow(row)

    with OUTCOMP.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_utc","phase",*component_ids]
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        maps={cid:{r["time_utc"]:r for r in rows} for cid,rows in combined_components.items()}
        component_times=sorted({t for m in maps.values() for t in m},key=parse_utc)
        for t in component_times:
            phases={maps[cid].get(t,{}).get("source") for cid in component_ids if t in maps[cid]}
            phase=next(iter(phases)) if len(phases)==1 else "mixed_or_missing"
            row={"time_utc":t,"phase":phase}
            for cid in component_ids:
                v=maps[cid].get(t,{}).get("mm")
                row[cid]="" if v is None else v
            w.writerow(row)

    interval_payload=[]
    for iid in ids:
        rows=combined[iid]
        obs_rows=[x for x in rows if x["source"]=="observed"]
        fc_rows=[x for x in rows if x["source"]=="ecmwf_ifs_fullgrid_0p1_sampling"]
        interval_payload.append({
            "interval_id":iid,
            "observed_hours":len(obs_rows),
            "observed_available_hours":sum(x.get("mm") is not None for x in obs_rows),
            "forecast_hours":len(fc_rows),
            "forecast_available_hours":sum(x.get("mm") is not None for x in fc_rows),
            "series":rows,
        })

    obs_complete_before_t0=all(
        x["observed_available_hours"]>=24 for x in interval_payload
    )
    forecast_complete=all(
        x["forecast_available_hours"]==x["forecast_hours"] and x["forecast_hours"]>=120
        for x in interval_payload
    )
    component_obs_complete=all(x["observed_available_hours"]>=24 for x in component_payload)
    component_forecast_complete=all(
        x["forecast_available_hours"]==x["forecast_hours"] and x["forecast_hours"]>=120
        for x in component_payload
    )
    exact_cycle=bool((fc.get("gates") or {}).get("exact_cycle_id_available"))
    base_ready=(
        obs_complete_before_t0 and forecast_complete
        and component_obs_complete and component_forecast_complete
        and full_grid_merge["forecast_all_cells_complete"]
    )
    if base_ready and exact_cycle:
        status="MERGED_RAIN_FORCING_READY"
    elif base_ready:
        status="MERGED_RAIN_FORCING_READY_RESEARCH_CYCLE_ID_UNVERIFIED"
    else:
        status="MERGED_RAIN_FORCING_REVIEW"

    payload={
        "schema_version":"g040_merged_interval_rain_forcing_v2",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":status,
        "boundary_scenario":{
            "name":obs_scenario,
            "active_boundary_codes":obs_active,
        },
        "transition":{
            "forecast_start_utc":forecast_start.isoformat().replace("+00:00","Z"),
            "rule":"observed 600-cell IDW^2 field strictly before forecast_start; ECMWF IFS 600-cell sampling field from forecast_start onward",
            "overlap_averaged":False,
            "missing_zero_filled":False,
        },
        "continuity_diagnostics":continuity,
        "component_continuity_diagnostics":component_continuity,
        "gates":{
            "all_intervals_present":len(ids)==8,
            "at_least_24_observed_hours_each":obs_complete_before_t0,
            "120h_forecast_complete_each":forecast_complete,
            "observed_forecast_scenario_match":True,
            "all_11_components_present":len(component_ids)==11,
            "at_least_24_observed_hours_each_component":component_obs_complete,
            "120h_forecast_complete_each_component":component_forecast_complete,
            "observed_forecast_grid_contract_identical":True,
            "merged_full_grid_cells":full_grid_merge["cell_count"],
            "merged_full_grid_forecast_complete":full_grid_merge["forecast_all_cells_complete"],
            "exact_ecmwf_cycle_id_available":exact_cycle,
            "operational_promotion_allowed":bool(base_ready and exact_cycle),
        },
        "grid_contract":{k:og.get(k) for k in ("resolution_deg","rows_latitude","cols_longitude","cells","edge_bounds","crs")},
        "full_grid_merge":full_grid_merge,
        "intervals":interval_payload,
        "components":component_payload,
        "artifacts":{
            "hourly_interval_csv":str(OUTCSV.relative_to(ROOT)),
            "hourly_component_csv":str(OUTCOMP.relative_to(ROOT)),
            "full_grid_hourly_csv":str(OUTGRID.relative_to(ROOT)),
        },
        "next_step":"translate the merged full-grid and component forcing into HEC-HMS branch-model inputs; retain research-only status until exact ECMWF cycle provenance is attached",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":status,
        "forecast_start_utc":payload["transition"]["forecast_start_utc"],
        "gates":payload["gates"],
        "intervals":len(ids),
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
