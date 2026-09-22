#!/usr/bin/env python3
"""Build the public HEC/REC platform v3.

V3 keeps the existing audited basin inventory and calibration products, adds the
full spatial ECMWF/IFS rain field over the Muçum catchment, and prevents the
legacy point-proxy HEC twin result from being presented as the current forecast.

Research only. Not an official alert.
"""

from __future__ import annotations

import json
from pathlib import Path

import build_plataforma_hec_twin_mucum as base
import plataforma_hec_twin_mucum_ui_v3 as ui

ROOT = base.ROOT
OUT = base.OUT
SPATIAL_DIR = OUT / "spatial_ifs_mucum"
SPATIAL_JSON = SPATIAL_DIR / "spatial_ifs_mucum_latest.json"


def load_spatial() -> dict:
    if not SPATIAL_JSON.exists():
        return {}
    try:
        return json.loads(SPATIAL_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def spatial_summary(pkg: dict) -> dict:
    rain = pkg.get("rainfall_120h") or {}
    grid = pkg.get("grid") or {}
    cells = list(pkg.get("cells") or [])
    wettest = sorted(cells, key=lambda c: float(c.get("total_120h_mm") or 0), reverse=True)[:10]
    return {
        "available": bool(pkg and cells),
        "generated_at_utc": pkg.get("generated_at_utc"),
        "window": pkg.get("window") or {},
        "model": ((pkg.get("source") or {}).get("model")),
        "resolution_deg": grid.get("resolution_deg"),
        "intersecting_cells": grid.get("intersecting_cells"),
        "basin_area_km2": grid.get("basin_area_projected_km2"),
        "coverage_ratio": grid.get("coverage_ratio"),
        "spatial_field_preserved": grid.get("spatial_field_preserved"),
        "cell_total_min_mm": rain.get("cell_total_min_mm"),
        "cell_total_p25_mm": rain.get("cell_total_p25_mm"),
        "cell_total_median_mm": rain.get("cell_total_median_mm"),
        "cell_total_p75_mm": rain.get("cell_total_p75_mm"),
        "cell_total_max_mm": rain.get("cell_total_max_mm"),
        "total_rain_volume_hm3": rain.get("total_rain_volume_hm3_over_basin"),
        "equivalent_basin_depth_mm_for_audit_only": rain.get("equivalent_basin_depth_mm_for_audit_only"),
        "geojson": "spatial_ifs_mucum/spatial_ifs_mucum_cells_120h.geojson",
        "png": "spatial_ifs_mucum/spatial_ifs_mucum_120h.png",
        "cells_csv": "spatial_ifs_mucum/spatial_ifs_mucum_cells_120h.csv",
        "hourly_csv": "spatial_ifs_mucum/spatial_ifs_mucum_hourly.csv",
        "wettest_cells": [
            {
                "cell_id": c.get("cell_id"),
                "latitude": c.get("latitude"),
                "longitude": c.get("longitude"),
                "overlap_km2": c.get("overlap_km2"),
                "total_120h_mm": c.get("total_120h_mm"),
                "rain_volume_hm3": c.get("rain_volume_hm3"),
            }
            for c in wettest
        ],
        "note_pt": (
            "Campo IFS 0,25° preservado célula a célula em toda a bacia contribuinte até Muçum. "
            "A profundidade equivalente da bacia aparece apenas para auditoria volumétrica; "
            "ela não substitui o campo espacial na modelagem."
        ),
    }



def build_hydro_nodes(feed: dict) -> dict:
    """Curated hydrologic nodes with the freshest values already published by PREVINE.

    Never invent discharge. Q is exposed only where a validated/declared conversion exists.
    """
    stz_live = base.load_json(ROOT / "previsao_ao_vivo.json") or {}
    muc_live = base.load_json(ROOT / "previsao_ao_vivo_mucum.json") or {}
    fwd = base.load_json(OUT / "hec_twin_mucum_forward_5d_latest.json") or {}
    q_rating = (((fwd.get("quanto_sobe") or {}).get("q_now_from_rating_m3s") or {}).get("q_m3s"))

    anchors = {str(a.get("code")): a for a in (((feed.get("spatial") or {}).get("anchors")) or [])}
    inventory = {}
    for feat in ((((feed.get("spatial") or {}).get("basin_network")) or {}).get("features") or []):
        p = feat.get("properties") or {}
        g = feat.get("geometry") or {}
        co = g.get("coordinates") or []
        code = str(p.get("code") or "")
        if code and len(co) >= 2:
            inventory[code] = {
                "lat": float(co[1]), "lon": float(co[0]),
                "name": p.get("name"), "ug": p.get("ug"),
                "area_km2": p.get("area_km2"), "kind": p.get("kind"),
            }

    rows = []
    seen = set()

    def coords_for(code: str, status: dict | None = None):
        status = status or {}
        lat, lon = status.get("latitude"), status.get("longitude")
        if lat is not None and lon is not None:
            return float(lat), float(lon)
        a = anchors.get(code) or {}
        if a.get("lat") is not None and a.get("lon") is not None:
            return float(a["lat"]), float(a["lon"])
        inv = inventory.get(code) or {}
        if inv.get("lat") is not None and inv.get("lon") is not None:
            return float(inv["lat"]), float(inv["lon"])
        return None, None

    for st in stz_live.get("estacoes_status") or []:
        code = str(st.get("estacao") or "")
        if not code or code in seen:
            continue
        lat, lon = coords_for(code, st)
        if lat is None or lon is None:
            continue
        inv = inventory.get(code) or {}
        a = anchors.get(code) or {}
        rows.append({
            "code": code,
            "name": st.get("nome") or a.get("label") or inv.get("name") or code,
            "lat": lat, "lon": lon,
            "ug": a.get("ug") or inv.get("ug"),
            "role": st.get("papel") or a.get("role_pt") or "monitor",
            "level_cm": st.get("ultima_leitura_bruta_nivel_cm"),
            "level_at_local": st.get("ultima_leitura_bruta"),
            "age_min": st.get("idade_leitura_min"),
            "qc_status": st.get("qc_status"),
            "source": st.get("fonte") or "SGB/ANA",
            "drainage_area_km2": inv.get("area_km2"),
            "discharge_m3s": None,
            "discharge_kind": None,
            "discharge_note_pt": "Vazão não exibida sem curva-chave validada para este nó.",
        })
        seen.add(code)

    # Muçum is produced by its own live robot and may not appear in STZ estacoes_status.
    code = "86510000"
    if code not in seen:
        lat, lon = coords_for(code)
        if lat is not None and lon is not None:
            inv = inventory.get(code) or {}
            rows.append({
                "code": code,
                "name": "Muçum",
                "lat": lat, "lon": lon,
                "ug": (anchors.get(code) or {}).get("ug") or inv.get("ug"),
                "role": "alvo Muçum",
                "level_cm": muc_live.get("telemetria_ultima_nivel_cm") or muc_live.get("nivel_rio_agora_cm"),
                "level_at_local": muc_live.get("telemetria_ultima_em") or muc_live.get("nivel_rio_agora_em"),
                "age_min": muc_live.get("idade_telemetria_min"),
                "qc_status": "NORMAL" if muc_live.get("disponivel") else "ATENCAO",
                "source": "SGB/ANA - Hidrotelemetria",
                "drainage_area_km2": inv.get("area_km2"),
                "discharge_m3s": q_rating,
                "discharge_kind": "rating_curve_estimate",
                "discharge_note_pt": (
                    "Q estimada a partir do nível observado pela curva-chave de Muçum "
                    "usada pelo gêmeo. Não confundir com a vazão interna do gêmeo HEC."
                ),
            })
            seen.add(code)

    # Highest-value curated nodes first.
    priority = {
        "86510000": 0, "86472600": 1, "86472000": 2, "86507000": 3,
        "86125130": 4, "86125500": 5, "86298000": 6, "86306000": 7,
        "86448000": 8, "86430900": 9, "86447000": 10, "86505500": 11,
    }
    rows.sort(key=lambda r: (priority.get(r["code"], 99), r["code"]))
    return {
        "generated_from": ["previsao_ao_vivo.json", "previsao_ao_vivo_mucum.json", "hec_twin_mucum_forward_5d_latest.json"],
        "count": len(rows),
        "nodes": rows,
        "note_pt": (
            "Nós hidrológicos curados. Nível = telemetria publicada pelo robô PREVINE. "
            "Vazão só aparece quando existe conversão declarada; ausência de Q não significa vazão zero."
        ),
    }



def build_corridor_model_nodes(feed: dict, forward_pkg: dict) -> dict:
    """Summarize the spatial 5-zone twin Q(t) at hydrologic controls."""
    forcing = forward_pkg.get("forcing") or {}
    s = forward_pkg.get("series_primary") or {}
    times = list(s.get("time_utc") or [])
    if not times or not bool(forcing.get("spatial_field_full")):
        return {"available": False, "nodes": [], "reason": "spatial_5zone_twin_not_ready"}

    live_by_code = {
        str(n.get("code")): n
        for n in ((feed.get("hydro_nodes") or {}).get("nodes") or [])
        if n.get("code")
    }

    def loc(code: str, fallback=None):
        n = live_by_code.get(code) or {}
        if n.get("lat") is not None and n.get("lon") is not None:
            return float(n["lat"]), float(n["lon"])
        return fallback or (None, None)

    def summarize(code: str, name: str, series, fallback=None, role="controle do modelo"):
        vals = [float(v) for v in (series or []) if v is not None]
        lat, lon = loc(code, fallback)
        if not vals or lat is None or lon is None:
            return None
        peak_i = max(range(min(len(series), len(times))), key=lambda i: float(series[i]))
        return {
            "code": code,
            "name": name,
            "role": role,
            "lat": lat,
            "lon": lon,
            "q0_m3s": round(float(series[0]), 3),
            "peak_q_m3s": round(float(series[peak_i]), 3),
            "peak_time_utc": times[peak_i],
            "end_q_m3s": round(float(series[min(len(series), len(times))-1]), 3),
            "n_hours": min(len(series), len(times)),
            "engine": "gêmeo HEC/Python · 5 zonas",
            "forcing": "ECMWF/IFS espacial por interseção célula-zona",
        }

    rows = [
        summarize("86472000", "Antas · Linha José Júlio", s.get("q_antas_m3s"), role="J_ANTAS_86472000"),
        summarize(
            "J_CARREIRO_CONFLUENCE",
            "Confluência do Rio Carreiro",
            s.get("q_carreiro_confluence_m3s"),
            fallback=(-29.0901686, -51.7133474),
            role="J_CARREIRO_CONFLUENCE",
        ),
        summarize("86472600", "Santa Tereza", s.get("q_stz_diagnostic_m3s"), role="J_STZ_86472600"),
        summarize("86510000", "Muçum", s.get("q_mucum_m3s"), role="J_MUCUM_86510000"),
    ]
    rows = [r for r in rows if r]
    return {
        "available": bool(rows),
        "nodes": rows,
        "generated_at_utc": forward_pkg.get("generated_at_utc"),
        "forcing_artifact": forcing.get("artifact"),
        "note_pt": (
            "Nós do gêmeo espacial de 5 zonas. São saídas modeladas Q(t), separadas da telemetria. "
            "Muçum continua tendo como produto principal o HEC-HMS 4.13 espacial executado no mesmo ciclo."
        ),
    }


def build_feed_v3() -> dict:
    feed = base.enrich_feed(base.build_feed())
    spatial_pkg = load_spatial()
    sr = spatial_summary(spatial_pkg)
    feed["schema_version"] = "plataforma_hec_twin_mucum_v3"
    feed["status"] = "hec_hms_spatial_ready" if (OUT / "hec_hms_spatial_forecast_mucum_latest.json").exists() else "spatial_rain_ready_hydrology_integration_pending"
    feed["spatial_rain"] = sr
    feed["hydro_nodes"] = build_hydro_nodes(feed)

    # Prefer the real HEC-HMS 4.13 spatial run. Fall back to the Python twin
    # only when the HEC spatial artifact is unavailable.
    spatial_hec = base.load_json(OUT / "hec_hms_spatial_forecast_mucum_latest.json") or {}
    spatial_ready = spatial_hec.get("status") == "hec_hms_4_13_spatial_ifs_ready"
    forward_pkg = base.load_json(OUT / "hec_twin_mucum_forward_5d_latest.json") or {}
    corridor_nodes = build_corridor_model_nodes(feed, forward_pkg)

    if spatial_ready:
        ss = spatial_hec.get("series") or {}
        sm = spatial_hec.get("summary") or {}
        rain = spatial_hec.get("rain") or {}
        zones = rain.get("zones") or {}
        feed["rainfall_runoff_result"] = {
            "available": bool(spatial_hec.get("times_utc") and ss.get("q_mucum_m3s")),
            "generated_at_utc": spatial_hec.get("generated_at_utc"),
            "status": "hec_hms_4_13_spatial_ifs_ready",
            "label_pt": "HEC-HMS 4.13 · chuva IFS espacial",
            "warning_pt": spatial_hec.get("warning_pt"),
            "forcing_spatial": True,
            "engine": "HEC-HMS 4.13",
            "mode": spatial_hec.get("mode"),
            "time_utc": spatial_hec.get("times_utc") or [],
            "q_mucum_m3s": ss.get("q_mucum_m3s") or [],
            "q_antas_m3s": [],
            "q_stz_diagnostic_m3s": [],
            "n_mucum_anchored_cm": ss.get("n_mucum_anchored_cm") or [],
            "delta_n_from_now_cm": ss.get("delta_n_from_now_cm") or [],
            "current_observed_stage_cm": sm.get("level_now_observed_cm"),
            "current_observed_q_rating_m3s": sm.get("q_now_observed_rating_m3s"),
            "primary": {
                "event_id": "HEC-HMS-SPATIAL",
                "rise_cm": sm.get("rise_from_now_cm"),
                "peak_time_utc": sm.get("peak_time_utc"),
                "peak_anchored_cm": sm.get("peak_level_anchored_cm"),
                "peak_q_m3s": sm.get("peak_q_m3s"),
            },
            "horizon_hours": len(spatial_hec.get("times_utc") or []),
            "forcing_rain_mm": rain.get("basin_equivalent_forecast_mm_for_audit"),
            "spatial_cells": rain.get("spatial_cells"),
            "rain_zones": {
                sid: {
                    "name": z.get("name"),
                    "total_mm": z.get("total_mm"),
                    "n_cells_touching": z.get("n_cells_touching"),
                    "coverage_ratio": z.get("coverage_ratio"),
                }
                for sid, z in zones.items()
            },
            "initial_state": spatial_hec.get("initial_state"),
            "parameter_source": spatial_hec.get("parameter_source"),
            "nodes_model": spatial_hec.get("nodes") or {},
            "corridor_nodes": corridor_nodes,
            "plain_pt": (
                f"HEC-HMS 4.13 executado com {rain.get('spatial_cells') or '?'} células IFS "
                f"espacializadas. Q inicial {sm.get('q_model_initial_m3s')} m³/s; "
                f"pico {sm.get('peak_q_m3s')} m³/s; ΔN {sm.get('rise_from_now_cm')} cm."
            ),
            "q_note_pt": (
                "Q(t) é a saída do HEC-HMS 4.13. O estado inicial foi reconciliado com a "
                "vazão derivada da curva-chave de Muçum; a chuva é espacializada por interseção "
                "das células IFS com as zonas do piloto HEC."
            ),
            "artifact_json": "hec_hms_spatial_forecast_mucum_latest.json",
            "series_csv": "hec_hms_spatial_forecast_mucum/primary_series.csv",
        }
    else:
        s = forward_pkg.get("series_primary") or {}
        qs = forward_pkg.get("quanto_sobe") or {}
        forcing_used = forward_pkg.get("forcing") or {}
        is_spatial = bool(forcing_used.get("spatial_field_full")) and not bool(forcing_used.get("point_proxy_not_areal_mask", True))
        feed["rainfall_runoff_result"] = {
            "available": bool(s.get("time_utc") and s.get("q_mucum_m3s")),
            "generated_at_utc": forward_pkg.get("generated_at_utc"),
            "status": "spatial_ifs_rainfall_runoff_ready" if is_spatial else "experimental_legacy_point_proxy",
            "label_pt": "Resultado chuva–vazão com IFS espacial" if is_spatial else "Resultado do modelo chuva–vazão disponível",
            "warning_pt": (
                "Esta rodada usa o campo IFS espacial completo, agregado separadamente dentro de cada "
                "zona hidrológica do gêmeo. É um resultado de pesquisa do gêmeo HEC, não alerta oficial."
                if is_spatial else
                "Esta série é a saída executável do gêmeo HEC atual. A chuva que gerou esta saída "
                "ainda é a forçante proxy antiga, não o campo IFS espacial completo."
            ),
            "forcing_spatial": is_spatial,
            "forcing": forcing_used,
            "time_utc": s.get("time_utc") or [],
            "q_mucum_m3s": s.get("q_mucum_m3s") or [],
            "q_antas_m3s": s.get("q_antas_m3s") or [],
            "q_stz_diagnostic_m3s": s.get("q_stz_diagnostic_m3s") or [],
            "n_mucum_anchored_cm": s.get("n_mucum_anchored_cm") or [],
            "delta_n_from_now_cm": s.get("delta_n_from_now_cm") or [],
            "current_observed_stage_cm": ((qs.get("level_now") or {}).get("stage_cm")),
            "current_observed_q_rating_m3s": ((qs.get("q_now_from_rating_m3s") or {}).get("q_m3s")),
            "primary": qs.get("primary") or {},
            "ensemble_rise_cm": qs.get("ensemble_rise_cm") or {},
            "forcing_rain_mm": qs.get("rain_forecast_mm_area_weighted"),
            "horizon_hours": qs.get("horizon_hours"),
            "plain_pt": qs.get("plain_pt"),
            "q_note_pt": "Fallback do gêmeo de pesquisa; não é o HEC-HMS espacial preferencial.",
            "corridor_nodes": corridor_nodes,
        }

    discipline = dict(feed.get("discipline") or {})
    discipline.update({
        "spatial_ifs_full_field_available": bool(sr.get("available")),
        "legacy_forward_uses_point_proxy": True,
        "legacy_forward_not_valid_as_full_basin_spatial_forecast": True,
        "do_not_publish_legacy_delta_n_as_current_forecast": True,
    })
    feed["discipline"] = discipline

    # Preserve the previous HEC-twin result for audit, but never present it as
    # the current spatial forecast after the full-field rainfall audit.
    legacy_headline = dict(feed.get("headline") or {})
    feed["legacy_headline"] = legacy_headline

    fwd = ((feed.get("products") or {}).get("forward_5d") or {})
    level_now = fwd.get("level_now") or {}
    products = dict(feed.get("products") or {})
    fwd = dict(fwd)
    fwd.update({
        "valid_for_current_spatial_forecast": False,
        "input_policy": "legacy_point_proxy",
        "blocking_reason_pt": (
            "O gêmeo HEC atual ainda usa proxies pontuais de chuva. O resultado de ΔN é mantido "
            "somente para auditoria e não é apresentado como previsão espacial da bacia."
        ),
    })
    products["forward_5d"] = fwd
    feed["products"] = products

    if spatial_ready:
        hsm = spatial_hec.get("summary") or {}
        feed["headline"] = {
            "source": "hec_hms_4_13_spatial_ifs",
            "question_pt": "O que toda a chuva prevista na bacia contribuinte produz no modelo chuva–vazão de Muçum?",
            "plain_pt": (
                f"HEC-HMS 4.13 executado com o campo IFS espacial. "
                f"Q atual modelada {hsm.get('q_model_initial_m3s')} m³/s, "
                f"pico {hsm.get('peak_q_m3s')} m³/s e ΔN {hsm.get('rise_from_now_cm')} cm."
            ),
            "primary": feed["rainfall_runoff_result"].get("primary"),
            "rain_mm_area_weighted": (spatial_hec.get("rain") or {}).get("basin_equivalent_forecast_mm_for_audit"),
            "validation_ref": "hec_hms_spatial_forecast_mucum_latest.json",
        }
    else:
        feed["headline"] = {
            "source": "spatial_ifs_full_field",
            "question_pt": "O que toda a chuva prevista na bacia contribuinte pode produzir em Muçum?",
            "plain_pt": (
                "A chuva espacial IFS está atualizada, mas o HEC-HMS espacial ainda não publicou "
                "uma execução válida neste ciclo."
            ),
            "primary": None,
            "ensemble_rise_cm": None,
            "rain_mm_area_weighted": None,
            "verification_plain_pt": None,
            "scorecard": {},
            "validation_ref": "products.live_eval",
        }

    summary = dict(feed.get("summary") or {})
    summary.update({
        "peak_n_cm": None,
        "peak_delta_n_cm": None,
        "peak_when_utc": None,
        "n_plus_24h_cm": None,
        "delta_plus_24h_cm": None,
        "when_plus_24h_utc": None,
        "hydrology_status": "blocked_until_spatial_rain_is_integrated",
        "observed_stage_cm": level_now.get("stage_cm"),
        "observed_at_utc": level_now.get("observed_at_utc"),
        "observed_source": level_now.get("source"),
    })
    if spatial_ready:
        hsm = spatial_hec.get("summary") or {}
        summary.update({
            "peak_n_cm": hsm.get("peak_level_anchored_cm"),
            "peak_delta_n_cm": hsm.get("rise_from_now_cm"),
            "peak_when_utc": hsm.get("peak_time_utc"),
            "hydrology_status": "hec_hms_4_13_spatial_ifs_ready",
            "observed_stage_cm": hsm.get("level_now_observed_cm"),
        })
    feed["summary"] = summary

    freshness = dict(feed.get("freshness") or {})
    freshness["preferred_source"] = "spatial_ifs_full_field"
    freshness["note_pt"] = (
        "Chuva espacial atualizada. O ΔN do forward legado não é promovido como previsão atual "
        "porque a entrada hidrológica ainda usa proxies pontuais."
    )
    feed["freshness"] = freshness

    auto = dict(feed.get("automation") or {})
    auto["steps_pt"] = [
        "Atualiza o campo ECMWF/IFS 0,25° em todas as células que interceptam a bacia até Muçum",
        "Mantém o gêmeo HEC legado separado para auditoria enquanto ele ainda usa chuva proxy",
        "Reconstrói a plataforma com chuva espacial, telemetria, inventário e calibração",
        "Publica no main e atualiza o GitHub Pages",
    ]
    feed["automation"] = auto

    # Keep old event trace for audit panels only; label it explicitly.
    trace = dict(feed.get("event_trace") or {})
    trace["legacy_point_proxy"] = True
    trace["note"] = (
        "Traço legado do gêmeo HEC com chuva proxy. Exibido somente como diagnóstico/auditoria; "
        "não é a previsão espacial atual."
    )
    feed["event_trace"] = trace

    return feed


def main() -> None:
    feed = build_feed_v3()
    base.FEED_JSON.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    base.FEED_HTML.write_text(ui.render_platform_html(feed), encoding="utf-8")
    base.ROOT_HTML.write_text(base.render_root_entry(), encoding="utf-8")
    print(f"wrote {base.FEED_JSON.relative_to(ROOT)}")
    print(f"wrote {base.FEED_HTML.relative_to(ROOT)}")
    print(f"spatial rain available={bool((feed.get('spatial_rain') or {}).get('available'))}")
    print(f"hydrology_status={(feed.get('summary') or {}).get('hydrology_status')}")


if __name__ == "__main__":
    main()
