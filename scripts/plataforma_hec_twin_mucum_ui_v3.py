#!/usr/bin/env python3
"""UI pública da plataforma HEC-HMS para toda a bacia Taquari-Antas (G040).

O gerador histórico mantém o feed legado de Muçum para auditoria, mas a interface
pública lê os artefatos próprios da G040 inteira: arquitetura de ramos,
telemetria, chuva observada + ECMWF/IFS, calibração multi-evento e seleção
adaptativa. Muçum é tratado como checkpoint interno, não como exutório da bacia.
"""

from __future__ import annotations

import json
from typing import Any


def render_platform_html(feed: dict[str, Any]) -> str:
    blob = json.dumps(feed, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__LEGACY_DATA__", blob)


TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PREVINE · Bacia Taquari–Antas · G040</title>
<meta name="description" content="Plataforma de pesquisa hidrológica da bacia Taquari–Antas (G040): chuva observada e ECMWF/IFS, telemetria, arquitetura HEC-HMS e calibração multi-evento para toda a bacia."/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Source+Serif+4:opsz,wght@8..60,650;8..60,750&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--bg:#edf3ef;--panel:#fbfdfb;--panel2:#f4f8f5;--ink:#10241b;--muted:#607168;--line:#d4e0d8;--green:#176149;--green2:#0d4534;--blue:#225d8d;--amber:#98661d;--red:#9a3c32;--shadow:0 10px 32px rgba(15,45,33,.08);--r:18px}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:linear-gradient(180deg,#e7f0ea 0,#f7f9f7 36rem,#f5f4ef 100%);color:var(--ink);font:14px/1.5 Inter,system-ui,sans-serif}
a{color:var(--green);text-decoration:none}.wrap{max-width:1380px;margin:auto;padding:18px 18px 48px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 14px;border:1px solid rgba(255,255,255,.62);background:rgba(250,253,251,.86);backdrop-filter:blur(14px);border-radius:16px;box-shadow:var(--shadow);position:sticky;top:10px;z-index:1000}
.brand{display:flex;align-items:center;gap:10px;font-weight:800}.brand-mark{width:34px;height:34px;border-radius:11px;background:linear-gradient(145deg,var(--green2),#3c8a69);display:grid;place-items:center;color:white}
.nav{display:flex;gap:5px;flex-wrap:wrap}.nav a{padding:7px 9px;border-radius:9px;color:#375047;font-size:11px;font-weight:700}.nav a:hover{background:#e8f1eb}
.hero{padding:34px 4px 18px;display:grid;grid-template-columns:1.35fr .82fr;gap:22px;align-items:end}
.hero h1{margin:0;font:750 clamp(2.15rem,4.3vw,3.8rem)/1.01 "Source Serif 4",Georgia,serif;letter-spacing:-.04em}.hero h1 span{color:var(--green)}
.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.12em;font-weight:800;color:var(--green);margin-bottom:9px}.hero p{max-width:82ch;color:var(--muted);font-size:15px;margin:13px 0 0}
.status-stack{display:grid;gap:9px}.status{border:1px solid var(--line);background:rgba(255,255,255,.78);border-radius:14px;padding:12px 14px;display:flex;gap:10px;align-items:flex-start}
.dot{width:10px;height:10px;border-radius:50%;margin-top:5px;flex:0 0 auto}.dot.ok{background:#2e8b66}.dot.wait{background:#cc8a25}.dot.off{background:#a74a41}.status strong{display:block;font-size:13px}.status span{color:var(--muted);font-size:11px}
.notice{border:1px solid #e4c997;background:#fff8e9;border-radius:15px;padding:13px 15px;color:#5f4c29;margin:0 0 16px}.notice strong{color:#6f4a0d}
.grid{display:grid;gap:14px}.metrics{grid-template-columns:repeat(4,1fr)}.card{background:rgba(252,254,252,.95);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);padding:16px}
.metric .k{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.metric .v{font-size:28px;font-weight:800;letter-spacing:-.035em;margin-top:4px;font-variant-numeric:tabular-nums}.metric .s{font-size:11px;color:var(--muted);margin-top:2px}
.section{margin-top:16px;scroll-margin-top:86px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:15px;margin:0 2px 9px}.section-head h2{margin:0;font:700 1.4rem/1.1 "Source Serif 4",Georgia,serif}.section-head p{margin:0;color:var(--muted);font-size:11px;max-width:75ch;text-align:right}
.two{grid-template-columns:minmax(0,1.8fr) minmax(360px,.75fr)}.three{grid-template-columns:repeat(3,minmax(0,1fr))}
#map{height:clamp(540px,68vh,760px);min-height:540px;border-radius:14px;border:1px solid var(--line);overflow:hidden;background:#e9efeb}
.map-toolbar{display:flex;justify-content:space-between;align-items:center;gap:9px;margin-bottom:9px;flex-wrap:wrap}.map-legend{display:flex;gap:6px;flex-wrap:wrap}.map-legend span{display:inline-flex;gap:6px;align-items:center;border:1px solid #dbe5df;background:#f8fbf9;border-radius:999px;padding:5px 8px;color:#52665c;font-size:10px;font-weight:700}.sym{width:9px;height:9px;display:inline-block}.sym.branch{transform:rotate(45deg);background:#98661d}.sym.check{border-radius:50%;background:#176149}.sym.stale{border-radius:50%;background:#b9443d}.sym.river{width:14px;height:0;border-top:2px solid #4777a0}
.map-action{border:1px solid #c9d9d0;background:#fff;color:#355247;border-radius:9px;padding:7px 10px;font:700 10px Inter,sans-serif;cursor:pointer}.map-action:hover{background:#edf5f0}.map-readout{margin-top:8px;padding:8px 10px;border:1px solid #d8e3dc;background:#f7faf8;border-radius:10px;color:var(--muted);font-size:10px}
.panel-kicker{display:block;color:var(--green);font-size:9px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;margin-bottom:6px}.panel-title{font:700 1rem "Source Serif 4",Georgia,serif;margin:0 0 7px}
.node-detail{border:1px solid #c8d9cf;background:#f8fbf9;border-radius:14px;padding:13px;margin-bottom:12px}.node-detail h3{margin:0;font:750 1.08rem "Source Serif 4",Georgia,serif}.node-detail p{margin:4px 0 0;color:var(--muted);font-size:10px}
.node-kpis{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:10px}.node-kpi{background:white;border:1px solid #dbe6df;border-radius:10px;padding:9px}.node-kpi span{display:block;font-size:8.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.node-kpi b{display:block;font-size:16px;margin-top:2px}.node-kpi small{display:block;font-size:8.5px;color:var(--muted);margin-top:3px}
.searchline{display:flex;gap:7px;margin-bottom:8px}.searchline input,.searchline select{min-width:0;border:1px solid #cfdcd5;background:#fff;border-radius:9px;padding:7px 9px;color:var(--ink);font:500 10px Inter,sans-serif}.searchline input{flex:1}.node-list{display:grid;gap:6px;max-height:410px;overflow:auto;padding-right:3px}
.node-row{border:1px solid #dce5df;background:#fff;border-radius:11px;padding:8px 9px;cursor:pointer}.node-row:hover{border-color:#98b9a8}.node-row.active{border-color:var(--green);background:#f3f8f5;box-shadow:inset 3px 0 0 var(--green)}.node-row .head{display:flex;justify-content:space-between;gap:8px;font-size:10px}.node-row .name{font-weight:800;font-size:11px}.node-row .vals{display:flex;gap:5px;flex-wrap:wrap;margin-top:5px}.node-row .vals span{font-size:9px;padding:3px 5px;background:#f1f5f2;border-radius:7px}.fresh{color:#176149}.late{color:#9a6519}.bad{color:#9a3c32}
.spark{width:100%;height:125px;display:block;margin-top:10px;background:white;border:1px solid #dde7e1;border-radius:10px}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:11px}th,td{padding:8px 7px;border-bottom:1px solid #e1e8e3;text-align:left;white-space:nowrap}th{font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.pills{display:flex;gap:7px;flex-wrap:wrap}.pill{border:1px solid var(--line);background:#f3f7f4;border-radius:999px;padding:6px 9px;font-size:10px;color:#4d6258}.pill b{color:var(--ink)}
.callout{border-radius:14px;padding:14px;border:1px solid #e7d6ad;background:#fffbef}.callout h3{margin:0 0 5px;font-size:13px;color:#725018}.callout p{margin:0;color:#665534;font-size:11px}
.goodbox{border-color:#c8dfd0;background:#f0f8f3}.goodbox h3{color:#205d46}.goodbox p{color:#486258}
.ug-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.ug{border:1px solid var(--line);background:#fff;border-radius:12px;padding:10px}.ug b{display:block;font-size:12px}.ug span{display:block;color:var(--muted);font-size:9px;margin-top:3px}
.maturity{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.maturity .box{border:1px solid var(--line);background:#f7faf8;border-radius:12px;padding:11px}.maturity .box strong{display:block;font-size:12px}.maturity .box span{font-size:9.5px;color:var(--muted)}
.links{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.links a{border:1px solid #cbdad1;background:#f7faf8;padding:6px 9px;border-radius:999px;font-size:10px;font-weight:700}
.foot{color:var(--muted);font-size:10px;margin-top:15px}.loader{color:var(--muted);font-size:11px}.error{color:var(--red)}
@media(max-width:980px){.hero{grid-template-columns:1fr}.metrics,.maturity{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}.ug-grid{grid-template-columns:1fr 1fr}.section-head{align-items:start;flex-direction:column}.section-head p{text-align:left}.nav{display:none}}
@media(max-width:580px){.wrap{padding:10px 10px 34px}.metrics,.maturity,.ug-grid{grid-template-columns:1fr}.hero{padding-top:24px}#map{height:480px;min-height:480px}.searchline{flex-direction:column}.node-kpis{grid-template-columns:1fr}.topbar{top:6px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div class="brand"><span class="brand-mark">P</span><span>PREVINE · HEC-HMS G040</span></div>
    <nav class="nav"><a href="#visao">Visão geral</a><a href="#rede">Rede</a><a href="#chuva">Chuva</a><a href="#modelo">HEC-HMS</a><a href="#calibracao">Calibração</a><a href="#cobertura">Cobertura</a><a href="#dados">Dados</a></nav>
  </div>

  <header class="hero" id="visao">
    <div>
      <div class="eyebrow">Bacia Taquari–Antas · G040 · pesquisa</div>
      <h1>A bacia inteira, <span>ponto a ponto.</span></h1>
      <p>Plataforma integrada da G040 para acompanhar a chuva em toda a bacia, os principais ramos tributários, a telemetria do tronco do Taquari e a evolução do HEC-HMS 4.13. <strong>Muçum é um controle interno</strong>; o domínio hidrológico segue a jusante até o baixo Taquari e a confluência Taquari–Jacuí.</p>
    </div>
    <div class="status-stack">
      <div class="status"><span class="dot wait" id="hydroDot"></span><div><strong>Rede hidrológica</strong><span id="statusHydro">carregando controles…</span></div></div>
      <div class="status"><span class="dot wait" id="rainDot"></span><div><strong>Chuva observada + ECMWF/IFS</strong><span id="statusRain">carregando malha…</span></div></div>
      <div class="status"><span class="dot wait" id="modelDot"></span><div><strong>HEC-HMS G040</strong><span id="statusModel">carregando calibração…</span></div></div>
    </div>
  </header>

  <div class="notice" id="mainNotice"><strong>Pesquisa:</strong> carregando o estado científico da plataforma. Nenhum resultado desta página substitui alerta ou decisão da Defesa Civil.</div>

  <section class="grid metrics">
    <article class="card metric"><div class="k">Área oficial G040</div><div class="v" id="mArea">—</div><div class="s">km² · domínio da bacia</div></article>
    <article class="card metric"><div class="k">Unidades de gestão</div><div class="v" id="mUG">—</div><div class="s">UGs na G040</div></article>
    <article class="card metric"><div class="k">Controles hidrológicos</div><div class="v" id="mControls">—</div><div class="s">ramos + checkpoints do tronco</div></article>
    <article class="card metric"><div class="k">Malha meteorológica</div><div class="v" id="mGrid">—</div><div class="s">células · contrato G040 + buffer</div></article>
  </section>

  <section class="section" id="rede">
    <div class="section-head"><div><div class="eyebrow">estado observado</div><h2>Rede hidrológica da bacia</h2></div><p>Ramos Antas/Prata/Carreiro/Guaporé/Forqueta e checkpoints do tronco até Triunfo. A vazão só aparece quando está publicada no pacote hidrometeorológico; nível é mostrado na unidade bruta da fonte, sem conversão inventada.</p></div>
    <div class="grid two">
      <article class="card">
        <div class="map-toolbar">
          <div class="map-legend"><span><i class="sym branch"></i>ramo</span><span><i class="sym check"></i>checkpoint</span><span><i class="sym stale"></i>atrasado/indisponível</span><span><i class="sym river"></i>rede BHO6</span></div>
          <button class="map-action" id="fitBasin" type="button">Ver G040 inteira</button>
        </div>
        <div id="map"></div>
        <div class="map-readout" id="mapReadout">Clique em um controle para inspecionar a leitura e a série recente.</div>
      </article>
      <article class="card">
        <span class="panel-kicker">controle selecionado</span>
        <div class="node-detail" id="nodeDetail"><h3>Selecione um ponto</h3><p>Use o mapa ou a lista abaixo.</p></div>
        <div class="searchline"><input id="nodeSearch" type="search" placeholder="Buscar cidade, posto ou código"/><select id="nodeFilter"><option value="all">Todos</option><option value="branch">Ramos</option><option value="checkpoint">Tronco</option></select></div>
        <div class="node-list" id="nodeList"><span class="loader">carregando…</span></div>
      </article>
    </div>
  </section>

  <section class="section" id="chuva">
    <div class="section-head"><div><div class="eyebrow">forçante meteorológica</div><h2>Chuva em toda a G040</h2></div><p>O pacote combina chuva observada em malha com ECMWF/IFS no horizonte de 120 h. Nenhuma lacuna é preenchida silenciosamente com zero; o status do ciclo e as guardas permanecem visíveis.</p></div>
    <div class="grid metrics">
      <article class="card metric"><div class="k">Células do contrato</div><div class="v" id="rainCells">—</div><div class="s">malha 0,1° com buffer meteorológico</div></article>
      <article class="card metric"><div class="k">Horas observadas</div><div class="v" id="rainObsH">—</div><div class="s">por componente</div></article>
      <article class="card metric"><div class="k">Horizonte previsto</div><div class="v" id="rainFcH">—</div><div class="s">horas ECMWF/IFS</div></article>
      <article class="card metric"><div class="k">Componentes chuva–vazão</div><div class="v" id="rainComp">—</div><div class="s">ramos + incrementos do tronco</div></article>
    </div>
    <div class="grid two" style="margin-top:14px">
      <article class="card">
        <h3 class="panel-title">Acumulados por componente hidrológico</h3>
        <div class="table-wrap"><table><thead><tr><th>Componente</th><th>Área suporte</th><th>Obs. 24 h</th><th>ECMWF 120 h</th><th>Cobertura</th></tr></thead><tbody id="rainRows"></tbody></table></div>
      </article>
      <article class="card">
        <h3 class="panel-title">Integridade da forçante</h3>
        <div class="pills" id="rainGates"></div>
        <div class="callout" style="margin-top:12px" id="rainNote"><h3>Proveniência</h3><p>carregando…</p></div>
        <div class="links"><a href="../hec_hms_g040_full_basin/whole_basin_rain_forcing_fullgrid_hourly.csv">Malha horária CSV</a><a href="../hec_hms_g040_full_basin/whole_basin_rain_forcing_latest.json">Forçante JSON</a></div>
      </article>
    </div>
  </section>

  <section class="section" id="modelo">
    <div class="section-head"><div><div class="eyebrow">modelo hidrológico</div><h2>HEC-HMS 4.13 · arquitetura de bacia inteira</h2></div><p>Modelo intermediário com ramos observados, geração chuva–vazão incremental e roteamento ao longo do tronco. O alvo final permanece 145 sub-bacias HEC e 72 trechos.</p></div>
    <div class="maturity">
      <div class="box"><strong id="modelScope">—</strong><span>domínio hidrológico</span></div>
      <div class="box"><strong id="modelSub">—</strong><span>sub-bacias alvo</span></div>
      <div class="box"><strong id="modelReach">—</strong><span>trechos alvo</span></div>
      <div class="box"><strong id="modelPromotion">—</strong><span>promoção operacional</span></div>
    </div>
    <div class="grid two" style="margin-top:14px">
      <article class="card">
        <h3 class="panel-title">Ramos e controles incorporados</h3>
        <div class="table-wrap"><table><thead><tr><th>Controle</th><th>Papel</th><th>UG</th><th>Área drenagem</th><th>Balanço</th></tr></thead><tbody id="branchRows"></tbody></table></div>
      </article>
      <article class="card">
        <h3 class="panel-title">Estado científico</h3>
        <div class="callout" id="modelState"><h3>Carregando</h3><p>—</p></div>
        <div class="pills" id="modelParams" style="margin-top:10px"></div>
      </article>
    </div>
    <article class="card" id="mucumValidation" style="margin-top:14px">
      <h3 class="panel-title">Checkpoint Muçum · validação da rodada atual</h3>
      <div class="callout" id="mucumValidationState"><h3>Carregando</h3><p>—</p></div>
      <div class="pills" id="mucumValidationMetrics" style="margin-top:10px"></div>
    </article>
  </section>

  <section class="section" id="calibracao">
    <div class="section-head"><div><div class="eyebrow">desempenho e seleção adaptativa</div><h2>Calibração multi-evento por checkpoint</h2></div><p>Os resultados históricos são exibidos como evidência de calibração, não como garantia de previsão. Parâmetros congelados devem ser testados em eventos de validação sem retuning.</p></div>
    <article class="card">
      <div class="pills" id="calSummary"></div>
      <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Evento</th><th>Checkpoint</th><th>Pares</th><th>NSE</th><th>KGE</th><th>PBIAS</th><th>Erro pico</th><th>Erro horário</th></tr></thead><tbody id="calRows"></tbody></table></div>
    </article>
    <div class="card" style="margin-top:14px">
      <h3 class="panel-title">Biblioteca adaptativa por alvo</h3>
      <div class="table-wrap"><table><thead><tr><th>Alvo</th><th>Biblioteca</th><th>Confiança atual</th><th>Modo</th><th>Análogos disponíveis</th></tr></thead><tbody id="adaptiveRows"></tbody></table></div>
    </div>
  </section>

  <section class="section" id="cobertura">
    <div class="section-head"><div><div class="eyebrow">cobertura espacial</div><h2>Sete UGs dentro do mesmo sistema</h2></div><p>As UGs são unidades de organização e auditoria; não são tratadas automaticamente como as 145 sub-bacias computacionais finais do HEC-HMS.</p></div>
    <div class="ug-grid" id="ugGrid"></div>
    <div class="grid two" style="margin-top:14px">
      <div class="callout goodbox"><h3>Muçum no lugar correto</h3><p>Muçum permanece como um checkpoint interno importante, mas deixa de definir o domínio da plataforma. A leitura da bacia segue por Encantado, Arroio do Meio, Lajeado, Estrela, Porto Mariante, Taquari e Triunfo.</p></div>
      <div class="callout"><h3>Limite hidrodinâmico</h3><p id="hydraulicNote">HEC-HMS representa a resposta chuva–vazão. No baixo Taquari, previsão de nível/mancha pode exigir um modelo hidráulico separado quando remanso do Jacuí/Guaíba for relevante.</p></div>
    </div>
  </section>

  <section class="section" id="dados">
    <div class="section-head"><div><div class="eyebrow">rastreabilidade</div><h2>Fontes do painel</h2></div><p>O painel lê diretamente os artefatos de pesquisa publicados no repositório e mostra o timestamp de cada pacote.</p></div>
    <div class="card">
      <div class="table-wrap"><table><thead><tr><th>Pacote</th><th>Gerado</th><th>Status</th></tr></thead><tbody id="sourceRows"></tbody></table></div>
      <div class="links">
        <a href="../hec_hms_g040_full_basin/whole_basin_branch_model_latest.json">Arquitetura</a>
        <a href="../hec_hms_g040_full_basin/whole_basin_live_hydro_controls_latest.json">Hidrometria</a>
        <a href="../hec_hms_g040_full_basin/whole_basin_rain_forcing_latest.json">Chuva</a>
        <a href="../hec_hms_g040_full_basin/g040_e1_multievent_calibration_latest.json">Calibração</a>
        <a href="../hec_hms_g040_full_basin/g040_adaptive_scenario_latest.json">Seleção adaptativa</a>
        <a href="../hec_hms_g040_full_basin/full_basin_architecture_latest.json">Arquitetura 145</a>
      </div>
    </div>
    <p class="foot">PREVINE Taquari–Antas · plataforma de pesquisa. Não emite alerta, ordem de evacuação ou decisão operacional. Ausência de vazão/nível significa ausência de dado compatível no pacote publicado, não valor zero.</p>
  </section>
</div>

<script>
const LEGACY_DATA=__LEGACY_DATA__;
const PATHS={
 branch:"../hec_hms_g040_full_basin/whole_basin_branch_model_latest.json",
 hydro:"../hec_hms_g040_full_basin/whole_basin_live_hydro_controls_latest.json",
 rain:"../hec_hms_g040_full_basin/whole_basin_rain_forcing_latest.json",
 cal:"../hec_hms_g040_full_basin/g040_e1_multievent_calibration_latest.json",
 adaptive:"../hec_hms_g040_full_basin/g040_adaptive_scenario_latest.json",
 arch:"../hec_hms_g040_full_basin/full_basin_architecture_latest.json",
 dual:"hec_hms_dual_boundary_mucum_latest.json",
 basin:"../hec_hms_g040_full_basin/g040_basin_mask.geojson",
 network:"../hec_hms_g040_full_basin/whole_basin_bho6_network.geojson",
 ugs:"ugs_g040.geojson"
};
const $=id=>document.getElementById(id);
const fmt=(v,d=0)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString("pt-BR",{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=v=>v==null?"—":fmt(Number(v)*100,0)+"%";
function when(v){if(!v)return"—";try{return new Intl.DateTimeFormat("pt-BR",{timeZone:"America/Sao_Paulo",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(v))+" BRT"}catch(e){return String(v)}}
function safe(s){return String(s==null?"—":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
async function get(url){const r=await fetch(url+"?ts="+Date.now(),{cache:"no-store"});if(!r.ok)throw new Error(r.status+" "+url);return r.json()}
function dot(id,kind){const e=$(id);if(e)e.className="dot "+kind}
function statusText(v){return String(v||"sem status").replaceAll("_"," ").toLowerCase()}
function sum(arr){return arr.reduce((a,b)=>a+(Number.isFinite(Number(b))?Number(b):0),0)}
function roleLabel(r){return({upper_antas:"Antas principal",prata:"Prata",carreiro:"Carreiro",guapore:"Guaporé",forqueta:"Forqueta",checkpoint:"checkpoint do tronco"})[r]||r||"controle"}
function controlClass(c){if(c&&c.fresh_for_state)return"fresh";if(c&&c.fetch_ok)return"late";return"bad"}
function levelText(c){return c&&c.latest_level_source_unit!=null?fmt(c.latest_level_source_unit,1):"—"}
function qText(c){return c&&c.latest_flow_m3s!=null?fmt(c.latest_flow_m3s,0)+" m³/s":"—"}
function ageText(c){return c&&c.age_minutes!=null?fmt(c.age_minutes,0)+" min":"—"}

(async function boot(){
 const names=["branch","hydro","rain","cal","adaptive","arch","dual"];
 const results=await Promise.all(names.map(async n=>{try{return [n,await get(PATHS[n]),null]}catch(e){return[n,null,String(e)]}}));
 const D={},ERR={};results.forEach(x=>{D[x[0]]=x[1];ERR[x[0]]=x[2]});
 const branch=D.branch||{},hydro=D.hydro||{},rain=D.rain||{},cal=D.cal||{},adaptive=D.adaptive||{},arch=D.arch||{},dual=D.dual||{};

 const area=((arch.scope||{}).official_area_km2)||((branch.scope||{}).official_area_km2);
 $("mArea").textContent=fmt(area,0);
 $("mUG").textContent=fmt(Object.keys(arch.units_by_ug||{}).length||7,0);
 $("mControls").textContent=fmt((hydro.summary||{}).control_count,0);
 $("mGrid").textContent=fmt(((rain.gates||{}).merged_full_grid_cells)||((rain.grid_contract||{}).cells),0);

 const hs=hydro.summary||{};
 $("statusHydro").textContent=hydro.generated_at_utc?fmt(hs.fetch_ok_count,0)+"/"+fmt(hs.control_count,0)+" controles com coleta · pacote "+when(hydro.generated_at_utc):"pacote indisponível";
 dot("hydroDot",hydro.generated_at_utc?(hs.fresh_state_count>0?"ok":"wait"):"off");
 const rg=rain.gates||{};
 $("statusRain").textContent=rain.generated_at_utc?fmt(rg.merged_full_grid_cells||((rain.grid_contract||{}).cells),0)+" células · 120 h previstos · pacote "+when(rain.generated_at_utc):"pacote indisponível";
 dot("rainDot",rain.generated_at_utc?(rg.merged_full_grid_forecast_complete?"ok":"wait"):"off");
 $("statusModel").textContent=cal.generated_at_utc?statusText(cal.status)+" · pacote "+when(cal.generated_at_utc):"pacote indisponível";
 dot("modelDot",cal.generated_at_utc?(cal.promotion_allowed?"ok":"wait"):"off");

 const reason=!rg.exact_ecmwf_cycle_id_available?"O ciclo ECMWF exato ainda não está anexado ao pacote; ":"";
 const promotion=cal.promotion_allowed?"calibração promovível":"calibração ainda sem promoção";
 $("mainNotice").innerHTML="<strong>Estado científico:</strong> "+safe(reason)+safe(promotion)+". O painel cobre a G040 inteira, mas não transforma resultados de pesquisa em alerta operacional.";

 // Build whole-basin node catalog.
 const catalog=[];
 (branch.major_branch_controls||[]).forEach(x=>{const s=x.station||{};catalog.push({code:String(x.code),name:x.label,group:"branch",role:x.role,branch:x.branch,ug:s.management_unit,area:s.drainage_area_km2,lat:s.lat,lon:s.lon,mass:x.mass_balance})});
 (branch.mainstem_checkpoints||[]).forEach(x=>{const s=x.station||{};catalog.push({code:String(x.code),name:x.label,group:"checkpoint",role:"checkpoint",branch:"Taquari principal",ug:s.management_unit,area:s.drainage_area_km2,lat:s.lat,lon:s.lon,mass:false,order:x.order})});
 const liveMap=new Map((hydro.controls||[]).map(x=>[String(x.code),x]));
 const nodes=catalog.map(n=>Object.assign({},n,{live:liveMap.get(n.code)||null}));
 const nameMap=new Map(nodes.map(n=>[n.code,n.name]));
 nameMap.set("86472600","Santa Tereza");

 // Map.
 const map=L.map("map",{scrollWheelZoom:true,zoomControl:true}).setView([-29.25,-51.65],8);
 L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,referrerPolicy:"strict-origin-when-cross-origin",attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
 const basinLayer=L.layerGroup().addTo(map),ugLayer=L.layerGroup().addTo(map),netLayer=L.layerGroup(),nodeLayer=L.layerGroup().addTo(map);
 let basinBounds=null;const markers={};
 try{const gj=await get(PATHS.basin);const ly=L.geoJSON(gj,{style:{color:"#123f30",weight:2,fillColor:"#dcebe2",fillOpacity:.08}}).addTo(basinLayer);basinBounds=ly.getBounds();if(basinBounds.isValid())map.fitBounds(basinBounds,{padding:[14,14]})}catch(e){}
 try{const gj=await get(PATHS.ugs);L.geoJSON(gj,{style:{color:"#547263",weight:1,fillOpacity:0},onEachFeature:(f,l)=>{const p=f.properties||{};l.bindTooltip(p.sub_bacia||p.nome||p.name||"UG",{sticky:true})}}).addTo(ugLayer)}catch(e){}
 try{const gj=await get(PATHS.network);L.geoJSON(gj,{style:{color:"#4777a0",weight:.7,opacity:.34}}).addTo(netLayer)}catch(e){}
 nodes.forEach(n=>{
   if(n.lat==null||n.lon==null)return;
   const c=n.live&&n.live.fresh_for_state?"#176149":(n.live&&n.live.fetch_ok?"#c08222":"#a74a41");
   const opts={radius:n.group==="branch"?6:7,color:"#fff",weight:2,fillColor:c,fillOpacity:.95};
   const m=L.circleMarker([n.lat,n.lon],opts).addTo(nodeLayer);
   m.bindTooltip(safe(n.name)+" · "+safe(n.code),{direction:"top"});
   m.on("click",()=>selectNode(n.code,true));markers[n.code]=m;
 });
 L.control.layers(null,{"Controles hidrológicos":nodeLayer,"UGs":ugLayer,"Rede BHO6":netLayer,"Limite G040":basinLayer},{collapsed:true}).addTo(map);
 $("fitBasin").onclick=()=>{if(basinBounds&&basinBounds.isValid())map.fitBounds(basinBounds,{padding:[14,14]})};

 let active=null;
 function drawSpark(n){
   const svg=$("sparkQ");if(!svg)return;const rows=((n.live||{}).recent_rows||[]).filter(x=>x.flow_m3s!=null);
   if(rows.length<2){svg.innerHTML="<text x='18' y='34' fill='#607168' font-size='12'>Sem série de vazão compatível neste pacote.</text>";return}
   const vals=rows.map(x=>Number(x.flow_m3s)),W=800,H=125,L=48,R=10,T=12,B=24,lo=Math.min(...vals),hi=Math.max(...vals),sp=(hi-lo)||1;
   const x=i=>L+(W-L-R)*i/(vals.length-1),y=v=>T+(H-T-B)*(1-(v-lo)/sp);
   const p=vals.map((v,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ");
   svg.innerHTML="<line x1='"+L+"' y1='"+(H-B)+"' x2='"+(W-R)+"' y2='"+(H-B)+"' stroke='#dbe5df'/><path d='"+p+"' fill='none' stroke='#176149' stroke-width='2.5' vector-effect='non-scaling-stroke'/><text x='7' y='18' fill='#607168' font-size='10'>"+fmt(hi,0)+"</text><text x='7' y='"+(H-B)+"' fill='#607168' font-size='10'>"+fmt(lo,0)+"</text><text x='"+L+"' y='"+(H-7)+"' fill='#607168' font-size='9'>"+when(rows[0].time_utc)+"</text><text x='"+(W-R)+"' y='"+(H-7)+"' text-anchor='end' fill='#607168' font-size='9'>"+when(rows[rows.length-1].time_utc)+"</text>";
 }
 function selectNode(code,focus){
   const n=nodes.find(x=>x.code===String(code));if(!n)return;active=n.code;const c=n.live||{};
   $("nodeDetail").innerHTML="<h3>"+safe(n.name)+" <span style='font:600 9px ui-monospace;color:var(--muted)'>"+safe(n.code)+"</span></h3><p>"+safe(roleLabel(n.role))+" · "+safe(n.ug||"UG não informada")+" · área drenante "+fmt(n.area,0)+" km²</p><div class='node-kpis'><div class='node-kpi'><span>Vazão publicada</span><b>"+qText(c)+"</b><small>"+safe(c.latest_flow_at_utc?when(c.latest_flow_at_utc):"sem Q compatível")+"</small></div><div class='node-kpi'><span>Nível bruto da fonte</span><b>"+levelText(c)+"</b><small>unidade original; sem conversão presumida</small></div><div class='node-kpi'><span>Idade no pacote</span><b class='"+controlClass(c)+"'>"+ageText(c)+"</b><small>"+safe(c.last_observation_utc?when(c.last_observation_utc):"sem leitura")+"</small></div><div class='node-kpi'><span>Uso no modelo</span><b>"+safe(n.mass?"balanço":"controle")+"</b><small>"+safe(n.branch||"")+"</small></div></div><svg class='spark' id='sparkQ' viewBox='0 0 800 125' preserveAspectRatio='none'></svg>";
   drawSpark(n);renderNodeList();
   $("mapReadout").textContent=n.name+" · "+qText(c)+" · leitura "+(c.last_observation_utc?when(c.last_observation_utc):"indisponível");
   if(focus&&n.lat!=null&&n.lon!=null){map.setView([n.lat,n.lon],10,{animate:true});if(markers[n.code])markers[n.code].openTooltip()}
 }
 function renderNodeList(){
   const q=($("nodeSearch").value||"").trim().toLowerCase(),f=$("nodeFilter").value;
   const visible=nodes.filter(n=>(f==="all"||n.group===f)&&(!q||(n.name+" "+n.code+" "+(n.ug||"")+" "+(n.branch||"")).toLowerCase().includes(q)));
   $("nodeList").innerHTML="";
   visible.sort((a,b)=>a.group.localeCompare(b.group)||((a.order||0)-(b.order||0))||a.name.localeCompare(b.name,"pt-BR")).forEach(n=>{
     const c=n.live||{},d=document.createElement("div");d.className="node-row"+(active===n.code?" active":"");
     d.innerHTML="<div class='head'><span class='name'>"+safe(n.name)+"</span><span>"+safe(n.code)+"</span></div><div class='vals'><span>"+safe(n.group==="branch"?"ramo":"tronco")+"</span><span>Q "+safe(qText(c))+"</span><span class='"+controlClass(c)+"'>"+safe(c.fetch_ok?ageText(c):"sem coleta")+"</span></div>";
     d.onclick=()=>selectNode(n.code,true);$("nodeList").appendChild(d);
   });
   if(!visible.length)$("nodeList").innerHTML="<span class='loader'>Nenhum controle encontrado.</span>";
 }
 $("nodeSearch").addEventListener("input",renderNodeList);$("nodeFilter").addEventListener("change",renderNodeList);renderNodeList();
 if(nodes.length)selectNode(nodes.find(n=>n.code==="86510000")?.code||nodes[0].code,false);

 // Rainfall.
 const comps=rain.components||[],transition=(rain.transition||{}).forecast_start_utc;
 $("rainCells").textContent=fmt((rain.full_grid_merge||{}).cell_count||((rain.grid_contract||{}).cells),0);
 $("rainObsH").textContent=fmt(comps.length?Math.min(...comps.map(c=>Number(c.observed_hours||0))):null,0);
 $("rainFcH").textContent=fmt(comps.length?Math.min(...comps.map(c=>Number(c.forecast_hours||0))):null,0);
 $("rainComp").textContent=fmt(comps.length,0);
 function compName(id){
   const mapNames={"BRANCH_86500000":"Carreiro · Passo Carreiro","BRANCH_86595000":"Guaporé · Barra do Zeferino","BRANCH_86746000":"Forqueta · Travesseiro",
   "CORE_INC_86472000_86510000":"Antas/Linha José Júlio → Muçum","CORE_INC_86510000_86720000":"Muçum → Encantado","CORE_INC_86720000_86743000":"Encantado → Arroio do Meio","CORE_INC_86743000_86879000":"Arroio do Meio → Lajeado","CORE_INC_86879000_86879300":"Lajeado → Estrela","CORE_INC_86879300_86895000":"Estrela → Porto Mariante","CORE_INC_86895000_86950000":"Porto Mariante → Taquari","CORE_INC_86950000_86996000":"Taquari → Triunfo"};
   return mapNames[id]||id;
 }
 const rainRows=comps.map(c=>{
   const s=c.series||[],obs=s.filter(x=>x.source==="observed"&&x.mm!=null&&(transition?new Date(x.time_utc)<new Date(transition):true)).slice(-24),fc=s.filter(x=>x.mm!=null&&(String(x.source||"").startsWith("ecmwf")||(transition&&new Date(x.time_utc)>=new Date(transition))));
   return {id:c.component_id,name:compName(c.component_id),area:c.support_area_km2,obs24:sum(obs.map(x=>x.mm)),fc120:sum(fc.map(x=>x.mm)),obsN:obs.length,fcN:fc.length};
 }).sort((a,b)=>b.fc120-a.fc120);
 $("rainRows").innerHTML=rainRows.map(r=>"<tr><td><b>"+safe(r.name)+"</b></td><td>"+fmt(r.area,0)+" km²</td><td>"+fmt(r.obs24,1)+" mm</td><td><b>"+fmt(r.fc120,1)+" mm</b></td><td>"+r.obsN+"/24 · "+r.fcN+"/120</td></tr>").join("");
 const gates=[["11 componentes",rg.all_11_components_present],["obs ≥24 h",rg.at_least_24_observed_hours_each_component],["IFS 120 h",rg["120h_forecast_complete_each_component"]],["600 células completas",rg.merged_full_grid_forecast_complete],["ciclo ECMWF identificado",rg.exact_ecmwf_cycle_id_available],["promoção operacional",rg.operational_promotion_allowed]];
 $("rainGates").innerHTML=gates.map(g=>"<span class='pill'><b>"+(g[1]?"✓":"×")+"</b> "+safe(g[0])+"</span>").join("");
 $("rainNote").innerHTML="<h3>Proveniência</h3><p>"+safe((rain.transition||{}).rule||"Regra não publicada.")+" "+(rg.exact_ecmwf_cycle_id_available?"O ciclo ECMWF está identificado.":"O ciclo ECMWF exato ainda não está anexado ao artefato; por isso o próprio pacote bloqueia promoção operacional.")+"</p>";

 // HEC architecture.
 const sc=branch.scope||{};
 $("modelScope").textContent=sc.basin||"G040";
 $("modelSub").textContent=fmt(sc.final_hec_target_subbasins||((arch.scope||{}).hec_target_subbasins),0);
 $("modelReach").textContent=fmt(sc.final_hec_target_reaches||((arch.scope||{}).hec_target_reaches),0);
 $("modelPromotion").textContent=cal.promotion_allowed?"liberada":"não liberada";
 $("branchRows").innerHTML=(branch.major_branch_controls||[]).map(x=>{const s=x.station||{};return"<tr><td><b>"+safe(x.label)+"</b><br><small>"+safe(x.code)+"</small></td><td>"+safe(roleLabel(x.role))+"</td><td>"+safe(s.management_unit)+"</td><td>"+fmt(s.drainage_area_km2,0)+" km²</td><td>"+(x.mass_balance?"sim":"diagnóstico")+"</td></tr>"}).join("")+(branch.mainstem_checkpoints||[]).map(x=>{const s=x.station||{};return"<tr><td><b>"+safe(x.label)+"</b><br><small>"+safe(x.code)+"</small></td><td>checkpoint #"+safe(x.order)+"</td><td>"+safe(s.management_unit)+"</td><td>"+fmt(s.drainage_area_km2,0)+" km²</td><td>validação</td></tr>"}).join("");
 const best=cal.best_calibration_candidate||{},pars=best.parameters||{};
 $("modelState").innerHTML="<h3>"+safe(statusText(cal.status))+"</h3><p>O candidato "+safe(best.candidate_id||"—")+" foi o melhor da busca multi-evento, mas o pacote atual marca <strong>promotion_allowed = "+safe(String(!!cal.promotion_allowed))+"</strong>. Isso mantém a previsão de bacia inteira em pesquisa até validação independente dos parâmetros congelados.</p>";
 $("modelParams").innerHTML=Object.entries(pars).map(([k,v])=>"<span class='pill'>"+safe(k)+" <b>"+fmt(v,3)+"</b></span>").join("");

 // Current Muçum checkpoint validation. This is a checkpoint inside the G040,
 // not the spatial domain of the platform.
 const ov=(dual.operational_validation||{}),cur=(dual.current||{}),f6=(dual.recent_fit_6h||{}),f12=(dual.recent_fit_12h||{}),pk=(dual.peak||{});
 const ok=dual.publishable===true && ov.status==="VALIDATED";
 if(dual.generated_at_utc){
   $("mucumValidationState").className="callout "+(ok?"goodbox":"");
   $("mucumValidationState").innerHTML="<h3>"+(ok?"RODADA VALIDADA":"RECALIBRAÇÃO EM ANDAMENTO")+"</h3><p>"+
     (ok
       ?"O HEC-HMS fechou o estado recente de Muçum sem deslocamento visual: observado <strong>"+fmt(cur.observed_stage_cm,2)+" cm</strong>, HEC <strong>"+fmt(cur.model_stage_cm,2)+" cm</strong>, erro <strong>"+fmt(cur.stage_error_cm,2)+" cm</strong>. A validação foi concluída em "+safe(when(dual.generated_at_utc))+"."
       :"O checkpoint ainda está sendo ajustado. O painel mantém os critérios visíveis e não troca um erro de estado por simples deslocamento da curva.")+
     "</p>";
   $("mucumValidationMetrics").innerHTML=
     "<span class='pill'>NSE 6 h <b>"+fmt(f6.nse,3)+"</b></span>"+
     "<span class='pill'>NSE 12 h <b>"+fmt(f12.nse,3)+"</b></span>"+
     "<span class='pill'>RMSE 6 h <b>"+fmt(f6.raw_rmse_cm,2)+" cm</b></span>"+
     "<span class='pill'>erro t0 <b>"+fmt(cur.stage_error_cm,2)+" cm</b></span>"+
     "<span class='pill'>pico HEC <b>"+fmt(pk.stage_cm/100,2)+" m</b></span>"+
     "<span class='pill'>pico local <b>"+safe(pk.time_local||"—")+"</b></span>";
 } else {
   $("mucumValidationState").innerHTML="<h3>Sem pacote atual</h3><p>O checkpoint Muçum não publicou uma validação corrente.</p>";
   $("mucumValidationMetrics").innerHTML="";
 }

 // Calibration.
 $("calSummary").innerHTML="<span class='pill'>candidato <b>"+safe(best.candidate_id||"—")+"</b></span><span class='pill'>eventos contribuintes <b>"+fmt(best.contributing_event_count,0)+"</b></span><span class='pill'>checkpoints válidos <b>"+fmt(best.valid_checkpoint_event_count,0)+"</b></span><span class='pill'>passes <b>"+fmt(best.checkpoint_gate_pass_count,0)+"</b></span><span class='pill'>penalidade média <b>"+fmt(best.mean_multi_metric_penalty,3)+"</b></span>";
 const cr=[];(best.events||[]).forEach(ev=>Object.entries(ev.scores||{}).forEach(([code,s])=>{if((s||{}).pairs>0)cr.push({event:ev.event_id,code,name:nameMap.get(code)||code,s})}));
 $("calRows").innerHTML=cr.map(r=>"<tr><td>"+safe(r.event)+"</td><td><b>"+safe(r.name)+"</b></td><td>"+fmt(r.s.pairs,0)+"</td><td>"+fmt(r.s.nse,3)+"</td><td>"+fmt(r.s.kge,3)+"</td><td>"+fmt(r.s.pbias_pct,1)+"%</td><td>"+fmt(r.s.peak_error_pct,1)+"%</td><td>"+fmt(r.s.peak_timing_error_h,1)+" h</td></tr>").join("")||"<tr><td colspan='8'>Sem escores publicados.</td></tr>";
 const targets=Array.isArray(adaptive.targets)?adaptive.targets:Object.values(adaptive.targets||{});
 $("adaptiveRows").innerHTML=targets.map(t=>"<tr><td><b>"+safe(t.target_name||t.target_code)+"</b><br><small>"+safe(t.target_code)+"</small></td><td>"+safe(statusText(t.library_status))+"</td><td>"+safe(t.confidence||"—")+(t.confidence_cap_reason?" · "+safe(statusText(t.confidence_cap_reason)):"")+"</td><td>"+safe(statusText(t.selection_mode))+"</td><td>"+fmt((t.top_analogs||[]).length,0)+"</td></tr>").join("");

 // UG coverage.
 const units=arch.units_by_ug||{};
 $("ugGrid").innerHTML=Object.entries(units).sort((a,b)=>a[0].localeCompare(b[0],"pt-BR")).map(([n,u])=>"<div class='ug'><b>"+safe(n)+"</b><span>"+fmt(u.area_km2,0)+" km² · "+fmt(u.subbasin_count,0)+" polígonos de gestão no inventário</span></div>").join("")||"<div class='ug'><b>UGs</b><span>inventário indisponível</span></div>";
 if(arch.hydraulic_boundary_note)$("hydraulicNote").textContent=arch.hydraulic_boundary_note;

 // Sources.
 const sourceMeta=[
   ["Arquitetura de ramos",branch.generated_at_utc,branch.status],
   ["Controles hidrológicos",hydro.generated_at_utc,"fetch "+fmt(hs.fetch_ok_count,0)+"/"+fmt(hs.control_count,0)],
   ["Chuva observada + IFS",rain.generated_at_utc,rain.status],
   ["Calibração multi-evento",cal.generated_at_utc,cal.status],
   ["Seleção adaptativa",adaptive.generated_at_utc,(adaptive.governance||{}).pseudo_operational_validation_required?"validação pseudo-operacional requerida":"—"],
   ["Arquitetura 145 sub-bacias",arch.generated_at_utc,arch.status],
   ["Checkpoint Muçum · rodada atual",dual.generated_at_utc,(dual.operational_validation||{}).status||dual.status]
 ];
 $("sourceRows").innerHTML=sourceMeta.map(r=>"<tr><td><b>"+safe(r[0])+"</b></td><td>"+safe(when(r[1]))+"</td><td>"+safe(statusText(r[2]))+"</td></tr>").join("");
 setTimeout(()=>map.invalidateSize(),150);
})().catch(e=>{
 $("mainNotice").innerHTML="<strong>Erro de leitura:</strong> "+safe(e.message)+". A página não inventa valores quando um artefato não pode ser carregado.";
 dot("hydroDot","off");dot("rainDot","off");dot("modelDot","off");
});
</script>
</body>
</html>"""
