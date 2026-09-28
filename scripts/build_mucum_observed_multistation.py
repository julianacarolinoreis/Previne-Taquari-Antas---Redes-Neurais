#!/usr/bin/env python3
from __future__ import annotations
import csv,json,math,os,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
from shapely.geometry import Point,shape
from shapely.ops import unary_union

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/data/estudo_bacia_taquari_antas"
RAIN_CATALOG=OUT/"pluviometria_g040.geojson"
FLOW_CATALOG=OUT/"postos_g040.geojson"
BASIN_PATH=ROOT/"assets/data/hec_hms_spatialized_mucum/watershed_86510000_srtm.geojson"
ZONES_PATH=ROOT/"assets/data/hec_hms_spatialized_mucum/thiessen_zones_86510000.geojson"
JSON_OUT=OUT/"mucum_observed_multistation_latest.json"
RAIN_CSV=OUT/"mucum_observed_multistation_rain_hourly.csv"
FLOW_CSV=OUT/"mucum_observed_multistation_flow_hourly.csv"
BRT=timezone(timedelta(hours=-3)); UTC=timezone.utc
EVENT_START_LOCAL=datetime(2026,9,26,0,0)
ANA_URL="https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
INMET_URL="https://apitempo.inmet.gov.br/estacao/{start}/{end}/{code}"
CEMADEN_URL="https://mapservices.cemaden.gov.br/MapaInterativoWS/resources/horario/{station_id}/167"
CEMADEN_IDS={"432040401A":"8928","4320404010A":"8928"}
MAX_WORKERS=int(os.environ.get("OBS_FETCH_WORKERS","14"))
GRID_STEP=float(os.environ.get("OBS_GRID_STEP_DEG","0.05"))

def load(path): return json.loads(path.read_text(encoding="utf-8"))
def finite(v):
    try:x=float(str(v).replace(",","."))
    except (TypeError,ValueError):return None
    return x if math.isfinite(x) else None
def lname(tag):return tag.rsplit("}",1)[-1]
def parse_ana_time(v):
    v=(v or "").strip().replace("T"," ")
    for fmt in ("%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M"):
        try:return datetime.strptime(v[:19],fmt)
        except ValueError:pass
    return None
def request(url,timeout=35):
    req=urllib.request.Request(url,headers={"User-Agent":"PREVINE-Mucum-multistation/1.0","Accept":"application/json,text/xml,application/xml,*/*;q=0.8"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()
def fetch_ana(code,start,end):
    params=urllib.parse.urlencode({"codEstacao":code,"dataInicio":start.strftime("%d/%m/%Y"),"dataFim":end.strftime("%d/%m/%Y")})
    root=ET.fromstring(request(f"{ANA_URL}?{params}")); roots=[root]
    if (root.text or "").strip().startswith("<"):
        try:roots.append(ET.fromstring(root.text))
        except Exception:pass
    rows=[]
    for rt in roots:
        for node in rt.iter():
            f={lname(ch.tag):(ch.text or "") for ch in node}
            stamp=f.get("DataHora") or f.get("Data_Hora")
            if not stamp:continue
            dt=parse_ana_time(stamp)
            if dt is None or dt<start or dt>end:continue
            rows.append({"time_local":dt,"rain_mm":finite(f.get("Chuva") or f.get("chuva") or f.get("Precipitacao")),"flow_m3s":finite(f.get("Vazao") or f.get("vazao")),"level":finite(f.get("Nivel") or f.get("nivel"))})
    return {"rows":rows,"source":"ANA DadosHidrometeorologicos"}
def parse_inmet_time(row):
    d=str(row.get("DT_MEDICAO") or "").strip(); h=str(row.get("HR_MEDICAO") or "").strip()
    if not d:return None
    try:return datetime.strptime(d+(h.zfill(4)[:4] if h else "0000"),"%Y-%m-%d%H%M")
    except ValueError:return None
def fetch_inmet(code,start,end):
    url=INMET_URL.format(start=start.strftime("%Y-%m-%d"),end=end.strftime("%Y-%m-%d"),code=urllib.parse.quote(code))
    data=json.loads(request(url).decode("utf-8",errors="replace") or "[]")
    if not isinstance(data,list):data=[]
    rows=[]
    for item in data:
        if not isinstance(item,dict):continue
        dt=parse_inmet_time(item)
        if dt is None or dt<start or dt>end:continue
        rows.append({"time_local":dt,"rain_mm":finite(item.get("CHUVA") if item.get("CHUVA") not in (None,"") else item.get("PRECIPITACAO_TOTAL_HORARIO_MM")),"flow_m3s":None,"level":None})
    return {"rows":rows,"source":"INMET API Tempo"}
def fetch_cemaden(code,start,end):
    sid=CEMADEN_IDS.get(code)
    if not sid:return {"rows":[],"source":"CEMADEN","error":"station id not mapped"}
    payload=json.loads(request(CEMADEN_URL.format(station_id=sid)).decode("utf-8",errors="replace") or "{}")
    rows=[]; dates=payload.get("datas") if isinstance(payload,dict) else None
    vals=(payload.get("chuvas") or payload.get("valores") or payload.get("precipitacoes") or []) if isinstance(payload,dict) else []
    if isinstance(dates,list):
        for i,raw_t in enumerate(dates):
            txt=str(raw_t).replace("T"," ").replace("Z",""); dt=None
            for fmt in ("%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M"):
                try:dt=datetime.strptime(txt[:19],fmt);break
                except ValueError:pass
            if dt is None or dt<start or dt>end:continue
            rows.append({"time_local":dt,"rain_mm":finite(vals[i]) if i<len(vals) else None,"flow_m3s":None,"level":None})
    return {"rows":rows,"source":"CEMADEN horário 167h"}
def aggregate(rows):
    b={}
    for r in rows:
        t=r["time_local"].replace(minute=0,second=0,microsecond=0); x=b.setdefault(t,{"rain":[],"flow":[],"level":[]})
        if r.get("rain_mm") is not None and r["rain_mm"]>=0:x["rain"].append(float(r["rain_mm"]))
        if r.get("flow_m3s") is not None and r["flow_m3s"]>=0:x["flow"].append(float(r["flow_m3s"]))
        if r.get("level") is not None:x["level"].append(float(r["level"]))
    return {t:{"rain_mm":sum(x["rain"]) if x["rain"] else None,"flow_m3s":sum(x["flow"])/len(x["flow"]) if x["flow"] else None,"level":sum(x["level"])/len(x["level"]) if x["level"] else None} for t,x in b.items()}
def catalogs(path,basin,rain):
    raw=load(path); out=[]
    for feat in raw.get("features") or []:
        p=feat.get("properties") or {}; c=(feat.get("geometry") or {}).get("coordinates") or []
        lon=finite(c[0]) if len(c)>=2 else finite(p.get("lon")); lat=finite(c[1]) if len(c)>=2 else finite(p.get("lat"))
        if lon is None or lat is None or not basin.covers(Point(lon,lat)):continue
        if rain:
            net=str(p.get("rede") or "ANA").upper()
            if net not in {"ANA","INMET","CEMADEN"}:continue
        else:
            if str(p.get("tipo") or "").lower()!="fluviometrica":continue
            net="ANA"
        code=str(p.get("codigo") or "").strip()
        if code:out.append({"code":code,"name":p.get("nome") or code,"network":net,"lat":float(lat),"lon":float(lon),"upg":p.get("upg"),"operating_flag":p.get("situacao") if rain else p.get("operando")})
    return out
def fetch_item(item,start,end):
    try:
        if item["network"]=="ANA":res=fetch_ana(item["code"].lstrip("0") if len(item["code"])==8 and item["code"].startswith("0") else item["code"],start,end)
        elif item["network"]=="INMET":res=fetch_inmet(item["code"],start,end)
        else:res=fetch_cemaden(item["code"],start,end)
        res["ok"]=True
    except Exception as e:res={"rows":[],"source":item["network"],"ok":False,"error":str(e)}
    res["hourly"]=aggregate(res["rows"]);res["station"]=item;return res
def geometries():
    basin=unary_union([shape(f["geometry"]) for f in load(BASIN_PATH).get("features") or [] if f.get("geometry")])
    zones={}
    for feat in load(ZONES_PATH).get("features") or []:
        p=feat.get("properties") or {}
        if p.get("feature_type")=="thiessen_zone" and p.get("station"):zones[str(p["station"])]=shape(feat["geometry"]).intersection(basin)
    return basin,zones
def grid(geom):
    minx,miny,maxx,maxy=geom.bounds; pts=[]; y=math.floor(miny/GRID_STEP)*GRID_STEP+GRID_STEP/2
    while y<=maxy:
        x=math.floor(minx/GRID_STEP)*GRID_STEP+GRID_STEP/2
        while x<=maxx:
            if geom.covers(Point(x,y)):pts.append((x,y,math.cos(math.radians(y))))
            x+=GRID_STEP
        y+=GRID_STEP
    return pts
def idw(g,stations,vals,k=6):
    use=[s for s in stations if vals.get(s["code"]) is not None]
    if len(use)<2 or not g:return None
    sx=np.asarray([s["lon"] for s in use]);sy=np.asarray([s["lat"] for s in use]);sv=np.asarray([vals[s["code"]] for s in use],dtype=float)
    total=aw=0.0
    for gx,gy,a in g:
        d2=((sx-gx)*math.cos(math.radians(gy)))**2+(sy-gy)**2
        if np.any(d2<1e-12):v=float(sv[int(np.argmin(d2))])
        else:
            idx=np.argpartition(d2,min(k,len(d2))-1)[:min(k,len(d2))];w=1.0/d2[idx];v=float(np.sum(w*sv[idx])/np.sum(w))
        total+=v*a;aw+=a
    return total/aw if aw else None
def isots(t):return t.isoformat(timespec="minutes")
def main():
    start=EVENT_START_LOCAL;end=datetime.now(BRT).replace(tzinfo=None);basin,zones=geometries()
    raincat=catalogs(RAIN_CATALOG,basin,True);flowcat=catalogs(FLOW_CATALOG,basin,False)
    all_items=[];seen=set()
    for item in raincat+flowcat:
        key=(item["network"],item["code"])
        if key not in seen:seen.add(key);all_items.append(item)
    results={}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs={ex.submit(fetch_item,item,start,end):(item["network"],item["code"]) for item in all_items}
        for fut in as_completed(futs):
            try:results[futs[fut]]=fut.result()
            except Exception as e:results[futs[fut]]={"ok":False,"rows":[],"hourly":{},"error":str(e)}
    rains=[]
    for st in raincat:
        r=results.get((st["network"],st["code"])) or {};n=sum(v.get("rain_mm") is not None for v in (r.get("hourly") or {}).values())
        if n:rains.append({"station":st,"result":r,"valid_hours":n})
    flows=[]
    for st in flowcat:
        r=results.get((st["network"],st["code"])) or {};h=r.get("hourly") or {};nq=sum(v.get("flow_m3s") is not None for v in h.values());nl=sum(v.get("level") is not None for v in h.values())
        if nq or nl:flows.append({"station":st,"result":r,"valid_flow_hours":nq,"valid_level_hours":nl})
    hours=[];t=start
    while t<=end.replace(minute=0,second=0,microsecond=0):hours.append(t);t+=timedelta(hours=1)
    metas=[x["station"] for x in rains];grids={"basin":grid(basin),**{c:grid(g) for c,g in zones.items()}}
    areal=[]
    for h in hours:
        vals={e["station"]["code"]:(e["result"].get("hourly") or {}).get(h,{}).get("rain_mm") for e in rains}
        vals={k:float(v) for k,v in vals.items() if v is not None}
        row={"time_local":isots(h),"valid_station_count":len(vals),"basin_mean_mm":idw(grids["basin"],metas,vals)}
        for c in zones:row[f"zone_{c}_mm"]=idw(grids[c],metas,vals)
        areal.append(row)
    with RAIN_CSV.open("w",encoding="utf-8",newline="") as fh:
        fields=["time_local","valid_station_count","basin_mean_mm"]+[f"zone_{c}_mm" for c in zones];w=csv.DictWriter(fh,fieldnames=fields);w.writeheader()
        for row in areal:w.writerow({k:"" if v is None else round(v,4) if isinstance(v,float) else v for k,v in row.items()})
    with FLOW_CSV.open("w",encoding="utf-8",newline="") as fh:
        fields=["code","name","upg","time_local","flow_m3s","level"];w=csv.DictWriter(fh,fieldnames=fields);w.writeheader()
        for e in flows:
            st=e["station"]
            for h,v in sorted((e["result"].get("hourly") or {}).items()):
                if v.get("flow_m3s") is None and v.get("level") is None:continue
                w.writerow({"code":st["code"],"name":st["name"],"upg":st.get("upg"),"time_local":isots(h),"flow_m3s":"" if v.get("flow_m3s") is None else round(v["flow_m3s"],4),"level":"" if v.get("level") is None else round(v["level"],4)})
    payload={"schema_version":"mucum_observed_multistation_v1","generated_at_utc":datetime.now(UTC).isoformat().replace("+00:00","Z"),"event_window":{"start_local":isots(start),"end_local":isots(end),"timezone":"America/Sao_Paulo"},"watershed":{"outlet_station":"86510000","scope":"bacia contribuinte até Muçum; postos a jusante excluídos"},"rain":{"inventory_count_inside":len(raincat),"valid_station_count":len(rains),"valid_by_network":{n:sum(e["station"]["network"]==n for e in rains) for n in ("ANA","INMET","CEMADEN")},"spatial_method":"IDW^2 em grade 0.05°; até 6 vizinhos; somente observações válidas; ausências não viram zero","hourly_areal":[{k:None if v is None else round(v,4) if isinstance(v,float) else v for k,v in row.items()} for row in areal],"stations":[{**e["station"],"source":e["result"].get("source"),"valid_hours":e["valid_hours"],"series":[{"time_local":isots(h),"mm":round(v["rain_mm"],4)} for h,v in sorted((e["result"].get("hourly") or {}).items()) if v.get("rain_mm") is not None]} for e in rains]},"flow":{"inventory_count_inside":len(flowcat),"stations_with_flow_or_level":len(flows),"stations_with_flow":sum(e["valid_flow_hours"]>0 for e in flows),"stations_with_level":sum(e["valid_level_hours"]>0 for e in flows),"stations":[{**e["station"],"source":e["result"].get("source"),"valid_flow_hours":e["valid_flow_hours"],"valid_level_hours":e["valid_level_hours"],"series":[{"time_local":isots(h),"flow_m3s":None if v.get("flow_m3s") is None else round(v["flow_m3s"],4),"level":None if v.get("level") is None else round(v["level"],4)} for h,v in sorted((e["result"].get("hourly") or {}).items()) if v.get("flow_m3s") is not None or v.get("level") is not None]} for e in flows]},"fetch_audit":{"requested_unique_station_count":len(all_items),"failed_count":sum(not bool(r.get("ok")) for r in results.values()),"failures":[{"network":k[0],"code":k[1],"error":r.get("error")} for k,r in results.items() if not r.get("ok")][:100]},"artifacts":{"rain_csv":str(RAIN_CSV.relative_to(ROOT)),"flow_csv":str(FLOW_CSV.relative_to(ROOT))},"research_only":True}
    JSON_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"rain_inventory_inside":len(raincat),"rain_valid":len(rains),"rain_valid_by_network":payload["rain"]["valid_by_network"],"flow_inventory_inside":len(flowcat),"flow_stations_valid":len(flows),"flow_stations_with_q":payload["flow"]["stations_with_flow"],"failures":payload["fetch_audit"]["failed_count"],"event_start":payload["event_window"]["start_local"],"event_end":payload["event_window"]["end_local"]},ensure_ascii=False))
if __name__=="__main__":main()
