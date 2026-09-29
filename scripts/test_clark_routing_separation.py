#!/usr/bin/env python3
"""Clark × routing separation experiment for Muçum.

Runs:
- E27 and E28 with the auditable HEC-method Python twin and fresh ANA telemetry.
- Current 26/09/2026 event with the real HEC-HMS 4.13 two-zone pilot, then an
  explicit Muskingum post-routing sensitivity layer for diagnosis.

Research only. Does not modify/promote operational parameters.
"""

from __future__ import annotations
import csv, json, math, os, re, subprocess, sys, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hec_twin_nested_v17 import NestedParams, ZoneParams
from run_hec_twin_stz_mucum_calibrate import run_network, metrics, research_score, muskingum

OUT = ROOT / "assets/data/hec_hms_integrated_taquari_antas/clark_routing_separation_20260928"
MODEL = ROOT / "assets/data/estudo_bacia_taquari_antas/modelo_mucum_eventwise_v1_fechado_latest.json"
STRUCT = ROOT / "assets/data/estudo_bacia_taquari_antas/estrutura_stz_mucum_latest.json"
LIVE_OBS = ROOT / "assets/data/estudo_bacia_taquari_antas/mucum_observed_multistation_latest.json"
LIVE_CAL = ROOT / "assets/data/estudo_bacia_taquari_antas/hec_hms_live_event_calibration_latest.json"
LIVE_RUNTIME = ROOT / "assets/data/estudo_bacia_taquari_antas/hec_hms_spatial_forecast_mucum"
LIVE_BASIN = LIVE_RUNTIME / "project/bacia_spatial_live.basin"
LIVE_SCRIPT = LIVE_RUNTIME / "project/run_forecast.script"
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA2 = "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"

EVENTS = {
    "E27": ("2024-04-29 16:00:00", "2024-05-09 20:00:00"),
    "E28": ("2024-06-16 10:00:00", "2024-06-25 02:00:00"),
}
RAIN_PREF = {
    "SB_PRATA_7868": ["86472000", "2851072", "86507000"],
    "SB_ANTAS_RESIDUAL": ["86472000", "2851072", "86507000"],
    "SB_CARREIRO_7866": ["86507000", "86472000", "86510000", "2851072"],
    "SB_STZ_RESIDUAL": ["86472600", "86472000", "86510000", "2851072"],
    "SB_INC_MUCUM": ["86510000", "86472600", "86472000"],
}
STATIONS = ("86472000","86472600","86507000","86510000","2851072")
SBS = tuple(RAIN_PREF)


def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def ts(s): return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
def hours(a,b):
    out=[]; t=a
    while t<=b: out.append(t.strftime("%Y-%m-%d %H:%M:%S")); t+=timedelta(hours=1)
    return out
def num(v):
    try: return float(str(v).replace(",","."))
    except: return None
def lname(t): return t.rsplit("}",1)[-1]


def fetch_ana(code, start, end):
    q=urllib.parse.urlencode({"codEstacao":code,"dataInicio":start.strftime("%d/%m/%Y"),"dataFim":end.strftime("%d/%m/%Y")})
    errs=[]
    for base in (ANA,ANA2):
        try:
            req=urllib.request.Request(base+"?"+q,headers={"User-Agent":"previne-routing-separation/1.0"})
            with urllib.request.urlopen(req,timeout=45) as r: raw=r.read()
            root=ET.fromstring(raw); roots=[root]
            if (root.text or "").strip().startswith("<"):
                try: roots.append(ET.fromstring(root.text))
                except: pass
            rows=[]; seen=set()
            for rt in roots:
                for node in rt.iter():
                    f={lname(c.tag):(c.text or "") for c in node}
                    stamp=f.get("DataHora") or f.get("Data_Hora")
                    if not stamp: continue
                    d=None
                    for fmt in ("%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M"):
                        try: d=datetime.strptime(stamp[:19].replace("T"," "),fmt); break
                        except: pass
                    if d is None or d<start or d>end: continue
                    key=(d,f.get("Chuva"),f.get("Vazao"),f.get("Nivel"))
                    if key in seen: continue
                    seen.add(key)
                    rows.append({"dt":d,"rain":num(f.get("Chuva")),"flow":num(f.get("Vazao")),"level":num(f.get("Nivel"))})
            if rows: return rows
            errs.append(base+":empty")
        except Exception as e: errs.append(base+":"+str(e))
    raise RuntimeError(code+" ANA failed: "+" | ".join(errs))


def hourly(rows, field, reduce="mean"):
    b={}
    for r in rows:
        v=r.get(field)
        if v is None: continue
        h=r["dt"].replace(minute=0,second=0,microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        b.setdefault(h,[]).append(float(v))
    return {h:(sum(vs) if reduce=="sum" else sum(vs)/len(vs)) for h,vs in b.items()}


def hist_forcing(event, pad_h):
    a,b=map(ts,EVENTS[event]); start=a-timedelta(hours=pad_h); hs=hours(start,b); core=hours(a,b)
    raw={s:fetch_ana(s,start,b) for s in STATIONS}
    rain={s:hourly(raw[s],"rain","sum") for s in STATIONS}
    precip={}; src={}
    for sb,prefs in RAIN_PREF.items():
        complete=[]
        for s in prefs:
            vals=[rain[s].get(h) for h in hs]
            if all(v is not None for v in vals):
                arr=[float(v) for v in vals]
                complete.append((s,arr,sum(arr),sum(arr[pad_h:])))
        if not complete: raise RuntimeError(f"{event}: no complete rain for {sb}")
        chosen=complete[0]
        wetter=max(complete,key=lambda z:z[3])
        if wetter[0]!=chosen[0] and chosen[3] < .2*wetter[3]: chosen=wetter
        if sb in ("SB_PRATA_7868","SB_ANTAS_RESIDUAL") and len(complete)>=2:
            arr=[sum(z[1][i] for z in complete)/len(complete) for i in range(len(hs))]
            chosen=("+".join(z[0] for z in complete),arr,sum(arr),sum(arr[pad_h:]))
        precip[sb]=chosen[1]; src[sb]=chosen[0]
    qm=hourly(raw["86510000"],"flow","mean")
    return precip,hs,core,pad_h,qm,src


def get_areas():
    st = load(STRUCT)
    elems = ((st.get("models") or {}).get("mucum") or {}).get("elements") or []
    areas = {
        e["id"]: float(e["area_km2"])
        for e in elems
        if isinstance(e, dict) and e.get("type") == "subbasin" and e.get("area_km2") is not None
    }
    required = {"SB_PRATA_7868", "SB_ANTAS_RESIDUAL", "SB_CARREIRO_7866", "SB_STZ_RESIDUAL", "SB_INC_MUCUM"}
    if not required.issubset(areas):
        raise RuntimeError("estrutura_stz_mucum sem todas as áreas de sub-bacia: " + str(sorted(required - set(areas))))
    return areas


def p_from_record(rec):
    u=rec["params"]["upstream"]; d=rec["params"]["downstream"]
    return NestedParams(ZoneParams(**u),ZoneParams(**d),float(rec["params"]["k1"]),float(rec["params"]["k2"]),float(rec["params"]["k3"]),float(rec["params"].get("x",.2)))


def score_hist(precip,areas,p,core,pad,qobs):
    sim=run_network(precip,areas,p,include_mucum_increment=True)["at_mucum"][pad:pad+len(core)]
    idx=[i for i,h in enumerate(core) if h in qobs]
    o=[qobs[core[i]] for i in idx]; s=[sim[i] for i in idx]
    m=metrics(o,s); m["research_score"]=research_score(m); return m


def hist_event(event,areas,rec):
    pad=int(rec.get("pad_hours_selected") or 0)
    precip,hs,core,pad,qobs,src=hist_forcing(event,pad)
    base=p_from_record(rec); bm=score_hist(precip,areas,base,core,pad,qobs)
    kvals=sorted(set([.25,.5,1.,1.25,2.,2.5,4.,6.,base.k1,base.k2,base.k3]))
    rrows=[]
    for k1 in kvals:
      for k2 in kvals:
       for k3 in kvals:
        for x in (.1,.2,.3):
         p=NestedParams(base.up,base.dn,k1,k2,k3,x)
         m=score_hist(precip,areas,p,core,pad,qobs)
         rrows.append({"mode":"routing_only","k1":k1,"k2":k2,"k3":k3,"x":x,**m})
    best_r=max(rrows,key=lambda z:z["research_score"])

    pairs=[(.5,.5),(.75,.75),(1,1),(1.25,1.25),(1.5,1.5),(.5,1),(1,.5),(.75,1),(1,.75),(1,1.25),(1.25,1)]
    crows=[]
    for fu_t,fu_s in pairs:
      for fd_t,fd_s in pairs:
        up=ZoneParams(base.up.initial_loss,base.up.constant_loss,max(.25,base.up.tc*fu_t),max(.25,base.up.storage*fu_s),base.up.recession,base.up.initial_flow_ratio)
        dn=ZoneParams(base.dn.initial_loss,base.dn.constant_loss,max(.25,base.dn.tc*fd_t),max(.25,base.dn.storage*fd_s),base.dn.recession,base.dn.initial_flow_ratio)
        p=NestedParams(up,dn,base.k1,base.k2,base.k3,base.x)
        m=score_hist(precip,areas,p,core,pad,qobs)
        crows.append({"mode":"clark_only","up_tc":up.tc,"up_storage":up.storage,"dn_tc":dn.tc,"dn_storage":dn.storage,**m})
    best_c=max(crows,key=lambda z:z["research_score"])

    # Joint small polish around the best independent candidates.
    top_r=sorted(rrows,key=lambda z:z["research_score"],reverse=True)[:8]
    top_c=sorted(crows,key=lambda z:z["research_score"],reverse=True)[:8]
    jrows=[]
    for rr in top_r:
      for cc in top_c:
        up=ZoneParams(base.up.initial_loss,base.up.constant_loss,cc["up_tc"],cc["up_storage"],base.up.recession,base.up.initial_flow_ratio)
        dn=ZoneParams(base.dn.initial_loss,base.dn.constant_loss,cc["dn_tc"],cc["dn_storage"],base.dn.recession,base.dn.initial_flow_ratio)
        p=NestedParams(up,dn,rr["k1"],rr["k2"],rr["k3"],rr["x"])
        m=score_hist(precip,areas,p,core,pad,qobs)
        jrows.append({"mode":"joint","up_tc":up.tc,"up_storage":up.storage,"dn_tc":dn.tc,"dn_storage":dn.storage,"k1":rr["k1"],"k2":rr["k2"],"k3":rr["k3"],"x":rr["x"],**m})
    best_j=max(jrows,key=lambda z:z["research_score"])
    return {"event":event,"rain_sources":src,"baseline":{"params":base.to_dict(),**bm},"best_routing_only":best_r,"best_clark_only":best_c,"best_joint":best_j,"candidate_counts":{"routing":len(rrows),"clark":len(crows),"joint":len(jrows)}}, rrows+crows+jrows


def live_obs_map():
    o=load(LIVE_OBS); arr=o["flow"]["stations"]
    if isinstance(arr,dict): arr=list(arr.values())
    s=next(x for x in arr if str(x.get("code"))=="86510000")
    m={}
    for r in s["series"]:
        d=datetime.fromisoformat(r["time_local"]).replace(tzinfo=timezone(timedelta(hours=-3))).astimezone(timezone.utc)
        if r.get("flow_m3s") is not None: m[d.strftime("%Y-%m-%dT%H:00:00Z")]=float(r["flow_m3s"])
    return m


def read_live_q():
    inp=load(LIVE_RUNTIME/"forecast_input.json")
    times=inp["times_utc"]
    rows=[]
    with (LIVE_RUNTIME/"hec_output_values.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["element"]=="Saida_LIVE": rows.append((int(float(r["time_value"])),float(r["q_m3s"])))
    rows=sorted(rows); q=[v for _,v in rows]
    n=min(len(times),len(q))
    return times[:n],q[:n]


def live_metrics(times,q,obs):
    paired=[(obs[t],q[i]) for i,t in enumerate(times) if t in obs]
    o=[a for a,b in paired]; s=[b for a,b in paired]
    m=metrics(o,s)
    if not o: return {**m,"current_q_error_m3s":None,"trend_error_m3s_h":None,"live_score":-999}
    last_err=s[-1]-o[-1]
    otr=o[-1]-o[-2] if len(o)>1 else 0; strend=s[-1]-s[-2] if len(s)>1 else 0
    trerr=strend-otr
    peak=max(o) or 1.0
    score=m["nse"]-.5*(m["rmse_m3s"]/peak)-.3*(abs(last_err)/peak)-.2*(abs(trerr)/(abs(otr)+100))
    return {**m,"current_q_error_m3s":last_err,"observed_last_trend_m3s_h":otr,"model_last_trend_m3s_h":strend,"trend_error_m3s_h":trerr,"live_score":score}


def frozen_hec_clark_run(hec_sh, tc_h, storage_h, base_basin_text):
    """Run the committed/frozen HEC forcing while changing only Clark timing."""
    text = re.sub(
        r"(?m)^(\s*Time of Concentration:\s*)[-+0-9.eE]+\s*$",
        lambda m: m.group(1) + f"{float(tc_h):.6f}",
        base_basin_text,
    )
    text = re.sub(
        r"(?m)^(\s*Storage Coefficient:\s*)[-+0-9.eE]+\s*$",
        lambda m: m.group(1) + f"{float(storage_h):.6f}",
        text,
    )
    LIVE_BASIN.write_text(text, encoding="utf-8")
    out_csv = LIVE_RUNTIME / "hec_output_values.csv"
    if out_csv.exists():
        out_csv.unlink()
    subprocess.run(
        [hec_sh, "-s", str(LIVE_SCRIPT)],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    return read_live_q()


def live_event(hec_sh):
    # Freeze the exact HEC project/forcing committed at workflow checkout.
    # This avoids mixing a newer ANA observation with an older IFS first hour
    # while the live robot is updating concurrently.
    base_text = LIVE_BASIN.read_text(encoding="utf-8")
    # HEC basin files may use CRLF. Permit trailing whitespace/CR explicitly.
    tc_vals = [float(x) for x in re.findall(r"(?m)^\s*Time of Concentration:\s*([-+0-9.eE]+)\s*$", base_text)]
    st_vals = [float(x) for x in re.findall(r"(?m)^\s*Storage Coefficient:\s*([-+0-9.eE]+)\s*$", base_text)]
    if not tc_vals or not st_vals:
        raise RuntimeError("Clark parameters not found in frozen live basin")
    baseline_tc = tc_vals[0]
    baseline_storage = st_vals[0]

    obs = live_obs_map()
    timing = [(5,5),(8,8),(10,10),(12,12),(15,15),(20,15),(20,20),(25,20),(25,25),(15,20),(10,15),(15,10),(baseline_tc,baseline_storage)]
    seen=set()
    timing=[x for x in timing if not (x in seen or seen.add(x))]
    rows=[]
    try:
        for tc,st in timing:
            times,q=frozen_hec_clark_run(hec_sh,tc,st,base_text)
            m0=live_metrics(times,q,obs)
            rows.append({"mode":"clark_only","tc_h":tc,"storage_h":st,"routing_k_h":0.0,"routing_x":0.0,**m0})
            for k in (.25,.5,1.,2.,3.,4.,6.):
                for x in (.1,.2,.3):
                    qr=muskingum(q,k,x)
                    mm=live_metrics(times,qr,obs)
                    rows.append({"mode":"clark_plus_postrouting","tc_h":tc,"storage_h":st,"routing_k_h":k,"routing_x":x,**mm})
    finally:
        LIVE_BASIN.write_text(base_text, encoding="utf-8")
        # Restore the frozen baseline HEC output in the ephemeral runner.
        try:
            frozen_hec_clark_run(hec_sh,baseline_tc,baseline_storage,base_text)
        finally:
            LIVE_BASIN.write_text(base_text, encoding="utf-8")

    baseline = next(
        r for r in rows
        if r["routing_k_h"]==0 and r["tc_h"]==baseline_tc and r["storage_h"]==baseline_storage
    )
    best_c=max((r for r in rows if r["routing_k_h"]==0),key=lambda z:z["live_score"])
    best_j=max(rows,key=lambda z:z["live_score"])
    return {
        "event":"CURRENT_2026_09_26",
        "engine":"HEC-HMS 4.13 frozen committed two-zone forcing; Muskingum is diagnostic post-routing after outlet, not promoted reach",
        "frozen_baseline_clark":{"tc_h":baseline_tc,"storage_h":baseline_storage},
        "baseline_selected":baseline,
        "best_clark_only":best_c,
        "best_clark_plus_postrouting":best_j,
        "candidate_count":len(rows),
        "note":"Observed window is still rising; no completed-peak lag is used in the live score. Frozen checkout prevents concurrent ANA/IFS timestamp mixing."
    }, rows


def main():
    if len(sys.argv)<2: raise SystemExit("usage: script /path/to/hec-hms.sh")
    hec_sh=sys.argv[1]
    OUT.mkdir(parents=True,exist_ok=True)
    areas=get_areas()
    model=load(MODEL)
    recs={r["event_id"]:r for r in model["params_library_eventwise"]}
    hist=[]; allrows=[]
    for e in ("E27","E28"):
        rep,rows=hist_event(e,areas,recs[e]); hist.append(rep); allrows += [{"event":e,**r} for r in rows]
    live,lrows=live_event(hec_sh); allrows += [{"event":"CURRENT_2026_09_26",**r} for r in lrows]
    report={
      "schema_version":"clark_routing_separation_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "purpose":"separate rainfall-runoff timing (Clark Tc/Storage) from channel propagation (Muskingum) without changing operational model",
      "historical_engine":"auditable Python twin of Initial+Constant/Clark/Recession/Muskingum, fresh ANA event telemetry",
      "historical":hist,
      "current":live,
      "operational_changes":False,
      "interpretation":["Historical E27/E28 results use the audit twin because exact archived HEC-HMS network projects are not committed.","Current event Clark candidates are actual HEC-HMS 4.13 runs; the added routing is a diagnostic post-routing sensitivity, not an HEC reach promotion.","No routing parameter from this experiment is automatically operational."]
    }
    (OUT/"clark_routing_separation_latest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fields=sorted({k for r in allrows for k in r})
    with (OUT/"clark_routing_candidates.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(allrows)
    print(json.dumps(report,ensure_ascii=False))
    return 0

if __name__=="__main__": raise SystemExit(main())
