#!/usr/bin/env python3
"""Recover BHO6 topology for the G040 whole-basin observed-branch architecture.

Stations are snapped using BOTH drainage-area similarity and spatial distance.
The resulting graph is used to verify mainstem order and tributary confluences.
No management polygon is promoted to an HEC computational subbasin.

Research only; not an official warning system.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
ARCH=BASE/"whole_basin_branch_model_latest.json"
STATIONS=BASE/"full_basin_station_matrix.csv"
OUT=BASE/"whole_basin_bho6_topology_latest.json"
GEO=BASE/"whole_basin_bho6_network.geojson"

BHO6_QUERY=(
 "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
 "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
OUT_FIELDS=(
 "fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,nuareamont,"
 "nuareacont,nucomptrec,nucompcda,nunivotcda,nustrahler,noriocomp,"
 "noespecif,dedominial,dsversao"
)
PROJECTED=Transformer.from_crs("EPSG:4326","EPSG:31982",always_xy=True)

def get_json(session,params):
    r=session.get(BHO6_QUERY,params=params,timeout=90)
    r.raise_for_status()
    p=r.json()
    if "error" in p:
        raise RuntimeError(json.dumps(p["error"],ensure_ascii=False))
    return p

def fetch_attributes(session):
    rows=[]; offset=0
    while True:
        p=get_json(session,{
          "where":"cocursodag LIKE '786%'","outFields":OUT_FIELDS,
          "returnGeometry":"false","resultOffset":offset,
          "resultRecordCount":2000,"orderByFields":"fid","f":"json",
        })
        page=[x["attributes"] for x in p.get("features",[])]
        rows.extend(page)
        if len(page)<2000: break
        offset+=len(page)
    return rows

def fetch_geometry_for_ids(session,fids):
    out=[]
    for i in range(0,len(fids),100):
        batch=fids[i:i+100]
        if not batch: continue
        p=get_json(session,{
          "where":"fid IN ("+",".join(str(int(x)) for x in batch)+")",
          "outFields":OUT_FIELDS,"returnGeometry":"true","outSR":"4326",
          "resultRecordCount":200,"f":"geojson",
        })
        out.extend(p.get("features",[]))
    return out

def dist_m(feature,lon,lat):
    geom=shape(feature["geometry"])
    def proj(x,y,z=None):
        return PROJECTED.transform(x,y)
    pg=shp_transform(proj,geom)
    x,y=PROJECTED.transform(lon,lat)
    return pg.distance(Point(x,y))

def station_inventory():
    out={}
    with STATIONS.open(encoding="utf-8",newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("kind")!="flow": continue
            out[str(r["code"])]=r
    return out

def area(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def snap_station(session,all_segments,st):
    a=area(st.get("drainage_area_km2"))
    lon=float(st["lon"]); lat=float(st["lat"])
    tolerances=(0.08,0.15,0.30,0.50)
    candidates=[]
    for frac in tolerances:
        if a is None: break
        abs_tol=max(80.0,a*frac)
        candidates=[
          s for s in all_segments
          if area(s.get("nuareamont")) is not None
          and abs(float(s["nuareamont"])-a)<=abs_tol
        ]
        if candidates: break
    if not candidates:
        # Rare fallback: use plausible G040 segments, then spatial distance.
        candidates=[s for s in all_segments if area(s.get("nuareamont")) is not None]
    # Bound geometry calls when a wide area window returns too many segments.
    if len(candidates)>700:
        candidates=sorted(
          candidates,
          key=lambda s: abs(float(s.get("nuareamont") or 0)-(a or 0))
        )[:700]
    feats=fetch_geometry_for_ids(session,[int(s["fid"]) for s in candidates])
    if not feats:
        raise RuntimeError(f"no BHO6 geometry candidates for {st['code']}")
    ranked=sorted(
      ((dist_m(f,lon,lat),f) for f in feats),
      key=lambda x:x[0]
    )
    d,f=ranked[0]
    p=f["properties"]
    return {
      "station_code":str(st["code"]),
      "station_name":st.get("name"),
      "station_lon":lon,"station_lat":lat,
      "station_drainage_area_km2":a,
      "segment":p,
      "distance_m":round(d,2),
      "area_error_km2":None if a is None else round(float(p.get("nuareamont") or 0)-a,3),
      "candidate_count":len(candidates),
    }

def choose_downstream(choices):
    # On a directed hydrographic graph, the downstream continuation should
    # normally be unique. If multiple records share a node, prefer the largest
    # upstream area as the receiving trunk.
    return max(choices,key=lambda x:(float(x.get("nuareamont") or 0),int(x["fid"])))

def downstream_path(by_origin,start,target_fid=None,stop_fids=None,max_steps=10000):
    path=[start]; seen={int(start["fid"])}
    current=start
    stop_fids=set(stop_fids or [])
    if int(current["fid"]) in stop_fids:
        return path,"joined_existing"
    for _ in range(max_steps):
        if target_fid is not None and int(current["fid"])==int(target_fid):
            return path,"target"
        choices=by_origin.get(int(current["nodestino"]),[])
        if not choices:
            return path,"terminal"
        nxt=choose_downstream(choices)
        fid=int(nxt["fid"])
        if fid in seen:
            return path,"cycle"
        path.append(nxt); seen.add(fid); current=nxt
        if fid in stop_fids:
            return path,"joined_existing"
    return path,"max_steps"

def path_summary(path):
    return {
      "segment_count":len(path),
      "length_km":round(sum(float(x.get("nucomptrec") or 0) for x in path),3),
      "start_fid":int(path[0]["fid"]),
      "end_fid":int(path[-1]["fid"]),
      "start_area_km2":round(float(path[0].get("nuareamont") or 0),3),
      "end_area_km2":round(float(path[-1].get("nuareamont") or 0),3),
      "segments":[int(x["fid"]) for x in path],
    }

def main():
    arch=json.loads(ARCH.read_text(encoding="utf-8"))
    inv=station_inventory()
    branch_specs=arch["major_branch_controls"]
    main_specs=sorted(arch["mainstem_checkpoints"],key=lambda x:int(x["order"]))

    required={x["code"] for x in branch_specs}|{x["code"] for x in main_specs}
    missing=sorted(required-set(inv))
    if missing: raise RuntimeError(f"stations missing from inventory: {missing}")

    with requests.Session() as session:
        session.headers.update({"User-Agent":"PREVINE-G040-whole-basin-topology/1.0"})
        segs=fetch_attributes(session)
        by_origin={}
        for s in segs:
            by_origin.setdefault(int(s["noorigem"]),[]).append(s)

        snapped={}
        for code in sorted(required):
            snapped[code]=snap_station(session,segs,inv[code])

        # Mainstem begins at Linha José Júlio, preserving the validated Muçum
        # architecture; Prata remains upstream diagnostic and is not added.
        chain_codes=["86472000"]+[x["code"] for x in main_specs]
        chain_paths={}
        all_mainstem_fids=set()
        order_ok=True
        for a,b in zip(chain_codes,chain_codes[1:]):
            p,status=downstream_path(
              by_origin,
              snapped[a]["segment"],
              target_fid=int(snapped[b]["segment"]["fid"])
            )
            sm=path_summary(p); sm["status"]=status
            sm["from_station"]=a; sm["to_station"]=b
            sm["target_reached"]=status=="target"
            if not sm["target_reached"]: order_ok=False
            chain_paths[f"{a}_to_{b}"]=sm
            all_mainstem_fids.update(sm["segments"])

        tributaries={}
        for b in branch_specs:
            code=b["code"]
            if b.get("mass_balance") is False:
                tributaries[code]={
                  "role":b["role"],"branch":b["branch"],
                  "mass_balance":False,
                  "status":"upstream_diagnostic_nested_inside_86472000",
                  "snap":snapped[code],
                }
                continue
            if code=="86472000":
                continue
            p,status=downstream_path(
              by_origin,
              snapped[code]["segment"],
              stop_fids=all_mainstem_fids
            )
            sm=path_summary(p)
            join_fid=int(p[-1]["fid"]) if status=="joined_existing" else None
            tributaries[code]={
              "role":b["role"],"branch":b["branch"],"mass_balance":True,
              "status":status,
              "joins_mainstem":status=="joined_existing",
              "join_mainstem_fid":join_fid,
              "path":sm,
              "snap":snapped[code],
            }

        # Collect geometries only for selected network paths.
        selected_fids=set(all_mainstem_fids)
        for x in tributaries.values():
            for fid in ((x.get("path") or {}).get("segments") or []):
                selected_fids.add(int(fid))
        feats=fetch_geometry_for_ids(session,sorted(selected_fids))

    feature_out=[]
    mainset=set(all_mainstem_fids)
    branchsets={}
    for code,x in tributaries.items():
        branchsets[code]=set(((x.get("path") or {}).get("segments") or []))
    for f in feats:
        p=dict(f["properties"]); fid=int(p["fid"])
        if fid in mainset:
            role="taquari_mainstem_model_path"
        else:
            owners=[c for c,s in branchsets.items() if fid in s]
            role="tributary_path_"+("_".join(owners) if owners else "selected")
        p["model_role"]=role
        feature_out.append({"type":"Feature","geometry":f["geometry"],"properties":p})
    for code,s in snapped.items():
        feature_out.append({
          "type":"Feature",
          "geometry":{"type":"Point","coordinates":[s["station_lon"],s["station_lat"]]},
          "properties":{"station_code":code,"name":s["station_name"],
                        "model_role":"station_anchor","snap_distance_m":s["distance_m"]},
        })
    GEO.write_text(json.dumps({
      "type":"FeatureCollection","name":"G040_whole_basin_BHO6_research_network",
      "features":feature_out
    },ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")

    payload={
      "schema_version":"g040_whole_basin_bho6_topology_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "source":{
        "provider":"ANA/SNIRH","dataset":"BHO6 trecho drenagem",
        "query":"cocursodag LIKE '786%'","network_semantics":"noorigem -> nodestino",
      },
      "snap_method":"station drainage-area similarity + projected spatial distance",
      "snapped_stations":snapped,
      "mainstem_chain":chain_codes,
      "mainstem_order_pass":order_ok,
      "mainstem_paths":chain_paths,
      "tributary_connections":tributaries,
      "gates":{
        "all_mainstem_targets_reached":order_ok,
        "carreiro_joins_mainstem":bool((tributaries.get("86500000") or {}).get("joins_mainstem")),
        "guapore_joins_mainstem":bool((tributaries.get("86595000") or {}).get("joins_mainstem")),
        "forqueta_joins_mainstem":bool((tributaries.get("86746000") or {}).get("joins_mainstem")),
        "prata_not_double_counted":(tributaries.get("86447000") or {}).get("mass_balance") is False,
      },
      "next_step":"derive incremental contributing areas between verified junctions and generate HEC-HMS branch project",
      "artifacts":{"network_geojson":str(GEO.relative_to(ROOT))},
    }
    payload["topology_pass"]=all(bool(v) for v in payload["gates"].values())
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "topology_pass":payload["topology_pass"],
      "mainstem_order_pass":order_ok,
      "gates":payload["gates"],
      "snap_distance_m":{k:v["distance_m"] for k,v in snapped.items()},
      "out":str(OUT.relative_to(ROOT)),
    },ensure_ascii=False))
    return 0 if payload["topology_pass"] else 2

if __name__=="__main__":
    raise SystemExit(main())
