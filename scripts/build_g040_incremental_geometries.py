#!/usr/bin/env python3
"""Build residual incremental catchment geometries for the G040 branch HEC model.

Method
------
1. Rebuild the directed BHO6 graph for cocursodag LIKE '786%'.
2. For each verified mainstem interval U -> D, compute:
      residual segments = upstream(D) - upstream(U) - upstream(observed branches entering interval)
3. Validate the residual area from sum(nuareacont) against the independent
   cumulative-area budget.
4. Crosswalk residual BHO6 ottobasins to the official ANA BHO 2017 50K
   drainage-area polygon layer by COBACIA.
5. Union matched polygons per interval and publish geometry coverage metrics.

The 2017 polygon layer is used only when its Otto code matches the BHO6
segment. Unmatched codes remain explicit; no guessed polygon replacement.

Research only.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform as shp_transform

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
BUDGET=BASE/"whole_basin_incremental_area_budget_latest.json"
OUT=BASE/"whole_basin_incremental_geometry_latest.json"
GEO=BASE/"whole_basin_incremental_catchments.geojson"

BHO6_QUERY=(
 "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
 "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
BHO2017_POLY=(
 "https://portal1.snirh.gov.br/arcgis/rest/services/SPR/"
 "BHO2017_50K_AREADRENAGEM/FeatureServer/0/query"
)
FIELDS="fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,nuareamont,nuareacont,nucomptrec,dsversao"
PROJECT=Transformer.from_crs("EPSG:4326","EPSG:31982",always_xy=True)

def fetch_json(url,params,timeout=90):
    r=requests.get(url,params=params,timeout=timeout,headers={"User-Agent":"PREVINE-G040-incremental-geometry/1.0"})
    r.raise_for_status()
    p=r.json()
    if "error" in p:
        raise RuntimeError(json.dumps(p["error"],ensure_ascii=False))
    return p

def fetch_bho6():
    rows=[]; offset=0
    while True:
        p=fetch_json(BHO6_QUERY,{
          "where":"cocursodag LIKE '786%'","outFields":FIELDS,
          "returnGeometry":"false","resultOffset":offset,
          "resultRecordCount":2000,"orderByFields":"fid","f":"json",
        })
        page=[x["attributes"] for x in p.get("features",[])]
        rows.extend(page)
        if len(page)<2000: break
        offset+=len(page)
    return rows

def upstream_set(by_dest,start_fid,by_fid):
    start=by_fid[int(start_fid)]
    selected={int(start["fid"])}
    pending=[int(start["noorigem"])]
    visited=set()
    while pending:
        node=pending.pop()
        if node in visited: continue
        visited.add(node)
        for s in by_dest.get(node,[]):
            fid=int(s["fid"])
            if fid in selected: continue
            selected.add(fid)
            pending.append(int(s["noorigem"]))
    return selected

def batch_query_polygons(cobacias):
    features=[]
    vals=sorted({str(x) for x in cobacias if x not in (None,"")})
    for i in range(0,len(vals),50):
        batch=vals[i:i+50]
        quoted=",".join("'" + x.replace("'","''") + "'" for x in batch)
        where=f"COBACIA IN ({quoted})"
        p=fetch_json(BHO2017_POLY,{
          "where":where,
          "outFields":"OBJECTID,COTRECHO,COCURSODAG,COBACIA,NUAREACONT,DSVERSAO",
          "returnGeometry":"true","outSR":"4326","resultRecordCount":1000,"f":"geojson",
        },timeout=120)
        features.extend(p.get("features",[]))
    return features

def area_km2(geom):
    def pr(x,y,z=None):
        return PROJECT.transform(x,y)
    return shp_transform(pr,geom).area/1e6

def main():
    topo=json.loads(TOPO.read_text(encoding="utf-8"))
    budget=json.loads(BUDGET.read_text(encoding="utf-8"))
    if not topo.get("topology_pass") or budget.get("status")!="AREA_BUDGET_CLOSED":
        raise RuntimeError("topology/area budget not ready")

    segs=fetch_bho6()
    by_fid={int(x["fid"]):x for x in segs}
    by_dest={}
    for x in segs:
        by_dest.setdefault(int(x["nodestino"]),[]).append(x)

    snapped=topo["snapped_stations"]
    upstream_cache={}
    def U(code):
        if code not in upstream_cache:
            upstream_cache[code]=upstream_set(
              by_dest,int(snapped[code]["segment"]["fid"]),by_fid
            )
        return upstream_cache[code]

    # map entering branches from budget interval records
    records=[]
    all_cobacias=set()
    interval_segment_sets={}
    for item in budget["intervals"]:
        up=item["upstream_station"]; down=item["downstream_station"]
        residual=set(U(down))-set(U(up))
        entering_codes=[x["station_code"] for x in item.get("entering_observed_boundaries") or []]
        for code in entering_codes:
            residual-=set(U(code))
        interval_segment_sets[item["interval_id"]]=residual
        local_area=sum(float(by_fid[f].get("nuareacont") or 0.0) for f in residual)
        expected=float(item["residual_rainfall_runoff_area_km2"])
        cobacias=[str(by_fid[f].get("cobacia") or "") for f in residual if by_fid[f].get("cobacia")]
        all_cobacias.update(cobacias)
        records.append({
          "interval_id":item["interval_id"],
          "upstream_station":up,"downstream_station":down,
          "segment_count":len(residual),
          "bho6_local_area_sum_km2":round(local_area,3),
          "budget_residual_area_km2":round(expected,3),
          "area_difference_km2":round(local_area-expected,3),
          "area_difference_pct":round(100*(local_area-expected)/expected,3) if expected else None,
          "cobacia_count":len(set(cobacias)),
          "entering_observed_boundaries":entering_codes,
        })

    # Area budget and segment-local area should agree before geometry crosswalk.
    bad=[r for r in records if abs(r["area_difference_km2"])>max(2.0,0.01*r["budget_residual_area_km2"])]
    if bad:
        raise RuntimeError("BHO6 local-area difference exceeds tolerance: "+json.dumps(bad,ensure_ascii=False))

    polys=batch_query_polygons(all_cobacias)
    poly_by_cobacia={}
    for f in polys:
        code=str((f.get("properties") or {}).get("COBACIA") or "")
        if code and f.get("geometry"):
            poly_by_cobacia.setdefault(code,[]).append(f)

    out_features=[]
    geometry_records=[]
    for rec in records:
        ids=interval_segment_sets[rec["interval_id"]]
        codes={str(by_fid[f].get("cobacia") or "") for f in ids if by_fid[f].get("cobacia")}
        matched=[feat for c in codes for feat in poly_by_cobacia.get(c,[])]
        matched_codes={str((x.get("properties") or {}).get("COBACIA") or "") for x in matched}
        missing=sorted(codes-matched_codes)
        geoms=[shape(x["geometry"]) for x in matched if x.get("geometry")]
        union=unary_union(geoms) if geoms else None
        ga=area_km2(union) if union is not None and not union.is_empty else None
        coverage=(len(matched_codes)/len(codes)) if codes else 1.0
        row={
          **rec,
          "polygon_source":"ANA BHO2017 50K AREADRENAGEM",
          "matched_cobacia_count":len(matched_codes),
          "missing_cobacia_count":len(missing),
          "cobacia_match_ratio":round(coverage,4),
          "geometry_area_km2_epsg31982":None if ga is None else round(ga,3),
          "missing_cobacias":missing[:100],
        }
        geometry_records.append(row)
        if union is not None and not union.is_empty:
            out_features.append({
              "type":"Feature",
              "geometry":mapping(union),
              "properties":{
                "interval_id":rec["interval_id"],
                "upstream_station":rec["upstream_station"],
                "downstream_station":rec["downstream_station"],
                "bho6_residual_area_km2":rec["budget_residual_area_km2"],
                "geometry_area_km2":None if ga is None else round(ga,3),
                "cobacia_match_ratio":round(coverage,4),
                "research_only":True,
              },
            })

    min_match=min((x["cobacia_match_ratio"] for x in geometry_records),default=0.0)
    usable=min_match>=0.95 and len(out_features)==len(records)
    payload={
      "schema_version":"g040_whole_basin_incremental_geometry_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "status":"GEOMETRY_CANDIDATE_READY_FOR_RAINFALL_SPATIALIZATION" if usable else "GEOMETRY_CROSSWALK_REVIEW",
      "bho6_version":"BHO bho_v_06_02_04 de 2022-10-11",
      "polygon_source":{
        "provider":"ANA/SNIRH",
        "dataset":"BHO2017 50K AREADRENAGEM",
        "endpoint":BHO2017_POLY,
        "crosswalk_key":"COBACIA",
        "policy":"exact Otto code match only; no guessed replacement",
      },
      "intervals":geometry_records,
      "minimum_cobacia_match_ratio":round(min_match,4),
      "all_interval_geometries_created":len(out_features)==len(records),
      "usable_for_spatial_rain_candidate":usable,
      "note":"2017 polygons are a geometry crosswalk candidate, not a silent replacement for the final ANADEM-derived 145 HEC subbasins.",
      "next_step":"intersect 600-cell observed/IFS forcing with accepted residual polygons and build HEC-HMS branch project",
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    GEO.write_text(json.dumps({
      "type":"FeatureCollection",
      "name":"G040_residual_incremental_catchments_candidate",
      "features":out_features,
    },ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps({
      "status":payload["status"],
      "intervals":len(records),
      "min_match_ratio":payload["minimum_cobacia_match_ratio"],
      "geometries":len(out_features),
      "usable":payload["usable_for_spatial_rain_candidate"],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
