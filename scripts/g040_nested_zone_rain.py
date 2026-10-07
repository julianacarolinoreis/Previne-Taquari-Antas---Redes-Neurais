#!/usr/bin/env python3
"""Area weights between the fixed 600-cell G040 rain grid and Muçum twin zones.

The same geometric weights are used for observed IDW grids and exact ECMWF grids
so historical causal replays do not change spatial support at t0.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform

try:
    from scripts.g040_rain_grid import (
        GRID_STEP_DEG, build_grid_cells,
    )
except ModuleNotFoundError:
    from g040_rain_grid import GRID_STEP_DEG, build_grid_cells

ROOT=Path(__file__).resolve().parents[1]
ZONES=ROOT/"assets/data/estudo_bacia_taquari_antas/mucum_twin_subbasin_zones.geojson"
ZONE_IDS=(
    "SB_PRATA_7868",
    "SB_ANTAS_RESIDUAL",
    "SB_CARREIRO_7866",
    "SB_STZ_RESIDUAL",
    "SB_INC_MUCUM",
)
_PROJECT=Transformer.from_crs("EPSG:4326","EPSG:31982",always_xy=True).transform

@lru_cache(maxsize=1)
def zone_grid_weights() -> dict[str,dict[str,Any]]:
    raw=json.loads(ZONES.read_text(encoding="utf-8"))
    zones={}
    for f in raw.get("features") or []:
        sid=str((f.get("properties") or {}).get("subbasin_id") or "")
        if sid in ZONE_IDS and f.get("geometry"):
            zones[sid]=transform(_PROJECT,shape(f["geometry"]))
    missing=[z for z in ZONE_IDS if z not in zones]
    if missing:
        raise RuntimeError(f"Muçum twin zones missing: {missing}")

    half=GRID_STEP_DEG/2.0
    cells=build_grid_cells()
    cell_geom={}
    for c in cells:
        lon=float(c["longitude"]); lat=float(c["latitude"])
        cell_geom[c["cell_id"]]=transform(
            _PROJECT,
            box(lon-half,lat-half,lon+half,lat+half),
        )

    out={}
    for sid,zg in zones.items():
        overlaps={}
        for cid,cg in cell_geom.items():
            inter=zg.intersection(cg)
            if inter.is_empty:
                continue
            a=float(inter.area/1_000_000.0)
            if a>1e-6:
                overlaps[cid]=a
        total=sum(overlaps.values())
        zone_area=float(zg.area/1_000_000.0)
        if total<=0:
            raise RuntimeError(f"{sid}: no G040-grid overlap")
        ratio=total/zone_area if zone_area>0 else 0.0
        if not 0.985<=ratio<=1.015:
            raise RuntimeError(f"{sid}: grid overlap ratio {ratio:.5f} outside tolerance")
        out[sid]={
            "zone_geometry_km2":zone_area,
            "grid_overlap_km2":total,
            "coverage_ratio":ratio,
            "cell_area_km2":overlaps,
        }
    return out

def aggregate_grid_by_zone(
    grid_values: dict[str,float|None],
) -> dict[str,float|None]:
    result={}
    for sid,meta in zone_grid_weights().items():
        num=0.0; den=0.0
        for cid,a in meta["cell_area_km2"].items():
            v=grid_values.get(cid)
            if v is None:
                continue
            num+=float(v)*float(a); den+=float(a)
        result[sid]=None if den<=0 else num/den
    return result

def audit_summary() -> dict[str,Any]:
    return {
        sid:{
            "zone_geometry_km2":round(float(m["zone_geometry_km2"]),3),
            "grid_overlap_km2":round(float(m["grid_overlap_km2"]),3),
            "coverage_ratio":round(float(m["coverage_ratio"]),6),
            "cell_count":len(m["cell_area_km2"]),
        }
        for sid,m in zone_grid_weights().items()
    }
