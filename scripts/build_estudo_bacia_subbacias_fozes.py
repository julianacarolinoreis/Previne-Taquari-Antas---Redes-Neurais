#!/usr/bin/env python3
"""Continue the Taquari-Antas STUDY: official sub-basins + confluence map.

Sources:
- IEDE/SEMA Enquad_Sub_Bacias (bh=Q040) = 32 sub-bacias do enquadramento
- IEDE/SEMA limites_sub_bacias (cod_bacia=G040) = 7 UGs
- BHO6 ANA for confluence positions of major tributaries vs Muçum

No HEC modeling.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
UA = {"User-Agent": "PREVINE-estudo-bacia/1.0"}

ENQUAD = (
    "https://iede.rs.gov.br/server/rest/services/DRH/"
    "Enquad_Sub_Bacias_Taquari_Antas_Cai/FeatureServer/0"
)
UGS = (
    "https://iede.rs.gov.br/server/rest/services/DRH/"
    "limites_sub_bacias_hidrograficas/FeatureServer/0"
)
BHO6 = (
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)

CONTROLS = {
    "86472000": {"name": "Linha Jose Julio / Antas", "lon": -51.6997, "lat": -29.0978, "area_km2": 12918.656},
    "86472600": {"name": "Santa Tereza", "lon": -51.7322, "lat": -29.1781, "area_km2": 15775.186},
    "86510000": {"name": "Mucum", "lon": -51.8686, "lat": -29.1672, "area_km2": 15965.207},
}


def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def deg2_to_km2(area_deg2: float, lat_deg: float = -29.0) -> float:
    """Approximate geodesic area from Web Mercator-ish degree area on IEDE."""
    # IEDE Shape__Area is in CRS geographic degrees squared for these layers.
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_deg))
    return area_deg2 * (m_per_deg_lat * m_per_deg_lon) / 1e6


def fetch_geojson(base: str, where: str) -> dict[str, Any]:
    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": 200,
        "f": "geojson",
    }
    return http_json(base + "/query?" + urllib.parse.urlencode(params))


def fetch_bho6(where: str, geometry: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": "fid,noorigem,nodestino,cocursodag,nuareamont,noriocomp,noespecif",
            "returnGeometry": "true" if geometry else "false",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": 2000,
            "orderByFields": "fid",
            "f": "json",
        }
        payload = http_json(BHO6 + "?" + urllib.parse.urlencode(params))
        feats = payload.get("features") or []
        rows.extend(feats)
        if len(feats) < 2000:
            break
        offset += len(feats)
        if offset > 60000:
            break
    return rows


def position(mainstem_area: float) -> str:
    if mainstem_area <= CONTROLS["86472000"]["area_km2"] + 1:
        return "upstream_or_at_antas"
    if mainstem_area <= CONTROLS["86472600"]["area_km2"] + 1:
        return "between_antas_and_santa_tereza"
    if mainstem_area <= CONTROLS["86510000"]["area_km2"] + 1:
        return "between_santa_tereza_and_mucum"
    return "downstream_of_mucum"


def major_joins() -> list[dict[str, Any]]:
    main = fetch_bho6("cocursodag='786'", geometry=True)
    main_nodes: set[int] = set()
    main_area_at: dict[int, float] = {}
    for feat in main:
        attrs = feat["attributes"]
        o, d = int(attrs["noorigem"]), int(attrs["nodestino"])
        main_nodes.add(o)
        main_nodes.add(d)
        area = float(attrs.get("nuareamont") or 0)
        main_area_at[d] = max(main_area_at.get(d, 0.0), area)
        main_area_at[o] = max(main_area_at.get(o, 0.0), area)

    families = [
        ("7868", "sistema Prata / Turvo-Humatã (BHO6 7868)"),
        ("7866", "Rio Carreiro (BHO6 7866)"),
        ("7864", "Rio Guaporé (BHO6 7864)"),
        ("7862", "sistema Forqueta (BHO6 7862)"),
    ]
    out: list[dict[str, Any]] = []
    for code, label in families:
        trib = fetch_bho6(f"cocursodag LIKE '{code}%'", geometry=True)
        joins = []
        for feat in trib:
            attrs = feat["attributes"]
            if str(attrs.get("cocursodag")) == "786":
                continue
            dest = int(attrs["nodestino"])
            if dest not in main_nodes:
                continue
            geom = feat.get("geometry") or {}
            paths = geom.get("paths") or []
            end = paths[0][-1] if paths and paths[0] else None
            joins.append(
                {
                    "join_area_km2": float(attrs.get("nuareamont") or 0),
                    "mainstem_area_at_join_km2": float(main_area_at.get(dest) or 0),
                    "fid": int(attrs["fid"]),
                    "name": attrs.get("noriocomp") or attrs.get("noespecif"),
                    "cocursodag": attrs.get("cocursodag"),
                    "lonlat": end,
                }
            )
        if not joins:
            continue
        best = max(joins, key=lambda item: item["join_area_km2"])
        best.update(
            {
                "label": label,
                "family_code": code,
                "position_vs_controls": position(best["mainstem_area_at_join_km2"]),
                "delta_vs_mucum_km2": round(
                    best["mainstem_area_at_join_km2"] - CONTROLS["86510000"]["area_km2"], 2
                ),
            }
        )
        out.append(best)
    out.sort(key=lambda item: item["mainstem_area_at_join_km2"])
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    print("fetching 32 sub-bacias Q040...")
    sub = fetch_geojson(ENQUAD, "bh='Q040'")
    print("fetching 7 UGs G040...")
    ugs = fetch_geojson(UGS, "cod_bacia='G040'")
    print("mapping major confluences on BHO6...")
    joins = major_joins()

    # enrich areas
    sub_features = []
    for feat in sub.get("features") or []:
        props = dict(feat.get("properties") or {})
        area_deg = float(props.get("Shape__Area") or 0)
        props["area_km2_approx"] = round(deg2_to_km2(area_deg), 2)
        props["source_layer"] = "IEDE DRH/Enquad_Sub_Bacias_Taquari_Antas_Cai (bh=Q040)"
        sub_features.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": props})

    ug_features = []
    for feat in ugs.get("features") or []:
        props = dict(feat.get("properties") or {})
        area_deg = float(props.get("Shape__Area") or 0)
        props["area_km2_approx"] = round(deg2_to_km2(area_deg), 2)
        props["source_layer"] = "IEDE DRH/limites_sub_bacias_hidrograficas (cod_bacia=G040)"
        ug_features.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": props})

    sub_fc = {"type": "FeatureCollection", "name": "sub_bacias_Q040_enquadramento", "features": sub_features}
    ug_fc = {"type": "FeatureCollection", "name": "ugs_G040", "features": ug_features}
    joins_fc = {
        "type": "FeatureCollection",
        "name": "fozes_principais_bho6",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": j["lonlat"]} if j.get("lonlat") else None,
                "properties": {k: v for k, v in j.items() if k != "lonlat"},
            }
            for j in joins
            if j.get("lonlat")
        ],
    }

    (OUT / "sub_bacias_q040_enquadramento.geojson").write_text(
        json.dumps(sub_fc, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "ugs_g040.geojson").write_text(json.dumps(ug_fc, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "fozes_principais_bho6.geojson").write_text(
        json.dumps(joins_fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    by_ug: dict[str, list[dict[str, Any]]] = {}
    for feat in sub_features:
        p = feat["properties"]
        ug = (p.get("upg") or "sem_ug").strip() or "sem_ug"
        by_ug.setdefault(ug, []).append(
            {
                "nome_plano": p.get("nome_plano"),
                "area_km2_approx": p.get("area_km2_approx"),
                "enq": p.get("enq"),
                "objectid": p.get("objectid"),
            }
        )

    ug_table = [
        {
            "nome": f["properties"].get("sub_bacia"),
            "area_km2_approx": f["properties"].get("area_km2_approx"),
            "objectid": f["properties"].get("objectid"),
        }
        for f in ug_features
    ]
    ug_table.sort(key=lambda r: -(r["area_km2_approx"] or 0))

    sum_sub = round(sum(f["properties"]["area_km2_approx"] for f in sub_features), 2)
    sum_ug = round(sum(f["properties"]["area_km2_approx"] for f in ug_features), 2)

    report = {
        "schema_version": "estudo_bacia_taquari_antas_subbacias_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "continuidade do estudo oficial da bacia; nao e HEC",
        "sources": {
            "enquadramento_subbacias": ENQUAD,
            "enquadramento_filter": "bh='Q040' (no layer IEDE o codigo da bacia aparece como Q040, nao G040)",
            "ugs": UGS,
            "ugs_filter": "cod_bacia='G040'",
            "confluences": "ANA BHO6 main.geoft_bho_trecho_drenagem",
        },
        "counts": {
            "subbacias_enquadramento": len(sub_features),
            "ugs": len(ug_features),
            "fozes_mapeadas": len(joins),
        },
        "area_check_approx_km2": {
            "sum_32_subbacias": sum_sub,
            "sum_7_ugs": sum_ug,
            "sema_official": 26430,
            "note": "Areas aproximadas a partir de Shape__Area em graus; reconciliar com shapefile projetado depois.",
        },
        "ugs": ug_table,
        "subbacias_by_ug": {
            ug: sorted(rows, key=lambda r: -(r["area_km2_approx"] or 0)) for ug, rows in by_ug.items()
        },
        "fozes_principais": joins,
        "reading": {
            "guapore": "Foz do Guapore no tronco com area aninhada BHO6 ~18.460 km2, ~+2.495 km2 apos Muçum (15.965). Geograficamente perto de Mucum/Encantado, mas hidrologicamente a jusante do posto 86510000.",
            "forqueta": "Foz do sistema Forqueta com area aninhada BHO6 ~22.505 km2, bem a jusante de Mucum.",
            "carreiro": "Foz do Carreiro entre Antas e Santa Tereza (~15.486 km2 no tronco).",
            "prata_system": "Sistema 7868 (Prata/componentes) entra a montante do posto Antas.",
            "implication": "O PREVINE em Mucum nao ve Guapore nem Forqueta. Modelar so o corredor Ate Mucum nao e modelar a bacia Taquari-Antas.",
        },
        "artifacts": {
            "sub_bacias_geojson": "sub_bacias_q040_enquadramento.geojson",
            "ugs_geojson": "ugs_g040.geojson",
            "fozes_geojson": "fozes_principais_bho6.geojson",
            "mapa": "mapa_subbacias.html",
        },
    }
    (OUT / "subbacias_e_fozes_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # merge previous estudo if present
    prev_path = OUT / "estudo_bacia_latest.json"
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        prev["subbacias_oficial_iede"] = {
            "status": "baixado",
            "counts": report["counts"],
            "area_check_approx_km2": report["area_check_approx_km2"],
            "fozes_principais": joins,
            "reading": report["reading"],
            "artifacts": report["artifacts"],
            "updated_at_utc": report["generated_at_utc"],
        }
        # update unknowns that are now known
        known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
        for item in [
            "IEDE disponibiliza as 32 sub-bacias do enquadramento sob codigo Q040.",
            "IEDE disponibiliza as 7 UGs sob cod_bacia G040.",
            "Guapore entra no tronco a jusante hidrologica do posto Mucum (~+2495 km2).",
            "Forqueta entra ainda mais a jusante (~22.5 mil km2 aninhados).",
        ]:
            if item not in known:
                known.append(item)
        unknown = prev.get("known_vs_unknown", {}).get("unknown_or_unreconciled", [])
        prev["known_vs_unknown"]["unknown_or_unreconciled"] = [
            u
            for u in unknown
            if "Shapefile oficial das 32" not in u and "Posicao exata" not in u
        ]
        for item in [
            "Area projetada exata (m2) das 32 sub-bacias em EPSG:31982 (hoje aproximacao por graus).",
            "Inventario de postos por UG/sub-bacia.",
        ]:
            if item not in prev["known_vs_unknown"]["unknown_or_unreconciled"]:
                prev["known_vs_unknown"]["unknown_or_unreconciled"].append(item)
        prev["next_study_steps_only"] = [
            "Reconciliar areas das 32 sub-bacias em EPSG:31982 (hoje Shape__Area em graus).",
            "Montar inventario de postos por UG sem forcar uso em HEC.",
            "So depois escolher o recorte de modelo com a Juliana (bacia toda vs corredor).",
        ]
        prev_path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_map(report, sub_fc, ug_fc, joins_fc)
    print(
        json.dumps(
            {
                "ok": True,
                "subbacias": len(sub_features),
                "ugs": len(ug_features),
                "sum_sub_approx": sum_sub,
                "sum_ug_approx": sum_ug,
                "joins": [(j["label"], j["position_vs_controls"], j["join_area_km2"]) for j in joins],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_map(report: dict[str, Any], sub_fc: dict, ug_fc: dict, joins_fc: dict) -> None:
    # Keep embedded geojson modest: only UG outlines + confluence points + controls
    controls_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                "properties": {"code": code, **c},
            }
            for code, c in CONTROLS.items()
        ],
    }
    rows = "".join(
        f"<tr><td>{u['nome']}</td><td class='num'>{u['area_km2_approx']:,.0f}</td></tr>"
        for u in report["ugs"]
    )
    join_rows = "".join(
        "<tr>"
        f"<td>{j['label']}</td>"
        f"<td class='num'>{j['join_area_km2']:,.0f}</td>"
        f"<td class='num'>{j['mainstem_area_at_join_km2']:,.0f}</td>"
        f"<td>{j['position_vs_controls']}</td>"
        f"<td class='num'>{j['delta_vs_mucum_km2']:+,.0f}</td>"
        "</tr>"
        for j in report["fozes_principais"]
    )
    # subbasin list compact
    sub_list = []
    for ug, items in sorted(report["subbacias_by_ug"].items()):
        lis = "".join(
            f"<li>{i['nome_plano']} <span class='muted'>({i['area_km2_approx']:,.0f} km²)</span></li>"
            for i in items
        )
        sub_list.append(f"<div class='ug'><h3>{ug}</h3><ul>{lis}</ul></div>")

    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sub-bacias e fozes · Taquari-Antas</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --car:#c45c16; }}
    body {{ margin:0; color:var(--ink); font:16px/1.5 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1180px; margin:auto; padding:24px 16px 56px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(26px,4vw,40px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:26px; color:var(--accent); }}
    #map {{ height:540px; border-radius:14px; border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th,td {{ padding:8px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }} td.num {{ text-align:right; }}
    .ugs {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }}
    .ug {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f8fcfc; }}
    .ug h3 {{ margin:0 0 6px; font-size:1rem; }}
    .ug ul {{ margin:0; padding-left:18px; }}
    .muted {{ color:var(--muted); font-size:12px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid,.ugs {{ grid-template-columns:1fr; }} #map {{ height:380px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · sub-bacias oficiais + fozes</div>
    <h1>32 sub-bacias no mapa, sem inventar HEC</h1>
    <p class="muted">{report['generated_at_utc']}</p>
    <div class="notice"><strong>Leitura:</strong> {report['reading']['implication']}</div>
  </header>
  <section>
    <div class="grid">
      <div class="stat"><strong>{report['counts']['subbacias_enquadramento']}</strong><span>sub-bacias IEDE (Q040)</span></div>
      <div class="stat"><strong>{report['counts']['ugs']}</strong><span>UGs (G040)</span></div>
      <div class="stat"><strong>{report['area_check_approx_km2']['sum_7_ugs']:,.0f}</strong><span>km² approx soma das 7 UGs</span></div>
    </div>
  </section>
  <section>
    <h2>Mapa</h2>
    <div id="map"></div>
    <p class="muted">Poligonos = 7 UGs. Pontos azuis = controles PREVINE. Pontos âmbar = fozes BHO6 (Prata-sistema, Carreiro, Guapore, Forqueta).</p>
  </section>
  <section>
    <h2>Fozes no tronco vs Muçum</h2>
    <table>
      <thead><tr><th>Sistema</th><th class="num">Area na foz</th><th class="num">Area tronco na foz</th><th>Posicao</th><th class="num">Δ vs Muçum</th></tr></thead>
      <tbody>{join_rows}</tbody>
    </table>
  </section>
  <section>
    <h2>7 UGs (areas approx)</h2>
    <table><thead><tr><th>UG</th><th class="num">km² approx</th></tr></thead><tbody>{rows}</tbody></table>
  </section>
  <section>
    <h2>32 sub-bacias por UG</h2>
    <div class="ugs">{''.join(sub_list)}</div>
  </section>
  <section>
    <h2>Arquivos</h2>
    <ul>
      <li><a href="subbacias_e_fozes_latest.json">subbacias_e_fozes_latest.json</a></li>
      <li><a href="sub_bacias_q040_enquadramento.geojson">32 sub-bacias GeoJSON</a></li>
      <li><a href="ugs_g040.geojson">7 UGs GeoJSON</a></li>
      <li><a href="fozes_principais_bho6.geojson">fozes BHO6</a></li>
      <li><a href="index.html">estudo-base</a></li>
    </ul>
  </section>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const ugs = {json.dumps(ug_fc, ensure_ascii=False)};
const joins = {json.dumps(joins_fc, ensure_ascii=False)};
const controls = {json.dumps(controls_fc, ensure_ascii=False)};
const map = L.map('map').setView([-29.15, -51.55], 8);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 18, attribution: '&copy; OSM' }}).addTo(map);
L.geoJSON(ugs, {{
  style: {{ color:'#0a6f9c', weight:1.5, fillColor:'#7eb8d4', fillOpacity:0.25 }},
  onEachFeature: (f, layer) => layer.bindPopup(`<strong>${{f.properties.sub_bacia}}</strong><br>${{f.properties.area_km2_approx}} km² approx`)
}}).addTo(map);
L.geoJSON(joins, {{
  pointToLayer: (f, latlng) => L.circleMarker(latlng, {{ radius:8, color:'#7a4a10', fillColor:'#e0a045', fillOpacity:0.9, weight:1 }}),
  onEachFeature: (f, layer) => layer.bindPopup(`<strong>${{f.properties.label}}</strong><br>${{f.properties.position_vs_controls}}<br>foz ${{f.properties.join_area_km2}} km²`)
}}).addTo(map);
L.geoJSON(controls, {{
  pointToLayer: (f, latlng) => L.circleMarker(latlng, {{ radius:7, color:'#fff', weight:2, fillColor:'#0a6f9c', fillOpacity:1 }}),
  onEachFeature: (f, layer) => layer.bindPopup(`<strong>${{f.properties.name}}</strong><br>${{f.properties.code}}`)
}}).addTo(map);
</script>
</body>
</html>
"""
    (OUT / "mapa_subbacias.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
