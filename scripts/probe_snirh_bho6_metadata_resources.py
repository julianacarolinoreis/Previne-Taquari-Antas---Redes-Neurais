#!/usr/bin/env python3
"""Probe the official SNIRH GeoNetwork record for BHO 6.2.4 distribution resources.

This avoids guessing protected /files URLs. It tests public GeoNetwork API,
legacy metadata XML, formatter, and OGC CSW GetRecordById endpoints and extracts
candidate distribution/download/service URLs from any successful response.

Research/audit only.
"""
from __future__ import annotations

import json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/hec_hms_g040_full_basin/snirh_bho6_metadata_resource_probe_latest.json"
UUID="32e309da-a8c1-443f-90ac-0cd79ce6a33d"
BASE="https://metadados.snirh.gov.br"
UA={
 "User-Agent":"Mozilla/5.0 PREVINE-research-metadata-probe/1.0",
 "Accept":"application/json,application/xml,text/xml,text/html,*/*",
}

ENDPOINTS=[
 ("api_record",f"{BASE}/geonetwork/srv/api/records/{UUID}"),
 ("api_attachments",f"{BASE}/geonetwork/srv/api/records/{UUID}/attachments"),
 ("formatter_xml",f"{BASE}/geonetwork/srv/api/records/{UUID}/formatters/xml"),
 ("legacy_xml_metadata_get",f"{BASE}/geonetwork/srv/por/xml.metadata.get?uuid={UUID}"),
 ("csw_get_record",f"{BASE}/geonetwork/srv/por/csw?"+urlencode({
   "service":"CSW","version":"2.0.2","request":"GetRecordById",
   "id":UUID,"elementSetName":"full",
   "outputSchema":"http://www.isotc211.org/2005/gmd",
 })),
]

URL_RE=re.compile(r'https?://[^\s"<>]+',re.I)
HREF_RE=re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']',re.I)
FILE_RE=re.compile(r'[^\s"<>]+\.(?:gpkg|zip|7z|rar|shp|tif|tiff)(?:\?[^\s"<>]*)?',re.I)

def candidate_score(u:str)->int:
    s=u.lower()
    score=0
    if "area_dren" in s: score+=10
    if "bho" in s: score+=4
    if ".gpkg" in s: score+=10
    if ".zip" in s: score+=6
    if "download" in s: score+=4
    if "attachment" in s: score+=3
    if "featureserver" in s or "wfs" in s: score+=8
    if UUID in s: score+=2
    return score

def extract_urls(text:str):
    vals=set()
    for u in URL_RE.findall(text or ""):
        vals.add(u.rstrip(").,;"))
    for h in HREF_RE.findall(text or ""):
        vals.add(urljoin(BASE,h))
    for f in FILE_RE.findall(text or ""):
        if f.startswith("http"):
            vals.add(f)
        else:
            vals.add(urljoin(BASE,f))
    out=[]
    for u in vals:
        if candidate_score(u)>0:
            out.append({"url":u,"score":candidate_score(u)})
    return sorted(out,key=lambda x:(-x["score"],x["url"]))

def main():
    probes=[]
    all_candidates={}
    with requests.Session() as s:
        s.headers.update(UA)
        for name,url in ENDPOINTS:
            item={"name":name,"url":url}
            try:
                r=s.get(url,timeout=60,allow_redirects=True)
                text=r.text
                item.update({
                  "status":r.status_code,
                  "final_url":r.url,
                  "content_type":r.headers.get("Content-Type"),
                  "content_length_header":r.headers.get("Content-Length"),
                  "body_bytes":len(r.content),
                  "body_prefix":text[:500],
                  "candidates":extract_urls(text),
                })
                for c in item["candidates"]:
                    all_candidates[c["url"]]=max(c["score"],all_candidates.get(c["url"],0))
            except Exception as exc:
                item["error"]=str(exc)
            probes.append(item)

    candidates=[{"url":u,"score":sc} for u,sc in all_candidates.items()]
    candidates.sort(key=lambda x:(-x["score"],x["url"]))

    # Probe only small/metadata-like candidate URLs. Avoid downloading a national dataset.
    resource_probes=[]
    with requests.Session() as s:
        s.headers.update(UA)
        for c in candidates[:25]:
            u=c["url"]
            item={**c}
            try:
                h=s.head(u,timeout=30,allow_redirects=True)
                item.update({
                  "head_status":h.status_code,
                  "final_url":h.url,
                  "content_type":h.headers.get("Content-Type"),
                  "content_length":h.headers.get("Content-Length"),
                  "accept_ranges":h.headers.get("Accept-Ranges"),
                  "content_disposition":h.headers.get("Content-Disposition"),
                })
                # Request only first bytes; close immediately.
                g=s.get(u,headers={**UA,"Range":"bytes=0-4095"},timeout=45,stream=True,allow_redirects=True)
                first=next(g.iter_content(4096),b"")
                item.update({
                  "range_status":g.status_code,
                  "content_range":g.headers.get("Content-Range"),
                  "range_content_length":g.headers.get("Content-Length"),
                  "range_accept_ranges":g.headers.get("Accept-Ranges"),
                  "first_bytes_hex":first[:16].hex(),
                  "sqlite_header":first[:16].decode("latin1",errors="replace"),
                  "range_supported":bool(g.status_code==206 and g.headers.get("Content-Range")),
                })
                g.close()
            except Exception as exc:
                item["probe_error"]=str(exc)
            resource_probes.append(item)

    payload={
      "schema_version":"snirh_bho6_metadata_resource_probe_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "record_uuid":UUID,
      "probes":probes,
      "candidate_resources":candidates,
      "candidate_resource_probes":resource_probes,
      "policy":"metadata/resource discovery only; never download the full national dataset in this probe",
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "record_uuid":UUID,
      "endpoint_statuses":[{"name":x["name"],"status":x.get("status"),"error":x.get("error")} for x in probes],
      "candidate_resources":candidates[:15],
      "resource_probes":resource_probes[:10],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
