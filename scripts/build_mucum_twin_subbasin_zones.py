#!/usr/bin/env python3
"""Build hydrologically nested polygons for the current Muçum HEC twin.

The model units are:
- SB_PRATA_7868: Prata UG clipped by watershed 86472000
- SB_ANTAS_RESIDUAL: watershed 86472000 minus Prata
- SB_CARREIRO_7866: Carreiro UG clipped by watershed 86472600
- SB_STZ_RESIDUAL: watershed 86472600 minus upstream Antas and Carreiro
- SB_INC_MUCUM: watershed 86510000 minus watershed 86472600

SRTM/WhiteboxTools is used only to delineate the three nested control basins.
The result is a small GeoJSON committed to the repository and reused by the
6-hour forecast robot. Research artifact, not an official basin product.
"""
from __future__ import annotations
import gzip, json, shutil, urllib.request
from pathlib import Path
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.merge import merge
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import Point, shape, mapping
from shapely.ops import unary_union
from whitebox.whitebox_tools import WhiteboxTools

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
WORK=OUT/"mucum_twin_zones_work"
UGS=OUT/"ugs_g040.geojson"
OUTPUT=OUT/"mucum_twin_subbasin_zones.geojson"
REPORT=OUT/"mucum_twin_subbasin_zones_report.json"
TARGET_CRS="EPSG:31982"
TILES=["S30W052","S29W052","S28W052","S30W051","S29W051","S28W051"]
S3="https://s3.amazonaws.com/elevation-tiles-prod/skadi/{band}/{tile}.hgt.gz"
OUTLETS={
 "86472000":{"name":"Linha Jose Julio","lon":-51.6997,"lat":-29.0978,"target_area_km2":12918.656},
 "86472600":{"name":"Santa Tereza","lon":-51.7322,"lat":-29.1781,"target_area_km2":15775.186},
 "86510000":{"name":"Mucum","lon":-51.8686,"lat":-29.1672,"target_area_km2":15965.207},
}
TARGET_AREAS={
 "SB_PRATA_7868":3775.99,
 "SB_ANTAS_RESIDUAL":9142.666,
 "SB_CARREIRO_7866":2564.19,
 "SB_STZ_RESIDUAL":292.34,
 "SB_INC_MUCUM":190.021,
}

def download_tiles():
 d=WORK/"dem_source"; d.mkdir(parents=True,exist_ok=True)
 paths=[]
 for tile in TILES:
  gz=d/f"{tile}.hgt.gz"; hgt=d/f"{tile}.hgt"
  if not gz.exists():
   req=urllib.request.Request(S3.format(band=tile[:3],tile=tile),headers={"User-Agent":"PREVINE-twin-zones/1.0"})
   with urllib.request.urlopen(req,timeout=180) as resp: gz.write_bytes(resp.read())
  if not hgt.exists():
   with gzip.open(gz,"rb") as src,hgt.open("wb") as dst: shutil.copyfileobj(src,dst)
  paths.append(hgt)
 return paths

def prepare_dem(paths):
 mosaic=WORK/"srtm_mosaic_wgs84.tif"
 srcs=[rasterio.open(p) for p in paths]
 try:
  data,tr=merge(srcs,nodata=-32768)
  prof=srcs[0].profile.copy(); prof.update(driver="GTiff",height=data.shape[1],width=data.shape[2],transform=tr,crs="EPSG:4326",count=1,dtype="int16",nodata=-32768,compress="deflate",predictor=2)
  with rasterio.open(mosaic,"w",**prof) as dst: dst.write(data[0].astype("int16"),1)
 finally:
  for s in srcs:s.close()
 target=WORK/"srtm_utm22s_30m.tif"
 with rasterio.open(mosaic) as src:
  tr,w,h=calculate_default_transform(src.crs,TARGET_CRS,src.width,src.height,*src.bounds,resolution=30)
  prof=src.profile.copy(); prof.update(crs=TARGET_CRS,transform=tr,width=w,height=h,dtype="float32",nodata=-32768.0,compress="deflate")
  with rasterio.open(target,"w",**prof) as dst:
   reproject(source=rasterio.band(src,1),destination=rasterio.band(dst,1),src_transform=src.transform,src_crs=src.crs,src_nodata=src.nodata,dst_transform=tr,dst_crs=TARGET_CRS,dst_nodata=-32768.0,resampling=Resampling.bilinear)
 return target

def raster_polygon(path):
 with rasterio.open(path) as src:
  a=src.read(1); mask=a>0
  gs=[shape(g) for g,v in shapes(a,mask=mask,transform=src.transform) if v>0]
  if not gs: raise RuntimeError(f"empty watershed {path}")
  return unary_union(gs)

def delineate_all(dem):
 wb=WORK/"whitebox"; wb.mkdir(exist_ok=True)
 wbt=WhiteboxTools(); wbt.set_working_dir(str(wb)); wbt.verbose=False
 filled=wb/"dem_filled.tif"; ptr=wb/"d8_pointer.tif"; acc=wb/"d8_accumulation.tif"
 wbt.fill_depressions_wang_and_liu(str(dem),str(filled))
 wbt.d8_pointer(str(filled),str(ptr))
 wbt.d8_flow_accumulation(str(filled),str(acc),out_type="cells")
 out={}
 for code,o in OUTLETS.items():
  raw=wb/f"raw_{code}.shp"; snap=wb/f"snap_{code}.shp"; ws=wb/f"ws_{code}.tif"
  gpd.GeoDataFrame([{"station":code}],geometry=[Point(o["lon"],o["lat"])],crs="EPSG:4326").to_crs(TARGET_CRS).to_file(raw)
  wbt.snap_pour_points(str(raw),str(acc),str(snap),snap_dist=3000.0)
  wbt.watershed(str(ptr),str(snap),str(ws))
  out[code]=raster_polygon(ws)
 return out

def find_ug(gdf, needle):
 needle=needle.casefold()
 hits=[]
 for _,row in gdf.iterrows():
  text=" ".join(str(v) for k,v in row.items() if k!="geometry").casefold()
  if needle in text:hits.append(row.geometry)
 if not hits: raise RuntimeError(f"UG not found: {needle}")
 return unary_union(hits)

def clean(g):
 return g.buffer(0) if not g.is_valid else g

def main():
 WORK.mkdir(parents=True,exist_ok=True)
 dem=prepare_dem(download_tiles())
 ws=delineate_all(dem)
 antas=clean(ws["86472000"]); stz=clean(ws["86472600"]); muc=clean(ws["86510000"])
 ugs=gpd.read_file(UGS).to_crs(TARGET_CRS)
 prata=clean(find_ug(ugs,"prata").intersection(antas))
 carreiro=clean(find_ug(ugs,"carreiro").intersection(stz).difference(antas))
 antas_res=clean(antas.difference(prata))
 stz_res=clean(stz.difference(antas.union(carreiro)))
 muc_inc=clean(muc.difference(stz))
 zones={
  "SB_PRATA_7868":prata,
  "SB_ANTAS_RESIDUAL":antas_res,
  "SB_CARREIRO_7866":carreiro,
  "SB_STZ_RESIDUAL":stz_res,
  "SB_INC_MUCUM":muc_inc,
 }
 features=[]; report={"schema_version":"mucum_twin_subbasin_zones_v1","method":"nested SRTM watersheds + official G040 UG Prata/Carreiro","outlets":{},"zones":{}}
 for code,g in ws.items():
  area=g.area/1e6; target=OUTLETS[code]["target_area_km2"]
  report["outlets"][code]={"area_srtm_km2":round(area,3),"target_model_km2":target,"ratio":round(area/target,5)}
 for zid,g in zones.items():
  area=g.area/1e6; target=TARGET_AREAS[zid]
  report["zones"][zid]={"area_geometry_km2":round(area,3),"area_model_km2":target,"ratio":round(area/target,5)}
  gw=gpd.GeoSeries([g],crs=TARGET_CRS).to_crs("EPSG:4326").iloc[0]
  features.append({"type":"Feature","properties":{"subbasin_id":zid,"area_geometry_km2":round(area,3),"area_model_km2":target,"area_ratio":round(area/target,5)},"geometry":mapping(gw.simplify(0.00015,preserve_topology=True))})
 # Hard gate only for gross topology failure; area differences from DEM/inventory are reported, never forced.
 for code,item in report["outlets"].items():
  if not 0.80 <= item["ratio"] <= 1.20: raise RuntimeError(f"nested watershed gross area mismatch {code}: {item}")
 for zid,item in report["zones"].items():
  if not 0.65 <= item["ratio"] <= 1.35: raise RuntimeError(f"zone gross area mismatch {zid}: {item}")
 payload={"type":"FeatureCollection","name":"mucum_twin_subbasin_zones","properties":{"method":report["method"],"target_crs":TARGET_CRS},"features":features}
 OUTPUT.write_text(json.dumps(payload,ensure_ascii=False)+"\n",encoding="utf-8")
 REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":main()
