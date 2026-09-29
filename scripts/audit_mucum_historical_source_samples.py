#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spot-check Muçum historical calibration inputs against fresh ANA telemetry.

Purpose
-------
Independently re-download a few *promoted* historical Muçum events from the
official ANA ServiceANA endpoint on a clean GitHub runner and compare them with
what is archived in this repository.

Checks:
1) Rain forcing station 86472000:
   fresh ANA Chuva (15-min/subhourly summed to local clock-hour) vs
   assets/data/chuvas_horarias.csv column chuva_86472000.
2) Muçum target station 86510000:
   fresh ANA Nivel/Vazao vs archived raw XML used by the calibration audit.

No model is trained or modified by this script.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/data/hec_hms_audit/mucum_historical_source_spotcheck"
OUT.mkdir(parents=True, exist_ok=True)
RAIN_CSV = ROOT / "assets/data/chuvas_horarias.csv"

ANA_PRIMARY = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA_MIRROR = "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"
UA = "PREVINE-mucum-historical-source-spotcheck/1.0"

EVENTS = {
    # The three promoted HEC-HMS historical replays that matter most to the
    # current Muçum calibration lineage.
    "E24": {
        "start": datetime(2023, 11, 16, 0, 0),
        "end": datetime(2023, 11, 25, 23, 45),
        "target_raw": ROOT / "assets/data/hec_hms_audit/raw/ana/supplemental/telemetry_86510000_E24.xml",
    },
    "E27": {
        "start": datetime(2024, 4, 29, 0, 0),
        "end": datetime(2024, 5, 9, 23, 45),
        "target_raw": ROOT / "assets/data/hec_hms_audit/raw/ana/supplemental/telemetry_86510000_E27.xml",
    },
    "E28": {
        "start": datetime(2024, 6, 16, 0, 0),
        "end": datetime(2024, 6, 25, 23, 45),
        "target_raw": ROOT / "assets/data/hec_hms_audit/raw/ana/supplemental/telemetry_86510000_E28.xml",
    },
}


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fnum(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if not s:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def parse_time(v):
    s = str(v or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            pass
    return None


def fetch_ana(code: str, start: datetime, end: datetime) -> tuple[bytes, str]:
    params = urllib.parse.urlencode({
        "codEstacao": code,
        "dataInicio": start.strftime("%d/%m/%Y"),
        "dataFim": end.strftime("%d/%m/%Y"),
    })
    errors = []
    for base in (ANA_PRIMARY, ANA_MIRROR):
        url = base + "?" + params
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "text/xml,application/xml,*/*"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            if not raw:
                raise RuntimeError("empty response")
            return raw, url
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(" | ".join(errors))


def parse_rows(raw: bytes):
    root = ET.fromstring(raw)
    roots = [root]
    if (root.text or "").strip().startswith("<"):
        try:
            roots.append(ET.fromstring(root.text))
        except Exception:
            pass
    out = {}
    for rt in roots:
        for node in rt.iter():
            fields = {lname(ch.tag): (ch.text or "") for ch in node}
            stamp = fields.get("DataHora") or fields.get("Data_Hora")
            if not stamp:
                continue
            t = parse_time(stamp)
            if t is None:
                continue
            item = {
                "rain_mm": fnum(fields.get("Chuva") or fields.get("chuva") or fields.get("Precipitacao")),
                "level": fnum(fields.get("Nivel") or fields.get("nivel")),
                "flow_m3s": fnum(fields.get("Vazao") or fields.get("vazao")),
            }
            # If duplicate rows exist, the last identical timestamp from the
            # official response wins; the report will expose counts.
            out[t] = item
    return out


def aggregate_rain_hourly(rows, start, end):
    hourly = {}
    counts = {}
    for t, v in rows.items():
        if not (start <= t <= end):
            continue
        rain = v.get("rain_mm")
        if rain is None or rain < 0:
            continue
        h = t.replace(minute=0, second=0, microsecond=0)
        hourly[h] = hourly.get(h, 0.0) + rain
        counts[h] = counts.get(h, 0) + 1
    return hourly, counts


def load_archived_rain(start, end):
    out = {}
    with RAIN_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            code = str(row.get("COD_SEQUENCIAL") or "").strip()
            try:
                t = datetime.strptime(code, "%Y%m%d%H%M")
            except ValueError:
                continue
            if t < start.replace(minute=0, second=0, microsecond=0):
                continue
            if t > end.replace(minute=0, second=0, microsecond=0):
                continue
            val = fnum(row.get("chuva_86472000"))
            if val is not None:
                out[t] = val
    return out


def compare_scalar_maps(a, b, tol):
    common = sorted(set(a) & set(b))
    diffs = [abs(float(a[t]) - float(b[t])) for t in common]
    mism = [(t, a[t], b[t], abs(float(a[t]) - float(b[t]))) for t in common if abs(float(a[t])-float(b[t])) > tol]
    return {
        "a_count": len(a),
        "b_count": len(b),
        "common_count": len(common),
        "a_only_count": len(set(a)-set(b)),
        "b_only_count": len(set(b)-set(a)),
        "match_within_tolerance": len(common)-len(mism),
        "mismatch_count": len(mism),
        "match_pct_common": None if not common else round(100*(len(common)-len(mism))/len(common), 3),
        "mean_abs_diff": None if not diffs else round(statistics.fmean(diffs), 6),
        "max_abs_diff": None if not diffs else round(max(diffs), 6),
        "mismatch_examples": [
            {"time": t.isoformat(" "), "fresh": av, "archived": bv, "abs_diff": round(d, 6)}
            for t,av,bv,d in mism[:12]
        ],
    }


def load_archived_target(path):
    return parse_rows(path.read_bytes())


def compare_target(fresh, archived, start, end):
    times = sorted(
        t for t in (set(fresh) & set(archived))
        if start <= t <= end
    )
    lvl_diffs=[]; q_diffs=[]; lvl_mism=[]; q_mism=[]
    for t in times:
        fl=fresh[t].get("level"); al=archived[t].get("level")
        fq=fresh[t].get("flow_m3s"); aq=archived[t].get("flow_m3s")
        if fl is not None and al is not None:
            d=abs(fl-al); lvl_diffs.append(d)
            if d > 0.01: lvl_mism.append((t,fl,al,d))
        if fq is not None and aq is not None:
            d=abs(fq-aq); q_diffs.append(d)
            if d > 0.11: q_mism.append((t,fq,aq,d))
    fresh_event={t:v for t,v in fresh.items() if start<=t<=end}
    arch_event={t:v for t,v in archived.items() if start<=t<=end}
    def peak(which, field):
        vals=[(t,v[field]) for t,v in which.items() if v.get(field) is not None]
        return None if not vals else max(vals,key=lambda x:x[1])
    return {
        "fresh_rows": len(fresh_event),
        "archived_rows": len(arch_event),
        "common_timestamps": len(times),
        "fresh_only_timestamps": len(set(fresh_event)-set(arch_event)),
        "archived_only_timestamps": len(set(arch_event)-set(fresh_event)),
        "level": {
            "paired": len(lvl_diffs),
            "mismatch_count_gt_0_01": len(lvl_mism),
            "mean_abs_diff": None if not lvl_diffs else round(statistics.fmean(lvl_diffs),6),
            "max_abs_diff": None if not lvl_diffs else round(max(lvl_diffs),6),
            "fresh_peak": None if peak(fresh_event,"level") is None else {
                "time":peak(fresh_event,"level")[0].isoformat(" "),"value":peak(fresh_event,"level")[1]},
            "archived_peak": None if peak(arch_event,"level") is None else {
                "time":peak(arch_event,"level")[0].isoformat(" "),"value":peak(arch_event,"level")[1]},
            "mismatch_examples": [
                {"time":t.isoformat(" "),"fresh":a,"archived":b,"abs_diff":round(d,6)}
                for t,a,b,d in lvl_mism[:12]
            ],
        },
        "flow": {
            "paired": len(q_diffs),
            "mismatch_count_gt_0_11": len(q_mism),
            "mean_abs_diff": None if not q_diffs else round(statistics.fmean(q_diffs),6),
            "max_abs_diff": None if not q_diffs else round(max(q_diffs),6),
            "fresh_peak": None if peak(fresh_event,"flow_m3s") is None else {
                "time":peak(fresh_event,"flow_m3s")[0].isoformat(" "),"value":peak(fresh_event,"flow_m3s")[1]},
            "archived_peak": None if peak(arch_event,"flow_m3s") is None else {
                "time":peak(arch_event,"flow_m3s")[0].isoformat(" "),"value":peak(arch_event,"flow_m3s")[1]},
            "mismatch_examples": [
                {"time":t.isoformat(" "),"fresh":a,"archived":b,"abs_diff":round(d,6)}
                for t,a,b,d in q_mism[:12]
            ],
        },
    }


def choose_rain_examples(fresh_hourly, archived_hourly, n=6):
    common=sorted(set(fresh_hourly)&set(archived_hourly))
    if not common:
        return []
    # Prefer largest observed rain hours, then add chronological boundaries.
    ranked=sorted(common,key=lambda t:fresh_hourly[t],reverse=True)
    selected=[]
    for t in ranked[:max(3,n-2)] + [common[0],common[-1]]:
        if t not in selected:
            selected.append(t)
        if len(selected)>=n:
            break
    return [
        {
            "time":t.isoformat(" "),
            "fresh_ANA_mm":round(fresh_hourly[t],3),
            "archived_CSV_mm":round(archived_hourly[t],3),
            "diff_mm":round(archived_hourly[t]-fresh_hourly[t],3),
        }
        for t in selected
    ]


def choose_target_examples(fresh, archived, start, end, n=6):
    common=sorted(t for t in set(fresh)&set(archived) if start<=t<=end)
    if not common:
        return []
    vals=[t for t in common if fresh[t].get("level") is not None and archived[t].get("level") is not None]
    ranked=sorted(vals,key=lambda t:fresh[t]["level"],reverse=True)
    selected=[]
    for t in ranked[:3] + ([vals[0], vals[len(vals)//2], vals[-1]] if vals else []):
        if t not in selected:
            selected.append(t)
        if len(selected)>=n:
            break
    return [
        {
            "time":t.isoformat(" "),
            "fresh_level":fresh[t].get("level"),
            "archived_level":archived[t].get("level"),
            "fresh_q":fresh[t].get("flow_m3s"),
            "archived_q":archived[t].get("flow_m3s"),
        }
        for t in selected
    ]


def main():
    report={
        "schema_version":"mucum_historical_source_spotcheck_v1",
        "generated_at_utc":datetime.utcnow().isoformat()+"Z",
        "source":"ANA ServiceANA/DadosHidrometeorologicos fresh download on GitHub Actions",
        "scope":"spot-check of E24, E27, E28 only; no model changes",
        "fresh_runner_note":"workflow runs on GitHub-hosted ubuntu-latest, not on the user's computer",
        "events":[],
    }
    csv_rows=[]
    for event_id,cfg in EVENTS.items():
        start,end=cfg["start"],cfg["end"]
        fresh_rain_raw,rain_url=fetch_ana("86472000",start,end)
        fresh_target_raw,target_url=fetch_ana("86510000",start,end)
        fresh_rain_rows=parse_rows(fresh_rain_raw)
        fresh_target=parse_rows(fresh_target_raw)
        fresh_hourly,subcounts=aggregate_rain_hourly(fresh_rain_rows,start,end)
        archived_hourly=load_archived_rain(start,end)
        rain_cmp=compare_scalar_maps(fresh_hourly,archived_hourly,tol=0.011)

        archived_target=load_archived_target(cfg["target_raw"])
        target_cmp=compare_target(fresh_target,archived_target,start,end)

        # Critical contamination checks.
        false_zeros=[
            t for t in set(fresh_hourly)&set(archived_hourly)
            if fresh_hourly[t] > 0.011 and abs(archived_hourly[t]) <= 0.001
        ]
        source_missing_but_archive_zero=[
            t for t in set(archived_hourly)-set(fresh_hourly)
            if abs(archived_hourly[t]) <= 0.001
        ]

        event={
            "event_id":event_id,
            "period_local":{"start":start.isoformat(" "),"end":end.isoformat(" ")},
            "rain_station":"86472000",
            "target_station":"86510000",
            "fresh_urls":{"rain":rain_url,"target":target_url},
            "rain_comparison":rain_cmp,
            "rain_false_zero_count_where_fresh_positive":len(false_zeros),
            "rain_archive_zero_while_fresh_missing_count":len(source_missing_but_archive_zero),
            "rain_examples":choose_rain_examples(fresh_hourly,archived_hourly),
            "target_comparison":target_cmp,
            "target_examples":choose_target_examples(fresh_target,archived_target,start,end),
            "verdict":(
                "MATCH"
                if rain_cmp["mismatch_count"]==0
                and len(false_zeros)==0
                and target_cmp["level"]["mismatch_count_gt_0_01"]==0
                and target_cmp["flow"]["mismatch_count_gt_0_11"]==0
                else "REVIEW"
            ),
        }
        report["events"].append(event)
        for ex in event["rain_examples"]:
            csv_rows.append({"event":event_id,"kind":"rain","time":ex["time"],
                             "fresh":ex["fresh_ANA_mm"],"archived":ex["archived_CSV_mm"],
                             "difference":ex["diff_mm"]})
        for ex in event["target_examples"]:
            csv_rows.append({"event":event_id,"kind":"level","time":ex["time"],
                             "fresh":ex["fresh_level"],"archived":ex["archived_level"],
                             "difference":None if ex["fresh_level"] is None or ex["archived_level"] is None else ex["archived_level"]-ex["fresh_level"]})
            csv_rows.append({"event":event_id,"kind":"flow","time":ex["time"],
                             "fresh":ex["fresh_q"],"archived":ex["archived_q"],
                             "difference":None if ex["fresh_q"] is None or ex["archived_q"] is None else ex["archived_q"]-ex["fresh_q"]})

    report["overall_verdict"]="MATCH" if all(x["verdict"]=="MATCH" for x in report["events"]) else "REVIEW"
    (OUT/"mucum_historical_source_spotcheck_latest.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    with (OUT/"mucum_historical_source_spotcheck_examples.csv").open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=["event","kind","time","fresh","archived","difference"])
        w.writeheader(); w.writerows(csv_rows)
    print(json.dumps({
        "overall_verdict":report["overall_verdict"],
        "events":[{
            "event_id":e["event_id"],
            "verdict":e["verdict"],
            "rain":e["rain_comparison"],
            "false_zeros":e["rain_false_zero_count_where_fresh_positive"],
            "target_level":e["target_comparison"]["level"],
            "target_flow":e["target_comparison"]["flow"],
        } for e in report["events"]]
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
