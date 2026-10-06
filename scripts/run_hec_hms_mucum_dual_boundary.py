#!/usr/bin/env python3
"""Muçum HEC-HMS forecast with two observed upstream discharge boundaries.

Operational research logic:
- 86472000 Linha José Júlio is a native HEC Source/Flow Gage using observed Q history.
- 86500000 Passo Carreiro is a second native HEC Source/Flow Gage using observed Q history.
- Future LJJ shape uses the current-cycle operational HEC increment, anchored to the last observed LJJ Q.
- Future Carreiro shape uses the E28 calibrated branch response to spatial ECMWF/IFS, anchored to observed Carreiro Q.
- The Passo Carreiro observation covers 1,820 km²; the ~744 km² downstream Carreiro increment, plus STZ and Muçum residual areas, remain rainfall-runoff subbasins.
- Routing uses the E28 eventwise values (K1=2.5 h, K2=2.5 h, K3=1 h, x=0.2).
- Muçum observed stage/Q is validation only: no future peak is forced toward the RNAs.

Research only; not an official alert.
"""
from __future__ import annotations
import csv, json, math, os, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

from build_hec_hms_spatial_forecast_mucum import BRT, fmt_hec_date, fmt_hec_time, dpart
from run_hec_twin_mucum_forward_5d import q_to_stage_cm, mucum_curve_segments, load_areas, params_from_library_row
from run_hec_twin_stz_mucum_calibrate import run_network, muskingum
from run_mucum_06z_upstream_assimilated import solve_dn_ratio
from hec_twin_nested_v17 import NestedParams, ZoneParams

OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
OBS=OUT/"mucum_observed_multistation_latest.json"
LIVE=ROOT/"previsao_ao_vivo_mucum.json"
RESTART=OUT/"hec_hms_operational_forecast_latest.json"
FORCING=OUT/"hec_twin_ifs_spatial_forcing_5d_latest.json"
LIB=OUT/"modelo_mucum_eventwise_v1_fechado_latest.json"
ZONE=OUT/"hec_hms_spatial_forecast_mucum/zone_hourly.csv"
RT=OUT/"hec_hms_dual_boundary_mucum"
PROJ=RT/"project"
RESULT=OUT/"hec_hms_dual_boundary_mucum_latest.json"
SERIES=RT/"primary_series.csv"

AREA_LJJ=12918.656
# Passo Carreiro (86500000) drains ~1,820 km², while the full BHO6 Carreiro
# contribution at the Taquari confluence is ~2,564.19 km². Treating the
# observed gauge as the whole tributary silently removed ~744 km² from the
# mass balance. Keep the observed part as a Source and model only the
# downstream/unmeasured increment as rainfall-runoff.
AREA_CARR_TOTAL=2564.190
AREA_CARR_GAUGE=1820.000
AREA_CARR_RES=max(0.0,AREA_CARR_TOTAL-AREA_CARR_GAUGE)
AREA_STZ_RES=292.340
AREA_MUC_INC=190.021
K1=float(os.environ.get("DUAL_K1_H","2.5"))
K2=float(os.environ.get("DUAL_K2_H","2.5"))
K3=float(os.environ.get("DUAL_K3_H","1.0"))
X=float(os.environ.get("DUAL_X","0.2"))
WARMUP_H=float(os.environ.get("DUAL_WARMUP_H","12"))
MEMORY_TAU_H=float(os.environ.get("DUAL_MEMORY_TAU_H","3.0"))
DN_INITIAL_LOSS_SCALE=float(os.environ.get("DUAL_DN_INITIAL_LOSS_SCALE","1.0"))
DN_CONSTANT_LOSS_SCALE=float(os.environ.get("DUAL_DN_CONSTANT_LOSS_SCALE","1.0"))
DN_TC_SCALE=float(os.environ.get("DUAL_DN_TC_SCALE","1.0"))
DN_STORAGE_SCALE=float(os.environ.get("DUAL_DN_STORAGE_SCALE","1.0"))
DN_RECESSION_SCALE=float(os.environ.get("DUAL_DN_RECESSION_SCALE","1.0"))
DN_FLOW_RATIO_SCALE=float(os.environ.get("DUAL_DN_FLOW_RATIO_SCALE","1.0"))

def loadj(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def dt_local(s):
    return datetime.fromisoformat(str(s).replace("Z","+00:00")).astimezone(BRT).replace(tzinfo=None)

def dt_utc(s):
    return datetime.fromisoformat(str(s).replace("Z","+00:00")).astimezone(timezone.utc)

def interp(xs, ys, target):
    if target <= xs[0]: return float(ys[0])
    if target >= xs[-1]: return float(ys[-1])
    for i in range(len(xs)-1):
        if xs[i] <= target <= xs[i+1]:
            den=(xs[i+1]-xs[i]).total_seconds()
            a=(target-xs[i]).total_seconds()/den if den else 0.0
            return float(ys[i])*(1-a)+float(ys[i+1])*a
    return float(ys[-1])

def station_rows(pkg, code):
    st=next(x for x in pkg["flow"]["stations"] if str(x.get("code"))==str(code))
    rows=[]
    for r in st.get("series") or []:
        if r.get("flow_m3s") is None: continue
        rows.append((datetime.fromisoformat(str(r["time_local"])),float(r["flow_m3s"])))
    rows.sort()
    if not rows: raise RuntimeError(f"no observed flow for {code}")
    return rows

def network_branch_stats(pkg, upg, boundary_code, exclude_codes=(), max_age_h=2.5):
    """Robust current branch trend from every fresh observed-Q station in the UPG.

    Stations are NOT summed. Their relative hour-to-hour changes are used as
    state diagnostics because many gauges are nested along the same river.
    """
    all_stations=(pkg.get("flow") or {}).get("stations") or []
    ref_times=[]
    for st0 in all_stations:
        for x0 in reversed(st0.get("series") or []):
            if x0.get("flow_m3s") is not None or x0.get("level") is not None:
                try: ref_times.append(datetime.fromisoformat(str(x0["time_local"])))
                except Exception: pass
                break
    reference_time=max(ref_times) if ref_times else None
    rows=[]
    for st in all_stations:
        if str(st.get("upg") or "") != str(upg):
            continue
        if str(st.get("code")) in set(str(x) for x in exclude_codes):
            continue
        q=[x for x in (st.get("series") or []) if x.get("flow_m3s") is not None]
        if len(q)<2:
            continue
        a,b=q[-2],q[-1]
        try:
            ta=datetime.fromisoformat(str(a["time_local"]))
            tb=datetime.fromisoformat(str(b["time_local"]))
            qa=float(a["flow_m3s"]); qb=float(b["flow_m3s"])
        except Exception:
            continue
        dh=(tb-ta).total_seconds()/3600.0
        age_h=((reference_time-tb).total_seconds()/3600.0) if reference_time is not None else 0.0
        if dh<=0 or dh>3 or qa<=0 or age_h>float(max_age_h):
            continue
        rel_per_h=(qb/qa-1.0)/dh
        if abs(rel_per_h)>0.50:
            # keep extreme local jumps visible in station audit, but do not let
            # a single plant/gauge dominate the robust branch-state estimate.
            continue
        rows.append({
            "code":str(st.get("code")),"name":st.get("name"),
            "time_local":str(b.get("time_local")),"q_m3s":round(qb,3),
            "relative_change_per_h":rel_per_h,
        })
    vals=sorted(x["relative_change_per_h"] for x in rows)
    median_rel=vals[len(vals)//2] if vals else None

    bst=next((st for st in (pkg.get("flow") or {}).get("stations") or []
              if str(st.get("code"))==str(boundary_code)),None)
    bq=[x for x in ((bst or {}).get("series") or []) if x.get("flow_m3s") is not None]
    direct_slope=None; q0=None
    if len(bq)>=2:
        a,b=bq[-2],bq[-1]
        ta=datetime.fromisoformat(str(a["time_local"])); tb=datetime.fromisoformat(str(b["time_local"]))
        dh=(tb-ta).total_seconds()/3600.0
        if dh>0:
            q0=float(b["flow_m3s"])
            direct_slope=(float(b["flow_m3s"])-float(a["flow_m3s"]))/dh
    network_slope=(q0*median_rel) if (q0 is not None and median_rel is not None) else None
    slopes=[x for x in (direct_slope,network_slope) if x is not None]
    state_slope=sum(slopes)/len(slopes) if slopes else 0.0
    return {
        "upg":upg,"boundary_code":str(boundary_code),
        "fresh_q_station_count":len(rows),"stations":rows,
        "reference_time_local":None if reference_time is None else reference_time.isoformat(timespec="minutes"),
        "max_age_h":float(max_age_h),
        "median_relative_change_per_h":None if median_rel is None else round(median_rel,5),
        "boundary_direct_slope_m3s_h":None if direct_slope is None else round(direct_slope,3),
        "network_equivalent_slope_m3s_h":None if network_slope is None else round(network_slope,3),
        "state_slope_m3s_h":round(state_slope,3),
        "note":"all fresh Q gauges constrain branch trend; nested gauges are diagnostics, never added as independent flows",
    }


def observed_at_hour(rows, t):
    exact={x:y for x,y in rows}
    if t in exact: return exact[t]
    before=[z for z in rows if z[0] < t]
    after=[z for z in rows if z[0] > t]
    if before and after:
        t0,q0=before[-1]; t1,q1=after[0]
        a=(t-t0).total_seconds()/(t1-t0).total_seconds()
        return q0*(1-a)+q1*a
    if before: return before[-1][1]
    return after[0][1]

def read_zone():
    rows=list(csv.DictReader(ZONE.open(encoding="utf-8")))
    times=[datetime.strptime(r["time_local"],"%Y-%m-%d %H:%M:%S") for r in rows]
    return rows,times

def l_julio_future_model():
    pkg=loadj(RESTART)
    times=[dt_local(t) for t in pkg["times_utc"]]
    vals=(pkg.get("nodes") or {}).get("Zona_86472000_LIVE",{}).get("q_m3s") or []
    if not vals or len(vals)!=len(times):
        raise RuntimeError("restart has no aligned Zona_86472000_LIVE series")
    return times,[float(v) for v in vals]

def carreiro_future_model(obs_q0):
    forcing=loadj(FORCING)
    lib=loadj(LIB)
    times=[dt_local(t) for t in forcing["times_utc"]]
    precip=forcing["precip_mm_by_subbasin"]
    areas=load_areas()
    row=next(r for r in lib["params_library_eventwise"] if r["event_id"]=="E28")
    params=params_from_library_row(row)
    params,meta=solve_dn_ratio(params,precip,areas,float(obs_q0),0)
    net=run_network(precip,areas,params,include_mucum_increment=True)
    routed=muskingum(net["at_antas"],params.k1,params.x)
    branch=[max(0.0,float(a)-float(b)) for a,b in zip(net["at_carreiro"],routed)]
    return times,branch,meta

def make_source(times, obs_rows, future_times, future_vals, label, state_slope_m3s_h=0.0, memory_tau_h=3.0, model_increment_scale=1.0):
    last_t,last_q=obs_rows[-1]
    # Model change is used, never its absolute modeled Q.
    anchor_t=max(future_times[0], min(last_t, future_times[-1]))
    anchor_model=interp(future_times,future_vals,anchor_t)
    out=[]; source=[]
    for t in times:
        if t <= last_t:
            out.append(observed_at_hour(obs_rows,t)); source.append(f"observed_{label}")
        else:
            m=interp(future_times,future_vals,t)
            h=max(0.0,(t-last_t).total_seconds()/3600.0)
            # A short observed-state memory term carries the measured rising/falling
            # wave into the forecast without inventing any current Q. It decays back
            # toward the rainfall-runoff forecast and is estimated from the complete
            # fresh gauge network in the same UPG.
            memory=float(state_slope_m3s_h)*h*math.exp(-h/max(float(memory_tau_h),0.25))
            model_increment=(m-anchor_model)*float(model_increment_scale)
            out.append(max(0.0,last_q+model_increment+memory)); source.append(f"modeled_increment_plus_observed_network_memory_{label}")
    return out,{
        "station":label,
        "last_observed_local":last_t.isoformat(timespec="minutes"),
        "last_observed_q_m3s":round(last_q,3),
        "model_anchor_local":anchor_t.isoformat(timespec="minutes"),
        "model_anchor_q_m3s":round(anchor_model,3),
        "observed_network_state_slope_m3s_h":round(float(state_slope_m3s_h),3),
        "memory_tau_h":float(memory_tau_h),
        "model_increment_scale":float(model_increment_scale),
    },source

def recent_observed_lag_audit(obs, hours=24):
    """Find the lag that best relates independent upstream branch Q to Muçum Q.
    Uses LJJ + Passo Carreiro as independent branch controls; upstream nested
    stations are retained as diagnostics and are never summed twice.
    """
    lrows=station_rows(obs,"86472000")
    crows=station_rows(obs,"86500000")
    mrows=station_rows(obs,"86510000")
    lm={t:q for t,q in lrows}; cm={t:q for t,q in crows}; mm={t:q for t,q in mrows}
    if not mm: return {"best_lag_h":None,"trials":[]}
    end=max(mm); start=end-timedelta(hours=hours)
    trials=[]
    for lag in (0,1,2,3,4,5,6):
        pairs=[]
        for t,qm in mm.items():
            if t<start: continue
            u=t-timedelta(hours=lag)
            if u in lm and u in cm: pairs.append((lm[u]+cm[u],qm))
        if len(pairs)<4: continue
        mx=sum(a for a,_ in pairs)/len(pairs); my=sum(b for _,b in pairs)/len(pairs)
        cov=sum((a-mx)*(b-my) for a,b in pairs)
        vx=sum((a-mx)**2 for a,_ in pairs) or 1e-9
        vy=sum((b-my)**2 for _,b in pairs) or 1e-9
        corr=cov/math.sqrt(vx*vy)
        b=cov/vx; a=my-b*mx
        rmse=math.sqrt(sum((yy-(a+b*xx))**2 for xx,yy in pairs)/len(pairs))
        trials.append({"lag_h":lag,"n":len(pairs),"corr":corr,"rmse_m3s":rmse,"intercept":a,"slope":b})
    best=min(trials,key=lambda z:z["rmse_m3s"]) if trials else None
    return {"best_lag_h":None if best is None else best["lag_h"],"best":best,"trials":trials}

def sb_text(name,area,downstream,il,cl,tc,storage,rec,ratio):
    return f"""Subbasin: {name}
     Area: {area:.3f}
     Downstream: {downstream}
     Canopy: None
     Allow Simultaneous Precip Et: No
     Plant Uptake Method: None
     Surface: None
     LossRate: Initial+Constant
     Percent Impervious Area: 0.0
     Initial Loss: {il:.3f}
     Constant Loss Rate: {cl:.3f}
     Transform: Clark
     Clark Method: Specified
     Time of Concentration: {tc:.3f}
     Storage Coefficient: {storage:.3f}
     Time Area Method: Default
     Baseflow: Recession
     Recession Factor: {rec:.5f}
     Initial Flow/Area Ratio: {ratio:.6f}
     Threshold Flow to Peak Ratio: 0.1
End:
"""

def basin_text(params):
    dn=params.dn
    return f"""Basin: Mucum Dual Observed Boundary
     Description: observed LJJ + observed Carreiro boundaries, residual rain-runoff only
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:25:00
     Version: 4.13
     Filepath Separator: \\
     Unit System: Metric
     Missing Flow To Zero: No
     Enable Flow Ratio: No
     Compute Local Flow At Junctions: No
     Unregulated Output Required: No
     Enable Sediment Routing: No
End:

Source: LJJ_SOURCE
     Area: {AREA_LJJ:.3f}
     Downstream: R_LJJ_CARR
     Flow Method: GAGE_FLOW
     Flow Gage: Q_LJJ_LIVE
     End Flow Method:
End:

Reach: R_LJJ_CARR
     Downstream: J_CARR
     Route: Muskingum
     Initial Variable: Combined Inflow
     Muskingum K: {K1:.3f}
     Muskingum x: {X:.3f}
     Muskingum Steps: 1
     Channel Loss: None
End:

Source: CARR_SOURCE
     Area: {AREA_CARR_GAUGE:.3f}
     Downstream: J_CARR
     Flow Method: GAGE_FLOW
     Flow Gage: Q_CARR_LIVE
     End Flow Method:
End:

{sb_text("CARR_RES",AREA_CARR_RES,"J_CARR",dn.initial_loss,dn.constant_loss,dn.tc,dn.storage,dn.recession,dn.initial_flow_ratio)}
Junction: J_CARR
     Downstream: R_CARR_STZ
End:

Reach: R_CARR_STZ
     Downstream: J_STZ
     Route: Muskingum
     Initial Variable: Combined Inflow
     Muskingum K: {K2:.3f}
     Muskingum x: {X:.3f}
     Muskingum Steps: 1
     Channel Loss: None
End:

{sb_text("STZ_RES",AREA_STZ_RES,"J_STZ",dn.initial_loss,dn.constant_loss,dn.tc,dn.storage,dn.recession,dn.initial_flow_ratio)}
Junction: J_STZ
     Downstream: R_STZ_MUCUM
End:

Reach: R_STZ_MUCUM
     Downstream: MUCUM
     Route: Muskingum
     Initial Variable: Combined Inflow
     Muskingum K: {K3:.3f}
     Muskingum x: {X:.3f}
     Muskingum Steps: 1
     Channel Loss: None
End:

{sb_text("MUC_INC",AREA_MUC_INC,"MUCUM",dn.initial_loss,dn.constant_loss,dn.tc,dn.storage,dn.recession,dn.initial_flow_ratio)}
Junction: MUCUM
     Computation Point: Yes
End:
"""

def met_text():
    return """Meteorology: Residual Rain
     Version: 4.13
     Unit System: Metric
     Set Missing Data to Default: No
     Precipitation Method: Specified Average
     Air Temperature Method: None
     Atmospheric Pressure Method: None
     Dew Point Method: None
     Wind Speed Method: None
     Shortwave Radiation Method: None
     Longwave Radiation Method: None
     Snowmelt Method: None
     Evapotranspiration Method: No Evapotranspiration
     Use Basin Model: Mucum Dual Observed Boundary
End:

Precip Method Parameters: Specified Average
     Allow Depth Override: Yes
End:

Subbasin: CARR_RES
     Gage: RAIN_RESIDUAL
End:

Subbasin: STZ_RES
     Gage: RAIN_RESIDUAL
End:

Subbasin: MUC_INC
     Gage: RAIN_RESIDUAL
End:
"""

def project_text():
    return """Project: mucum_dual_boundary
     Description: Muçum dual observed boundary forecast
     Version: 4.13
     Filepath Separator: \\
     DSS File Name: input.dss
     Time Zone ID: America/Sao_Paulo
End:

Precipitation: Residual Rain
     Filename: residual.met
End:

Basin: Mucum Dual Observed Boundary
     Filename: dual.basin
End:

Control: Dual Control
     FileName: dual.control
End:
"""

def run_text():
    return """Run: Forecast
     Description: observed LJJ + observed Carreiro + residual rainfall
     Log File: forecast.log
     DSS File: output.dss
     Is Save Spatial Results: No
     Basin: Mucum Dual Observed Boundary
     Precip: Residual Rain
     Control: Dual Control
     Save State Type: None
     Time-Series Output: Save All
     Time Series Results Manager Start:
     Time Series Results Manager End:
End:
"""

def control_text(start,end):
    return f"""Control: Dual Control
     Version: 4.13
     Start Date: {fmt_hec_date(start)}
     Start Time: {fmt_hec_time(start)}
     End Date: {fmt_hec_date(end)}
     End Time: {fmt_hec_time(end)}
     Time Interval: 60
End:
"""

def gage_text(start,end):
    dp=dpart(start)
    def block(name,typ,path,units=""):
        return f"""Gage: {name}
     Gage: {name}
     Gage Type: {typ}
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: input.dss
     Pathname: {path}
     Variant: Variant-1
       Start Time: {fmt_hec_date(start)}, {fmt_hec_time(start)}
       End Time: {fmt_hec_date(end)}, {fmt_hec_time(end)}
     End Variant: Variant-1
End:

"""
    return """Gage Manager: Mucum dual boundary
     Version: 4.13
     Filepath Separator: \\
End:

""" + block("Q_LJJ_LIVE","Flow",f"/MUCUM/LJJ/FLOW/{dp}/1Hour/FORECAST/") + block("Q_CARR_LIVE","Flow",f"/MUCUM/CARR/FLOW/{dp}/1Hour/FORECAST/") + block("RAIN_RESIDUAL","Precipitation",f"/MUCUM/RESIDUAL/PRECIP-INC/{dp}/1Hour/FORECAST/")

def write_script(times,q_ljj,q_carr,rain):
    p=PROJ/"run.script"
    ts=[t.strftime("%Y-%m-%d %H:%M:%S") for t in times]
    dp=dpart(times[0].replace(tzinfo=BRT))
    p.write_text(f"""from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
from hec.io import TimeSeriesContainer
import os, csv
project_dir=r"{PROJ.as_posix()}"
times={ts!r}
q_ljj={q_ljj!r}
q_carr={q_carr!r}
rain={rain!r}
dp="{dp}"

def put(path,values,units,typ):
    first=times[0]
    y=int(first[0:4]); m=int(first[5:7]); d=int(first[8:10]); hh=int(first[11:13])*100
    months=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    t=HecTime("%02d%s%04d"%(d,months[m-1],y),"%04d"%hh)
    tv=[]
    for v in values:
        tv.append(t.value()); t.add(60)
    c=TimeSeriesContainer(); c.fullName=path; c.interval=60; c.times=tv; c.values=values
    c.numberValues=len(values); c.units=units; c.type=typ
    dss.put(c)

dss=HecDss.open(project_dir+"/input.dss")
put("/MUCUM/LJJ/FLOW/"+dp+"/1Hour/FORECAST/",q_ljj,"M3/S","INST-VAL")
put("/MUCUM/CARR/FLOW/"+dp+"/1Hour/FORECAST/",q_carr,"M3/S","INST-VAL")
put("/MUCUM/RESIDUAL/PRECIP-INC/"+dp+"/1Hour/FORECAST/",rain,"MM","PER-CUM")
dss.close()
out=project_dir+"/output.dss"
if os.path.exists(out): os.remove(out)
OpenProject("mucum_dual_boundary",project_dir)
Compute("Forecast")
dss=HecDss.open(out)
paths=list(dss.getCatalogedPathnames())
flows=[x for x in paths if "/FLOW/" in x and "/1Hour/RUN:Forecast/" in x]
fo=open(r"{(RT/'hec_output_values.csv').as_posix()}","wb")
w=csv.writer(fo); w.writerow(["element","time_value","q_m3s","pathname"])
for path in flows:
    s=dss.get(path); parts=path.split("/"); element=parts[2] if len(parts)>2 else ""
    for i in range(s.numberValues):
        v=float(s.values[i])
        if v>-1e20: w.writerow([element,int(s.times[i]),v,path])
fo.close(); dss.close(); Exit(1)
""",encoding="utf-8")
    return p

def main():
    if len(sys.argv)<2: raise SystemExit("usage: run_hec_hms_mucum_dual_boundary.py /path/to/hec-hms.sh")
    hec=sys.argv[1]
    obs=loadj(OBS); live=loadj(LIVE); lib=loadj(LIB)
    rows_all,times_all=read_zone()
    live=loadj(LIVE)
    obs_t=datetime.fromisoformat(live["telemetria_ultima_em"])
    warm_start=obs_t.replace(minute=0,second=0,microsecond=0)-timedelta(hours=WARMUP_H)
    keep=[i for i,t in enumerate(times_all) if t>=warm_start]
    rows=[rows_all[i] for i in keep]
    times=[times_all[i] for i in keep]
    lrows=station_rows(obs,"86472000")
    crows=station_rows(obs,"86500000")
    lag_audit=recent_observed_lag_audit(obs,24)
    # Every observed-Q gauge participates in state diagnosis by UPG.
    # Only non-overlapping downstream controls become mass boundaries.
    antas_stats=network_branch_stats(obs,"Médio Taquari-Antas","86472000",exclude_codes=("86472600","86510000"))
    carr_stats=network_branch_stats(obs,"Carreiro","86500000")

    lft,lfq=l_julio_future_model()
    forcing=loadj(FORCING)
    fstart=dt_local(forcing["times_utc"][0])
    cq0=observed_at_hour(crows,fstart)
    cft,cfq,cmeta=carreiro_future_model(cq0)

    q_ljj,laudit,lsource=make_source(
        times,lrows,lft,lfq,"86472000",
        state_slope_m3s_h=float(antas_stats["state_slope_m3s_h"]),memory_tau_h=MEMORY_TAU_H
    )
    q_carr,caudit,csource=make_source(
        times,crows,cft,cfq,"86500000",
        state_slope_m3s_h=float(carr_stats["state_slope_m3s_h"]),memory_tau_h=MEMORY_TAU_H,
        model_increment_scale=(AREA_CARR_GAUGE/AREA_CARR_TOTAL)
    )
    rain=[float(r["rain_02851072_mm"]) for r in rows]

    row=next(r for r in lib["params_library_eventwise"] if r["event_id"]=="E28")
    params=params_from_library_row(row)

    # Live-event residual calibration. These are true HEC-HMS basin parameters,
    # not a visual shift of the resulting stage curve. The iterative controller
    # may vary them when routing/warm-up alone cannot reproduce the observed
    # 6 h / 12 h hydrograph.
    dn0=params.dn
    params=NestedParams(
        up=params.up,
        dn=ZoneParams(
            initial_loss=max(0.0,dn0.initial_loss*DN_INITIAL_LOSS_SCALE),
            constant_loss=max(0.0,dn0.constant_loss*DN_CONSTANT_LOSS_SCALE),
            tc=max(0.5,dn0.tc*DN_TC_SCALE),
            storage=max(0.5,dn0.storage*DN_STORAGE_SCALE),
            recession=min(0.995,max(0.50,dn0.recession*DN_RECESSION_SCALE)),
            initial_flow_ratio=max(0.0,dn0.initial_flow_ratio*DN_FLOW_RATIO_SCALE),
        ),
        k1=params.k1,k2=params.k2,k3=params.k3,x=params.x,
    )

    # Build HEC-HMS with the observed boundary areas and explicit ungauged
    # Carreiro increment. Reach initialisation remains native/valid HEC syntax.
    segs=mucum_curve_segments()
    PROJ.mkdir(parents=True,exist_ok=True)
    start=times[0].replace(tzinfo=BRT); end=times[-1].replace(tzinfo=BRT)
    (PROJ/"mucum_dual_boundary.hms").write_text(project_text(),encoding="utf-8")
    (PROJ/"mucum_dual_boundary.run").write_text(run_text(),encoding="utf-8")
    (PROJ/"dual.basin").write_text(basin_text(params),encoding="utf-8")
    (PROJ/"residual.met").write_text(met_text(),encoding="utf-8")
    (PROJ/"dual.control").write_text(control_text(start,end),encoding="utf-8")
    (PROJ/"mucum_dual_boundary.gage").write_text(gage_text(start,end),encoding="utf-8")

    js=write_script(times,q_ljj,q_carr,rain)
    cp=subprocess.run([hec,"-s",str(js)],cwd=ROOT,text=True,capture_output=True)
    print(cp.stdout); print(cp.stderr,file=sys.stderr)
    if cp.returncode!=0: raise SystemExit(cp.returncode)

    rr=list(csv.DictReader((RT/"hec_output_values.csv").open(encoding="utf-8")))
    vals=[float(x["q_m3s"]) for x in rr if x["element"]=="MUCUM"]
    vals=vals[-len(times):]
    if len(vals)!=len(times): raise RuntimeError(f"MUCUM output {len(vals)} != {len(times)}")
    stage_meta=[q_to_stage_cm(q,segs) for q in vals]
    stages=[m.get("stage_cm") for m in stage_meta]

    obs_n=float(live["telemetria_ultima_nivel_cm"])
    q_now=interp(times,vals,obs_t)
    relevant=[
        (i,m) for i,(t,m) in enumerate(zip(times,stage_meta))
        if t>=obs_t-timedelta(hours=12) and not bool(m.get("ok"))
    ]
    if relevant:
        i0,m0=relevant[0]
        out={
          "schema_version":"hec_hms_mucum_dual_observed_boundary_v1",
          "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
          "status":"blocked_rating_curve_safety",
          "model":"HEC-HMS 4.13",
          "current":{
            "observed_time_local":obs_t.isoformat(timespec="minutes"),
            "observed_stage_cm":obs_n,
            "model_q_m3s":round(q_now,3)
          },
          "rating_curve_safety":{
            "first_unsafe_index":i0,
            "first_unsafe_time_local":times[i0].isoformat(timespec="minutes"),
            "reason":m0.get("reason"),
            "diagnostic_stage_cm":m0.get("diagnostic_stage_cm"),
            "safety_limit_cm":m0.get("safety_limit_cm"),
            "unsafe_count_relevant_window":len(relevant)
          },
          "q_m3s":[round(x,3) for x in vals],
          "stage_cm":[None for _ in vals],
          "research_only":True,
          "not_official_alert":True,
          "publishable":False
        }
        RESULT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        with SERIES.open("w",newline="",encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(["time_local","q_m3s","stage_cm"])
            for t,q in zip(times,vals): w.writerow([t.isoformat(timespec="minutes"),q,None])
        print("DUAL_BOUNDARY_RESULT="+json.dumps({"status":out["status"],"rating_curve_safety":out["rating_curve_safety"]},ensure_ascii=False))
        return

    model_now=interp(times,stages,obs_t)

    # Recent fit against the 15-min live Muçum series. Keep both 6 h and 12 h
    # metrics because the platform must optimize a rejected candidate instead of
    # simply stopping at the first failed validation.
    live_series=[]
    for r in live.get("serie_observada_ana") or []:
        try: live_series.append((datetime.fromisoformat(r["hora"]),float(r["nivel_cm"])))
        except Exception: pass

    def fit_window(hours):
        recent=[(t,n) for t,n in live_series if t<=obs_t and t>=obs_t-timedelta(hours=hours)]
        pairs=[(interp(times,stages,t),n) for t,n in recent if times[0]<=t<=times[-1]]
        if not pairs:
            return {"n":0,"rmse_cm":None,"bias_cm":None,"nse":None}
        errs=[m-o for m,o in pairs]
        rmse=(sum(e*e for e in errs)/len(errs))**0.5
        bias=sum(errs)/len(errs)
        obs_vals=[o for _,o in pairs]
        om=sum(obs_vals)/len(obs_vals)
        den=sum((o-om)**2 for o in obs_vals)
        nse=None if den<=1e-9 else 1.0-sum((m-o)**2 for m,o in pairs)/den
        return {"n":len(pairs),"rmse_cm":rmse,"bias_cm":bias,"nse":nse}

    fit6=fit_window(6)
    fit12=fit_window(12)
    rmse=fit6["rmse_cm"]
    bias=fit6["bias_cm"]
    recent=[(t,n) for t,n in live_series if t<=obs_t and t>=obs_t-timedelta(hours=6)]
    errs=[interp(times,stages,t)-n for t,n in recent if times[0]<=t<=times[-1]]

    # Current observed slope is a hard operational diagnostic: a candidate that
    # reaches the right level but is climbing much faster/slower is not accepted.
    slope_window_h=0.5
    slope_t0=obs_t-timedelta(hours=slope_window_h)
    obs_prev=[(t,n) for t,n in live_series if t<=slope_t0]
    if obs_prev:
        t_prev,n_prev=obs_prev[-1]
        dh=(obs_t-t_prev).total_seconds()/3600.0
        observed_slope_cm_h=(obs_n-n_prev)/dh if dh>0 else None
    else:
        observed_slope_cm_h=None
    model_prev=interp(times,stages,slope_t0)
    model_slope_cm_h=(model_now-model_prev)/slope_window_h
    slope_error_cm_h=None if observed_slope_cm_h is None else model_slope_cm_h-observed_slope_cm_h

    state_error=model_now-obs_n
    adjusted_errs=[(e-state_error) for e in errs]
    adj_rmse=(sum(e*e for e in adjusted_errs)/len(adjusted_errs))**0.5 if adjusted_errs else None
    adj_bias=sum(adjusted_errs)/len(adjusted_errs) if adjusted_errs else None

    # Prefer the native HEC state whenever it already reaches the observation.
    # Only use explicit stage conditioning when the HEC state is materially off.
    if abs(state_error) <= 10.0:
        operational_stage=[float(n) for n in stages]
        state_mode="native_hec_state_matches_observed"
        state_assimilation_applied=False
        publishable=(rmse is None or rmse<=60.0) and (slope_error_cm_h is None or abs(slope_error_cm_h)<=20.0)
    else:
        operational_stage=[obs_n+(float(n)-model_now) for n in stages]
        state_mode="explicit_observed_stage_conditioning"
        state_assimilation_applied=True
        # Conditioning is retained only as a diagnostic delta trajectory.
        # It must never promote a HEC run whose native internal state misses t0.
        publishable=False

    future=[(t,n,q) for t,n,q in zip(times,operational_stage,vals) if t>=obs_t]
    peak=max(future,key=lambda z:z[1])

    out={
      "schema_version":"hec_hms_mucum_dual_observed_boundary_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "model":"HEC-HMS 4.13",
      "method":"two observed discharge boundaries (LJJ 86472000 + Passo Carreiro 86500000 over its 1820 km2 gauged area) + explicit 744 km2 ungauged Carreiro residual + STZ/Mucum residual rainfall-runoff + E28 routing",
      "topology":{
        "areas_km2":{"LJJ_upstream":AREA_LJJ,"Carreiro_total":AREA_CARR_TOTAL,"Carreiro_gauged_86500000":AREA_CARR_GAUGE,"Carreiro_ungauged_residual":AREA_CARR_RES,"STZ_residual":AREA_STZ_RES,"Mucum_increment":AREA_MUC_INC},
        "routing":{"k1_h":K1,"k2_h":K2,"k3_h":K3,"x":X},
        "live_calibration_controls":{
          "warmup_h":WARMUP_H,"memory_tau_h":MEMORY_TAU_H,
          "carreiro_gauge_fraction":round(AREA_CARR_GAUGE/AREA_CARR_TOTAL,6),
          "carreiro_residual_area_km2":round(AREA_CARR_RES,3),
          "dn_initial_loss_scale":DN_INITIAL_LOSS_SCALE,
          "dn_constant_loss_scale":DN_CONSTANT_LOSS_SCALE,
          "dn_tc_scale":DN_TC_SCALE,
          "dn_storage_scale":DN_STORAGE_SCALE,
          "dn_recession_scale":DN_RECESSION_SCALE,
          "dn_flow_ratio_scale":DN_FLOW_RATIO_SCALE,
        },
        "calibration_event":"E28","calibration_nse":row.get("nse"),"warmup_h":WARMUP_H,
      },
      "observed_network_audit":{
        "rain_valid_station_count":(obs.get("rain") or {}).get("valid_station_count"),
        "rain_spatial_method":(obs.get("rain") or {}).get("spatial_method"),
        "rain_event_basin_areal_mm":((obs.get("rain") or {}).get("accumulations") or {}).get("event_basin_areal_mm"),
        "rain_event_by_zone_mm":((obs.get("rain") or {}).get("accumulations") or {}).get("event_by_zone_mm"),
        "flow_station_count":len((obs.get("flow") or {}).get("stations") or []),
        "flow_stations_with_q":(obs.get("flow") or {}).get("stations_with_flow"),
        "flow_stations_with_level":(obs.get("flow") or {}).get("stations_with_level"),
        "antas_branch_state":antas_stats,
        "carreiro_branch_state":carr_stats,
        "rule":"all observed gauges are used for QC/state/trend; only non-overlapping downstream branch controls are added to mass balance",
      },
      "boundary_audit":{"linha_jose_julio":laudit,"passo_carreiro":caudit,"carreiro_state_scaling":cmeta,
          "observed_event_lag":lag_audit},
      "current":{"observed_time_local":obs_t.isoformat(timespec="minutes"),"observed_stage_cm":obs_n,
          "model_stage_cm":round(model_now,2),"stage_error_cm":round(state_error,2),
          "model_q_m3s":round(q_now,2),
          "observed_slope_cm_h":None if observed_slope_cm_h is None else round(observed_slope_cm_h,2),
          "model_slope_cm_h":round(model_slope_cm_h,2),
          "slope_error_cm_h":None if slope_error_cm_h is None else round(slope_error_cm_h,2)},
      "recent_fit_6h":{"n":fit6["n"],"raw_rmse_cm":None if fit6["rmse_cm"] is None else round(fit6["rmse_cm"],2),
          "raw_bias_cm":None if fit6["bias_cm"] is None else round(fit6["bias_cm"],2),
          "nse":None if fit6["nse"] is None else round(fit6["nse"],4),
          "conditioned_rmse_cm":None if adj_rmse is None else round(adj_rmse,2),
          "conditioned_bias_cm":None if adj_bias is None else round(adj_bias,2),
          "operational_state_mode":state_mode,
          "state_assimilation_applied":state_assimilation_applied},
      "recent_fit_12h":{"n":fit12["n"],"raw_rmse_cm":None if fit12["rmse_cm"] is None else round(fit12["rmse_cm"],2),
          "raw_bias_cm":None if fit12["bias_cm"] is None else round(fit12["bias_cm"],2),
          "nse":None if fit12["nse"] is None else round(fit12["nse"],4)},
      "peak":{"time_local":peak[0].isoformat(timespec="minutes"),"stage_cm":round(peak[1],2),"q_m3s":round(peak[2],2),
          "rise_from_observed_cm":round(peak[1]-obs_n,2)},
      "publishable":publishable,
      "rna_reference_not_assimilated":{
        "2h":(live.get("horizontes") or {}).get("2h",{}).get("nivel_previsto_cm"),
        "4h":(live.get("horizontes") or {}).get("4h",{}).get("nivel_previsto_cm"),
        "note":"RNA values are validation references only and do not enter HEC forcing or calibration."
      },
      "times_local":[t.isoformat(timespec="minutes") for t in times],
      "q_m3s":[round(x,3) for x in vals],
      "stage_cm_raw":[round(x,2) for x in stages],
      "stage_cm_operational":[round(x,2) for x in operational_stage],
      "q_ljj_boundary_m3s":[round(x,3) for x in q_ljj],
      "q_carreiro_boundary_m3s":[round(x,3) for x in q_carr],
      "ljj_source":lsource,"carreiro_source":csource,
      "research_only":True,"not_official_alert":True
    }
    RESULT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    RT.mkdir(parents=True,exist_ok=True)
    with SERIES.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["time_local","q_m3s","stage_cm","q_ljj_boundary_m3s","q_carreiro_boundary_m3s"])
        for t,q,n,ql,qc in zip(times,vals,operational_stage,q_ljj,q_carr):
            w.writerow([t.isoformat(timespec="minutes"),q,n,ql,qc])
    print("DUAL_BOUNDARY_RESULT="+json.dumps({
      "current":out["current"],"recent_fit_6h":out["recent_fit_6h"],"peak":out["peak"],
      "publishable":out["publishable"],"boundary_audit":out["boundary_audit"]
    },ensure_ascii=False))

if __name__=="__main__": main()
