#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estudo de caso animado — Muçum.

A RNA prevê o nível daqui a 12 h. Quem essa mancha alcança precisa evacuar.
Conforme a previsão sobe, a fila muda — e a rota a pé desvia, passa pela
água ou some.

Gera mucum_estudo_caso_slides.html (play no browser) e, com --video, o MP4 16:9.

Uso:
  py codigo_python/09_rota_fuga/gerar_estudo_caso_slides.py
  py codigo_python/09_rota_fuga/gerar_estudo_caso_slides.py --video
"""
from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import math
import os
import re
import shutil
import socketserver
import subprocess
import threading
import time
from pathlib import Path

import networkx as nx
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

RAIZ = Path(__file__).resolve().parents[2]
RF = RAIZ / "assets" / "data" / "rota_fuga" / "rota_fuga_ruas_mucum_cenario.json"
CONTORNOS = RAIZ / "assets" / "data" / "mucum_inundacao" / "contornos_mancha.json"
PREVISAO = RAIZ / "mucum_previsao_inundacao.html"
SAIDA_HTML = RAIZ / "mucum_estudo_caso_slides.html"
OUT = RAIZ / "outputs"
COPY = Path(r"D:\PREVINE\repo_site_stz4h_pro_20260812\outputs")
ZERO_REGUA = 5.0
VEL_IDOSO = 0.9
PASSO = 0.5
EVENTO = "ev27_12h"
PORT = 8768
VIEW = {"width": 1600, "height": 900}
FPS = 4


def cotas_por_no(nos):
    dc = json.loads(CONTORNOS.read_text(encoding="utf-8"))
    porn = {}
    for f in dc["features"]:
        nb = round(int(round(float(f["properties"]["nivel_m"]), 1) / PASSO) * PASSO, 1)
        porn.setdefault(nb, []).append(shape(f["geometry"]).buffer(0))
    niveis = sorted(porn)
    unioes = {nv: unary_union(porn[nv]) for nv in niveis}

    def cota(lat, lon):
        p = Point(lon, lat)
        for nv in niveis:
            if unioes[nv].covers(p):
                return nv
        return None

    return [cota(la, lo) for la, lo in nos]


def rota_ate_abrigo(rf, i0):
    nos, prox, dest = rf["nos"], rf["prox"], rf["dest"]
    pts, i, g = [], i0, 0
    while g < 8000:
        pts.append([round(nos[i][0], 6), round(nos[i][1], 6)])
        nxt = prox[i]
        if nxt == i or nxt < 0:
            break
        i = nxt
        g += 1
    abrigo = next((a for a in rf["abrigos"] if a["id"] == dest[i0]), rf["abrigos"][0])
    return pts, abrigo


def escolhe_casas(rf, cotas):
    dist = rf["dist_m"]
    alvos = [
        ("Casa na várzea", 3.0, "A RNA alcança primeiro — sair cedo."),
        ("Casa no centro baixo", 5.7, "Entra na fila quando o alerta sobe."),
        ("Casa na encosta", 8.8, "Só vira prioridade na cheia alta."),
    ]
    usadas = set()
    casas = []
    for nome, alvo, blurb in alvos:
        melhor = None
        for i, cota in enumerate(cotas):
            if i in usadas or cota is None:
                continue
            if dist[i] < 400 or dist[i] > 2200:
                continue
            score = abs(cota - alvo) * 40 + abs(dist[i] - 1100) / 80
            if melhor is None or score < melhor[0]:
                melhor = (score, i, cota)
        if melhor is None:
            continue
        _, i, cota = melhor
        usadas.add(i)
        pts, abrigo = rota_ate_abrigo(rf, i)
        casas.append({
            "id": f"c{len(casas)+1}",
            "nome": nome,
            "blurb": blurb,
            "lat": round(rf["nos"][i][0], 6),
            "lon": round(rf["nos"][i][1], 6),
            "cota_hand_m": round(float(cota), 1),
            "dist_m": round(dist[i]),
            "min_idoso": round(dist[i] / VEL_IDOSO / 60),
            "abrigo": abrigo["nome"],
            "abrigo_lat": abrigo["lat"],
            "abrigo_lon": abrigo["lon"],
            "rota": pts,
        })
    return casas


def _rf_mod():
    p = Path(__file__).resolve().parent / "gerar_rota_fuga_ruas.py"
    spec = importlib.util.spec_from_file_location("rota_fuga_ruas", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _simplifica(pts, eps=0.00008):
    if len(pts) < 4:
        return pts
    line = LineString([(p[1], p[0]) for p in pts])
    if line.length == 0:
        return pts
    s = line.simplify(eps)
    return [[round(y, 6), round(x, 6)] for x, y in s.coords]


def _dijkstra_casas(mod, osm, abrigos, casas, hand, remover):
    cfg = mod.CIDADES["mucum"]
    mancha, _nn = mod.carrega_mancha(cfg, max(hand, 0.01) if hand > 0 else 0.0)
    G, _n_flood = mod.monta_grafo(osm, mancha)
    if remover:
        G.remove_edges_from([(a, b) for a, b, d in G.edges(data=True) if d.get("alaga")])
    fontes = {}
    if G.number_of_edges() > 0:
        for a in abrigos:
            gn = mod.snap(G, a["lon"], a["lat"])
            if gn in G:
                fontes[gn] = a
    paths = {}
    if fontes:
        try:
            _dist, paths = nx.multi_source_dijkstra(G, set(fontes), weight="peso")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            paths = {}
    out = {}
    for c in casas:
        gn = mod.snap(G, c["lon"], c["lat"]) if G.number_of_nodes() else None
        rec = None
        if gn is not None and gn in paths:
            rec = _caminho_para_rec(G, fontes, paths[gn])
        if rec is None:
            rec = {"isolada": True, "pts": [[c["lat"], c["lon"]]],
                   "dist_m": None, "agua_m": 0, "abrigo": None}
        rec["hand"] = hand
        out[c["id"]] = rec
    return out


def _caminho_para_rec(G, fontes, caminho):
    pts = [
        [round(G.nodes[n]["lat"], 6), round(G.nodes[n]["lon"], 6)]
        for n in reversed(caminho)
    ]
    dr = ag = 0.0
    for x, y in zip(caminho, caminho[1:]):
        dr += G[x][y]["comp"]
        ag += G[x][y]["comp"] * G[x][y].get("alaga", False)
    ab = fontes[caminho[0]]
    return {
        "isolada": False,
        "pts": _simplifica(pts),
        "dist_m": round(dr),
        "agua_m": round(ag),
        "abrigo": ab["nome"],
        "abrigo_lat": ab["lat"],
        "abrigo_lon": ab["lon"],
    }


def anexa_rotas(casas, serie):
    """Rota seca (arestas da mancha RNA removidas) e rota de fuga (só penalidade)."""
    mod = _rf_mod()
    cfg = mod.CIDADES["mucum"]
    print("carregando OSM e recalculando Dijkstra por nível da RNA...")
    osm = mod.baixa_osm(cfg)
    abrigos = mod.carrega_abrigos(cfg)
    hands = sorted({round(max(0.0, s["rna_cm"] / 100.0 - ZERO_REGUA) / PASSO) * PASSO for s in serie})
    extra = [i * PASSO for i in range(0, 29)]  # 0 .. 14 m, para o salto da RNA não pular o desvio
    hands = sorted(set(hands) | set(extra))

    seca = {c["id"]: [] for c in casas}
    fuga = {c["id"]: [] for c in casas}
    for h in hands:
        print(f"  HAND {h:.1f} m")
        for c_id, rec in _dijkstra_casas(mod, osm, abrigos, casas, h, True).items():
            seca[c_id].append(rec)
        for c_id, rec in _dijkstra_casas(mod, osm, abrigos, casas, h, False).items():
            fuga[c_id].append(rec)

    for c in casas:
        c["rotas_seca"] = seca[c["id"]]
        c["rotas_fuga"] = fuga[c["id"]]
        base = next((r for r in seca[c["id"]] if not r.get("isolada") and r.get("pts")), None)
        if base is None:
            base = next((r for r in fuga[c["id"]] if not r.get("isolada")), None)
        if base:
            c["rota"] = base["pts"]
            c["dist_m"] = base["dist_m"]
            c["min_idoso"] = round((base["dist_m"] or 0) / VEL_IDOSO / 60)
            c["abrigo"] = base["abrigo"] or c["abrigo"]
            c["abrigo_lat"] = base.get("abrigo_lat", c["abrigo_lat"])
            c["abrigo_lon"] = base.get("abrigo_lon", c["abrigo_lon"])
        seca_ok = [r for r in seca[c["id"]] if not r.get("isolada")]
        corte = next((r["hand"] for r in seca[c["id"]] if r.get("isolada") and r["hand"] > 0), None)
        ultimo = seca_ok[-1] if seca_ok else None
        extra = f", rota seca até HAND {ultimo['hand']} m" if ultimo else ", sem rota seca"
        if corte is not None:
            extra += f", cortada a partir de {corte} m"
        print(f"  {c['nome']}: {c['min_idoso']} min -> {c['abrigo']}{extra}")
    return casas


def _lookup_rota(arr, hand):
    best = arr[0]
    for r in arr:
        if r["hand"] <= hand + 0.05:
            best = r
    return best


def serie_rna():
    html = PREVISAO.read_text(encoding="utf-8")
    m = re.search(r'<script id="event-data" type="application/json">(.*?)</script>', html, re.S)
    ev = json.loads(m.group(1))[EVENTO]
    out = []
    for row in ev["series"]:
        t, obs, rna = row[0], row[1], row[2]
        out.append({"t": t, "obs_cm": obs, "rna_cm": rna})
    return out, ev.get("label", EVENTO)


def build_html(doc):
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return _TEMPLATE.replace("__DADOS__", payload)


_TEMPLATE = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Estudo de caso — prioridade de evacuação · Muçum</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 html,body{height:100%;margin:0}
 body{font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#12211b;background:#0e1612}
 #map{position:fixed;inset:0}
 .card{position:absolute;z-index:500;top:12px;right:12px;width:360px;max-width:calc(100vw - 24px);
   background:#fff;border-radius:14px;box-shadow:0 8px 28px rgba(0,0,0,.28);overflow:hidden}
 .card h1{font:650 16px Georgia,serif;margin:0;padding:14px 16px 4px}
 .kicker{padding:0 16px;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:#5b6b62;font-weight:700}
 .body{padding:8px 16px 14px}
 .clock{font-variant-numeric:tabular-nums;font-size:13px;color:#5b6b62;margin:0 0 8px}
 .rna{background:#fff6ee;border:1px solid #f0d3b3;border-radius:10px;padding:9px 11px;margin:0 0 10px}
 .rna .big{font-size:28px;font-weight:800;color:#e8730c;letter-spacing:-.03em;line-height:1}
 .rna .big small{font-size:13px;font-weight:600;color:#a8650f}
 .rna .sub{font-size:12px;color:#7a5b00;margin-top:3px}
 .pills{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 10px}
 .pill{font-size:11px;font-weight:700;border-radius:999px;padding:3px 8px;background:#f2f4f3;color:#5b6b62}
 .pill.on{color:#fff}
 .fila h2{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#5b6b62;margin:8px 0 6px}
 .casa{display:flex;gap:8px;align-items:flex-start;border:1px solid #e6ece9;border-radius:10px;padding:8px 9px;margin:0 0 6px}
 .casa.sair,.casa.atencao{border-color:#f0c98a;background:#fff8ee}
 .casa.urgente{border-color:#f2b8b2;background:#fdecea}
 .casa.alagada{border-color:#9bb8e0;background:#eef4fb}
 .casa.isolada{border-color:#7a1f1f;background:#fde8e8}
 .casa.fuga{border-color:#c0392b;background:#fdecea}
 .casa.seguro{opacity:.72}
 .tag{font-size:10.5px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;border-radius:6px;padding:2px 6px;color:#fff;white-space:nowrap}
 .nm{font-weight:700;font-size:13px}
 .bl{font-size:11.5px;color:#5b6b62}
 .play{width:100%;margin-top:8px;border:0;border-radius:10px;background:#0f6b4a;color:#fff;font:700 13px inherit;padding:9px;cursor:pointer}
 body.gravando .play,.leaflet-control-zoom,.leaflet-control-attribution{display:none!important}
 .leg{position:absolute;z-index:500;bottom:12px;left:12px;background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.15);padding:8px 10px;font-size:12px}
 .leg i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
 .dot{width:22px;height:22px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.3)}
 .leaflet-tooltip.casa-tip{background:#fff;border:0;border-radius:8px;font:700 12px inherit;box-shadow:0 2px 8px rgba(0,0,0,.25);padding:3px 7px}
 .ord{font:800 15px/1 Georgia,serif;min-width:22px;text-align:center;color:#5b6b62}
 .casa:not(.seguro) .ord{color:#c0392b}
</style></head><body>
<div id="map"></div>
<div class="card">
  <div class="kicker">Estudo de caso · Muçum</div>
  <h1>A RNA fecha ruas — a rota desvia ou some</h1>
  <div class="body">
    <div class="clock" id="clock">—</div>
    <div class="rna"><div class="big" id="rna">— <small>RNA +12h</small></div>
      <div class="sub" id="rnasub">nível previsto na régua · quem essa mancha alcança evacua</div></div>
    <div class="pills" id="pills"></div>
    <div class="fila"><h2>Fila · quem a RNA alcança sai · a rota muda com a mancha</h2><div id="fila"></div></div>
    <button class="play" id="play">▶ Play</button>
  </div>
</div>
<div class="leg" id="leg"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D=__DADOS__;
const ZERO=D.meta.zero_regua_m, VEL=D.meta.vel_idoso_ms;
const CORES={seguro:'#1b7a5a',atencao:'#e3b100',urgente:'#e8730c',alagada:'#1e5fbf',alto:'#7a8a84',isolada:'#7a1f1f',fuga:'#c0392b'};
const ROT={seguro:'fora da mancha prevista',atencao:'sair nas próximas horas',urgente:'sair AGORA',alagada:'já na água',alto:'ponto alto'};
const ALARMES=[{id:'normal',l:'Normal',lim:0,c:'#5c6b63'},{id:'atencao',l:'Atenção 5 m',lim:500,c:'#e08a1e'},{id:'alerta',l:'Alerta 10 m',lim:1000,c:'#e8730c'},{id:'inundacao',l:'Inundação 18 m',lim:1800,c:'#c0392b'}];
function faixa(cm){return cm>=1800?'inundacao':cm>=1000?'alerta':cm>=500?'atencao':'normal';}
function hand(cm){return Math.max(0,(cm/100)-ZERO);}
function cls(cota, hNow, hRna){
  if(cota==null) return 'alto';
  if(cota<=hNow+0.05) return 'alagada';
  if(cota>hRna+0.05) return 'seguro';
  const cam=/*walk h*/ null;
  return (cota-hNow)<1.2 ? 'urgente' : 'atencao';
}
function clsCasa(c, hNow, hRna){
  const k=cls(c.cota_hand_m,hNow,hRna);
  if(k==='seguro'||k==='alto') return k;
  const camH=(c.dist_m/VEL)/3600;
  const dH=Math.max(0.05, hRna-hNow);
  const hAte=12*(c.cota_hand_m-hNow)/dH;
  if(k==='alagada') return k;
  return (hAte-camH)<0.4 ? 'urgente' : 'atencao';
}
if(location.search.includes('gravar')) document.body.classList.add('gravando');
const map=L.map('map',{zoomControl:false,attributionControl:false});
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Esri'}).addTo(map);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,opacity:.9}).addTo(map);
const linhas=D.edges.map(([a,c])=>{
  const A=D.nos[a],C=D.nos[c];
  const tem=D.cota_no[a]!=null||D.cota_no[c]!=null;
  return {pl:L.polyline([A,C],{weight:tem?3:1.4,opacity:tem?.9:.35}).addTo(map), a,c,tem};});
D.abrigos.forEach(a=>L.circleMarker([a.lat,a.lon],{radius:7,color:'#fff',weight:2,fillColor:'#0f6b4a',fillOpacity:1}).addTo(map).bindTooltip(a.nome.split(' ').slice(0,3).join(' '),{permanent:false}));
const rotas={}; const orig={}; const dots={};
const b=L.latLngBounds();
D.casas.forEach(c=>{
  (c.rota||[]).forEach(p=>b.extend(p));
  b.extend([c.lat,c.lon]); b.extend([c.abrigo_lat,c.abrigo_lon]);
  orig[c.id]=L.polyline(c.rota||[[c.lat,c.lon]],{color:'#ffffff',weight:3,opacity:0,dashArray:'7 8'}).addTo(map);
  rotas[c.id]=L.polyline(c.rota||[[c.lat,c.lon]],{color:'#0f8b46',weight:6,opacity:0}).addTo(map);
  const ic=L.divIcon({className:'',html:'<div class="dot" style="background:#1b7a5a"></div>',iconSize:[22,22],iconAnchor:[11,11]});
  dots[c.id]=L.marker([c.lat,c.lon],{icon:ic,zIndexOffset:900}).addTo(map).bindTooltip(c.nome,{permanent:true,direction:'right',offset:[12,0],className:'casa-tip'});
});
map.fitBounds(b,{paddingTopLeft:[16,16],paddingBottomRight:[390,70]});
setTimeout(()=>map.invalidateSize(),200);
document.getElementById('pills').innerHTML=ALARMES.map(a=>`<span class="pill" data-id="${a.id}">${a.l}</span>`).join('');
document.getElementById('leg').innerHTML='<b>Ruas e rotas</b><br>'+
  '<i style="background:#1b7a5a"></i>ainda fora da RNA<br>'+
  '<i style="background:#e3b100"></i>a RNA diz: vai alagar — sair<br>'+
  '<i style="background:#e8730c"></i>urgente (pouca margem)<br>'+
  '<i style="background:#1e5fbf"></i>já na água agora<br>'+
  '<i style="background:#0f8b46"></i>rota seca até o abrigo<br>'+
  '<i style="background:#c0392b"></i>só pela água / cortada';
function rotaEm(arr,h){if(!arr||!arr.length) return null; let b=arr[0]; for(const r of arr) if(r.hand<=h+0.05) b=r; return b;}
function pegaRota(c,hRna){
  const seca=rotaEm(c.rotas_seca,hRna), fuga=rotaEm(c.rotas_fuga,hRna);
  if(seca && !seca.isolada) return Object.assign({kind:'seca'},seca);
  if(fuga && !fuga.isolada) return Object.assign({kind:'fuga'},fuga);
  return {kind:'isolada',isolada:true,pts:[[c.lat,c.lon]],dist_m:null,abrigo:c.abrigo,agua_m:0};
}
function txtRota(c,k,rr){
  if(k==='seguro'||k==='alto') return 'rota ainda não necessária';
  if(rr.kind==='isolada') return 'rota cortada — não chega a pé ao abrigo';
  const min=Math.round((rr.dist_m||0)/VEL/60);
  const dest=(rr.abrigo||c.abrigo||'').split(' ').slice(0,3).join(' ');
  if(rr.kind==='fuga') return 'último corredor · '+min+' min → '+dest+(rr.agua_m>20?(' · '+Math.round(rr.agua_m)+' m na água'):'');
  const extra=(c.dist_m && rr.dist_m>c.dist_m*1.15)?(' · desvio +'+Math.round((rr.dist_m-c.dist_m)/VEL/60)+' min'):'';
  return min+' min → '+dest+extra;
}
let idx=0, playing=false, timer=null;
function fmtT(s){const m=String(s).match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return m?`${m[3]}/${m[2]} ${m[4]}:${m[5]}`:s;}
function fmtM(cm){return (cm/100).toFixed(2).replace('.',',')+' m';}
function render(i){
  idx=i; const s=D.serie[i], hNow=hand(s.obs_cm), hRna=hand(s.rna_cm);
  const f=faixa(s.rna_cm);
  document.getElementById('clock').textContent='Cheia mai/2024 · '+fmtT(s.t)+' · o que a RNA via daqui a 12h';
  document.getElementById('rna').innerHTML=fmtM(s.rna_cm)+' <small>RNA +12h</small>';
  document.getElementById('rnasub').textContent='agora na régua '+fmtM(s.obs_cm)+' · HAND previsto '+(hRna).toFixed(1)+' m';
  document.querySelectorAll('#pills .pill').forEach(p=>{
    const a=ALARMES.find(x=>x.id===p.dataset.id);
    const on=p.dataset.id==='normal'?f==='normal':ALARMES.findIndex(x=>x.id===p.dataset.id)<=ALARMES.findIndex(x=>x.id===f);
    p.classList.toggle('on',on); p.style.background=on?a.c:'#f2f4f3'; p.style.color=on?'#fff':'#5b6b62';
  });
  const cl=D.cota_no.map(c=>cls(c,hNow,hRna));
  const rank={seguro:0,alto:0,atencao:1,urgente:2,alagada:3};
  linhas.forEach(r=>{const k=rank[cl[r.a]]>=rank[cl[r.c]]?cl[r.a]:cl[r.c];
    r.pl.setStyle({color:r.tem?(CORES[k]||'#7a8a84'):'#5a6a64'});});
  const ranked=D.casas.slice().sort((a,b)=>a.cota_hand_m-b.cota_hand_m);
  let nFila=0;
  document.getElementById('fila').innerHTML=ranked.map(c=>{
    const k=clsCasa(c,hNow,hRna);
    const rr=pegaRota(c,hRna);
    const rotaFecha=rr.kind==='fuga'||rr.kind==='isolada';
    const naFila=(k!=='seguro'&&k!=='alto')||rotaFecha;
    if(naFila) nFila+=1;
    const vis=rr.kind==='isolada'?'isolada':(rr.kind==='fuga'?'fuga':k);
    const lab={seguro:'ainda seguro',atencao:'sair — RNA alcança',urgente:'SAIR AGORA',alagada:'já alagou',alto:'ponto alto',isolada:'ROTA CORTADA',fuga:'só pela água'}[vis];
    const ord=naFila?nFila+'º':'—';
    const cor=CORES[vis]||CORES[k];
    return `<div class="casa ${naFila?vis:'seguro'}">
      <div class="ord">${ord}</div>
      <div><span class="tag" style="background:${cor}">${lab}</span>
      <div class="nm">${c.nome}</div>
      <div class="bl">alaga em HAND ${c.cota_hand_m} m</div>
      <div class="bl">${txtRota(c,naFila?k:'seguro',rr)}</div></div></div>`;
  }).join('');
  D.casas.forEach(c=>{
    const k=clsCasa(c,hNow,hRna);
    const rr=pegaRota(c,hRna);
    const show=(k==='atencao'||k==='urgente'||k==='alagada'||rr.kind==='fuga'||rr.kind==='isolada');
    const desvia=show && (rr.kind!=='seca') && (c.rota||[]).length>1;
    orig[c.id].setLatLngs(c.rota||[[c.lat,c.lon]]);
    orig[c.id].setStyle({opacity:desvia?0.55:0});
    rotas[c.id].setLatLngs(rr.pts&&rr.pts.length?rr.pts:[[c.lat,c.lon]]);
    const corLinha=rr.kind==='isolada'?'#7a1f1f':rr.kind==='fuga'?'#c0392b':k==='urgente'?'#c0392b':'#0f8b46';
    rotas[c.id].setStyle({opacity:show?0.95:0,color:corLinha,dashArray:rr.kind==='isolada'?'5 7':null});
    const corDot=rr.kind==='isolada'?CORES.isolada:(rr.kind==='fuga'?CORES.fuga:CORES[k]);
    dots[c.id].setIcon(L.divIcon({className:'',html:`<div class="dot" style="background:${corDot}"></div>`,iconSize:[22,22],iconAnchor:[11,11]}));
  });
}
window.slideN=()=>D.serie.length;
window.slideGo=i=>{render(i);};
window.slideMeta=()=>D.serie[idx];
function tick(){ if(!playing) return; idx=(idx+1)%D.serie.length; render(idx); timer=setTimeout(tick,280); }
document.getElementById('play').onclick=()=>{playing=!playing; document.getElementById('play').textContent=playing?'⏸ Pause':'▶ Play'; if(playing) tick(); else clearTimeout(timer);};
render(0);
</script></body></html>
"""


def encode(frames, dest, holds=None, fps=FPS):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    dest.parent.mkdir(parents=True, exist_ok=True)
    lst = dest.with_suffix(".txt")
    lines = []
    for i, frame in enumerate(frames):
        dur = 1.0 / fps
        if holds and holds[i]:
            dur *= 3.5
        if i == 0:
            dur *= 2.5
        if i == len(frames) - 1:
            dur *= 6
        lines.append(f"file '{frame.resolve().as_posix()}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{frames[-1].resolve().as_posix()}'")
    lst.write_text("\n".join(lines), encoding="utf-8")
    subprocess.run(
        [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-vsync", "vfr", "-pix_fmt", "yuv420p", "-c:v", "libx264",
         "-crf", "20", "-movflags", "+faststart", str(dest)],
        check=True,
    )
    lst.unlink(missing_ok=True)


def gravar(html_path: Path, casas, serie):
    from playwright.sync_api import sync_playwright

    frames_dir = OUT / "_frames_estudo_caso_mucum"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    os.chdir(RAIZ)
    socketserver.ThreadingTCPServer.allow_reuse_address = True

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--hide-scrollbars"])
        page = browser.new_page(viewport=VIEW, device_scale_factor=1)
        page.goto(f"http://127.0.0.1:{PORT}/{html_path.name}?gravar=1", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_function("() => window.slideN && window.slideN() > 1", timeout=60000)
        page.wait_for_timeout(1500)
        n = page.evaluate("() => window.slideN()")
        print(f"gravando {n} quadros")
        frames = []
        money = None
        for i in range(n):
            page.evaluate("(i) => window.slideGo(i)", i)
            page.wait_for_timeout(200 if i else 800)
            path = frames_dir / f"f{i:04d}.png"
            page.screenshot(path=str(path), type="png")
            frames.append(path)
            meta = page.evaluate("() => window.slideMeta()")
            if money is None and meta and (meta.get("rna_cm") or 0) >= 1800:
                money = i
            print(f"  {i+1}/{n}  {meta.get('t')}  rna={meta.get('rna_cm')}")
        still_i = money if money is not None else min(36, n - 1)
        still = OUT / "animacao_mucum_estudo_caso_quadro.png"
        shutil.copy2(frames[still_i], still)
        browser.close()

    def kind_em(c, h):
        r = _lookup_rota(c.get("rotas_seca") or [{"hand": 0, "isolada": True}], h)
        if r and not r.get("isolada"):
            return ("seca", r.get("abrigo"), round((r.get("dist_m") or 0) / 80))
        r2 = _lookup_rota(c.get("rotas_fuga") or [{"hand": 0, "isolada": True}], h)
        if r2 and not r2.get("isolada"):
            return ("fuga", r2.get("abrigo"), round((r2.get("dist_m") or 0) / 80))
        return ("isolada", None, 0)

    def n_fila(s):
        h = max(0.0, s["rna_cm"] / 100 - ZERO_REGUA)
        return sum(c["cota_hand_m"] <= h + 0.05 for c in casas)

    holds = []
    last = None
    dois = None
    corte = None
    for i, s in enumerate(serie):
        h = max(0.0, s["rna_cm"] / 100 - ZERO_REGUA)
        cur = (n_fila(s), tuple(kind_em(c, h) for c in casas))
        holds.append(cur != last)
        if dois is None and n_fila(s) == 2:
            dois = i
        if corte is None and any(
            c["cota_hand_m"] <= h + 0.05 and kind_em(c, h)[0] != "seca" for c in casas
        ):
            corte = i
        last = cur
    if corte is not None:
        shutil.copy2(frames[corte], still)
    elif dois is not None:
        shutil.copy2(frames[dois], still)

    full = OUT / "animacao_mucum_estudo_caso.mp4"
    encode(frames, full, holds=holds)
    COPY.mkdir(parents=True, exist_ok=True)
    for src in (full, still):
        shutil.copy2(src, COPY / src.name)
        print("copiado", COPY / src.name)
    print("OK", full)
    print(" ", still)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", action="store_true")
    args = ap.parse_args()

    print("carregando rede e cotas HAND...")
    rf = json.loads(RF.read_text(encoding="utf-8"))
    cotas = cotas_por_no(rf["nos"])
    casas = escolhe_casas(rf, cotas)
    serie, label = serie_rna()
    print(f"série {label}: {len(serie)} passos")
    casas = anexa_rotas(casas, serie)

    doc = {
        "meta": {
            "municipio": "Muçum",
            "zero_regua_m": ZERO_REGUA,
            "vel_idoso_ms": VEL_IDOSO,
            "evento": label,
            "horizonte": "12h",
        },
        "nos": rf["nos"],
        "edges": [[a, b] for a, b, *_ in rf["edges"]],
        "cota_no": cotas,
        "abrigos": [{"lat": a["lat"], "lon": a["lon"], "nome": a["nome"]} for a in rf["abrigos"]],
        "casas": casas,
        "serie": serie,
    }
    SAIDA_HTML.write_text(build_html(doc), encoding="utf-8")
    print("->", SAIDA_HTML)
    fila_path = RAIZ / "assets" / "data" / "rota_fuga" / "fila_evacuacao_mucum.json"
    fila_path.parent.mkdir(parents=True, exist_ok=True)
    fila_path.write_text(json.dumps({
        "meta": {
            "municipio": "Muçum",
            "zero_regua_m": ZERO_REGUA,
            "vel_idoso_ms": VEL_IDOSO,
        },
        "abrigos": [{"lat": a["lat"], "lon": a["lon"], "nome": a["nome"]} for a in rf["abrigos"]],
        "casas": [{k: c[k] for k in (
            "id", "nome", "blurb", "lat", "lon", "cota_hand_m", "dist_m",
            "min_idoso", "abrigo", "abrigo_lat", "abrigo_lon", "rota",
            "rotas_seca", "rotas_fuga",
        ) if k in c} for c in casas],
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("->", fila_path)
    if args.video:
        gravar(SAIDA_HTML, casas, serie)


if __name__ == "__main__":
    main()
