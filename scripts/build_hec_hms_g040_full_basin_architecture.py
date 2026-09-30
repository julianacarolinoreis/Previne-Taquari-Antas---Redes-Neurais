#!/usr/bin/env python3
"""Build an auditable G040 management-layer/topology diagnostic.

Scope:
- entire Taquari-Antas basin (G040), not only the Antas->Santa Tereza->Muçum corridor;
- 32 official IEDE framing/management sub-basins grouped in 7 UGs;
- ANA BHO6 drainage family 786 used to audit coarse inter-unit connectivity;
- existing G040 rain/flow station inventories spatially assigned to the 32 management units.

IMPORTANT: the 32 polygons are NOT the HEC-HMS computational discretization.
The research target preserves the original 145 HEC sub-basins and 72 reaches.
This script is a territorial/station audit and must not be used to replace
the native 145-unit model.

Research only; not an official warning system.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer
from shapely.geometry import Point, shape, mapping
from shapely.ops import transform as shp_transform
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "assets/data/estudo_bacia_taquari_antas"
OUT = ROOT / "assets/data/hec_hms_g040_full_basin"
SUBBASINS = STUDY / "sub_bacias_q040_enquadramento.geojson"
SUMMARY = STUDY / "subbacias_e_fozes_latest.json"
FLOW = STUDY / "postos_g040.geojson"
RAIN = STUDY / "pluviometria_g040.geojson"

BHO6 = (
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
BHO_FIELDS = (
    "fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,nuareamont,"
    "nuareacont,nucomptrec,nunivotcda,nustrahler,noriocomp,noespecif,dsversao"
)
PROJ = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True)
OFFICIAL_AREA_KM2 = 26430.0


def loadj(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ci(props: dict[str, Any], *names: str) -> Any:
    lower = {str(k).lower(): v for k, v in props.items()}
    for name in names:
        if name.lower() in lower and lower[name.lower()] not in (None, ""):
            return lower[name.lower()]
    return None


def fnum(value: Any) -> float | None:
    try:
        x = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def slug(text: str) -> str:
    import unicodedata
    raw = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()
    return raw or "SEM_NOME"


def project_geom(geom):
    return shp_transform(PROJ.transform, geom)


def canonical_index() -> dict[int, dict[str, str]]:
    src = loadj(SUMMARY)
    out: dict[int, dict[str, str]] = {}
    for ug, rows in (src.get("subbacias_by_ug") or {}).items():
        for row in rows or []:
            oid = row.get("objectid")
            if oid is None:
                continue
            out[int(oid)] = {"name": str(row.get("nome_plano")), "ug": str(ug)}
    return out


def load_subbasins() -> list[dict[str, Any]]:
    canonical = canonical_index()
    raw = loadj(SUBBASINS)
    out = []
    for i, ft in enumerate(raw.get("features") or []):
        props = ft.get("properties") or {}
        oid0 = ci(props, "objectid", "objectid_1", "fid")
        oid = int(float(oid0)) if oid0 not in (None, "") else None
        can = canonical.get(oid or -1, {})
        name = can.get("name") or str(
            ci(props, "nome_plano", "nome", "sub_bacia", "subbacia", "nm_sub_bac", "nome_sub_bacia")
            or f"Sub-bacia {oid or i+1}"
        )
        ug = can.get("ug") or str(ci(props, "ug", "nome_ug", "sub_bacia_h", "unidade") or "UG não reconciliada")
        geom = shape(ft["geometry"])
        pgeom = project_geom(geom)
        out.append({
            "index": i,
            "objectid": oid,
            "name": name,
            "ug": ug,
            "slug": slug(name),
            "geometry": geom,
            "prepared": prep(geom),
            "bounds": geom.bounds,
            "area_km2": pgeom.area / 1e6,
        })
    if len(out) != 32:
        raise RuntimeError(f"esperadas 32 sub-bacias oficiais; encontradas {len(out)}")
    return out


def fetch_bho6() -> list[dict[str, Any]]:
    rows = []
    offset = 0
    with requests.Session() as s:
        s.headers.update({"User-Agent": "PREVINE-G040-full-basin-research/1.0"})
        while True:
            params = {
                "where": "cocursodag LIKE '786%'",
                "outFields": BHO_FIELDS,
                "returnGeometry": "true",
                "outSR": "4326",
                "resultOffset": offset,
                "resultRecordCount": 1500,
                "orderByFields": "fid",
                "f": "geojson",
            }
            r = s.get(BHO6, params=params, timeout=120)
            r.raise_for_status()
            payload = r.json()
            page = payload.get("features") or []
            if not page:
                break
            rows.extend(page)
            offset += len(page)
            if len(page) < 1500:
                break
    if not rows:
        raise RuntimeError("BHO6 não retornou a família 786")
    return rows


def point_in_subbasin(point: Point, subbasins: list[dict[str, Any]]) -> int | None:
    x, y = point.x, point.y
    for sb in subbasins:
        xmin, ymin, xmax, ymax = sb["bounds"]
        if xmin <= x <= xmax and ymin <= y <= ymax and sb["prepared"].covers(point):
            return sb["index"]
    return None


def assign_segment(geom, subbasins: list[dict[str, Any]]) -> int | None:
    mid = geom.interpolate(0.5, normalized=True)
    found = point_in_subbasin(mid, subbasins)
    if found is not None:
        return found
    # Boundary-crossing fallback: use the polygon containing the largest line share.
    best = None
    best_len = 0.0
    for sb in subbasins:
        if not geom.intersects(sb["geometry"]):
            continue
        inter = geom.intersection(sb["geometry"])
        length = inter.length
        if length > best_len:
            best_len = length
            best = sb["index"]
    return best


def segment_table(features: list[dict[str, Any]], subbasins: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    rows = []
    missing = 0
    for ft in features:
        p = ft.get("properties") or {}
        g = shape(ft["geometry"])
        sb = assign_segment(g, subbasins)
        if sb is None:
            missing += 1
        rows.append({
            "fid": int(p["fid"]),
            "origin": int(p["noorigem"]),
            "dest": int(p["nodestino"]),
            "course": str(p.get("cocursodag") or ""),
            "area_up_km2": fnum(p.get("nuareamont")),
            "area_local_km2": fnum(p.get("nuareacont")),
            "length_km": fnum(p.get("nucomptrec")),
            "strahler": fnum(p.get("nustrahler")),
            "river": p.get("noriocomp") or p.get("noespecif"),
            "geometry": g,
            "subbasin": sb,
        })
    return rows, missing


def infer_topology(segments: list[dict[str, Any]], subbasins: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_origin: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for seg in segments:
        by_origin[seg["origin"]].append(seg)

    crossing: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    terminal_counts: dict[int, int] = defaultdict(int)

    for seg in segments:
        a = seg["subbasin"]
        if a is None:
            continue
        nxt = by_origin.get(seg["dest"], [])
        if not nxt:
            terminal_counts[a] += 1
            continue
        for down in nxt:
            b = down["subbasin"]
            if b is None or b == a:
                continue
            rec = crossing[a].setdefault(b, {"count": 0, "max_area_up_km2": -1.0, "fids": []})
            rec["count"] += 1
            area = seg["area_up_km2"] or 0.0
            rec["max_area_up_km2"] = max(rec["max_area_up_km2"], area)
            if len(rec["fids"]) < 8:
                rec["fids"].append(seg["fid"])

    edges = []
    downstream_map: dict[int, int | None] = {}
    ambiguities = []
    for sb in subbasins:
        i = sb["index"]
        opts = crossing.get(i, {})
        if not opts:
            downstream_map[i] = None
            continue
        ranked = sorted(
            opts.items(),
            key=lambda kv: (kv[1]["max_area_up_km2"], kv[1]["count"]),
            reverse=True,
        )
        b, evidence = ranked[0]
        downstream_map[i] = b
        if len(ranked) > 1:
            ambiguities.append({
                "subbasin": sb["name"],
                "candidates": [
                    {
                        "downstream": subbasins[j]["name"],
                        "count": ev["count"],
                        "max_area_up_km2": ev["max_area_up_km2"],
                    }
                    for j, ev in ranked
                ],
            })
        edges.append({
            "upstream_index": i,
            "upstream": sb["name"],
            "downstream_index": b,
            "downstream": subbasins[b]["name"],
            "evidence_count": evidence["count"],
            "max_area_up_km2": evidence["max_area_up_km2"],
            "crossing_fids": evidence["fids"],
        })

    # Cycle audit for the chosen 32-node graph.
    cycles = []
    for start in range(len(subbasins)):
        seen = {}
        cur = start
        step = 0
        while cur is not None:
            if cur in seen:
                cycle = []
                p = cur
                while True:
                    cycle.append(subbasins[p]["name"])
                    p = downstream_map.get(p)
                    if p == cur or p is None:
                        break
                cycles.append(cycle)
                break
            seen[cur] = step
            step += 1
            cur = downstream_map.get(cur)

    unique_cycles = []
    cycle_keys = set()
    for cyc in cycles:
        key = tuple(sorted(cyc))
        if key not in cycle_keys:
            cycle_keys.add(key)
            unique_cycles.append(cyc)

    outlets = [subbasins[i]["name"] for i, d in downstream_map.items() if d is None]
    audit = {
        "edge_count": len(edges),
        "outlet_candidates": outlets,
        "terminal_segment_counts_by_subbasin": {
            subbasins[i]["name"]: c for i, c in terminal_counts.items()
        },
        "ambiguities": ambiguities,
        "cycles": unique_cycles,
        "topology_pass": len(unique_cycles) == 0 and len(outlets) == 1 and len(edges) == 31,
    }
    return edges, audit


def station_rows(path: Path, kind: str, subbasins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = loadj(path)
    out = []
    for ft in raw.get("features") or []:
        props = ft.get("properties") or {}
        geom = ft.get("geometry") or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        lon = fnum(ci(props, "lon", "longitude"))
        lat = fnum(ci(props, "lat", "latitude"))
        if (lon is None or lat is None) and isinstance(coords, list) and len(coords) >= 2:
            lon, lat = fnum(coords[0]), fnum(coords[1])
        if lon is None or lat is None:
            continue
        sb_i = point_in_subbasin(Point(lon, lat), subbasins)
        if sb_i is None:
            continue
        out.append({
            "kind": kind,
            "code": str(ci(props, "codigo", "code", "codestacao") or ""),
            "name": str(ci(props, "nome", "name") or ""),
            "network": str(ci(props, "rede", "network") or "ANA"),
            "operating": ci(props, "operando", "situacao", "operating_flag"),
            "drainage_area_km2": fnum(ci(props, "area_drenagem_km2", "area", "nuareamont")),
            "subbasin_index": sb_i,
            "subbasin": subbasins[sb_i]["name"],
            "ug": subbasins[sb_i]["ug"],
            "lon": lon,
            "lat": lat,
        })
    return out


def station_summary(stations: list[dict[str, Any]], subbasins: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for sb in subbasins:
        i = sb["index"]
        rain = [s for s in stations if s["subbasin_index"] == i and s["kind"] == "rain"]
        flow = [s for s in stations if s["subbasin_index"] == i and s["kind"] == "flow"]
        controls = sorted(
            flow,
            key=lambda s: (s["drainage_area_km2"] is not None, s["drainage_area_km2"] or -1),
            reverse=True,
        )[:5]
        out[i] = {
            "rain_station_count": len(rain),
            "flow_station_count": len(flow),
            "flow_control_candidates": [
                {
                    "code": s["code"],
                    "name": s["name"],
                    "network": s["network"],
                    "drainage_area_km2": s["drainage_area_km2"],
                }
                for s in controls
            ],
        }
    return out


def write_outputs(subbasins, edges, topology, segments, unassigned_segments, stations):
    OUT.mkdir(parents=True, exist_ok=True)
    stsum = station_summary(stations, subbasins)
    down = {e["upstream_index"]: e["downstream_index"] for e in edges}

    units = []
    geo_features = []
    for sb in subbasins:
        i = sb["index"]
        d = down.get(i)
        unit = {
            "id": f"SB_{i+1:02d}_{sb['slug']}",
            "objectid": sb["objectid"],
            "name": sb["name"],
            "ug": sb["ug"],
            "area_km2_epsg31982": round(sb["area_km2"], 3),
            "downstream_subbasin": None if d is None else subbasins[d]["name"],
            **stsum[i],
            "hec_role": "management_enquadramento_unit",
            "not_hec_computational_unit": True,
            "routing_status": "coarse_connectivity_audit_only",
        }
        units.append(unit)
        geo_features.append({
            "type": "Feature",
            "geometry": mapping(sb["geometry"]),
            "properties": {
                "id": unit["id"],
                "name": sb["name"],
                "ug": sb["ug"],
                "area_km2": unit["area_km2_epsg31982"],
                "downstream": unit["downstream_subbasin"],
                "rain_n": unit["rain_station_count"],
                "flow_n": unit["flow_station_count"],
            },
        })

    by_ug = defaultdict(lambda: {"subbasin_count": 0, "area_km2": 0.0, "rain_station_count": 0, "flow_station_count": 0})
    for u in units:
        r = by_ug[u["ug"]]
        r["subbasin_count"] += 1
        r["area_km2"] += u["area_km2_epsg31982"]
        r["rain_station_count"] += u["rain_station_count"]
        r["flow_station_count"] += u["flow_station_count"]
    by_ug = {
        k: {
            "subbasin_count": v["subbasin_count"],
            "area_km2": round(v["area_km2"], 3),
            "rain_station_count": v["rain_station_count"],
            "flow_station_count": v["flow_station_count"],
        }
        for k, v in sorted(by_ug.items())
    }

    area_sum = sum(x["area_km2_epsg31982"] for x in units)
    payload = {
        "schema_version": "hec_hms_g040_full_basin_architecture_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "topology_audit_ready" if topology["topology_pass"] else "topology_requires_review",
        "research_only": True,
        "scope": {
            "basin": "Taquari-Antas G040",
            "outlet": "Rio Taquari na confluência com o Rio Jacuí",
            "official_area_km2": OFFICIAL_AREA_KM2,
            "management_polygons": 32,
            "management_units": 7,
            "hec_target_subbasins": 145,
            "hec_target_reaches": 72,
            "important_note_2": "The 32 IEDE polygons are audit/grouping units only; they are not HEC computational sub-basins.",
            "important_note": "Muçum is an internal control point, not the basin outlet.",
        },
        "area_audit": {
            "sum_32_projected_km2_epsg31982": round(area_sum, 3),
            "difference_vs_sema_official_km2": round(area_sum - OFFICIAL_AREA_KM2, 3),
            "difference_vs_sema_official_pct": round(100.0 * (area_sum - OFFICIAL_AREA_KM2) / OFFICIAL_AREA_KM2, 3),
        },
        "bho6_audit": {
            "query": "cocursodag LIKE '786%'",
            "segment_count": len(segments),
            "segments_not_assigned_to_32_polygons": unassigned_segments,
            "source": BHO6,
        },
        "topology_audit": topology,
        "forcing_policy": {
            "observed_rain": "hourly accumulated precipitation, station QC, spatialized separately for each of the 32 sub-basins; missing never becomes zero",
            "forecast_rain": "ECMWF/IFS spatial field integrated over each sub-basin polygon",
            "station_rule": "nested hydrometric gauges are diagnostics/state constraints and are never blindly summed as independent tributaries",
        },
        "state_and_calibration_policy": {
            "initial_state": "use fresh observed non-overlapping branch controls where available; otherwise warm-up from rainfall-runoff states",
            "publish_gate": "native HEC state must pass level/flow/trend/recent-hydrograph criteria; diagnostic stage shifting cannot promote a run",
            "calibration": "multi-event and branch-wise first; only then test transferable parameter regions across G040",
        },
        "hydraulic_boundary_note": "HEC-HMS can provide basin runoff/flow hydrographs. Forecasting stage/inundation in the lower Taquari where Jacuí/Guaíba backwater matters requires a hydraulic model (e.g. HEC-RAS) downstream of the hydrologic model.",
        "units_by_ug": by_ug,
        "subbasins": units,
        "topology_edges": edges,
    }
    (OUT / "full_basin_architecture_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "full_basin_subbasins.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": geo_features}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with (OUT / "full_basin_topology_edges.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["upstream","downstream","evidence_count","max_area_up_km2"])
        w.writeheader()
        for e in edges:
            w.writerow({k: e[k] for k in w.fieldnames})

    with (OUT / "full_basin_station_matrix.csv").open("w", encoding="utf-8", newline="") as fh:
        fields = ["kind","code","name","network","operating","drainage_area_km2","subbasin","ug","lon","lat"]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for s in stations:
            w.writerow({k: s.get(k) for k in fields})

    print(json.dumps({
        "status": payload["status"],
        "area_audit": payload["area_audit"],
        "topology_audit": {
            "edge_count": topology["edge_count"],
            "outlet_candidates": topology["outlet_candidates"],
            "ambiguity_count": len(topology["ambiguities"]),
            "cycle_count": len(topology["cycles"]),
            "topology_pass": topology["topology_pass"],
        },
        "stations": {
            "rain": sum(1 for s in stations if s["kind"] == "rain"),
            "flow": sum(1 for s in stations if s["kind"] == "flow"),
        },
    }, ensure_ascii=False))


def main() -> int:
    subbasins = load_subbasins()
    bho_features = fetch_bho6()
    segments, unassigned = segment_table(bho_features, subbasins)
    edges, topology = infer_topology(segments, subbasins)
    stations = station_rows(RAIN, "rain", subbasins) + station_rows(FLOW, "flow", subbasins)
    write_outputs(subbasins, edges, topology, segments, unassigned, stations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
