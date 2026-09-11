#!/usr/bin/env python3
"""Leave-one-out hindcast skill for Muçum HEC twin 'quanto sobe' product.

For each library event:
  1) rebuild observed rain as if it were QPF
  2) pick analog params EXCLUDING the event itself
  3) run HEC twin forward
  4) score peak Q / ΔQ / ΔN vs observed

Research only. Does not touch RNA. Does not invent STZ rating curve.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_hec_twin_mucum_forward_5d as fwd  # noqa: E402
import run_hec_twin_stz_mucum_calibrate as cal  # noqa: E402

OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
MODELO = OUT / "modelo_mucum_eventwise_v1_fechado_latest.json"
HEC = OUT / "hec_twin_stz_mucum_v1_latest.json"

SUBBASINS = [
    "SB_PRATA_7868",
    "SB_ANTAS_RESIDUAL",
    "SB_CARREIRO_7866",
    "SB_STZ_RESIDUAL",
    "SB_INC_MUCUM",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def q_to_n_series(qs: list[float], segments: list[dict[str, Any]]) -> list[float | None]:
    return [fwd.q_to_stage_cm(q, segments).get("stage_cm") for q in qs]


def area_weighted_rain_mm(precip: dict[str, list[float]], areas: dict[str, float]) -> float:
    total_area = sum(areas[sb] for sb in precip)
    if total_area <= 0:
        return float("nan")
    acc = 0.0
    for sb, series in precip.items():
        acc += sum(series) * areas[sb]
    return acc / total_area


def pick_loo_analog(
    target_event_id: str,
    forecast_rain_mm: float,
    library: list[dict[str, Any]],
    hec_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    pool = [r for r in library if r["event_id"] != target_event_id]
    if not pool:
        return None
    scored = fwd.choose_analogs(forecast_rain_mm, pool, hec_events, top_k=1)
    return scored[0] if scored else None


def score_event(
    event_id: str,
    *,
    library: list[dict[str, Any]],
    hec_by_id: dict[str, Any],
    hec_events: list[dict[str, Any]],
    areas: dict[str, float],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    hec_ev = hec_by_id.get(event_id) or {}
    pad = int(hec_ev.get("pad_hours_selected") or 0)
    precip, rain_meta, hours, flow, _flow_antas, core_offset, core_hours = cal.prepare_event_forcing(
        event_id, SUBBASINS, pad
    )
    if precip is None:
        return {
            "event_id": event_id,
            "status": "blocked_rain",
            "reason": (rain_meta or {}).get("blocked_reason"),
        }

    rain_mm = area_weighted_rain_mm(precip, areas)
    analog = pick_loo_analog(event_id, rain_mm, library, hec_events)
    if analog is None:
        return {"event_id": event_id, "status": "blocked_no_analog", "rain_mm_aw": rain_mm}

    params = fwd.params_from_library_row(analog["row"])
    net = cal.run_network(precip, areas, params, include_mucum_increment=True)
    q_sim = net["at_mucum"]

    # Align observed flow on core window timestamps
    obs_map = {h: flow[h] for h in core_hours if h in flow}
    sim_core = q_sim[core_offset : core_offset + len(core_hours)]
    paired_obs: list[float] = []
    paired_sim: list[float] = []
    for i, h in enumerate(core_hours):
        if h in obs_map and i < len(sim_core):
            paired_obs.append(float(obs_map[h]))
            paired_sim.append(float(sim_core[i]))

    if len(paired_obs) < 6:
        return {
            "event_id": event_id,
            "status": "blocked_obs",
            "rain_mm_aw": round(rain_mm, 3),
            "analog_event_id": analog["event_id"],
            "reason": "insufficient_observed_q_pairs",
        }

    obs_peak = max(paired_obs)
    sim_peak = max(paired_sim)
    obs_t0 = paired_obs[0]
    sim_t0 = paired_sim[0]
    obs_rise_q = obs_peak - obs_t0
    sim_rise_q = sim_peak - sim_t0

    obs_n = q_to_n_series(paired_obs, segments)
    sim_n = q_to_n_series(paired_sim, segments)
    obs_n_valid = [(o, s) for o, s in zip(obs_n, sim_n) if o is not None and s is not None]
    if obs_n_valid:
        obs_n0 = obs_n_valid[0][0]
        sim_n0 = obs_n_valid[0][1]
        obs_n_peak = max(o for o, _ in obs_n_valid)
        sim_n_peak = max(s for _, s in obs_n_valid)
        obs_rise_n = float(obs_n_peak) - float(obs_n0)
        sim_rise_n = float(sim_n_peak) - float(sim_n0)
    else:
        obs_n0 = sim_n0 = obs_n_peak = sim_n_peak = obs_rise_n = sim_rise_n = float("nan")

    peak_rel_err = abs(sim_peak - obs_peak) / obs_peak if obs_peak else float("nan")
    rise_q_rel_err = abs(sim_rise_q - obs_rise_q) / abs(obs_rise_q) if abs(obs_rise_q) > 1e-6 else float("nan")
    rise_n_rel_err = (
        abs(sim_rise_n - obs_rise_n) / abs(obs_rise_n)
        if obs_rise_n == obs_rise_n and abs(obs_rise_n) > 1e-6
        else float("nan")
    )
    rise_n_abs_err = (
        abs(sim_rise_n - obs_rise_n) if obs_rise_n == obs_rise_n and sim_rise_n == sim_rise_n else float("nan")
    )

    # NSE on paired Q
    mean_o = mean(paired_obs)
    ss_res = sum((o - s) ** 2 for o, s in zip(paired_obs, paired_sim))
    ss_tot = sum((o - mean_o) ** 2 for o in paired_obs) or 1e-9
    nse = 1.0 - ss_res / ss_tot

    self_fit_nse = None
    lib_row = next((r for r in library if r["event_id"] == event_id), None)
    if lib_row is not None:
        self_fit_nse = lib_row.get("nse")

    return {
        "event_id": event_id,
        "status": "scored",
        "rain_mm_aw": round(rain_mm, 3),
        "analog_event_id": analog["event_id"],
        "analog_abs_mm_gap": analog.get("abs_mm_gap"),
        "pad_hours": pad,
        "pairs": len(paired_obs),
        "nse_loo": round(nse, 4),
        "self_fit_nse": self_fit_nse,
        "obs_peak_q_m3s": round(obs_peak, 2),
        "sim_peak_q_m3s": round(sim_peak, 2),
        "peak_q_rel_err": round(peak_rel_err, 4),
        "obs_rise_q_m3s": round(obs_rise_q, 2),
        "sim_rise_q_m3s": round(sim_rise_q, 2),
        "rise_q_rel_err": round(rise_q_rel_err, 4) if rise_q_rel_err == rise_q_rel_err else None,
        "obs_rise_n_cm": round(obs_rise_n, 2) if obs_rise_n == obs_rise_n else None,
        "sim_rise_n_cm": round(sim_rise_n, 2) if sim_rise_n == sim_rise_n else None,
        "rise_n_abs_err_cm": round(rise_n_abs_err, 2) if rise_n_abs_err == rise_n_abs_err else None,
        "rise_n_rel_err": round(rise_n_rel_err, 4) if rise_n_rel_err == rise_n_rel_err else None,
        "obs_n_t0_cm": round(float(obs_n0), 2) if obs_n0 == obs_n0 else None,
        "sim_n_t0_cm": round(float(sim_n0), 2) if sim_n0 == sim_n0 else None,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r.get("status") == "scored"]
    if not scored:
        return {"n_scored": 0}

    def vals(key: str) -> list[float]:
        out = []
        for r in scored:
            v = r.get(key)
            if v is not None and v == v:
                out.append(float(v))
        return out

    peak_errs = vals("peak_q_rel_err")
    rise_n_abs = vals("rise_n_abs_err_cm")
    rise_n_rel = vals("rise_n_rel_err")
    nse_loo = vals("nse_loo")
    return {
        "n_scored": len(scored),
        "mean_nse_loo": round(mean(nse_loo), 4) if nse_loo else None,
        "mean_peak_q_rel_err": round(mean(peak_errs), 4) if peak_errs else None,
        "median_peak_q_rel_err": round(sorted(peak_errs)[len(peak_errs) // 2], 4) if peak_errs else None,
        "mean_rise_n_abs_err_cm": round(mean(rise_n_abs), 2) if rise_n_abs else None,
        "median_rise_n_abs_err_cm": round(sorted(rise_n_abs)[len(rise_n_abs) // 2], 2) if rise_n_abs else None,
        "mean_rise_n_rel_err": round(mean(rise_n_rel), 4) if rise_n_rel else None,
        "n_rise_n_within_50pct": sum(1 for v in rise_n_rel if v <= 0.5),
        "n_rise_n_within_100pct": sum(1 for v in rise_n_rel if v <= 1.0),
        "n_peak_q_within_30pct": sum(1 for v in peak_errs if v <= 0.3),
    }


def render_html(payload: dict[str, Any]) -> str:
    s = payload["summary"]
    rows = []
    for r in payload["events"]:
        if r.get("status") != "scored":
            rows.append(
                "<tr>"
                f"<td><code>{html.escape(r['event_id'])}</code></td>"
                f"<td colspan='8'>{html.escape(r.get('status',''))} — {html.escape(str(r.get('reason') or ''))}</td>"
                "</tr>"
            )
            continue
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(r['event_id'])}</code></td>"
            f"<td><code>{html.escape(str(r['analog_event_id']))}</code></td>"
            f"<td>{r['rain_mm_aw']}</td>"
            f"<td>{r['nse_loo']}</td>"
            f"<td>{r['peak_q_rel_err']}</td>"
            f"<td>{r['obs_rise_n_cm']} → {r['sim_rise_n_cm']}</td>"
            f"<td>{r['rise_n_abs_err_cm']}</td>"
            f"<td>{r['rise_n_rel_err']}</td>"
            "</tr>"
        )
    verdict = payload["verdict"]["plain_pt"]
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<title>HEC Muçum · hindcast skill (quanto sobe)</title>
<style>
:root {{ --ink:#14231c; --muted:#4d6358; --ok:#1f6b4a; --warn:#8a5a12; --bad:#8a2f2f; --card:#f7fbf8; }}
body {{ margin:0; font-family:"Source Serif 4",Georgia,serif; color:var(--ink);
  background:radial-gradient(900px 500px at 0% 0%, #cfe0d4, transparent), linear-gradient(160deg,#d9e6de,#f2f6f3); }}
main {{ max-width:1040px; margin:0 auto; padding:2rem 1.1rem 3rem; }}
h1 {{ font-size:clamp(1.45rem,3vw,2rem); margin:0 0 .4rem; }}
.lead {{ color:var(--muted); }}
.pill {{ display:inline-block; padding:.2rem .65rem; border:1px solid #9bb8a8; color:var(--ok); font-size:.85rem; }}
.notice {{ padding:.85rem 1rem; margin:1rem 0; background:#e3f0e8; border-left:4px solid var(--ok); }}
.notice.warn {{ background:#f5ecda; border-left-color:var(--warn); }}
.notice.bad {{ background:#f5e3e3; border-left-color:var(--bad); }}
section {{ margin-top:1.4rem; border-top:1px solid #c5d5cc; padding-top:1rem; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); font-size:.9rem; }}
th,td {{ text-align:left; padding:.4rem .45rem; border-bottom:1px solid #d5e0da; vertical-align:top; }}
th {{ color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; }}
code {{ font-family:ui-monospace,monospace; font-size:.86em; }}
</style>
</head>
<body>
<main>
<p class="pill">{html.escape(payload['status'])}</p>
<h1>Hindcast leave-one-out · quanto sobe Muçum</h1>
<p class="lead">Chuva observada do evento como se fosse previsão; params de outro evento (análogo). Mede se o ΔN/pico generaliza.</p>
<div class="notice {'warn' if payload['verdict']['level']=='caution' else ('bad' if payload['verdict']['level']=='weak' else '')}">
<strong>Veredito:</strong> {html.escape(verdict)}
</div>
<section>
<h2>Resumo</h2>
<ul>
<li>Eventos pontuados: {s.get('n_scored')}</li>
<li>NSE LOO médio: {s.get('mean_nse_loo')}</li>
<li>Erro relativo médio do pico Q: {s.get('mean_peak_q_rel_err')}</li>
<li>Erro absoluto médio do ΔN: {s.get('mean_rise_n_abs_err_cm')} cm</li>
<li>ΔN com erro relativo ≤50%: {s.get('n_rise_n_within_50pct')} / {s.get('n_scored')}</li>
<li>ΔN com erro relativo ≤100%: {s.get('n_rise_n_within_100pct')} / {s.get('n_scored')}</li>
</ul>
</section>
<section>
<h2>Por evento</h2>
<table>
<thead><tr>
<th>Evento</th><th>Análogo</th><th>Chuva mm</th><th>NSE LOO</th><th>|err| pico Q</th>
<th>ΔN obs→sim cm</th><th>|err| ΔN cm</th><th>|err| ΔN rel</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>
<section>
<h2>Disciplina</h2>
<ul>
<li>Leave-one-out: o evento-alvo não entra como análogo.</li>
<li>ΔN via curva-chave oficial de Muçum (Q→N). STZ fora.</li>
<li>RNA não é tocada. Pacote de pesquisa, não alerta.</li>
</ul>
<p><a href="hec_twin_mucum_hindcast_skill_5d_latest.json">JSON</a></p>
</section>
</main>
</body>
</html>
"""


def build_verdict(summary: dict[str, Any]) -> dict[str, Any]:
    n = summary.get("n_scored") or 0
    if n == 0:
        return {
            "level": "weak",
            "plain_pt": "Hindcast não pontuou eventos — não dá para confiar no ΔN operacional ainda.",
        }
    mean_rise = summary.get("mean_rise_n_rel_err")
    within50 = summary.get("n_rise_n_within_50pct") or 0
    mean_peak = summary.get("mean_peak_q_rel_err")
    if mean_rise is not None and mean_rise <= 0.5 and within50 >= max(1, n // 2):
        level = "usable_research"
        plain = (
            f"Hindcast LOO: ΔN médio com erro relativo ~{mean_rise:.0%} "
            f"({within50}/{n} eventos ≤50%). Pico Q médio |err|~{(mean_peak or 0):.0%}. "
            "Útil como pesquisa; ainda não é alerta."
        )
    elif mean_rise is not None and mean_rise <= 1.0:
        level = "caution"
        plain = (
            f"Hindcast LOO: ΔN ainda grosso (erro relativo médio ~{mean_rise:.0%}; "
            f"{within50}/{n} ≤50%). Direção pode servir; magnitude precisa apertar "
            "(análogo/CI/forçante) antes de uso forte."
        )
    else:
        level = "weak"
        plain = (
            f"Hindcast LOO fraco para ΔN (erro relativo médio ~{(mean_rise if mean_rise is not None else float('nan')):.0%}). "
            "Não usar o número de subida como decisão até melhorar análogo/calibração."
        )
    return {"level": level, "plain_pt": plain}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events",
        nargs="*",
        default=None,
        help="Subset of event ids (default: library eventwise core).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT,
        help="Directory for JSON/HTML artifacts (default: estudo package dir).",
    )
    args = parser.parse_args()

    modelo = json.loads(MODELO.read_text(encoding="utf-8"))
    hec = json.loads(HEC.read_text(encoding="utf-8"))
    library = list(modelo.get("params_library_eventwise") or [])
    if not library:
        raise SystemExit("empty eventwise library")
    hec_events = list((hec.get("models") or {}).get("mucum", {}).get("events") or [])
    hec_by_id = {e["event_id"]: e for e in hec_events}
    areas = fwd.load_areas()
    segments = fwd.mucum_curve_segments()

    event_ids = args.events or [r["event_id"] for r in library]
    rows: list[dict[str, Any]] = []
    for eid in event_ids:
        print(f"scoring {eid} ...", flush=True)
        rows.append(
            score_event(
                eid,
                library=library,
                hec_by_id=hec_by_id,
                hec_events=hec_events,
                areas=areas,
                segments=segments,
            )
        )

    summary = summarize(rows)
    verdict = build_verdict(summary)
    payload = {
        "schema_version": "hec_twin_mucum_hindcast_skill_5d_v1",
        "generated_at_utc": utc_now(),
        "status": "research_hindcast_skill_ready",
        "purpose": (
            "Skill leave-one-out do produto 'chuva prevista → quanto sobe Muçum' "
            "usando chuva observada de evento como QPF proxy."
        ),
        "method": {
            "forcing": "observed_event_rain_as_qpf_proxy",
            "params": "leave_one_out_analog_by_rain_total",
            "stage": "Q_to_N_via_mucum_official_rating_curve",
            "not": ["rna", "stz_n", "official_alert"],
        },
        "summary": summary,
        "verdict": verdict,
        "events": rows,
        "artifacts": {
            "json": "hec_twin_mucum_hindcast_skill_5d_latest.json",
            "html": "hec_twin_mucum_hindcast_skill_5d.html",
        },
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "hec_twin_mucum_hindcast_skill_5d_latest.json"
    html_path = out_dir / "hec_twin_mucum_hindcast_skill_5d.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(payload), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    print(json.dumps({"summary": summary, "verdict": verdict}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
