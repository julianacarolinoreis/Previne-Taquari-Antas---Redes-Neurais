#!/usr/bin/env python3
"""HTML renderer for the HEC/REC twin research platform (Muçum)."""

from __future__ import annotations

import json
from typing import Any


def _esc(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_platform_html(feed: dict[str, Any]) -> str:
    """Render the self-contained research platform page from an enriched feed."""
    blob = json.dumps(feed, ensure_ascii=False).replace("</", "<\\/")

    title = _esc(feed.get("label_pt") or "Plataforma HEC/REC · Muçum")
    generated = _esc(feed.get("generated_at_utc") or "—")
    status = _esc(feed.get("status") or "research")

    product = feed.get("product") or {}
    product_name = _esc(product.get("name") or "ΔN ~5d · Muçum")
    product_horizon = _esc(product.get("horizon") or "~5 dias")
    product_target = _esc(product.get("target") or "Muçum")
    product_mode = _esc(product.get("mode") or "pesquisa")

    summary = feed.get("summary") or {}
    peak_n = summary.get("peak_n_cm")
    peak_dn = summary.get("peak_delta_n_cm")
    peak_when = _esc(summary.get("peak_when_utc") or "—")
    timing = summary.get("timing_error_h")
    n_anchor = summary.get("n_anchor_cm")

    auto = feed.get("automation") or {}
    auto_name = _esc(
        auto.get("workflow_name") or auto.get("workflow") or "HEC twin Muçum forward"
    )
    auto_sched = _esc(auto.get("schedule_cron") or "12 */6 * * *")
    auto_owner = _esc(auto.get("commit_author") or "previne-hec-bot")

    freshness = feed.get("freshness") or {}
    live_age = freshness.get("live_age_hours")
    fwd_age = freshness.get("forward_age_hours")
    preferred = _esc(
        freshness.get("preferred_source")
        or freshness.get("preferred_source")
        or "live_eval"
    )
    stale = bool(freshness.get("stale_forward", freshness.get("stale_forward")))
    live_age_txt = "—" if live_age is None else f"{float(live_age):.1f} h"
    fwd_age_txt = "—" if fwd_age is None else f"{float(fwd_age):.1f} h"
    peak_n_txt = "—" if peak_n is None else f"{float(peak_n):.0f} cm"
    peak_dn_txt = "—" if peak_dn is None else f"{float(peak_dn):+.0f} cm"
    timing_txt = "—" if timing is None else f"{float(timing):+.1f} h"
    n_anchor_txt = "—" if n_anchor is None else f"{float(n_anchor):.0f} cm"
    n_anchors = int((feed.get("spatial") or {}).get("anchor_count") or 0)
    fresh_cls = "fresh warn" if stale else "fresh"

    html = TEMPLATE
    for key, val in {
        "TITLE": title,
        "GENERATED": generated,
        "STATUS": status,
        "PRODUCT_NAME": product_name,
        "PRODUCT_HORIZON": product_horizon,
        "PRODUCT_TARGET": product_target,
        "PRODUCT_MODE": product_mode,
        "PEAK_N": peak_n_txt,
        "PEAK_DN": peak_dn_txt,
        "PEAK_WHEN": peak_when,
        "TIMING": timing_txt,
        "N_ANCHOR": n_anchor_txt,
        "AUTO_NAME": auto_name,
        "AUTO_SCHED": auto_sched,
        "AUTO_OWNER": auto_owner,
        "PREFERRED": preferred,
        "LIVE_AGE": live_age_txt,
        "FWD_AGE": fwd_age_txt,
        "N_ANCHORS": str(n_anchors),
        "FRESH_CLS": fresh_cls,
        "BLOB": blob,
    }.items():
        html = html.replace("{{" + key + "}}", val)
    return html


TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{{TITLE}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;550;650;700&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {
  --ink:#12241c; --muted:#4a6356; --line:#c5d5cb; --panel:rgba(243,247,244,.94);
  --live:#0f5c45; --fwd:#1d4f91; --warn:#8a5a12; --shadow:0 12px 28px rgba(18,52,42,.10);
}
* { box-sizing:border-box; }
body {
  margin:0; color:var(--ink);
  font:15px/1.55 "IBM Plex Sans", "Segoe UI", sans-serif;
  background:
    radial-gradient(1100px 520px at 8% -12%, #cfe2d6 0%, transparent 55%),
    radial-gradient(900px 480px at 100% 0%, #d5e4ef 0%, transparent 50%),
    linear-gradient(165deg, #d9e6de 0%, #eef3ef 45%, #f7f4ee 100%);
  min-height:100vh;
}
.wrap { max-width:1180px; margin:0 auto; padding:1.15rem 1rem 2.5rem; }
header.hero { display:grid; gap:.85rem; margin-bottom:1rem; animation:rise .55s ease both; }
.kicker { display:flex; flex-wrap:wrap; gap:.45rem; align-items:center; }
.pill {
  display:inline-flex; align-items:center; gap:.3rem;
  border:1px solid var(--line); background:#fff; border-radius:999px;
  padding:.18rem .62rem; font-size:.74rem; color:var(--muted);
  letter-spacing:.04em; text-transform:uppercase; font-weight:650;
}
.pill.ok { border-color:#9fd6c0; color:var(--live); background:#f0faf6; }
h1 {
  margin:0; font-family:Fraunces, Georgia, serif;
  font-size:clamp(1.55rem, 3vw, 2.15rem); letter-spacing:-.02em; line-height:1.15;
}
h1 span { color:var(--live); }
.lede { margin:0; color:var(--muted); max-width:64ch; }
.fresh {
  display:flex; flex-wrap:wrap; gap:.7rem 1.1rem; align-items:center;
  padding:.7rem .9rem; border-radius:12px; border:1px solid #c9e2d6;
  background:linear-gradient(90deg,#f3fbf7,#eef6fb); box-shadow:var(--shadow);
}
.fresh.warn { border-color:#e7c9a4; background:linear-gradient(90deg,#fff7f0,#eef6fb); }
.fresh strong { color:var(--live); }
.grid { display:grid; gap:.9rem; }
@media (min-width:900px) {
  .metrics { grid-template-columns:repeat(4,1fr); }
  .products { grid-template-columns:1fr 1fr; }
  .split { grid-template-columns:1.35fr 1fr; }
}
.card {
  background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:.9rem 1rem; box-shadow:var(--shadow); backdrop-filter:blur(6px);
  animation:rise .6s ease both;
}
.card h2, .card h3 { margin:0 0 .45rem; font-family:Fraunces, Georgia, serif; font-size:1.05rem; }
.metric .label { color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; }
.metric .value { font-size:1.55rem; font-weight:700; letter-spacing:-.02em; margin-top:.15rem; font-variant-numeric:tabular-nums; }
.metric .hint { color:var(--muted); font-size:.8rem; margin-top:.15rem; }
.product-live { border-top:3px solid var(--live); }
.product-fwd { border-top:3px solid var(--fwd); }
.product-live h3 { color:var(--live); }
.product-fwd h3 { color:var(--fwd); }
.muted { color:var(--muted); }
.mono { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:.84rem; }
.chips { display:flex; flex-wrap:wrap; gap:.4rem; margin:.55rem 0 .7rem; }
.chip {
  border:1px solid var(--line); background:#fff; color:var(--muted);
  border-radius:999px; padding:.28rem .72rem; font-size:.8rem; cursor:pointer; font-family:inherit;
}
.chip.active { background:var(--ink); color:#fff; border-color:var(--ink); }
#map { height:min(62vh, 560px); border-radius:12px; border:1px solid var(--line); }
.legend {
  background:rgba(255,255,255,.94); border:1px solid var(--line); border-radius:10px;
  padding:.45rem .6rem; font-size:.78rem; line-height:1.35; box-shadow:var(--shadow);
}
.legend i { display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:.35rem; vertical-align:-1px; }
.chart-wrap { overflow-x:auto; }
svg.chart { width:100%; min-width:520px; height:280px; display:block; }
.chart-caption { color:var(--muted); font-size:.82rem; margin-top:.4rem; }
.anchor-list { max-height:360px; overflow:auto; display:grid; gap:.45rem; }
.anchor-item {
  border:1px solid var(--line); border-radius:10px; padding:.55rem .7rem; background:#fff;
  cursor:pointer; transition:border-color .15s ease, transform .15s ease;
}
.anchor-item:hover { border-color:#9eb6cc; transform:translateY(-1px); }
.anchor-item.active { border-color:var(--fwd); box-shadow:inset 0 0 0 1px rgba(29,79,145,.25); }
.anchor-item .name { font-weight:650; }
.anchor-item .meta { color:var(--muted); font-size:.8rem; }
.links { display:flex; flex-wrap:wrap; gap:.55rem; margin-top:.7rem; }
.links a {
  text-decoration:none; color:var(--fwd); border:1px solid #bfd0e4; background:#f5f9fd;
  border-radius:999px; padding:.35rem .8rem; font-size:.84rem; font-weight:650;
}
.foot { margin-top:1.1rem; color:var(--muted); font-size:.82rem; }
ol.muted { margin:.35rem 0 0; padding-left:1.15rem; }
@keyframes rise {
  from { opacity:0; transform:translateY(8px); }
  to { opacity:1; transform:translateY(0); }
}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="kicker">
      <span class="pill ok">pesquisa · não é alerta oficial</span>
      <span class="pill">{{STATUS}}</span>
      <span class="pill">{{PRODUCT_NAME}}</span>
      <span class="pill">{{PRODUCT_HORIZON}}</span>
      <span class="pill">alvo {{PRODUCT_TARGET}}</span>
      <span class="pill">{{PRODUCT_MODE}}</span>
    </div>
    <h1>Plataforma <span>HEC/REC</span></h1>
    <p class="lede">
      Onde o resultado do gêmeo hidrológico vai parar — quanto sobe em Muçum, com a chuva
      no mapa do corredor, hidrograma do evento e amarração nos postos. RNAs de curto prazo
      permanecem intactas.
    </p>
    <div class="{{FRESH_CLS}}" id="freshnessBanner">
      <span>Atualização: <strong>{{GENERATED}}</strong> UTC</span>
      <span>Fonte preferida: <strong>{{PREFERRED}}</strong></span>
      <span>Live eval: <span class="mono">{{LIVE_AGE}}</span></span>
      <span>Forward: <span class="mono">{{FWD_AGE}}</span></span>
      <span>Âncoras: <strong>{{N_ANCHORS}}</strong></span>
    </div>
  </header>

  <section class="grid metrics" style="margin-bottom:.9rem">
    <article class="card metric">
      <div class="label">ΔN pico (live)</div>
      <div class="value">{{PEAK_DN}}</div>
      <div class="hint">acima da âncora {{N_ANCHOR}}</div>
    </article>
    <article class="card metric">
      <div class="label">N pico estimado</div>
      <div class="value">{{PEAK_N}}</div>
      <div class="hint">em {{PEAK_WHEN}}</div>
    </article>
    <article class="card metric">
      <div class="label">Timing vs obs</div>
      <div class="value">{{TIMING}}</div>
      <div class="hint">erro de tempo do pico</div>
    </article>
    <article class="card metric">
      <div class="label">Robô HEC</div>
      <div class="value" style="font-size:1.02rem">{{AUTO_NAME}}</div>
      <div class="hint mono">{{AUTO_SCHED}} · {{AUTO_OWNER}}</div>
    </article>
  </section>

  <section class="grid products" style="margin-bottom:.9rem">
    <article class="card product-live"><h3>Live eval (evento)</h3><p class="muted" id="liveSummary">Carregando…</p></article>
    <article class="card product-fwd"><h3>Forward ~5d (operacional)</h3><p class="muted" id="fwdSummary">Carregando…</p></article>
  </section>

  <section class="card" style="margin-bottom:.9rem">
    <h2>Traço do evento · hidrograma + chuva</h2>
    <p class="muted" id="chartCaption">Série do live eval (quando disponível) ou amostra do forward.</p>
    <div class="chart-wrap">
      <svg class="chart" id="eventChart" viewBox="0 0 960 280" role="img" aria-label="Hidrograma do evento"></svg>
    </div>
    <p class="chart-caption" id="chartNote"></p>
  </section>

  <section class="grid split" style="margin-bottom:.9rem">
    <article class="card">
      <h2>Mapa espacial · UGs + âncoras</h2>
      <div class="chips" id="roleChips"></div>
      <div id="map"></div>
    </article>
    <article class="card">
      <h2>Pontos de amarração</h2>
      <p class="muted">Clique para focar no mapa. Filtro por papel no corredor HEC.</p>
      <div class="anchor-list" id="anchorList"></div>
      <div class="links" id="artifactLinks"></div>
    </article>
  </section>

  <section class="card">
    <h2>Como o robô alimenta esta página</h2>
    <ol class="muted" id="robotSteps"></ol>
    <p class="foot">
      IFS = proxy pontual por sub-bacia (não máscara areal). Modelo de corredor ≠ G040 completa
      (Guaporé/Forqueta fora). Santa Tereza sem curva-chave inventada. Pesquisa, não alerta oficial.
    </p>
  </section>
</div>

<script>
const DATA = {{BLOB}};

function fmt(v, digits) {
  if (digits === undefined) digits = 0;
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("pt-BR", {maximumFractionDigits:digits, minimumFractionDigits:digits});
}
function ageLabel(h) {
  if (h === null || h === undefined) return "idade desconhecida";
  if (h < 1) return Math.round(h * 60) + " min";
  return Number(h).toFixed(1) + " h";
}
function roleColor(role) {
  if (role === "target") return "#0f5c45";
  if (role === "level_control") return "#1d4f91";
  if (role === "rain") return "#1d6b9f";
  return "#5a6570";
}
function roleLabel(role) {
  return ({target:"alvo", level_control:"nível", rain:"chuva", upstream_monitor:"montante"})[role] || role;
}
function anchorRain(a) {
  return (a && a.rain_mm_window != null) ? a.rain_mm_window : null;
}

const live = (DATA.products && DATA.products.live_eval) || {};
const fwd = (DATA.products && DATA.products.forward_5d) || {};
const liveP = live.primary || {};
const fwdP = fwd.primary || {};
const liveEl = document.getElementById("liveSummary");
const fwdEl = document.getElementById("fwdSummary");

if (live.available !== false && (liveP.rise_cm != null || live.plain_pt)) {
  liveEl.innerHTML =
    "<span class=\"mono\">" + (live.artifact || "live_eval") + "</span><br/>" +
    "ΔN " + fmt(liveP.rise_cm, 0) + " cm · N pico " + fmt(liveP.peak_anchored_cm, 0) + " cm<br/>" +
    "quando " + (liveP.peak_time_utc || "—") +
    (live.timing_error_h != null ? " · timing " + fmt(live.timing_error_h, 1) + " h" : "") + "<br/>" +
    "<span class=\"muted\">idade " + ageLabel(live.age_hours) + (live.note ? " · " + live.note : "") + "</span>";
} else {
  liveEl.textContent = "Live eval indisponível neste build.";
}

if (fwd.available !== false) {
  fwdEl.innerHTML =
    "<span class=\"mono\">" + (fwd.artifact || "forward_5d") + "</span><br/>" +
    "ΔN " + fmt(fwdP.rise_cm, 0) + " cm · N pico " + fmt(fwdP.peak_anchored_cm, 0) + " cm<br/>" +
    "quando " + (fwdP.peak_time_utc || "—") + "<br/>" +
    "<span class=\"muted\">idade " + ageLabel(fwd.age_hours) +
    (fwd.stale ? " · forward seco/stale — preferir live para o evento" : "") + "</span>";
} else {
  fwdEl.textContent = "Forward ainda não gerado.";
}

const steps = document.getElementById("robotSteps");
((DATA.automation && (DATA.automation.steps_pt || DATA.automation.pipeline)) || []).forEach(function(s) {
  const li = document.createElement("li");
  li.textContent = s;
  steps.appendChild(li);
});

const links = document.getElementById("artifactLinks");
const local = ((DATA.where_results_go || {}).local) || {};
[
  ["Forward ~5d", local.forward_html],
  ["Live eval", local.live_eval_html],
  ["Verify", local.verify_html],
  ["Hindcast", local.hindcast_html],
  ["Feed JSON", local.platform_json],
  ["Mapa UGs", local.mapa_subbacias]
].forEach(function(pair) {
  if (!pair[1]) return;
  const a = document.createElement("a");
  a.href = pair[1];
  a.textContent = pair[0];
  links.appendChild(a);
});

(function drawChart() {
  const svg = document.getElementById("eventChart");
  const note = document.getElementById("chartNote");
  const trace = DATA.event_trace || {};
  const series = trace.series || [];
  const rain = trace.rain_mm || [];
  if (!series.length) {
    svg.innerHTML = "<text x=\"24\" y=\"140\" fill=\"#4a6356\">Sem série para plotar.</text>";
    return;
  }
  const W = 960, H = 280, pad = {l:54, r:18, t:18, b:36};
  const innerW = W - pad.l - pad.r, innerH = H - pad.t - pad.b;
  const ys = series.map(function(p){ return Number(p.n_cm); }).filter(function(v){ return !Number.isNaN(v); });
  const yMin = Math.min.apply(null, ys.concat([0]));
  const yMax = Math.max.apply(null, ys.concat([1]));
  const xAt = function(i){ return pad.l + (i / Math.max(series.length - 1, 1)) * innerW; };
  const yAt = function(v){ return pad.t + (1 - ((v - yMin) / (yMax - yMin || 1))) * innerH; };
  let path = "";
  series.forEach(function(p, i) {
    const x = xAt(i), y = yAt(Number(p.n_cm));
    path += (i ? " L " : "M ") + x.toFixed(1) + " " + y.toFixed(1);
  });
  const rainMax = Math.max.apply(null, rain.concat([1]));
  let bars = "";
  rain.forEach(function(v, i) {
    const h = (Number(v) / rainMax) * (innerH * 0.28);
    const x = xAt(i);
    const bw = Math.max(2, innerW / Math.max(rain.length, 1) * 0.55);
    bars += "<rect x=\"" + (x - bw/2).toFixed(1) + "\" y=\"" + (pad.t + 4).toFixed(1) +
      "\" width=\"" + bw.toFixed(1) + "\" height=\"" + h.toFixed(1) +
      "\" fill=\"rgba(29,107,159,0.28)\"></rect>";
  });
  const grid = [];
  for (let g = 0; g < 4; g++) {
    const yy = pad.t + (innerH * g / 3);
    const val = yMax - (yMax - yMin) * g / 3;
    grid.push("<line x1=\"" + pad.l + "\" x2=\"" + (W-pad.r) + "\" y1=\"" + yy + "\" y2=\"" + yy + "\" stroke=\"#d7e2db\"/>");
    grid.push("<text x=\"8\" y=\"" + (yy+4) + "\" fill=\"#4a6356\" font-size=\"11\">" + val.toFixed(0) + "</text>");
  }
  svg.innerHTML = grid.join("") + bars +
    "<path d=\"" + path + "\" fill=\"none\" stroke=\"#0f5c45\" stroke-width=\"2.4\"></path>" +
    "<text x=\"" + pad.l + "\" y=\"" + (H-10) + "\" fill=\"#4a6356\" font-size=\"11\">" +
    (series[0] && series[0].t ? series[0].t : "") + "</text>" +
    "<text x=\"" + (W-pad.r) + "\" y=\"" + (H-10) + "\" fill=\"#4a6356\" font-size=\"11\" text-anchor=\"end\">" +
    (series[series.length-1] && series[series.length-1].t ? series[series.length-1].t : "") + "</text>";
  document.getElementById("chartCaption").textContent =
    "Fonte do traço: " + (trace.source || "—") + (trace.note ? " · " + trace.note : "");
  note.textContent = "Linha verde = nível estimado (cm). Barras azuis = chuva proxy (mm).";
})();

const anchors = ((DATA.spatial || {}).anchors) || [];
const roleChips = document.getElementById("roleChips");
const roles = ["all"].concat(Array.from(new Set(anchors.map(function(a){ return a.role; }))));
let activeRole = "all";
let activeId = null;
const list = document.getElementById("anchorList");
const map = L.map("map", {scrollWheelZoom:true}).setView([-29.05, -51.75], 9);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom:18, attribution:"&copy; OpenStreetMap"
}).addTo(map);
const ugLayer = L.layerGroup().addTo(map);
const rainLayer = L.layerGroup().addTo(map);
const anchorLayer = L.layerGroup().addTo(map);
const markers = {};

const legend = L.control({position:"bottomright"});
legend.onAdd = function() {
  const d = L.DomUtil.create("div", "legend");
  d.innerHTML =
    "<div><i style=\"background:#0f5c45\"></i>alvo</div>" +
    "<div><i style=\"background:#1d4f91\"></i>nível</div>" +
    "<div><i style=\"background:#1d6b9f\"></i>chuva</div>" +
    "<div><i style=\"background:#5a6570\"></i>montante</div>";
  return d;
};
legend.addTo(map);
L.control.layers(null, {"UGs HEC":ugLayer, "Chuva IFS":rainLayer, "Âncoras":anchorLayer}, {collapsed:false}).addTo(map);

function renderChips() {
  roleChips.innerHTML = "";
  roles.forEach(function(r) {
    const b = document.createElement("button");
    b.className = "chip" + (r === activeRole ? " active" : "");
    b.type = "button";
    b.textContent = r === "all" ? "todos" : roleLabel(r);
    b.onclick = function(){ activeRole = r; renderAnchors(); };
    roleChips.appendChild(b);
  });
}

function renderAnchors() {
  list.innerHTML = "";
  anchorLayer.clearLayers();
  Object.keys(markers).forEach(function(k){ delete markers[k]; });
  anchors.filter(function(a){ return activeRole === "all" || a.role === activeRole; }).forEach(function(a) {
    const id = a.code || a.id;
    const rain = anchorRain(a);
    const item = document.createElement("div");
    item.className = "anchor-item" + (id === activeId ? " active" : "");
    item.innerHTML =
      "<div class=\"name\">" + (a.label || a.name) + "</div>" +
      "<div class=\"meta\">" + (a.role_pt || roleLabel(a.role)) +
      (a.ug ? " · " + a.ug : "") +
      (rain != null ? " · chuva " + Number(rain).toFixed(1) + " mm" : "") + "</div>";
    item.onclick = function() {
      activeId = id;
      map.setView([a.lat, a.lon], 11, {animate:true});
      if (markers[id]) markers[id].openPopup();
      renderAnchors();
    };
    list.appendChild(item);
    const m = L.circleMarker([a.lat, a.lon], {
      radius: a.role === "target" ? 9 : 7, color:"#fff", weight:2,
      fillColor: roleColor(a.role), fillOpacity:0.95
    }).bindPopup(
      "<strong>" + (a.label || a.name) + "</strong><br/>" +
      (a.role_pt || roleLabel(a.role)) + "<br/>" + (a.name || "") + " · " + id +
      (rain != null ? "<br/>chuva janela: " + Number(rain).toFixed(1) + " mm" : "")
    );
    m.addTo(anchorLayer);
    markers[id] = m;
  });
}

function rainColor(mm) {
  if (mm == null) return "#9bb8a8";
  if (mm < 5) return "#a8c5b4";
  if (mm < 15) return "#5f9e7a";
  if (mm < 30) return "#c47a2a";
  if (mm < 50) return "#b85a1a";
  return "#8f2f2a";
}
function rainRadius(mm) {
  const v = Math.max(0, Number(mm) || 0);
  return Math.max(8, Math.min(34, 8 + Math.sqrt(v) * 3.2));
}

((((DATA.spatial || {}).rain_geojson) || ((DATA.spatial || {}).rain_geojson) || {}).features || []).forEach(function(f) {
  const pr = f.properties || {};
  const coords = (f.geometry && f.geometry.coordinates) || [];
  if (coords.length < 2) return;
  const mm = pr.total_mm;
  L.circleMarker([coords[1], coords[0]], {
    radius: rainRadius(mm), color:"#5c4030", weight:1,
    fillColor: rainColor(mm), fillOpacity:0.72
  }).bindPopup(
    "<strong>" + (pr.label || pr.subbasin_id || "") + "</strong><br/>total " + fmt(mm,1) + " mm" +
    "<br/>passado " + fmt(pr.past_mm,1) + " · futuro " + fmt(pr.future_mm,1)
  ).addTo(rainLayer);
});

async function loadUgs() {
  const path = (DATA.spatial || {}).ug_geojson;
  if (!path) return;
  try {
    const res = await fetch(path);
    if (!res.ok) return;
    const geo = await res.json();
    const rainByUg = (DATA.spatial || {}).ug_rain_mm || {};
    const filterSet = new Set((DATA.spatial || {}).ug_filter || []);
    const layer = L.geoJSON(geo, {
      filter: function(feat) {
        const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "";
        if (filterSet.size) return filterSet.has(name);
        return /Prata|Carreiro|M[eé]dio Taquari/i.test(name);
      },
      style: function(feat) {
        const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "";
        const rain = rainByUg[name];
        let fill = "#94a3b8";
        if (rain != null) {
          if (rain >= 80) fill = "#1d4ed8";
          else if (rain >= 40) fill = "#3b82f6";
          else if (rain >= 15) fill = "#93c5fd";
          else fill = "#dbeafe";
        }
        return {color:"#1e3a5f", weight:1.2, fillColor:fill, fillOpacity:0.35};
      },
      onEachFeature: function(feat, lyr) {
        const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "UG";
        const rain = rainByUg[name];
        lyr.bindPopup("<strong>" + name + "</strong>" +
          (rain != null ? "<br/>chuva proxy: " + Number(rain).toFixed(1) + " mm" : ""));
      }
    });
    layer.addTo(ugLayer);
    try { map.fitBounds(layer.getBounds().pad(0.08)); } catch (e) {}
  } catch (e) {}
}

drawChart();
renderChips();
renderAnchors();
loadUgs();
setTimeout(function(){ map.invalidateSize(); }, 200);
</script>
</body>
</html>
"""
