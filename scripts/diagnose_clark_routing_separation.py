#!/usr/bin/env python3
"""Diagnose Clark-vs-routing separation for Muçum corridor.

Runs three controlled experiments:
- E27 (Apr-May 2024)
- E28 (Jun 2024)
- current observed event 26-28 Sep 2026 (rising-limb only)

Historical cases use the auditable Python twin of the same method family
Initial+Constant + Clark + Recession + Muskingum. This is a diagnostic to decide
whether a better channel profile/routing representation is worth promoting; it
does NOT modify the operational HEC-HMS forecast.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_hec_twin_stz_mucum_calibrate as twin
from hec_twin_nested_v17 import NestedParams, ZoneParams

OUT = ROOT / "assets/data/estudo_bacia_taquari_antas/clark_routing_separation"
OUT.mkdir(parents=True, exist_ok=True)
MODEL = ROOT / "assets/data/estudo_bacia_taquari_antas/modelo_mucum_eventwise_v1_fechado_latest.json"
LIVE = ROOT / "assets/data/estudo_bacia_taquari_antas/mucum_observed_multistation_latest.json"

AREAS = {
    "SB_PRATA_7868": 3775.99,
    "SB_ANTAS_RESIDUAL": 9142.666,
    "SB_CARREIRO_7866": 2564.19,
    "SB_STZ_RESIDUAL": 292.34,
    "SB_INC_MUCUM": 190.021,
}
SUBBASINS = list(AREAS)
K_ALL = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.5)
K_CONSTRAINED = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.5)
X_ALL = (0.10, 0.20, 0.30)


def loadj(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dynamic_event_rows(station: str, event_id: str):
    aliases = {station}
    if station == "2851072":
        aliases.add("02851072")
    candidates = []
    for alias in aliases:
        candidates.extend(ROOT.glob(f"assets/data/**/telemetry_{alias}_{event_id}.xml"))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return []
    # prefer the largest raw file; audit copies can coexist.
    p = max(candidates, key=lambda q: q.stat().st_size)
    return twin.parse_telemetry(p)


# Make the historical forcing builder independent of an old fixed raw-data directory.
twin.load_event_series = dynamic_event_rows


def zparams(d):
    return ZoneParams(
        float(d["initial_loss"]), float(d["constant_loss"]), float(d["tc"]),
        float(d["storage"]), float(d["recession"]), float(d["initial_flow_ratio"])
    )


def nparams(d):
    return NestedParams(
        up=zparams(d["upstream"]), dn=zparams(d["downstream"]),
        k1=float(d["k1"]), k2=float(d["k2"]), k3=float(d["k3"]), x=float(d.get("x", 0.2))
    )


def metrics_for(precip, hours, flow, p, core_offset=0, core_hours=None):
    if core_hours is None:
        core_hours = hours
    net = twin.run_network(precip, AREAS, p, include_mucum_increment=True)
    sim = net["at_mucum"][core_offset:core_offset+len(core_hours)]
    paired = [i for i,h in enumerate(core_hours) if h in flow]
    obs = [float(flow[core_hours[i]]) for i in paired]
    ss = [float(sim[i]) for i in paired]
    m = twin.metrics(obs, ss)
    m["research_score"] = twin.research_score(m)
    return m, net


def best_routing(precip, hours, flow, base, *, core_offset=0, core_hours=None, constrained=False, current=False):
    """Multi-start coordinate search of Muskingum routing.

    Much faster than a full k1×k2×k3 Cartesian grid while still testing each
    allowed K and x repeatedly from several starting points.
    """
    kvals = K_CONSTRAINED if constrained else K_ALL
    def evaluate(p):
        m, net = metrics_for(precip, hours, flow, p, core_offset, core_hours)
        score = current_score(m, hours, flow, net["at_mucum"]) if current else m["research_score"]
        return {"params":p.to_dict(),"metrics":m,"objective":score}
    starts=[
        NestedParams(up=base.up,dn=base.dn,k1=base.k1,k2=base.k2,k3=base.k3,x=base.x),
        NestedParams(up=base.up,dn=base.dn,k1=1.0,k2=1.0,k3=1.0,x=0.2),
        NestedParams(up=base.up,dn=base.dn,k1=2.0,k2=2.0,k3=2.0,x=0.2),
        NestedParams(up=base.up,dn=base.dn,k1=4.0,k2=4.0,k3=3.0,x=0.3),
    ]
    if constrained:
        starts=[NestedParams(up=s.up,dn=s.dn,k1=max(1.0,s.k1),k2=max(1.0,s.k2),k3=max(1.0,s.k3),x=s.x) for s in starts]
    global_best=None
    for seed in starts:
        p=seed
        best=evaluate(p)
        for _ in range(3):
            changed=False
            for field in ("k1","k2","k3"):
                local=best
                for v in kvals:
                    kw=dict(k1=p.k1,k2=p.k2,k3=p.k3,x=p.x); kw[field]=v
                    cand=NestedParams(up=base.up,dn=base.dn,**kw)
                    row=evaluate(cand)
                    if row["objective"]>local["objective"]:
                        local=row
                if local["objective"]>best["objective"]:
                    best=local; p=nparams(local["params"]); changed=True
            local=best
            for x in X_ALL:
                cand=NestedParams(up=base.up,dn=base.dn,k1=p.k1,k2=p.k2,k3=p.k3,x=x)
                row=evaluate(cand)
                if row["objective"]>local["objective"]:
                    local=row
            if local["objective"]>best["objective"]:
                best=local; p=nparams(local["params"]); changed=True
            if not changed:
                break
        if global_best is None or best["objective"]>global_best["objective"]:
            global_best=best
    return global_best

def candidates_around(v, deltas, lower):
    return sorted({round(max(lower, float(v)+d), 3) for d in deltas})


def best_clark(precip, hours, flow, base, *, core_offset=0, core_hours=None, current=False):
    """Coordinate search of Clark Tc/storage with losses/baseflow fixed."""
    def evaluate(p):
        m, net=metrics_for(precip,hours,flow,p,core_offset,core_hours)
        score=current_score(m,hours,flow,net["at_mucum"]) if current else m["research_score"]
        return {"params":p.to_dict(),"metrics":m,"objective":score}
    p=base
    best=evaluate(p)
    for _ in range(3):
        changed=False
        for zone,field,deltas,lower in (
            ("up","tc",(-10,-5,0,5,10),1.0),
            ("up","storage",(-20,-10,0,10,20),1.0),
            ("dn","tc",(-10,-5,0,5,10),1.0),
            ("dn","storage",(-20,-10,0,10,20),1.0),
        ):
            z=p.up if zone=="up" else p.dn
            current_v=float(getattr(z,field))
            vals=candidates_around(current_v,deltas,lower)
            local=best
            for v in vals:
                up=deepcopy(p.up); dn=deepcopy(p.dn)
                target=up if zone=="up" else dn
                setattr(target,field,v)
                cand=NestedParams(up=up,dn=dn,k1=p.k1,k2=p.k2,k3=p.k3,x=p.x)
                row=evaluate(cand)
                if row["objective"]>local["objective"]:
                    local=row
            if local["objective"]>best["objective"]:
                best=local; p=nparams(local["params"]); changed=True
        if not changed:
            break
    return best

def terminal_metrics(hours, flow, sim):
    pairs = [(i, flow[h]) for i,h in enumerate(hours) if h in flow and i < len(sim)]
    if not pairs:
        return {}
    i, obs = pairs[-1]
    err = float(sim[i]) - float(obs)
    obs3 = [(j, flow[hours[j]]) for j in range(max(0,i-3), i+1) if hours[j] in flow]
    trend_obs = None
    trend_sim = None
    if len(obs3) >= 2:
        j0,o0 = obs3[0]; j1,o1 = obs3[-1]
        dh = max(1, j1-j0)
        trend_obs = (float(o1)-float(o0))/dh
        trend_sim = (float(sim[j1])-float(sim[j0]))/dh
    return {"end_obs_m3s": float(obs), "end_sim_m3s": float(sim[i]), "end_error_m3s": err,
            "trend_obs_m3s_h": trend_obs, "trend_sim_m3s_h": trend_sim}


def current_score(m, hours, flow, sim):
    t = terminal_metrics(hours, flow, sim)
    nse = float(m["nse"])
    end_obs = max(abs(t.get("end_obs_m3s",1.0)),1.0)
    end_pen = abs(t.get("end_error_m3s",0.0))/end_obs
    trend_obs = t.get("trend_obs_m3s_h")
    trend_sim = t.get("trend_sim_m3s_h")
    trend_pen = 0.0
    if trend_obs is not None and trend_sim is not None:
        trend_pen = abs(trend_sim-trend_obs)/max(abs(trend_obs),100.0)
    return nse - 0.65*end_pen - 0.20*trend_pen



def parse_rain_csv_time(row):
    try:
        y=int(float(row.get("ANO") or 0)); m=int(float(row.get("MES") or 0)); d=int(float(row.get("DIA") or 0))
        raw=str(row.get("HORA") or "0").strip()
        if ":" in raw:
            hh=int(raw.split(":")[0])
        else:
            n=int(float(raw))
            hh=n//100 if n>=100 else n
        return datetime(y,m,d,hh).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        code=str(row.get("COD_SEQUENCIAL") or "").strip()
        if len(code)>=10 and code[:10].isdigit():
            return datetime.strptime(code[:10],"%Y%m%d%H").strftime("%Y-%m-%d %H:%M:%S")
    return None


def fcsv(v):
    s=str(v or "").strip().replace(",",".")
    if not s or s.lower() in {"nan","none","null","na"}:
        return None
    try:
        x=float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def historical_csv_forcing(event_id, librow):
    """Fallback using the operational audited rain CSV with hourly masks.

    No missing value is converted to zero. At each hour, another observed gauge
    is used only when it actually has a value. If all available gauges are
    missing in the same hour, the experiment is blocked.
    """
    rain_path=ROOT/"assets/data/chuvas_horarias.csv"
    series_path=ROOT/f"assets/data/estudo_bacia_taquari_antas/hec_twin_stz_mucum_v1/mucum_{event_id}_best_series.csv"
    if not rain_path.exists() or not series_path.exists():
        return None, {"runnable":False,"blocked_reason":"fallback rain/series file missing"}, [], {}, 0, []
    start_s,end_s=twin.EVENTS[event_id]
    core_start=datetime.strptime(start_s,"%Y-%m-%d %H:%M:%S")
    core_end=datetime.strptime(end_s,"%Y-%m-%d %H:%M:%S")
    pad=int(librow.get("pad_hours_selected") or 0)
    from datetime import timedelta
    sim_start=core_start-timedelta(hours=pad)
    hours=[]
    t=sim_start
    while t<=core_end:
        hours.append(t.strftime("%Y-%m-%d %H:%M:%S")); t+=timedelta(hours=1)
    wanted=set(hours)
    rr={}
    with rain_path.open(newline="",encoding="utf-8",errors="replace") as fh:
        for row in csv.DictReader(fh):
            ts=parse_rain_csv_time(row)
            if ts not in wanted: continue
            rr[ts]={
                "86472000":fcsv(row.get("chuva_86472000")),
                "86472600":fcsv(row.get("chuva_86472600")),
                "2851072":fcsv(row.get("chuva_02851072")),
            }
    precip={sb:[] for sb in SUBBASINS}
    missing=[]
    used={"up_mean_86472000_2851072":0,"carreiro_2851072":0,"stz_86472600":0,"mucum_proxy":0}
    for h in hours:
        r=rr.get(h,{})
        up=[v for v in (r.get("86472000"),r.get("2851072")) if v is not None]
        if not up:
            missing.append(h); continue
        upv=sum(up)/len(up); used["up_mean_86472000_2851072"]+=1
        cv=r.get("2851072")
        if cv is None: cv=r.get("86472000")
        if cv is None: missing.append(h); continue
        used["carreiro_2851072"]+=1
        sv=r.get("86472600")
        if sv is None:
            vals=[v for v in (r.get("86472000"),r.get("2851072")) if v is not None]
            sv=sum(vals)/len(vals) if vals else None
        if sv is None: missing.append(h); continue
        used["stz_86472600"]+=1
        mv=r.get("86472600")
        if mv is None: mv=r.get("86472000")
        if mv is None: mv=r.get("2851072")
        if mv is None: missing.append(h); continue
        used["mucum_proxy"]+=1
        precip["SB_PRATA_7868"].append(upv)
        precip["SB_ANTAS_RESIDUAL"].append(upv)
        precip["SB_CARREIRO_7866"].append(cv)
        precip["SB_STZ_RESIDUAL"].append(sv)
        precip["SB_INC_MUCUM"].append(mv)
    if missing:
        return None, {"runnable":False,"blocked_reason":f"{len(missing)} hours with no observed fallback rain","missing_hours":missing[:20]}, hours, {}, pad, []
    flow={}
    with series_path.open(newline="",encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ts=str(row.get("timestamp") or "")
            val=fcsv(row.get("obs_m3s"))
            if val is not None:
                flow[ts]=val
    core_hours=[]
    t=core_start
    while t<=core_end:
        core_hours.append(t.strftime("%Y-%m-%d %H:%M:%S")); t+=timedelta(hours=1)
    meta={"runnable":True,"source":"assets/data/chuvas_horarias.csv masked hourly fallback","no_missing_as_zero":True,"used_counts":used,"pad_h":pad}
    return precip,meta,hours,flow,pad,core_hours


def historical_case(event_id, librow):
    pad = int(librow.get("pad_hours_selected") or 0)
    precip, meta, hours, flow, flow_antas, core_offset, core_hours = twin.prepare_event_forcing(event_id, SUBBASINS, pad)
    if precip is None:
        precip, meta2, hours, flow, core_offset, core_hours = historical_csv_forcing(event_id, librow)
        meta = {"strict_raw": meta, "masked_csv_fallback": meta2}
        if precip is None:
            return {"event_id": event_id, "status": "blocked_no_precip", "rain_meta": meta}
    base = nparams(librow["params"])
    bm, _ = metrics_for(precip, hours, flow, base, core_offset, core_hours)
    route_free = best_routing(precip, hours, flow, base, core_offset=core_offset, core_hours=core_hours, constrained=False)
    route_k1 = best_routing(precip, hours, flow, base, core_offset=core_offset, core_hours=core_hours, constrained=True)
    clark = best_clark(precip, hours, flow, base, core_offset=core_offset, core_hours=core_hours)
    # Sequential separation: routing then Clark, and Clark then routing.
    p_r = nparams(route_k1["params"])
    rc = best_clark(precip, hours, flow, p_r, core_offset=core_offset, core_hours=core_hours)
    p_c = nparams(clark["params"])
    cr = best_routing(precip, hours, flow, p_c, core_offset=core_offset, core_hours=core_hours, constrained=True)
    joint = rc if rc["objective"] >= cr["objective"] else cr
    return {
        "event_id": event_id, "status": "ok", "pad_h": pad,
        "baseline": {"params": base.to_dict(), "metrics": bm, "objective": bm["research_score"]},
        "routing_only_unconstrained": route_free,
        "routing_only_k_ge_1h": route_k1,
        "clark_only": clark,
        "sequential_clark_routing_k_ge_1h": joint,
        "rain_meta": meta,
    }


def live_station_series(pkg, code, field):
    st = next((x for x in pkg["flow"]["stations"] if str(x.get("code")) == code), None)
    if not st:
        return {}
    return {str(r["time_local"]).replace("T"," ")+":00" if len(str(r["time_local"]))==16 else str(r["time_local"]).replace("T"," "):
            float(r[field]) for r in st.get("series",[]) if r.get(field) is not None}


def current_forcing(pkg):
    stations = {}
    for s in pkg["rain"]["stations"]:
        code = str(s.get("code"))
        stations[code] = {str(r["time_local"]).replace("T"," ")+":00" if len(str(r["time_local"]))==16 else str(r["time_local"]).replace("T"," "):
                          float(r["mm"]) for r in s.get("series",[]) if r.get("mm") is not None}
    areal = {str(r["time_local"]).replace("T"," ")+":00" if len(str(r["time_local"]))==16 else str(r["time_local"]).replace("T"," "):
             float(r.get("basin_mean_mm") or 0.0) for r in pkg["rain"]["hourly_areal"]}
    flow = live_station_series(pkg, "86510000", "flow_m3s")
    antas = live_station_series(pkg, "86472000", "flow_m3s")
    hours = sorted(flow.keys())
    prefs = {
        "SB_PRATA_7868": ["86472000","2851072","86507000"],
        "SB_ANTAS_RESIDUAL": ["86472000","2851072","86507000"],
        "SB_CARREIRO_7866": ["86507000","86472000","86510000","2851072"],
        "SB_STZ_RESIDUAL": ["86472600","86472000","86510000","2851072"],
        "SB_INC_MUCUM": ["86510000","86472600","86472000"],
    }
    precip = {}
    source_audit = {}
    for sb, ps in prefs.items():
        vals=[]; used={}
        for h in hours:
            hh=[]
            for code in ps:
                if h in stations.get(code,{}):
                    hh.append(stations[code][h]); used[code]=used.get(code,0)+1
            vals.append(sum(hh)/len(hh) if hh else areal.get(h,0.0))
        precip[sb]=vals
        source_audit[sb]=used
    return precip, hours, flow, antas, source_audit


def scale_state(base, scale):
    up = deepcopy(base.up); dn = deepcopy(base.dn)
    up.initial_flow_ratio *= scale; dn.initial_flow_ratio *= scale
    return NestedParams(up=up,dn=dn,k1=base.k1,k2=base.k2,k3=base.k3,x=base.x)


def live_case(librow):
    pkg=loadj(LIVE)
    precip,hours,flow,flow_antas,source_audit=current_forcing(pkg)
    seed=nparams(librow["params"])
    # State initialization only: choose one multiplier from a coarse grid using
    # the pre-rise first 12 hours, holding all runoff/routing params fixed.
    best_state=None
    first=hours[:12]
    for scale in (1,2,4,8,12,16,24,32,40,48,64):
        p=scale_state(seed,scale)
        m,net=metrics_for(precip,hours,flow,p)
        pairs=[i for i,h in enumerate(first) if h in flow]
        rm=math.sqrt(sum((net["at_mucum"][i]-flow[first[i]])**2 for i in range(len(first)) if first[i] in flow)/max(1,len(pairs)))
        if best_state is None or rm<best_state[0]:
            best_state=(rm,p)
    base=best_state[1]
    bm,net=metrics_for(precip,hours,flow,base)
    bterm=terminal_metrics(hours,flow,net["at_mucum"])
    route_free=best_routing(precip,hours,flow,base,current=True,constrained=False)
    route_k1=best_routing(precip,hours,flow,base,current=True,constrained=True)
    clark=best_clark(precip,hours,flow,base,current=True)
    p_r=nparams(route_k1["params"])
    rc=best_clark(precip,hours,flow,p_r,current=True)
    p_c=nparams(clark["params"])
    cr=best_routing(precip,hours,flow,p_c,current=True,constrained=True)
    joint=rc if rc["objective"]>=cr["objective"] else cr
    for row in (route_free,route_k1,clark,joint):
        p=nparams(row["params"])
        mm,nn=metrics_for(precip,hours,flow,p)
        row["metrics"]=mm
        row["terminal"]=terminal_metrics(hours,flow,nn["at_mucum"])
    # observed timing diagnostics from levels, no flow conversion at STZ.
    timing={}
    for code in ("86472000","86472600","86510000"):
        st=next((x for x in pkg["flow"]["stations"] if str(x.get("code"))==code),None)
        vals=[(r["time_local"],float(r["level"])) for r in (st or {}).get("series",[]) if r.get("level") is not None]
        rises=[]
        for a,b in zip(vals,vals[1:]):
            try:
                t0=datetime.fromisoformat(a[0]); t1=datetime.fromisoformat(b[0])
                dh=(t1-t0).total_seconds()/3600
                if dh>0: rises.append(((b[1]-a[1])/dh,b[0]))
            except Exception: pass
        timing[code]={
            "last": vals[-1] if vals else None,
            "max_hourly_rise": max(rises,key=lambda x:x[0]) if rises else None,
            "observed_peak_so_far": max(vals,key=lambda x:x[1]) if vals else None,
            "censored_rising_limb": True,
        }
    return {
        "event_id":"LIVE_20260926_28","status":"ok_rising_limb_censored",
        "hours":len(hours),"start":hours[0],"end":hours[-1],
        "state_scale_for_initial_flow_ratio":best_state[1].up.initial_flow_ratio/seed.up.initial_flow_ratio,
        "state_pre_rise_rmse_m3s":best_state[0],
        "baseline":{"params":base.to_dict(),"metrics":bm,"terminal":bterm,"objective":current_score(bm,hours,flow,net["at_mucum"])},
        "routing_only_unconstrained":route_free,
        "routing_only_k_ge_1h":route_k1,
        "clark_only":clark,
        "sequential_clark_routing_k_ge_1h":joint,
        "rain_source_audit":source_audit,
        "observed_timing":timing,
        "note":"current event is still rising/censored; peak timing is not used in the current objective",
    }


def summarize(case):
    if not case.get("status","").startswith("ok"):
        return {"event_id":case.get("event_id"),"status":case.get("status")}
    out={"event_id":case["event_id"],"status":case["status"]}
    for key in ("baseline","routing_only_unconstrained","routing_only_k_ge_1h","clark_only","sequential_clark_routing_k_ge_1h"):
        r=case[key]; m=r["metrics"]
        out[key]={
            "nse":round(float(m["nse"]),4),
            "rmse_m3s":round(float(m["rmse_m3s"]),1),
            "peak_lag_h":None if case["event_id"].startswith("LIVE") else round(float(m["peak_lag_hours"]),2),
            "peak_error_pct":None if case["event_id"].startswith("LIVE") else round(100*float(m["peak_relative_error"]),2),
            "objective":round(float(r["objective"]),4),
            "k1":r["params"]["k1"],"k2":r["params"]["k2"],"k3":r["params"]["k3"],"x":r["params"]["x"],
            "up_tc":r["params"]["upstream"]["tc"],"up_storage":r["params"]["upstream"]["storage"],
            "dn_tc":r["params"]["downstream"]["tc"],"dn_storage":r["params"]["downstream"]["storage"],
        }
        if "terminal" in r:
            out[key]["end_error_m3s"]=round(float(r["terminal"]["end_error_m3s"]),1)
            out[key]["trend_obs_m3s_h"]=None if r["terminal"]["trend_obs_m3s_h"] is None else round(float(r["terminal"]["trend_obs_m3s_h"]),1)
            out[key]["trend_sim_m3s_h"]=None if r["terminal"]["trend_sim_m3s_h"] is None else round(float(r["terminal"]["trend_sim_m3s_h"]),1)
    return out


def main():
    model=loadj(MODEL)
    rows={r["event_id"]:r for r in model["params_library_eventwise"]}
    cases=[historical_case("E27",rows["E27"]),historical_case("E28",rows["E28"]),live_case(rows["E28"])]
    report={
        "schema_version":"clark_routing_separation_v1",
        "generated_at_utc":datetime.utcnow().isoformat()+"Z",
        "purpose":"diagnosticar se o erro temporal melhora ao separar resposta Clark de routing do canal; sem alterar modelo operacional",
        "engine":"Python audit twin: Initial+Constant + Clark + Recession + Muskingum",
        "operational_model_modified":False,
        "routing_search":{"unconstrained_k_h":K_ALL,"diagnostic_constrained_k_h":K_CONSTRAINED,"x":X_ALL},
        "cases":cases,
        "summary":[summarize(c) for c in cases],
        "interpretation_rules":[
            "Ganho que só aparece com K<1 h é tratado como sinal de compensação entre Clark e routing, não como parâmetro físico validado.",
            "K>=1 h é apenas uma guarda diagnóstica; valor físico final depende de seções, declividade hidráulica e/ou tempo de onda observado.",
            "Evento atual é censurado porque a onda ainda estava subindo no último dado; não se usa horário de pico futuro como verdade observada.",
            "Nenhum resultado deste experimento é promovido automaticamente ao HEC operacional."
        ]
    }
    (OUT/"clark_routing_separation_latest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (OUT/"summary.csv").open("w",newline="",encoding="utf-8") as fh:
        fields=["event_id","variant","nse","rmse_m3s","peak_lag_h","peak_error_pct","objective","k1","k2","k3","x","up_tc","up_storage","dn_tc","dn_storage","end_error_m3s","trend_obs_m3s_h","trend_sim_m3s_h"]
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for s in report["summary"]:
            for v in ("baseline","routing_only_unconstrained","routing_only_k_ge_1h","clark_only","sequential_clark_routing_k_ge_1h"):
                if v in s:
                    w.writerow({"event_id":s["event_id"],"variant":v,**s[v]})
    print(json.dumps(report["summary"],ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
