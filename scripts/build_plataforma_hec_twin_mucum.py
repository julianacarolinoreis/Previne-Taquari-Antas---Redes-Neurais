#!/usr/bin/env python3
"""Assemble the HEC/REC twin public platform (JSON feed + map page).

One place where Muçum ~5d twin results land — like the RNA live platform —
with corridor rain on a map and links to audit JSON/HTML.

Research only. Does not touch RNA. Does not invent STZ rating curve.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
POINTS = ROOT / "assets" / "data" / "basin_forecast_points.json"

FEED_JSON = OUT / "plataforma_hec_twin_mucum_latest.json"
FEED_HTML = OUT / "plataforma_hec_twin_mucum.html"
ROOT_HTML = ROOT / "plataforma_hec_twin.html"

PAGES_BASE = (
    "https://julianacarolinoreis.github.io/Previne-Taquari-Antas---Redes-Neurais"
)
STUDY_REL = "assets/data/estudo_bacia_taquari_antas"

SUBBASIN_LABELS = {
    "SB_PRATA_7868": "Prata / Turvo-Humatã",
    "SB_ANTAS_RESIDUAL": "Antas residual",
    "SB_CARREIRO_7866": "Carreiro",
    "SB_STZ_RESIDUAL": "Residual até Santa Tereza",
    "SB_INC_MUCUM": "Incremento até Muçum",
}

SUBBASIN_OFFSETS = {
    "SB_PRATA_7868": (0.04, -0.06),
    "SB_ANTAS_RESIDUAL": (-0.02, 0.02),
    "SB_CARREIRO_7866": (0.0, 0.0),
    "SB_STZ_RESIDUAL": (0.03, 0.03),
    "SB_INC_MUCUM": (-0.03, -0.04),
}

UG_CORRIDOR = {"Prata", "Carreiro", "Médio Taquari-Antas"}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# Corridor anchoring catalog: forçantes HEC + monitores upstream + chuvas PREVINE.
# Codes without coords in basin_forecast_points are resolved from postos/pluvio inventories.
ANCHOR_SPEC: list[tuple[str, str, str]] = [
    ("86510000", "target", "Muçum (alvo N)"),
    ("86472600", "level_control", "Santa Tereza (sem curva N↔Q)"),
    ("86472000", "level_control", "Antas / Linha José Júlio"),
    ("86507000", "level_control", "Carreiro / Cotiporã"),
    ("86125500", "level_control", "Prata / Jararaca"),
    ("86448000", "level_control", "Monte Claro barramento"),
    ("2851072", "rain", "Ibiraiaras (chuva Carreiro–Prata)"),
    ("2851044", "rain", "Guaporé (chuva)"),
    ("A894", "rain", "Serafina INMET A894"),
    ("432040401A", "rain", "Serafina CEMADEN Centro"),
    ("86488000", "upstream_monitor", "PCH Caçador montante"),
    ("86490500", "upstream_monitor", "PCH Boa Fé montante"),
    ("86497000", "upstream_monitor", "PCH São Paulo jusante"),
    ("86505500", "upstream_monitor", "PCH Linha Emília jusante"),
    ("86298000", "upstream_monitor", "UHE Castro Alves"),
    ("86125130", "upstream_monitor", "PCH Morro Grande jusante 2"),
]

ROLE_LABEL_PT = {
    "target": "alvo",
    "level_control": "nível / controle",
    "rain": "chuva",
    "upstream_monitor": "monitor montante",
}


def station_index() -> dict[str, dict[str, Any]]:
    """Merge basin IFS points + postos ANA + pluviometria for anchor coords."""
    out: dict[str, dict[str, Any]] = {}

    raw = load_json(POINTS) or {}
    for row in raw.get("points") or []:
        code = str(row.get("station_code") or "")
        if not code:
            continue
        out[code] = {
            "station_code": code,
            "name": row.get("name"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "role": row.get("role"),
            "source": "basin_forecast_points",
        }

    def _ingest_station(st: dict[str, Any], source: str) -> None:
        code = str(st.get("codigo") or st.get("code") or st.get("station_code") or "")
        if not code or code in out:
            return
        lat = st.get("lat") if st.get("lat") is not None else st.get("latitude")
        lon = st.get("lon") if st.get("lon") is not None else st.get("longitude")
        if lat is None or lon is None:
            return
        out[code] = {
            "station_code": code,
            "name": st.get("nome") or st.get("name"),
            "latitude": float(lat),
            "longitude": float(lon),
            "role": "inventory",
            "source": source,
        }

    postos = load_json(OUT / "postos_por_upg_latest.json") or {}
    by_upg = postos.get("by_upg")
    if isinstance(by_upg, dict):
        for rows in by_upg.values():
            if isinstance(rows, list):
                for st in rows:
                    if isinstance(st, dict):
                        _ingest_station(st, "postos_por_upg")
            elif isinstance(rows, dict):
                for st in rows.get("stations") or []:
                    if isinstance(st, dict):
                        _ingest_station(st, "postos_por_upg")
    for st in postos.get("stations_inside_g040") or []:
        if isinstance(st, dict):
            _ingest_station(st, "postos_g040")

    pluv = load_json(OUT / "pluviometria_g040_latest.json") or {}
    for st in pluv.get("stations") or []:
        code = str(st.get("codigo") or st.get("code") or "")
        if not code or code in out:
            continue
        lat = st.get("lat")
        lon = st.get("lon")
        if lat is None or lon is None:
            continue
        out[code] = {
            "station_code": code,
            "name": st.get("nome") or st.get("name"),
            "latitude": float(lat),
            "longitude": float(lon),
            "role": "rain_inventory",
            "source": "pluviometria_g040",
        }
    return out


def build_anchors(stations: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for code, role, label in ANCHOR_SPEC:
        st = stations.get(code) or {}
        lat = st.get("latitude")
        lon = st.get("longitude")
        if lat is None or lon is None:
            continue
        anchors.append(
            {
                "code": code,
                "role": role,
                "role_pt": ROLE_LABEL_PT.get(role, role),
                "label": label,
                "name": st.get("name") or label,
                "lat": float(lat),
                "lon": float(lon),
                "coord_source": st.get("source"),
            }
        )
    return anchors


def compact_primary(primary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(primary, dict):
        return None
    return {
        "event_id": primary.get("event_id"),
        "rise_cm": primary.get("rise_cm"),
        "peak_anchored_cm": primary.get("peak_anchored_cm"),
        "peak_time_utc": primary.get("peak_time_utc"),
        "peak_time_argmax_utc": primary.get("peak_time_argmax_utc"),
        "peak_time_method": primary.get("peak_time_method"),
    }


def series_sample(
    fwd: dict[str, Any] | None, step_hours: int = 6
) -> list[dict[str, Any]]:
    series = (fwd or {}).get("series_primary") or {}
    times = list(series.get("time_utc") or [])
    if not times:
        return []
    n_anch = list(series.get("n_mucum_anchored_cm") or [])
    d_n = list(series.get("delta_n_from_now_cm") or [])
    q = list(series.get("q_mucum_m3s") or [])
    rows: list[dict[str, Any]] = []
    for i, ts in enumerate(times):
        if i % step_hours != 0 and i != len(times) - 1:
            continue
        rows.append(
            {
                "time_utc": ts,
                "n_anchored_cm": n_anch[i] if i < len(n_anch) else None,
                "delta_n_cm": d_n[i] if i < len(d_n) else None,
                "q_mucum_m3s": q[i] if i < len(q) else None,
            }
        )
    return rows


def build_spatial(
    force: dict[str, Any] | None,
    stations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    meta = (force or {}).get("subbasin_meta") or {}
    aw = (force or {}).get("area_weighted_mean_mm") or {}
    features: list[dict[str, Any]] = []
    for sb_id, info in meta.items():
        code = str(info.get("point_code") or "")
        st = stations.get(code) or {}
        lat = st.get("latitude")
        lon = st.get("longitude")
        if lat is None or lon is None:
            continue
        dlat, dlon = SUBBASIN_OFFSETS.get(sb_id, (0.0, 0.0))
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(lon) + dlon, float(lat) + dlat],
                },
                "properties": {
                    "subbasin_id": sb_id,
                    "label": SUBBASIN_LABELS.get(sb_id, sb_id),
                    "point_code": code,
                    "point_name": st.get("name"),
                    "total_mm": info.get("total_mm"),
                    "past_mm": info.get("past_mm"),
                    "future_mm": info.get("future_mm"),
                },
            }
        )

    anchors = build_anchors(stations)
    # Primary twin controls remain the IFS sample / target set.
    primary_codes = {"86472000", "86472600", "86507000", "86510000"}
    controls = [
        {
            "code": a["code"],
            "label": a["label"],
            "name": a["name"],
            "lat": a["lat"],
            "lon": a["lon"],
            "role": a["role"],
        }
        for a in anchors
        if a["code"] in primary_codes
    ]

    return {
        "note_pt": (
            "Chuva IFS é proxy pontual por sub-bacia do corredor HEC — não máscara "
            "areal fechada. Pontos de amarração = forçantes + monitores do corredor "
            "(Prata/Carreiro/Antas→Muçum). UG G040 é contexto; Guaporé/Forqueta fora."
        ),
        "area_weighted_total_mm": aw.get("total_mm"),
        "area_weighted_past_mm": aw.get("past_mm"),
        "area_weighted_future_mm": aw.get("future_mm"),
        "window": (force or {}).get("window"),
        "rain_geojson": {"type": "FeatureCollection", "features": features},
        "controls": controls,
        "anchors": anchors,
        "anchor_count": len(anchors),
        "ug_filter": sorted(UG_CORRIDOR),
        "ug_geojson": "ugs_g040.geojson",
        "fozes_geojson": "fozes_principais_bho6.geojson",
    }


def build_feed() -> dict[str, Any]:
    fwd = load_json(OUT / "hec_twin_mucum_forward_5d_latest.json")
    live = load_json(OUT / "hec_twin_mucum_live_eval_latest.json")
    verify = load_json(OUT / "hec_twin_mucum_live_eval_verify_latest.json")
    hind = load_json(OUT / "hec_twin_mucum_hindcast_skill_5d_latest.json")
    force_live = load_json(OUT / "hec_twin_ifs_forcing_live_eval_latest.json")
    force_fwd = load_json(OUT / "hec_twin_ifs_forcing_5d_latest.json")
    stations = station_index()

    qs = (fwd or {}).get("quanto_sobe") or {}
    live_ans = (live or {}).get("answer_from_anchor") or {}
    live_ver = (live or {}).get("verification") or {}
    score = (verify or {}).get("scorecard") or {}

    live_primary = compact_primary(live_ans.get("primary"))
    use_live = live_primary is not None and live_primary.get("rise_cm") is not None

    if use_live:
        headline_source = "live_eval"
        headline_primary = live_primary
        headline_ensemble = live_ans.get("ensemble_rise_cm")
        headline_plain = live_ans.get("plain_pt") or (live or {}).get("plain_pt")
        rain_ifs = (live or {}).get("rain_ifs") or {}
        rain_total = rain_ifs.get("window_total_mm")
        if rain_total is None:
            rain_total = (rain_ifs.get("past_48h_mm") or 0) + (
                rain_ifs.get("next_72h_mm") or 0
            )
    else:
        headline_source = "forward"
        headline_primary = compact_primary(qs.get("primary"))
        headline_ensemble = qs.get("ensemble_rise_cm")
        headline_plain = qs.get("plain_pt")
        rain_total = qs.get("rain_forecast_mm_area_weighted")

    pages = {
        "platform_html": f"{PAGES_BASE}/{STUDY_REL}/plataforma_hec_twin_mucum.html",
        "platform_root": f"{PAGES_BASE}/plataforma_hec_twin.html",
        "platform_json": f"{PAGES_BASE}/{STUDY_REL}/plataforma_hec_twin_mucum_latest.json",
        "forward_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_forward_5d.html",
        "live_eval_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_live_eval.html",
        "verify_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_live_eval_verify.html",
        "hindcast_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_hindcast_skill_5d.html",
        "mapa_subbacias": f"{PAGES_BASE}/{STUDY_REL}/mapa_subbacias.html",
        "rna_mucum_live": f"{PAGES_BASE}/mucum_previsao_inundacao.html",
    }

    local = {
        "platform_html": "plataforma_hec_twin_mucum.html",
        "platform_json": "plataforma_hec_twin_mucum_latest.json",
        "forward_html": "hec_twin_mucum_forward_5d.html",
        "forward_json": "hec_twin_mucum_forward_5d_latest.json",
        "live_eval_html": "hec_twin_mucum_live_eval.html",
        "live_eval_json": "hec_twin_mucum_live_eval_latest.json",
        "verify_html": "hec_twin_mucum_live_eval_verify.html",
        "verify_json": "hec_twin_mucum_live_eval_verify_latest.json",
        "hindcast_html": "hec_twin_mucum_hindcast_skill_5d.html",
        "hindcast_json": "hec_twin_mucum_hindcast_skill_5d_latest.json",
        "forcing_live_json": "hec_twin_ifs_forcing_live_eval_latest.json",
        "forcing_forward_json": "hec_twin_ifs_forcing_5d_latest.json",
        "mapa_subbacias": "mapa_subbacias.html",
    }

    return {
        "schema_version": "plataforma_hec_twin_mucum_v1",
        "generated_at_utc": utc_now(),
        "status": "research_platform_ready",
        "label_pt": "Plataforma HEC/REC · gêmeo Muçum ~5d",
        "purpose_pt": (
            "Onde o resultado do gêmeo HEC (REC) vai parar: quanto sobe em Muçum, "
            "chuva espacializada no corredor, verificação ao vivo e skill hindcast — "
            "no GitHub Pages, como a plataforma das RNAs."
        ),
        "discipline": {
            "research_not_alert": True,
            "does_not_touch_rna": True,
            "no_invented_stz_rating_curve": True,
            "ifs_point_proxy_not_areal_mask": True,
            "corridor_not_full_g040": True,
        },
        "where_results_go": {
            "pages_base": PAGES_BASE,
            "study_dir": STUDY_REL,
            "pages": pages,
            "local": local,
            "pipeline_pt": [
                "IFS QPF → forçante por sub-bacia (JSON)",
                "Gêmeo HEC eventwise → Q Muçum → curva-chave → ΔN",
                "Feed estável plataforma_hec_twin_mucum_latest.json",
                "Página mapa plataforma_hec_twin_mucum.html (+ atalho raiz)",
                "Deploy Pages quando paths do estudo / plataforma mudam",
            ],
        },
        "headline": {
            "source": headline_source,
            "question_pt": "Com a chuva (prevista ou do evento), quanto sobe Muçum?",
            "plain_pt": headline_plain,
            "primary": headline_primary,
            "ensemble_rise_cm": headline_ensemble,
            "rain_mm_area_weighted": rain_total,
            "verification_plain_pt": live_ver.get("plain_pt") or score.get("plain_pt"),
            "scorecard": {
                "verdict_level": score.get("verdict_level")
                or live_ver.get("verdict_level"),
                "peak_error_cm": score.get("peak_error_cm")
                or live_ver.get("peak_error_cm"),
                "timing_error_h": score.get("timing_error_h")
                or live_ver.get("timing_error_h"),
                "obs_peak_cm": score.get("obs_peak_cm") or live_ver.get("obs_peak_cm"),
                "predicted_peak_anchored_cm": (
                    ((verify or {}).get("forecast_ref") or {}).get(
                        "predicted_peak_anchored_cm"
                    )
                    or (headline_primary or {}).get("peak_anchored_cm")
                ),
            },
        },
        "products": {
            "forward_5d": {
                "status": (fwd or {}).get("status"),
                "generated_at_utc": (fwd or {}).get("generated_at_utc"),
                "plain_pt": qs.get("plain_pt"),
                "primary": compact_primary(qs.get("primary")),
                "ensemble_rise_cm": qs.get("ensemble_rise_cm"),
                "rain_forecast_mm": qs.get("rain_forecast_mm_area_weighted"),
                "level_now": qs.get("level_now"),
                "note_pt": (
                    "Produto operacional de pesquisa (~5d). Se a forçante estiver seca "
                    "ou a telemetria cair, o ΔN pode ir a zero — conferir live eval."
                ),
            },
            "live_eval": {
                "status": (live or {}).get("status"),
                "generated_at_utc": (live or {}).get("generated_at_utc"),
                "plain_pt": live_ans.get("plain_pt") or (live or {}).get("plain_pt"),
                "primary": compact_primary(live_ans.get("primary")),
                "ensemble_rise_cm": live_ans.get("ensemble_rise_cm"),
                "observations": (live or {}).get("observations"),
                "verification": live_ver,
            },
            "verify": {
                "status": (verify or {}).get("status"),
                "generated_at_utc": (verify or {}).get("generated_at_utc"),
                "plain_pt": (verify or {}).get("plain_pt"),
                "observed": (verify or {}).get("observed"),
                "scorecard": score,
            },
            "hindcast_skill": {
                "status": (hind or {}).get("status"),
                "generated_at_utc": (hind or {}).get("generated_at_utc"),
                "summary": (hind or {}).get("summary"),
                "verdict": (hind or {}).get("verdict"),
            },
        },
        "spatial": build_spatial(force_live or force_fwd, stations),
        "hydrograph_sample_6h": series_sample(fwd, step_hours=6),
        "param_selection": {
            "forward": (fwd or {}).get("param_selection"),
            "live": (live or {}).get("param_selection"),
        },
        "artifacts": {
            "json": "plataforma_hec_twin_mucum_latest.json",
            "html": "plataforma_hec_twin_mucum.html",
            "root_entry": "plataforma_hec_twin.html",
        },
        "automation": {
            "robot_pt": "Robô GitHub Actions puxa IFS → gêmeo HEC → plataforma",
            "workflow": ".github/workflows/hec-twin-mucum-forward.yml",
            "schedule_cron": "12 */6 * * *",
            "schedule_pt": "a cada 6 horas (min :12) + disparo manual",
            "steps_pt": [
                "Busca chuva IFS (Open-Meteo) por sub-bacia do corredor",
                "Roda gêmeo HEC Muçum ~5d (âncora no nível ao vivo se houver)",
                "Reconstrói plataforma_hec_twin_mucum (mapa + feed)",
                "Publica no main → GitHub Pages atualiza",
            ],
            "does_not_touch_rna": True,
            "research_not_alert": True,
        },
    }


def render_html(feed: dict[str, Any]) -> str:
    payload = json.dumps(feed, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PREVINE · Plataforma HEC/REC — Muçum ~5d</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;550;650;700&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  :root {{
    --ink:#12241c; --muted:#4a6356; --line:#c5d5cb; --panel:#f3f7f4;
    --brand:#0f5c45; --warn:#8a5a12; --ok:#1f6b4a; --mapmist:#d7e4dc;
  }}
  * {{ box-sizing:border-box }}
  html,body {{ margin:0; height:100%; color:var(--ink);
    font-family:"IBM Plex Sans", "Segoe UI", sans-serif;
    background:
      radial-gradient(900px 420px at 10% -10%, #cfe2d6 0%, transparent 55%),
      linear-gradient(165deg, #d9e6de 0%, #eef3ef 45%, #f7f4ee 100%);
  }}
  .shell {{ display:grid; grid-template-columns:minmax(320px,420px) 1fr; height:100vh; }}
  aside {{
    overflow:auto; padding:1rem 1.05rem 2rem; border-right:1px solid var(--line);
    background:linear-gradient(180deg, rgba(243,247,244,.96), rgba(238,243,239,.92));
  }}
  #map {{ height:100%; background:var(--mapmist); position:relative; }}
  .brand {{
    font-family:Fraunces, Georgia, serif;
    font-size:clamp(1.55rem, 2.4vw, 1.95rem); line-height:1.05; margin:0 0 .35rem;
  }}
  .brand span {{ color:var(--brand); }}
  .eyebrow {{
    display:inline-block; font-size:.72rem; font-weight:700; letter-spacing:.08em;
    text-transform:uppercase; color:var(--brand); margin:0 0 .55rem;
  }}
  .lede {{ color:var(--muted); font-size:.95rem; margin:0 0 .9rem; }}
  .warn {{
    border-left:4px solid var(--warn); background:#f5ecda; color:#6d4810;
    padding:.65rem .75rem; font-size:.86rem; margin:0 0 .9rem;
  }}
  .hero-answer {{
    background:linear-gradient(135deg, #12352a, #1a4d3a 55%, #245744);
    color:#eef7f1; padding:1rem 1.05rem; margin:0 0 1rem;
    box-shadow:0 12px 28px rgba(18,52,42,.22);
  }}
  .hero-answer .k {{ font-size:.72rem; letter-spacing:.07em; text-transform:uppercase; opacity:.8; }}
  .hero-answer .big {{
    font-family:Fraunces, Georgia, serif; font-size:clamp(1.7rem, 3vw, 2.25rem);
    margin:.15rem 0;
  }}
  .hero-answer .sub {{ font-size:.92rem; opacity:.92; line-height:1.4; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:.55rem; margin:0 0 1rem; }}
  .stat {{ background:var(--panel); border:1px solid var(--line); padding:.65rem .7rem; }}
  .stat b {{ display:block; font-size:1.15rem; font-variant-numeric:tabular-nums; color:var(--brand); }}
  .stat span {{ font-size:.75rem; color:var(--muted); }}
  section {{ margin:1.1rem 0 0; padding-top:.85rem; border-top:1px solid var(--line); }}
  h2 {{ font-family:Fraunces, Georgia, serif; font-size:1.05rem; margin:0 0 .45rem; }}
  p, li {{ font-size:.9rem; line-height:1.45; color:#24362d; }}
  ul, ol {{ margin:.35rem 0 0; padding-left:1.1rem; }}
  a {{ color:#0a5f7a; font-weight:650; }}
  .path {{
    font-family:ui-monospace, "IBM Plex Mono", monospace; font-size:.72rem;
    background:#e7efe9; padding:.35rem .45rem; word-break:break-all; display:block;
  }}
  .pipe {{ font-size:.84rem; color:var(--muted); }}
  table {{ width:100%; border-collapse:collapse; font-size:.82rem; background:#fff; }}
  th, td {{ text-align:left; padding:.35rem .4rem; border-bottom:1px solid #d7e2db; }}
  th {{ color:var(--muted); font-size:.7rem; text-transform:uppercase; letter-spacing:.04em; }}
  .legend {{
    position:absolute; z-index:500; right:12px; bottom:12px; background:rgba(243,247,244,.94);
    border:1px solid var(--line); padding:.55rem .7rem; font-size:.78rem; max-width:240px;
  }}
  .legend i {{ display:inline-block; width:10px; height:10px; margin-right:6px; vertical-align:middle; }}
  .verdict-ok {{ color:var(--ok); font-weight:700; }}
  .verdict-warn {{ color:var(--warn); font-weight:700; }}
  @media (max-width:900px) {{
    .shell {{ grid-template-columns:1fr; grid-template-rows:auto minmax(48vh,1fr); height:auto; min-height:100vh; }}
    aside {{ border-right:0; border-bottom:1px solid var(--line); }}
    #map {{ min-height:48vh; }}
  }}
</style>
</head>
<body>
<div class="shell">
  <aside>
    <p class="eyebrow">PREVINE · pesquisa · não é alerta</p>
    <h1 class="brand">Plataforma <span>HEC/REC</span></h1>
    <p class="lede">Onde o resultado do gêmeo hidrológico vai parar — quanto sobe em Muçum, com a chuva no mapa do corredor.</p>
    <div class="warn"><strong>PESQUISA.</strong> Não substitui alerta oficial. RNA de curto prazo segue noutro trilho e não é alterada aqui. Santa Tereza: só Q diagnóstico (sem curva).</div>

    <div class="hero-answer">
      <div class="k">Resultado em destaque</div>
      <div class="big" id="hero-big">Carregando…</div>
      <div class="sub" id="hero-sub"></div>
    </div>
    <div class="grid" id="stats"></div>

    <section>
      <h2>Para onde vai o resultado?</h2>
      <p>GitHub Pages — mesma casa da plataforma das RNAs, pasta do estudo HEC:</p>
      <p class="path" id="pages-url"></p>
      <ol class="pipe" id="pipeline"></ol>
    </section>

    <section>
      <h2>Verificação ao vivo</h2>
      <p id="verify-plain"></p>
      <div class="grid" id="verify-stats"></div>
    </section>

    <section>
      <h2>Skill hindcast (LOO)</h2>
      <p id="hind-plain"></p>
    </section>

    <section>
      <h2>Robô automático</h2>
      <p id="robot-plain"></p>
      <ol class="pipe" id="robot-steps"></ol>
    </section>

    <section>
      <h2>Pontos de amarração</h2>
      <p class="lede" style="margin:0 0 .5rem">Forçantes de nível/chuva e monitores do corredor — não só o alvo Muçum.</p>
      <table>
        <thead><tr><th>Papel</th><th>Ponto</th><th>Código</th></tr></thead>
        <tbody id="anchor-rows"></tbody>
      </table>
    </section>

    <section>
      <h2>Chuva por sub-bacia (proxy IFS)</h2>
      <table>
        <thead><tr><th>Sub-bacia</th><th>Total</th><th>Passado</th><th>Futuro</th></tr></thead>
        <tbody id="rain-rows"></tbody>
      </table>
    </section>

    <section>
      <h2>Série ancorada (amostra 6 h)</h2>
      <table>
        <thead><tr><th>UTC</th><th>N anc.</th><th>ΔN</th><th>Q</th></tr></thead>
        <tbody id="series-rows"></tbody>
      </table>
    </section>

    <section>
      <h2>Produtos auditáveis</h2>
      <ul id="product-links"></ul>
      <p style="margin-top:.7rem">
        <a href="../../mucum_previsao_inundacao.html">Plataforma RNA Muçum (curto prazo)</a> ·
        <a href="index.html">Estudo da bacia</a> ·
        <a href="mapa_subbacias.html">Mapa UPG + fozes</a>
      </p>
    </section>
  </aside>
  <div id="map" role="application" aria-label="Mapa do corredor HEC com chuva por sub-bacia">
    <div class="legend">
      <div><i style="background:#0f5c45"></i>UG do corredor</div>
      <div><i style="background:#b85a1a;border-radius:50%"></i>Chuva IFS (mm)</div>
      <div><i style="background:#b85a1a"></i>Alvo Muçum</div>
      <div><i style="background:#1e5fbf"></i>Controle de nível</div>
      <div><i style="background:#0a7a6a;border-radius:50%"></i>Chuva (forçante)</div>
      <div><i style="background:#5a6570"></i>Monitor montante</div>
    </div>
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const FEED = {payload};

function fmt(n, d=0) {{
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("pt-BR", {{ maximumFractionDigits:d, minimumFractionDigits:d }});
}}
function rainColor(mm) {{
  if (mm == null) return "#9bb8a8";
  if (mm < 5) return "#a8c5b4";
  if (mm < 15) return "#5f9e7a";
  if (mm < 30) return "#c47a2a";
  if (mm < 50) return "#b85a1a";
  return "#8f2f2a";
}}
function rainRadius(mm) {{
  const v = Math.max(0, Number(mm) || 0);
  return Math.max(8, Math.min(34, 8 + Math.sqrt(v) * 3.2));
}}

const h = FEED.headline || {{}};
const p = h.primary || {{}};
const ens = h.ensemble_rise_cm || {{}};
document.getElementById("hero-big").textContent =
  (p.rise_cm == null) ? "Sem ΔN" : ("+" + fmt(p.rise_cm, 0) + " cm");
document.getElementById("hero-sub").textContent =
  (h.plain_pt || "") +
  (p.peak_anchored_cm != null
    ? (" · pico ancorado ~" + fmt(p.peak_anchored_cm, 0) + " cm" +
       (p.peak_time_utc ? (" @ " + p.peak_time_utc) : ""))
    : "");

document.getElementById("stats").innerHTML = [
  ["Fonte", h.source === "live_eval" ? "live eval" : "forward 5d"],
  ["Banda ΔN", (ens.min != null) ? (fmt(ens.min,0) + "–" + fmt(ens.max,0) + " cm") : "—"],
  ["Chuva AW", fmt(h.rain_mm_area_weighted, 1) + " mm"],
  ["Análogo", p.event_id || "—"],
].map(([k,v]) => `<div class="stat"><b>${{v}}</b><span>${{k}}</span></div>`).join("");

document.getElementById("pages-url").textContent =
  (FEED.where_results_go && FEED.where_results_go.pages && FEED.where_results_go.pages.platform_html) || "";
document.getElementById("pipeline").innerHTML =
  ((FEED.where_results_go && FEED.where_results_go.pipeline_pt) || [])
    .map(t => `<li>${{t}}</li>`).join("");

document.getElementById("verify-plain").textContent =
  h.verification_plain_pt || "Sem verificação publicada.";
const sc = h.scorecard || {{}};
document.getElementById("verify-stats").innerHTML = [
  ["Erro de pico", (sc.peak_error_cm == null ? "—" : fmt(sc.peak_error_cm, 1) + " cm")],
  ["Erro horário", (sc.timing_error_h == null ? "—" : fmt(sc.timing_error_h, 1) + " h")],
  ["Obs pico", fmt(sc.obs_peak_cm, 0) + " cm"],
  ["Prev pico", fmt(sc.predicted_peak_anchored_cm, 0) + " cm"],
].map(([k,v]) => `<div class="stat"><b>${{v}}</b><span>${{k}}</span></div>`).join("");

const hind = (FEED.products && FEED.products.hindcast_skill) || {{}};
const verd = hind.verdict || {{}};
const summ = hind.summary || {{}};
document.getElementById("hind-plain").innerHTML =
  `<span class="${{(verd.level === "usable_research") ? "verdict-ok" : "verdict-warn"}}">${{verd.level || "—"}}</span>
   — ${{verd.plain_pt || ""}}
   (n=${{summ.n_scored ?? "—"}}, ΔN rel ~${{summ.mean_rise_n_rel_err != null ? Math.round(100*summ.mean_rise_n_rel_err)+"%" : "—"}},
   ${{summ.n_rise_n_within_50pct ?? "—"}}/${{summ.n_scored ?? "—"}} ≤50%).`;

const rainFeats = (((FEED.spatial || {{}}).rain_geojson || {{}}).features) || [];
document.getElementById("rain-rows").innerHTML = rainFeats.map(f => {{
  const pr = f.properties || {{}};
  return `<tr><td>${{pr.label || pr.subbasin_id}}</td><td>${{fmt(pr.total_mm,1)}}</td><td>${{fmt(pr.past_mm,1)}}</td><td>${{fmt(pr.future_mm,1)}}</td></tr>`;
}}).join("") || `<tr><td colspan="4">Sem forçante espacial</td></tr>`;

document.getElementById("series-rows").innerHTML =
  (FEED.hydrograph_sample_6h || []).slice(0, 16).map(r =>
    `<tr><td>${{r.time_utc}}</td><td>${{fmt(r.n_anchored_cm,1)}}</td><td>${{fmt(r.delta_n_cm,1)}}</td><td>${{fmt(r.q_mucum_m3s,1)}}</td></tr>`
  ).join("") || `<tr><td colspan="4">Sem série forward</td></tr>`;

const loc = (FEED.where_results_go && FEED.where_results_go.local) || {{}};
document.getElementById("product-links").innerHTML = [
  ["Forward ~5d", loc.forward_html, loc.forward_json],
  ["Live eval", loc.live_eval_html, loc.live_eval_json],
  ["Verify", loc.verify_html, loc.verify_json],
  ["Hindcast skill", loc.hindcast_html, loc.hindcast_json],
  ["Forçante IFS (live)", null, loc.forcing_live_json],
  ["Feed desta plataforma", null, loc.platform_json],
].map(([label, html, js]) =>
  `<li><strong>${{label}}:</strong> ${{html ? `<a href="${{html}}">HTML</a> · ` : ""}}${{js ? `<a href="${{js}}">JSON</a>` : ""}}</li>`
).join("");

const auto = FEED.automation || {{}};
document.getElementById("robot-plain").textContent =
  (auto.robot_pt || "Robô previsto") +
  (auto.schedule_pt ? (" · " + auto.schedule_pt) : "") +
  (auto.workflow ? (" · `" + auto.workflow + "`") : "");
document.getElementById("robot-steps").innerHTML =
  (auto.steps_pt || []).map(t => `<li>${{t}}</li>`).join("");

const anchors = (FEED.spatial && FEED.spatial.anchors) || [];
document.getElementById("anchor-rows").innerHTML = anchors.map(a =>
  `<tr><td>${{a.role_pt || a.role}}</td><td>${{a.label}}</td><td><code>${{a.code}}</code></td></tr>`
).join("") || `<tr><td colspan="3">Sem pontos de amarração</td></tr>`;

const map = L.map("map", {{ zoomControl:true }}).setView([-29.12, -51.72], 9);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
  attribution: "&copy; OpenStreetMap", maxZoom: 18,
}}).addTo(map);

const ugFilter = new Set((FEED.spatial && FEED.spatial.ug_filter) || []);
fetch("ugs_g040.geojson").then(r => r.json()).then(geo => {{
  L.geoJSON(geo, {{
    filter: f => ugFilter.has((f.properties || {{}}).sub_bacia),
    style: {{ color:"#0f5c45", weight:1.2, fillColor:"#0f5c45", fillOpacity:0.08 }},
    onEachFeature: (f, layer) => {{
      layer.bindPopup(`<strong>${{(f.properties || {{}}).sub_bacia || "UG"}}</strong><br/>contexto G040 (corredor)`);
    }},
  }}).addTo(map);
}}).catch(() => {{}});

fetch("fozes_principais_bho6.geojson").then(r => r.json()).then(geo => {{
  L.geoJSON(geo, {{
    pointToLayer: (_f, latlng) => L.circleMarker(latlng, {{
      radius:5, color:"#245744", weight:2, fillColor:"#fff", fillOpacity:1,
    }}),
    onEachFeature: (f, layer) => {{
      layer.bindPopup(`<strong>${{(f.properties || {{}}).label || "foz"}}</strong>`);
    }},
  }}).addTo(map);
}}).catch(() => {{}});

rainFeats.forEach(f => {{
  const pr = f.properties || {{}};
  const [lon, lat] = f.geometry.coordinates;
  const mm = pr.total_mm;
  L.circleMarker([lat, lon], {{
    radius: rainRadius(mm), color:"#5c4030", weight:1,
    fillColor: rainColor(mm), fillOpacity:0.72,
  }}).bindPopup(
    `<strong>${{pr.label}}</strong><br/>total ${{fmt(mm,1)}} mm` +
    `<br/>passado ${{fmt(pr.past_mm,1)}} · futuro ${{fmt(pr.future_mm,1)}}` +
    `<br/><span style="opacity:.75">proxy ${{pr.point_code}} · ${{pr.point_name || ""}}</span>`
  ).addTo(map);
}});

function anchorStyle(role) {{
  if (role === "target") return {{ radius: 8, color: "#b85a1a", fillColor: "#f0a35a", fillOpacity: 0.95 }};
  if (role === "level_control") return {{ radius: 6, color: "#1e5fbf", fillColor: "#fff", fillOpacity: 1 }};
  if (role === "rain") return {{ radius: 6, color: "#0a7a6a", fillColor: "#3cbc9c", fillOpacity: 0.85 }};
  return {{ radius: 5, color: "#5a6570", fillColor: "#d5dbe0", fillOpacity: 0.95 }};
}}
(anchors.length ? anchors : ((FEED.spatial && FEED.spatial.controls) || [])).forEach(c => {{
  if (c.lat == null || c.lon == null) return;
  const style = anchorStyle(c.role || (c.code === "86510000" ? "target" : "level_control"));
  L.circleMarker([c.lat, c.lon], Object.assign({{ weight: 2 }}, style))
    .bindPopup(`<strong>${{c.label}}</strong><br/>${{c.role_pt || c.role || ""}}<br/>${{c.name || ""}} · ${{c.code}}`)
    .addTo(map);
}});

const note = document.createElement("div");
note.className = "legend";
note.style.right = "12px";
note.style.bottom = "92px";
note.style.maxWidth = "260px";
note.textContent = (FEED.spatial && FEED.spatial.note_pt) || "";
document.getElementById("map").appendChild(note);
</script>
</body>
</html>
"""


def render_root_entry() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PREVINE · Plataforma HEC/REC</title>
<meta http-equiv="refresh" content="0; url=assets/data/estudo_bacia_taquari_antas/plataforma_hec_twin_mucum.html"/>
<link rel="canonical" href="assets/data/estudo_bacia_taquari_antas/plataforma_hec_twin_mucum.html"/>
<style>
  body { margin:0; font-family:"IBM Plex Sans", "Source Sans 3", sans-serif; background:#e8f0ea; color:#12241c;
    display:grid; place-items:center; min-height:100vh; }
  main { max-width:36rem; padding:2rem; }
  a { color:#0f5c45; font-weight:700; }
</style>
</head>
<body>
<main>
  <p><strong>PREVINE · Plataforma HEC/REC</strong></p>
  <p>Redirecionando para o mapa e os resultados do gêmeo Muçum ~5d…</p>
  <p><a href="assets/data/estudo_bacia_taquari_antas/plataforma_hec_twin_mucum.html">Abrir plataforma</a>
     · <a href="mucum_previsao_inundacao.html">Plataforma RNA Muçum</a></p>
</main>
</body>
</html>
"""


def main() -> None:
    feed = build_feed()
    FEED_JSON.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    FEED_HTML.write_text(render_html(feed), encoding="utf-8")
    ROOT_HTML.write_text(render_root_entry(), encoding="utf-8")
    print(f"wrote {FEED_JSON.relative_to(ROOT)}")
    print(f"wrote {FEED_HTML.relative_to(ROOT)}")
    print(f"wrote {ROOT_HTML.relative_to(ROOT)}")
    print(
        "headline",
        feed["headline"]["source"],
        feed["headline"]["primary"],
        "rain_features",
        len(feed["spatial"]["rain_geojson"]["features"]),
        "pages",
        feed["where_results_go"]["pages"]["platform_html"],
    )


if __name__ == "__main__":
    main()
