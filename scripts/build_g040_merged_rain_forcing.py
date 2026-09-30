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

def main() -> int:
    obs=loadj(OBS); fc=loadj(FCST)
    if obs.get("status") not in {"OBSERVED_RAIN_READY","OBSERVED_RAIN_PARTIAL"}:
        raise RuntimeError(f"observed forcing not usable: {obs.get('status')}")
    if fc.get("status")!="IFS_INTERVAL_FORCING_READY":
        raise RuntimeError(f"IFS forcing not ready: {fc.get('status')}")

    obs_scenario=(obs.get("boundary_scenario") or {}).get("name")
    fc_scenario=(fc.get("boundary_scenario") or {}).get("name")
    obs_active=sorted(str(x) for x in (obs.get("boundary_scenario") or {}).get("active_boundary_codes") or [])
    fc_active=sorted(str(x) for x in (fc.get("boundary_scenario") or {}).get("active_boundary_codes") or [])
    if obs_scenario!=fc_scenario or obs_active!=fc_active:
        raise RuntimeError(
            f"observed/IFS boundary scenario mismatch: {obs_scenario}/{obs_active} vs {fc_scenario}/{fc_active}"
        )
    forecast_start=parse_utc(fc["window"]["start_utc"])
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
                "source":"ecmwf_ifs025",
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

    interval_payload=[]
    for iid in ids:
        rows=combined[iid]
        obs_rows=[x for x in rows if x["source"]=="observed"]
        fc_rows=[x for x in rows if x["source"]=="ecmwf_ifs025"]
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
    status="MERGED_RAIN_FORCING_READY" if obs_complete_before_t0 and forecast_complete else "MERGED_RAIN_FORCING_REVIEW"

    payload={
        "schema_version":"g040_merged_interval_rain_forcing_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":status,
        "boundary_scenario":{
            "name":obs_scenario,
            "active_boundary_codes":obs_active,
        },
        "transition":{
            "forecast_start_utc":forecast_start.isoformat().replace("+00:00","Z"),
            "rule":"observed strictly before forecast_start; ECMWF IFS from forecast_start onward",
            "overlap_averaged":False,
            "missing_zero_filled":False,
        },
        "continuity_diagnostics":continuity,
        "gates":{
            "all_intervals_present":len(ids)==8,
            "at_least_24_observed_hours_each":obs_complete_before_t0,
            "120h_forecast_complete_each":forecast_complete,
            "observed_forecast_scenario_match":True,
        },
        "intervals":interval_payload,
        "artifacts":{"hourly_csv":str(OUTCSV.relative_to(ROOT))},
        "next_step":"translate the merged interval forcing and observed Source hydrographs into HEC-HMS time-series inputs for the branch-model replay",
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
