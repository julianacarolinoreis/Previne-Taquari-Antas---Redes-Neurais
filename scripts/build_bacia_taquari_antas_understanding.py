#!/usr/bin/env python3
"""Build an audited first-principles understanding of the Taquari–Antas basin.

This does NOT calibrate HEC-HMS. It answers: what is the basin, where do the
major inflows enter, which gauges sit on which rivers, and how crude the
current 3-bucket HEC skeleton is relative to that structure.

Sources (local, already audited in-repo):
- BHO6 network clip: assets/data/hec_hms_integrated_taquari_antas/bho6_taquari_antas_network.geojson
- Network audit: assets/data/hec_hms_integrated_taquari_antas/network_audit_latest.json
- Basin screening stations: assets/data/research_basin_screening_latest.json
- Muçum watershed prep (SRTM): assets/data/hec_hms_spatialized_mucum/watershed_preparation_report.json
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GEOJSON = (
    ROOT
    / "assets"
    / "data"
    / "hec_hms_integrated_taquari_antas"
    / "bho6_taquari_antas_network.geojson"
)
NETWORK_AUDIT = (
    ROOT
    / "assets"
    / "data"
    / "hec_hms_integrated_taquari_antas"
    / "network_audit_latest.json"
)
BASIN_SCREENING = ROOT / "assets" / "data" / "research_basin_screening_latest.json"
WATERSHED_PREP = (
    ROOT
    / "assets"
    / "data"
    / "hec_hms_spatialized_mucum"
    / "watershed_preparation_report.json"
)
OUT_DIR = ROOT / "assets" / "data" / "bacia_taquari_antas"
MIN_JOIN_AREA_KM2 = 100.0
CONTROL_ORDER = ["86472000", "86472600", "86510000"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_indexes(geojson: dict[str, Any]) -> tuple[dict[int, dict], dict[int, list]]:
    by_fid: dict[int, dict] = {}
    by_dest: dict[int, list] = defaultdict(list)
    for feature in geojson["features"]:
        if feature["geometry"]["type"] == "Point":
            continue
        props = dict(feature["properties"])
        props["_geometry"] = feature["geometry"]
        fid = int(props["fid"])
        by_fid[fid] = props
        by_dest[int(props["nodestino"])].append(props)
    return by_fid, by_dest


def upstream_walk(start: dict, by_dest: dict[int, list]) -> list[dict]:
    pending = [start]
    seen: set[int] = set()
    out: list[dict] = []
    while pending:
        cur = pending.pop()
        fid = int(cur["fid"])
        if fid in seen:
            continue
        seen.add(fid)
        out.append(cur)
        for up in by_dest.get(int(cur["noorigem"]), []):
            pending.append(up)
    return out


def name_tributary_system(join: dict, upstream: list[dict]) -> dict[str, Any]:
    """Name without inventing hydronyms absent from BHO6."""
    named_areas: dict[str, float] = {}
    for seg in upstream:
        name = seg.get("noriocomp")
        if not name:
            continue
        area = float(seg.get("nuareamont") or 0)
        named_areas[name] = max(named_areas.get(name, 0.0), area)
    ranked = sorted(named_areas.items(), key=lambda kv: -kv[1])
    join_area = float(join.get("nuareamont") or 0)
    raw = join.get("noriocomp")
    code = str(join.get("cocursodag") or "")

    if raw:
        label = raw
        confidence = "join_segment_named"
    elif ranked and ranked[0][1] >= 0.5 * join_area:
        label = ranked[0][0]
        confidence = "dominant_named_upstream"
    elif ranked:
        # Large unnamed stem; keep system label + components.
        label = f"sistema BHO6 {code} (componentes: {', '.join(n for n, _ in ranked[:4])})"
        confidence = "unnamed_stem_with_named_components"
    else:
        label = f"afluente sem nome BHO6 {code}"
        confidence = "unnamed"

    return {
        "label": label,
        "confidence": confidence,
        "bho6_cocursodag": code,
        "named_components_top": [
            {"name": n, "max_upstream_area_km2": round(a, 2)} for n, a in ranked[:8]
        ],
    }


def position_vs_controls(mainstem_area: float | None, areas: dict[str, float]) -> str:
    if mainstem_area is None:
        return "unknown"
    if mainstem_area <= areas["86472000"] + 1:
        return "upstream_or_at_antas"
    if mainstem_area <= areas["86472600"] + 1:
        return "between_antas_and_santa_tereza"
    if mainstem_area <= areas["86510000"] + 1:
        return "between_santa_tereza_and_mucum"
    return "downstream_of_mucum"


def join_point_lonlat(join: dict) -> list[float] | None:
    geom = join.get("_geometry") or {}
    coords = geom.get("coordinates") or []
    if not coords:
        return None
    # LineString: use downstream end (last vertex) as confluence approximation.
    end = coords[-1]
    return [float(end[0]), float(end[1])]


def extract_joins(
    by_fid: dict[int, dict],
    by_dest: dict[int, list],
    control_areas: dict[str, float],
) -> list[dict[str, Any]]:
    main_nodes: set[int] = set()
    for props in by_fid.values():
        if str(props.get("cocursodag")) == "786":
            main_nodes.add(int(props["noorigem"]))
            main_nodes.add(int(props["nodestino"]))

    joins: list[dict[str, Any]] = []
    for props in by_fid.values():
        if str(props.get("cocursodag")) == "786":
            continue
        if int(props["nodestino"]) not in main_nodes:
            continue
        area = float(props.get("nuareamont") or 0)
        if area < MIN_JOIN_AREA_KM2:
            continue

        upstream = upstream_walk(props, by_dest)
        naming = name_tributary_system(props, upstream)
        dest = int(props["nodestino"])
        main_at = [
            m
            for m in by_fid.values()
            if str(m.get("cocursodag")) == "786"
            and (int(m["noorigem"]) == dest or int(m["nodestino"]) == dest)
        ]
        main_area = max((float(m.get("nuareamont") or 0) for m in main_at), default=None)
        lonlat = join_point_lonlat(props)
        joins.append(
            {
                "join_fid": int(props["fid"]),
                "join_area_km2": round(area, 2),
                "strahler": props.get("nustrahler"),
                "mainstem_area_at_join_km2": round(main_area, 2) if main_area else None,
                "position_vs_controls": position_vs_controls(main_area, control_areas),
                "confluence_lonlat": lonlat,
                "upstream_segments_in_clip": len(upstream),
                **naming,
            }
        )

    joins.sort(key=lambda item: -item["join_area_km2"])
    return joins


def summarize_positions(joins: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pos in [
        "upstream_or_at_antas",
        "between_antas_and_santa_tereza",
        "between_santa_tereza_and_mucum",
        "downstream_of_mucum",
        "unknown",
    ]:
        subset = [j for j in joins if j["position_vs_controls"] == pos]
        out[pos] = {
            "tributary_count_ge_100km2": len(subset),
            "sum_join_areas_km2": round(sum(j["join_area_km2"] for j in subset), 2),
            "top": [
                {
                    "label": j["label"],
                    "join_area_km2": j["join_area_km2"],
                    "confidence": j["confidence"],
                    "bho6_cocursodag": j["bho6_cocursodag"],
                }
                for j in subset[:8]
            ],
        }
    return out


def station_inventory(screening: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    stations: dict[str, dict[str, Any]] = {}
    for code, meta in audit.get("stations", {}).items():
        stations[code] = {
            "station_code": code,
            "name": meta.get("name"),
            "river": meta.get("role"),
            "role": meta.get("role"),
            "lon": meta.get("lon"),
            "lat": meta.get("lat"),
            "bho6_upstream_area_km2": round(
                float(meta.get("segment", {}).get("nuareamont") or 0), 3
            ),
            "source": "network_audit_latest.json",
        }

    for item in screening.get("basin", {}).get("upstream_gauges", {}).get("stations", []):
        code = str(item.get("station_code"))
        coords = item.get("coordinates") or {}
        entry = stations.get(code, {"station_code": code})
        entry.update(
            {
                "name": item.get("name") or entry.get("name"),
                "river": item.get("river") or entry.get("river"),
                "role_in_rna_contract": item.get("role"),
                "lat": coords.get("latitude") or entry.get("lat"),
                "lon": coords.get("longitude") or entry.get("lon"),
                "telemetry": item.get("telemetry"),
                "source": entry.get("source", "research_basin_screening_latest.json"),
            }
        )
        if "source" in entry and "screening" not in entry["source"]:
            entry["source"] = entry["source"] + "+screening"
        stations[code] = entry

    # Canonical control roles for the corridor studied so far.
    role_map = {
        "86472000": "controle no Rio das Antas (montante do corredor)",
        "86472600": "controle intermediário no Rio Taquari (Santa Tereza)",
        "86510000": "exutório de estudo atual (Muçum, Rio Taquari)",
        "86507000": "auxiliar no Rio Carreiro (afluente entre Antas e Santa Tereza)",
        "86125500": "auxiliar no Rio da Prata (sistema a montante de Antas)",
        "86125130": "auxiliar no Rio Ituim (sistema a montante de Antas)",
        "86298000": "auxiliar no Rio das Antas (UHE Castro Alves)",
        "86448000": "auxiliar no Rio das Antas (UHE Monte Claro)",
    }
    ordered: list[dict[str, Any]] = []
    for code in list(role_map) + sorted(set(stations) - set(role_map)):
        if code not in stations:
            continue
        row = stations[code]
        row["basin_role"] = role_map.get(code, "estação auxiliar / a inventariar")
        ordered.append(row)
    return ordered


def hec_gap_statement(
    control_areas: dict[str, float],
    joins: list[dict[str, Any]],
    positions: dict[str, Any],
) -> dict[str, Any]:
    carreiro = next(
        (j for j in joins if "Carreiro" in j["label"] or j["bho6_cocursodag"] == "7866"),
        None,
    )
    incr_stz = round(control_areas["86472600"] - control_areas["86472000"], 3)
    incr_mucum = round(control_areas["86510000"] - control_areas["86472600"], 3)
    return {
        "current_hec_skeleton": {
            "subbasins": 3,
            "reaches": 2,
            "buckets": [
                {
                    "id": "SB_ANTAS",
                    "area_km2": control_areas["86472000"],
                    "meaning": "quase toda a bacia a montante de Linha José Júlio",
                },
                {
                    "id": "SB_INC_STZ",
                    "area_km2": incr_stz,
                    "meaning": "incremento Antas→Santa Tereza",
                    "dominated_by": None
                    if carreiro is None
                    else {
                        "label": carreiro["label"],
                        "join_area_km2": carreiro["join_area_km2"],
                        "fraction_of_increment": round(
                            carreiro["join_area_km2"] / incr_stz, 3
                        ),
                    },
                },
                {
                    "id": "SB_INC_MUCUM",
                    "area_km2": incr_mucum,
                    "meaning": "incremento Santa Tereza→Muçum (sem afluente ≥100 km² no recorte)",
                },
            ],
        },
        "why_this_is_still_crude": [
            "O HEC atual não discretiza os afluentes a montante de Antas (Telha/Prata/Ituim, Tainhas, Refugiado, etc.).",
            "O incremento Santa Tereza é tratado como um balde genérico, embora ~90% da área seja o sistema do Rio Carreiro.",
            "Tributários BHO6 a montante de Muçum: milhares de trechos; o HEC usa 2 reaches no tronco.",
            "Santa Tereza ainda não tem vazão reconciliada — o ponto intermediário não valida a rede.",
            "Várias entradas da RNA (Carreiro, Prata, Ituim, UHEs) ainda não viram sub-bacias HEC.",
        ],
        "minimum_next_structure_before_recalibration": [
            "Manter tronco Antas → Santa Tereza → Muçum.",
            "Separar SB_INC_STZ em pelo menos: sistema Carreiro + residual lateral.",
            "Dentro de SB_ANTAS, abrir os sistemas ≥500 km² (código 7868/Prata-Ituim-Telha, Tainhas, Bururi, Refugiado) quando houver chuva/posto.",
            "Só então discutir parâmetros comuns — não antes de a estrutura refletir as entradas da bacia.",
        ],
        "tributaries_ge_100km2_in_clip": len(joins),
        "position_summary": {
            key: {
                "count": val["tributary_count_ge_100km2"],
                "sum_km2": val["sum_join_areas_km2"],
            }
            for key, val in positions.items()
            if val["tributary_count_ge_100km2"]
        },
    }


def write_html(report: dict[str, Any], path: Path) -> None:
    controls = report["controls"]
    joins = report["major_tributary_joins"]
    stations = report["stations"]
    gap = report["hec_structure_gap"]
    pos = report["joins_by_position"]

    def rows_joins(items: list[dict[str, Any]]) -> str:
        return "".join(
            f"<tr><td>{j['label']}</td><td class='num'>{j['join_area_km2']:,.1f}</td>"
            f"<td>{j['position_vs_controls']}</td><td>{j['bho6_cocursodag']}</td>"
            f"<td>{j['confidence']}</td></tr>"
            for j in items
        )

    def rows_stations(items: list[dict[str, Any]]) -> str:
        out = []
        for s in items:
            area = s.get("bho6_upstream_area_km2")
            area_txt = f"{area:,.1f}" if isinstance(area, (int, float)) and area else "—"
            out.append(
                "<tr>"
                f"<td><code>{s['station_code']}</code></td>"
                f"<td>{s.get('name') or '—'}</td>"
                f"<td>{s.get('river') or '—'}</td>"
                f"<td>{s.get('basin_role') or '—'}</td>"
                f"<td class='num'>{area_txt}</td>"
                "</tr>"
            )
        return "".join(out)

    carreiro = gap["current_hec_skeleton"]["buckets"][1].get("dominated_by") or {}
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Compreensão da bacia Taquari–Antas</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {{ --ink:#163043; --muted:#5d7380; --line:#d5e3e6; --panel:#fff; --accent:#0a6f9c; --warn:#9a5b12; --good:#0b7a68; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif;
      background:radial-gradient(1200px 600px at 10% -10%,#dff3f5 0%,transparent 55%), linear-gradient(160deg,#f4fbfb,#fff8f1 55%,#f7fafc); }}
    main {{ max-width:1180px; margin:auto; padding:28px 18px 64px; }}
    header, section {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:22px 24px; margin-bottom:16px; box-shadow:0 10px 28px #16304310; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,44px)/1.08 "Fraunces",Georgia,serif; }}
    h2 {{ margin:0 0 10px; font-size:1.25rem; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .meta, .muted {{ color:var(--muted); font-size:14px; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .ok {{ border-left-color:var(--good); background:#eefaf6; color:#0d5c50; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
    .stat {{ border:1px solid var(--line); border-radius:14px; padding:14px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:28px; color:var(--accent); }}
    .stat span {{ color:var(--muted); font-size:13px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ text-align:left; padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ background:#eef6f7; color:#355468; }}
    td.num, th.num {{ text-align:right; white-space:nowrap; }}
    #map {{ height:520px; border-radius:14px; border:1px solid var(--line); }}
    ul {{ margin:8px 0 0; padding-left:20px; color:#27495a; }}
    code {{ font-size:12px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} #map {{ height:380px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Antes do HEC · compreensão da bacia</div>
    <h1>Taquari–Antas não é um balde</h1>
    <p class="meta">Gerado em {report['generated_at_utc']} · fonte BHO6/ANA no recorte a montante de Muçum · pesquisa, não operação</p>
    <div class="notice">Este artefato descreve a <strong>estrutura da bacia</strong> (tronco, afluentes, postos, áreas). Não calibra HEC e não autoriza alerta.</div>
  </header>

  <section>
    <div class="grid">
      <div class="stat"><strong>{controls['86510000']['area_km2']:,.0f}</strong><span>km² a montante de Muçum (BHO6)</span></div>
      <div class="stat"><strong>{report['counts']['tributaries_ge_100km2']}</strong><span>afluentes ≥100 km² entrando no tronco</span></div>
      <div class="stat"><strong>{report['counts']['stations_inventoried']}</strong><span>postos inventariados no contrato atual</span></div>
    </div>
  </section>

  <section>
    <h2>Leitura correta do corredor</h2>
    <p>Ordem aninhada confirmada na BHO6:</p>
    <ol>
      <li><strong>Linha José Júlio</strong> <code>86472000</code> — Rio das Antas — <strong>{controls['86472000']['area_km2']:,.1f} km²</strong></li>
      <li><strong>Santa Tereza</strong> <code>86472600</code> — Rio Taquari — <strong>{controls['86472600']['area_km2']:,.1f} km²</strong> (incremento +{controls['incremental_km2']['antas_to_stz']:,.1f})</li>
      <li><strong>Muçum</strong> <code>86510000</code> — Rio Taquari — <strong>{controls['86510000']['area_km2']:,.1f} km²</strong> (incremento +{controls['incremental_km2']['stz_to_mucum']:,.1f})</li>
    </ol>
    <div class="notice ok">O incremento Antas→Santa Tereza (~{controls['incremental_km2']['antas_to_stz']:,.0f} km²) é dominado pelo <strong>{carreiro.get('label','sistema Carreiro')}</strong> (~{carreiro.get('join_area_km2',0):,.0f} km², {carreiro.get('fraction_of_increment',0)*100:.0f}% do incremento). Tratar isso como “chuva genérica de Santa Tereza” apaga a entrada principal da bacia nesse trecho.</div>
  </section>

  <section>
    <h2>Mapa do tronco e das entradas ≥100 km²</h2>
    <div id="map"></div>
    <p class="muted">Linha = tronco BHO6 (código 786). Pontos azuis = controles. Pontos âmbar = confluências de afluentes grandes. O GeoJSON completo do recorte permanece em <code>hec_hms_integrated_taquari_antas/</code>.</p>
  </section>

  <section>
    <h2>Onde as entradas grandes entram</h2>
    <div class="grid">
      <div class="stat"><strong>{pos['upstream_or_at_antas']['tributary_count_ge_100km2']}</strong><span>a montante/em Antas · Σ {pos['upstream_or_at_antas']['sum_join_areas_km2']:,.0f} km²</span></div>
      <div class="stat"><strong>{pos['between_antas_and_santa_tereza']['tributary_count_ge_100km2']}</strong><span>entre Antas e Santa Tereza · Σ {pos['between_antas_and_santa_tereza']['sum_join_areas_km2']:,.0f} km²</span></div>
      <div class="stat"><strong>{pos['between_santa_tereza_and_mucum']['tributary_count_ge_100km2']}</strong><span>entre Santa Tereza e Muçum · Σ {pos['between_santa_tereza_and_mucum']['sum_join_areas_km2']:,.0f} km²</span></div>
    </div>
    <div class="table-wrap" style="overflow:auto;margin-top:14px">
      <table>
        <thead><tr><th>Afluente / sistema</th><th class="num">Área na foz (km²)</th><th>Posição</th><th>Código BHO6</th><th>Confiança do nome</th></tr></thead>
        <tbody>{rows_joins(joins)}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Postos: quem observa o quê</h2>
    <div class="table-wrap" style="overflow:auto">
      <table>
        <thead><tr><th>Código</th><th>Nome</th><th>Rio</th><th>Papel na bacia</th><th class="num">Área BHO6 (km²)</th></tr></thead>
        <tbody>{rows_stations(stations)}</tbody>
      </table>
    </div>
    <p class="muted">Vários postos da RNA (Carreiro, Prata, Ituim, UHEs) já existem no contrato de nível e ainda <strong>não</strong> aparecem como sub-bacias no HEC.</p>
  </section>

  <section>
    <h2>Por que o HEC atual ainda está cru</h2>
    <ul>
      {''.join(f'<li>{item}</li>' for item in gap['why_this_is_still_crude'])}
    </ul>
    <h2 style="margin-top:18px">Estrutura mínima antes de recalibrar</h2>
    <ul>
      {''.join(f'<li>{item}</li>' for item in gap['minimum_next_structure_before_recalibration'])}
    </ul>
  </section>

  <section>
    <h2>Artefatos</h2>
    <ul>
      <li><a href="bacia_understanding_latest.json"><code>bacia_understanding_latest.json</code></a> — relatório auditável</li>
      <li><a href="major_tributary_joins.geojson"><code>major_tributary_joins.geojson</code></a> — confluências</li>
      <li><a href="../hec_hms_integrated_taquari_antas/bho6_taquari_antas_network.geojson">rede BHO6 do corredor</a></li>
      <li><a href="../hec_hms_integrated_taquari_antas/network_audit_latest.json">auditoria de rede</a></li>
    </ul>
  </section>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const report = {json.dumps({
    "controls": report["controls"],
    "joins": [
        {
            "label": j["label"],
            "join_area_km2": j["join_area_km2"],
            "confluence_lonlat": j["confluence_lonlat"],
            "position_vs_controls": j["position_vs_controls"],
        }
        for j in joins
        if j.get("confluence_lonlat")
    ],
    "mainstem": report["mainstem_simplified"],
}, ensure_ascii=False)};
const map = L.map('map').setView([-29.12, -51.55], 8);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '&copy; OpenStreetMap',
  maxZoom: 18
}}).addTo(map);
if (report.mainstem && report.mainstem.coordinates) {{
  L.polyline(report.mainstem.coordinates.map(([lon,lat]) => [lat,lon]), {{
    color:'#0a6f9c', weight:3, opacity:0.85
  }}).addTo(map);
}}
const controlColors = {{'86472000':'#0a6f9c','86472600':'#0b7a68','86510000':'#9a5b12'}};
for (const [code, c] of Object.entries(report.controls)) {{
  if (!c.lon || !c.lat) continue;
  L.circleMarker([c.lat, c.lon], {{
    radius:8, color:'#fff', weight:2, fillColor:controlColors[code]||'#333', fillOpacity:1
  }}).addTo(map).bindPopup(`<strong>${{c.name}}</strong><br>${{code}}<br>${{c.area_km2.toFixed(0)}} km²`);
}}
for (const j of report.joins) {{
  const [lon, lat] = j.confluence_lonlat;
  L.circleMarker([lat, lon], {{
    radius: Math.max(4, Math.min(14, Math.sqrt(j.join_area_km2)/8)),
    color:'#7a4a10', weight:1, fillColor:'#e0a045', fillOpacity:0.85
  }}).addTo(map).bindPopup(`<strong>${{j.label}}</strong><br>${{j.join_area_km2}} km²<br>${{j.position_vs_controls}}`);
}}
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def simplify_mainstem(by_fid: dict[int, dict]) -> dict[str, Any]:
    """Build a simplified polyline from mainstem segments sorted by area."""
    segs = [
        p
        for p in by_fid.values()
        if str(p.get("cocursodag")) == "786" and p.get("_geometry")
    ]
    segs.sort(key=lambda p: float(p.get("nuareamont") or 0))
    coords: list[list[float]] = []
    for seg in segs:
        line = seg["_geometry"].get("coordinates") or []
        for xy in line:
            pt = [float(xy[0]), float(xy[1])]
            if not coords or coords[-1] != pt:
                coords.append(pt)
    # Decimate for HTML embed size.
    if len(coords) > 400:
        step = max(1, len(coords) // 400)
        coords = coords[::step]
    return {"type": "LineString", "coordinates": coords, "vertex_count": len(coords)}


def main() -> None:
    geojson = load_json(GEOJSON)
    audit = load_json(NETWORK_AUDIT)
    screening = load_json(BASIN_SCREENING)
    watershed = load_json(WATERSHED_PREP) if WATERSHED_PREP.exists() else {}

    by_fid, by_dest = build_indexes(geojson)
    nested = audit["topology"]["nested_catchment_area_km2_from_bho6"]
    control_areas = {code: float(nested[code]) for code in CONTROL_ORDER}

    joins = extract_joins(by_fid, by_dest, control_areas)
    positions = summarize_positions(joins)
    stations = station_inventory(screening, audit)
    gap = hec_gap_statement(control_areas, joins, positions)
    mainstem = simplify_mainstem(by_fid)

    station_meta = {
        code: {
            "name": audit["stations"][code]["name"],
            "lon": audit["stations"][code]["lon"],
            "lat": audit["stations"][code]["lat"],
            "area_km2": control_areas[code],
            "role": audit["stations"][code]["role"],
        }
        for code in CONTROL_ORDER
    }

    report = {
        "schema_version": "bacia_taquari_antas_understanding_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "compreensão estrutural da bacia antes de recalibrar HEC-HMS; não é calibração nem alerta",
        "sources": {
            "bho6_geojson": {
                "path": str(GEOJSON.relative_to(ROOT)),
                "sha256": sha256_file(GEOJSON),
                "features": len(geojson["features"]),
            },
            "network_audit": {
                "path": str(NETWORK_AUDIT.relative_to(ROOT)),
                "sha256": sha256_file(NETWORK_AUDIT),
            },
            "basin_screening": {
                "path": str(BASIN_SCREENING.relative_to(ROOT)),
                "sha256": sha256_file(BASIN_SCREENING),
            },
            "watershed_preparation": {
                "path": str(WATERSHED_PREP.relative_to(ROOT)) if WATERSHED_PREP.exists() else None,
                "srtm_area_km2": watershed.get("watershed_area_km2")
                or watershed.get("area_km2"),
            },
        },
        "scope": {
            "basin_name": "Taquari–Antas",
            "study_outlet": "86510000",
            "note": "Recorte = rede BHO6 a montante de Muçum usada no audit HEC; não é inventário de toda a OTTO/BHO da bacia oficial além desse clip.",
            "full_taquari_antas_basin_discretized": False,
            "bho6_upstream_segments_reachable_from_mucum": audit["topology"][
                "upstream_segments_reachable_from_86510000"
            ],
            "segments_in_published_clip": len(by_fid),
        },
        "controls": {
            **station_meta,
            "incremental_km2": {
                "antas_to_stz": round(control_areas["86472600"] - control_areas["86472000"], 3),
                "stz_to_mucum": round(control_areas["86510000"] - control_areas["86472600"], 3),
            },
        },
        "counts": {
            "tributaries_ge_100km2": len(joins),
            "stations_inventoried": len(stations),
            "mainstem_segments_in_clip": sum(
                1 for p in by_fid.values() if str(p.get("cocursodag")) == "786"
            ),
        },
        "major_tributary_joins": [
            {k: v for k, v in j.items() if k != "_geometry"} for j in joins
        ],
        "joins_by_position": positions,
        "stations": stations,
        "hec_structure_gap": gap,
        "mainstem_simplified": mainstem,
        "reading_for_next_hec": {
            "one_sentence": "A bacia tem múltiplas entradas reais; o HEC atual comprime isso em 3 baldes e apaga o Carreiro como entrada dominante entre Antas e Santa Tereza.",
            "do_not": [
                "Recalibrar parâmetros comuns no esqueleto de 3 baldes e declarar modelo de bacia.",
                "Usar uma única série de chuva (86472000) como proxy de todos os incrementos.",
                "Tratar NSE bom só em Muçum como prova da rede.",
            ],
            "do_next": gap["minimum_next_structure_before_recalibration"],
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "bacia_understanding_latest.json"
    html_path = OUT_DIR / "index.html"
    joins_gj_path = OUT_DIR / "major_tributary_joins.geojson"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    joins_gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": j["confluence_lonlat"],
                },
                "properties": {
                    k: v
                    for k, v in j.items()
                    if k not in {"confluence_lonlat", "named_components_top"}
                },
            }
            for j in joins
            if j.get("confluence_lonlat")
        ],
    }
    joins_gj_path.write_text(
        json.dumps(joins_gj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_html(report, html_path)

    readme = OUT_DIR / "README.md"
    readme.write_text(
        """# Compreensão da bacia Taquari–Antas

Artefato de **estrutura hidrológica** gerado antes de qualquer nova calibração HEC-HMS.

## O que este pacote responde

- Quais são os controles aninhados Antas → Santa Tereza → Muçum e suas áreas BHO6
- Quais afluentes ≥100 km² entram no tronco e em que trecho
- Que o incremento Antas→Santa Tereza é dominado pelo sistema do Rio Carreiro
- Quais postos do contrato RNA já observam afluentes que o HEC ainda não discretiza
- Por que o esqueleto HEC de 3 baldes + 2 reaches continua cru

## Arquivos

- `index.html` — leitura visual
- `bacia_understanding_latest.json` — relatório auditável
- `major_tributary_joins.geojson` — confluências

## Reprodução

```bash
python scripts/build_bacia_taquari_antas_understanding.py
```

Não é alerta, previsão operacional nem calibração HEC.
""",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "json": str(json_path.relative_to(ROOT)),
                "html": str(html_path.relative_to(ROOT)),
                "joins": len(joins),
                "carreiro_fraction_of_stz_increment": (
                    gap["current_hec_skeleton"]["buckets"][1]
                    .get("dominated_by", {})
                    .get("fraction_of_increment")
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
