#!/usr/bin/env python3
"""Build BHO6-compatible residual catchment geometries for the G040 branch model.

The network and area budget come from ANA/SNIRH BHO6. Polygon geometry is
accepted only from an explicitly BHO6-compatible polygon layer. The previous
BHO2017 COBACIA crosswalk is intentionally rejected because the code systems
are not version-compatible for this use.

Research only.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform as shp_transform

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
TOPO=BASE/"whole_basin_bho6_topology_latest.json"
BUDGET=BASE/"whole_basin_incremental_area_budget_latest.json"
PROBE=BASE/"arcgis_bho6_polygon_probe_latest.json"
OUT=BASE/"whole_basin_incremental_geometry_latest.json"
GEO=BASE/"whole_basin_incremental_catchments.geojson"

BHO6_QUERY=(
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
FIELDS="fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,nuareamont,nuareacont,nucomptrec,dsversao"
PROJECT=Transformer.from_crs("EPSG:4326","EPSG:31982",always_xy=True)
UA={"User-Agent":"PREVINE-G040-incremental-geometry/2.0"}
CORE={"cobacia","cotrecho","nuareacont"}

def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def fetch_json(url,params=None,timeout=90):
    r=requests.get(url,params=params or {},timeout=timeout,headers=UA)
    r.raise_for_status()
    p=r.json()
    if isinstance(p,dict) and p.get("error"):
        raise RuntimeError(json.dumps(p["error"],ensure_ascii=False))
    return p

def fetch_bho6():
    rows=[]; offset=0
    while True:
        p=fetch_json(BHO6_QUERY,{
            "where":"cocursodag LIKE '786%'",
            "outFields":FIELDS,
            "returnGeometry":"false",
            "resultOffset":offset,
            "resultRecordCount":2000,
            "orderByFields":"fid",
            "f":"json",
        })
        page=[x["attributes"] for x in p.get("features",[])]
        rows.extend(page)
        if len(page)<2000:
            break
        offset+=len(page)
    return rows

def upstream_set(by_dest,start_fid,by_fid):
    start=by_fid[int(start_fid)]
    selected={int(start["fid"])}
    pending=[int(start["noorigem"])]
    visited=set()
    while pending:
        node=pending.pop()
        if node in visited:
            continue
        visited.add(node)
        for seg in by_dest.get(node,[]):
            fid=int(seg["fid"])
            if fid in selected:
                continue
            selected.add(fid)
            pending.append(int(seg["noorigem"]))
    return selected

def resolve_polygon_layer():
    env=os.environ.get("BHO6_POLYGON_LAYER_URL","").strip().rstrip("/")
    if env:
        return env, "environment"
    if PROBE.exists():
        p=json.loads(PROBE.read_text(encoding="utf-8"))
        accepted=p.get("accepted_candidates") or []
        if accepted:
            return str(accepted[0]["layer_url"]).rstrip("/"), "arcgis_probe"
    return None, None

def inspect_polygon_layer(layer_url):
    meta=fetch_json(layer_url,{"f":"json"})
    fields=[str(x.get("name") or "") for x in meta.get("fields") or []]
    low={x.lower():x for x in fields}
    if str(meta.get("geometryType") or "")!="esriGeometryPolygon":
        raise RuntimeError("candidate polygon source is not esriGeometryPolygon")
    if not CORE <= set(low):
        raise RuntimeError(f"candidate polygon source misses required fields: {sorted(CORE-set(low))}")
    out=[low[x] for x in ("cobacia","cotrecho","nuareacont")]
    for extra in ("cocursodag","dsversao"):
        if extra in low:
            out.append(low[extra])
    where="1=1"
    if "cocursodag" in low:
        where=f"{low['cocursodag']} LIKE '786%'"
    sample=fetch_json(layer_url+"/query",{
        "f":"json","where":where,"outFields":",".join(out),
        "returnGeometry":"false","resultRecordCount":1,
    })
    attrs=((sample.get("features") or [{}])[0].get("attributes") or {}) if sample.get("features") else {}
    evidence=" ".join([
        str(meta.get("name") or ""),
        str(meta.get("description") or ""),
        str(attrs),
    ]).lower()
    bho6=("bho6" in evidence or "versão 6" in evidence or "versao 6" in evidence or "v_06" in evidence or "6.2" in evidence)
    if "2017" in evidence or not bho6:
        raise RuntimeError("polygon layer lacks explicit BHO6 version evidence")
    return {
        "layer_url":layer_url,
        "layer_name":meta.get("name"),
        "fields":fields,
        "sample_g040":attrs,
        "version_evidence":evidence[:1000],
    }

def batch_query_polygons(layer_url,cobacias):
    features=[]
    vals=sorted({str(x) for x in cobacias if x not in (None,"")})
    for i in range(0,len(vals),50):
        batch=vals[i:i+50]
        quoted=",".join("'" + x.replace("'","''") + "'" for x in batch)
        p=fetch_json(layer_url+"/query",{
            "where":f"COBACIA IN ({quoted})",
            "outFields":"COBACIA,COTRECHO,COCURSODAG,NUAREACONT,DSVERSAO",
            "returnGeometry":"true",
            "outSR":"4326",
            "resultRecordCount":2000,
            "f":"geojson",
        },timeout=120)
        features.extend(p.get("features",[]))
    return features

def area_km2(geom):
    def pr(x,y,z=None):
        return PROJECT.transform(x,y)
    return shp_transform(pr,geom).area/1e6

def persist(payload,features):
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    GEO.write_text(json.dumps({
        "type":"FeatureCollection",
        "name":"G040_residual_incremental_catchments_BHO6",
        "features":features,
    },ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")

def main():
    topo=json.loads(TOPO.read_text(encoding="utf-8"))
    budget=json.loads(BUDGET.read_text(encoding="utf-8"))
    if not topo.get("topology_pass") or budget.get("status")!="AREA_BUDGET_CLOSED":
        raise RuntimeError("BHO6 topology/area budget not ready")

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

    records=[]
    interval_segment_sets={}
    all_cobacias=set()
    for item in budget["intervals"]:
        up=item["upstream_station"]; down=item["downstream_station"]
        residual=set(U(down))-set(U(up))
        entering=[x["station_code"] for x in item.get("entering_observed_boundaries") or []]
        for code in entering:
            residual-=set(U(code))
        local_area=sum(float(by_fid[f].get("nuareacont") or 0.0) for f in residual)
        expected=float(item["residual_rainfall_runoff_area_km2"])
        codes={str(by_fid[f].get("cobacia") or "") for f in residual if by_fid[f].get("cobacia")}
        all_cobacias.update(codes)
        interval_segment_sets[item["interval_id"]]=residual
        records.append({
            "interval_id":item["interval_id"],
            "upstream_station":up,
            "downstream_station":down,
            "segment_count":len(residual),
            "cobacia_count":len(codes),
            "bho6_local_area_sum_km2":round(local_area,3),
            "budget_residual_area_km2":round(expected,3),
            "area_difference_km2":round(local_area-expected,3),
            "area_difference_pct":round(100*(local_area-expected)/expected,3) if expected else None,
            "entering_observed_boundaries":entering,
        })

    bad=[r for r in records if abs(r["area_difference_km2"])>max(2.0,0.01*r["budget_residual_area_km2"])]
    if bad:
        raise RuntimeError("BHO6 segment area does not close: "+json.dumps(bad,ensure_ascii=False))

    layer_url,selection=resolve_polygon_layer()
    if not layer_url:
        payload={
            "schema_version":"g040_whole_basin_incremental_geometry_v2",
            "generated_at_utc":now(),
            "research_only":True,
            "status":"BLOCKED_BHO6_POLYGON_SOURCE_REQUIRED",
            "bho6_version":"BHO v6.2.4 / topology source reports 2022-10-11",
            "polygon_source":None,
            "rejected_source":"BHO2017 50K exact COBACIA crosswalk",
            "reason":"BHO6 and BHO2017 drainage-area identifiers are not version-compatible enough for exact residual geometry reconstruction.",
            "intervals":records,
            "all_interval_geometries_created":False,
            "usable_for_spatial_rain_candidate":False,
            "next_step":"provide/query a BHO6 area-drainage polygon layer and rerun exact COBACIA matching",
        }
        persist(payload,[])
        print(json.dumps({"status":payload["status"],"intervals":len(records)},ensure_ascii=False))
        return 0

    source=inspect_polygon_layer(layer_url)
    source["selection"]=selection
    polys=batch_query_polygons(layer_url,all_cobacias)
    poly_by_code={}
    for feat in polys:
        props=feat.get("properties") or {}
        code=str(props.get("COBACIA") or props.get("cobacia") or "")
        if code and feat.get("geometry"):
            poly_by_code.setdefault(code,[]).append(feat)

    out_features=[]
    geometry_records=[]
    for rec in records:
        ids=interval_segment_sets[rec["interval_id"]]
        codes={str(by_fid[f].get("cobacia") or "") for f in ids if by_fid[f].get("cobacia")}
        matched=[feat for c in codes for feat in poly_by_code.get(c,[])]
        matched_codes={
            str((x.get("properties") or {}).get("COBACIA") or (x.get("properties") or {}).get("cobacia") or "")
            for x in matched
        }
        missing=sorted(codes-matched_codes)
        geoms=[shape(x["geometry"]) for x in matched if x.get("geometry")]
        union=unary_union(geoms) if geoms else None
        ga=area_km2(union) if union is not None and not union.is_empty else None
        expected=rec["budget_residual_area_km2"]
        geom_err_pct=None if ga is None or not expected else 100*(ga-expected)/expected
        coverage=(len(matched_codes)/len(codes)) if codes else 1.0
        row={
            **rec,
            "matched_cobacia_count":len(matched_codes),
            "missing_cobacia_count":len(missing),
            "cobacia_match_ratio":round(coverage,4),
            "geometry_area_km2_epsg31982":None if ga is None else round(ga,3),
            "geometry_vs_budget_error_pct":None if geom_err_pct is None else round(geom_err_pct,3),
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
                    "bho6_residual_area_km2":expected,
                    "geometry_area_km2":None if ga is None else round(ga,3),
                    "cobacia_match_ratio":round(coverage,4),
                    "research_only":True,
                },
            })

    min_match=min((x["cobacia_match_ratio"] for x in geometry_records),default=0.0)
    max_area_err=max((abs(x["geometry_vs_budget_error_pct"]) for x in geometry_records if x["geometry_vs_budget_error_pct"] is not None),default=999.0)
    usable=min_match>=0.99 and len(out_features)==len(records) and max_area_err<=5.0
    payload={
        "schema_version":"g040_whole_basin_incremental_geometry_v2",
        "generated_at_utc":now(),
        "research_only":True,
        "status":"GEOMETRY_CANDIDATE_READY_FOR_RAINFALL_SPATIALIZATION" if usable else "BHO6_GEOMETRY_REVIEW_REQUIRED",
        "bho6_version":"BHO v6.2.4 / topology source reports 2022-10-11",
        "polygon_source":source,
        "rejected_source":"BHO2017 50K exact COBACIA crosswalk",
        "intervals":geometry_records,
        "minimum_cobacia_match_ratio":round(min_match,4),
        "maximum_abs_geometry_area_error_pct":round(max_area_err,3),
        "all_interval_geometries_created":len(out_features)==len(records),
        "usable_for_spatial_rain_candidate":usable,
        "note":"Geometry is promoted only from version-compatible BHO6 polygons; no guessed crosswalk.",
        "next_step":"intersect the 600-cell observed/IFS forcing with accepted residual polygons" if usable else "review BHO6 polygon coverage/version evidence before rainfall spatialization",
    }
    persist(payload,out_features)
    print(json.dumps({
        "status":payload["status"],
        "intervals":len(records),
        "min_match_ratio":payload["minimum_cobacia_match_ratio"],
        "max_area_error_pct":payload["maximum_abs_geometry_area_error_pct"],
        "geometries":len(out_features),
        "usable":usable,
        "source":layer_url,
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
