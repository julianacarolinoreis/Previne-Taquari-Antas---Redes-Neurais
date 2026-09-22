#!/usr/bin/env python3
"""Convert full-field IFS cells into spatial forcing for the current Muçum twin.

Every IFS cell is intersected with each hydrologic model zone. Rainfall is
area-weighted only inside each subbasin; there is no single basin-wide forcing.
The resulting JSON is API-compatible with run_hec_twin_mucum_forward_5d.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
SPATIAL=OUT/"spatial_ifs_mucum/spatial_ifs_mucum_latest.json"
CELLS_GEO=OUT/"spatial_ifs_mucum/spatial_ifs_mucum_cells_120h.geojson"
ZONES=OUT/"mucum_twin_subbasin_zones.geojson"
STRUCT=OUT/"estrutura_stz_mucum_latest.json"
OUTPUT=OUT/"hec_twin_ifs_spatial_forcing_5d_latest.json"
PROJ=Transformer.from_crs("EPSG:4326","EPSG:31982",always_xy=True).transform
SUBBASINS=[
 "SB_PRATA_7868","SB_ANTAS_RESIDUAL","SB_CARREIRO_7866","SB_STZ_RESIDUAL","SB_INC_MUCUM"
]

def load_json(p):
 return json.loads(p.read_text(encoding="utf-8"))

def main():
 if not SPATIAL.exists(): raise SystemExit(f"missing {SPATIAL}")
 if not CELLS_GEO.exists(): raise SystemExit(f"missing {CELLS_GEO}")
 if not ZONES.exists(): raise SystemExit(f"missing {ZONES}")

 spatial=load_json(SPATIAL)
 cells_meta={c["cell_id"]:c for c in spatial.get("cells",[])}
 cell_gj=load_json(CELLS_GEO)
 cell_geom={}
 for f in cell_gj.get("features",[]):
  cid=(f.get("properties") or {}).get("cell_id")
  if cid: cell_geom[cid]=transform(PROJ,shape(f["geometry"]))

 zone_gj=load_json(ZONES)
 zones={}
 for f in zone_gj.get("features",[]):
  sid=(f.get("properties") or {}).get("subbasin_id")
  if sid: zones[sid]=transform(PROJ,shape(f["geometry"]))
 for sid in SUBBASINS:
  if sid not in zones: raise RuntimeError(f"zone missing {sid}")

 times=list((spatial.get("window") or {}).get("hours") and (spatial.get("cells") or [{}])[0].get("times_utc") or [])
 # v1 spatial package stores time axis implicitly on every cell only in the generation object;
 # reconstructed published JSON stores precip arrays and window. Build hourly timestamps from first window.
 if not times:
  start=(spatial.get("window") or {}).get("start_utc")
  hours=int((spatial.get("window") or {}).get("hours") or 0)
  if not start or hours<=0: raise RuntimeError("spatial IFS time window missing")
  from datetime import timedelta
  t0=datetime.fromisoformat(start.replace("Z","+00:00"))
  times=[(t0+timedelta(hours=i)).isoformat().replace("+00:00","Z") for i in range(hours)]

 n=len(times)
 precip={}
 audit={}
 for sid,zg in zones.items():
  overlaps=[]
  for cid,cg in cell_geom.items():
   if cid not in cells_meta: continue
   inter=zg.intersection(cg)
   if inter.is_empty: continue
   a=inter.area/1e6
   if a>0.0001: overlaps.append((cid,a))
  area=sum(a for _,a in overlaps)
  if area<=0: raise RuntimeError(f"no IFS overlap for {sid}")
  series=[]
  for i in range(n):
   value=0.0
   for cid,a in overlaps:
    vals=cells_meta[cid].get("precip_mm") or []
    if i>=len(vals): raise RuntimeError(f"cell {cid} has only {len(vals)} hours")
    value+=float(vals[i])*a
   series.append(round(value/area,4))
  precip[sid]=series
  audit[sid]={
   "zone_geometry_km2":round(zg.area/1e6,3),
   "ifs_overlap_km2":round(area,3),
   "ifs_cells_used":len(overlaps),
   "total_mm":round(sum(series),3),
   "min_hourly_mm":round(min(series),4),
   "max_hourly_mm":round(max(series),4),
  }

 struct=load_json(STRUCT)
 areas={el["id"]:float(el["area_km2"]) for el in struct["models"]["mucum"]["elements"] if el.get("type")=="subbasin"}
 total_area=sum(areas[s] for s in SUBBASINS)
 aw_hourly=[sum(precip[s][i]*areas[s] for s in SUBBASINS)/total_area for i in range(n)]
 payload={
  "schema_version":"hec_twin_ifs_spatial_forcing_v1",
  "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
  "model":"ecmwf_ifs025_full_field",
  "source_spatial_artifact":str(SPATIAL.relative_to(ROOT)),
  "zone_artifact":str(ZONES.relative_to(ROOT)),
  "artifact_name":"hec_twin_ifs_spatial_forcing_5d_latest.json",
  "horizon_hours":n,
  "times_utc":times,
  "precip_mm_by_subbasin":precip,
  "area_weighted_mean_mm":{
    "hourly":[round(v,4) for v in aw_hourly],
    "total_mm":round(sum(aw_hourly),3),
    "past_mm":0.0,
    "note":"audit summary only; model forcing remains distinct by subbasin",
  },
  "window":{"start_utc":times[0],"end_utc":times[-1],"hours":n,"past_hours":0},
  "point_proxy_not_areal_mask":False,
  "spatial_field_full":True,
  "all_ifs_cells_preserved_before_subbasin_integration":True,
  "subbasin_overlap_audit":audit,
  "method_pt":"Todas as células IFS 0,25° são intersectadas com cada zona hidrológica do gêmeo; cada sub-bacia recebe seu próprio hietograma horário ponderado pela área de interseção.",
 }
 OUTPUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"output":str(OUTPUT.relative_to(ROOT)),"total_mm_audit":payload["area_weighted_mean_mm"]["total_mm"],"subbasins":audit},ensure_ascii=False))
if __name__=="__main__":main()
