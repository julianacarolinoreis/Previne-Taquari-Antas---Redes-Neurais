#!/usr/bin/env python3
"""Build scenario-aware BHO6 rainfall support points for G040.

Each mainstem interval is represented by ALL BHO6 local drainage elements in
its gross incremental area.  Points that belong to an independently observed
tributary boundary are tagged with that boundary code instead of being deleted.

At forcing time, only points belonging to ACTIVE observed boundaries are
excluded.  Therefore if Guaporé/Forqueta discharge becomes unavailable, their
areas automatically return to rainfall-runoff without changing the support
mesh or violating mass balance.

Geometry: midpoint of the BHO6 drainage reach.
Area weight: official BHO6 local drainage area (nuareacont).
No BHO2017 polygon crosswalk is guessed.

Research only; not an official warning system.
"""
from __future__ import annotations
import csv, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
BUDGET=BASE/"whole_basin_incremental_area_budget_latest.json"
OUT=BASE/"whole_basin_rain_support_latest.json"
OUTCSV=BASE/"whole_basin_rain_support_points.csv"

BHO6_QUERY=(
 "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
 "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
FIELDS=("fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,"
        "nuareamont,nuareacont,nucomptrec,dsversao")

def get_json(session:requests.Session,params:dict[str,Any])->dict[str,Any]:
    r=session.get(BHO6_QUERY,params=params,timeout=120); r.raise_for_status()
    p=r.json()
    if "error" in p: raise RuntimeError(json.dumps(p["error"],ensure_ascii=False))
    return p

def fetch_attributes(session):
    rows=[]; offset=0
    while True:
        p=get_json(session,{"where":"cocursodag LIKE '786%'","outFields":FIELDS,
          "returnGeometry":"false","resultOffset":offset,"resultRecordCount":2000,
          "orderByFields":"fid","f":"json"})
        page=[x["attributes"] for x in p.get("features",[])]
        rows.extend(page)
        if len(page)<2000: break
        offset+=len(page)
    if not rows: raise RuntimeError("BHO6 family 786 returned no records")
    return rows

def fetch_geometries(session,fids):
    out={}
    for i in range(0,len(fids),100):
        batch=fids[i:i+100]
        p=get_json(session,{"where":"fid IN ("+",".join(map(str,batch))+")",
          "outFields":FIELDS,"returnGeometry":"true","outSR":"4326",
          "resultRecordCount":200,"f":"geojson"})
        for f in p.get("features",[]):
            pr=f.get("properties") or {}
            if pr.get("fid") is not None and f.get("geometry"):
                out[int(pr["fid"])]=f
    return out

def upstream_set(by_dest,start_fid,by_fid):
    start=by_fid[int(start_fid)]
    selected={int(start["fid"])}; pending=[int(start["noorigem"])]; visited=set()
    while pending:
        node=pending.pop()
        if node in visited: continue
        visited.add(node)
        for s in by_dest.get(node,[]):
            fid=int(s["fid"])
            if fid in selected: continue
            selected.add(fid); pending.append(int(s["noorigem"]))
    return selected

def midpoint(feature):
    g=shape(feature["geometry"])
    if g.is_empty: raise RuntimeError("empty BHO6 geometry")
    p=g.interpolate(.5,normalized=True)
    return float(p.x),float(p.y)

def main():
    topo=json.loads(TOPO.read_text(encoding="utf-8"))
    budget=json.loads(BUDGET.read_text(encoding="utf-8"))
    if not topo.get("topology_pass"): raise RuntimeError("BHO6 topology has not passed")
    if budget.get("status")!="AREA_BUDGET_CLOSED": raise RuntimeError("area budget not closed")

    with requests.Session() as session:
        session.headers.update({"User-Agent":"PREVINE-G040-dynamic-rain-support/2.0"})
        segs=fetch_attributes(session)
        by_fid={int(x["fid"]):x for x in segs}; by_dest={}
        for x in segs: by_dest.setdefault(int(x["nodestino"]),[]).append(x)
        snapped=topo["snapped_stations"]; cache={}
        def U(code):
            code=str(code)
            if code not in cache:
                cache[code]=upstream_set(by_dest,int(snapped[code]["segment"]["fid"]),by_fid)
            return cache[code]

        interval_sets={}; branch_sets={}; all_fids=set()
        budget_by={x["interval_id"]:x for x in budget["intervals"]}
        for item in budget["intervals"]:
            iid=item["interval_id"]; up=str(item["upstream_station"]); down=str(item["downstream_station"])
            gross=set(U(down))-set(U(up))
            interval_sets[iid]=gross; all_fids.update(gross)
            for b in item.get("entering_observed_boundaries") or []:
                code=str(b["station_code"])
                branch_sets[(iid,code)]=set(U(code)) & gross
        geom=fetch_geometries(session,sorted(all_fids))

    missing=all_fids-set(geom)
    if missing: raise RuntimeError(f"missing BHO6 geometries for {len(missing)} gross interval segments")

    rows=[]; summaries=[]
    for iid,gross in interval_sets.items():
        item=budget_by[iid]
        expected=float(item["gross_increment_km2"])
        local_sum=sum(float(by_fid[f].get("nuareacont") or 0) for f in gross)
        tol=max(.05,.0005*expected)
        if abs(local_sum-expected)>tol:
            raise RuntimeError(f"{iid}: gross support area {local_sum:.6f} != budget {expected:.6f}")
        branch_codes=[str(x["station_code"]) for x in item.get("entering_observed_boundaries") or []]
        branch_areas={code:0.0 for code in branch_codes}
        ir=[]
        for fid in sorted(gross):
            a=float(by_fid[fid].get("nuareacont") or 0)
            if a<=0: continue
            tags=[code for code in branch_codes if fid in branch_sets.get((iid,code),set())]
            if len(tags)>1: raise RuntimeError(f"{iid} fid={fid}: overlaps multiple independent boundaries {tags}")
            tag=tags[0] if tags else ""
            if tag: branch_areas[tag]+=a
            lon,lat=midpoint(geom[fid])
            row={"interval_id":iid,"upstream_station":item["upstream_station"],
                 "downstream_station":item["downstream_station"],"fid":fid,
                 "cobacia":str(by_fid[fid].get("cobacia") or ""),"lon":round(lon,7),
                 "lat":round(lat,7),"local_area_km2":a,
                 "gross_weight":a/local_sum,"tributary_boundary_code":tag,
                 "component_id":("BRANCH_"+tag) if tag else ("CORE_"+iid)}
            ir.append(row); rows.append(row)
        expected_br={str(x["station_code"]):float(x["boundary_area_km2_bho6"])
                     for x in item.get("entering_observed_boundaries") or []}
        branch_checks={}
        for code,exp in expected_br.items():
            got=branch_areas.get(code,0.0)
            branch_checks[code]={"expected_km2":round(exp,6),"support_km2":round(got,6),
                                 "error_km2":round(got-exp,6),
                                 "pass":abs(got-exp)<=max(.05,.0005*exp)}
        summaries.append({"interval_id":iid,"support_points":len(ir),
          "gross_budget_area_km2":round(expected,6),"gross_support_area_km2":round(local_sum,6),
          "gross_area_error_km2":round(local_sum-expected,6),
          "gross_weight_sum":round(sum(x["gross_weight"] for x in ir),12),
          "boundary_area_checks":branch_checks,
          "pass":abs(local_sum-expected)<=tol and all(x["pass"] for x in branch_checks.values())})

    if not rows or not all(x["pass"] for x in summaries):
        raise RuntimeError("scenario-aware support mesh failed closure")

    fields=["interval_id","upstream_station","downstream_station","fid","cobacia",
            "lon","lat","local_area_km2","gross_weight","tributary_boundary_code","component_id"]
    with OUTCSV.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for row in rows: w.writerow({k:row[k] for k in fields})

    total=sum(x["gross_support_area_km2"] for x in summaries)
    payload={"schema_version":"g040_bho6_rain_support_v2_dynamic_boundaries",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,"status":"RAIN_SUPPORT_READY_DYNAMIC_SCENARIO",
      "method":{"geometry":"BHO6 reach midpoint","weight":"BHO6 nuareacont",
        "mesh_scope":"gross incremental mainstem area",
        "boundary_tagging":"points inside an independent tributary upstream set carry tributary_boundary_code",
        "scenario_rule":"exclude only points whose tributary boundary is ACTIVE; inactive boundary areas remain rainfall-runoff",
        "polygon_dependency":False},
      "source":{"provider":"ANA/SNIRH","dataset":"BHO6 trecho drenagem",
        "version":next((str(x.get("dsversao")) for x in segs if x.get("dsversao")),None)},
      "intervals":summaries,"total_support_points":len(rows),
      "total_gross_support_area_km2":round(total,6),
      "expected_total_mainstem_area_gain_km2":round(sum(float(x["gross_increment_km2"]) for x in budget["intervals"]),6),
      "all_intervals_close":True,
      "usage_contract":{"observed":"IDW field sampled at support points after scenario filtering",
        "forecast":"ECMWF field sampled at same points after scenario filtering",
        "missing":"never zero-fill","dynamic_boundaries":True},
      "artifacts":{"support_points_csv":str(OUTCSV.relative_to(ROOT))},
      "next_step":"filter support mesh with current boundary scenario, then build observed/forecast interval rainfall"}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"points":len(rows),
      "gross_area_km2":payload["total_gross_support_area_km2"],"intervals":len(summaries)},ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
