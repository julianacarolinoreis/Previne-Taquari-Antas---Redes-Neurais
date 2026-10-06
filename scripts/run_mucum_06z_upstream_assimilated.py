#!/usr/bin/env python3
from __future__ import annotations

import json, sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

from run_hec_twin_mucum_forward_5d import load_areas, params_from_library_row, mucum_curve_segments, q_to_stage_cm
from run_hec_twin_stz_mucum_calibrate import run_network, muskingum

OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
FORCING=OUT/"hec_twin_ifs_spatial_forcing_5d_latest.json"
OBS=OUT/"mucum_observed_multistation_latest.json"
LIB=OUT/"modelo_mucum_eventwise_v1_fechado_latest.json"
OUT_JSON=OUT/"mucum_06z_upstream_assimilated_latest.json"
OUT_CSV=OUT/"mucum_06z_upstream_assimilated_series.csv"

MUCUM="86510000"
ANTAS="86472000"
CARREIRO="86500000"


def pdt(s):
    return datetime.fromisoformat(str(s))


def station(obs, code):
    for s in obs["flow"]["stations"]:
        if str(s.get("code"))==code:
            return s
    raise RuntimeError(f"station {code} missing")


def latest_q_at_or_extrapolated(st, target_local: datetime):
    rows=[]
    for r in st.get("series") or []:
        q=r.get("flow_m3s")
        if q is None:
            continue
        t=pdt(r["time_local"])
        if t<=target_local:
            rows.append((t,float(q)))
    if not rows:
        raise RuntimeError(f"no Q for {st.get('code')}")
    rows.sort()
    t1,q1=rows[-1]
    if t1==target_local or len(rows)<2:
        return q1, {"method":"observed_exact_or_latest","source_time":t1.isoformat(timespec="minutes")}
    t0,q0=rows[-2]
    dt=(t1-t0).total_seconds()/3600
    ahead=(target_local-t1).total_seconds()/3600
    slope=(q1-q0)/dt if dt>0 else 0.0
    # Extrapolation is limited to one hour and 15% of latest Q.
    ahead=max(0.0,min(ahead,1.0))
    delta=max(-0.15*q1,min(0.15*q1,slope*ahead))
    q=q1+delta
    return q, {
        "method":"one_hour_linear_extrapolation_from_last_two_observations",
        "source_time":t1.isoformat(timespec="minutes"),
        "previous_time":t0.isoformat(timespec="minutes"),
        "slope_m3s_h":round(slope,3),
        "ahead_h":round(ahead,3),
    }


def solve_up_ratio(params, precip, areas, q_target, idx=0):
    net=run_network(precip,areas,params,include_mucum_increment=True)
    zero=replace(params, up=replace(params.up,initial_flow_ratio=0.0))
    net0=run_network(precip,areas,zero,include_mucum_increment=True)
    qb=float(net["at_antas"][idx]); qz=float(net0["at_antas"][idx])
    base=qb-qz
    if base<=1e-6: raise RuntimeError("up baseflow component near zero")
    f=max((q_target-qz)/base,0.0)
    return replace(params,up=replace(params.up,initial_flow_ratio=params.up.initial_flow_ratio*f)), {
        "q_before":qb,"q_direct":qz,"target":q_target,"factor":f
    }


def carreiro_branch(net,params,idx=0):
    routed=muskingum(net["at_antas"],params.k1,params.x)
    return float(net["at_carreiro"][idx])-float(routed[idx])


def solve_dn_ratio(params,precip,areas,q_target,idx=0):
    net=run_network(precip,areas,params,include_mucum_increment=True)
    qb=carreiro_branch(net,params,idx)
    zero=replace(params,dn=replace(params.dn,initial_flow_ratio=0.0))
    net0=run_network(precip,areas,zero,include_mucum_increment=True)
    qz=carreiro_branch(net0,zero,idx)
    base=qb-qz
    if base<=1e-6: raise RuntimeError("dn baseflow component near zero")
    f=max((q_target-qz)/base,0.0)
    return replace(params,dn=replace(params.dn,initial_flow_ratio=params.dn.initial_flow_ratio*f)), {
        "q_before":qb,"q_direct":qz,"target":q_target,"factor":f
    }


def main():
    forcing=json.loads(FORCING.read_text(encoding="utf-8"))
    obs=json.loads(OBS.read_text(encoding="utf-8"))
    lib=json.loads(LIB.read_text(encoding="utf-8"))

    times=list(forcing["times_utc"])
    precip=forcing["precip_mm_by_subbasin"]
    areas=load_areas()

    sm=station(obs,MUCUM)
    mrows=[r for r in sm.get("series") or [] if r.get("level") is not None]
    mrows.sort(key=lambda r:r["time_local"])
    cur=mrows[-1]
    target_local=pdt(cur["time_local"])
    stage_now=float(cur["level"])
    q_now=float(cur["flow_m3s"]) if cur.get("flow_m3s") is not None else None

    # A assimilacao so e cientificamente valida quando forcing e observacao
    # partem do mesmo instante. Desalinhamento de fonte nao deve derrubar os
    # demais produtos HEC da rodada: publica-se um diagnostico explicitamente
    # bloqueado, sem reutilizar silenciosamente a assimilacao anterior.
    forcing_start=datetime.fromisoformat(times[0].replace("Z","+00:00")).replace(tzinfo=None)-timedelta(hours=3)
    if forcing_start!=target_local:
        gap_h=(forcing_start-target_local).total_seconds()/3600.0
        blocked={
          "schema_version":"mucum_06z_upstream_assimilated_v1",
          "status":"blocked_time_mismatch",
          "publishable":False,
          "model":"nested HEC-method twin E28 with observed branch-state assimilation",
          "current":{
            "time_local":cur["time_local"],"stage_cm":stage_now,"q_m3s":q_now
          },
          "forcing_start_local":forcing_start.isoformat(timespec="minutes"),
          "time_mismatch_hours":round(gap_h,3),
          "reason":"forcing e observacao atual nao compartilham o mesmo t0; assimilacao nao executada",
          "audit":{
            "upstream_observed_assimilation":False,
            "visual_only_shift":False,
            "blocked_by_temporal_alignment_gate":True
          }
        }
        OUT_JSON.write_text(json.dumps(blocked,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        with OUT_CSV.open("w",encoding="utf-8") as f:
            f.write("time_utc,n_mucum_anchored_cm,q_mucum_m3s,q_antas_m3s,q_carreiro_confluence_m3s\n")
        print(json.dumps(blocked,ensure_ascii=False))
        return

    q_antas,meta_antas=latest_q_at_or_extrapolated(station(obs,ANTAS),target_local)
    q_carr,meta_carr=latest_q_at_or_extrapolated(station(obs,CARREIRO),target_local)

    row=next(r for r in lib["params_library_eventwise"] if r["event_id"]=="E28")
    params=params_from_library_row(row)
    params,up_meta=solve_up_ratio(params,precip,areas,q_antas,0)
    params,dn_meta=solve_dn_ratio(params,precip,areas,q_carr,0)

    net=run_network(precip,areas,params,include_mucum_increment=True)
    segs=mucum_curve_segments()
    stages=[q_to_stage_cm(float(q),segs).get("stage_cm") for q in net["at_mucum"]]
    if stages[0] is None:
        raise RuntimeError("invalid Muçum stage at t0")
    n0=float(stages[0])
    anchored=[stage_now+(float(n)-n0) if n is not None else None for n in stages]

    n24=min(25,len(times))
    future=[x for x in anchored[:n24] if x is not None]
    peak=max(future) if future else stage_now
    peak_i=max(range(n24),key=lambda i: anchored[i] if anchored[i] is not None else -1e9)
    min_i=min(range(n24),key=lambda i: anchored[i] if anchored[i] is not None else 1e9)

    payload={
      "schema_version":"mucum_06z_upstream_assimilated_v1",
      "ecmwf_cycle_time_utc":"2026-09-29T06:00:00Z",
      "model":"nested HEC-method twin E28 with observed branch-state assimilation",
      "current":{
        "time_local":cur["time_local"],"stage_cm":stage_now,"q_m3s":q_now
      },
      "boundary_state":{
        "antas_86472000_q_m3s":round(q_antas,3),"antas_meta":meta_antas,
        "carreiro_86500000_q_m3s":round(q_carr,3),"carreiro_meta":meta_carr,
        "up_ratio_factor":up_meta,"dn_ratio_factor":dn_meta
      },
      "forecast":{
        "peak_24h_cm":round(float(peak),2),
        "peak_24h_time_utc":times[peak_i],
        "min_24h_cm":round(float(anchored[min_i]),2),
        "min_24h_time_utc":times[min_i],
        "rise_24h_cm":round(float(peak-stage_now),2)
      },
      "parameters":params.to_dict(),
      "series":{
        "time_utc":times,
        "q_mucum_m3s":[round(float(x),3) for x in net["at_mucum"]],
        "q_antas_m3s":[round(float(x),3) for x in net["at_antas"]],
        "q_carreiro_confluence_m3s":[round(float(x),3) for x in net["at_carreiro"]],
        "n_mucum_raw_cm":[None if x is None else round(float(x),2) for x in stages],
        "n_mucum_anchored_cm":[None if x is None else round(float(x),2) for x in anchored]
      },
      "audit":{
        "anchoring":"observed Muçum stage at exact t0 + modeled delta after branch-state assimilation",
        "structural_event":"E28",
        "upstream_observed_assimilation":True,
        "visual_only_shift":False
      }
    }
    OUT_JSON.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with OUT_CSV.open("w",encoding="utf-8") as f:
        f.write("time_utc,n_mucum_anchored_cm,q_mucum_m3s,q_antas_m3s,q_carreiro_confluence_m3s\n")
        for i,t in enumerate(times):
            f.write(f"{t},{anchored[i]:.2f},{net['at_mucum'][i]:.3f},{net['at_antas'][i]:.3f},{net['at_carreiro'][i]:.3f}\n")
    print(json.dumps({
      "current":payload["current"],
      "boundary_state":payload["boundary_state"],
      "forecast":payload["forecast"]
    },ensure_ascii=False))


if __name__=="__main__":
    main()
