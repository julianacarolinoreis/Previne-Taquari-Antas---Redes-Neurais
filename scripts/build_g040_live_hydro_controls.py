#!/usr/bin/env python3
"""Build a compact live hydrometric snapshot for G040 HEC control stations.

Uses the same ANA/SGB DadosHidrometeorologicos endpoint already used by PREVINE
live robots. Preserves raw timestamps and keeps level and discharge distinct.
No rating-curve conversion is invented here.

Research only; not an official warning system.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
ARCH=BASE/"whole_basin_branch_model_latest.json"
OUT=BASE/"whole_basin_live_hydro_controls_latest.json"

BRT=timezone(timedelta(hours=-3))
UTC=timezone.utc
ANA_PRIMARY="https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA_MIRROR="https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"
FRESH_MINUTES=180
TIMEOUT=12
RETRIES=2

# Upstream alternatives are diagnostics until topology/area is reconciled.
# They are never silently substituted for the preferred boundary.
FALLBACK_CANDIDATES = [
    {"code":"86555800","label":"Rio Guaporé (Guaporé)","branch_role":"guapore","drainage_area_km2":2042.0},
    {"code":"86560000","label":"Linha Colombo","branch_role":"guapore","drainage_area_km2":2030.0},
    {"code":"86780000","label":"Barra do Fão","branch_role":"forqueta","drainage_area_km2":2077.0},
]

def finite(v):
    try:
        x=float(str(v).replace(",","."))
    except (TypeError,ValueError):
        return None
    return x if math.isfinite(x) else None

def lname(tag):
    return tag.rsplit("}",1)[-1]

def parse_time(v):
    t=str(v or "").strip().replace("T"," ")
    for fmt in ("%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M","%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(t[:19],fmt).replace(tzinfo=BRT)
        except ValueError:
            pass
    return None

def parse_xml(raw,start_utc,end_utc):
    root=ET.fromstring(raw)
    roots=[root]
    if (root.text or "").strip().startswith("<"):
        try: roots.append(ET.fromstring(root.text))
        except Exception: pass
    out=[]; seen=set()
    for rt in roots:
        for node in rt.iter():
            fields={lname(ch.tag):(ch.text or "") for ch in node}
            stamp=fields.get("DataHora") or fields.get("Data_Hora")
            dt=parse_time(stamp)
            if dt is None: continue
            u=dt.astimezone(UTC)
            if u<start_utc or u>end_utc: continue
            q=finite(fields.get("Vazao") or fields.get("vazao"))
            n=finite(fields.get("Nivel") or fields.get("nivel"))
            key=(u,q,n)
            if key in seen: continue
            seen.add(key)
            out.append({"time_utc":u,"flow_m3s":q,"level_source_unit":n})
    out.sort(key=lambda x:x["time_utc"])
    return out

def fetch_station(code,start_utc,end_utc):
    start_local=start_utc.astimezone(BRT)
    end_local=end_utc.astimezone(BRT)
    params=urllib.parse.urlencode({
      "codEstacao":code,
      "dataInicio":start_local.strftime("%d/%m/%Y"),
      "dataFim":end_local.strftime("%d/%m/%Y"),
    })
    errors=[]
    for attempt in range(RETRIES):
        for base in (ANA_PRIMARY,ANA_MIRROR):
            try:
                req=urllib.request.Request(
                  f"{base}?{params}",
                  headers={"User-Agent":"PREVINE-G040-hydro-controls/1.0","Accept":"text/xml,application/xml,*/*;q=0.8"}
                )
                with urllib.request.urlopen(req,timeout=TIMEOUT) as resp:
                    raw=resp.read()
                rows=parse_xml(raw,start_utc,end_utc)
                if rows:
                    return {"ok":True,"source":"ANA/SGB DadosHidrometeorologicos","endpoint":base,"rows":rows}
                errors.append(f"{base}: empty")
            except urllib.error.HTTPError as exc:
                errors.append(f"{base}: HTTP {exc.code}")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
        if attempt<RETRIES-1:
            time.sleep(2)
    return {"ok":False,"source":"ANA/SGB DadosHidrometeorologicos","rows":[],"error":" | ".join(errors[-4:])}

def summarize(rows,now):
    qrows=[r for r in rows if r["flow_m3s"] is not None and 0<=r["flow_m3s"]<=60000]
    nrows=[r for r in rows if r["level_source_unit"] is not None]
    q=qrows[-1] if qrows else None
    n=nrows[-1] if nrows else None
    last=max([x["time_utc"] for x in (qrows+nrows)],default=None)
    age=(now-last).total_seconds()/60 if last else None
    # Preserve the complete 72 h query window for HEC warm-up/hindcast.
    # The previous 96-sample cap kept only ~24 h at 15-minute telemetry.
    recent=[]
    for r in rows:
        recent.append({
          "time_utc":r["time_utc"].isoformat().replace("+00:00","Z"),
          "flow_m3s":r["flow_m3s"],
          "level_source_unit":r["level_source_unit"],
        })
    return {
      "last_observation_utc":last.isoformat().replace("+00:00","Z") if last else None,
      "age_minutes":round(age,1) if age is not None else None,
      "latest_flow_m3s":q["flow_m3s"] if q else None,
      "latest_flow_at_utc":q["time_utc"].isoformat().replace("+00:00","Z") if q else None,
      "latest_level_source_unit":n["level_source_unit"] if n else None,
      "latest_level_at_utc":n["time_utc"].isoformat().replace("+00:00","Z") if n else None,
      "fresh_for_state":bool(last and age<=FRESH_MINUTES),
      "fresh_flow_boundary":bool(q and (now-q["time_utc"]).total_seconds()/60<=FRESH_MINUTES),
      "recent_rows":recent,
      "retained_series_hours":72,
    }

def main():
    arch=json.loads(ARCH.read_text(encoding="utf-8"))
    specs=[]
    for b in arch["major_branch_controls"]:
        specs.append({
          "code":b["code"],"label":b["label"],"group":"branch",
          "role":b["role"],"mass_balance":b.get("mass_balance")
        })
    for m in arch["mainstem_checkpoints"]:
        specs.append({
          "code":m["code"],"label":m["label"],"group":"mainstem",
          "role":"checkpoint","order":m["order"]
        })

    now=datetime.now(UTC)
    start=now-timedelta(hours=72)
    controls=[]
    for spec in specs:
        f=fetch_station(str(spec["code"]),start,now)
        s=summarize(f.get("rows") or [],now)
        controls.append({
          **spec,
          "source":f.get("source"),
          "endpoint":f.get("endpoint"),
          "fetch_ok":bool(f.get("ok")),
          "fetch_error":f.get("error"),
          **s,
        })

    fallback_controls=[]
    for spec in FALLBACK_CANDIDATES:
        f=fetch_station(str(spec["code"]),start,now)
        s=summarize(f.get("rows") or [],now)
        fallback_controls.append({
          **spec,
          "group":"fallback_candidate",
          "source":f.get("source"),
          "endpoint":f.get("endpoint"),
          "fetch_ok":bool(f.get("ok")),
          "fetch_error":f.get("error"),
          **s,
        })

    boundaries=[x for x in controls if x.get("group")=="branch" and x.get("mass_balance")]
    payload={
      "schema_version":"g040_whole_basin_live_hydro_controls_v1",
      "generated_at_utc":now.isoformat().replace("+00:00","Z"),
      "research_only":True,
      "source":"ANA/SGB DadosHidrometeorologicos",
      "window_hours":72,
      "freshness_gate_minutes":FRESH_MINUTES,
      "controls":controls,
      "fallback_candidates":fallback_controls,
      "summary":{
        "control_count":len(controls),
        "fetch_ok_count":sum(x["fetch_ok"] for x in controls),
        "fresh_state_count":sum(x["fresh_for_state"] for x in controls),
        "mass_balance_boundary_count":len(boundaries),
        "fresh_flow_boundary_count":sum(x["fresh_flow_boundary"] for x in boundaries),
        "fresh_fallback_candidate_count":sum(x["fresh_flow_boundary"] for x in fallback_controls),
      },
      "policy":{
        "flow":"use directly only when ANA provides Vazao and freshness gate passes",
        "level":"retained in source units; no cross-station datum equivalence assumed",
        "missing":"missing stays missing; no interpolation or zero fill",
        "rating_curve":"no rating curve is invented in this collector",
        "fallback":"candidate stations are diagnostics only until BHO topology and incremental area are explicitly recalculated; no silent substitution",
      },
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload["summary"],ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
