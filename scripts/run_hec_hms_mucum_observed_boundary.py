#!/usr/bin/env python3
"""HEC-HMS Muçum forecast with observed upstream discharge boundary.

Stage 1 (run by workflow before this script): full-event rainfall-runoff HEC-HMS
provides a future *increment* for Linha José Júlio.
Stage 2 (this script): replaces the upstream history by observed 86472000 flow,
anchors future HEC increments to the last observation, uses that as a native
HEC-HMS Source/Discharge Gage, adds downstream incremental rainfall-runoff,
and routes the combined hydrograph to Muçum with two Muskingum reaches.
"""
from __future__ import annotations
import csv, json, math, subprocess, sys, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from build_hec_hms_spatial_forecast_mucum import iso_utc, BRT, fmt_hec_date, fmt_hec_time, dpart
from run_hec_twin_mucum_forward_5d import q_to_stage_cm, mucum_curve_segments

OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
OBS=OUT/"mucum_observed_multistation_latest.json"
BASE=OUT/"hec_hms_spatial_forecast_mucum"
ZONE=BASE/"zone_hourly.csv"
BASEQ=BASE/"hec_output_values.csv"
RT=OUT/"hec_hms_observed_boundary_mucum"
PROJ=RT/"project"
RESULT=OUT/"hec_hms_observed_boundary_mucum_latest.json"
SERIES=RT/"primary_series.csv"

UP_AREA=12918.656
TOTAL_AREA=15690.7
INC_AREA=TOTAL_AREA-UP_AREA
K1=float(os.environ.get("BOUNDARY_K1_H","1.0"))
K2=float(os.environ.get("BOUNDARY_K2_H","1.0"))
X=float(os.environ.get("BOUNDARY_X","0.2"))

def loadj(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def hourly_obs_flow(pkg,code):
    st=next(x for x in pkg["flow"]["stations"] if str(x.get("code"))==str(code))
    out={}
    for r in st.get("series",[]):
        if r.get("flow_m3s") is None: continue
        t=datetime.fromisoformat(str(r["time_local"])).replace(minute=0,second=0,microsecond=0)
        out[t]=float(r["flow_m3s"])
    return out

def read_zone():
    rows=list(csv.DictReader(ZONE.open(encoding="utf-8")))
    return rows,[datetime.strptime(r["time_local"],"%Y-%m-%d %H:%M:%S") for r in rows]

def base_element_series(times, element):
    rows=list(csv.DictReader(BASEQ.open(encoding="utf-8")))
    vals=[float(r["q_m3s"]) for r in rows if r["element"]==element]
    # HEC extractor may include stale windows; align the newest N values.
    vals=vals[-len(times):]
    if len(vals)!=len(times):
        raise RuntimeError(f"{element}: {len(vals)} HEC values for {len(times)} times")
    return vals

def make_boundary(times, model_q, obs):
    last_t=max(obs)
    if last_t not in times:
        # match the hourly model stamp
        cand=min(range(len(times)),key=lambda i:abs((times[i]-last_t).total_seconds()))
        model_t=times[cand]
    else:
        cand=times.index(last_t); model_t=last_t
    q0_obs=obs[last_t]; q0_mod=model_q[cand]
    q=[]
    sources=[]
    for i,t in enumerate(times):
        if t<=last_t and t in obs:
            q.append(obs[t]); sources.append("observed_86472000")
        elif i>=cand:
            q.append(max(0.0,q0_obs+(model_q[i]-q0_mod))); sources.append("hec_future_increment_anchored")
        else:
            # should be rare; interpolate from nearest observed hour
            near=min(obs,key=lambda z:abs((z-t).total_seconds()))
            q.append(obs[near]); sources.append("nearest_observed_86472000")
    return q,{"last_observed_local":last_t.isoformat(timespec="minutes"),
              "last_observed_q_m3s":q0_obs,"base_model_q_at_anchor_m3s":q0_mod,
              "anchor_model_time_local":model_t.isoformat(timespec="minutes")},sources

def basin_text():
    return f"""Basin: Mucum Observed Boundary
     Description: observed Linha Jose Julio boundary + downstream incremental rainfall-runoff
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
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
     Description: Linha Jose Julio 86472000 observed boundary, future anchored to upstream HEC response
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
     Area: {UP_AREA:.3f}
     Downstream: R_LJJ_STZ

     Flow Method: GAGE_FLOW
     Flow Gage: Q_LJJ_LIVE
     End Flow Method:
End:

Reach: R_LJJ_STZ
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
     Downstream: J_STZ
     Route: Muskingum
     Initial Variable: Combined Inflow
     Muskingum K: {K1:.3f}
     Muskingum x: {X:.3f}
     Muskingum Steps: 1
     Channel Loss: None
End:

Subbasin: INC_DOWN
     Description: incremental contributing area downstream of Linha Jose Julio
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
     Area: {INC_AREA:.3f}
     Downstream: J_STZ
     Canopy: None
     Allow Simultaneous Precip Et: No
     Plant Uptake Method: None
     Surface: None
     LossRate: Initial+Constant
     Percent Impervious Area: 0.0
     Initial Loss: 2.500
     Constant Loss Rate: 2.000
     Transform: Clark
     Clark Method: Specified
     Time of Concentration: 25.000
     Storage Coefficient: 25.000
     Time Area Method: Default
     Baseflow: Recession
     Recession Factor: 0.800
     Initial Flow/Area Ratio: 0.001000
     Threshold Flow to Peak Ratio: 0.1
End:

Junction: J_STZ
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
     Downstream: R_STZ_MUCUM
End:

Reach: R_STZ_MUCUM
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
     Downstream: MUCUM
     Route: Muskingum
     Initial Variable: Combined Inflow
     Muskingum K: {K2:.3f}
     Muskingum x: {X:.3f}
     Muskingum Steps: 1
     Channel Loss: None
End:

Junction: MUCUM
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
     Computation Point: Yes
End:
"""

def met_text():
    return """Meteorology: Inc Rain
     Description: observed spatial rainfall since 26/09 plus ECMWF/IFS future for downstream increment
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
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
     Use Basin Model: Mucum Observed Boundary
End:

Precip Method Parameters: Specified Average
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10:00
     Allow Depth Override: Yes
End:

Subbasin: INC_DOWN
     Gage: Chuva_INC_LIVE
End:
"""

def project_text():
    return """Project: mucum_observed_boundary
     Description: Muçum observed upstream boundary forecast
     Version: 4.13
     Filepath Separator: \\
     DSS File Name: input.dss
     Time Zone ID: America/Sao_Paulo
End:

Precipitation: Inc Rain
     Filename: inc.met
End:

Basin: Mucum Observed Boundary
     Filename: boundary.basin
End:

Control: Boundary Control
     FileName: boundary.control
End:
"""

def run_text():
    return """Run: Forecast
     Description: observed upstream boundary plus incremental rain
     Log File: forecast.log
     DSS File: output.dss
     Is Save Spatial Results: No
     Basin: Mucum Observed Boundary
     Precip: Inc Rain
     Control: Boundary Control
     Save State Type: None
     Time-Series Output: Save All
     Time Series Results Manager Start:
     Time Series Results Manager End:
End:
"""

def control_text(start,end):
    return f"""Control: Boundary Control
     Description: observed boundary and forecast
     Last Modified Date: 29 September 2026
     Last Modified Time: 19:10
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
    return f"""Gage Manager: Mucum observed boundary
     Version: 4.13
     Filepath Separator: \\
End:

Gage: Chuva_INC_LIVE
     Gage: Chuva_INC_LIVE
     Gage Type: Precipitation
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: input.dss
     Pathname: /MUCUM/INC/PRECIP-INC/{dp}/1Hour/FORECAST/
     Variant: Variant-1
       Start Time: {fmt_hec_date(start)}, {fmt_hec_time(start)}
       End Time: {fmt_hec_date(end)}, {fmt_hec_time(end)}
     End Variant: Variant-1
End:

Gage: Q_LJJ_LIVE
     Gage: Q_LJJ_LIVE
     Gage Type: Flow
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: input.dss
     Pathname: /MUCUM/LJJ/FLOW/{dp}/1Hour/FORECAST/
     Variant: Variant-1
       Start Time: {fmt_hec_date(start)}, {fmt_hec_time(start)}
       End Time: {fmt_hec_date(end)}, {fmt_hec_time(end)}
     End Variant: Variant-1
End:
"""

def write_script(times,boundary_q,rain):
    p=PROJ/"run.script"
    # data are embedded as Python literals to avoid CSV parsing differences in Jython.
    ts=[t.strftime("%Y-%m-%d %H:%M:%S") for t in times]
    p.write_text(f"""from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
from hec.io import TimeSeriesContainer
import os
project_dir=r"{PROJ.as_posix()}"
times={ts!r}
q={boundary_q!r}
rain={rain!r}
dp="{dpart(times[0].replace(tzinfo=BRT))}"

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
put("/MUCUM/LJJ/FLOW/"+dp+"/1Hour/FORECAST/",q,"M3/S","INST-VAL")
put("/MUCUM/INC/PRECIP-INC/"+dp+"/1Hour/FORECAST/",rain,"MM","PER-CUM")
dss.close()
out=project_dir+"/output.dss"
if os.path.exists(out): os.remove(out)
OpenProject("mucum_observed_boundary",project_dir)
Compute("Forecast")
dss=HecDss.open(out)
paths=list(dss.getCatalogedPathnames())
flows=[x for x in paths if "/FLOW/" in x and "/1Hour/RUN:Forecast/" in x]
print("BOUNDARY_FLOW_PATHS|"+"|".join(flows))
fo=open(r"{(RT/'hec_output_values.csv').as_posix()}","wb")
import csv
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
    if len(sys.argv)<2: raise SystemExit("usage: script /path/to/hec-hms.sh")
    hec=sys.argv[1]
    pkg=loadj(OBS)
    rows,times=read_zone()
    model_up=base_element_series(times,"Zona_86472000_LIVE")
    obs=hourly_obs_flow(pkg,"86472000")
    bq,audit,sources=make_boundary(times,model_up,obs)
    # Downstream incremental rainfall: use the wetter/downstream HEC zone field.
    rain=[float(r["rain_02851072_mm"]) for r in rows]

    PROJ.mkdir(parents=True,exist_ok=True)
    start=times[0].replace(tzinfo=BRT); end=times[-1].replace(tzinfo=BRT)
    (PROJ/"mucum_observed_boundary.hms").write_text(project_text(),encoding="utf-8")
    (PROJ/"mucum_observed_boundary.run").write_text(run_text(),encoding="utf-8")
    (PROJ/"boundary.basin").write_text(basin_text(),encoding="utf-8")
    (PROJ/"inc.met").write_text(met_text(),encoding="utf-8")
    (PROJ/"boundary.control").write_text(control_text(start,end),encoding="utf-8")
    (PROJ/"mucum_observed_boundary.gage").write_text(gage_text(start,end),encoding="utf-8")
    js=write_script(times,bq,rain)
    cp=subprocess.run([hec,"-s",str(js)],cwd=ROOT,text=True,capture_output=True)
    print(cp.stdout); print(cp.stderr,file=sys.stderr)
    if cp.returncode!=0: raise SystemExit(cp.returncode)

    rr=list(csv.DictReader((RT/"hec_output_values.csv").open(encoding="utf-8")))
    vals=[float(x["q_m3s"]) for x in rr if x["element"]=="MUCUM"]
    vals=vals[-len(times):]
    if len(vals)!=len(times): raise RuntimeError(f"MUCUM output {len(vals)} != {len(times)}")
    seg=mucum_curve_segments()
    stage_meta=[q_to_stage_cm(q,seg) for q in vals]
    stages=[m.get("stage_cm") for m in stage_meta]
    # exact current Muçum state from live package; compare with hourly interpolation.
    live=loadj(ROOT/"previsao_ao_vivo_mucum.json")
    obs_t=datetime.fromisoformat(live["telemetria_ultima_em"])
    obs_n=float(live["nivel_atual_cm"])

    relevant=[
        (i,m) for i,(t,m) in enumerate(zip(times,stage_meta))
        if t>=obs_t-timedelta(hours=12) and not bool(m.get("ok"))
    ]
    if relevant:
        i0,m0=relevant[0]
        out={
          "schema_version":"hec_hms_mucum_observed_boundary_v1",
          "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
          "status":"blocked_rating_curve_safety",
          "model":"HEC-HMS 4.13",
          "boundary_audit":audit,
          "current":{"observed_time_local":obs_t.isoformat(timespec="minutes"),"observed_stage_cm":obs_n},
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
            w=csv.writer(f); w.writerow(["time_local","q_m3s","stage_cm","source_q_m3s"])
            for t,q,sq in zip(times,vals,bq): w.writerow([t.isoformat(timespec="minutes"),q,None,sq])
        print("OBS_BOUNDARY_RESULT="+json.dumps({"status":out["status"],"rating_curve_safety":out["rating_curve_safety"]},ensure_ascii=False))
        return
    def interp_at(t,ys):
        if t<=times[0]: return ys[0]
        for i in range(len(times)-1):
            if times[i]<=t<=times[i+1]:
                a=(t-times[i]).total_seconds()/(times[i+1]-times[i]).total_seconds()
                return ys[i]*(1-a)+ys[i+1]*a
        return ys[-1]
    model_now=interp_at(obs_t,stages)
    future=[(t,n,q) for t,n,q in zip(times,stages,vals) if t>=obs_t]
    peak=max(future,key=lambda z:z[1])
    out={
      "schema_version":"hec_hms_mucum_observed_boundary_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "model":"HEC-HMS 4.13",
      "method":"observed 86472000 Source/Discharge Gage + HEC-anchored future increment + downstream incremental rainfall-runoff + Muskingum routing",
      "boundary_audit":audit,
      "rain_forcing":{"full_event_observed_package":str(OBS.relative_to(ROOT)),
          "downstream_increment_rain_field":"zone_02851072_mm",
          "whole_basin_accum_mm":sum(float(x.get("basin_mean_mm") or 0) for x in pkg["rain"]["hourly_areal"]),
          "antas_accum_mm":sum(float(x.get("zone_86472000_mm") or 0) for x in pkg["rain"]["hourly_areal"]),
          "prata_accum_mm":sum(float(x.get("zone_02851072_mm") or 0) for x in pkg["rain"]["hourly_areal"]),
          "valid_station_count":pkg["rain"].get("valid_station_count")},
      "current":{"observed_time_local":obs_t.isoformat(timespec="minutes"),"observed_stage_cm":obs_n,
          "model_stage_cm":round(model_now,2),"error_cm":round(model_now-obs_n,2)},
      "peak":{"time_local":peak[0].isoformat(timespec="minutes"),"stage_cm":round(peak[1],2),"q_m3s":round(peak[2],2)},
      "routing":{"k1_h":K1,"k2_h":K2,"x":X},
      "times_local":[t.isoformat(timespec="minutes") for t in times],
      "q_m3s":[round(x,3) for x in vals],
      "stage_cm":[round(x,2) for x in stages],
      "source_boundary_q_m3s":[round(x,3) for x in bq],
      "source_boundary_source":sources,
      "research_only":True,
      "not_official_alert":True
    }
    RESULT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with SERIES.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["time_local","q_m3s","stage_cm","source_q_m3s"])
        for t,q,n,sq in zip(times,vals,stages,bq): w.writerow([t.isoformat(timespec="minutes"),q,n,sq])
    print("OBS_BOUNDARY_RESULT="+json.dumps({"current":out["current"],"peak":out["peak"],"boundary":audit,"rain":out["rain_forcing"]},ensure_ascii=False))
    print("OBS_BOUNDARY_SERIES_BEGIN")
    print(SERIES.read_text())
    print("OBS_BOUNDARY_SERIES_END")

if __name__=="__main__": main()
