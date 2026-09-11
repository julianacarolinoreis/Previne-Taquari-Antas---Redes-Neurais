#!/usr/bin/env python3
"""Closed ~5-day Muçum forward forecast: IFS forcing → HEC twin → Q → N.

Santa Tereza: diagnostic Q only (no rating curve → no stage). Research, not alert.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hec_twin_nested_v17 import NestedParams, ZoneParams  # noqa: E402
from run_hec_twin_stz_mucum_calibrate import run_network  # noqa: E402

OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
FORCING_DEFAULT = OUT / "hec_twin_ifs_forcing_5d_latest.json"
MODELO = OUT / "modelo_mucum_eventwise_v1_fechado_latest.json"
HEC = OUT / "hec_twin_stz_mucum_v1_latest.json"
ESTRUTURA = OUT / "estrutura_stz_mucum_latest.json"
CURVA_HUNT = OUT / "curva_chave_86472600" / "curva_chave_hunt_86472600_latest.json"

SUBBASINS = [
    "SB_PRATA_7868",
    "SB_ANTAS_RESIDUAL",
    "SB_CARREIRO_7866",
    "SB_STZ_RESIDUAL",
    "SB_INC_MUCUM",
]
MUCUM_CODE = "86510000"
STZ_CODE = "86472600"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_areas() -> dict[str, float]:
    estrutura = json.loads(ESTRUTURA.read_text(encoding="utf-8"))
    return {
        el["id"]: float(el["area_km2"])
        for el in estrutura["models"]["mucum"]["elements"]
        if el.get("type") == "subbasin"
    }


def params_from_library_row(row: dict[str, Any]) -> NestedParams:
    up = row["params"]["upstream"]
    dn = row["params"]["downstream"]
    return NestedParams(
        up=ZoneParams(
            initial_loss=float(up["initial_loss"]),
            constant_loss=float(up["constant_loss"]),
            tc=float(up["tc"]),
            storage=float(up["storage"]),
            recession=float(up["recession"]),
            initial_flow_ratio=float(up["initial_flow_ratio"]),
        ),
        dn=ZoneParams(
            initial_loss=float(dn["initial_loss"]),
            constant_loss=float(dn["constant_loss"]),
            tc=float(dn["tc"]),
            storage=float(dn["storage"]),
            recession=float(dn["recession"]),
            initial_flow_ratio=float(dn["initial_flow_ratio"]),
        ),
        k1=float(row["params"]["k1"]),
        k2=float(row["params"]["k2"]),
        k3=float(row["params"]["k3"]),
        x=float(row["params"].get("x", 0.2)),
    )


def event_core_rain_mm(hec_event: dict[str, Any]) -> float:
    rain = hec_event.get("rain") or {}
    core = rain.get("stations_mm_sum_core") or rain.get("stations_mm_sum") or {}
    if not core:
        return float("nan")
    return float(sum(core.values()) / len(core))


def choose_analogs(
    forecast_total_mm: float,
    library: list[dict[str, Any]],
    hec_events: list[dict[str, Any]],
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    by_id = {e["event_id"]: e for e in hec_events}
    scored: list[dict[str, Any]] = []
    for row in library:
        eid = row["event_id"]
        hist = event_core_rain_mm(by_id.get(eid) or {})
        if hist != hist:
            continue
        scored.append(
            {
                "event_id": eid,
                "historical_core_mean_mm": round(hist, 3),
                "forecast_aw_total_mm": round(forecast_total_mm, 3),
                "abs_mm_gap": round(abs(hist - forecast_total_mm), 3),
                "nse": row.get("nse"),
                "research_score": row.get("research_score"),
                "row": row,
            }
        )
    scored.sort(key=lambda r: (r["abs_mm_gap"], -(r["nse"] or -9)))
    return scored[:top_k]


def mucum_curve_segments() -> list[dict[str, Any]]:
    hunt = json.loads(CURVA_HUNT.read_text(encoding="utf-8"))
    block = (hunt.get("neighbors_official_curves_NOT_for_STZ") or {}).get(MUCUM_CODE) or {}
    segs = list(block.get("segments") or [])
    if not segs:
        raise RuntimeError("Muçum rating curve segments missing in hunt artifact")
    return segs


def q_to_stage_cm(q_m3s: float, segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Invert Q = a * (h_m - h0_m)^n."""
    if q_m3s is None or q_m3s != q_m3s or q_m3s < 0:
        return {"stage_cm": None, "ok": False, "reason": "invalid_q"}
    candidates: list[dict[str, Any]] = []
    for seg in segments:
        a = float(seg["a"])
        h0 = float(seg["h0_m"])
        n = float(seg["n"])
        if a <= 0 or n <= 0:
            continue
        h_m = h0 + (max(q_m3s, 0.0) / a) ** (1.0 / n)
        stage_cm = h_m * 100.0
        lo = float(seg["stage_min_cm"])
        hi = float(seg["stage_max_cm"])
        inside = lo - 1e-6 <= stage_cm <= hi + 1e-6
        candidates.append(
            {
                "stage_cm": stage_cm,
                "segment_number": seg.get("segment_number"),
                "inside": inside,
                "stage_min_cm": lo,
                "stage_max_cm": hi,
            }
        )
    if not candidates:
        return {"stage_cm": None, "ok": False, "reason": "no_segment"}
    inside = [c for c in candidates if c["inside"]]
    pick = inside[0] if inside else min(
        candidates,
        key=lambda c: abs(c["stage_cm"] - (c["stage_min_cm"] + c["stage_max_cm"]) / 2),
    )
    return {
        "stage_cm": round(float(pick["stage_cm"]), 2),
        "ok": True,
        "segment_number": pick["segment_number"],
        "inside_segment": bool(pick["inside"]),
        "extrapolated": not bool(pick["inside"]),
    }


def build_package(forcing: dict[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
    modelo = json.loads(MODELO.read_text(encoding="utf-8"))
    hec = json.loads(HEC.read_text(encoding="utf-8"))
    library = list(modelo.get("params_library_eventwise") or [])
    if not library:
        raise RuntimeError("empty eventwise params library")
    hec_events = list((hec.get("models") or {}).get("mucum", {}).get("events") or [])
    areas = load_areas()
    precip = forcing["precip_mm_by_subbasin"]
    for sb in SUBBASINS:
        if sb not in precip:
            raise RuntimeError(f"forcing missing {sb}")
        if sb not in areas:
            raise RuntimeError(f"area missing for {sb}")
    times = list(forcing["times_utc"])
    forecast_total = float(forcing["area_weighted_mean_mm"]["total_mm"])

    if event_id:
        row = next((r for r in library if r["event_id"] == event_id), None)
        if row is None:
            raise RuntimeError(f"event {event_id} not in core library")
        he_ev = next((e for e in hec_events if e["event_id"] == event_id), {})
        analogs = [
            {
                "event_id": event_id,
                "historical_core_mean_mm": event_core_rain_mm(he_ev),
                "forecast_aw_total_mm": forecast_total,
                "abs_mm_gap": None,
                "nse": row.get("nse"),
                "research_score": row.get("research_score"),
                "row": row,
            }
        ]
    else:
        analogs = choose_analogs(forecast_total, library, hec_events, top_k=3)
        if not analogs:
            raise RuntimeError("no analogs scored")

    segments = mucum_curve_segments()
    members: list[dict[str, Any]] = []
    for analog in analogs:
        params = params_from_library_row(analog["row"])
        net = run_network(precip, areas, params, include_mucum_increment=True)
        q_mucum = net["at_mucum"]
        q_antas = net["at_antas"]
        q_stz = net["at_stz"]
        stages = [q_to_stage_cm(q, segments) for q in q_mucum]
        peak_i = max(range(len(q_mucum)), key=lambda i: q_mucum[i]) if q_mucum else 0
        members.append(
            {
                "event_id": analog["event_id"],
                "analog": {k: v for k, v in analog.items() if k != "row"},
                "params": params.to_dict(),
                "peak_q_mucum_m3s": round(float(q_mucum[peak_i]), 3),
                "peak_time_utc": times[peak_i] if times else None,
                "peak_stage_mucum_cm": stages[peak_i].get("stage_cm") if stages else None,
                "series": {
                    "time_utc": times,
                    "q_mucum_m3s": [round(float(x), 3) for x in q_mucum],
                    "q_antas_m3s": [round(float(x), 3) for x in q_antas],
                    "q_stz_diagnostic_m3s": [round(float(x), 3) for x in q_stz],
                    "n_mucum_cm": [s.get("stage_cm") for s in stages],
                    "n_mucum_meta": stages,
                },
            }
        )

    primary = members[0]
    band_q = []
    for i in range(len(times)):
        vals = [m["series"]["q_mucum_m3s"][i] for m in members]
        band_q.append({"min": min(vals), "max": max(vals), "primary": vals[0]})

    return {
        "schema_version": "hec_twin_mucum_forward_5d_v1",
        "generated_at_utc": utc_now(),
        "status": "research_forward_5d_ready",
        "label": (
            "PESQUISA — previsão ~5 dias Muçum via gêmeo HEC + IFS. "
            "NÃO é alerta oficial / evacuação autorizada."
        ),
        "purpose": (
            "Antecedência multi-dia (chuva prevista → Q → N em Muçum) para estudo de evacuação. "
            "RNA continua no curto prazo; HEC+QPF é o caminho de ~5 dias."
        ),
        "decision_alignment": {
            "primary_for_multiday": "HEC_twin_plus_IFS_QPF",
            "short_horizon_complement": "RNA_nivel_2h_4h_8h",
            "stz_rating_curve": "absent — no N@STZ from HEC; Q@STZ diagnostic only",
            "do_not": [
                "invent_stz_rating_curve",
                "promote_common_search_params",
                "call_this_official_alert",
            ],
        },
        "forcing": {
            "artifact": "hec_twin_ifs_forcing_5d_latest.json",
            "model": forcing.get("model"),
            "horizon_hours": forcing.get("horizon_hours"),
            "area_weighted_total_mm": forecast_total,
            "generated_at_utc": forcing.get("generated_at_utc"),
            "point_proxy_not_areal_mask": True,
        },
        "param_selection": {
            "method": "analog_eventwise_by_core_rain_mm" if event_id is None else "forced_event_id",
            "forced_event_id": event_id,
            "analogs": [{k: v for k, v in a.items() if k != "row"} for a in analogs],
            "common_search": "blocked_not_used",
        },
        "primary_member": {
            "event_id": primary["event_id"],
            "peak_q_mucum_m3s": primary["peak_q_mucum_m3s"],
            "peak_time_utc": primary["peak_time_utc"],
            "peak_stage_mucum_cm": primary["peak_stage_mucum_cm"],
            "params": primary["params"],
        },
        "ensemble_members": [
            {
                "event_id": m["event_id"],
                "analog": m["analog"],
                "peak_q_mucum_m3s": m["peak_q_mucum_m3s"],
                "peak_time_utc": m["peak_time_utc"],
                "peak_stage_mucum_cm": m["peak_stage_mucum_cm"],
            }
            for m in members
        ],
        "series_primary": primary["series"],
        "q_mucum_band_m3s": band_q,
        "rating_curve_mucum": {
            "station": MUCUM_CODE,
            "source": "curva_chave_hunt → neighbors_official_curves_NOT_for_STZ.86510000",
            "n_segments": len(segments),
        },
        "santa_tereza": {
            "station": STZ_CODE,
            "q_status": "diagnostic_only_not_calibrated",
            "n_status": "blocked_no_rating_curve",
            "note": "Sem curva-chave oficial: HEC não publica N em STZ. Curto prazo: RNA STZ.",
        },
        "artifacts": {
            "json": "hec_twin_mucum_forward_5d_latest.json",
            "html": "hec_twin_mucum_forward_5d.html",
            "csv": "hec_twin_mucum_forward_5d/primary_series.csv",
        },
        "_members_full": members,
    }


def write_csv(package: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    series = package["series_primary"]
    band = package["q_mucum_band_m3s"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "time_utc",
                "q_mucum_m3s",
                "q_mucum_band_min",
                "q_mucum_band_max",
                "n_mucum_cm",
                "q_antas_m3s",
                "q_stz_diagnostic_m3s",
            ]
        )
        for i, t in enumerate(series["time_utc"]):
            w.writerow(
                [
                    t,
                    series["q_mucum_m3s"][i],
                    band[i]["min"],
                    band[i]["max"],
                    series["n_mucum_cm"][i],
                    series["q_antas_m3s"][i],
                    series["q_stz_diagnostic_m3s"][i],
                ]
            )


def render_html(package: dict[str, Any]) -> str:
    p = package["primary_member"]
    analogs = "".join(
        (
            f"<li><code>{html.escape(m['event_id'])}</code> — pico Q {m['peak_q_mucum_m3s']} m³/s"
            f" · N {m['peak_stage_mucum_cm']} cm"
            f" · gap chuva {m['analog'].get('abs_mm_gap')} mm</li>"
        )
        for m in package["ensemble_members"]
    )
    series = package["series_primary"]
    rows = []
    for i, t in enumerate(series["time_utc"]):
        if i % 6 != 0 and i != len(series["time_utc"]) - 1:
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(t)}</td>"
            f"<td>{series['q_mucum_m3s'][i]}</td>"
            f"<td>{package['q_mucum_band_m3s'][i]['min']}–{package['q_mucum_band_m3s'][i]['max']}</td>"
            f"<td>{series['n_mucum_cm'][i]}</td>"
            f"<td>{series['q_stz_diagnostic_m3s'][i]}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<title>HEC twin · previsão ~5d Muçum (pesquisa)</title>
<style>
:root {{ --ink:#14231c; --muted:#4d6358; --card:#f7fbf8; --ok:#1f6b4a; --warn:#8a5a12; }}
body {{ margin:0; font-family:"Source Serif 4",Georgia,serif; color:var(--ink);
  background:radial-gradient(900px 500px at 0% 0%, #cfe0d4, transparent), linear-gradient(160deg,#d9e6de,#f2f6f3); }}
main {{ max-width:960px; margin:0 auto; padding:2rem 1.1rem 3rem; }}
h1 {{ font-size:clamp(1.5rem,3vw,2.1rem); margin:0 0 .4rem; }}
.lead {{ color:var(--muted); }}
.pill {{ display:inline-block; padding:.2rem .65rem; border:1px solid #9bb8a8; color:var(--ok); font-size:.85rem; }}
.notice {{ padding:.85rem 1rem; margin:1rem 0; background:#e3f0e8; border-left:4px solid var(--ok); }}
.notice.warn {{ background:#f5ecda; border-left-color:var(--warn); }}
section {{ margin-top:1.5rem; border-top:1px solid #c5d5cc; padding-top:1rem; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); font-size:.92rem; }}
th,td {{ text-align:left; padding:.4rem .5rem; border-bottom:1px solid #d5e0da; }}
th {{ color:var(--muted); font-size:.75rem; text-transform:uppercase; letter-spacing:.04em; }}
code {{ font-family:ui-monospace,monospace; font-size:.86em; }}
</style>
</head>
<body>
<main>
<p class="pill">{html.escape(package['status'])}</p>
<h1>Previsão ~5 dias · Muçum (gêmeo HEC + IFS)</h1>
<p class="lead">{html.escape(package['purpose'])}</p>
<div class="notice warn"><strong>{html.escape(package['label'])}</strong></div>
<div class="notice">
  <strong>Membro principal:</strong> análogo <code>{html.escape(p['event_id'])}</code>
  · pico Q <strong>{p['peak_q_mucum_m3s']}</strong> m³/s
  · pico N <strong>{p['peak_stage_mucum_cm']}</strong> cm
  · em {html.escape(str(p['peak_time_utc']))}
  · chuva IFS (média ponderada) {package['forcing']['area_weighted_total_mm']} mm
  / {package['forcing']['horizon_hours']} h
</div>
<section>
<h2>Por que HEC aqui</h2>
<ul>
<li>Evacuação precisa de dias de antecedência — RNA ao vivo cobre horas, não ~5 dias.</li>
<li>Caminho: chuva prevista (IFS) → gêmeo HEC eventwise → Q Muçum → curva-chave → N Muçum.</li>
<li>Santa Tereza sem curva-chave: sem N via HEC; Q diagnóstico apenas.</li>
</ul>
</section>
<section>
<h2>Ensemble de análogos (top 3)</h2>
<ul>{analogs}</ul>
</section>
<section>
<h2>Série (amostra 6 h)</h2>
<table>
<thead><tr><th>UTC</th><th>Q Muçum</th><th>banda Q</th><th>N Muçum cm</th><th>Q STZ diag.</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>
<section>
<h2>Disciplina</h2>
<ul>
<li>Params = biblioteca eventwise (análogo por chuva); common-search bloqueado.</li>
<li>Forçante IFS é proxy pontual por sub-bacia — não máscara areal fechada.</li>
<li>Não inventar curva STZ. Não chamar de alerta oficial.</li>
</ul>
<p><a href="hec_twin_mucum_forward_5d_latest.json">JSON</a> ·
<a href="hec_twin_mucum_forward_5d/primary_series.csv">CSV</a> ·
<a href="hec_twin_ifs_forcing_5d_latest.json">Forçante IFS</a></p>
</section>
</main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forcing", type=Path, default=FORCING_DEFAULT)
    parser.add_argument("--event-id", type=str, default=None)
    args = parser.parse_args()
    if not args.forcing.exists():
        raise SystemExit(
            f"missing forcing: {args.forcing} (run build_hec_twin_ifs_forcing_5d.py first)"
        )

    forcing = json.loads(args.forcing.read_text(encoding="utf-8"))
    package = build_package(forcing, event_id=args.event_id)
    members_full = package.pop("_members_full")

    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "hec_twin_mucum_forward_5d_latest.json"
    html_path = OUT / "hec_twin_mucum_forward_5d.html"
    csv_path = OUT / "hec_twin_mucum_forward_5d" / "primary_series.csv"
    ens_path = OUT / "hec_twin_mucum_forward_5d" / "ensemble_members.json"

    json_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(package), encoding="utf-8")
    write_csv(package, csv_path)
    ens_path.parent.mkdir(parents=True, exist_ok=True)
    ens_path.write_text(json.dumps(members_full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    print(f"wrote {csv_path}")
    print(
        f"primary={package['primary_member']['event_id']} "
        f"peak_q={package['primary_member']['peak_q_mucum_m3s']} "
        f"peak_n_cm={package['primary_member']['peak_stage_mucum_cm']}"
    )


if __name__ == "__main__":
    main()
