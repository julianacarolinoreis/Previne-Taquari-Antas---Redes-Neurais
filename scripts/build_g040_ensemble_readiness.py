#!/usr/bin/env python3
"""Build a variable-aware ensemble member inventory for G040.

The inventory prevents invalid averaging across stage and discharge and records
the evidence required before a member can receive a skill weight.

Research only.
"""
from __future__ import annotations
import csv, json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STACK=ROOT/"assets/data/g040_hydro_stack"
ST2=ROOT/"assets/data/santa_tereza_eventwise_replay_rna_2h/eventwise_manifest.json"
ST2MET=ROOT/"assets/data/santa_tereza_eventwise_replay_rna_2h/events_metrics.csv"
RNA8=ROOT/"assets/data/estudo_bacia_taquari_antas/treino_rna_stz_mucum_v1_latest.json"
E1=ROOT/"assets/data/hec_hms_g040_full_basin/g040_e1_hindcast/SMOKE_E1/result.json"
MGB=STACK/"mgb_input_readiness_latest.json"
OUT=STACK/"ensemble_member_inventory_latest.json"

def load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def main():
    st2=load(ST2); rna8=load(RNA8); e1=load(E1); mgb=load(MGB)
    test_events=[]
    if ST2MET.exists():
        with ST2MET.open(encoding="utf-8",newline="") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("papel_avaliacao") or "").lower()=="teste_independente":
                    test_events.append({
                        "evento":r.get("evento"),
                        "inicio":r.get("inicio"),
                        "fim":r.get("fim"),
                        "mae_cm":float(r["mae_cm"]) if r.get("mae_cm") else None,
                        "peak_timing_error_h":float(r["atraso_pico_horas"]) if r.get("atraso_pico_horas") else None,
                    })

    members=[
        {
            "member_id":"RNA_STZ_2H_EVENTWISE",
            "family":"RNA",
            "location":"Santa Tereza",
            "target_variable":"stage",
            "target_unit":"cm",
            "horizon_h":2,
            "status":st2.get("status"),
            "auditable_event_replay":bool(st2),
            "independent_test_events":test_events,
            "eligible_for_skill_weight":bool(test_events),
            "limitations":[
                "stage member only; not discharge",
                "cannot be averaged with discharge HEC/MGB output without a validated common-variable mapping",
                "eventwise replay package is research-only",
            ],
        }
    ]
    models=rna8.get("models") or {}
    for key,label,station in [
        ("santa_tereza","RNA_STZ_8H_RESEARCH","Santa Tereza"),
        ("mucum","RNA_MUCUM_8H_RESEARCH","Muçum"),
    ]:
        m=models.get(key) or {}
        test=((m.get("metrics") or {}).get("Teste") or {})
        members.append({
            "member_id":label,
            "family":"RNA",
            "location":station,
            "target_variable":"stage",
            "target_unit":"cm",
            "horizon_h":8,
            "status":rna8.get("status"),
            "test_metrics":test,
            "eligible_for_skill_weight":bool(test.get("n")) and float(test.get("skill_rmse_vs_pers") or 0)>0,
            "limitations":[
                "research MLP, not the operational MATLAB model",
                "must be replayed on the same fixed benchmark events before cross-model weighting",
                "stage-only output",
            ],
        })

    members.append({
        "member_id":"HEC_HMS_G040_BRANCH",
        "family":"HEC-HMS",
        "location":"G040 mainstem branch model",
        "target_variable":"discharge",
        "target_unit":"m3/s",
        "horizon_h":None,
        "status":"compute_ok" if e1.get("compute_ok") else "smoke_compute_pending",
        "eligible_for_skill_weight":bool(e1.get("compute_ok")) and bool(e1.get("scores")),
        "limitations":["event-model branch representation until continuous SMA is calibrated"],
    })
    members.append({
        "member_id":"MGB_G040",
        "family":"MGB",
        "location":"G040",
        "target_variable":"discharge",
        "target_unit":"m3/s",
        "horizon_h":None,
        "status":mgb.get("status") or "input_readiness_not_built",
        "eligible_for_skill_weight":False,
        "limitations":["model has not yet completed source-backed preprocessing/calibration"],
    })

    eligible=[m for m in members if m["eligible_for_skill_weight"]]
    groups={}
    for m in eligible:
        key=(
            str(m.get("target_variable")),
            str(m.get("target_unit")),
            str(m.get("location")),
            str(m.get("horizon_h")),
        )
        groups.setdefault(key,[]).append(m["member_id"])
    compatible_groups=[
        {
            "target_variable":k[0],
            "target_unit":k[1],
            "location":k[2],
            "horizon_h":None if k[3]=="None" else float(k[3]),
            "member_ids":v,
            "member_count":len(v),
            "ensemble_ready":len(v)>=2,
        }
        for k,v in sorted(groups.items())
    ]
    stage_ready=[m for m in eligible if m["target_variable"]=="stage"]
    q_ready=[m for m in eligible if m["target_variable"]=="discharge"]
    stage_groups_ready=[g for g in compatible_groups if g["target_variable"]=="stage" and g["ensemble_ready"]]
    q_groups_ready=[g for g in compatible_groups if g["target_variable"]=="discharge" and g["ensemble_ready"]]
    payload={
        "schema_version":"g040_ensemble_member_inventory_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "members":members,
        "compatibility":{
            "stage_ready_member_ids":[m["member_id"] for m in stage_ready],
            "discharge_ready_member_ids":[m["member_id"] for m in q_ready],
            "compatible_groups":compatible_groups,
            "ready_stage_groups":stage_groups_ready,
            "ready_discharge_groups":q_groups_ready,
            "cross_variable_averaging_allowed":False,
            "rule":"weights may be estimated only among members predicting the same target variable/unit at the same location/horizon, or after an independently validated transformation",
            "rating_curve_rule":"never invent stage-discharge conversion",
        },
        "weighting_gate":{
            "fixed_benchmark_required":True,
            "simple_mean_default":False,
            "same_events_checkpoints_metrics_required":True,
            "minimum_ready_members_per_target":2,
            "stage_ensemble_ready":bool(stage_groups_ready),
            "discharge_ensemble_ready":bool(q_groups_ready),
        },
        "promotion_allowed":False,
    }
    STACK.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "stage_ready_members":[m["member_id"] for m in stage_ready],
        "discharge_ready_members":[m["member_id"] for m in q_ready],
        "compatible_groups_ready":[g for g in compatible_groups if g["ensemble_ready"]],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
