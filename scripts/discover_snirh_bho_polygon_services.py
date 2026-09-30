#!/usr/bin/env python3
"""Discover public SNIRH polygon services potentially compatible with BHO6.

Scans ArcGIS Server service folders, then inspects only BHO/Otto/Hidrografia-
related MapServer/FeatureServer services. Candidate layers must be polygons and
expose hydrologic identifiers such as COBACIA/COTRECHO/NUAREACONT.

No candidate is promoted automatically. The report records service/layer URL,
field names, extent, description and any version-like metadata for audit.
"""
from __future__ import annotations
import json, os, re, requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/hec_hms_g040_full_basin/snirh_bho_polygon_service_discovery_latest.json"
ROOT_URL="https://portal1.snirh.gov.br/server/rest/services"
UA={"User-Agent":"PREVINE-SNIRH-BHO-discovery/1.0"}

KEYWORDS=("bho","otto","hidrograf","area_dren","aredren","drenagem")
FIELD_KEYS={"cobacia","cotrecho","nuareacont"}
BHO6_METADATA_UUID="32e309da-a8c1-443f-90ac-0cd79ce6a33d"
BHO6_FILE_BASE=f"https://metadados.snirh.gov.br/files/{BHO6_METADATA_UUID}"
BHO6_AREA_GPKG_CANDIDATES=[
    f"{BHO6_FILE_BASE}/geoft_bho_area_drenagem.gpkg",
    f"{BHO6_FILE_BASE}/GEOFT_BHO_AREA_DRENAGEM.gpkg",
]

def get(url,params=None,timeout=45):
    r=requests.get(url,params=params or {"f":"pjson"},headers=UA,timeout=timeout)
    r.raise_for_status()
    p=r.json()
    if isinstance(p,dict) and p.get("error"):
        raise RuntimeError(json.dumps(p["error"],ensure_ascii=False))
    return p

def relevant(name):
    s=str(name or "").lower()
    return any(k in s for k in KEYWORDS)

def probe_remote_gpkg(url):
    out={"url":url}
    try:
        h=requests.head(url,headers=UA,timeout=30,allow_redirects=True)
        out["head_status"]=h.status_code
        out["content_length"]=h.headers.get("Content-Length")
        out["accept_ranges"]=h.headers.get("Accept-Ranges")
        out["content_type"]=h.headers.get("Content-Type")
        out["final_url"]=h.url
    except Exception as exc:
        out["head_error"]=str(exc)
    try:
        g=requests.get(url,headers={**UA,"Range":"bytes=0-4095"},timeout=45,allow_redirects=True,stream=True)
        raw=next(g.iter_content(chunk_size=4096),b"")
        out["range_status"]=g.status_code
        out["content_range"]=g.headers.get("Content-Range")
        out["range_content_length"]=g.headers.get("Content-Length")
        out["sqlite_header"]=raw[:16].decode("latin1",errors="replace")
        out["first_bytes_hex"]=raw[:16].hex()
        out["range_supported"]=bool(g.status_code==206 and str(g.headers.get("Content-Range") or "").lower().startswith("bytes "))
        g.close()
    except Exception as exc:
        out["range_error"]=str(exc)
        out["range_supported"]=False
    return out

def list_services(folder=""):
    url=ROOT_URL + ("/"+folder if folder else "")
    return get(url,{"f":"pjson"})

def layer_metadata(service_name,service_type):
    return get(f"{ROOT_URL}/{service_name}/{service_type}",{"f":"pjson"})

def inspect_layer(service_name,service_type,layer_id):
    url=f"{ROOT_URL}/{service_name}/{service_type}/{layer_id}"
    p=get(url,{"f":"pjson"})
    fields=[str(x.get("name") or "") for x in p.get("fields") or []]
    low={x.lower() for x in fields}
    return {
      "url":url,
      "name":p.get("name"),
      "geometry_type":p.get("geometryType"),
      "fields":fields,
      "has_core_fields":sorted(FIELD_KEYS & low),
      "description":p.get("description"),
      "copyright":p.get("copyrightText"),
      "extent":p.get("extent"),
      "service_item_id":p.get("serviceItemId"),
      "max_record_count":p.get("maxRecordCount"),
    }

def main():
    fast_mode=os.environ.get("SNIRH_DISCOVERY_FAST","0").strip().lower() in {"1","true","yes","on"}
    services=[]
    errors=[]
    folders=[]
    if not fast_mode:
        root=list_services()
        folders=[""]+[str(x) for x in root.get("folders") or []]
        for folder in folders:
            try:
                p=list_services(folder)
            except Exception as exc:
                errors.append({"folder":folder,"error":str(exc)})
                continue
            for s in p.get("services") or []:
                name=str(s.get("name") or "")
                typ=str(s.get("type") or "")
                if typ not in {"FeatureServer","MapServer"}: continue
                if relevant(name):
                    services.append({"name":name,"type":typ})
        uniq={(x["name"],x["type"]):x for x in services}
        services=list(uniq.values())

    candidates=[]
    inspected=[]
    for s in services:
        try:
            meta=layer_metadata(s["name"],s["type"])
            layers=meta.get("layers") or []
            entry={"service":s,"layer_count":len(layers),"description":meta.get("serviceDescription")}
            inspected.append(entry)
            for lyr in layers:
                try:
                    lm=inspect_layer(s["name"],s["type"],lyr.get("id"))
                except Exception as exc:
                    errors.append({"service":s["name"],"layer":lyr.get("id"),"error":str(exc)})
                    continue
                geom=str(lm.get("geometry_type") or "")
                low_fields={x.lower() for x in lm["fields"]}
                score=0
                if geom=="esriGeometryPolygon": score+=5
                score+=sum(2 for f in FIELD_KEYS if f in low_fields)
                name_text=(str(lm.get("name") or "")+" "+str(lm.get("description") or "")+" "+s["name"]).lower()
                if "bho6" in name_text: score+=8
                if "2022" in name_text: score+=4
                if "2017" in name_text: score-=2
                if geom=="esriGeometryPolygon" and (FIELD_KEYS & low_fields):
                    candidates.append({**lm,"service_name":s["name"],"service_type":s["type"],"score":score})
        except Exception as exc:
            errors.append({"service":s["name"],"error":str(exc)})

    candidates.sort(key=lambda x:(-int(x["score"]),str(x["service_name"]),str(x["name"])))
    gpkg_probes=[probe_remote_gpkg(u) for u in BHO6_AREA_GPKG_CANDIDATES]

    payload={
      "schema_version":"snirh_bho_polygon_service_discovery_v2",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "catalog_root":ROOT_URL,
      "fast_mode":fast_mode,
      "folders_scanned":len(folders),
      "relevant_services_inspected":len(services),
      "candidate_count":len(candidates),
      "candidates":candidates,
      "bho6_area_gpkg_probes":gpkg_probes,
      "errors":errors[:100],
      "policy":"discovery only; a polygon service must be version/crosswalk validated against BHO6 before use",
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "folders_scanned":payload["folders_scanned"],
      "services":payload["relevant_services_inspected"],
      "candidate_count":payload["candidate_count"],
      "gpkg_probes":gpkg_probes,
      "top":[{"service":x["service_name"],"layer":x["name"],"score":x["score"],"url":x["url"]} for x in candidates[:10]]
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
