#!/usr/bin/env python3
"""HTML renderer for the HEC/REC platform — bacia Taquari–Antas (G040)."""

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
    blob = json.dumps(feed, ensure_ascii=False).replace("</", "<" + chr(92) + "/")

    title = _esc(feed.get("label_pt") or "Plataforma HEC/REC · bacia Taquari–Antas (G040)")
    generated = _esc(feed.get("generated_at_utc") or "—")
    status = _esc(feed.get("status") or "research")

    product = feed.get("product") or {}
    product_name = _esc(product.get("name") or "Produto gêmeo · ΔN Muçum ~5d")
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

    spatial = feed.get("spatial") or {}
    framing = spatial.get("basin_framing") or {}
    inv = spatial.get("inventory_stats") or {}
    totals = inv.get("totals") or ((spatial.get("basin_network") or {}).get("counts") or {})
    basin = feed.get("basin") or {}

    n_anchors = int(spatial.get("anchor_count") or 0)
    n_network = int(totals.get("total") or 0)
    n_outside = int(totals.get("outside_twin_domain") or 0)
    basin_km2 = basin.get("area_km2") or framing.get("g040_km2") or 26430
    n_ugs = int(totals.get("ugs") or len(basin.get("ugs") or framing.get("g040_ugs") or []) or 7)
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
        "N_NETWORK": f"{n_network:,}".replace(",", "."),
        "N_OUTSIDE": str(n_outside),
        "BASIN_KM2": f"{int(basin_km2):,}".replace(",", "."),
        "N_UGS": str(n_ugs),
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
.method-grid { display:grid; gap:.55rem; margin-top:.45rem; }
@media (min-width:800px) { .method-grid { grid-template-columns:1.2fr 1fr; } }
.method-grid .box {
  border:1px solid var(--line); border-radius:12px; background:#fff; padding:.65rem .75rem;
}
.method-grid h3 { margin:0 0 .35rem; font-family:Fraunces, Georgia, serif; font-size:.95rem; }
.method-grid ul { margin:.2rem 0 0; padding-left:1.1rem; color:var(--muted); }
.method-grid li { margin:.15rem 0; }
.contrast {
  display:flex; flex-wrap:wrap; gap:.55rem 1rem; margin:.4rem 0 .15rem;
  padding:.55rem .7rem; border-radius:10px; border:1px dashed #b9cfc2; background:#f4faf6;
}
.contrast strong { color:var(--live); }
.badge-n1 {
  display:inline-block; margin-left:.35rem; padding:.1rem .45rem; border-radius:999px;
  border:1px solid #e0c08a; background:#fff8ee; color:#8a5a12; font-size:.72rem; font-weight:700;
}
ol.muted { margin:.35rem 0 0; padding-left:1.15rem; }

.skill-table { width:100%; border-collapse:collapse; font-size:.84rem; margin-top:.55rem; }
.skill-table th, .skill-table td {
  border-bottom:1px solid var(--line); padding:.4rem .35rem; text-align:left;
  font-variant-numeric:tabular-nums;
}
.skill-table th { color:var(--muted); font-weight:650; font-size:.75rem; text-transform:uppercase; letter-spacing:.03em; }
.skill-table tr.tag-best_rel_dn td:first-child { color:var(--live); font-weight:700; }
.skill-table tr.tag-worst_rel_dn td:first-child,
.skill-table tr.tag-worst_peak_q td:first-child,
.skill-table tr.tag-negative_nse td:first-child { color:#8a3b12; font-weight:700; }
.lessons { margin:.55rem 0 0; padding-left:1.1rem; }
.lessons li { margin:.25rem 0; color:var(--muted); }
.skill-summary { display:flex; flex-wrap:wrap; gap:.55rem 1rem; margin:.35rem 0 .2rem; }
.skill-summary strong { color:var(--live); }
.inspector {
  margin-top:.7rem; border:1px solid var(--line); border-radius:12px;
  background:rgba(255,255,255,.78); padding:.7rem .8rem; min-height:9.5rem;
}
.inspector h3 { margin:0 0 .35rem; font-family:Fraunces, Georgia, serif; font-size:.98rem; }
.inspector .empty { color:var(--muted); font-size:.88rem; }
svg.mini-chart { width:100%; height:168px; display:block; }

.ug-inventory { display:grid; gap:.45rem; max-height:280px; overflow:auto; margin-top:.45rem; }
.ug-row {
  border:1px solid var(--line); border-radius:10px; padding:.5rem .65rem; background:#fff;
  display:grid; gap:.15rem;
}
.ug-row .name { font-weight:650; display:flex; justify-content:space-between; gap:.5rem; }
.ug-row .meta { color:var(--muted); font-size:.8rem; }
.ug-row.twin { border-left:3px solid #2f5a48; }
.ug-row.inventory { border-left:3px solid #8a6a28; }
.pill.quiet { opacity:.85; font-weight:550; }
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
      <span class="pill ok">G040 · {{BASIN_KM2}} km²</span>
      <span class="pill ok">7 UGs</span>
      <span class="pill">rede {{N_NETWORK}}</span>
      <span class="pill">{{PRODUCT_NAME}}</span>
    </div>
    <h1>Bacia Taquari–Antas <span>G040</span></h1>
    <p class="lede">
      Esta página é da <strong>bacia oficial inteira</strong>
      (~{{BASIN_KM2}} km², {{N_UGS}} UGs). Produtos multi-exutório: corredor Muçum (~16 mil km²)
      e Encantado após Guaporé (~19 mil km²). Foz Guaporé isolada, Forqueta e Baixo ainda
      sem Q oficial — inventário + gate, não ΔN inventado.
    </p>
    <div class="{{FRESH_CLS}}" id="freshnessBanner">
      <span>Atualização: <strong>{{GENERATED}}</strong> UTC</span>
      <span>Fonte preferida: <strong>{{PREFERRED}}</strong></span>
      <span>Live eval: <span class="mono">{{LIVE_AGE}}</span></span>
      <span>Forward: <span class="mono">{{FWD_AGE}}</span></span>
      <span>Rede G040: <strong>{{N_NETWORK}}</strong></span>
      <span>fora do gêmeo: <strong>{{N_OUTSIDE}}</strong></span>
      <span>Âncoras produto: <strong>{{N_ANCHORS}}</strong></span>
    </div>
  </header>

  <section class="card" style="margin-bottom:.9rem" id="methodCard">
    <h2>Método · o que isto é (e o que não é)</h2>
    <p class="muted" id="methodLede">Braço da família HEC/REC, domínio e validação — sem overclaim.</p>
    <div class="contrast" id="skillContrast"></div>
    <div class="method-grid" id="methodGrid"></div>
  </section>

  <section class="card" style="margin-bottom:.9rem" id="multiOutletCard">
    <h2>Calibração G040 · multi-exutório</h2>
    <p class="muted" id="multiOutletLede">Muçum + Encantado (Guaporé) calibrados; fozes Guaporé/Forqueta e Baixo gated.</p>
    <div class="contrast" id="encantadoContrast"></div>
    <div class="ug-inventory" id="outletInventory"></div>
    <ol class="lessons" id="multiOutletNext"></ol>
  </section>

  <section class="grid metrics" style="margin-bottom:.9rem" id="basinMetrics">
    <article class="card metric">
      <div class="label">Área da bacia</div>
      <div class="value">{{BASIN_KM2}}</div>
      <div class="hint">km² · G040 oficial</div>
    </article>
    <article class="card metric">
      <div class="label">Unidades de gestão</div>
      <div class="value">{{N_UGS}}</div>
      <div class="hint">Alto→Baixo · inventário completo</div>
    </article>
    <article class="card metric">
      <div class="label">Rede inventário</div>
      <div class="value">{{N_NETWORK}}</div>
      <div class="hint">flu+chuva · {{N_OUTSIDE}} fora do gêmeo</div>
    </article>
    <article class="card metric">
      <div class="label">Produto ΔN</div>
      <div class="value" style="font-size:1.15rem">{{PEAK_DN}}</div>
      <div class="hint">Muçum · dentro da bacia</div>
    </article>
  </section>

  <section class="grid split" style="margin-bottom:.9rem" id="basinMapSection">
    <article class="card">
      <h2>Mapa · bacia Taquari–Antas (G040)</h2>
      <p class="muted" id="mapFramingNote" style="margin:.15rem 0 .55rem"></p>
      <div class="chips" id="roleChips"></div>
      <div id="map"></div>
      <div class="inspector" id="pointInspector">
        <h3 id="inspectorTitle">Curva do ponto</h3>
        <p class="empty" id="inspectorEmpty">Clique numa âncora (ou na lista) para ver a curva / hietograma.</p>
        <div id="inspectorBody" hidden>
          <p class="muted" id="inspectorMeta"></p>
          <svg class="mini-chart" id="inspectorChart" viewBox="0 0 520 168" role="img" aria-label="Curva do ponto selecionado"></svg>
          <p class="chart-caption" id="inspectorNote"></p>
        </div>
      </div>
    </article>
    <article class="card">
      <h2>Inventário por UG</h2>
      <p class="muted">7 UGs da G040. As 3 fora do gêmeo (Guaporé, Forqueta, Baixo) aparecem sem ΔN HEC inventado.</p>
      <div class="ug-inventory" id="ugInventory"></div>
      <h2 style="margin-top:1rem">Pontos de amarração (produto)</h2>
      <p class="muted">Âncoras curadas do gêmeo Muçum. Clique para focar e abrir a curva.</p>
      <div class="chips" id="roleChipsSide"></div>
      <div class="anchor-list" id="anchorList"></div>
      <div class="links" id="artifactLinks"></div>
    </article>
  </section>

  <section class="card" style="margin-bottom:.9rem" id="corridorCard">
    <h2>Produto gêmeo · corredor até Muçum</h2>
    <p class="muted" id="corridorNote">Produto dentro da bacia G040 · cinco sub-bacias aninhadas · análogos.</p>
    <div class="chips" id="corridorChips"></div>
    <div class="chips" id="ugDomainChips" style="margin-top:.35rem"></div>
    <p class="muted mono" id="corridorMeta" style="margin-top:.55rem"></p>
  </section>

  <section class="grid metrics" style="margin-bottom:.9rem" id="productMetrics">
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

  <section class="card" style="margin-bottom:.9rem" id="skillCard">
    <h2>Validação · self-fit vs LOO por evento</h2>
    <p class="muted" id="skillVerdict">Hindcast leave-one-out: onde o gêmeo acerta e onde erra.</p>
    <div class="skill-summary" id="skillSummary"></div>
    <div style="overflow-x:auto">
      <table class="skill-table" id="skillTable">
        <thead>
          <tr>
            <th>Evento</th><th>Chuva mm</th><th>Self-fit</th><th>NSE LOO</th><th>|err| ΔN cm</th><th>err ΔN %</th><th>err pico Q %</th><th>Tag</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
    <ol class="lessons" id="skillLessons"></ol>
  </section>

  <section class="card" style="margin-bottom:.9rem">
    <h2>Traço do evento · hidrograma + chuva</h2>
    <p class="muted" id="chartCaption">Série do live eval (quando disponível) ou amostra do forward.</p>
    <div class="chart-wrap">
      <svg class="chart" id="eventChart" viewBox="0 0 960 280" role="img" aria-label="Hidrograma do evento"></svg>
    </div>
    <p class="chart-caption" id="chartNote"></p>
  </section>

  <section class="card">
    <h2>Como o robô alimenta esta página</h2>
    <ol class="muted" id="robotSteps"></ol>
    <p class="foot">
      Sujeito espacial = bacia Taquari–Antas (G040, 7 UGs). Produto = gêmeo Python HMS-like
      no corredor até Muçum (Alto+Prata+Carreiro+Médio) — não HEC-HMS binário, não RAS, não CWMS,
      e ainda não calibração da G040 inteira. Guaporé/Forqueta/Baixo no inventário, fora do balanço.
      IFS = proxy pontual. Validação honesta = LOO (não self-fit). STZ sem curva N↔Q inventada.
      Pesquisa, não alerta.
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

const UG_COLORS = {
  "Alto Taquari-Antas": "#3d6b58",
  "Prata": "#2f6b54",
  "Carreiro": "#4a7a62",
  "Médio Taquari-Antas": "#1f5a46",
  "Guaporé": "#9a6b2f",
  "Forqueta": "#5a6e8a",
  "Baixo Taquari-Antas": "#6a7a8e"
};

function ugColor(name, fallback) {
  return UG_COLORS[name] || fallback || "#6a7f72";
}

function renderUgInventory() {
  const el = document.getElementById("ugInventory");
  if (!el) return;
  const inv = ((DATA.spatial || {}).inventory_stats) || {};
  const by = inv.by_ug || {};
  const names = Object.keys(by).sort(function(a, b) {
    const oa = by[a].in_twin_domain ? 0 : 1;
    const ob = by[b].in_twin_domain ? 0 : 1;
    if (oa !== ob) return oa - ob;
    return a.localeCompare(b, "pt-BR");
  });
  if (!names.length) {
    el.innerHTML = "<p class=\"muted\">Inventário por UG indisponível neste build.</p>";
    return;
  }
  el.innerHTML = names.map(function(name) {
    const row = by[name] || {};
    const twin = !!row.in_twin_domain;
    const area = row.area_km2_approx != null ? fmt(row.area_km2_approx, 0) + " km²" : "área —";
    const badge = twin ? "gêmeo" : "inventário · sem HEC";
    return "<div class=\"ug-row " + (twin ? "twin" : "inventory") + "\">" +
      "<div class=\"name\"><span><i class=\"swatch\" style=\"background:" + ugColor(name) + "\"></i>" + name +
      "</span><span class=\"meta\">" + badge + "</span></div>" +
      "<div class=\"meta\">" + area + " · flu " + fmt(row.flu, 0) +
      " · chuva " + fmt(row.rain, 0) + " · total " + fmt(row.total, 0) + "</div>" +
      "</div>";
  }).join("");
}

function renderUgDomainChips() {
  const el = document.getElementById("ugDomainChips");
  if (!el) return;
  const fr = ((DATA.spatial || {}).basin_framing) || {};
  const twin = fr.twin_domain_ugs || (DATA.spatial || {}).ug_twin_domain || [];
  const excl = fr.excluded_ugs || [];
  el.innerHTML = "";
  twin.forEach(function(ug) {
    const b = document.createElement("span");
    b.className = "chip";
    b.style.cursor = "default";
    b.style.borderColor = ugColor(ug);
    b.textContent = ug.replace(" Taquari-Antas", "") + " · gêmeo";
    el.appendChild(b);
  });
  excl.forEach(function(ug) {
    const b = document.createElement("span");
    b.className = "chip";
    b.style.cursor = "default";
    b.style.borderColor = ugColor(ug);
    b.textContent = ug.replace(" Taquari-Antas", "") + " · inventário";
    b.title = "UG da bacia G040 · fora do balanço HEC até Muçum";
    el.appendChild(b);
  });
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
    "<span class=\"mono\">" + (live.artifact || "live_eval") + "</span>" +
    "<span class=\"badge-n1\">verify n=1</span><br/>" +
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
  ["Mapa UGs", local.mapa_subbacias],
  ["Multi-exutório", local.multi_outlet_html]
].forEach(function(pair) {
  if (!pair[1]) return;
  const a = document.createElement("a");
  a.href = pair[1];
  a.textContent = pair[0];
  links.appendChild(a);
});

function drawSeriesSvg(svg, series, rain, opts) {
  opts = opts || {};
  const W = opts.W || 960, H = opts.H || 280;
  const pad = opts.pad || {l:54, r:18, t:18, b:36};
  if (!series || !series.length) {
    svg.innerHTML = "<text x=\"24\" y=\"" + (H/2) + "\" fill=\"#4a6356\">Sem série para plotar.</text>";
    return;
  }
  const innerW = W - pad.l - pad.r, innerH = H - pad.t - pad.b;
  const mode = opts.mode || "level";
  const ys = series.map(function(p){ return Number(p.n_cm); }).filter(function(v){ return !Number.isNaN(v); });
  const yMin = mode === "rain" ? 0 : Math.min.apply(null, ys.concat([0]));
  const yMax = mode === "rain"
    ? Math.max.apply(null, (rain || []).concat([1]))
    : Math.max.apply(null, ys.concat([1]));
  const xAt = function(i, n){ return pad.l + (i / Math.max(n - 1, 1)) * innerW; };
  const yAt = function(v){ return pad.t + (1 - ((v - yMin) / (yMax - yMin || 1))) * innerH; };
  let path = "";
  if (mode !== "rain") {
    series.forEach(function(p, i) {
      const x = xAt(i, series.length), y = yAt(Number(p.n_cm));
      path += (i ? " L " : "M ") + x.toFixed(1) + " " + y.toFixed(1);
    });
  }
  const rainArr = rain || [];
  const rainMax = Math.max.apply(null, rainArr.concat([1]));
  let bars = "";
  rainArr.forEach(function(v, i) {
    const h = (Number(v) / rainMax) * (mode === "rain" ? innerH * 0.92 : innerH * 0.28);
    const x = xAt(i, Math.max(rainArr.length, series.length));
    const bw = Math.max(1.6, innerW / Math.max(rainArr.length, 1) * 0.5);
    const y0 = mode === "rain" ? (pad.t + innerH - h) : (pad.t + 4);
    bars += "<rect x=\"" + (x - bw/2).toFixed(1) + "\" y=\"" + y0.toFixed(1) +
      "\" width=\"" + bw.toFixed(1) + "\" height=\"" + h.toFixed(1) +
      "\" fill=\"rgba(29,107,159," + (mode === "rain" ? "0.42" : "0.22") + ")\"></rect>";
  });
  const grid = [];
  for (let g = 0; g < 4; g++) {
    const yy = pad.t + (innerH * g / 3);
    const val = yMax - (yMax - yMin) * g / 3;
    grid.push("<line x1=\"" + pad.l + "\" x2=\"" + (W-pad.r) + "\" y1=\"" + yy + "\" y2=\"" + yy + "\" stroke=\"#d7e2db\"/>");
    grid.push("<text x=\"8\" y=\"" + (yy+4) + "\" fill=\"#4a6356\" font-size=\"10\">" + val.toFixed(0) + "</text>");
  }
  const stroke = opts.stroke || "#0f5c45";
  svg.innerHTML = grid.join("") + bars +
    (path ? ("<path d=\"" + path + "\" fill=\"none\" stroke=\"" + stroke + "\" stroke-width=\"1.7\" stroke-linecap=\"round\" stroke-linejoin=\"round\"></path>") : "") +
    "<text x=\"" + pad.l + "\" y=\"" + (H-8) + "\" fill=\"#4a6356\" font-size=\"10\">" +
    (series[0] && series[0].t ? series[0].t : "") + "</text>" +
    "<text x=\"" + (W-pad.r) + "\" y=\"" + (H-8) + "\" fill=\"#4a6356\" font-size=\"10\" text-anchor=\"end\">" +
    (series[series.length-1] && series[series.length-1].t ? series[series.length-1].t : "") + "</text>";
}

function drawChart() {
  const svg = document.getElementById("eventChart");
  const note = document.getElementById("chartNote");
  const trace = DATA.event_trace || {};
  const series = trace.series || [];
  const rain = trace.rain_mm || [];
  drawSeriesSvg(svg, series, rain, {W:960, H:280, mode:"level"});
  document.getElementById("chartCaption").textContent =
    "Fonte do traço: " + (trace.source || "—") + (trace.note ? " · " + trace.note : "");
  note.textContent = "Linha = nível estimado em Muçum (cm). Barras = chuva proxy areal ponderada (mm).";
}

function showInspector(anchor, kind) {
  const empty = document.getElementById("inspectorEmpty");
  const body = document.getElementById("inspectorBody");
  const title = document.getElementById("inspectorTitle");
  const meta = document.getElementById("inspectorMeta");
  const note = document.getElementById("inspectorNote");
  const svg = document.getElementById("inspectorChart");
  const trace = DATA.event_trace || {};
  const series = trace.series || [];
  const rain = trace.rain_mm || [];
  empty.hidden = true;
  body.hidden = false;
  const label = (anchor && (anchor.label || anchor.name)) || (anchor && anchor.code) || "Ponto";
  title.textContent = label;
  if (kind === "network") {
    meta.textContent = (anchor.kind === "rain" ? "chuva inventário" : "flu inventário") +
      (anchor.ug ? " · " + anchor.ug : "") + " · " + (anchor.code || "");
    svg.innerHTML = "<text x=\"18\" y=\"84\" fill=\"#4a6356\" font-size=\"12\">Ponto de inventário — sem série do gêmeo neste build.</text>";
    note.textContent = "Use as âncoras curadas para abrir hidrograma / hietograma do evento.";
    return;
  }
  const role = anchor.role;
  const rainWin = anchorRain(anchor);
  meta.textContent = (anchor.role_pt || roleLabel(role)) +
    (anchor.ug ? " · " + anchor.ug : "") +
    " · " + (anchor.code || "") +
    (rainWin != null ? " · chuva UG " + Number(rainWin).toFixed(1) + " mm" : "");
  if (role === "target") {
    drawSeriesSvg(svg, series, rain, {W:520, H:168, pad:{l:40,r:12,t:12,b:28}, mode:"level", stroke:"#0f5c45"});
    note.textContent = "Curva do produto: N estimado em Muçum + chuva proxy da janela.";
  } else if (role === "level_control") {
    drawSeriesSvg(svg, series, rain, {W:520, H:168, pad:{l:40,r:12,t:12,b:28}, mode:"level", stroke:"#1d4f91"});
    note.textContent = "STZ = controle de nível (sem curva N↔Q inventada). Traço exibido = produto Muçum da mesma janela, só para contexto temporal.";
  } else if (role === "rain") {
    const rainSeries = rain.map(function(v, i) {
      return {t: (series[i] && series[i].t) || ("i"+i), n_cm: Number(v) || 0};
    });
    drawSeriesSvg(svg, rainSeries, rain, {W:520, H:168, pad:{l:40,r:12,t:12,b:28}, mode:"rain"});
    note.textContent = "Hietograma proxy da janela (IFS pontual por sub-bacia — ainda não máscara areal ECMWF/REC).";
  } else {
    drawSeriesSvg(svg, series, rain, {W:520, H:168, pad:{l:40,r:12,t:12,b:28}, mode:"level", stroke:"#5a6570"});
    note.textContent = "Monitor de montante: série do produto Muçum na janela (contexto). Sem curva local inventada.";
  }
}

const anchors = ((DATA.spatial || {}).anchors) || [];
const roleChips = document.getElementById("roleChips");
const roles = ["all"].concat(Array.from(new Set(anchors.map(function(a){ return a.role; }))));
let activeRole = "all";
let activeId = null;
const list = document.getElementById("anchorList");
const _bb0 = (((DATA.spatial || {}).basin_framing) || {}).g040_bbox_latlon;
const _center = _bb0 && _bb0.length === 2
  ? [(_bb0[0][0] + _bb0[1][0]) / 2, (_bb0[0][1] + _bb0[1][1]) / 2]
  : [-29.05, -51.35];
const map = L.map("map", {scrollWheelZoom:true}).setView(_center, 8);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, referrerPolicy:'strict-origin-when-cross-origin', attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
const basinLayer = L.layerGroup().addTo(map);
const ugLayer = L.layerGroup().addTo(map);
const fozLayer = L.layerGroup().addTo(map);
const rainLayer = L.layerGroup().addTo(map);
const networkLayer = L.layerGroup(); // G040 inventory — off by default (UG polygons first)
const anchorLayer = L.layerGroup().addTo(map);
const markers = {};

(function fillMapFraming() {
  const fr = ((DATA.spatial || {}).basin_framing) || {};
  const el = document.getElementById("mapFramingNote");
  if (!el) return;
  el.textContent =
    "Bacia: " + (fr.g040_label_pt || "G040") + " (~" + fmt(fr.g040_km2, 0) + " km², 7 UGs) · " +
    "produto gêmeo: corredor até Muçum (~" + fmt(fr.twin_domain_km2, 0) + " km²) · " +
    "no mapa da bacia também: " + ((fr.excluded_ugs || []).join(", ") || "—") + " · rede G040 desligada por padrão (ligue no controle de camadas).";
})();

const legend = L.control({position:"bottomright"});
legend.onAdd = function() {
  const d = L.DomUtil.create("div", "legend");
  d.innerHTML =
    "<div><i style=\"background:#0f5c45\"></i>alvo Muçum</div>" +
    "<div><i style=\"background:#1d4f91\"></i>nível / controle</div>" +
    "<div><i style=\"background:#9a6b2f\"></i>Guaporé</div>" +
    "<div><i style=\"background:#5a6e8a\"></i>Forqueta</div>" +
    "<div><i style=\"background:#6a7a8e\"></i>Baixo</div>" +
    "<div><i style=\"background:#b8892d\"></i>foz BHO6</div>" +
    "<div style=\"margin-top:.25rem\">fill colorido = 7 UGs · contorno = produto gêmeo</div>";
  return d;
};
legend.addTo(map);
L.control.layers(null, {
  "Bacia G040":basinLayer,
  "Produto gêmeo":ugLayer,
  "Fozes BHO6":fozLayer,
  "Chuva IFS":rainLayer,
  "Rede G040":networkLayer,
  "Âncoras":anchorLayer
}, {collapsed:false}).addTo(map);

function renderChips() {
  roleChips.innerHTML = "";
  roles.forEach(function(r) {
    const b = document.createElement("button");
    b.className = "chip" + (r === activeRole ? " active" : "");
    b.type = "button";
    b.textContent = r === "all" ? "todos" : roleLabel(r);
    b.onclick = function(){ activeRole = r; renderChips(); renderAnchors(); };
    roleChips.appendChild(b);
  });
}

function renderNetwork() {
  networkLayer.clearLayers();
  const net = ((DATA.spatial || {}).basin_network)
    || ((DATA.spatial || {}).corridor_network)
    || {};
  const feats = net.features || [];
  feats.forEach(function(f) {
    const p = f.properties || {};
    const c = (f.geometry && f.geometry.coordinates) || [];
    if (c.length < 2) return;
    const isRain = p.kind === "rain";
    const inTwin = !!p.in_twin_domain;
    const base = ugColor(p.ug, inTwin ? "#9aa3aa" : "#b8a890");
    const m = L.circleMarker([c[1], c[0]], {
      radius: isRain ? 2.1 : 2.45,
      color: "rgba(255,255,255,0.35)",
      weight: 0.55,
      fillColor: base,
      fillOpacity: inTwin ? 0.28 : 0.48
    });
    m.on("click", function() {
      showInspector({
        label: p.name || p.code,
        name: p.name,
        code: p.code,
        ug: p.ug,
        kind: p.kind,
        role: "network"
      }, "network");
    });
    m.bindPopup(
      "<strong>" + (p.name || p.code) + "</strong><br/>" +
      (isRain ? "chuva inventário" : "flu inventário") +
      (p.ug ? " · " + p.ug : "") +
      (inTwin ? " · corredor gêmeo" : " · bacia G040 (fora do gêmeo Muçum)") +
      "<br/>" + (p.code || "")
    );
    m.addTo(networkLayer);
  });
}



function renderMultiOutlet() {
  const mo = ((DATA.products || {}).g040_multi_outlet) || {};
  const lede = document.getElementById("multiOutletLede");
  if (lede && mo.purpose_pt) lede.textContent = mo.purpose_pt;
  const enc = mo.encantado || {};
  const sum = enc.summary || {};
  const verd = enc.verdict || {};
  const contrast = document.getElementById("encantadoContrast");
  if (contrast) {
    contrast.innerHTML =
      "<span>Encantado self-fit <strong>" + fmt(sum.mean_self_fit_nse, 2) + "</strong></span>" +
      "<span>≠</span>" +
      "<span>NSE LOO <strong>" + fmt(sum.mean_nse_loo, 2) + "</strong></span>" +
      "<span class=\"muted\">" + (verd.plain_pt || "Muçum roteado + residual Guaporé vs Q ANA Encantado.") + "</span>";
  }
  const inv = document.getElementById("outletInventory");
  if (inv) {
    const outlets = mo.outlets || [];
    inv.innerHTML = outlets.map(function(o) {
      const ok = (o.status || "").indexOf("calibrated") >= 0;
      const cls = ok ? "twin" : "inventory";
      const badge = ok ? "calibrado" : (o.status || "gated");
      return "<div class=\"ug-row " + cls + "\">" +
        "<div class=\"name\"><span>" + (o.label_pt || o.outlet_id) +
        " · <span class=\"mono\">" + (o.station_code || "") + "</span></span>" +
        "<span class=\"meta\">" + badge + "</span></div>" +
        "<div class=\"meta\">" + fmt(o.nested_area_km2, 0) + " km² · " +
        ((o.ugs || []).join(", ")) + "</div>" +
        "<div class=\"meta\">" + (o.note_pt || o.blocker_pt || "") + "</div></div>";
    }).join("");
  }
  const next = document.getElementById("multiOutletNext");
  if (next) {
    next.innerHTML = "";
    (mo.blocked_next || []).forEach(function(line) {
      const li = document.createElement("li");
      li.textContent = line;
      next.appendChild(li);
    });
  }
}

function renderMethodology() {
  const m = DATA.methodology || {};
  const lede = document.getElementById("methodLede");
  if (lede) {
    lede.textContent = m.family_arm_pt
      ? (m.family_arm_pt + " · " + (m.domain_pt || ""))
      : "Braço da família HEC/REC, domínio e validação — sem overclaim.";
  }
  const grid = document.getElementById("methodGrid");
  if (!grid) return;
  const events = m.events || {};
  const core = (events.core || []).join(", ") || "—";
  const marginal = (events.marginal || []).join(", ") || "—";
  const failed = (events.failed || []).join(", ") || "—";
  const notList = (m.not_pt || []).map(function(x){ return "<li>" + x + "</li>"; }).join("");
  const points = (m.forcing_point_map || []).map(function(p){
    return "<li><span class=\"mono\">" + (p.subbasin_id || "") + "</span> → " +
      (p.point_code || "—") + (p.label ? " (" + p.label + ")" : "") + "</li>";
  }).join("");
  grid.innerHTML =
    "<div class=\"box\"><h3>Motor e forçante</h3><ul>" +
      "<li><strong>Motor:</strong> " + (m.engine_name || "python HMS-like") +
        (m.not_hec_hms_binary ? " · não binário HEC-HMS" : "") + "</li>" +
      "<li><strong>Métodos:</strong> " + ((m.methods || []).join(" · ") || "—") + "</li>" +
      "<li>" + (m.why_pt || "") + "</li>" +
      "<li>" + (m.forcing_pt || "IFS pontual") + "</li>" +
      "<li>" + (m.transfer_pt || "análogos LOO") + "</li>" +
      "<li>" + (m.rating_pt || "curva oficial Muçum") + "</li>" +
    "</ul></div>" +
    "<div class=\"box\"><h3>Eventos e limites</h3><ul>" +
      "<li><strong>Core:</strong> " + core + (events.core_rule_pt ? " <em>(" + events.core_rule_pt + ")</em>" : "") + "</li>" +
      "<li><strong>Marginais:</strong> " + marginal + "</li>" +
      "<li><strong>Falha:</strong> " + failed + "</li>" +
      "<li>" + (m.live_verify_pt || "Live verify n=1") + "</li>" +
    "</ul>" +
    (notList ? "<p class=\"muted\" style=\"margin:.45rem 0 .2rem\">Isto não é</p><ul>" + notList + "</ul>" : "") +
    (points ? "<h3 style=\"margin-top:.55rem\">Proxy IFS por sub-bacia</h3><ul>" + points + "</ul>" : "") +
    "</div>";
}

function renderSkill() {
  const skill = ((DATA.products || {}).hindcast_skill) || {};
  const verdictEl = document.getElementById("skillVerdict");
  const sumEl = document.getElementById("skillSummary");
  const tbody = document.querySelector("#skillTable tbody");
  const lessonsEl = document.getElementById("skillLessons");
  if (!tbody) return;
  const summary = skill.summary || {};
  const verdict = skill.verdict || {};
  if (verdictEl) {
    verdictEl.textContent = verdict.plain_pt || skill.method_pt ||
      "Hindcast leave-one-out: onde o gêmeo acerta e onde erra.";
  }
  if (sumEl) {
    sumEl.innerHTML =
      "<span><strong>" + fmt(summary.n_scored, 0) + "</strong> eventos LOO</span>" +
      "<span>self-fit médio <strong>" + fmt(summary.mean_self_fit_nse, 2) + "</strong></span>" +
      "<span>NSE LOO médio <strong>" + fmt(summary.mean_nse_loo, 2) + "</strong></span>" +
      "<span>ΔN rel médio <strong>" + fmt((summary.mean_rise_n_rel_err || 0) * 100, 0) + "%</strong></span>" +
      "<span>pico Q |err| médio <strong>" + fmt((summary.mean_peak_q_rel_err || 0) * 100, 0) + "%</strong></span>";
  }
  const contrastEl = document.getElementById("skillContrast");
  if (contrastEl) {
    contrastEl.innerHTML =
      "<span>Self-fit biblioteca <strong>" + fmt(summary.mean_self_fit_nse, 2) + "</strong></span>" +
      "<span>≠</span>" +
      "<span>NSE LOO transferência <strong>" + fmt(summary.mean_nse_loo, 2) + "</strong></span>" +
      "<span class=\"muted\">" + (summary.contrast_pt || skill.method_pt ||
        "Self-fit mede ajuste no próprio evento; LOO mede previsão por análogo.") + "</span>";
  }
  tbody.innerHTML = "";
  (skill.events || []).forEach(function(e) {
    const tr = document.createElement("tr");
    tr.className = "tag-" + (e.tag || "ok");
    tr.innerHTML =
      "<td>" + (e.event_id || "—") + "</td>" +
      "<td>" + fmt(e.rain_mm_aw, 0) + "</td>" +
      "<td>" + fmt(e.self_fit_nse, 2) + "</td>" +
      "<td>" + fmt(e.nse_loo, 2) + "</td>" +
      "<td>" + fmt(e.rise_n_abs_err_cm, 0) + "</td>" +
      "<td>" + fmt((e.rise_n_rel_err || 0) * 100, 0) + "%</td>" +
      "<td>" + fmt((e.peak_q_rel_err || 0) * 100, 0) + "%</td>" +
      "<td>" + (e.tag || "ok") + "</td>";
    tbody.appendChild(tr);
  });
  if (lessonsEl) {
    lessonsEl.innerHTML = "";
    (((skill.calibration || {}).lessons_pt) || []).forEach(function(line) {
      const li = document.createElement("li");
      li.textContent = line;
      lessonsEl.appendChild(li);
    });
  }
}

function selectAnchor(a) {
  activeId = a.code || a.id;
  showInspector(a, "anchor");
  renderAnchors();
  map.setView([a.lat, a.lon], 11, {animate:true});
  if (markers[activeId]) markers[activeId].openPopup();
}

function delicateRadius(role) {
  if (role === "target") return 5.2;
  if (role === "level_control") return 4.4;
  if (role === "rain") return 3.4;
  return 3.8;
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
    item.onclick = function() { selectAnchor(a); };
    list.appendChild(item);
    const m = L.circleMarker([a.lat, a.lon], {
      radius: delicateRadius(a.role),
      color: "rgba(255,255,255,0.55)",
      weight: 1,
      fillColor: roleColor(a.role),
      fillOpacity: a.role === "target" ? 0.78 : 0.62
    });
    m.bindPopup(
      "<strong>" + (a.label || a.name) + "</strong><br/>" +
      (a.role_pt || roleLabel(a.role)) + "<br/>" + (a.name || "") + " · " + id +
      (rain != null ? "<br/>chuva janela: " + Number(rain).toFixed(1) + " mm" : "") +
      "<br/><em>clique no ponto para a curva</em>"
    );
    m.on("click", function() { selectAnchor(a); });
    m.addTo(anchorLayer);
    markers[id] = m;
  });
}

function rainColor(mm) {
  if (mm == null) return "#7a9e8c";
  if (mm < 10) return "#6f9e86";
  if (mm < 25) return "#3f7f64";
  if (mm < 40) return "#2f6b54";
  return "#1f5a46";
}
function rainRadius(mm) {
  const v = Math.max(0, Number(mm) || 0);
  return Math.max(3.2, Math.min(6.5, 3.2 + Math.sqrt(v) * 0.45));
}

((((DATA.spatial || {}).rain_geojson) || {}).features || []).forEach(function(f) {
  const pr = f.properties || {};
  const coords = (f.geometry && f.geometry.coordinates) || [];
  if (coords.length < 2) return;
  const mm = pr.total_mm;
  L.circleMarker([coords[1], coords[0]], {
    radius: rainRadius(mm),
    color: "rgba(255,255,255,0.4)",
    weight: 0.8,
    fillColor: rainColor(mm),
    fillOpacity: 0.55
  }).bindPopup(
    "<strong>" + (pr.label || pr.subbasin_id || "") + "</strong><br/>total " + fmt(mm,1) + " mm" +
    "<br/>passado " + fmt(pr.past_mm,1) + " · futuro " + fmt(pr.future_mm,1) +
    "<br/><span style=\"opacity:.8\">proxy pontual IFS (não máscara areal)</span>"
  ).addTo(rainLayer);
});

function fozPositionPt(pos) {
  if (pos === "upstream_or_at_antas") return "montante / na Antas (dentro do gêmeo)";
  if (pos === "between_antas_and_santa_tereza") return "entre Antas e Santa Tereza (dentro do gêmeo)";
  if (pos === "downstream_of_mucum") return "jusante de Muçum · fora do gêmeo";
  return pos || "posição vs Muçum desconhecida";
}

async function loadFozes() {
  const path = (DATA.spatial || {}).fozes_geojson;
  if (!path) return;
  try {
    const res = await fetch(path);
    if (!res.ok) return;
    const geo = await res.json();
    L.geoJSON(geo, {
      pointToLayer: function(feat, latlng) {
        const p = feat.properties || {};
        const downstream = String(p.position_vs_controls || "").indexOf("downstream") >= 0;
        return L.circleMarker(latlng, {
          radius: 4.2,
          color: "rgba(255,255,255,0.55)",
          weight: 1,
          fillColor: downstream ? "#a67c2a" : "#8a6a28",
          fillOpacity: 0.72
        });
      },
      onEachFeature: function(feat, lyr) {
        const p = feat.properties || {};
        const delta = p.delta_vs_mucum_km2;
        lyr.bindPopup(
          "<strong>" + (p.label || p.name || "Foz BHO6") + "</strong><br/>" +
          fozPositionPt(p.position_vs_controls) +
          (delta != null ? "<br/>Δ área vs Muçum: " + Number(delta).toFixed(0) + " km²" : "") +
          "<br/><span style=\"opacity:.8\">marca topológica — não é âncora do gêmeo</span>"
        );
      }
    }).addTo(fozLayer);
  } catch (e) {}
}

async function loadUgs() {
  const path = (DATA.spatial || {}).ug_geojson;
  if (!path) return;
  try {
    const res = await fetch(path);
    if (!res.ok) return;
    const geo = await res.json();
    const rainByUg = (DATA.spatial || {}).ug_rain_mm || {};
    const twinSet = new Set(
      (DATA.spatial || {}).ug_twin_domain
      || ((DATA.spatial || {}).basin_framing || {}).twin_domain_ugs
      || []
    );
    const g040Set = new Set(
      (DATA.spatial || {}).ug_basin
      || (DATA.spatial || {}).ug_g040
      || (DATA.spatial || {}).ug_filter
      || []
    );

    // Primary subject: full G040 basin (all 7 UGs), visible fill.
    L.geoJSON(geo, {
      filter: function(feat) {
        const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "";
        if (g040Set.size) return g040Set.has(name);
        return true;
      },
      style: function(feat) {
        const name = (feat.properties && feat.properties.sub_bacia) || "";
        const inTwin = twinSet.has(name);
        const fill = ugColor(name, inTwin ? "#3d6b58" : "#6a7f72");
        return {
          color: inTwin ? "#1f4a3a" : fill,
          weight: inTwin ? 1.15 : 1.35,
          dashArray: inTwin ? null : "4 3",
          fillColor: fill,
          fillOpacity: inTwin ? 0.10 : 0.16
        };
      },
      onEachFeature: function(feat, lyr) {
        const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "UG";
        const inTwin = twinSet.has(name);
        const inv = ((((DATA.spatial || {}).inventory_stats) || {}).by_ug || {})[name] || {};
        const area = (feat.properties && feat.properties.area_km2_approx) || inv.area_km2_approx;
        lyr.bindPopup("<strong>" + name + "</strong><br/>" +
          (inTwin
            ? "UG da bacia · também no produto gêmeo (corredor Muçum)"
            : "UG da bacia G040 · inventário · sem forçante HEC até Muçum") +
          (area != null ? "<br/>área ~" + Number(area).toFixed(0) + " km²" : "") +
          (inv.total != null ? "<br/>rede: flu " + inv.flu + " · chuva " + inv.rain + " · total " + inv.total : "") +
          (rainByUg[name] != null
            ? "<br/>chuva proxy produto: " + Number(rainByUg[name]).toFixed(1) + " mm"
            : (inTwin ? "" : "<br/><em>sem ug_rain_mm HEC (fora do domínio)</em>")));
      }
    }).addTo(basinLayer);

    // Secondary overlay: twin product domain outline.
    L.geoJSON(geo, {
      filter: function(feat) {
        const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "";
        if (twinSet.size) return twinSet.has(name);
        return /Alto Taquari|Prata|Carreiro|M[eé]dio Taquari/i.test(name);
      },
      style: function() {
        return {color:"#1f4a3a", weight:2.0, fillColor:"#1f4a3a", fillOpacity:0.04};
      },
      onEachFeature: function(feat, lyr) {
        const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "UG";
        const rain = rainByUg[name];
        lyr.bindPopup("<strong>" + name + "</strong><br/>produto gêmeo · corredor até Muçum" +
          (rain != null ? "<br/>chuva proxy: " + Number(rain).toFixed(1) + " mm" : ""));
      }
    }).addTo(ugLayer);

    try {
      const g040SetLocal = g040Set;
      const filtered = {
        type: "FeatureCollection",
        features: (geo.features || []).filter(function(feat) {
          const name = (feat.properties && (feat.properties.sub_bacia || feat.properties.nome)) || "";
          return !g040SetLocal.size || g040SetLocal.has(name);
        })
      };
      map.fitBounds(L.geoJSON(filtered).getBounds().pad(0.05));
    } catch (e) {
      const bb = (((DATA.spatial || {}).basin_framing) || {}).g040_bbox_latlon;
      if (bb && bb.length === 2) {
        map.fitBounds(bb, {padding:[28,28]});
      } else {
        const pts = [];
        const net = ((DATA.spatial || {}).basin_network) || {};
        (net.features || []).forEach(function(f) {
          const c = (f.geometry && f.geometry.coordinates) || [];
          if (c.length >= 2) pts.push([c[1], c[0]]);
        });
        if (pts.length) map.fitBounds(pts, {padding:[28,28]});
      }
    }
  } catch (e) {}
}

(function fillCorridor() {
  const c = DATA.corridor || {};
  const note = document.getElementById("corridorNote");
  const chips = document.getElementById("corridorChips");
  const meta = document.getElementById("corridorMeta");
  if (!chips) return;
  if (note) {
    note.textContent = (c.label_pt || "Produto gêmeo · corredor até Muçum") +
      (c.nested_area_km2 != null ? (" · ~" + Number(c.nested_area_km2).toFixed(0) + " km²") : "") +
      " · dentro da bacia G040 · não substitui a bacia inteira";
  }
  const rainBySb = {};
  ((((DATA.spatial || {}).rain_geojson) || {}).features || []).forEach(function(f) {
    const p = f.properties || {};
    if (p.subbasin_id) rainBySb[p.subbasin_id] = p.total_mm;
  });
  (c.subbasins || []).forEach(function(sb) {
    const b = document.createElement("span");
    b.className = "chip";
    b.style.cursor = "default";
    const mm = rainBySb[sb.id];
    b.textContent = sb.label + (mm != null ? (" · " + Number(mm).toFixed(0) + " mm") : "");
    b.title = sb.id + " · " + (sb.role || "");
    chips.appendChild(b);
  });
  if (meta) {
    const net = ((DATA.spatial || {}).basin_network)
      || ((DATA.spatial || {}).corridor_network)
      || {};
    const counts = net.counts || {};
    const fr = ((DATA.spatial || {}).basin_framing) || {};
    meta.textContent =
      "Bacia G040 · produto gêmeo UGs: " + ((fr.twin_domain_ugs || (DATA.spatial || {}).ug_twin_domain || []).join(", ")) +
      " · calibração: " + (c.calibration_method || "análogos") +
      " · saída " + (c.outlet_pt || "Muçum") +
      " · no mapa também: " + ((c.excluded_pt || fr.excluded_ugs || []).join(", ") || "—") +
      " · âncoras produto " + ((((DATA.spatial || {}).anchors) || []).length) +
      " · rede G040 " + (counts.total != null ? counts.total : "—");
  }
})();

drawChart();
renderChips();
renderAnchors();
renderNetwork();
renderMethodology();
renderMultiOutlet();
renderSkill();
renderUgInventory();
renderUgDomainChips();
loadUgs();
loadFozes();
setTimeout(function(){ map.invalidateSize(); }, 200);
</script>
</body>
</html>
"""
