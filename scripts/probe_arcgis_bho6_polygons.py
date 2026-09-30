#!/usr/bin/env python3
"""Probe ArcGIS Online for a queryable BHO6 drainage-area polygon layer.

This is discovery only. A candidate is accepted only when:
- geometry is polygon;
- fields include COBACIA/COTRECHO/NUAREACONT;
- a G040 sample query succeeds;
- returned DSVERSAO is compatible with BHO v6 when present.

No BHO2017 layer is promoted as a substitute.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/hec_hms_g040_full_basin/arcgis_bho6_polygon_probe_latest.json"
SEARCH="https://www.arcgis.com/sharing/rest/search"
UA={"User-Agent":"PREVINE-G040-BHO6-polygon-probe/1.0"}

QUERIES=[
    'owner:hidrografiaana BHO',
    'owner:hidrografiaana "area de drenagem"',
    'owner:hidrografiaana "área de drenagem"',
    '"Base Hidrográfica Ottocodificada" "area de drenagem"',
]
CORE={"cobacia","cotrecho","nuareacont"}

def get_json(url, params=None, timeout=45):
    r=requests.get(url,params=params or {},headers=UA,timeout=timeout)
    r.raise_for_status()
    p=r.json()
    if isinstance(p,dict) and p.get("error"):
        raise RuntimeError(json.dumps(p["error"],ensure_ascii=False))
    return p

def sample_layer(url, fields):
    low={x.lower():x for x in fields}
    wanted=[low[x] for x in ("cobacia","cotrecho","nuareacont") if x in low]
    for extra in ("dsversao","cocursodag"):
        if extra in low:
            wanted.append(low[extra])
    where="1=1"
    if "cocursodag" in low:
        where=f"{low['cocursodag']} LIKE '786%'"
    p=get_json(url+"/query",{
        "f":"json","where":where,"outFields":",".join(wanted),
        "returnGeometry":"false","resultRecordCount":1,
    })
    rows=[x.get("attributes") or {} for x in p.get("features") or []]
    return rows[0] if rows else None

def main():
    items={}
    errors=[]
    for q in QUERIES:
        try:
            p=get_json(SEARCH,{"f":"json","q":q,"num":100})
            for x in p.get("results") or []:
                items[str(x.get("id"))]=x
        except Exception as exc:
            errors.append({"query":q,"error":str(exc)})
    candidates=[]
    for item in items.values():
        url=item.get("url")
        typ=str(item.get("type") or "")
        if not url or "Service" not in typ:
            continue
        try:
            svc=get_json(url,{"f":"json"})
        except Exception as exc:
            errors.append({"item_id":item.get("id"),"service_url":url,"error":str(exc)})
            continue
        for lyr in svc.get("layers") or []:
            lid=lyr.get("id")
            lurl=f"{url}/{lid}"
            try:
                meta=get_json(lurl,{"f":"json"})
            except Exception as exc:
                errors.append({"item_id":item.get("id"),"layer_id":lid,"error":str(exc)})
                continue
            fields=[str(f.get("name") or "") for f in meta.get("fields") or []]
            low={f.lower() for f in fields}
            geom=str(meta.get("geometryType") or "")
            title_text=" ".join([
                str(item.get("title") or ""),str(meta.get("name") or ""),
                str(item.get("description") or ""),str(meta.get("description") or ""),
            ]).lower()
            score=0
            if geom=="esriGeometryPolygon": score+=10
            score+=3*len(CORE & low)
            if "bho6" in title_text or "versão 6" in title_text or "versao 6" in title_text: score+=12
            if "2017" in title_text: score-=12
            sample=None; sample_error=None
            if geom=="esriGeometryPolygon" and CORE <= low:
                try:
                    sample=sample_layer(lurl,fields)
                    if sample: score+=8
                    ds=str((sample or {}).get(next((f for f in fields if f.lower()=="dsversao"),""),"")).lower()
                    if "06" in ds or "v_06" in ds or "6." in ds: score+=20
                    if "2017" in ds: score-=20
                except Exception as exc:
                    sample_error=str(exc)
            candidates.append({
                "score":score,
                "item_id":item.get("id"),
                "item_title":item.get("title"),
                "item_type":typ,
                "owner":item.get("owner"),
                "service_url":url,
                "layer_id":lid,
                "layer_url":lurl,
                "layer_name":meta.get("name"),
                "geometry_type":geom,
                "fields":fields,
                "sample_g040":sample,
                "sample_error":sample_error,
            })
    candidates.sort(key=lambda x:(-int(x["score"]),str(x.get("item_title")),int(x.get("layer_id") or 0)))
    accepted=[
        x for x in candidates
        if x["geometry_type"]=="esriGeometryPolygon"
        and CORE <= {f.lower() for f in x["fields"]}
        and x.get("sample_g040")
        and "2017" not in (" ".join([str(x.get("item_title")),str(x.get("layer_name")),str(x.get("sample_g040"))]).lower())
    ]
    payload={
        "schema_version":"g040_arcgis_bho6_polygon_probe_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "query_count":len(QUERIES),
        "item_count":len(items),
        "candidate_count":len(candidates),
        "accepted_candidate_count":len(accepted),
        "accepted_candidates":accepted[:20],
        "top_candidates":candidates[:30],
        "errors":errors[:100],
        "policy":"Discovery only; BHO2017 is never promoted as a BHO6 geometry substitute.",
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "items":len(items),"candidates":len(candidates),
        "accepted":len(accepted),
        "top":[{"score":x["score"],"title":x["item_title"],"layer":x["layer_name"],"url":x["layer_url"],"sample":x["sample_g040"]} for x in candidates[:10]]
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
