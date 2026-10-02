#!/usr/bin/env python3
"""Prepare auditable terrain cross-sections for the Santa Tereza -> Muçum HEC-RAS pilot.

This script does NOT claim a compute-ready HEC-RAS model. It:
- places S01-S09 on the audited BHO6 river network;
- extracts terrain-only cross-section profiles from the best available MDT;
- preserves gaps instead of inventing channel bathymetry;
- exports a diagnostic Santa Tereza hydrograph candidate from the current HEC twin;
- writes explicit gates for vertical datum, bathymetry, structures and hydraulic validation.

Research only. No official alert use.
"""

from __future__ import annotations

import csv
import json
import math
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.coords import BoundingBox
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.ops import nearest_points, transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
NETWORK_DIR = ROOT / "assets/data/hec_hms_integrated_taquari_antas"
NETWORK_AUDIT = NETWORK_DIR / "network_audit_latest.json"
NETWORK_GEOJSON = NETWORK_DIR / "bho6_taquari_antas_network.geojson"
FORWARD = ROOT / "assets/data/estudo_bacia_taquari_antas/hec_twin_mucum_forward_5d_latest.json"
CONFLUENCES = ROOT / "assets/data/estudo_bacia_taquari_antas/subbacias_e_fozes_latest.json"
SOURCE_INVENTORY = ROOT / "assets/data/g040_hydro_stack/project_source_inventory_latest.json"
OUT = ROOT / "assets/data/g040_hydro_stack/mucum_ras_prep"
SGB_LST = OUT / "mucum_sgb_lst_evidence_latest.json"

WGS84 = "EPSG:4326"
UTM22S = "EPSG:31982"
TO_UTM = Transformer.from_crs(WGS84, UTM22S, always_xy=True).transform
TO_WGS = Transformer.from_crs(UTM22S, WGS84, always_xy=True).transform

STATIONS = {
    "86472000": {"name": "Linha José Júlio", "lon": -51.6997, "lat": -29.0978},
    "86472600": {"name": "Santa Tereza", "lon": -51.7322, "lat": -29.1781},
    "86510000": {"name": "Muçum", "lon": -51.8686, "lat": -29.1672},
}

TERRAIN = [
    {
        "id": "mucum_drone_1m",
        "path": ROOT / "assets/data/mucum_inundacao/mdt/mdt_mucum_drone_1m.tif",
        "nominal_resolution_m": 1.0,
        "role": "high_resolution_terrain_surface",
    },
    {
        "id": "santa_tereza_drone_1m",
        "path": ROOT / "assets/data/santa_tereza_inundacao/mdt/mdt_santa_tereza_drone_1m.tif",
        "nominal_resolution_m": 1.0,
        "role": "high_resolution_terrain_surface",
    },
    {
        "id": "mucum_anadem_30m",
        "path": ROOT / "assets/data/mucum_inundacao/mdt/mdt_mucum_anadem_30m.tif",
        "nominal_resolution_m": 30.0,
        "role": "regional_terrain_surface",
    },
    {
        "id": "santa_tereza_anadem_30m",
        "path": ROOT / "assets/data/santa_tereza_inundacao/mdt/mdt_santa_tereza_anadem_30m.tif",
        "nominal_resolution_m": 30.0,
        "role": "regional_terrain_surface",
    },
]

HALF_WIDTH_M = 1000.0
SAMPLE_STEP_M = 5.0
TANGENT_HALF_WINDOW_M = 30.0


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def norm_text(value) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def longest_line(geom):
    if geom.geom_type == "LineString":
        return geom
    if geom.geom_type == "MultiLineString":
        return max(geom.geoms, key=lambda g: g.length)
    if geom.geom_type == "GeometryCollection":
        lines = [g for g in geom.geoms if g.geom_type in ("LineString", "MultiLineString")]
        if lines:
            expanded = []
            for g in lines:
                expanded.extend(list(g.geoms) if g.geom_type == "MultiLineString" else [g])
            return max(expanded, key=lambda g: g.length)
    raise ValueError(f"unsupported line geometry: {geom.geom_type}")


def intish(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def feature_ids(props: dict) -> set[int]:
    ids = set()
    for key, value in props.items():
        if key.lower() in {"fid", "cotrecho", "objectid", "objectid_1", "id"}:
            v = intish(value)
            if v is not None:
                ids.add(v)
    return ids


def load_network():
    audit = load_json(NETWORK_AUDIT)
    geo = load_json(NETWORK_GEOJSON)
    features = geo.get("features") or []

    idmap = {}
    river_named = []
    for feat in features:
        try:
            geom_wgs = longest_line(shape(feat["geometry"]))
        except Exception:
            continue
        geom_utm = transform(TO_UTM, geom_wgs)
        props = feat.get("properties") or {}
        for sid in feature_ids(props):
            idmap.setdefault(sid, geom_utm)
        txt = " ".join(norm_text(v) for v in props.values())
        river_named.append((txt, geom_utm, props))

    return audit, idmap, river_named


def route_from_ids(ids: list[int], idmap: dict[int, LineString], start_point: Point) -> LineString:
    missing = [sid for sid in ids if sid not in idmap]
    if missing:
        raise RuntimeError(f"BHO6 route segments missing: {missing[:12]}")

    coords = []
    previous = start_point
    for i, sid in enumerate(ids):
        line = idmap[sid]
        c = list(line.coords)
        d0 = previous.distance(Point(c[0]))
        d1 = previous.distance(Point(c[-1]))
        if d1 < d0:
            c.reverse()
        if not coords:
            coords.extend(c)
        else:
            # Do not synthesize a river segment. Join only the segment endpoints
            # already supplied by BHO6; the straight connector is retained only
            # when tiny topology precision gaps exist.
            gap = Point(coords[-1]).distance(Point(c[0]))
            if gap > 250:
                raise RuntimeError(f"BHO6 route discontinuity {gap:.1f} m at segment {sid}")
            coords.extend(c[1:] if gap < 5 else c)
        previous = Point(coords[-1])

    return LineString(coords)


def station_point(code: str) -> Point:
    s = STATIONS[code]
    return transform(TO_UTM, Point(s["lon"], s["lat"]))


def point_on_route(route: LineString, point: Point) -> tuple[Point, float]:
    ch = route.project(point)
    return route.interpolate(ch), ch


def xs_line(route: LineString, chainage: float, half_width: float = HALF_WIDTH_M) -> LineString:
    p = route.interpolate(chainage)
    pa = route.interpolate(max(0.0, chainage - TANGENT_HALF_WINDOW_M))
    pb = route.interpolate(min(route.length, chainage + TANGENT_HALF_WINDOW_M))
    dx, dy = pb.x - pa.x, pb.y - pa.y
    mag = math.hypot(dx, dy)
    if mag <= 1e-9:
        raise RuntimeError("cannot derive cross-section normal")
    nx, ny = -dy / mag, dx / mag
    return LineString([
        (p.x - nx * half_width, p.y - ny * half_width),
        (p.x + nx * half_width, p.y + ny * half_width),
    ])


def raster_footprint_utm(path: Path):
    with rasterio.open(path) as ds:
        b = ds.bounds
        poly = box(b.left, b.bottom, b.right, b.top)
        if ds.crs and str(ds.crs) != UTM22S:
            tf = Transformer.from_crs(ds.crs, UTM22S, always_xy=True).transform
            poly = transform(tf, poly)
        return poly


def first_inside_chainage(route: LineString, poly, start_fraction: float = 0.45):
    ds = np.linspace(route.length * start_fraction, route.length, 1200)
    inside = [float(d) for d in ds if poly.covers(route.interpolate(float(d)))]
    return min(inside) if inside else None


def locate_sections(audit, route1, route2, river_named):
    _, s01 = point_on_route(route1, station_point("86472000"))
    _, s06 = point_on_route(route2, station_point("86472600"))
    _, s09 = point_on_route(route2, station_point("86510000"))

    # Use the already audited BHO6 mainstem-join coordinate for Carreiro.
    # Do not infer the confluence from river-name proximity: similarly named
    # features elsewhere in the basin can be tens of kilometres away.
    confluence_source = "fallback"
    confluence_distance_m = None
    carreiro_feature_count = 0
    if CONFLUENCES.exists():
        cj = load_json(CONFLUENCES)
        matches = [
            x for x in (cj.get("fozes_principais") or [])
            if str(x.get("family_code") or "") == "7866"
            or "carreiro" in norm_text(x.get("label"))
        ]
        if matches and matches[0].get("lonlat"):
            lon, lat = matches[0]["lonlat"]
            cp = transform(TO_UTM, Point(float(lon), float(lat)))
            on_main, _ = nearest_points(route1, cp)
            confluence = route1.project(on_main)
            confluence_distance_m = float(on_main.distance(cp))
            confluence_source = "subbacias_e_fozes_latest.json:BHO6_7866"
            carreiro_feature_count = 1
        else:
            confluence = route1.length * 0.65
    else:
        confluence = route1.length * 0.65

    s08 = None
    mucum_drone = TERRAIN[0]["path"]
    if mucum_drone.exists():
        try:
            s08 = first_inside_chainage(route2, raster_footprint_utm(mucum_drone))
        except Exception:
            s08 = None
    if s08 is None:
        s08 = route2.length * 0.85

    plan = [
        ("S01", route1, s01, "controle montante Linha José Júlio"),
        ("S02", route1, route1.length * 0.25, "geometria representativa no primeiro quarto do reach"),
        ("S03", route1, max(0.0, confluence - 200.0), "200 m a montante da confluência do Carreiro"),
        ("S04", route1, min(route1.length, confluence + 200.0), "200 m a jusante da confluência do Carreiro"),
        ("S05", route1, route1.length * 0.90, "aproximação a Santa Tereza"),
        ("S06", route2, s06, "controle Santa Tereza"),
        ("S07", route2, route2.length * 0.50, "meio do reach Santa Tereza-Muçum"),
        ("S08", route2, s08, "entrada no domínio MDT de alta resolução de Muçum"),
        ("S09", route2, s09, "controle Muçum"),
    ]
    return plan, {
        "carreiro_named_features": carreiro_feature_count,
        "carreiro_confluence_source": confluence_source,
        "carreiro_confluence_chainage_m": round(float(confluence), 2),
        "carreiro_to_main_nearest_distance_m": None if confluence_distance_m is None else round(float(confluence_distance_m), 2),
        "s08_rule": "first centerline point inside Muçum drone-MDT footprint; fallback 85% of reach if footprint unavailable",
    }


def sample_raster(xs: LineString, terrain: dict):
    path = terrain["path"]
    if not path.exists():
        return None

    distances = np.arange(0.0, xs.length + SAMPLE_STEP_M * 0.5, SAMPLE_STEP_M)
    points = [xs.interpolate(float(d)) for d in distances]
    center = xs.interpolate(xs.length / 2.0)

    with rasterio.open(path) as ds:
        if not ds.crs:
            return None
        from_utm = Transformer.from_crs(UTM22S, ds.crs, always_xy=True)
        cx, cy = from_utm.transform(center.x, center.y)
        b: BoundingBox = ds.bounds
        center_in = b.left <= cx <= b.right and b.bottom <= cy <= b.top
        if not center_in:
            return None

        coords = [from_utm.transform(p.x, p.y) for p in points]
        values = []
        nodata = ds.nodata
        for arr in ds.sample(coords, indexes=1, masked=False):
            v = float(arr[0])
            ok = math.isfinite(v) and (nodata is None or abs(v - float(nodata)) > 1e-9)
            values.append(v if ok else math.nan)

        valid = np.isfinite(values)
        valid_fraction = float(valid.mean()) if len(valid) else 0.0
        if valid_fraction <= 0.02:
            return None

        return {
            "terrain": terrain,
            "distances": distances,
            "points": points,
            "values": np.asarray(values, dtype=float),
            "valid_fraction": valid_fraction,
            "raster_crs": str(ds.crs),
            "raster_nodata": nodata,
        }


def best_profile(xs: LineString):
    for terrain in TERRAIN:
        try:
            result = sample_raster(xs, terrain)
        except Exception:
            result = None
        if result is not None:
            return result
    return None


def recursive_find_ids(obj, wanted: set[str]):
    found = []
    if isinstance(obj, dict):
        if str(obj.get("id") or "") in wanted:
            found.append(obj)
        for v in obj.values():
            found.extend(recursive_find_ids(v, wanted))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(recursive_find_ids(v, wanted))
    return found


def write_hydrograph_candidate():
    if not FORWARD.exists():
        return {"available": False, "reason": "forward artifact missing"}

    data = load_json(FORWARD)
    s = data.get("series_primary") or {}
    times = s.get("time_utc") or []
    q_stz = s.get("q_stz_diagnostic_m3s") or []
    q_mucum = s.get("q_mucum_m3s") or []
    n_mucum = s.get("n_mucum_anchored_cm") or []

    if not times or len(q_stz) != len(times):
        return {"available": False, "reason": "Santa Tereza diagnostic hydrograph missing"}

    path = OUT / "stz_to_mucum_hydrograph_candidate.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time_utc", "q_stz_diagnostic_m3s", "q_mucum_reference_m3s", "n_mucum_reference_cm"])
        for i, t in enumerate(times):
            w.writerow([
                t,
                q_stz[i],
                q_mucum[i] if i < len(q_mucum) else "",
                n_mucum[i] if i < len(n_mucum) else "",
            ])

    return {
        "available": True,
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "status": "DIAGNOSTIC_ONLY_NOT_HYDRAULIC_BOUNDARY_VALIDATED",
        "source_generated_at_utc": data.get("generated_at_utc"),
        "forcing": data.get("forcing"),
        "wetness": ((data.get("param_selection") or {}).get("wetness")),
        "santa_tereza_source_status": ((data.get("santa_tereza") or {}).get("q_status")),
        "note": "Use only as candidate upstream hydrograph for hydraulic sensitivity; Santa Tereza Q is not independently calibrated.",
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    audit, idmap, river_named = load_network()
    p1_ids = audit["topology"]["paths"]["86472000_to_86472600"]["segments"]
    p2_ids = audit["topology"]["paths"]["86472600_to_86510000"]["segments"]

    route1 = route_from_ids(p1_ids, idmap, station_point("86472000"))
    route2 = route_from_ids(p2_ids, idmap, station_point("86472600"))
    plan, placement_audit = locate_sections(audit, route1, route2, river_named)

    profile_rows = []
    section_features = []
    summaries = []

    for sid, route, chainage, purpose in plan:
        center = route.interpolate(chainage)
        xs = xs_line(route, chainage)
        result = best_profile(xs)

        terrain_id = None
        terrain_res = None
        valid_fraction = 0.0
        elevations = np.array([], dtype=float)
        source_role = None

        if result is not None:
            terrain_id = result["terrain"]["id"]
            terrain_res = result["terrain"]["nominal_resolution_m"]
            source_role = result["terrain"]["role"]
            valid_fraction = result["valid_fraction"]
            elevations = result["values"]

            for d, p, z in zip(result["distances"], result["points"], result["values"]):
                pw = transform(TO_WGS, p)
                profile_rows.append({
                    "section_id": sid,
                    "offset_from_left_m": round(float(d), 3),
                    "offset_from_center_m": round(float(d - xs.length / 2.0), 3),
                    "easting_utm22s": round(float(p.x), 3),
                    "northing_utm22s": round(float(p.y), 3),
                    "longitude": round(float(pw.x), 8),
                    "latitude": round(float(pw.y), 8),
                    "terrain_elevation_m": "" if not math.isfinite(float(z)) else round(float(z), 3),
                    "terrain_source": terrain_id,
                    "terrain_only_not_bathymetry": True,
                })

        cw = transform(TO_WGS, center)
        near_center_valid = None
        if result is not None and len(elevations):
            offsets = result["distances"] - xs.length / 2.0
            mask = np.abs(offsets) <= 100.0
            near_center_valid = float(np.isfinite(elevations[mask]).mean()) if mask.any() else None

        sgb_lst = load_json(SGB_LST) if (sid == "S09" and SGB_LST.exists()) else None
        summary = {
            "section_id": sid,
            "purpose": purpose,
            "center_lon": round(float(cw.x), 8),
            "center_lat": round(float(cw.y), 8),
            "route_chainage_m": round(float(chainage), 2),
            "cross_section_width_m": round(float(xs.length), 2),
            "terrain_status": "TERRAIN_PROFILE_AVAILABLE" if result is not None else "NO_TERRAIN_COVERAGE",
            "terrain_source": terrain_id,
            "terrain_role": source_role,
            "nominal_resolution_m": terrain_res,
            "valid_profile_fraction": round(valid_fraction, 4),
            "valid_fraction_within_100m_of_center": None if near_center_valid is None else round(near_center_valid, 4),
            "terrain_min_m": None if not np.isfinite(elevations).any() else round(float(np.nanmin(elevations)), 3),
            "terrain_max_m": None if not np.isfinite(elevations).any() else round(float(np.nanmax(elevations)), 3),
            "measured_channel_evidence": bool(sgb_lst),
            "measured_channel_source": None if not sgb_lst else "SGB LST Muçum 2011-2023 / Figura 6",
            "measured_channel_section_offset_m": None if not sgb_lst else 70,
            "measured_bed_min_2023_gauge_cm": None if not sgb_lst else -385,
            "measured_bed_min_2020_gauge_cm": None if not sgb_lst else -533,
            "channel_bed_source": "SGB_MEASURED_LST_EVIDENCE_PROFILE_NOT_YET_DIGITIZED" if sgb_lst else "MISSING_AUDITED_BATHYMETRY",
            "hydraulic_use": "NOT_COMPUTE_READY",
        }
        summaries.append(summary)

        section_features.append({
            "type": "Feature",
            "properties": summary,
            "geometry": mapping(transform(TO_WGS, xs)),
        })

    with (OUT / "cross_section_profiles.csv").open("w", newline="", encoding="utf-8") as fh:
        fields = [
            "section_id", "offset_from_left_m", "offset_from_center_m",
            "easting_utm22s", "northing_utm22s", "longitude", "latitude",
            "terrain_elevation_m", "terrain_source", "terrain_only_not_bathymetry",
        ]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(profile_rows)

    with (OUT / "cross_section_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        fields = list(summaries[0].keys())
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(summaries)

    (OUT / "cross_sections.geojson").write_text(
        json.dumps({
            "type": "FeatureCollection",
            "name": "Santa_Tereza_Mucum_RAS_prep_cross_sections",
            "crs": {"type": "name", "properties": {"name": WGS84}},
            "features": section_features,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    hydro = write_hydrograph_candidate()

    inventory = load_json(SOURCE_INVENTORY) if SOURCE_INVENTORY.exists() else {}
    bathy = recursive_find_ids(inventory, {"bathymetry_dnit_2024", "bathymetry_dnit_2025"})
    materialized_bathy = []
    for p in ROOT.rglob("*"):
        if p.is_file() and ("batim" in norm_text(p.name) or "bathym" in norm_text(p.name)):
            if p.suffix.lower() in {".xyz", ".dwg", ".dxf", ".csv", ".txt", ".asc"}:
                materialized_bathy.append(str(p.relative_to(ROOT)).replace("\\", "/"))

    manifest = {
        "schema_version": "mucum_ras_geometry_prep_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "research_only": True,
        "official_alert": False,
        "status": "TERRAIN_SECTIONS_PREPARED_HYDRAULIC_COMPUTE_BLOCKED",
        "domain": "Santa Tereza -> Muçum",
        "network": {
            "source": str(NETWORK_GEOJSON.relative_to(ROOT)).replace("\\", "/"),
            "route_86472000_to_86472600_length_m": round(float(route1.length), 2),
            "route_86472600_to_86510000_length_m": round(float(route2.length), 2),
            "placement_audit": placement_audit,
        },
        "sections": summaries,
        "terrain_policy": {
            "priority": [x["id"] for x in TERRAIN],
            "sample_step_m": SAMPLE_STEP_M,
            "cross_section_half_width_m": HALF_WIDTH_M,
            "rule": "use one terrain source per section; never silently splice rasters with unreconciled vertical datums",
            "river_bed_rule": "terrain/photogrammetry/ANADEM is not treated as bathymetry",
        },
        "bathymetry": {
            "source_candidates": bathy,
            "materialized_geometry_files_in_repo": materialized_bathy,
            "status": "PENDING_AUDIT_AND_VERTICAL_DATUM_RECONCILIATION",
        },
        "hydrologic_coupling": hydro,
        "gates": {
            "bho6_centerline_sections": True,
            "terrain_profiles_extracted": any(x["terrain_status"] == "TERRAIN_PROFILE_AVAILABLE" for x in summaries),
            "vertical_datum_reconciled": False,
            "station_gauge_zero_reconciled_with_terrain": False,
            "channel_bathymetry_audited": bool(materialized_bathy),
            "measured_s09_cross_section_evidence_found": SGB_LST.exists(),
            "measured_s09_full_numeric_profile_recovered": False,
            "bridges_and_contractions_audited": False,
            "manning_calibrated": False,
            "santa_tereza_upstream_hydrograph_validated": False,
            "downstream_boundary_validated": False,
            "hec_ras_compute_ready": False,
        },
        "next_compute_rule": (
            "Do not run or publish a HEC-RAS level forecast until bathymetry/terrain vertical reference, "
            "channel geometry, structures, Manning and hydraulic boundaries have been reconciled. "
            "The exported Santa Tereza Q is a diagnostic sensitivity boundary only."
        ),
        "artifacts": [
            "cross_sections.geojson",
            "cross_section_profiles.csv",
            "cross_section_summary.csv",
            "stz_to_mucum_hydrograph_candidate.csv",
            "mucum_sgb_lst_evidence_latest.json",
            "mucum_hydraulic_geometry_prep_latest.json",
        ],
    }
    (OUT / "mucum_hydraulic_geometry_prep_latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps({
        "status": manifest["status"],
        "sections": len(summaries),
        "terrain_sections": sum(x["terrain_status"] == "TERRAIN_PROFILE_AVAILABLE" for x in summaries),
        "hydrograph_candidate": hydro.get("available"),
        "compute_ready": manifest["gates"]["hec_ras_compute_ready"],
        "output": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
