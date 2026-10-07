#!/usr/bin/env python3
"""Compare frozen antecedent-adaptive HEC arm with the fixed frozen arm."""
from __future__ import annotations
import json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.run_hec_hms_g040_e1_hindcast import MAIN_CHECKPOINTS, interp, read_output_csv, series_control
    from scripts.evaluate_g040_causal_benchmark import observed_level_rows, stage_timing_score
except ModuleNotFoundError:
    from run_hec_hms_g040_e1_hindcast import MAIN_CHECKPOINTS, interp, read_output_csv, series_control
    from evaluate_g040_causal_benchmark import observed_level_rows, stage_timing_score

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/hec_hms_g040_full_basin"
FIXED=BASE/"causal_frozen_benchmark"
ADAPT=BASE/"antecedent_adaptive_benchmark"
CFG=ROOT/"config/g040_causal_frozen_benchmark_v1.json"
SELECT=BASE/"g040_frozen_antecedent_selection_latest.json"
OUT=ADAPT/"summary_latest.json"
HORIZONS=(6,12,24,48,72)

def load(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def utc(v:str)->datetime:
    d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def wape(pairs):
    den=sum(abs(o) for _t,o,_s in pairs)
    return None if not pairs or den<=0 else sum(abs(s-o) for _t,o,s in pairs)/den

def median(xs):
    xs=sorted(x for x in xs if x is not None)
    if not xs:return None
    n=len(xs)
    return xs[n//2] if n%2 else (xs[n//2-1]+xs[n//2])/2

def output_csv(root:Path)->Path:
    files=list((root/"hec_runs").glob("*/project/hec_output_values.csv"))
    if len(files)!=1:
        raise RuntimeError(f"{root}: expected one output CSV, found {len(files)}")
    return files[0]

def evaluate_case(case,selection):
    cid=case["case_id"]; event=case["event_id"]
    froot=FIXED/cid; aroot=ADAPT/cid
    hydro=load(froot/"hydro_scoring.json")
    fixed=read_output_csv(output_csv(froot))
    adaptive=read_output_csv(output_csv(aroot))
    t0=utc(case["decision_time_utc"])
    end=t0+timedelta(hours=72)
    primary=str((load(froot/"manifest.json")).get("primary_source_code") or "")

    stations=[]
    agg={h:{"fixed_all":[],"adaptive_all":[],"fixed_comp":[],"adaptive_comp":[],"persist":[]} for h in HORIZONS}
    for code in MAIN_CHECKPOINTS:
        if code==primary: continue
        try:_c,obsrows=series_control(hydro,code)
        except Exception:obsrows=[]
        q0=interp(obsrows,t0) if obsrows else None
        fm={t:q for t,q in fixed.get("J_"+code,[])}
        am={t:q for t,q in adaptive.get("J_"+code,[])}
        common=sorted(set(fm)&set(am))
        pairs=[]
        for t in common:
            if t<t0 or t>end:continue
            qo=interp(obsrows,t) if obsrows else None
            if qo is None:continue
            fs=fm[t]; aa=am[t]
            if not math.isfinite(fs) or not math.isfinite(aa):continue
            pairs.append((t,float(qo),float(fs),float(aa)))
        hrows={}
        for h in HORIZONS:
            lim=t0+timedelta(hours=h)
            p=[x for x in pairs if x[0]<=lim]
            fp=[(t,o,f) for t,o,f,a in p]
            ap=[(t,o,a) for t,o,f,a in p]
            agg[h]["fixed_all"].extend(fp);agg[h]["adaptive_all"].extend(ap)
            pp=[]
            if q0 is not None:
                pp=[(t,o,float(q0)) for t,o,f,a in p]
                agg[h]["fixed_comp"].extend(fp);agg[h]["adaptive_comp"].extend(ap);agg[h]["persist"].extend(pp)
            fw=wape(fp);aw=wape(ap);pw=wape(pp)
            hrows[str(h)]={
                "pairs":len(p),
                "fixed_wape":fw,
                "adaptive_wape":aw,
                "adaptive_skill_vs_fixed_pct":None if fw in (None,0) or aw is None else 100*(1-aw/fw),
                "persistence_wape":pw,
                "adaptive_skill_vs_persistence_pct":None if pw in (None,0) or aw is None else 100*(1-aw/pw),
            }
        fixed_stage=stage_timing_score(fm,observed_level_rows(hydro,code),t0,end)
        adapt_stage=stage_timing_score(am,observed_level_rows(hydro,code),t0,end)
        if pairs or fixed_stage or adapt_stage:
            stations.append({
                "code":code,"q_at_t0_m3s":q0,"horizons":hrows,
                "fixed_stage_validation":fixed_stage,
                "adaptive_stage_validation":adapt_stage,
            })
    aggregate={}
    for h in HORIZONS:
        fw=wape(agg[h]["fixed_all"]);aw=wape(agg[h]["adaptive_all"])
        fc=wape(agg[h]["fixed_comp"]);ac=wape(agg[h]["adaptive_comp"]);pw=wape(agg[h]["persist"])
        aggregate[str(h)]={
            "all_available_pairs":len(agg[h]["adaptive_all"]),
            "fixed_wape_all_available":fw,
            "adaptive_wape_all_available":aw,
            "adaptive_skill_vs_fixed_all_available_pct":None if fw in (None,0) or aw is None else 100*(1-aw/fw),
            "comparable_persistence_pairs":len(agg[h]["persist"]),
            "fixed_wape_comparable":fc,
            "adaptive_wape_comparable":ac,
            "persistence_wape":pw,
            "adaptive_skill_vs_persistence_pct":None if pw in (None,0) or ac is None else 100*(1-ac/pw),
        }
    return {
        "case_id":cid,"event_id":event,"split":case["split"],
        "selected_donor_event_id":selection["selected_donor_event_id"],
        "selected_candidate_id":selection["selected_candidate_id"],
        "distance":selection["distance"],
        "stations":stations,"aggregate":aggregate,
    }

def main()->int:
    cfg=load(CFG); sel=load(SELECT)
    smap={x["target_event_id"]:x for x in sel["selections"]}
    rows=[evaluate_case(c,smap[c["event_id"]]) for c in cfg["cases"]]
    grand={}
    for h in HORIZONS:
        grand[str(h)]={
            "case_count":len(rows),
            "median_fixed_wape_all_available":median([r["aggregate"][str(h)]["fixed_wape_all_available"] for r in rows]),
            "median_adaptive_wape_all_available":median([r["aggregate"][str(h)]["adaptive_wape_all_available"] for r in rows]),
            "median_adaptive_skill_vs_fixed_pct":median([r["aggregate"][str(h)]["adaptive_skill_vs_fixed_all_available_pct"] for r in rows]),
            "adaptive_wins_vs_fixed":sum((r["aggregate"][str(h)]["adaptive_skill_vs_fixed_all_available_pct"] or -1e9)>0 for r in rows),
            "median_adaptive_skill_vs_persistence_pct":median([r["aggregate"][str(h)]["adaptive_skill_vs_persistence_pct"] for r in rows]),
        }
    payload={
        "schema_version":"g040_antecedent_adaptive_benchmark_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"FROZEN_ANTECEDENT_ADAPTIVE_REPLAY_COMPLETE",
        "no_validation_leakage":True,
        "selection_ref":str(SELECT.relative_to(ROOT)),
        "comparison":"same causal observed/ECMWF forcing and boundary; parameters only differ by frozen antecedent donor selection",
        "grand_summary":grand,
        "cases":rows,
        "promotion_allowed":False,
    }
    ADAPT.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"grand_summary":grand},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
