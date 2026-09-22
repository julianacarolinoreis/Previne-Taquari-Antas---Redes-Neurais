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


def build_feed_v3() -> dict:
    feed = base.enrich_feed(base.build_feed())
    spatial_pkg = load_spatial()
    sr = spatial_summary(spatial_pkg)
    feed["schema_version"] = "plataforma_hec_twin_mucum_v3"
    feed["status"] = "spatial_rain_ready_hydrology_integration_pending"
    feed["spatial_rain"] = sr

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

    feed["headline"] = {
        "source": "spatial_ifs_full_field",
        "question_pt": "O que toda a chuva prevista na bacia contribuinte pode produzir em Muçum?",
        "plain_pt": (
            "A chuva espacial IFS está atualizada e cobre toda a bacia contribuinte até Muçum. "
            "A previsão de nível permanece bloqueada nesta página até o modelo chuva–vazão "
            "consumir esse campo espacial, sem reduzir a bacia a proxies pontuais."
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
