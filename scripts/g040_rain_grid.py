#!/usr/bin/env python3
"""Shared fixed precipitation-grid contract for G040 research models.

Historic HEC-HMS packages use a complete EPSG:4326 rectangle with 0.1-degree
sampling cells:
  longitude edges -52.8 .. -49.8  -> 30 columns
  latitude edges  -30.0 .. -28.0  -> 20 rows
Total: 600 cells.

The coordinates exposed here are cell centers. This module defines only grid
geometry/indexing; it never fabricates or fills rainfall values.
"""
from __future__ import annotations

import math
from typing import Any

GRID_WEST=-52.8
GRID_EAST=-49.8
GRID_SOUTH=-30.0
GRID_NORTH=-28.0
GRID_STEP_DEG=0.1
GRID_COLS=30
GRID_ROWS=20
GRID_CELL_COUNT=600

def _center(lo: float, idx: int) -> float:
    return round(lo + (idx + 0.5) * GRID_STEP_DEG,6)

def build_grid_cells() -> list[dict[str,Any]]:
    cells=[]
    for row in range(GRID_ROWS):
        lat=_center(GRID_SOUTH,row)
        for col in range(GRID_COLS):
            lon=_center(GRID_WEST,col)
            idx=row*GRID_COLS+col
            cells.append({
                "index":idx,
                "row":row,
                "col":col,
                "cell_id":f"G040_R{row:02d}_C{col:02d}",
                "latitude":lat,
                "longitude":lon,
            })
    if len(cells)!=GRID_CELL_COUNT:
        raise RuntimeError(f"invalid G040 rain grid: {len(cells)} cells")
    return cells

def point_to_grid_index(lon: float,lat: float) -> int:
    x=float(lon); y=float(lat); eps=1e-9
    if x < GRID_WEST-eps or x > GRID_EAST+eps or y < GRID_SOUTH-eps or y > GRID_NORTH+eps:
        raise ValueError(f"point outside G040 grid: lon={x}, lat={y}")
    col=GRID_COLS-1 if math.isclose(x,GRID_EAST,abs_tol=eps) else int(math.floor((x-GRID_WEST)/GRID_STEP_DEG))
    row=GRID_ROWS-1 if math.isclose(y,GRID_NORTH,abs_tol=eps) else int(math.floor((y-GRID_SOUTH)/GRID_STEP_DEG))
    if not (0<=col<GRID_COLS and 0<=row<GRID_ROWS):
        raise ValueError(f"invalid G040 grid index row={row}, col={col}")
    return row*GRID_COLS+col

def grid_contract() -> dict[str,Any]:
    return {
        "resolution_deg":GRID_STEP_DEG,
        "rows_latitude":GRID_ROWS,
        "cols_longitude":GRID_COLS,
        "cells":GRID_CELL_COUNT,
        "edge_bounds":{
            "west":GRID_WEST,"east":GRID_EAST,
            "south":GRID_SOUTH,"north":GRID_NORTH,
        },
        "cell_center_bounds":{
            "west":_center(GRID_WEST,0),
            "east":_center(GRID_WEST,GRID_COLS-1),
            "south":_center(GRID_SOUTH,0),
            "north":_center(GRID_SOUTH,GRID_ROWS-1),
        },
        "crs":"EPSG:4326",
    }
