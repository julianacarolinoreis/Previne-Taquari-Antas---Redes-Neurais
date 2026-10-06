#!/usr/bin/env python3
"""Run one HEC-HMS 4.13 G040 E1 hindcast candidate through Porto Mariante.

Experiment E1
-------------
Legacy event physics: SCS Curve Number + SCS Unit Hydrograph.
State architecture: observed Linha José Júlio plus any CURRENTLY fresh,
independent tributary Source hydrographs.  When a tributary Source is not
available, the same branch becomes a rainfall-runoff Subbasin at its verified
BHO6 confluence.

This script intentionally stops at Porto Mariante (86895000) for the first
whole-basin calibration because downstream Q-pair evidence is not yet adequate.

Candidate parameters are REQUIRED arguments.  There are no silent defaults for
CN, SCS lag or routing K/X.  One run is a research candidate, never promotion.
"""
from __future__ import annotations

import argparse, csv, json, math, os, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
OBSRAIN=BASE/"whole_basin_observed_rain_latest.json"
HYDRO=BASE/"whole_basin_live_hydro_controls_latest.json"
SCENARIOS=BASE/"whole_basin_boundary_scenarios_latest.json"
OUTROOT=BASE/"g040_e1_hindcast"
BRT=timezone(timedelta(hours=-3))
DSS_EPOCH=datetime(1899,12,31)
# Fixed across calibration candidates so ranking is not contaminated by changing numerical resolution.
# 3 min satisfies HEC-HMS SCS UH guidance dt <= 0.29*lag even at the current minimum lag bound (~15.85 min).
COMPUTE_INTERVAL_MIN=3
# HEC-HMS 4.13 rejects larger Muskingum subreach counts in the generated basin model.
# Keep the numerical search inside the accepted range; candidates without a stable
# solution inside this range are rejected instead of run with unstable routing.
MAX_MUSKINGUM_SUBREACHES=100

MAIN_CHECKPOINTS=["86510000","86720000","86743000","86879000","86879300","86895000"]
SOURCE_PRIMARY="86472000"
BRANCH_CODES=["86500000","86595000","86746000"]

# Mainstem routing pieces through Porto Mariante.
# group_length is used only to split an aggregate K parameter proportionally.
REACHES=[
 ("R_86472000_JOIN_86500000","SRC_86472000","J_JOIN_86500000",2.557,"g1"),
 ("R_JOIN_86500000_86510000","J_JOIN_86500000","J_86510000",41.418,"g1"),
 ("R_86510000_JOIN_86595000","J_86510000","J_JOIN_86595000",5.108,"g2"),
 ("R_JOIN_86595000_86720000","J_JOIN_86595000","J_86720000",12.666,"g2"),
 ("R_86720000_86743000","J_86720000","J_86743000",35.113,"g3"),
 ("R_86743000_JOIN_86746000","J_86743000","J_JOIN_86746000",5.139,"g3"),
 ("R_JOIN_86746000_86879000","J_JOIN_86746000","J_86879000",10.850,"g3"),
 ("R_86879000_86879300","J_86879000","J_86879300",1.472,"g3"),
 ("R_86879300_86895000","J_86879300","J_86895000",37.183,"g4"),
]
GROUP_LENGTH={
 g:sum(r[3] for r in REACHES if r[4]==g) for g in ("g1","g2","g3","g4")
}
CORE_TO_CHECKPOINT={
 "CORE_INC_86472000_86510000":"J_86510000",
 "CORE_INC_86510000_86720000":"J_86720000",
 "CORE_INC_86720000_86743000":"J_86743000",
 "CORE_INC_86743000_86879000":"J_86879000",
 "CORE_INC_86879000_86879300":"J_86879300",
 "CORE_INC_86879300_86895000":"J_86895000",
}
BRANCH_JOIN={
 "86500000":"J_JOIN_86500000",
 "86595000":"J_JOIN_86595000",
 "86746000":"J_JOIN_86746000",
}

def loadj(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def utc(s):
    d=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def local_naive(d):
    return d.astimezone(BRT).replace(tzinfo=None)

def fmt_date(d): return d.strftime("%d %B %Y")
def fmt_time(d): return d.strftime("%H:%M")
def dpart(d): return d.strftime("01%b%Y")

def series_control(pkg,code):
    c=next((x for x in pkg.get("controls") or [] if str(x.get("code"))==str(code)),None)
    if not c: raise RuntimeError(f"control not found: {code}")
    rows=[]
    for r in c.get("recent_rows") or []:
        if r.get("flow_m3s") is None: continue
        q=float(r["flow_m3s"])
        if not math.isfinite(q) or q<0: continue
        rows.append((utc(r["time_utc"]),q))
    rows.sort()
    return c,rows

def interp(rows,t):
    if not rows: return None
    if t<rows[0][0] or t>rows[-1][0]: return None
    exact={x:y for x,y in rows}
    if t in exact: return exact[t]
    lo=None; hi=None
    for a,b in rows:
        if a<t: lo=(a,b)
        elif a>t:
            hi=(a,b); break
    if lo is None or hi is None: return None
    f=(t-lo[0]).total_seconds()/(hi[0]-lo[0]).total_seconds()
    return lo[1]*(1-f)+hi[1]*f

def floor_hour(t): return t.replace(minute=0,second=0,microsecond=0)
def ceil_hour(t):
    f=floor_hour(t)
    return f if t==f else f+timedelta(hours=1)

def hourly_axis(a,b):
    out=[]; t=a
    while t<=b:
        out.append(t); t+=timedelta(hours=1)
    return out

def rain_components(pkg):
    out={}
    for x in pkg.get("components") or []:
        rows=[]
        for r in x.get("series") or []:
            if r.get("mm") is None: continue
            d=datetime.fromisoformat(str(r["time_local"]))
            if d.tzinfo is None: d=d.replace(tzinfo=BRT)
            else: d=d.astimezone(BRT)
            rows.append((d.astimezone(timezone.utc),float(r["mm"])))
        rows.sort()
        out[x["component_id"]]={
            "area_km2":float(x["support_area_km2"]),
            "used":bool(x.get("used_as_rainfall_runoff_in_current_scenario")),
            "rows":rows,
        }
    return out

def rain_at(rows,t):
    # hourly accumulated rain must match the reported hour exactly; no temporal interpolation
    m={floor_hour(a):v for a,v in rows}
    return m.get(floor_hour(t))

def choose_window(rain,hydro,active):
    source_codes=[SOURCE_PRIMARY,*active]
    series=[]
    for code in source_codes:
        _c,rows=series_control(hydro,code)
        if len(rows)<2: raise RuntimeError(f"source {code} has no usable Q history")
        series.append(rows)
    # Current E1 uses components through Porto Mariante.
    used_components=[cid for cid,v in rain.items()
      if v["used"] and (
       cid in CORE_TO_CHECKPOINT or
       (cid.startswith("BRANCH_") and cid.replace("BRANCH_","",1) in BRANCH_CODES)
      )]
    if not used_components: raise RuntimeError("no rainfall-runoff components")
    rain_starts=[min(t for t,_ in rain[cid]["rows"]) for cid in used_components]
    rain_ends=[max(t for t,_ in rain[cid]["rows"]) for cid in used_components]
    start=max([ceil_hour(rows[0][0]) for rows in series]+[ceil_hour(max(rain_starts))])
    end=min([floor_hour(rows[-1][0]) for rows in series]+[floor_hour(min(rain_ends))])
    # Avoid treating an in-progress rainfall hour as complete when wall-clock is inside it.
    complete_cap=floor_hour(datetime.now(timezone.utc))-timedelta(hours=1)
    end=min(end,complete_cap)
    if end<=start:
        raise RuntimeError(f"insufficient common hindcast window: {start} -> {end}")

    # Historical packages can contain isolated missing rain hours. Do not
    # zero-fill them and do not let one hole invalidate an otherwise useful
    # event. Select the longest contiguous hourly block for which every
    # rainfall-runoff component has observed rain and every Source has flow.
    axis=hourly_axis(start,end)
    valid=[]
    for t in axis:
        rain_ok=all(rain_at(rain[cid]["rows"],t) is not None for cid in used_components)
        flow_ok=all(interp(rows,t) is not None for rows in series)
        valid.append(bool(rain_ok and flow_ok))
    runs=[]
    run_start=None
    for i,ok in enumerate(valid+[False]):
        if ok and run_start is None:
            run_start=i
        elif not ok and run_start is not None:
            runs.append((run_start,i-1))
            run_start=None
    if not runs:
        raise RuntimeError("no contiguous complete rain+source-flow block in hindcast window")
    a,b=max(runs,key=lambda z:z[1]-z[0]+1)
    start2=axis[a]; end2=axis[b]
    if (end2-start2).total_seconds()<24*3600:
        raise RuntimeError(
            f"longest complete rain+source-flow block is shorter than 24h: {start2} -> {end2}"
        )
    return start2,end2,used_components

def source_hourly(hydro,code,times):
    _c,rows=series_control(hydro,code)
    vals=[interp(rows,t) for t in times]
    if any(v is None for v in vals):
        raise RuntimeError(f"{code}: source flow does not cover hourly hindcast axis")
    return [float(v) for v in vals]

def target_hourly(hydro,code,times):
    _c,rows=series_control(hydro,code)
    return {t:interp(rows,t) for t in times if interp(rows,t) is not None}

def safe(s):
    return "".join(ch if ch.isalnum() else "_" for ch in str(s))

def hec_subbasin_name(cid):
    cid=str(cid)
    if cid.startswith("CORE_INC_"):
        parts=cid.split("_")
        if len(parts)>=4:
            name=f"SB_C_{parts[-2]}_{parts[-1]}"
        else:
            name="SB_C_"+safe(cid)[9:]
    elif cid.startswith("BRANCH_"):
        name="SB_B_"+cid.replace("BRANCH_","",1)
    else:
        name="SB_"+safe(cid)
    if len(name)>28:
        raise RuntimeError(f"HEC element name exceeds 28 chars after normalization: {name}")
    return name

def subbasin_block(name,area,downstream,cn,lag_min):
    return f"""Subbasin: {name}
     Area: {area:.6f}
     Downstream: {downstream}
     Canopy: None
     Surface: None
     LossRate: SCS
     Percent Impervious Area: 0.0
     Curve Number: {cn:.5f}
     Transform: SCS
     Lag: {lag_min:.5f}
     Unitgraph Type: STANDARD
     Baseflow: None
End:
"""

def muskingum_steps(k_h,x,dt_min=COMPUTE_INTERVAL_MIN):
    """Choose a stable HEC-HMS Muskingum subreach count within accepted limits."""
    dt_h=float(dt_min)/60.0
    k_h=float(k_h); x=float(x)
    if not (k_h>0 and 0.0<=x<=0.5):
        raise RuntimeError(f"invalid Muskingum parameters K={k_h}, X={x}")

    stable=[]
    for n in range(1,MAX_MUSKINGUM_SUBREACHES+1):
        k_sub=k_h/n
        lo=2.0*k_sub*x
        hi=2.0*k_sub*(1.0-x)
        if lo-1e-12 <= dt_h <= hi+1e-12:
            # HEC guidance starts from n ~= K/dt. Among stable, accepted values,
            # pick the one closest to that target without exceeding HMS limits.
            stable.append((abs((k_h/dt_h)-n),n))
    if not stable:
        raise RuntimeError(
            "candidate has no stable Muskingum representation within HEC-HMS "
            f"subreach limit: K={k_h:.6f}h X={x:.6f} dt={dt_min}min "
            f"max_subreaches={MAX_MUSKINGUM_SUBREACHES}"
        )
    return min(stable)[1]

def reach_block(name,downstream,k,x):
    steps=muskingum_steps(k,x)
    return f"""Reach: {name}
     Downstream: {downstream}
     Route: Muskingum
     Initial Variable: Combined Inflow
     Muskingum K: {k:.6f}
     Muskingum x: {x:.6f}
     Muskingum Steps: {steps}
     Channel Loss: None
End:
"""

def source_block(code,downstream,area):
    return f"""Source: SRC_{code}
     Area: {area:.6f}
     Downstream: {downstream}
     Flow Method: GAGE_FLOW
     Flow Gage: Q_{code}
     End Flow Method:
End:
"""

def junction_block(name,downstream=None,checkpoint=False):
    s=f"Junction: {name}\n"
    if downstream: s+=f"     Downstream: {downstream}\n"
    if checkpoint: s+="     Computation Point: Yes\n"
    return s+"End:\n"

def route_k(reach_length,group,args):
    total=getattr(args,"k_"+group)
    return float(total)*float(reach_length)/float(GROUP_LENGTH[group])

def build_basin(rain,active,args):
    parts=["""Basin: G040 E1 Hindcast
     Description: research E1 observed-branch whole-basin hindcast through Porto Mariante
     Last Modified Date: 30 September 2026
     Last Modified Time: 19:00:00
     Version: 4.13
     Filepath Separator: \\
     Unit System: Metric
     Missing Flow To Zero: No
     Enable Flow Ratio: No
     Compute Local Flow At Junctions: No
     Unregulated Output Required: No
     Enable Sediment Routing: No
End:
"""]
    # Primary source and mainstem reaches/junctions.
    parts.append(source_block("86472000","R_86472000_JOIN_86500000",12918.656))
    active_set=set(active)
    # Each tributary join exists. Active branch = observed Source; inactive = rainfall Subbasin.
    # Core incremental runoff remains represented separately at the downstream checkpoint.
    downstream_by_reach={name:down for name,_up,down,_len,_g in REACHES}
    upstream_to_reach={}
    for name,up,down,l,g in REACHES:
        upstream_to_reach[up]=name

    # First join Carreiro
    if "86500000" in active_set:
        parts.append(source_block("86500000","J_JOIN_86500000",1816.359))
    else:
        cid="BRANCH_86500000"
        parts.append(subbasin_block(hec_subbasin_name(cid),rain[cid]["area_km2"],"J_JOIN_86500000",args.cn,args.lag_min))
    parts.append(junction_block("J_JOIN_86500000","R_JOIN_86500000_86510000"))

    # Muçum checkpoint
    parts.append(junction_block("J_86510000","R_86510000_JOIN_86595000",True))

    if "86595000" in active_set:
        parts.append(source_block("86595000","J_JOIN_86595000",2431.975))
    else:
        cid="BRANCH_86595000"
        parts.append(subbasin_block(hec_subbasin_name(cid),rain[cid]["area_km2"],"J_JOIN_86595000",args.cn,args.lag_min))
    parts.append(junction_block("J_JOIN_86595000","R_JOIN_86595000_86720000"))
    parts.append(junction_block("J_86720000","R_86720000_86743000",True))
    parts.append(junction_block("J_86743000","R_86743000_JOIN_86746000",True))

    if "86746000" in active_set:
        parts.append(source_block("86746000","J_JOIN_86746000",2226.742))
    else:
        cid="BRANCH_86746000"
        parts.append(subbasin_block(hec_subbasin_name(cid),rain[cid]["area_km2"],"J_JOIN_86746000",args.cn,args.lag_min))
    parts.append(junction_block("J_JOIN_86746000","R_JOIN_86746000_86879000"))
    parts.append(junction_block("J_86879000","R_86879000_86879300",True))
    parts.append(junction_block("J_86879300","R_86879300_86895000",True))
    parts.append(junction_block("J_86895000",None,True))

    # Core runoff subbasins.
    for cid,down in CORE_TO_CHECKPOINT.items():
        if cid not in rain: raise RuntimeError(f"missing rain component {cid}")
        parts.append(subbasin_block(hec_subbasin_name(cid),rain[cid]["area_km2"],down,args.cn,args.lag_min))

    for name,up,down,l,g in REACHES:
        parts.append(reach_block(name,down,route_k(l,g,args),args.x))
    return "\n".join(parts)

def build_met(used_components):
    lines=["""Meteorology: G040 E1 Observed Rain
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
     Use Basin Model: G040 E1 Hindcast
End:

Precip Method Parameters: Specified Average
     Allow Depth Override: Yes
End:
"""]
    for cid in used_components:
        lines.append(f"""Subbasin: {hec_subbasin_name(cid)}
     Gage: RAIN_{safe(cid)}
End:
""")
    return "\n".join(lines)

def build_project():
    return """Project: g040_e1_hindcast
     Description: PREVINE G040 E1 whole-basin research hindcast
     Version: 4.13
     Filepath Separator: \\
     DSS File Name: input.dss
     Time Zone ID: America/Sao_Paulo
End:

Precipitation: G040 E1 Observed Rain
     Filename: e1.met
End:

Basin: G040 E1 Hindcast
     Filename: e1.basin
End:

Control: E1 Control
     FileName: e1.control
End:
"""

def build_run():
    return """Run: Hindcast
     Description: G040 E1 observed-boundary research hindcast
     Log File: hindcast.log
     DSS File: output.dss
     Is Save Spatial Results: No
     Basin: G040 E1 Hindcast
     Precip: G040 E1 Observed Rain
     Control: E1 Control
     Save State Type: None
     Time-Series Output: Save All
     Time Series Results Manager Start:
     Time Series Results Manager End:
End:
"""

def build_control(a,b):
    la=local_naive(a); lb=local_naive(b)
    return f"""Control: E1 Control
     Version: 4.13
     Start Date: {fmt_date(la)}
     Start Time: {fmt_time(la)}
     End Date: {fmt_date(lb)}
     End Time: {fmt_time(lb)}
     Time Interval: {COMPUTE_INTERVAL_MIN}
End:
"""

def gage_block(name,gtype,path,start,end):
    a=local_naive(start); b=local_naive(end)
    return f"""Gage: {name}
     Gage: {name}
     Gage Type: {gtype}
     Reference Height Units: Meters
     Reference Height: 0.0
     Data Source Type: External DSS
     Filename: input.dss
     Pathname: {path}
     Variant: Variant-1
       Start Time: {fmt_date(a)}, {fmt_time(a)}
       End Time: {fmt_date(b)}, {fmt_time(b)}
     End Variant: Variant-1
End:
"""

def build_gage(start,end,active,used_components):
    dp=dpart(local_naive(start))
    lines=["""Gage Manager: G040 E1 Hindcast
     Version: 4.13
     Filepath Separator: \\
End:
"""]
    for code in [SOURCE_PRIMARY,*active]:
        lines.append(gage_block(f"Q_{code}","Flow",f"/G040/{code}/FLOW/{dp}/1Hour/FORECAST/",start,end))
    for cid in used_components:
        lines.append(gage_block(f"RAIN_{safe(cid)}","Precipitation",f"/G040/{safe(cid)}/PRECIP-INC/{dp}/1Hour/FORECAST/",start,end))
    return "\n".join(lines)

def validate_project_contract(gage_text, met_text, basin_text, active, used_components):
    required_sources=[SOURCE_PRIMARY,*active]
    missing_q=[code for code in required_sources if f"Gage: Q_{code}" not in gage_text]
    if missing_q:
        raise RuntimeError(f"missing flow gages in generated gage manager: {missing_q}")
    missing_source_refs=[code for code in required_sources if f"Flow Gage: Q_{code}" not in basin_text]
    if missing_source_refs:
        raise RuntimeError(f"missing source flow-gage references in basin: {missing_source_refs}")
    missing_rain=[cid for cid in used_components if f"Gage: RAIN_{safe(cid)}" not in gage_text]
    if missing_rain:
        raise RuntimeError(f"missing rain gages: {missing_rain}")
    missing_met=[cid for cid in used_components if f"Subbasin: {hec_subbasin_name(cid)}" not in met_text]
    if missing_met:
        raise RuntimeError(f"missing meteorologic subbasin mappings: {missing_met}")
    return {
        "flow_gages":required_sources,
        "rain_gages":list(used_components),
        "hec_subbasin_names":{cid:hec_subbasin_name(cid) for cid in used_components},
    }

def write_jython(project_dir,times,source_values,rain_values):
    local_times=[local_naive(t).strftime("%Y-%m-%d %H:%M:%S") for t in times]
    dp=dpart(local_naive(times[0]))
    script=project_dir/"run.script"
    script.write_text(f"""from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
from hec.io import TimeSeriesContainer
import os, csv
project_dir=r"{project_dir.as_posix()}"
times={local_times!r}
source_values={source_values!r}
rain_values={rain_values!r}
dp="{dp}"

def put(path,values,units,typ):
    first=times[0]
    y=int(first[0:4]); m=int(first[5:7]); d=int(first[8:10]); hh=int(first[11:13])*100
    months=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    t=HecTime("%02d%s%04d"%(d,months[m-1],y),"%04d"%hh)
    tv=[]
    for v in values:
        tv.append(t.value()); t.add(60)
    c=TimeSeriesContainer(); c.fullName=path; c.interval=60
    c.times=tv; c.values=values; c.numberValues=len(values); c.units=units; c.type=typ
    dss.put(c)

dss=HecDss.open(project_dir+"/input.dss")
for code,vals in source_values.items():
    put("/G040/%s/FLOW/%s/1Hour/FORECAST/"%(code,dp),vals,"M3/S","INST-VAL")
for cid,vals in rain_values.items():
    put("/G040/%s/PRECIP-INC/%s/1Hour/FORECAST/"%(cid,dp),vals,"MM","PER-CUM")
dss.close()

# Read back every cataloged DSS block belonging to each regular series.
# HEC-DSS can place a value at 00:00 on the first day of a month in the
# previous monthly block (interval-ending convention). Never infer D-parts
# from the simulation timestamps; discover the actual blocks written.
dss=HecDss.open(project_dir+"/input.dss")
catalog=list(dss.getCatalogedPathnames())

required=[]
for code in source_values.keys():
    required.append(("FLOW",code))
for cid in rain_values.keys():
    required.append(("PRECIP-INC",cid))

for kind,name in required:
    total=0
    if kind=="FLOW":
        prefix="/G040/%s/FLOW/"%name
    else:
        prefix="/G040/%s/PRECIP-INC/"%name
    suffix="/1Hour/FORECAST/"
    blocks=[path for path in catalog if path.startswith(prefix) and path.endswith(suffix)]
    blocks.sort()
    for path in blocks:
        series=dss.get(path)
        n=int(getattr(series,"numberValues",0) or 0)
        print("DSS_PREFLIGHT_BLOCK|%s|%d"%(path,n))
        total+=n
    print("DSS_PREFLIGHT_TOTAL|%s|%s|%d|expected=%d"%(kind,name,total,len(times)))
    if total != len(times):
        dss.close()
        raise RuntimeError("DSS preflight failed for %s %s: %d values != %d"%(kind,name,total,len(times)))
dss.close()

if os.path.exists(project_dir+"/output.dss"): os.remove(project_dir+"/output.dss")
OpenProject("g040_e1_hindcast",project_dir)
Compute("Hindcast")
dss=HecDss.open(project_dir+"/output.dss")
paths=list(dss.getCatalogedPathnames())
fo=open(r"{(project_dir/'hec_output_values.csv').as_posix()}","wb")
w=csv.writer(fo); w.writerow(["element","time_value","q_m3s","pathname"])
for path in paths:
    if "/FLOW/" not in path or "/RUN:Hindcast/" not in path: continue
    s=dss.get(path); parts=path.split("/"); element=parts[2] if len(parts)>2 else ""
    for i in range(s.numberValues):
        v=float(s.values[i])
        if v>-1e20: w.writerow([element,int(s.times[i]),v,path])
fo.close(); dss.close()
print("G040_E1_HINDCAST_COMPUTE_OK")
Exit(1)
""",encoding="utf-8")
    return script

def dss_time_to_utc(value):
    """HEC-DSS regular-series time is minutes since 1899-12-31 in project local time."""
    local_dt=DSS_EPOCH+timedelta(minutes=int(float(value)))
    return local_dt.replace(tzinfo=BRT).astimezone(timezone.utc)

def read_output_csv(path):
    # Catalog order is not temporal order and monthly DSS blocks can arrive in
    # either order. Preserve the real DSS timestamp, deduplicate boundaries,
    # then sort explicitly.
    by={}
    with path.open(encoding="utf-8",newline="") as fh:
        for r in csv.DictReader(fh):
            element=r["element"]
            t=dss_time_to_utc(r["time_value"])
            q=float(r["q_m3s"])
            by.setdefault(element,{})[t]=q
    return {
        element:sorted(values.items(),key=lambda x:x[0])
        for element,values in by.items()
    }

def _corr(a,b):
    if len(a)<2: return None
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    da=[x-ma for x in a]; db=[x-mb for x in b]
    den=math.sqrt(sum(x*x for x in da)*sum(x*x for x in db))
    return None if den<=0 else sum(x*y for x,y in zip(da,db))/den

def _sd(a):
    if len(a)<2: return 0.0
    m=sum(a)/len(a)
    return math.sqrt(sum((x-m)**2 for x in a)/(len(a)-1))

def score_outputs(out_by,hydro,times):
    result={}
    for code in MAIN_CHECKPOINTS:
        element="J_"+code
        sim_rows=out_by.get(element) or []
        simmap={t:q for t,q in sim_rows}
        obsmap=target_hourly(hydro,code,times)
        pairs=[]
        for t in times:
            qo=obsmap.get(t)
            qs=simmap.get(t)
            if qo is not None and qs is not None and math.isfinite(qs):
                pairs.append((t,float(qo),float(qs)))
        if len(pairs)<4:
            result[code]={"pairs":len(pairs),"status":"insufficient_observed_Q"}
            continue
        tt=[x[0] for x in pairs]; obs=[x[1] for x in pairs]; ss=[x[2] for x in pairs]
        mo=sum(obs)/len(obs); ms=sum(ss)/len(ss)
        sse=sum((a-b)**2 for a,b in zip(obs,ss)); den=sum((a-mo)**2 for a in obs)
        rmse=math.sqrt(sse/len(obs)); mae=sum(abs(a-b) for a,b in zip(obs,ss))/len(obs)
        nse=None if den<=0 else 1-sse/den
        pbias=100*sum(b-a for a,b in zip(obs,ss))/sum(obs) if sum(obs) else None
        r=_corr(obs,ss); so=_sd(obs); sm=_sd(ss)
        alpha=None if so<=0 else sm/so
        beta=None if mo==0 else ms/mo
        kge=None
        if r is not None and alpha is not None and beta is not None:
            kge=1-math.sqrt((r-1)**2+(alpha-1)**2+(beta-1)**2)
        oi=max(range(len(obs)),key=lambda i:obs[i]); si=max(range(len(ss)),key=lambda i:ss[i])
        peak_obs=obs[oi]; peak_sim=ss[si]
        peak_err=100*(peak_sim-peak_obs)/peak_obs if peak_obs else None
        peak_lag=(tt[si]-tt[oi]).total_seconds()/3600
        volume_obs=sum(obs)*3600.0; volume_sim=sum(ss)*3600.0
        volume_err=100*(volume_sim-volume_obs)/volume_obs if volume_obs else None
        do=[obs[i]-obs[i-1] for i in range(1,len(obs))]
        ds=[ss[i]-ss[i-1] for i in range(1,len(ss))]
        derivative_rmse=math.sqrt(sum((a-b)**2 for a,b in zip(do,ds))/len(do)) if do else None
        sign_hits=sum((a==0 and b==0) or (a*b>0) for a,b in zip(do,ds))
        rise_fall_skill=sign_hits/len(do) if do else None
        result[code]={
            "pairs":len(pairs),"mean_observed_m3s":mo,"mean_simulated_m3s":ms,
            "rmse_m3s":rmse,"normalized_rmse":None if mo==0 else rmse/mo,
            "mae_m3s":mae,"nse":nse,"kge":kge,"correlation":r,
            "pbias_pct":pbias,"volume_error_pct":volume_err,
            "observed_peak_m3s":peak_obs,"simulated_peak_m3s":peak_sim,
            "peak_error_pct":peak_err,
            "observed_peak_time_utc":tt[oi].isoformat().replace("+00:00","Z"),
            "simulated_peak_time_utc":tt[si].isoformat().replace("+00:00","Z"),
            "peak_timing_error_h":peak_lag,
            "derivative_rmse_m3s_h":derivative_rmse,
            "rise_fall_sign_skill":rise_fall_skill,
            "observed_last_m3s":obs[-1],"simulated_last_m3s":ss[-1],
            "last_error_pct":100*(ss[-1]-obs[-1])/obs[-1] if obs[-1] else None,
        }
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("hec_hms_sh")
    ap.add_argument("--cn",type=float,required=True)
    ap.add_argument("--lag-min",type=float,required=True)
    ap.add_argument("--k-g1",type=float,required=True)
    ap.add_argument("--k-g2",type=float,required=True)
    ap.add_argument("--k-g3",type=float,required=True)
    ap.add_argument("--k-g4",type=float,required=True)
    ap.add_argument("--x",type=float,required=True)
    ap.add_argument("--candidate-id",default="candidate")
    ap.add_argument("--event-id",default=None)
    ap.add_argument("--rain-file",type=Path,default=OBSRAIN)
    ap.add_argument("--hydro-file",type=Path,default=HYDRO)
    ap.add_argument("--score-hydro-file",type=Path,default=None,
        help="Optional untouched observed hydro package used only for verification scores. "
             "Use this in causal forecast replays so future observed boundary flow never enters forcing.")
    ap.add_argument("--score-start-utc",default=None,
        help="Optional ISO UTC time; verification metrics use only timestamps at/after this time.")
    ap.add_argument("--score-end-utc",default=None,
        help="Optional ISO UTC time; verification metrics use only timestamps at/before this time.")
    ap.add_argument("--scenario-file",type=Path,default=SCENARIOS)
    ap.add_argument("--output-root",type=Path,default=OUTROOT)
    args=ap.parse_args()
    if not (20<args.cn<95): raise SystemExit("CN outside physical search domain")
    if not (1<=args.lag_min<=600): raise SystemExit("lag outside search domain")
    if not (0<=args.x<=0.5): raise SystemExit("Muskingum X outside [0,0.5]")

    rainpkg=loadj(args.rain_file); hydro=loadj(args.hydro_file); scenarios=loadj(args.scenario_file)
    score_hydro=loadj(args.score_hydro_file) if args.score_hydro_file else hydro
    if rainpkg.get("status") not in {"OBSERVED_RAIN_READY","OBSERVED_RAIN_PARTIAL","CAUSAL_FORECAST_RAIN_READY"}:
        raise RuntimeError("G040 rain forcing not ready")
    current=scenarios.get("current") or {}
    active=[str(x) for x in current.get("active_boundary_codes") or []]
    if str((rainpkg.get("boundary_scenario") or {}).get("name"))!=str(scenarios.get("current_scenario")):
        raise RuntimeError("rain/hydro scenario mismatch")
    rain=rain_components(rainpkg)
    start,end,used=choose_window(rain,hydro,active)
    # Through Porto Mariante only.
    used=[cid for cid in used if cid in CORE_TO_CHECKPOINT or cid in {"BRANCH_86500000","BRANCH_86595000","BRANCH_86746000"}]
    times=hourly_axis(start,end)

    source_values={code:source_hourly(hydro,code,times) for code in [SOURCE_PRIMARY,*active]}
    score_start=utc(args.score_start_utc) if args.score_start_utc else None
    score_end=utc(args.score_end_utc) if args.score_end_utc else None
    score_times=[t for t in times if (score_start is None or t>=score_start) and (score_end is None or t<=score_end)]
    if (score_start or score_end) and not score_times:
        raise RuntimeError("score window does not overlap HEC simulation window")
    rain_values={}
    for cid in used:
        vals=[rain_at(rain[cid]["rows"],t) for t in times]
        if any(v is None for v in vals):
            raise RuntimeError(f"{cid}: missing observed rainfall inside HEC hindcast window")
        rain_values[safe(cid)]=[float(v) for v in vals]

    rt=Path(args.output_root)/safe(args.candidate_id)
    rt.mkdir(parents=True,exist_ok=True)
    proj=rt/"project"; proj.mkdir(parents=True,exist_ok=True)
    project_text=build_project()
    run_text=build_run()
    control_text=build_control(start,end)
    gage_text=build_gage(start,end,active,used)
    met_text=build_met(used)
    basin_text=build_basin(rain,active,args)
    preflight=validate_project_contract(gage_text,met_text,basin_text,active,used)

    (proj/"g040_e1_hindcast.hms").write_text(project_text,encoding="utf-8")
    (proj/"g040_e1_hindcast.run").write_text(run_text,encoding="utf-8")
    (proj/"e1.control").write_text(control_text,encoding="utf-8")
    (proj/"g040_e1_hindcast.gage").write_text(gage_text,encoding="utf-8")
    (proj/"e1.met").write_text(met_text,encoding="utf-8")
    (proj/"e1.basin").write_text(basin_text,encoding="utf-8")
    script=write_jython(proj,times,source_values,rain_values)

    proc=subprocess.run([str(Path(args.hec_hms_sh).resolve()),"-s",str(script.resolve())],
        cwd=Path(args.hec_hms_sh).resolve().parent,capture_output=True,text=True,timeout=240,check=False)
    (rt/"run.log").write_text(proc.stdout+"\n--- STDERR ---\n"+proc.stderr,encoding="utf-8")
    ok="G040_E1_HINDCAST_COMPUTE_OK" in proc.stdout and (proj/"hec_output_values.csv").exists()
    scores={}
    if ok: scores=score_outputs(read_output_csv(proj/"hec_output_values.csv"),score_hydro,score_times)
    result={"schema_version":"g040_e1_hindcast_candidate_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_only":True,"candidate_id":args.candidate_id,"event_id":args.event_id,"hec_hms_version":"4.13",
      "compute_ok":ok,"returncode":proc.returncode,
      "window":{"start_utc":start.isoformat().replace("+00:00","Z"),
                "end_utc":end.isoformat().replace("+00:00","Z"),"hours":len(times)},
      "score_window":{"start_utc":score_times[0].isoformat().replace("+00:00","Z") if score_times else None,
                      "end_utc":score_times[-1].isoformat().replace("+00:00","Z") if score_times else None,
                      "hours":len(score_times)},
      "boundary_scenario":scenarios.get("current_scenario"),"active_boundary_codes":active,
      "input_artifacts":{"rain_file":str(Path(args.rain_file)),"hydro_file":str(Path(args.hydro_file)),
        "score_hydro_file":str(Path(args.score_hydro_file)) if args.score_hydro_file else str(Path(args.hydro_file)),
        "scenario_file":str(Path(args.scenario_file))},
      "rainfall_runoff_components":used,
      "preflight_contract":preflight,
      "parameters":{"cn":args.cn,"lag_min":args.lag_min,"baseflow":"None",
        "k_group_h":{"g1":args.k_g1,"g2":args.k_g2,"g3":args.k_g3,"g4":args.k_g4},
        "x":args.x,
        "compute_interval_min":COMPUTE_INTERVAL_MIN,
        "reach_k_h":{name:route_k(l,g,args) for name,up,down,l,g in REACHES},
        "muskingum_subreaches":{
          name:muskingum_steps(route_k(l,g,args),args.x)
          for name,up,down,l,g in REACHES
        }},
      "scores":scores,
      "limitations":["event-specific E1 candidate; multi-event selection is performed by the calibration orchestrator","baseflow method not documented in recovered original report",
        "global CN and lag are temporary calibration parameterization, not 145-subbasin transfer",
        "model stops at Porto Mariante until lower-TaQ routing/backwater evidence is closed",
        "when score_hydro_file differs from hydro_file, future observations are verification-only and never enter forcing"],
      "promotion_allowed":False}
    (rt/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
    return 0 if ok else 2

if __name__=="__main__": raise SystemExit(main())
