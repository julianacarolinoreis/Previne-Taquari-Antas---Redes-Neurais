#!/usr/bin/env python3
"""Search reach-routing parameters for the E24 Muçum HEC-HMS replay.

Research-only experiment. It holds rainfall-runoff parameters and forcing fixed and
changes only Muskingum routing in the two BHO6 reaches:
86472000 -> 86472600 -> 86510000.

The objective is dominated by Muçum discharge fit (NSE, peak magnitude and timing).
When ANA level at Santa Tereza is available, its peak timing is used only as a weak
timing proxy; stage magnitude is never compared with simulated discharge.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/data/hec_hms_integrated_taquari_antas/network_replay_e24_censored_transfer/three_station/E24"
OUT = ROOT / "assets/data/hec_hms_integrated_taquari_antas/routing_profile_e24"
WORK = OUT / "work"
EVENT_ID = "E24"
PROJECT = "taquari_antas_E24"
START = datetime(2023, 11, 16, 0, 0)
END = datetime(2023, 11, 24, 19, 0)
ANA_PRIMARY = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA_MIRROR = "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"

REACHES = {
    "R_ANTAS_STZ_E24": {"length_km": 20.872, "terrain_slope_diag": 0.0006468},
    "R_STZ_MUCUM_E24": {"length_km": 23.652, "terrain_slope_diag": 0.0006765},
}


def finite(v):
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_time(value: str | None):
    text = str(value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            pass
    return None


def fetch_ana_level(code: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    params = urllib.parse.urlencode({
        "codEstacao": code,
        "dataInicio": start.strftime("%d/%m/%Y"),
        "dataFim": end.strftime("%d/%m/%Y"),
    })
    errors = []
    for base in (ANA_PRIMARY, ANA_MIRROR):
        try:
            req = urllib.request.Request(
                f"{base}?{params}",
                headers={"User-Agent": "previne-hec-routing-e24/1.0", "Accept": "text/xml,application/xml,*/*"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
            root = ET.fromstring(raw)
            roots = [root]
            if (root.text or "").strip().startswith("<"):
                try:
                    roots.append(ET.fromstring(root.text))
                except Exception:
                    pass
            rows = []
            seen = set()
            for rt in roots:
                for node in rt.iter():
                    fields = {lname(ch.tag): (ch.text or "") for ch in node}
                    stamp = fields.get("DataHora") or fields.get("Data_Hora")
                    if not stamp:
                        continue
                    dt = parse_time(stamp)
                    level = finite(fields.get("Nivel") or fields.get("nivel"))
                    if dt is None or level is None or dt < start or dt > end:
                        continue
                    key = (dt, level)
                    if key not in seen:
                        seen.add(key)
                        rows.append(key)
            if rows:
                return sorted(rows)
            errors.append(f"{base}: sem nível")
        except Exception as exc:
            errors.append(f"{base}: {exc}")
    print("WARN Santa Tereza ANA: " + " | ".join(errors[-2:]))
    return []


def observed_timing(rows: list[tuple[datetime, float]]) -> dict:
    if not rows:
        return {"available": False}
    peak_time, peak = max(rows, key=lambda x: x[1])
    best = None
    for i, (t0, v0) in enumerate(rows):
        for j in range(i + 1, min(i + 20, len(rows))):
            t1, v1 = rows[j]
            dh = (t1 - t0).total_seconds() / 3600.0
            if dh < 0.75:
                continue
            if dh > 1.5:
                break
            rate = (v1 - v0) / dh
            if best is None or rate > best[0]:
                best = (rate, t1)
    return {
        "available": True,
        "n": len(rows),
        "peak_level_source_unit": peak,
        "peak_time_local": peak_time.isoformat(),
        "max_rise_rate_source_unit_per_h": None if best is None else round(best[0], 4),
        "max_rise_time_local": None if best is None else best[1].isoformat(),
    }


def replace_reach_param(text: str, reach: str, field: str, value: float) -> str:
    pattern = re.compile(r"(?ms)(^Reach: " + re.escape(reach) + r"\n.*?^End:\s*$)")
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"reach not found: {reach}")
    block = match.group(1)
    block2, n = re.subn(rf"(?m)^(\s*{re.escape(field)}:\s*)[-+0-9.eE]+$", rf"\g<1>{value:.3f}", block, count=1)
    if n != 1:
        raise RuntimeError(f"field {field} not found in {reach}")
    return text[:match.start()] + block2 + text[match.end():]


def write_candidate_basin(base_text: str, k1: float, k2: float, x: float) -> None:
    text = base_text
    text = replace_reach_param(text, "R_ANTAS_STZ_E24", "Muskingum K", k1)
    text = replace_reach_param(text, "R_ANTAS_STZ_E24", "Muskingum x", x)
    text = replace_reach_param(text, "R_STZ_MUCUM_E24", "Muskingum K", k2)
    text = replace_reach_param(text, "R_STZ_MUCUM_E24", "Muskingum x", x)
    (WORK / "bacia_E24.basin").write_text(text, encoding="utf-8")


def jython_script(csv_path: Path) -> str:
    return f'''from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime
import csv
OpenProject("{PROJECT}", "{WORK.as_posix()}")
Compute("Calibracao")
dss = HecDss.open("{(WORK / 'output.dss').as_posix()}")
paths = list(dss.getCatalogedPathnames())
def vals(prefix, token):
    out = {{}}
    for p in paths:
        if p.startswith(prefix) and token in p and "/RUN:Calibracao/" in p:
            s = dss.get(p)
            for i in range(s.numberValues):
                v = float(s.values[i])
                if v > -1.0e20:
                    out[int(s.times[i])] = v
    return out
sim_m = vals("//J_MUCUM_E24/", "/FLOW/")
obs_m = vals("//J_MUCUM_E24/", "/FLOW-OBSERVED/")
sim_s = vals("//J_STZ_E24/", "/FLOW/")
start = HecTime("16Nov2023", "0000").value()
end = HecTime("24Nov2023", "1900").value()
h = open(r"{csv_path.as_posix()}", "wb")
w = csv.writer(h)
w.writerow(["time_value","obs_mucum_m3s","sim_mucum_m3s","sim_stz_m3s"])
for t in sorted(set(sim_m).intersection(obs_m)):
    if start <= t <= end:
        w.writerow([t, obs_m[t], sim_m[t], sim_s.get(t, -9.99e29)])
h.close()
dss.close()
print("ROUTING_E24_DONE=%d" % len(sim_m))
Exit(1)
'''


def score_rows(rows: list[dict[str, float]], stz_timing: dict) -> dict:
    if len(rows) < 24:
        return {"pairs": len(rows), "status": "blocked"}
    obs = [r["obs"] for r in rows]
    sim = [r["sim"] for r in rows]
    mean_obs = sum(obs) / len(obs)
    ss_res = sum((a-b)**2 for a,b in zip(sim, obs))
    ss_tot = sum((v-mean_obs)**2 for v in obs)
    nse = None if ss_tot <= 0 else 1 - ss_res/ss_tot
    rmse = math.sqrt(ss_res/len(obs))
    mae = sum(abs(a-b) for a,b in zip(sim, obs))/len(obs)
    i_obs = max(range(len(rows)), key=lambda i: rows[i]["obs"])
    i_sim = max(range(len(rows)), key=lambda i: rows[i]["sim"])
    lag_h = (rows[i_sim]["t"] - rows[i_obs]["t"])/60.0
    peak_err = abs(rows[i_sim]["sim"] - rows[i_obs]["obs"])/rows[i_obs]["obs"]
    stz_peak_lag_h = None
    stz_peak_time_local = None
    stz_valid = [r for r in rows if r.get("stz") is not None and r["stz"] > -1e20]
    if stz_valid:
        stz_peak = max(stz_valid, key=lambda r: r["stz"])
        first_t = rows[0]["t"]
        stz_dt = START + timedelta(minutes=(stz_peak["t"] - first_t))
        stz_peak_time_local = stz_dt.isoformat()
        if stz_timing.get("available"):
            obs_dt = datetime.fromisoformat(stz_timing["peak_time_local"])
            stz_peak_lag_h = (stz_dt - obs_dt).total_seconds()/3600.0
    score = (nse if nse is not None else -99.0) - 0.02*abs(lag_h) - 0.50*peak_err
    if stz_peak_lag_h is not None:
        score -= 0.01*abs(stz_peak_lag_h)
    return {
        "pairs": len(rows), "nse": nse, "rmse_m3s": rmse, "mae_m3s": mae,
        "peak_lag_hours": lag_h, "peak_relative_error": peak_err,
        "observed_peak_m3s": rows[i_obs]["obs"], "simulated_peak_m3s": rows[i_sim]["sim"],
        "stz_simulated_peak_time_local": stz_peak_time_local,
        "stz_peak_timing_error_h_vs_observed_level": stz_peak_lag_h,
        "research_score": score, "status": "scored",
    }


def run_candidate(hec_sh: Path, base_text: str, k1: float, k2: float, x: float, stz_timing: dict, label: str) -> dict:
    write_candidate_basin(base_text, k1, k2, x)
    out_dss = WORK / "output.dss"
    if out_dss.exists():
        out_dss.unlink()
    csv_path = WORK / "candidate_series.csv"
    if csv_path.exists():
        csv_path.unlink()
    script = WORK / "compute_routing.script"
    script.write_text(jython_script(csv_path), encoding="utf-8")
    proc = subprocess.run([str(hec_sh), "-s", str(script)], cwd=hec_sh.parent, capture_output=True, text=True, timeout=180, check=False)
    if not csv_path.exists():
        return {"label": label, "k1_h": k1, "k2_h": k2, "x": x, "research_score": -999.0, "status": "hec_failed", "returncode": proc.returncode, "stderr_tail": proc.stderr[-500:]}
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            stz = finite(r["sim_stz_m3s"])
            rows.append({"t": int(float(r["time_value"])), "obs": float(r["obs_mucum_m3s"]), "sim": float(r["sim_mucum_m3s"]), "stz": stz})
    metrics = score_rows(rows, stz_timing)
    return {"label": label, "k1_h": k1, "k2_h": k2, "x": x, **metrics}


def setup_work() -> str:
    if WORK.exists():
        shutil.rmtree(WORK)
    shutil.copytree(BASE, WORK)
    for p in (WORK / "output.dss", WORK / "Calibracao.log", WORK / "network_pairs_scored.csv"):
        if p.exists():
            p.unlink()
    return (WORK / "bacia_E24.basin").read_text(encoding="utf-8")


def celerity(length_km: float, k_h: float):
    return None if k_h <= 0 else length_km*1000.0/(k_h*3600.0)


def section_plan() -> list[dict]:
    return [
        {"id":"S01","location":"ANA 86472000 · Linha José Júlio","reach":"Antas→STZ","priority":"alta","purpose":"seção de controle montante + nível/Q"},
        {"id":"S02","location":"~25% do trecho 86472000→confluência Carreiro","reach":"Antas→STZ","priority":"média","purpose":"geometria representativa antes da confluência"},
        {"id":"S03","location":"imediatamente a montante da confluência do Carreiro","reach":"Antas→STZ","priority":"muito alta","purpose":"separar propagação do tronco da contribuição Carreiro"},
        {"id":"S04","location":"imediatamente a jusante da confluência do Carreiro","reach":"Antas→STZ","priority":"muito alta","purpose":"captar mudança de seção/armazenamento após confluência"},
        {"id":"S05","location":"trecho de aproximação a Santa Tereza","reach":"Antas→STZ","priority":"alta","purpose":"controle de propagação antes de 86472600"},
        {"id":"S06","location":"ANA 86472600 · Santa Tereza","reach":"STZ→Muçum","priority":"muito alta","purpose":"seção detalhada no controle intermediário"},
        {"id":"S07","location":"~meio do trecho Santa Tereza→Muçum","reach":"STZ→Muçum","priority":"alta","purpose":"geometria representativa e armazenamento do reach"},
        {"id":"S08","location":"entrada do vale urbano de Muçum / mudança geométrica relevante","reach":"STZ→Muçum","priority":"alta","purpose":"captar eventual controle hidráulico antes do posto"},
        {"id":"S09","location":"ANA 86510000 · Muçum","reach":"STZ→Muçum","priority":"muito alta","purpose":"fechamento no posto alvo + curva-chave"},
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hec_sh", type=Path)
    args = ap.parse_args()
    hec_sh = args.hec_sh.resolve()
    if not hec_sh.exists():
        raise SystemExit(f"HEC executable not found: {hec_sh}")
    OUT.mkdir(parents=True, exist_ok=True)
    base_text = setup_work()
    stz_timing = observed_timing(fetch_ana_level("86472600", START, END))

    results = []
    results.append(run_candidate(hec_sh, base_text, 1.0, 1.0, 0.2, stz_timing, "baseline_k1_k2_1h_x02"))
    coarse_k = [0.5, 1.0, 2.0, 4.0, 8.0]
    coarse_x = [0.1, 0.2, 0.3]
    seen = {(1.0, 1.0, 0.2)}
    for k1 in coarse_k:
        for k2 in coarse_k:
            for x in coarse_x:
                key = (k1,k2,x)
                if key in seen:
                    continue
                seen.add(key)
                results.append(run_candidate(hec_sh, base_text, k1, k2, x, stz_timing, f"coarse_k1_{k1}_k2_{k2}_x_{x}"))

    valid = sorted((r for r in results if r.get("status") == "scored"), key=lambda r: r.get("research_score", -999), reverse=True)
    seeds = valid[:5]
    fine = set()
    for s in seeds:
        for dk1 in (-1.0,-0.5,0,0.5,1.0):
            for dk2 in (-1.0,-0.5,0,0.5,1.0):
                for dx in (-0.05,0,0.05):
                    k1 = round(max(0.25, min(12.0, s["k1_h"]+dk1)), 2)
                    k2 = round(max(0.25, min(12.0, s["k2_h"]+dk2)), 2)
                    x = round(max(0.05, min(0.4, s["x"]+dx)), 2)
                    if (k1,k2,x) not in seen:
                        fine.add((k1,k2,x))
    for i,(k1,k2,x) in enumerate(sorted(fine)[:60],1):
        seen.add((k1,k2,x))
        results.append(run_candidate(hec_sh, base_text, k1, k2, x, stz_timing, f"fine_{i:03d}"))

    valid = sorted((r for r in results if r.get("status") == "scored"), key=lambda r: r.get("research_score", -999), reverse=True)
    best = valid[0] if valid else None
    baseline = next((r for r in results if r["label"].startswith("baseline_")), None)

    for r in results:
        r["celerity_antas_stz_m_s"] = None if r.get("status") != "scored" else celerity(REACHES["R_ANTAS_STZ_E24"]["length_km"], r["k1_h"])
        r["celerity_stz_mucum_m_s"] = None if r.get("status") != "scored" else celerity(REACHES["R_STZ_MUCUM_E24"]["length_km"], r["k2_h"])

    csv_path = OUT / "routing_candidates_e24.csv"
    fields = sorted({k for r in results for k in r if k != "stderr_tail"})
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows({k:v for k,v in r.items() if k in fields} for r in results)

    sections = section_plan()
    with (OUT / "section_survey_plan.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sections[0]))
        w.writeheader(); w.writerows(sections)

    delta = None
    if best and baseline and best.get("status") == baseline.get("status") == "scored":
        delta = {
            "delta_nse": best["nse"] - baseline["nse"],
            "delta_rmse_m3s": best["rmse_m3s"] - baseline["rmse_m3s"],
            "delta_abs_peak_lag_h": abs(best["peak_lag_hours"]) - abs(baseline["peak_lag_hours"]),
            "delta_peak_relative_error": best["peak_relative_error"] - baseline["peak_relative_error"],
        }
    report = {
        "schema_version": "hec_hms_e24_reach_routing_search_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "teste controlado de routing; não altera o HEC operacional",
        "event": "E24 · novembro/2023 · janela censurada sem preencher lacuna de chuva",
        "hec_hms": "4.13",
        "held_fixed": "forçantes, perdas, Clark e baseflow do projeto E24 publicado; variam apenas K1, K2 e x dos reaches",
        "network": "86472000 -> 86472600 -> 86510000",
        "reaches": REACHES,
        "santa_tereza_level_timing_proxy": stz_timing,
        "objective": "NSE Muçum - 0.02*|lag pico Muçum| - 0.50*erro relativo pico - 0.01*|erro horário pico STZ| quando disponível",
        "candidate_count": len(results),
        "baseline": baseline,
        "best": best,
        "improvement_best_minus_baseline": delta,
        "top10": valid[:10],
        "section_survey_plan": sections,
        "interpretation_limits": [
            "K do Muskingum é parâmetro de armazenamento/tempo e não deve ser igualado automaticamente ao tempo de viagem observado.",
            "O pico de nível em Santa Tereza é usado somente como proxy temporal; não há comparação de magnitude Q sem curva-chave reconciliada.",
            "As declividades do MDT/ANADEM são diagnóstico de terreno, não declividade do fundo da calha.",
            "Este teste E24 serve para decidir se routing merece entrar na próxima versão; generalização ainda exige E27/E28 e evento 2026.",
        ],
        "artifacts": ["routing_candidates_e24.csv", "section_survey_plan.csv", "routing_profile_e24_latest.json"],
    }
    (OUT / "routing_profile_e24_latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(WORK, ignore_errors=True)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if best else 2


if __name__ == "__main__":
    raise SystemExit(main())
