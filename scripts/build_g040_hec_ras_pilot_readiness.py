#!/usr/bin/env python3
"""Build source-backed HEC-RAS pilot readiness for Santa Tereza and Muçum.

This inventory distinguishes terrain/flood-reference assets from an actual
hydrodynamic model. HAND products are validation/context inputs only; they are
never presented as HEC-RAS results.

Research only.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STACK=ROOT/"assets/data/g040_hydro_stack"
ST=ROOT/"assets/data/santa_tereza_inundacao"
MU=ROOT/"assets/data/mucum_inundacao"
SRC=STACK/"project_source_inventory_latest.json"
MARKS=ROOT/"assets/data/research_mucum_flood_marks_latest.json"
OUT=STACK/"hec_ras_pilot_readiness_latest.json"

def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

def exists(rel):
    return (ROOT/rel).exists()

def main():
    st_diag=load(ST/"hand_lidar_5m_diagnostic.json")
    st_readme=(ST/"README_santa_tereza_inundacao.md").read_text(encoding="utf-8") if (ST/"README_santa_tereza_inundacao.md").exists() else ""
    mu_meta=load(MU/"mdt/altitude_terreno_10m.json")
    marks=load(MARKS)
    sources=load(SRC)
    srcs={x.get("id"):x for x in sources.get("sources") or []}

    st_assets={
        "hand_diagnostic":"assets/data/santa_tereza_inundacao/hand_lidar_5m_diagnostic.json",
        "contours":"assets/data/santa_tereza_inundacao/contornos_mancha.json",
        "drone_dem_1m":"assets/data/santa_tereza_inundacao/mdt/mdt_santa_tereza_drone_1m.tif",
        "anadem_30m":"assets/data/santa_tereza_inundacao/mdt/mdt_santa_tereza_anadem_30m.tif",
    }
    mu_assets={
        "contours":"assets/data/mucum_inundacao/contornos_mancha.json",
        "drone_dem_1m":"assets/data/mucum_inundacao/mdt/mdt_mucum_drone_1m.tif",
        "anadem_30m":"assets/data/mucum_inundacao/mdt/mdt_mucum_anadem_30m.tif",
        "flood_marks":"assets/data/research_mucum_flood_marks_latest.json",
    }

    st_current_lidar={
        "diagnostic_status":st_diag.get("status"),
        "source_resolution_m":st_diag.get("resolucao_fonte_m"),
        "payload_resolution_m":st_diag.get("resolucao_payload_aprox_m"),
        "crs":st_diag.get("crs"),
        "vertical_datum_known":False,
        "same_source_current_hand_note":"current HAND diagnostic references local raw LiDAR/FILL/FLOWACC/FLOWDIR; repo drone+ANADEM legacy layers are not substitutes for that source",
        "cartographic_validation_required":True,
    }
    mu_flood_marks={
        "status":marks.get("status"),
        "event":marks.get("event_label"),
        "count":marks.get("feature_count"),
        "marks_with_elevation":sum(x.get("elevation_m") is not None for x in marks.get("marks") or []),
        "promotion_allowed":bool(marks.get("training_or_promotion_allowed")),
    }

    bathy=[srcs.get("bathymetry_dnit_2024"),srcs.get("bathymetry_dnit_2025")]
    bathy=[x for x in bathy if x]

    pilots=[
        {
            "name":"Santa Tereza",
            "priority":1,
            "terrain_assets":{k:{"path":v,"exists":exists(v)} for k,v in st_assets.items()},
            "terrain_assessment":st_current_lidar,
            "validation_assets":{
                "existing_hand_contours":exists(st_assets["contours"]),
                "field_or_flood_marks_in_this_inventory":False,
            },
            "bathymetry_candidates":bathy,
            "gates":{
                "horizontal_crs_identified":bool(st_diag.get("crs")),
                "current_raw_lidar_materialized_for_ras":False,
                "vertical_datum_reconciled":False,
                "channel_bathymetry_audited":False,
                "bridges_structures_audited":False,
                "upstream_hydrograph_validated":False,
                "downstream_boundary_validated":False,
            },
            "notes":[
                "HAND 5 m is a terrain-connectivity research product, not a hydrodynamic solution.",
                "Current HAND uses raw LiDAR + D8 routing; legacy drone+ANADEM refined mosaic is explicitly not spatially compatible with the current HAND.",
                "Gauge-to-terrain vertical offset of 1.60 m is a current research spatialization rule and must not be assumed to be a HEC-RAS vertical datum transformation.",
            ],
        },
        {
            "name":"Muçum",
            "priority":2,
            "terrain_assets":{k:{"path":v,"exists":exists(v)} for k,v in mu_assets.items()},
            "terrain_assessment":{
                "web_terrain_source":mu_meta.get("fonte"),
                "web_grid_resolution_m":mu_meta.get("resolucao_aproximada_m"),
                "web_grid_crs":mu_meta.get("crs"),
                "drone_dem_1m_present":exists(mu_assets["drone_dem_1m"]),
                "anadem_30m_present":exists(mu_assets["anadem_30m"]),
                "vertical_datum_known":False,
            },
            "validation_assets":{
                "existing_hand_contours":exists(mu_assets["contours"]),
                "flood_marks":mu_flood_marks,
            },
            "bathymetry_candidates":bathy,
            "gates":{
                "horizontal_crs_identified":bool(mu_meta.get("crs")),
                "terrain_source_materialized":exists(mu_assets["drone_dem_1m"]),
                "vertical_datum_reconciled":False,
                "channel_bathymetry_audited":False,
                "bridges_structures_audited":False,
                "upstream_hydrograph_validated":False,
                "downstream_boundary_validated":False,
                "independent_flood_mark_reference_available":int(marks.get("feature_count") or 0)>0,
            },
            "notes":[
                "15 May-2024 SGB flood-mark records are available as research-only reference; most carry elevations.",
                "HAND expansion is not evidence that station stage reached the corresponding HAND value.",
                "Station gauge zero, terrain datum and bathymetry datum must be reconciled before depth validation.",
            ],
        },
    ]

    payload={
        "schema_version":"g040_hec_ras_pilot_readiness_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "research_only":True,
        "status":"PILOT_SOURCE_AUDIT_READY_GEOMETRY_AND_DATUM_BLOCKED",
        "pilots":pilots,
        "equation_protocol":{
            "baseline":"Diffusion Wave",
            "comparison":["SWE-ELM","SWE-EM where supported/appropriate"],
            "selection":"validation against level/arrival/extents/depth marks, not computational convenience",
        },
        "mandatory_before_compute":[
            "materialize and audit actual terrain used by each pilot",
            "reconcile vertical datums and station gauge zero",
            "audit channel bathymetry and terrain-bathymetry seam",
            "inventory bridges/culverts/structures",
            "define upstream hydrographs and downstream/backwater boundaries",
            "define Manning provenance and sensitivity ranges",
        ],
        "promotion_allowed":False,
    }
    STACK.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":payload["status"],
        "pilots":[{"name":p["name"],"gates":p["gates"]} for p in pilots],
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
