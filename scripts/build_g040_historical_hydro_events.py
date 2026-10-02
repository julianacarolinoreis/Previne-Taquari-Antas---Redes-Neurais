#!/usr/bin/env python3
"""Build multi-event historical hydrometric inputs for G040 HEC research.

Queries the same ANA/SGB DadosHidrometeorologicos endpoint used by PREVINE.
Stores hourly aggregated observed discharge/level at whole-basin control
stations for independent event replay and routing calibration.

No rating curves are invented. Missing stays missing. Research only.
"""
from __future__ import annotations

import json, math, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
ARCH=BASE/"whole_basin_branch_model_latest.json"
OUTDIR=BASE/"historical_hydro_events"
SUMMARY=BASE/"whole_basin_historical_hydro_events_latest.json"

BRT=timezone(timedelta(hours=-3)); UTC=timezone.utc
ANA_PRIMARY="https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA_MIRROR="https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"

EVENTS={
 "E19_MAY2023":("2023-05-05T00:00","2023-05-10T23:59"),
 "E22_SEP2023":("2023-09-01T00:00","2023-09-12T23:59"),
 "E24_NOV2023":("2023-11-16T00:00","2023-11-25T23:59"),
 "E27_MAY2024":("2024-04-28T00:00","2024-05-10T23:59"),
 "E28_JUN2024":("2024-06-15T00:00","2024-06-26T23:59"),
 "E2026_JUL":("2026-07-18T00:00","2026-07-24T23:59"),
}
FALLBACKS=[
 {"code":"86555800","label":"Rio Guaporé (Guaporé)","role":"guapore_fallback"},
 {"code":"86560000","label":"Linha Colombo","role":"guapore_fallback"},
 {"code":"86780000","label":"Barra do Fão","role":"forqueta_fallback"},
]
TIMEOUT=18

def finite(v):
    try: x=float(str(v).replace(",","."))
    except Exception: return None
    return x if math.isfinite(x) else None

def lname(tag): return tag.rsplit("}",1)[-1]

def parse_time(v):
    t=str(v or "").strip().replace("T"," ")
    for fmt in ("%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M","%d/%m/%Y %H:%M"):
        try: return datetime.strptime(t[:19],fmt).replace(tzinfo=BRT)
        except ValueError: pass
    return None

def parse_xml(raw,start_utc,end_utc):
    root=ET.fromstring(raw); roots=[root]
    if (root.text or "").strip().startswith("<"):
        try: roots.append(ET.fromstring(root.text))
        except Exception: pass
    out=[]; seen=set()
    for rt in roots:
        for node in rt.iter():
            fields={lname(ch.tag):(ch.text or "") for ch in node}
            dt=parse_time(fields.get("DataHora") or fields.get("Data_Hora"))
            if dt is None: continue
            u=dt.astimezone(UTC)
            if u<start_utc or u>end_utc: continue
            q=finite(fields.get("Vazao") or fields.get("vazao"))
            n=finite(fields.get("Nivel") or fields.get("nivel"))
            key=(u,q,n)
            if key in seen: continue
            seen.add(key); out.append((u,q,n))
    return sorted(out)

def fetch(code,start_local,end_local):
    start_utc=start_local.astimezone(UTC); end_utc=end_local.astimezone(UTC)
    params=urllib.parse.urlencode({
      "codEstacao":code,
      "dataInicio":start_local.strftime("%d/%m/%Y"),
      "dataFim":end_local.strftime("%d/%m/%Y"),
    })
    errs=[]
    for base in (ANA_PRIMARY,ANA_MIRROR):
        try:
            req=urllib.request.Request(f"{base}?{params}",headers={"User-Agent":"PREVINE-G040-historical/1.0","Accept":"text/xml,application/xml,*/*;q=0.8"})
            with urllib.request.urlopen(req,timeout=TIMEOUT) as resp: raw=resp.read()
            rows=parse_xml(raw,start_utc,end_utc)
            if rows: return {"ok":True,"endpoint":base,"rows":rows}
            errs.append(f"{base}:empty")
        except Exception as exc: errs.append(f"{base}:{exc}")
    return {"ok":False,"rows":[],"error":" | ".join(errs[-2:])}

def hourly(rows):
    b=defaultdict(lambda:{"q":[],"n":[]})
    for t,q,n in rows:
        h=t.replace(minute=0,second=0,microsecond=0)
        if q is not None and 0<=q<=60000: b[h]["q"].append(q)
        if n is not None: b[h]["n"].append(n)
    out=[]
    for h in sorted(b):
        qs=b[h]["q"]; ns=b[h]["n"]
        out.append({
          "time_utc":h.isoformat().replace("+00:00","Z"),
          "flow_m3s":None if not qs else round(sum(qs)/len(qs),5),
          "level_source_unit":None if not ns else round(sum(ns)/len(ns),5),
          "flow_samples":len(qs),"level_samples":len(ns),
        })
    return out

def station_specs():
    j=json.loads(ARCH.read_text(encoding="utf-8"))
    specs=[]
    for b in j["major_branch_controls"]:
        specs.append({"code":str(b["code"]),"label":b["label"],"role":b["role"],"group":"branch","mass_balance":b.get("mass_balance")})
    for m in j["mainstem_checkpoints"]:
        specs.append({"code":str(m["code"]),"label":m["label"],"role":"checkpoint","group":"mainstem","order":m["order"]})
    specs.extend(FALLBACKS)
    seen=set(); out=[]
    for s in specs:
        if s["code"] in seen: continue
        seen.add(s["code"]); out.append(s)
    return out

def main():
    OUTDIR.mkdir(parents=True,exist_ok=True)
    specs=station_specs()
    jobs=[]
    for eid,(a,b) in EVENTS.items():
        start=datetime.fromisoformat(a).replace(tzinfo=BRT)
        end=datetime.fromisoformat(b).replace(tzinfo=BRT)
        for s in specs: jobs.append((eid,start,end,s))

    results={}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs={ex.submit(fetch,s["code"],start,end):(eid,start,end,s) for eid,start,end,s in jobs}
        for fut in as_completed(futs):
            eid,start,end,s=futs[fut]
            try: f=fut.result()
            except Exception as exc: f={"ok":False,"rows":[],"error":str(exc)}
            hs=hourly(f.get("rows") or [])
            qvals=[x["flow_m3s"] for x in hs if x["flow_m3s"] is not None]
            nvals=[x["level_source_unit"] for x in hs if x["level_source_unit"] is not None]
            item={**s,
              "fetch_ok":bool(f.get("ok")),
              "endpoint":f.get("endpoint"),
              "error":f.get("error"),
              "hour_count":len(hs),
              "flow_hour_count":len(qvals),
              "level_hour_count":len(nvals),
              "flow_peak_m3s":max(qvals) if qvals else None,
              "flow_min_m3s":min(qvals) if qvals else None,
              "series":hs,
            }
            results.setdefault(eid,[]).append(item)

    events=[]
    for eid,(a,b) in EVENTS.items():
        stations=sorted(results.get(eid,[]),key=lambda x:(x.get("group",""),x["code"]))
        payload={
          "schema_version":"g040_historical_hydro_event_v1",
          "event_id":eid,
          "window_local":{"start":a,"end":b,"timezone":"America/Sao_Paulo"},
          "research_only":True,
          "source":"ANA/SGB DadosHidrometeorologicos",
          "stations":stations,
        }
        path=OUTDIR/f"{eid}.json"
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        events.append({
          "event_id":eid,"path":str(path.relative_to(ROOT)),
          "station_count":len(stations),
          "stations_with_flow":sum(x["flow_hour_count"]>0 for x in stations),
          "stations_with_level":sum(x["level_hour_count"]>0 for x in stations),
          "flow_hours_total":sum(x["flow_hour_count"] for x in stations),
        })

    summary={
      "schema_version":"g040_historical_hydro_events_manifest_v1",
      "generated_at_utc":datetime.now(UTC).isoformat().replace("+00:00","Z"),
      "research_only":True,
      "events":events,
      "policy":{
        "hourly_discharge":"mean of valid sub-hourly ANA Vazao samples inside UTC hour",
        "hourly_level":"mean of valid sub-hourly source-level samples inside UTC hour",
        "missing":"preserved as missing",
        "rating_curve":"none invented",
        "use":"routing/state calibration and independent event replay only after data QC",
      },
    }
    SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))
    return 0

if __name__=="__main__": raise SystemExit(main())
