#!/usr/bin/env python3
"""Build the HEC-HMS element graph for the G040 observed-branch research model.

This is a structural skeleton, not an executable forecast. It turns the verified
BHO6 topology + area budget into explicit HEC-style elements:
- Source at Linha Jose Julio;
- optional tributary Sources at verified confluences;
- mainstem Reaches split exactly at tributary joins;
- one incremental rainfall-runoff Subbasin per checkpoint interval;
- Junctions at confluences and observed mainstem checkpoints.

Incremental subbasins are attached at the downstream checkpoint in this first
lumped branch representation. Their final geometry/precipitation weighting is a
separate gate. No routing K/X is invented here.

Research only.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
BUDGET=BASE/"whole_basin_incremental_area_budget_latest.json"
NETWORK=BASE/"whole_basin_bho6_network.geojson"
SCENARIOS=BASE/"whole_basin_boundary_scenarios_latest.json"
OUT=BASE/"whole_basin_hec_branch_skeleton_latest.json"
EDGECSV=BASE/"whole_basin_hec_branch_edges.csv"

def load(p: Path) -> dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def fid_lengths() -> dict[int,float]:
    g=load(NETWORK)
    out={}
    for f in g.get("features") or []:
        p=f.get("properties") or {}
        if p.get("fid") is None: continue
        try:
            out[int(p["fid"])]=float(p.get("nucomptrec") or 0.0)
        except Exception:
            pass
    return out

def path_split(path_fids: list[int], join_fid: int|None, lengths: dict[int,float]):
    if join_fid is None:
        return {
          "upstream_fids":path_fids,
          "downstream_fids":[],
          "upstream_length_km":round(sum(lengths.get(x,0.0) for x in path_fids),3),
          "downstream_length_km":0.0,
        }
    try:
        i=path_fids.index(int(join_fid))
    except ValueError:
        raise RuntimeError(f"join fid {join_fid} not found in mainstem path")
    # The join segment itself is assigned to downstream side to avoid double length.
    a=path_fids[:i]
    b=path_fids[i:]
    return {
      "upstream_fids":a,
      "downstream_fids":b,
      "upstream_length_km":round(sum(lengths.get(x,0.0) for x in a),3),
      "downstream_length_km":round(sum(lengths.get(x,0.0) for x in b),3),
    }

def add_edge(edges,src,dst,kind,**kw):
    edges.append({"from":src,"to":dst,"kind":kind,**kw})

def main():
    topo=load(TOPO); budget=load(BUDGET)
    if not topo.get("topology_pass"):
        raise RuntimeError("topology not passed")
    if budget.get("status")!="AREA_BUDGET_CLOSED":
        raise RuntimeError("area budget not closed")
    lengths=fid_lengths()
    if not lengths:
        raise RuntimeError("BHO6 network segment lengths unavailable")

    scenario_doc=load(SCENARIOS) if SCENARIOS.exists() else None
    current_active=set()
    current_name=None
    if scenario_doc:
        current_name=scenario_doc.get("current_scenario")
        current_active=set(str(x) for x in (scenario_doc.get("current") or {}).get("active_boundary_codes") or [])

    elements=[]
    edges=[]
    routing_reaches=[]
    optional_sources=[]
    subbasins=[]
    checkpoints=[]

    # Primary upstream observed boundary.
    elements.append({
      "id":"SRC_86472000","type":"Source","station_code":"86472000",
      "name":"Linha Jose Julio","role":"primary_observed_upstream_boundary",
      "required_for_all_scenarios":True,
    })

    intervals={x["interval_id"]:x for x in budget["intervals"]}
    for up,down in zip(topo["mainstem_chain"],topo["mainstem_chain"][1:]):
        key=f"{up}_to_{down}"
        interval_id=f"INC_{up}_{down}"
        p=topo["mainstem_paths"][key]
        b=intervals[interval_id]
        fids=[int(x) for x in p.get("segments") or []]
        entering=b.get("entering_observed_boundaries") or []

        j_down=f"J_{down}"
        if not any(x["id"]==j_down for x in elements):
            elements.append({
              "id":j_down,"type":"Junction","station_code":down,
              "role":"observed_mainstem_checkpoint","observed_for_validation":True,
            })
            checkpoints.append(j_down)

        sb=f"SB_{interval_id}"
        elements.append({
          "id":sb,"type":"Subbasin",
          "area_km2_preferred":float(b["residual_rainfall_runoff_area_km2"]),
          "role":"incremental_rainfall_runoff",
          "geometry_status":"pending_BHO6_compatible_polygon_or_DEM_delineation",
          "downstream":j_down,
        })
        subbasins.append(sb)
        add_edge(edges,sb,j_down,"runoff_to_checkpoint",
                 area_km2=float(b["residual_rainfall_runoff_area_km2"]))

        upstream_node="SRC_86472000" if up=="86472000" else f"J_{up}"

        if entering:
            if len(entering)!=1:
                raise RuntimeError(f"{interval_id}: current skeleton supports one verified major branch per interval")
            e=entering[0]
            code=str(e["station_code"])
            t=topo["tributary_connections"][code]
            join=int(t["join_mainstem_fid"])
            split=path_split(fids,join,lengths)
            j_join=f"J_JOIN_{code}"
            src=f"SRC_{code}"
            elements.append({
              "id":src,"type":"Source","station_code":code,
              "branch":e.get("branch"),"role":"optional_observed_tributary_boundary",
              "active_in_current_live_scenario":code in current_active,
              "preferred_boundary_area_km2":float(e["boundary_area_km2_bho6"]),
              "inactive_policy":"area returns to interval rainfall-runoff subbasin",
            })
            elements.append({
              "id":j_join,"type":"Junction","role":"verified_BHO6_tributary_confluence",
              "tributary_station_code":code,"mainstem_join_fid":join,
            })
            optional_sources.append(src)
            add_edge(edges,src,j_join,"observed_tributary_inflow",
                     preferred_area_km2=float(e["boundary_area_km2_bho6"]))

            r1=f"R_{up}_TO_JOIN_{code}"
            r2=f"R_JOIN_{code}_TO_{down}"
            elements.append({
              "id":r1,"type":"Reach","length_km":split["upstream_length_km"],
              "routing_method_candidate":"Muskingum_or_Muskingum-Cunge",
              "routing_parameters_status":"UNSET_REQUIRES_MULTI_EVENT_CALIBRATION",
            })
            elements.append({
              "id":r2,"type":"Reach","length_km":split["downstream_length_km"],
              "routing_method_candidate":"Muskingum_or_Muskingum-Cunge",
              "routing_parameters_status":"UNSET_REQUIRES_MULTI_EVENT_CALIBRATION",
            })
            routing_reaches += [r1,r2]
            add_edge(edges,upstream_node,r1,"mainstem")
            add_edge(edges,r1,j_join,"mainstem")
            add_edge(edges,j_join,r2,"mainstem")
            add_edge(edges,r2,j_down,"mainstem")
        else:
            r=f"R_{up}_TO_{down}"
            length=round(sum(lengths.get(x,0.0) for x in fids),3)
            elements.append({
              "id":r,"type":"Reach","length_km":length,
              "routing_method_candidate":"Muskingum_or_Muskingum-Cunge",
              "routing_parameters_status":"UNSET_REQUIRES_MULTI_EVENT_CALIBRATION",
            })
            routing_reaches.append(r)
            add_edge(edges,upstream_node,r,"mainstem")
            add_edge(edges,r,j_down,"mainstem")

    # Derive scenario-specific effective areas without changing topology.
    scenario_areas={}
    if scenario_doc:
        for s in scenario_doc.get("scenarios") or []:
            scenario_areas[s["name"]]={
              x["interval_id"]:float(x["effective_rainfall_runoff_area_km2"])
              for x in s.get("intervals") or []
            }

    # Ensure every reach length closes to the BHO6 path length for each interval.
    length_audit=[]
    for up,down in zip(topo["mainstem_chain"],topo["mainstem_chain"][1:]):
        key=f"{up}_to_{down}"
        expected=float(topo["mainstem_paths"][key]["length_km"])
        rel=[e for e in elements if e["type"]=="Reach" and (
            e["id"]==f"R_{up}_TO_{down}" or
            e["id"].startswith(f"R_{up}_TO_JOIN_") or
            e["id"].endswith(f"_TO_{down}") and e["id"].startswith("R_JOIN_")
        )]
        actual=sum(float(x["length_km"]) for x in rel)
        length_audit.append({
          "interval":key,"expected_km":expected,"skeleton_km":round(actual,3),
          "difference_km":round(actual-expected,6),"pass":abs(actual-expected)<=0.01
        })

    payload={
      "schema_version":"g040_hec_branch_skeleton_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "status":"STRUCTURAL_SKELETON_READY_GEOMETRY_FORCING_AND_ROUTING_PENDING",
      "scope":{
        "model":"G040 intermediate observed-branch HEC-HMS",
        "final_target":"145 subbasins + 72 reaches",
        "skeleton_outlet_checkpoint":"86996000",
        "final_basin_outlet":"Taquari-Jacui confluence",
      },
      "current_boundary_scenario":current_name,
      "elements":elements,
      "edges":edges,
      "scenario_effective_subbasin_areas_km2":scenario_areas,
      "audits":{
        "reach_length_closure":length_audit,
        "all_reach_lengths_close":all(x["pass"] for x in length_audit),
        "area_budget_closed":True,
        "topology_passed":True,
      },
      "counts":{
        "sources":sum(x["type"]=="Source" for x in elements),
        "subbasins":sum(x["type"]=="Subbasin" for x in elements),
        "reaches":sum(x["type"]=="Reach" for x in elements),
        "junctions":sum(x["type"]=="Junction" for x in elements),
        "mainstem_checkpoints":len(checkpoints),
      },
      "gates_before_executable_hec":{
        "incremental_geometry":"PENDING",
        "hourly_observed_and_IFS_forcing_per_effective_subbasin":"PENDING",
        "source_gage_time_series":"PARTIAL_LIVE_EXISTS",
        "routing_K_X":"PENDING_MULTI_EVENT_CALIBRATION",
        "loss_transform_parameters":"PENDING_EXPERIMENT_CHOICE_E0_E1_FIRST",
      },
      "policy":{
        "routing":"no basin-wide copy of Muçum K=1.25 h; calibrate reach-wise/multi-event",
        "checkpoint_observations":"validation/state diagnostics, not silently imposed as downstream sources",
        "inactive_source":"return its contributing area to rainfall-runoff via scenario area contract",
      },
    }
    if not payload["audits"]["all_reach_lengths_close"]:
        raise RuntimeError("reach length closure failed")
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    with EDGECSV.open("w",encoding="utf-8",newline="") as fh:
        fields=["from","to","kind","area_km2","preferred_area_km2"]
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for e in edges:
            w.writerow({k:e.get(k,"") for k in fields})

    print(json.dumps({
      "status":payload["status"],
      "counts":payload["counts"],
      "all_reach_lengths_close":payload["audits"]["all_reach_lengths_close"],
      "current_boundary_scenario":current_name,
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
