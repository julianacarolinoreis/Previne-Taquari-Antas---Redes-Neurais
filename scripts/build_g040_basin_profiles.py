#!/usr/bin/env python3
"""Perfis longitudinais MDT da bacia G040 (tronco + Guaporé + Forqueta).

Diagnóstico de relevo a partir de SRTM (Skadi) amostrado sobre o eixo BHO6
oficial (cocursodag 786 / 7864 / 7862). Não é seção hidráulica, não é calha
nivelada, não alimenta HEC-RAS/alerta.

Saídas (estudo G040):
  - perfis_longitudinais_g040_latest.json
  - perfis_longitudinais_g040.html
  - pesquisas/perfis-g040-mdt.html (atalho Pages)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rasterio
import requests
from pyproj import Transformer
from rasterio.merge import merge
from shapely.geometry import LineString, MultiLineString, mapping, shape
from shapely.ops import linemerge, transform as shapely_transform

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
DEM_DIR = OUT / "_dem_srtm_g040"
DEM_DIR.mkdir(parents=True, exist_ok=True)
PAGES_HTML = ROOT / "pesquisas" / "perfis-g040-mdt.html"
MUN_GEOJSON = ROOT / "assets" / "data" / "vulnerabilidade" / "municipios.geojson"

UA = "PREVINE-G040-basin-profiles/1.0"
BHO6_QUERY = (
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)
OUT_FIELDS = (
    "fid,cotrecho,noorigem,nodestino,cocursodag,cobacia,nuareamont,"
    "nuareacont,nucomptrec,nucompcda,nustrahler,noriocomp"
)
S3_TEMPLATE = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{lat_band}/{tile}.hgt.gz"

# G040 bbox ≈ lon -52.64…-49.93, lat -29.95…-28.18 → 8 tiles SRTM 1°.
TILES = [
    "S29W053",
    "S29W052",
    "S29W051",
    "S29W050",
    "S30W053",
    "S30W052",
    "S30W051",
    "S30W050",
]

PROFILES = [
    {
        "id": "tronco_taquari_antas",
        "label_pt": "Tronco Taquari–Antas (BHO 786)",
        "cocursodag": "786",
        "role": "mainstem_g040",
        "note_pt": "Eixo principal da G040 (cabeceira → Baixo), passa por Muçum e recebe Guaporé/Forqueta.",
    },
    {
        "id": "guapore",
        "label_pt": "Rio Guaporé (BHO 7864)",
        "cocursodag": "7864",
        "role": "tributary_join_downstream_mucum",
        "note_pt": "Afluente que entra jusante de Muçum; foz BHO fid 5332058.",
    },
    {
        "id": "forqueta",
        "label_pt": "Sistema Forqueta (BHO 7862)",
        "cocursodag": "7862",
        "role": "tributary_join_downstream_mucum",
        "note_pt": "Afluente que entra jusante de Encantado; foz BHO fid 3999116.",
    },
]

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:31982", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:31982", "EPSG:4326", always_xy=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_tiles() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tile in TILES:
        compressed = DEM_DIR / f"{tile}.hgt.gz"
        hgt = DEM_DIR / f"{tile}.hgt"
        url = S3_TEMPLATE.format(lat_band=tile[:3], tile=tile)
        if not compressed.exists():
            print("download", tile)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=240) as resp:
                compressed.write_bytes(resp.read())
        if not hgt.exists():
            with gzip.open(compressed, "rb") as src, hgt.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        rows.append(
            {
                "tile": tile,
                "url": url,
                "compressed_bytes": compressed.stat().st_size,
                "hgt_bytes": hgt.stat().st_size,
                "sha256_compressed": sha256(compressed),
            }
        )
    return rows


def make_mosaic() -> Path:
    mosaic = DEM_DIR / "srtm_g040_mosaic_wgs84.tif"
    if mosaic.exists() and mosaic.stat().st_size > 1_000_000:
        print("reuse mosaic", mosaic.name)
        return mosaic
    sources = [rasterio.open(DEM_DIR / f"{tile}.hgt") for tile in TILES]
    try:
        data, transform = merge(sources, nodata=-32768)
        profile = sources[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[1],
            width=data.shape[2],
            transform=transform,
            crs="EPSG:4326",
            count=1,
            dtype="int16",
            nodata=-32768,
            compress="deflate",
            predictor=2,
        )
        with rasterio.open(mosaic, "w", **profile) as target:
            target.write(data[0].astype("int16"), 1)
    finally:
        for source in sources:
            source.close()
    print("wrote mosaic", mosaic.relative_to(ROOT), mosaic.stat().st_size)
    return mosaic


def get_json(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(BHO6_QUERY, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(json.dumps(payload["error"], ensure_ascii=False))
    return payload


def fetch_bho_mainstem(session: requests.Session, cocursodag: str) -> list[dict[str, Any]]:
    """Fetch all BHO6 segments for an exact cocursodag (paginated GeoJSON)."""
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = get_json(
            session,
            {
                "where": f"cocursodag='{cocursodag}'",
                "outFields": OUT_FIELDS,
                "returnGeometry": "true",
                "outSR": "4326",
                "resultOffset": offset,
                "resultRecordCount": 1000,
                "orderByFields": "fid",
                "f": "geojson",
            },
        )
        page = payload.get("features") or []
        features.extend(page)
        if len(page) < 1000:
            break
        offset += len(page)
    return features


def _props(feat: dict[str, Any]) -> dict[str, Any]:
    return feat.get("properties") or feat.get("attributes") or {}


def order_mainstem(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk BHO directed network from headwater (min area) to mouth (max area)."""
    by_origin: dict[Any, list[dict[str, Any]]] = {}
    for feat in features:
        p = _props(feat)
        by_origin.setdefault(p.get("noorigem"), []).append(feat)

    # Prefer start = segment with smallest upstream area among those whose
    # noorigem is not a nodestino of another segment in the set.
    dests = { _props(f).get("nodestino") for f in features }
    heads = [f for f in features if _props(f).get("noorigem") not in dests]
    if not heads:
        heads = list(features)
    start = min(heads, key=lambda f: float(_props(f).get("nuareamont") or 0.0))

    ordered = [start]
    seen = {int(_props(start).get("fid"))}
    node = _props(start).get("nodestino")
    while node is not None:
        cands = [f for f in by_origin.get(node, []) if int(_props(f).get("fid")) not in seen]
        if not cands:
            break
        # If branches, keep the highest-area continuation (main channel).
        nxt = max(cands, key=lambda f: float(_props(f).get("nuareamont") or 0.0))
        ordered.append(nxt)
        seen.add(int(_props(nxt).get("fid")))
        node = _props(nxt).get("nodestino")
        if len(ordered) > len(features) + 5:
            break
    return ordered


def merge_ordered_line(ordered: list[dict[str, Any]]) -> LineString:
    lines = []
    for feat in ordered:
        geom = shape(feat["geometry"])
        if geom.geom_type == "LineString":
            lines.append(geom)
        elif geom.geom_type == "MultiLineString":
            lines.extend(list(geom.geoms))
    if not lines:
        raise ValueError("no lines to merge")
    merged = linemerge(lines)
    if isinstance(merged, MultiLineString):
        # Pick the longest part if merge is incomplete.
        merged = max(list(merged.geoms), key=lambda g: g.length)
    # Ensure direction headwater → mouth by area endpoints.
    first_area = float(_props(ordered[0]).get("nuareamont") or 0.0)
    last_area = float(_props(ordered[-1]).get("nuareamont") or 0.0)
    if last_area < first_area:
        merged = LineString(list(merged.coords)[::-1])
    return merged


def densify_wgs(
    line_wgs: LineString, step_m: float = 250.0
) -> list[tuple[float, float, float]]:
    """Return [(lon, lat, distance_m_from_head), ...] every ~step_m."""
    line_utm = shapely_transform(lambda x, y: TO_UTM.transform(x, y), line_wgs)
    length = float(line_utm.length)
    if length <= 0:
        return []
    n = max(2, int(math.ceil(length / step_m)) + 1)
    out: list[tuple[float, float, float]] = []
    for i in range(n):
        d = min(length, i * step_m) if i < n - 1 else length
        pt = line_utm.interpolate(d)
        lon, lat = TO_WGS.transform(pt.x, pt.y)
        out.append((float(lon), float(lat), float(d)))
    return out


def sample_profile(
    dem: rasterio.DatasetReader, samples: list[tuple[float, float, float]]
) -> list[dict[str, Any]]:
    coords = [(lon, lat) for lon, lat, _ in samples]
    vals = [float(v[0]) for v in dem.sample(coords)]
    rows: list[dict[str, Any]] = []
    for (lon, lat, dist_m), elev in zip(samples, vals):
        if elev <= -1.0e20 or elev < -500:
            continue
        rows.append(
            {
                "distance_km": round(dist_m / 1000.0, 3),
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "elev_m": round(elev, 2),
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    elevs = [r["elev_m"] for r in rows]
    return {
        "n": len(rows),
        "length_km": rows[-1]["distance_km"],
        "elev_min_m": min(elevs),
        "elev_max_m": max(elevs),
        "elev_mean_m": round(sum(elevs) / len(elevs), 2),
        "elev_start_m": elevs[0],
        "elev_end_m": elevs[-1],
        "drop_m": round(elevs[0] - elevs[-1], 2),
        "mean_slope_m_per_km": round((elevs[0] - elevs[-1]) / max(rows[-1]["distance_km"], 1e-6), 3),
    }


def svg_polyline(rows: list[dict[str, Any]], width: int = 720, height: int = 240) -> str:
    if len(rows) < 2:
        return f'<svg viewBox="0 0 {width} {height}"><text x="24" y="120" fill="#4a6356">Sem pontos.</text></svg>'
    pad_l, pad_r, pad_t, pad_b = 48, 18, 18, 36
    xs = [r["distance_km"] for r in rows]
    ys = [r["elev_m"] for r in rows]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if xmax <= xmin:
        xmax = xmin + 1
    if ymax <= ymin:
        ymax = ymin + 1

    def x_at(v: float) -> float:
        return pad_l + (v - xmin) / (xmax - xmin) * (width - pad_l - pad_r)

    def y_at(v: float) -> float:
        return pad_t + (1.0 - (v - ymin) / (ymax - ymin)) * (height - pad_t - pad_b)

    pts = " ".join(f"{x_at(x):.1f},{y_at(y):.1f}" for x, y in zip(xs, ys))
    y0 = y_at(ymin)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="perfil longitudinal">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
        f'<line x1="{pad_l}" y1="{y0:.1f}" x2="{width-pad_r}" y2="{y0:.1f}" stroke="#9aa096"/>'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{y0:.1f}" stroke="#9aa096"/>'
        f'<polyline points="{pts}" fill="none" stroke="#0f5c45" stroke-width="2.4"/>'
        f'<text x="{pad_l}" y="{height-10}" fill="#4a6356" font-size="11">'
        f"{xmin:.0f} km</text>"
        f'<text x="{width-pad_r}" y="{height-10}" fill="#4a6356" font-size="11" text-anchor="end">'
        f"{xmax:.0f} km</text>"
        f'<text x="8" y="{pad_t+4}" fill="#4a6356" font-size="11">{ymax:.0f} m</text>'
        f'<text x="8" y="{y0:.1f}" fill="#4a6356" font-size="11">{ymin:.0f} m</text>'
        f"</svg>"
    )


def downsample_rows(rows: list[dict[str, Any]], max_n: int = 400) -> list[dict[str, Any]]:
    if len(rows) <= max_n:
        return rows
    step = max(1, len(rows) // max_n)
    kept = rows[::step]
    if kept[-1]["distance_km"] != rows[-1]["distance_km"]:
        kept.append(rows[-1])
    return kept


def line_parts(geom: Any) -> list[LineString]:
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        return [g for g in geom.geoms if not g.is_empty and g.length > 0]
    if geom.geom_type == "GeometryCollection":
        out: list[LineString] = []
        for g in geom.geoms:
            out.extend(line_parts(g))
        return out
    return []


def project_point_m(axis_utm: LineString, lon: float, lat: float) -> float:
    from shapely.geometry import Point as ShPoint

    x, y = TO_UTM.transform(lon, lat)
    return float(axis_utm.project(ShPoint(x, y)))


def sample_line_profile(
    dem: rasterio.DatasetReader, line_wgs: LineString, step_m: float = 250.0
) -> list[dict[str, Any]]:
    samples = densify_wgs(line_wgs, step_m=step_m)
    return sample_profile(dem, samples)


def build_municipal_profiles(
    dem: rasterio.DatasetReader,
    axis_lines: dict[str, LineString],
    axis_labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Clip each axis by município and sample longitudinal MDT profiles."""
    if not MUN_GEOJSON.exists():
        print("WARN: municipal geojson missing", MUN_GEOJSON)
        return []
    mun = json.loads(MUN_GEOJSON.read_text(encoding="utf-8"))
    axis_utm = {
        aid: shapely_transform(lambda x, y: TO_UTM.transform(x, y), line)
        for aid, line in axis_lines.items()
    }
    out: list[dict[str, Any]] = []
    for feat in mun["features"]:
        props = feat.get("properties") or {}
        nome = props.get("nome") or props.get("NM_MUN") or "Município"
        cod = str(props.get("cod_mun") or props.get("CD_MUN") or "")
        poly = shape(feat["geometry"])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        stretches: list[dict[str, Any]] = []
        for aid, line in axis_lines.items():
            inter = line.intersection(poly)
            parts = line_parts(inter)
            if not parts:
                continue
            # Order parts by position along the full axis (head → mouth).
            ranked: list[tuple[float, LineString]] = []
            for part in parts:
                mid = part.interpolate(0.5, normalized=True)
                ranked.append((project_point_m(axis_utm[aid], mid.x, mid.y), part))
            ranked.sort(key=lambda t: t[0])
            # Concatenate local distances across parts for one mun×axis chart.
            series: list[dict[str, Any]] = []
            local_offset_m = 0.0
            for _, part in ranked:
                dense = densify_wgs(part, step_m=200.0)
                if not dense:
                    continue
                rows = sample_profile(dem, dense)
                if not rows:
                    continue
                part_len_m = dense[-1][2]
                for r in rows:
                    series.append(
                        {
                            "distance_km": round(local_offset_m / 1000.0 + r["distance_km"], 3),
                            "lon": r["lon"],
                            "lat": r["lat"],
                            "elev_m": r["elev_m"],
                            "axis_distance_km": round(
                                project_point_m(axis_utm[aid], r["lon"], r["lat"]) / 1000.0, 3
                            ),
                        }
                    )
                local_offset_m += part_len_m
            series = downsample_rows(series, max_n=180)
            if len(series) < 3:
                continue
            summary = summarize(series)
            stretches.append(
                {
                    "axis_id": aid,
                    "axis_label_pt": axis_labels.get(aid, aid),
                    "part_count": len(ranked),
                    "summary": summary,
                    "series": series,
                    "svg": svg_polyline(series, width=680, height=200),
                }
            )
        if not stretches:
            continue
        # Primary stretch = longest river length inside the município.
        primary = max(stretches, key=lambda s: float(s["summary"].get("length_km") or 0))
        out.append(
            {
                "id": f"mun_{cod}",
                "cod_mun": cod,
                "nome": nome,
                "pct_na_bacia": props.get("pct_na_bacia"),
                "axes": [s["axis_id"] for s in stretches],
                "stretches": stretches,
                "primary_axis_id": primary["axis_id"],
                "summary": primary["summary"],
                "svg": primary["svg"],
                "label_pt": f"{nome} · {primary['axis_label_pt']}",
                "note_pt": (
                    "Trecho do eixo BHO6 dentro do polígono municipal (SRTM). "
                    "Pode haver mais de um eixo se o município cruza afluentes."
                ),
            }
        )
    out.sort(key=lambda m: (-float(m["summary"].get("length_km") or 0), m["nome"]))
    print("municipal profiles", len(out))
    return out


def build_html(report: dict[str, Any]) -> str:
    cards = []
    for p in report["profiles"]:
        s = p["summary"]
        meta = (
            f"comprimento {s.get('length_km')} km · "
            f"cota {s.get('elev_start_m')}→{s.get('elev_end_m')} m · "
            f"queda {s.get('drop_m')} m · "
            f"n={s.get('n')}"
        )
        cards.append(
            f"""<section class="profile">
  <h2>{p['label_pt']}</h2>
  <div class="meta">{meta}</div>
  <p class="note">{p.get('note_pt') or ''}</p>
  {p['svg']}
</section>"""
        )

    mun_cards = []
    for m in report.get("municipal_profiles") or []:
        s = m["summary"]
        axes = ", ".join(m.get("axes") or [])
        meta = (
            f"eixo principal: {m.get('primary_axis_id')} · "
            f"comprimento {s.get('length_km')} km · "
            f"cota {s.get('elev_start_m')}→{s.get('elev_end_m')} m · "
            f"queda {s.get('drop_m')} m"
        )
        extra = ""
        if len(m.get("stretches") or []) > 1:
            bits = []
            for st in m["stretches"]:
                ss = st["summary"]
                bits.append(
                    f"{st['axis_label_pt']}: {ss.get('length_km')} km / queda {ss.get('drop_m')} m"
                )
            extra = "<p class=\"note\">Também: " + " · ".join(bits) + "</p>"
        mun_cards.append(
            f"""<section class="profile mun" data-axes="{axes}" data-nome="{(m.get('nome') or '').lower()}">
  <h2>{m.get('nome')}</h2>
  <div class="meta">{meta}</div>
  <p class="note">{m.get('note_pt') or ''}</p>
  {extra}
  {m['svg']}
</section>"""
        )

    n_mun = len(report.get("municipal_profiles") or [])
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Perfis longitudinais G040 · MDT SRTM</title>
<style>
:root {{ --ink:#12241c; --muted:#4a6356; --line:#c5d5cb; }}
body {{ margin:0; font:15px/1.5 "IBM Plex Sans", "Segoe UI", sans-serif; color:var(--ink);
  background: linear-gradient(165deg,#d9e6de 0%,#eef3ef 45%,#f7f4ee 100%); }}
header {{ padding:1.1rem 1.2rem; background:rgba(255,255,255,.92); border-bottom:1px solid var(--line); }}
h1 {{ margin:0; font-family:Georgia, serif; font-size:clamp(1.35rem,2.5vw,1.85rem); }}
.lede {{ margin:.45rem 0 0; color:var(--muted); max-width:72ch; }}
main {{ display:grid; gap:12px; padding:12px; max-width:1100px; margin:0 auto; }}
.profile {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px; }}
h2 {{ margin:0 0 4px; font-size:1.05rem; }}
.meta {{ color:var(--muted); font-size:.82rem; margin-bottom:.35rem; }}
.note {{ color:var(--muted); font-size:.84rem; margin:.2rem 0 .55rem; }}
svg {{ width:100%; height:auto; border:1px solid #e2e4dc; border-radius:8px; }}
.foot {{ color:var(--muted); font-size:.8rem; padding:0 1.2rem 1.5rem; max-width:1100px; margin:0 auto; }}
.pill {{ display:inline-block; border:1px solid var(--line); border-radius:999px; padding:.12rem .55rem;
  font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin-right:.35rem; }}
.section-title {{ margin:1.1rem 0 .2rem; font-family:Georgia, serif; font-size:1.25rem; }}
.filters {{ display:flex; flex-wrap:wrap; gap:.4rem; margin:.4rem 0 .7rem; }}
.filters button {{ border:1px solid var(--line); background:#fff; border-radius:999px; padding:.28rem .7rem;
  font:inherit; font-size:.82rem; cursor:pointer; color:var(--muted); }}
.filters button.active {{ background:var(--ink); color:#fff; border-color:var(--ink); }}
#munSearch {{ width:min(100%,320px); padding:.45rem .65rem; border:1px solid var(--line); border-radius:8px; font:inherit; }}
.mun.hidden {{ display:none; }}
.table-wrap {{ overflow:auto; background:#fff; border:1px solid var(--line); border-radius:12px; padding:.4rem; }}
table {{ border-collapse:collapse; width:100%; font-size:.84rem; }}
th,td {{ border-bottom:1px solid #e2e4dc; padding:.35rem .45rem; text-align:left; }}
th {{ color:var(--muted); font-weight:650; }}
</style>
</head>
<body>
<header>
  <span class="pill">pesquisa · não é alerta</span>
  <span class="pill">G040 · SRTM</span>
  <span class="pill">BHO6</span>
  <span class="pill">{n_mun} municípios</span>
  <h1>Perfis longitudinais · bacia Taquari–Antas (G040)</h1>
  <p class="lede">{report['purpose_pt']}</p>
</header>
<main>
<h2 class="section-title">Eixos da bacia</h2>
{''.join(cards)}

<h2 class="section-title" id="municipios">Perfis por município</h2>
<p class="note">Trechos do eixo BHO6 (tronco / Guaporé / Forqueta) cortados pelo polígono de cada município que cruza o rio. {n_mun} municípios com perfil.</p>
<div class="filters" id="axisFilters">
  <button type="button" class="active" data-axis="all">todos</button>
  <button type="button" data-axis="tronco_taquari_antas">tronco</button>
  <button type="button" data-axis="guapore">Guaporé</button>
  <button type="button" data-axis="forqueta">Forqueta</button>
</div>
<p><input id="munSearch" type="search" placeholder="Filtrar município…" aria-label="Filtrar município"/></p>
<div class="table-wrap" style="margin-bottom:.8rem">
<table>
<thead><tr><th>Município</th><th>Eixos</th><th>Comp. km</th><th>Queda m</th><th>Cota início→fim</th></tr></thead>
<tbody>
{''.join(
    f"<tr><td>{m.get('nome')}</td><td>{', '.join(m.get('axes') or [])}</td>"
    f"<td>{(m.get('summary') or {}).get('length_km')}</td>"
    f"<td>{(m.get('summary') or {}).get('drop_m')}</td>"
    f"<td>{(m.get('summary') or {}).get('elev_start_m')}→{(m.get('summary') or {}).get('elev_end_m')}</td></tr>"
    for m in (report.get('municipal_profiles') or [])
)}
</tbody>
</table>
</div>
{''.join(mun_cards)}
</main>
<p class="foot">Gerado {report['generated_at_utc']} · MDT {report['dem']['source']} ·
rede ANA BHO6 · municípios IBGE (pacote vulnerabilidade PREVINE) ·
cota amostrada no terreno (não leito hidráulico). {report['discipline']['caveat_pt']}</p>
<script>
(function() {{
  const buttons = Array.from(document.querySelectorAll('#axisFilters button'));
  const cards = Array.from(document.querySelectorAll('section.mun'));
  const search = document.getElementById('munSearch');
  let axis = 'all';
  function apply() {{
    const q = (search && search.value || '').trim().toLowerCase();
    cards.forEach(function(card) {{
      const axes = (card.getAttribute('data-axes') || '').split(/\\s+/);
      const nome = card.getAttribute('data-nome') || '';
      const okAxis = axis === 'all' || axes.indexOf(axis) >= 0;
      const okName = !q || nome.indexOf(q) >= 0;
      card.classList.toggle('hidden', !(okAxis && okName));
    }});
  }}
  buttons.forEach(function(b) {{
    b.addEventListener('click', function() {{
      axis = b.getAttribute('data-axis') || 'all';
      buttons.forEach(function(x) {{ x.classList.toggle('active', x === b); }});
      apply();
    }});
  }});
  if (search) search.addEventListener('input', apply);
}})();
</script>
</body>
</html>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tile_meta = download_tiles()
    mosaic = make_mosaic()

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    profiles_out: list[dict[str, Any]] = []
    centerlines: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    axis_lines: dict[str, LineString] = {}
    axis_labels = {p["id"]: p["label_pt"] for p in PROFILES}

    with rasterio.open(mosaic) as dem:
        for spec in PROFILES:
            print("fetch BHO", spec["cocursodag"], spec["id"])
            feats = fetch_bho_mainstem(session, spec["cocursodag"])
            ordered = order_mainstem(feats)
            line = merge_ordered_line(ordered)
            axis_lines[spec["id"]] = line
            samples = densify_wgs(line, step_m=250.0)
            rows = downsample_rows(sample_profile(dem, samples), max_n=400)
            summary = summarize(rows)
            svg = svg_polyline(rows)
            profiles_out.append(
                {
                    "id": spec["id"],
                    "label_pt": spec["label_pt"],
                    "role": spec["role"],
                    "note_pt": spec["note_pt"],
                    "cocursodag": spec["cocursodag"],
                    "bho_segment_count": len(feats),
                    "ordered_segment_count": len(ordered),
                    "summary": summary,
                    "series": rows,
                    "svg": svg,
                    "head_fid": int(_props(ordered[0]).get("fid")),
                    "mouth_fid": int(_props(ordered[-1]).get("fid")),
                    "head_area_km2": float(_props(ordered[0]).get("nuareamont") or 0),
                    "mouth_area_km2": float(_props(ordered[-1]).get("nuareamont") or 0),
                }
            )
            centerlines["features"].append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": spec["id"],
                        "label_pt": spec["label_pt"],
                        "cocursodag": spec["cocursodag"],
                        "length_km": summary.get("length_km"),
                        "drop_m": summary.get("drop_m"),
                    },
                    "geometry": mapping(line),
                }
            )
            print(
                f"  {spec['id']}: segs={len(ordered)}/{len(feats)} "
                f"L={summary.get('length_km')} km drop={summary.get('drop_m')} m"
            )

        municipal = build_municipal_profiles(dem, axis_lines, axis_labels)

    report = {
        "schema_version": "g040_basin_profiles_v2",
        "generated_at_utc": utc_now(),
        "status": "research_profiles_ready",
        "purpose_pt": (
            "Perfis longitudinais de terreno (SRTM) na bacia oficial Taquari–Antas (G040): "
            "eixos BHO6 (tronco 786, Guaporé 7864, Forqueta 7862) e trechos por município "
            "que o rio atravessa. Diagnóstico de relevo — não é seção hidráulica nem alerta."
        ),
        "discipline": {
            "not_hydraulic_cross_section": True,
            "not_channel_bed_survey": True,
            "not_hec_ras": True,
            "research_not_alert": True,
            "dem_is_srtm_surface_approx": True,
            "municipal_profiles_are_axis_clips": True,
            "caveat_pt": (
                "SRTM ≈ superfície/terreno grosso (~30 m); pode ficar acima do leito. "
                "Perfis municipais = eixo BHO cortado pelo polígono IBGE, não perfil de "
                "toda a área do município. Use só para leitura de queda/comprimento."
            ),
        },
        "dem": {
            "source": "SRTM 1″ via Mapzen/AWS Skadi elevation-tiles-prod",
            "mosaic": str(mosaic.relative_to(ROOT)).replace("\\", "/"),
            "crs": "EPSG:4326",
            "tiles": tile_meta,
            "step_m_nominal": 250,
        },
        "network": {
            "source": "ANA BHO6 FeatureServer main_geoft_bho6_trecho_drenagem",
            "families": [p["cocursodag"] for p in PROFILES],
            "municipalities_source": str(MUN_GEOJSON.relative_to(ROOT)).replace("\\", "/"),
        },
        "profiles": profiles_out,
        "municipal_profiles": municipal,
        "municipal_count": len(municipal),
        "artifacts": {
            "json": "perfis_longitudinais_g040_latest.json",
            "html": "perfis_longitudinais_g040.html",
            "centerlines_geojson": "perfis_longitudinais_g040_centerlines.geojson",
            "pages_html": "pesquisas/perfis-g040-mdt.html",
        },
    }

    json_path = OUT / "perfis_longitudinais_g040_latest.json"
    html_path = OUT / "perfis_longitudinais_g040.html"
    cl_path = OUT / "perfis_longitudinais_g040_centerlines.geojson"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html = build_html(report)
    html_path.write_text(html, encoding="utf-8")
    PAGES_HTML.parent.mkdir(parents=True, exist_ok=True)
    PAGES_HTML.write_text(html, encoding="utf-8")
    cl_path.write_text(json.dumps(centerlines, ensure_ascii=False), encoding="utf-8")

    print("wrote", json_path.relative_to(ROOT))
    print("wrote", html_path.relative_to(ROOT))
    print("wrote", PAGES_HTML.relative_to(ROOT))
    print("wrote", cl_path.relative_to(ROOT))
    print("municipal_count", len(municipal))


if __name__ == "__main__":
    main()
