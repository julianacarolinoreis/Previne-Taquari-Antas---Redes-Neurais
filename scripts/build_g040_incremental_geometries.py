#!/usr/bin/env python3
"""Build residual incremental catchment geometries for the G040 branch HEC model.

Method
------
1. Rebuild the directed BHO6 graph for cocursodag LIKE '786%'.
2. For each verified mainstem interval U -> D, compute:
      residual segments = upstream(D) - upstream(U)
                          - upstream(observed branches entering interval)
3. Validate the residual area from sum(nuareacont) against the independent
   cumulative-area budget.
4. If a LOCAL BHO6-compatible drainage-area polygon clip is available, match
   residual ottobasins by exact COBACIA and union polygons per interval.
5. Otherwise publish the closed area budget plus an explicit geometry gate.

Important
---------
BHO2017 polygons are NOT used as a fallback. Their Otto codes are not assumed
to be version-compatible with BHO6. Missing BHO6 polygons never trigger guessed
spatial matching.

Research only; not an official warning system.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/data/hec_hms_g040_full_basin"
TOPO = BASE / "whole_basin_bho6_topology_latest.json"
BUDGET = BASE / "whole_basin_incremental_area_budget_latest.json"
DEFAULT_POLYGON_CLIP = BASE / "bho6_area_drenagem_g040.geojson"
OUT = BASE / "whole_basin_incremental_geometry_latest.json"
GEO = BASE / "whole_basin_incremental_catchments.geojson"

BHO6_QUERY = (
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
BHO6_AREA_GPKG_PUBLIC = (
    "https://metadados.snirh.gov.br/files/"
    "32e309da-a8c1-443f-90ac-0cd79ce6a33d/geoft_bho_area_drenagem.gpkg"
)
FIELDS = (
    "fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,"
    "nuareamont,nuareacont,nucomptrec,dsversao"
)
PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True)


def fetch_json(url, params, timeout=90):
    r = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={"User-Agent": "PREVINE-G040-incremental-geometry/2.0"},
    )
    r.raise_for_status()
    p = r.json()
    if "error" in p:
        raise RuntimeError(json.dumps(p["error"], ensure_ascii=False))
    return p


def fetch_bho6():
    rows = []
    offset = 0
    while True:
        p = fetch_json(
            BHO6_QUERY,
            {
                "where": "cocursodag LIKE '786%'",
                "outFields": FIELDS,
                "returnGeometry": "false",
                "resultOffset": offset,
                "resultRecordCount": 2000,
                "orderByFields": "fid",
                "f": "json",
            },
        )
        page = [x["attributes"] for x in p.get("features", [])]
        rows.extend(page)
        if len(page) < 2000:
            break
        offset += len(page)
    return rows


def upstream_set(by_dest, start_fid, by_fid):
    start = by_fid[int(start_fid)]
    selected = {int(start["fid"])}
    pending = [int(start["noorigem"])]
    visited = set()
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        for s in by_dest.get(node, []):
            fid = int(s["fid"])
            if fid in selected:
                continue
            selected.add(fid)
            pending.append(int(s["noorigem"]))
    return selected


def ci(props, *names):
    low = {str(k).lower(): v for k, v in (props or {}).items()}
    for name in names:
        value = low.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def load_bho6_polygon_clip(path: Path):
    """Load a pre-clipped BHO6 drainage-area GeoJSON.

    The clip must come from the same BHO6 family/version used for the drainage
    network. Exact COBACIA matching remains mandatory.
    """
    if not path.exists():
        return {}, {
            "available": False,
            "path": str(path.relative_to(ROOT)) if path.is_absolute() and ROOT in path.parents else str(path),
            "feature_count": 0,
            "unique_cobacia_count": 0,
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    by_code = {}
    invalid = 0
    for ft in features:
        props = ft.get("properties") or {}
        code = ci(props, "cobacia")
        geom = ft.get("geometry")
        if code in (None, "") or not geom:
            invalid += 1
            continue
        by_code.setdefault(str(code), []).append(ft)

    return by_code, {
        "available": True,
        "path": str(path.relative_to(ROOT)) if path.is_absolute() and ROOT in path.parents else str(path),
        "feature_count": len(features),
        "unique_cobacia_count": len(by_code),
        "invalid_or_unusable_features": invalid,
    }


def area_km2(geom):
    return shp_transform(PROJECT.transform, geom).area / 1e6


def write_empty_geojson():
    GEO.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": "G040_residual_incremental_catchments_bho6",
                "features": [],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--polygon-clip",
        type=Path,
        default=DEFAULT_POLYGON_CLIP,
        help=(
            "Local GeoJSON clip derived from official BHO6 "
            "GEOFT_BHO_AREA_DRENAGEM.gpkg for the G040 family."
        ),
    )
    args = ap.parse_args()

    topo = json.loads(TOPO.read_text(encoding="utf-8"))
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))
    if not topo.get("topology_pass") or budget.get("status") != "AREA_BUDGET_CLOSED":
        raise RuntimeError("topology/area budget not ready")

    segs = fetch_bho6()
    by_fid = {int(x["fid"]): x for x in segs}
    by_dest = {}
    for x in segs:
        by_dest.setdefault(int(x["nodestino"]), []).append(x)

    snapped = topo["snapped_stations"]
    upstream_cache = {}

    def U(code):
        if code not in upstream_cache:
            upstream_cache[code] = upstream_set(
                by_dest, int(snapped[code]["segment"]["fid"]), by_fid
            )
        return upstream_cache[code]

    records = []
    interval_segment_sets = {}
    interval_codes = {}
    all_cobacias = set()

    for item in budget["intervals"]:
        up = item["upstream_station"]
        down = item["downstream_station"]
        residual = set(U(down)) - set(U(up))
        entering_codes = [
            x["station_code"]
            for x in item.get("entering_observed_boundaries") or []
        ]
        for code in entering_codes:
            residual -= set(U(code))

        interval_segment_sets[item["interval_id"]] = residual
        local_area = sum(
            float(by_fid[f].get("nuareacont") or 0.0) for f in residual
        )
        expected = float(item["residual_rainfall_runoff_area_km2"])
        codes = {
            str(by_fid[f].get("cobacia"))
            for f in residual
            if by_fid[f].get("cobacia") not in (None, "")
        }
        interval_codes[item["interval_id"]] = codes
        all_cobacias.update(codes)

        records.append(
            {
                "interval_id": item["interval_id"],
                "upstream_station": up,
                "downstream_station": down,
                "segment_count": len(residual),
                "bho6_local_area_sum_km2": round(local_area, 3),
                "budget_residual_area_km2": round(expected, 3),
                "area_difference_km2": round(local_area - expected, 3),
                "area_difference_pct": (
                    round(100 * (local_area - expected) / expected, 3)
                    if expected
                    else None
                ),
                "cobacia_count": len(codes),
                "entering_observed_boundaries": entering_codes,
            }
        )

    bad = [
        r
        for r in records
        if abs(r["area_difference_km2"])
        > max(2.0, 0.01 * r["budget_residual_area_km2"])
    ]
    if bad:
        raise RuntimeError(
            "BHO6 local-area difference exceeds tolerance: "
            + json.dumps(bad, ensure_ascii=False)
        )

    poly_by_cobacia, clip_meta = load_bho6_polygon_clip(args.polygon_clip)

    # If the compatible BHO6 polygon clip is absent, stop at an explicit,
    # scientifically valid gate. The hydrologic area budget remains usable,
    # but no spatial rainfall polygon is claimed.
    if not clip_meta["available"]:
        geometry_records = [
            {
                **rec,
                "polygon_source": "ANA/SNIRH BHO6 GEOFT_BHO_AREA_DRENAGEM",
                "matched_cobacia_count": 0,
                "missing_cobacia_count": rec["cobacia_count"],
                "cobacia_match_ratio": None,
                "geometry_area_km2_epsg31982": None,
                "geometry_status": "BHO6_POLYGON_CLIP_REQUIRED",
            }
            for rec in records
        ]
        payload = {
            "schema_version": "g040_whole_basin_incremental_geometry_v2",
            "generated_at_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "research_only": True,
            "status": "BHO6_POLYGON_CLIP_REQUIRED",
            "bho6_version": "BHO bho_v_06_02_04 de 2022-10-11",
            "polygon_source": {
                "provider": "ANA/SNIRH",
                "dataset": "BHO6 GEOFT_BHO_AREA_DRENAGEM",
                "official_geopackage": BHO6_AREA_GPKG_PUBLIC,
                "local_clip": clip_meta,
                "crosswalk_key": "COBACIA",
                "policy": (
                    "same-version BHO6 exact Otto code match only; "
                    "BHO2017 is not used as fallback"
                ),
            },
            "area_budget_pass": True,
            "residual_cobacia_count": len(all_cobacias),
            "intervals": geometry_records,
            "minimum_cobacia_match_ratio": None,
            "all_interval_geometries_created": False,
            "usable_for_spatial_rain_candidate": False,
            "rejected_method": (
                "BHO2017 50K exact COBACIA crosswalk; observed near-zero "
                "coverage demonstrates version incompatibility"
            ),
            "next_step": (
                "create a G040 clip from the official BHO6 "
                "geoft_bho_area_drenagem.gpkg and rerun this script"
            ),
        }
        OUT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_empty_geojson()
        print(
            json.dumps(
                {
                    "status": payload["status"],
                    "intervals": len(records),
                    "area_budget_pass": True,
                    "polygon_clip_available": False,
                    "usable": False,
                },
                ensure_ascii=False,
            )
        )
        return 0

    out_features = []
    geometry_records = []
    for rec in records:
        codes = interval_codes[rec["interval_id"]]
        matched = [
            feat
            for code in codes
            for feat in poly_by_cobacia.get(code, [])
        ]
        matched_codes = {
            str(ci(x.get("properties") or {}, "cobacia"))
            for x in matched
            if ci(x.get("properties") or {}, "cobacia") not in (None, "")
        }
        missing = sorted(codes - matched_codes)
        geoms = [shape(x["geometry"]) for x in matched if x.get("geometry")]
        union = unary_union(geoms) if geoms else None
        ga = (
            area_km2(union)
            if union is not None and not union.is_empty
            else None
        )
        coverage = len(matched_codes) / len(codes) if codes else 1.0

        row = {
            **rec,
            "polygon_source": "ANA/SNIRH BHO6 GEOFT_BHO_AREA_DRENAGEM",
            "matched_cobacia_count": len(matched_codes),
            "missing_cobacia_count": len(missing),
            "cobacia_match_ratio": round(coverage, 4),
            "geometry_area_km2_epsg31982": None if ga is None else round(ga, 3),
            "geometry_status": (
                "MATCHED" if coverage >= 0.95 else "INCOMPLETE_BHO6_COVERAGE"
            ),
            "missing_cobacias": missing[:100],
        }
        geometry_records.append(row)

        if union is not None and not union.is_empty:
            out_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(union),
                    "properties": {
                        "interval_id": rec["interval_id"],
                        "upstream_station": rec["upstream_station"],
                        "downstream_station": rec["downstream_station"],
                        "bho6_residual_area_km2": rec[
                            "budget_residual_area_km2"
                        ],
                        "geometry_area_km2": (
                            None if ga is None else round(ga, 3)
                        ),
                        "cobacia_match_ratio": round(coverage, 4),
                        "research_only": True,
                    },
                }
            )

    min_match = min(
        (x["cobacia_match_ratio"] for x in geometry_records), default=0.0
    )
    usable = min_match >= 0.95 and len(out_features) == len(records)
    payload = {
        "schema_version": "g040_whole_basin_incremental_geometry_v2",
        "generated_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "research_only": True,
        "status": (
            "GEOMETRY_CANDIDATE_READY_FOR_RAINFALL_SPATIALIZATION"
            if usable
            else "BHO6_POLYGON_COVERAGE_REVIEW"
        ),
        "bho6_version": "BHO bho_v_06_02_04 de 2022-10-11",
        "polygon_source": {
            "provider": "ANA/SNIRH",
            "dataset": "BHO6 GEOFT_BHO_AREA_DRENAGEM",
            "official_geopackage": BHO6_AREA_GPKG_PUBLIC,
            "local_clip": clip_meta,
            "crosswalk_key": "COBACIA",
            "policy": (
                "same-version BHO6 exact Otto code match only; "
                "no BHO2017 fallback and no proximity guessing"
            ),
        },
        "area_budget_pass": True,
        "residual_cobacia_count": len(all_cobacias),
        "intervals": geometry_records,
        "minimum_cobacia_match_ratio": round(min_match, 4),
        "all_interval_geometries_created": len(out_features) == len(records),
        "usable_for_spatial_rain_candidate": usable,
        "next_step": (
            "intersect the validated 600-cell observed/IFS forcing with "
            "accepted residual polygons and build the branch HEC-HMS project"
        ),
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    GEO.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": "G040_residual_incremental_catchments_bho6",
                "features": out_features,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "intervals": len(records),
                "min_match_ratio": payload["minimum_cobacia_match_ratio"],
                "geometries": len(out_features),
                "usable": payload["usable_for_spatial_rain_candidate"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
