#!/usr/bin/env python3
"""UI v3 for the Taquari-Antas / Muçum research platform."""

from __future__ import annotations

import json
from typing import Any


def render_platform_html(feed: dict[str, Any]) -> str:
    blob = json.dumps(feed, ensure_ascii=False, separators=(",", ":")).replace("</", "<\/")
    return TEMPLATE.replace("__DATA__", blob)


TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PREVINE · Taquari–Antas · Muçum</title>
<meta name="description" content="Plataforma de pesquisa hidrológica da bacia Taquari–Antas com chuva espacial IFS e monitoramento de Muçum."/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Source+Serif+4:opsz,wght@8..60,650;8..60,750&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{
  --bg:#edf3ef; --panel:#fbfdfb; --panel2:#f4f8f5; --ink:#10241b; --muted:#607168;
  --line:#d4e0d8; --green:#176149; --green2:#0d4534; --blue:#225d8d; --amber:#98661d;
  --red:#9a3c32; --shadow:0 10px 32px rgba(15,45,33,.08); --r:18px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:linear-gradient(180deg,#e7f0ea 0,#f7f9f7 36rem,#f5f4ef 100%);color:var(--ink);font:14px/1.5 Inter,system-ui,sans-serif}
a{color:var(--green);text-decoration:none}
.wrap{max-width:1320px;margin:auto;padding:18px 18px 46px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 14px;border:1px solid rgba(255,255,255,.55);background:rgba(250,253,251,.82);backdrop-filter:blur(14px);border-radius:16px;box-shadow:var(--shadow);position:sticky;top:10px;z-index:1000}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:-.01em}
.brand-mark{width:34px;height:34px;border-radius:11px;background:linear-gradient(145deg,var(--green2),#3c8a69);display:grid;place-items:center;color:white;font-weight:800}
.nav{display:flex;gap:5px;flex-wrap:wrap}
.nav a{padding:7px 10px;border-radius:9px;color:#375047;font-size:12px;font-weight:650}
.nav a:hover{background:#e8f1eb}
.hero{padding:34px 4px 18px;display:grid;grid-template-columns:1.35fr .8fr;gap:22px;align-items:end}
.hero h1{margin:0;font:750 clamp(2rem,4vw,3.5rem)/1.02 "Source Serif 4",Georgia,serif;letter-spacing:-.035em}
.hero h1 span{color:var(--green)}
.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.12em;font-weight:800;color:var(--green);margin-bottom:10px}
.hero p{max-width:74ch;color:var(--muted);font-size:15px;margin:13px 0 0}
.status-stack{display:grid;gap:9px}
.status{border:1px solid var(--line);background:rgba(255,255,255,.75);border-radius:14px;padding:12px 14px;display:flex;gap:10px;align-items:flex-start}
.dot{width:10px;height:10px;border-radius:50%;margin-top:5px;flex:0 0 auto}
.dot.ok{background:#2e8b66}.dot.wait{background:#cc8a25}.dot.off{background:#a74a41}
.status strong{display:block;font-size:13px}.status span{color:var(--muted);font-size:12px}
.notice{border:1px solid #e4c997;background:#fff8e9;border-radius:15px;padding:13px 15px;color:#5f4c29;margin:0 0 16px}
.notice strong{color:#6f4a0d}
.grid{display:grid;gap:14px}.metrics{grid-template-columns:repeat(4,1fr)}
.card{background:rgba(252,254,252,.94);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);padding:16px}
.metric .k{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.metric .v{font-size:28px;font-weight:800;letter-spacing:-.035em;margin-top:4px;font-variant-numeric:tabular-nums}
.metric .s{font-size:12px;color:var(--muted);margin-top:2px}
.section{margin-top:14px;scroll-margin-top:86px}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:15px;margin:0 2px 9px}
.section-head h2{margin:0;font:700 1.35rem/1.1 "Source Serif 4",Georgia,serif}
.section-head p{margin:0;color:var(--muted);font-size:12px;max-width:68ch;text-align:right}
.two{grid-template-columns:minmax(0,1.55fr) minmax(280px,.7fr)}
#map{height:min(68vh,640px);min-height:440px;border-radius:14px;border:1px solid var(--line);overflow:hidden}
.map-tools{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:9px}
.chip{border:1px solid var(--line);background:white;border-radius:999px;padding:6px 10px;font-size:12px;color:#4f6359}
.chip strong{color:var(--ink)}
.legend{background:rgba(255,255,255,.95);border:1px solid var(--line);border-radius:12px;padding:8px 10px;box-shadow:var(--shadow);font-size:11px;line-height:1.5}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.side-list{display:grid;gap:8px;max-height:360px;overflow:auto}
.row{border:1px solid var(--line);background:#fff;border-radius:12px;padding:10px 11px}
.row .title{display:flex;justify-content:space-between;gap:8px;font-weight:700}
.row .meta{font-size:11px;color:var(--muted);margin-top:3px}
.row.warn{border-left:4px solid var(--amber)}
.row.ok{border-left:4px solid var(--green)}
.inspector{margin-top:12px;border:1px dashed #b9c9bf;background:var(--panel2);border-radius:13px;padding:11px}
.inspector h3{margin:0 0 4px;font-size:14px}.inspector p{margin:0;color:var(--muted);font-size:12px}
.rain-summary{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.rain-box{padding:12px;border-radius:13px;background:#f2f7f4;border:1px solid #d6e3da}
.rain-box b{display:block;font-size:20px}.rain-box span{font-size:11px;color:var(--muted)}
.table-wrap{overflow:auto}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:8px 7px;border-bottom:1px solid #e1e8e3;text-align:left;white-space:nowrap}
th{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.callout{border-radius:14px;padding:14px;border:1px solid #e7d6ad;background:#fffbef}
.callout h3{margin:0 0 5px;font-size:14px;color:#725018}.callout p{margin:0;color:#665534;font-size:12px}
.kpi-line{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px}
.kpi-line span{background:#f1f6f3;border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:12px}
.kpi-line b{font-variant-numeric:tabular-nums}
.panel-title{font:700 1rem "Source Serif 4",Georgia,serif;margin:0 0 7px}
.audit{border-left:4px solid #7b8790}
.skill-table tr.bad td:first-child{color:var(--red);font-weight:800}
.skill-table tr.good td:first-child{color:var(--green);font-weight:800}
.links{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.links a{border:1px solid #cbdad1;background:#f7faf8;padding:6px 9px;border-radius:999px;font-size:11px;font-weight:700}
.foot{color:var(--muted);font-size:11px;margin-top:14px}
@media(max-width:920px){.hero{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}.section-head{align-items:start;flex-direction:column}.section-head p{text-align:left}.nav{display:none}}
@media(max-width:560px){.wrap{padding:10px 10px 34px}.topbar{top:6px}.metrics{grid-template-columns:1fr}.hero{padding-top:24px}#map{min-height:420px}.rain-summary{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div class="brand"><span class="brand-mark">P</span><span>PREVINE · HEC/REC</span></div>
    <nav class="nav">
      <a href="#visao">Visão geral</a><a href="#chuva">Chuva</a><a href="#rio">Rio</a><a href="#mapa">Mapa</a><a href="#calibracao">Calibração</a><a href="#dados">Dados</a>
    </nav>
  </div>

  <header class="hero" id="visao">
    <div>
      <div class="eyebrow">bacia Taquari–Antas (G040) · pesquisa</div>
      <h1>Chuva na bacia, <span>Muçum</span> no foco.</h1>
      <p>Visão integrada da bacia G040, do campo espacial ECMWF/IFS e do monitoramento em Muçum. A plataforma separa claramente <strong>chuva observada/prevista</strong>, <strong>telemetria do rio</strong>, <strong>calibração</strong> e <strong>saídas ainda experimentais</strong>.</p>
    </div>
    <div class="status-stack">
      <div class="status"><span class="dot ok"></span><div><strong>Chuva espacial IFS</strong><span id="statusRain">carregando…</span></div></div>
      <div class="status"><span class="dot wait"></span><div><strong>Chuva → vazão</strong><span>integração espacial completa ainda pendente no gêmeo HEC</span></div></div>
      <div class="status"><span class="dot ok"></span><div><strong>Escopo</strong><span>pesquisa · não é alerta oficial</span></div></div>
    </div>
  </header>

  <div class="notice"><strong>Importante:</strong> o antigo ΔN do gêmeo HEC baseado em poucos pontos de chuva não é mais mostrado como previsão atual. Ele permanece apenas para auditoria até que o modelo chuva–vazão consuma o campo espacial completo da bacia.</div>

  <section class="grid metrics" id="basinMetrics">
    <article class="card metric"><div class="k">Área G040</div><div class="v" id="mArea">—</div><div class="s">km² · 7 UGs</div></article>
    <article class="card metric"><div class="k">Células IFS na bacia de Muçum</div><div class="v" id="mCells">—</div><div class="s">grade 0,25° preservada</div></article>
    <article class="card metric"><div class="k">Chuva prevista por célula</div><div class="v" id="mRainRange">—</div><div class="s">mínimo–máximo em 120 h</div></article>
    <article class="card metric"><div class="k">Volume de chuva na bacia</div><div class="v" id="mVolume">—</div><div class="s">hm³ em 120 h</div></article>
  </section>

  <section class="section" id="chuva">
    <div class="section-head"><h2>Chuva espacial · ECMWF/IFS</h2><p>Todas as células que interceptam a bacia contribuinte até Muçum são mantidas separadas. A profundidade equivalente da bacia é apenas uma conferência volumétrica.</p></div>
    <div class="grid two">
      <article class="card">
        <div class="rain-summary">
          <div class="rain-box"><b id="rMinMax">—</b><span>faixa espacial do acumulado 120 h</span></div>
          <div class="rain-box"><b id="rMedian">—</b><span>mediana das células</span></div>
          <div class="rain-box"><b id="rCoverage">—</b><span>cobertura do polígono da bacia</span></div>
          <div class="rain-box"><b id="rWindow">—</b><span>janela da rodada</span></div>
        </div>
        <div class="links" id="rainLinks"></div>
      </article>
      <article class="card">
        <h3 class="panel-title">Células mais chuvosas</h3>
        <div class="table-wrap"><table><thead><tr><th>Célula</th><th>mm/120h</th><th>área na bacia</th><th>volume</th></tr></thead><tbody id="wetCells"></tbody></table></div>
      </article>
    </div>
  </section>

  <section class="section" id="rio">
    <div class="section-head"><h2>Rio · Muçum</h2><p>Telemetria atual pode ser mostrada. A previsão futura de nível fica explicitamente bloqueada até a chuva espacial entrar no modelo chuva–vazão.</p></div>
    <div class="grid metrics" id="productMetrics">
      <article class="card metric"><div class="k">Nível observado</div><div class="v" id="obsLevel">—</div><div class="s" id="obsWhen">telemetria</div></article>
      <article class="card metric"><div class="k">Previsão ΔN</div><div class="v">bloqueada</div><div class="s">aguardando integração espacial</div></article>
      <article class="card metric"><div class="k">Forçante espacial</div><div class="v" id="spatialGate">—</div><div class="s">campo IFS completo</div></article>
      <article class="card metric"><div class="k">Atualização da plataforma</div><div class="v" style="font-size:18px" id="updatedAt">—</div><div class="s">horário de Brasília</div></article>
    </div>
    <div class="callout" style="margin-top:14px">
      <h3>Por que o hidrograma futuro não aparece como “válido”?</h3>
      <p>O forward legado ainda usa chuva proxy em poucos pontos. Isso pode ignorar núcleos importantes nas cabeceiras. O resultado antigo fica disponível abaixo apenas como diagnóstico técnico, não como previsão espacial da bacia.</p>
    </div>
  </section>

  <section class="section" id="mapa">
    <div class="section-head"><h2>Mapa · bacia, chuva e rede</h2><p>Camada principal: campo espacial IFS. As 7 UGs, âncoras e Rede G040 podem ser ligadas/desligadas.</p></div>
    <div class="grid two" id="basinMapSection">
      <article class="card">
        <div class="map-tools"><span class="chip"><strong>fill</strong> = chuva 120 h</span><span class="chip"><strong>contorno</strong> = UGs</span><span class="chip"><strong>pontos</strong> = monitoramento</span></div>
        <div id="map"></div>
        <div class="inspector" id="pointInspector"><h3 id="inspectorTitle">Detalhes</h3><p id="inspectorText">Clique em uma célula de chuva, UG ou ponto de monitoramento.</p></div>
      </article>
      <article class="card">
        <h3 class="panel-title">Inventário por UG</h3>
        <div class="side-list" id="ugInventory"></div>
        <div id="corridorCard" style="margin-top:14px">
          <h3 class="panel-title">Produto gêmeo · corredor até Muçum</h3>
          <p style="margin:0;color:var(--muted);font-size:12px">Alto + Prata + Carreiro + Médio. Guaporé, Forqueta e Baixo permanecem no mapa da bacia, mas fora do balanço do gêmeo até Muçum.</p>
        </div>
      </article>
    </div>
  </section>

  <section class="section" id="calibracao">
    <div class="section-head"><h2>Calibração e validação</h2><p>Os replays históricos continuam visíveis para avaliar desempenho, mas não substituem uma previsão atual.</p></div>
    <article class="card">
      <div class="kpi-line" id="skillSummary"></div>
      <div class="table-wrap"><table class="skill-table"><thead><tr><th>Evento</th><th>Chuva</th><th>NSE</th><th>|erro| ΔN</th><th>erro ΔN</th><th>erro pico Q</th></tr></thead><tbody id="skillRows"></tbody></table></div>
    </article>
  </section>

  <section class="section" id="dados">
    <div class="section-head"><h2>Dados e rastreabilidade</h2><p>O que está pronto, o que é legado e o que ainda falta para uma rodada chuva–vazão espacialmente coerente.</p></div>
    <div class="grid two">
      <article class="card">
        <h3 class="panel-title">Estado do pipeline</h3>
        <div class="side-list" id="pipeline"></div>
      </article>
      <article class="card audit">
        <h3 class="panel-title">Diagnóstico legado do gêmeo HEC</h3>
        <div id="legacyBox" style="color:var(--muted);font-size:12px"></div>
        <div class="links" id="artifactLinks"></div>
      </article>
    </div>
    <p class="foot">PREVINE Taquari–Antas · pesquisa. A página não emite alerta, ordem de evacuação ou decisão operacional.</p>
  </section>
</div>

<script>
const DATA=__DATA__;
const $=id=>document.getElementById(id);
function fmt(v,d=0){if(v===null||v===undefined||Number.isNaN(Number(v)))return"—";return Number(v).toLocaleString("pt-BR",{minimumFractionDigits:d,maximumFractionDigits:d})}
function brt(ts){if(!ts)return"—";try{return new Date(ts).toLocaleString("pt-BR",{timeZone:"America/Sao_Paulo",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}catch(e){return ts}}
function pct(v){return v==null?"—":fmt(Number(v)*100,0)+"%"}
const sr=DATA.spatial_rain||{}, sum=DATA.summary||{}, basin=DATA.basin||{}, skill=((DATA.products||{}).hindcast_skill)||{}, inv=((DATA.spatial||{}).inventory_stats)||{};
$("mArea").textContent=fmt(basin.area_km2,0);
$("mCells").textContent=fmt(sr.intersecting_cells,0);
$("mRainRange").textContent=fmt(sr.cell_total_min_mm,1)+"–"+fmt(sr.cell_total_max_mm,1)+" mm";
$("mVolume").textContent=fmt(sr.total_rain_volume_hm3,1);
$("rMinMax").textContent=fmt(sr.cell_total_min_mm,1)+"–"+fmt(sr.cell_total_max_mm,1)+" mm";
$("rMedian").textContent=fmt(sr.cell_total_median_mm,1)+" mm";
$("rCoverage").textContent=pct(sr.coverage_ratio);
$("rWindow").textContent=(sr.window&&sr.window.start_utc?brt(sr.window.start_utc)+" → "+brt(sr.window.end_utc):"—");
$("statusRain").textContent=sr.available?(fmt(sr.intersecting_cells,0)+" células · "+pct(sr.coverage_ratio)+" da bacia"):"indisponível";
$("spatialGate").textContent=sr.available?"pronta":"indisponível";
$("updatedAt").textContent=brt(DATA.generated_at_utc);
$("obsLevel").textContent=sum.observed_stage_cm!=null?fmt(sum.observed_stage_cm/100,2)+" m":"—";
$("obsWhen").textContent=sum.observed_at_utc?("observado em "+brt(sum.observed_at_utc)):"telemetria indisponível";

const wet=$("wetCells");(sr.wettest_cells||[]).forEach(c=>{const tr=document.createElement("tr");tr.innerHTML="<td>"+c.cell_id+"</td><td><b>"+fmt(c.total_120h_mm,1)+"</b></td><td>"+fmt(c.overlap_km2,0)+" km²</td><td>"+fmt(c.rain_volume_hm3,2)+" hm³</td>";wet.appendChild(tr)});
const rainLinks=[["Mapa PNG",sr.png],["Células CSV",sr.cells_csv],["Horário CSV",sr.hourly_csv],["GeoJSON",sr.geojson]];
rainLinks.forEach(([t,u])=>{if(!u)return;const a=document.createElement("a");a.href=u;a.textContent=t;$("rainLinks").appendChild(a)});

function renderUgInventory(){
 const by=inv.by_ug||{};$("ugInventory").innerHTML="";
 Object.keys(by).sort((a,b)=>(by[a].in_twin_domain?0:1)-(by[b].in_twin_domain?0:1)||a.localeCompare(b,"pt-BR")).forEach(name=>{
  const r=by[name],d=document.createElement("div");d.className="row "+(r.in_twin_domain?"ok":"warn");
  d.innerHTML="<div class='title'><span>"+name+"</span><span>"+(r.in_twin_domain?"gêmeo":"inventário")+"</span></div><div class='meta'>~"+fmt(r.area_km2_approx,0)+" km² · flu "+fmt(r.flu,0)+" · chuva "+fmt(r.rain,0)+" · total "+fmt(r.total,0)+"</div>";
  $("ugInventory").appendChild(d)
 })
}
renderUgInventory();

function showInspector(title,text){$("inspectorTitle").textContent=title;$("inspectorText").textContent=text}
function renderSkill(){
 const s=skill.summary||{};
 $("skillSummary").innerHTML="<span>eventos <b>"+fmt(s.n_scored,0)+"</b></span><span>NSE médio <b>"+fmt(s.mean_nse_loo,2)+"</b></span><span>erro ΔN médio <b>"+fmt((s.mean_rise_n_rel_err||0)*100,0)+"%</b></span><span>erro pico Q médio <b>"+fmt((s.mean_peak_q_rel_err||0)*100,0)+"%</b></span>";
 const tb=$("skillRows");(skill.events||[]).forEach(e=>{const tr=document.createElement("tr");tr.className=(e.tag||"").includes("best")?"good":((e.tag||"").includes("worst")||e.tag==="negative_nse"?"bad":"");tr.innerHTML="<td>"+(e.event_id||"—")+"</td><td>"+fmt(e.rain_mm_aw,0)+" mm</td><td>"+fmt(e.nse_loo,2)+"</td><td>"+fmt(e.rise_n_abs_err_cm,0)+" cm</td><td>"+fmt((e.rise_n_rel_err||0)*100,0)+"%</td><td>"+fmt((e.peak_q_rel_err||0)*100,0)+"%</td>";tb.appendChild(tr)})
}
renderSkill();

const pipe=$("pipeline");((DATA.automation||{}).steps_pt||[]).forEach((s,i)=>{const d=document.createElement("div");d.className="row "+(i===1?"warn":"ok");d.innerHTML="<div class='title'><span>"+(i+1)+". "+s+"</span></div>";pipe.appendChild(d)});
const legacy=DATA.legacy_headline||{}, lp=legacy.primary||{}, fwd=((DATA.products||{}).forward_5d)||{};
$("legacyBox").innerHTML="<p style='margin-top:0'><strong>Não usar como previsão atual.</strong> Forçante: "+(fwd.input_policy||"legacy_point_proxy")+".</p><p>Último diagnóstico legado: ΔN "+fmt(lp.rise_cm,0)+" cm · N pico "+fmt(lp.peak_anchored_cm,0)+" cm · "+(lp.peak_time_utc?brt(lp.peak_time_utc):"—")+".</p><p>"+(fwd.blocking_reason_pt||"")+"</p>";
const local=((DATA.where_results_go||{}).local)||{};
[["Forward legado",local.forward_html],["Replay",local.live_eval_html],["Hindcast",local.hindcast_html],["Feed JSON",local.platform_json],["Mapa UGs",local.mapa_subbacias]].forEach(([t,u])=>{if(!u)return;const a=document.createElement("a");a.href=u;a.textContent=t;$("artifactLinks").appendChild(a)});

const bb=((((DATA.spatial||{}).basin_framing)||{}).g040_bbox_latlon)||[[-29.95,-52.64],[-28.18,-49.93]];
const map=L.map("map",{scrollWheelZoom:true}).fitBounds(bb,{padding:[20,20]});
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
const rainLayer=L.layerGroup().addTo(map), ugLayer=L.layerGroup().addTo(map), anchorLayer=L.layerGroup().addTo(map), networkLayer=L.layerGroup(), fozLayer=L.layerGroup();

function rainColor(mm,max){const x=max?Math.max(0,Math.min(1,Number(mm||0)/max)):0; if(x<.2)return"#dceee5";if(x<.4)return"#a9d5be";if(x<.6)return"#68ad88";if(x<.8)return"#2d805e";return"#0f523b"}
async function loadSpatialRain(){
 if(!sr.geojson)return;try{const res=await fetch(sr.geojson);if(!res.ok)return;const gj=await res.json(),max=Number(sr.cell_total_max_mm||1);
 L.geoJSON(gj,{style:f=>({color:"#fff",weight:.7,fillColor:rainColor((f.properties||{}).total_120h_mm,max),fillOpacity:.64}),onEachFeature:(f,l)=>{const p=f.properties||{};l.on("click",()=>showInspector(p.cell_id||"Célula IFS","Chuva "+fmt(p.total_120h_mm,1)+" mm/120h · interseção "+fmt(p.overlap_km2,0)+" km² · volume "+fmt(p.rain_volume_hm3,2)+" hm³"));l.bindTooltip(fmt(p.total_120h_mm,1)+" mm")}}).addTo(rainLayer)}catch(e){}
}
async function loadUgs(){
 const path=((DATA.spatial||{}).ug_geojson)||"ugs_g040.geojson";try{const res=await fetch(path);if(!res.ok)return;const gj=await res.json();L.geoJSON(gj,{style:{color:"#204f3c",weight:1.25,fillOpacity:0},onEachFeature:(f,l)=>{const p=f.properties||{},n=p.sub_bacia||p.nome||"UG";l.on("click",()=>showInspector(n,"Unidade de gestão da bacia G040 · área aproximada "+fmt(p.area_km2_approx,0)+" km²"));l.bindTooltip(n)}}).addTo(ugLayer)}catch(e){}
}
function loadAnchors(){(((DATA.spatial||{}).anchors)||[]).forEach(a=>{const c=a.role==="target"?"#0e5b42":a.role==="rain"?"#2a6f9d":"#6b7780";const m=L.circleMarker([a.lat,a.lon],{radius:a.role==="target"?5:3.5,color:"#fff",weight:1,fillColor:c,fillOpacity:.9}).on("click",()=>showInspector(a.label||a.name,(a.role_pt||a.role)+" · "+(a.code||"")+(a.ug?" · "+a.ug:"")));m.bindTooltip(a.label||a.name);m.addTo(anchorLayer)})}
function loadNetwork(){const net=((DATA.spatial||{}).basin_network)||{};(net.features||[]).forEach(f=>{const p=f.properties||{},c=(f.geometry||{}).coordinates||[];if(c.length<2)return;L.circleMarker([c[1],c[0]],{radius:2,color:"#ffffff88",weight:.4,fillColor:p.kind==="rain"?"#3b7ca6":"#7b8b82",fillOpacity:.55}).on("click",()=>showInspector(p.name||p.code,(p.kind==="rain"?"chuva":"flu")+" · "+(p.ug||"")+" · "+(p.code||""))).addTo(networkLayer)})}
async function loadFozes(){const path=(DATA.spatial||{}).fozes_geojson;if(!path)return;try{const res=await fetch(path);if(!res.ok)return;const gj=await res.json();L.geoJSON(gj,{pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:3.5,color:"#fff",weight:1,fillColor:"#a77a2d",fillOpacity:.8})}).addTo(fozLayer)}catch(e){}}
loadSpatialRain();loadUgs();loadAnchors();loadNetwork();loadFozes();
L.control.layers(null,{"Chuva IFS espacial":rainLayer,"UGs G040":ugLayer,"Âncoras":anchorLayer,"Rede G040":networkLayer,"Fozes BHO6":fozLayer},{collapsed:false}).addTo(map);
const leg=L.control({position:"bottomright"});leg.onAdd=()=>{const d=L.DomUtil.create("div","legend");d.innerHTML="<div><i style='background:#dceee5'></i>menor chuva</div><div><i style='background:#68ad88'></i>chuva intermediária</div><div><i style='background:#0f523b'></i>maior chuva</div><div style='margin-top:4px'>IFS 0,25° · 120 h</div>";return d};leg.addTo(map);
setTimeout(()=>map.invalidateSize(),180);
</script>
</body>
</html>
"""
