#!/usr/bin/env python3
"""Perfis por município + eixos longitudinais MDT da bacia G040.

Produto principal: hipsometria SRTM na área de cada município da G040.
Complementar: eixos BHO6 (tronco 786 / Guaporé 7864 / Forqueta 7862),
marcadores de postos/fozes. Não é seção hidráulica, não alimenta alerta.

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
import numpy as np
import requests
from pyproj import Transformer
from rasterio.mask import mask as raster_mask
from rasterio.merge import merge
from shapely.geometry import LineString, MultiLineString, mapping, shape
from shapely.ops import linemerge, transform as shapely_transform

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
DEM_DIR = OUT / "_dem_srtm_g040"
DEM_DIR.mkdir(parents=True, exist_ok=True)
PAGES_HTML = ROOT / "pesquisas" / "perfis-g040-mdt.html"
MUN_GEOJSON = ROOT / "assets" / "data" / "vulnerabilidade" / "municipios.geojson"
BACIAS_GEOJSON = OUT / "bacias_rs_25.geojson"
POSTOS_GEOJSON = OUT / "postos_g040.geojson"
FOZES_GEOJSON = OUT / "fozes_principais_bho6.geojson"

KEY_STATION_CODES = {
    "86160000",  # Passo Tainhas
    "86447000",  # Balsa do Prata
    "86472000",  # José Júlio
    "86472600",  # Santa Tereza
    "86488000",  # Caçador / Carreiro
    "86510000",  # Muçum
    "86520100",  # Capigui
    "86720000",  # Encantado
    "86743700",  # Rastro Forqueta
    "86895000",  # Porto Mariante
    "86950000",  # Taquari
}

STATION_SHORT_LABEL = {
    "86160000": "Tainhas",
    "86447000": "Balsa Prata",
    "86472000": "José Júlio",
    "86472600": "STZ",
    "86488000": "Caçador",
    "86510000": "Muçum",
    "86520100": "Capigui",
    "86720000": "Encantado",
    "86743700": "Rastro",
    "86895000": "Mariante",
    "86950000": "Taquari",
}

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


def area_km2(geom: Any) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    return float(shapely_transform(lambda x, y: TO_UTM.transform(x, y), geom).area) / 1e6


def load_g040_polygon() -> Any:
    """Official G040 polygon from the RS 25-basins layer."""
    if not BACIAS_GEOJSON.exists():
        raise FileNotFoundError(f"missing basin layer: {BACIAS_GEOJSON}")
    data = json.loads(BACIAS_GEOJSON.read_text(encoding="utf-8"))
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        if str(props.get("codigo") or "").upper() == "G040":
            geom = shape(feat["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            return geom
    raise ValueError("G040 feature not found in bacias_rs_25.geojson")


def sample_hypsometry(
    dem: rasterio.DatasetReader,
    poly: Any,
    max_curve_pts: int = 120,
) -> dict[str, Any] | None:
    """Area hypsometry of SRTM inside a polygon (município ∩ G040)."""
    try:
        data, _ = raster_mask(dem, [mapping(poly)], crop=True, filled=True, nodata=dem.nodata)
    except ValueError:
        return None
    band = data[0]
    nodata = dem.nodata
    if nodata is None:
        valid = band[np.isfinite(band)]
    else:
        valid = band[(band != nodata) & np.isfinite(band)]
    valid = valid[valid > -50]
    if valid.size < 30:
        return None
    elevs = np.sort(valid.astype(np.float64))
    n = int(elevs.size)
    area_km2_val = area_km2(poly)
    idx = np.linspace(0, n - 1, num=min(max_curve_pts, n), dtype=int)
    curve = [
        {
            "area_below_pct": round(100.0 * float(i) / float(n - 1), 2),
            "elev_m": round(float(elevs[i]), 1),
        }
        for i in idx
    ]
    return {
        "n_pixels": n,
        "area_km2": round(area_km2_val, 2),
        "elev_min_m": round(float(elevs[0]), 1),
        "elev_max_m": round(float(elevs[-1]), 1),
        "elev_mean_m": round(float(elevs.mean()), 1),
        "elev_median_m": round(float(np.median(elevs)), 1),
        "elev_p10_m": round(float(np.percentile(elevs, 10)), 1),
        "elev_p90_m": round(float(np.percentile(elevs, 90)), 1),
        "relief_m": round(float(elevs[-1] - elevs[0]), 1),
        "curve": curve,
    }


def svg_hypsometry(
    hypo: dict[str, Any],
    width: int = 680,
    height: int = 220,
) -> str:
    curve = hypo.get("curve") or []
    if len(curve) < 2:
        return (
            f'<svg viewBox="0 0 {width} {height}">'
            f'<text x="24" y="120" fill="#4a6356">Sem hipsometria.</text></svg>'
        )
    pad_l, pad_r, pad_t, pad_b = 48, 18, 22, 40
    xs = [float(p["area_below_pct"]) for p in curve]
    ys = [float(p["elev_m"]) for p in curve]
    xmin, xmax = 0.0, 100.0
    ymin, ymax = min(ys), max(ys)
    if ymax <= ymin:
        ymax = ymin + 1.0

    def x_at(v: float) -> float:
        return pad_l + (v - xmin) / (xmax - xmin) * (width - pad_l - pad_r)

    def y_at(v: float) -> float:
        return pad_t + (1.0 - (v - ymin) / (ymax - ymin)) * (height - pad_t - pad_b)

    pts = " ".join(f"{x_at(x):.1f},{y_at(y):.1f}" for x, y in zip(xs, ys))
    y0 = y_at(ymin)
    med = hypo.get("elev_median_m")
    med_line = ""
    if med is not None:
        ym = y_at(float(med))
        med_line = (
            f'<line x1="{pad_l}" y1="{ym:.1f}" x2="{width-pad_r}" y2="{ym:.1f}" '
            f'stroke="#8a5a12" stroke-dasharray="4 3" stroke-width="1.2"/>'
            f'<text x="{width-pad_r}" y="{ym-4:.1f}" fill="#8a5a12" font-size="10" '
            f'text-anchor="end">mediana {med} m</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="hipsometria municipal">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
        f'<line x1="{pad_l}" y1="{y0:.1f}" x2="{width-pad_r}" y2="{y0:.1f}" stroke="#9aa096"/>'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{y0:.1f}" stroke="#9aa096"/>'
        f'<polyline points="{pts}" fill="none" stroke="#0f5c45" stroke-width="2.4"/>'
        + med_line
        + f'<text x="{pad_l}" y="{height-12}" fill="#4a6356" font-size="11">0% área</text>'
        f'<text x="{(pad_l + width - pad_r) / 2:.0f}" y="{height-12}" fill="#4a6356" '
        f'font-size="11" text-anchor="middle">área abaixo da cota</text>'
        f'<text x="{width-pad_r}" y="{height-12}" fill="#4a6356" font-size="11" '
        f'text-anchor="end">100%</text>'
        f'<text x="8" y="{pad_t+4}" fill="#4a6356" font-size="11">{ymax:.0f} m</text>'
        f'<text x="8" y="{y0:.1f}" fill="#4a6356" font-size="11">{ymin:.0f} m</text>'
        f"</svg>"
    )


def elev_at_distance(rows: list[dict[str, Any]], dist_km: float) -> float | None:
    if not rows:
        return None
    if dist_km <= rows[0]["distance_km"]:
        return float(rows[0]["elev_m"])
    if dist_km >= rows[-1]["distance_km"]:
        return float(rows[-1]["elev_m"])
    for left, right in zip(rows, rows[1:]):
        if left["distance_km"] <= dist_km <= right["distance_km"]:
            span = right["distance_km"] - left["distance_km"] or 1e-9
            t = (dist_km - left["distance_km"]) / span
            return float(left["elev_m"] + t * (right["elev_m"] - left["elev_m"]))
    return None


def svg_polyline(
    rows: list[dict[str, Any]],
    width: int = 720,
    height: int = 240,
    markers: list[dict[str, Any]] | None = None,
) -> str:
    if len(rows) < 2:
        return f'<svg viewBox="0 0 {width} {height}"><text x="24" y="120" fill="#4a6356">Sem pontos.</text></svg>'
    pad_l, pad_r, pad_t, pad_b = 48, 18, 22, 36
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
    marks: list[str] = []
    for m in markers or []:
        d = m.get("distance_km")
        if d is None or d < xmin - 0.5 or d > xmax + 0.5:
            continue
        elev = m.get("elev_m")
        if elev is None:
            elev = elev_at_distance(rows, float(d))
        if elev is None:
            continue
        x = x_at(float(d))
        y = y_at(float(elev))
        label = str(m.get("short_label") or m.get("label") or "")
        marks.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" fill="#8a5a12" '
            f'stroke="#fff" stroke-width="1.2"/>'
        )
        if label:
            marks.append(
                f'<text x="{x+5:.1f}" y="{y-7:.1f}" fill="#8a5a12" font-size="10">'
                f"{label}</text>"
            )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="perfil longitudinal">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
        f'<line x1="{pad_l}" y1="{y0:.1f}" x2="{width-pad_r}" y2="{y0:.1f}" stroke="#9aa096"/>'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{y0:.1f}" stroke="#9aa096"/>'
        f'<polyline points="{pts}" fill="none" stroke="#0f5c45" stroke-width="2.4"/>'
        + "".join(marks)
        + f'<text x="{pad_l}" y="{height-10}" fill="#4a6356" font-size="11">'
        f"{xmin:.0f} km</text>"
        f'<text x="{width-pad_r}" y="{height-10}" fill="#4a6356" font-size="11" text-anchor="end">'
        f"{xmax:.0f} km</text>"
        f'<text x="8" y="{pad_t+4}" fill="#4a6356" font-size="11">{ymax:.0f} m</text>'
        f'<text x="8" y="{y0:.1f}" fill="#4a6356" font-size="11">{ymin:.0f} m</text>'
        f"</svg>"
    )


def attach_axis_markers(
    axis_lines: dict[str, LineString],
    profiles_by_id: dict[str, dict[str, Any]],
    max_off_axis_m: float = 8000.0,
) -> list[dict[str, Any]]:
    """Project key flu stations + fozes onto nearest BHO axis."""
    from shapely.geometry import Point as ShPoint

    axis_utm = {
        aid: shapely_transform(lambda x, y: TO_UTM.transform(x, y), line)
        for aid, line in axis_lines.items()
    }
    candidates: list[dict[str, Any]] = []
    if POSTOS_GEOJSON.exists():
        postos = json.loads(POSTOS_GEOJSON.read_text(encoding="utf-8"))
        for feat in postos.get("features") or []:
            p = feat.get("properties") or {}
            code = str(p.get("codigo") or "")
            if code not in KEY_STATION_CODES:
                continue
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            candidates.append(
                {
                    "kind": "flu",
                    "code": code,
                    "label": p.get("nome") or code,
                    "short_label": STATION_SHORT_LABEL.get(code)
                    or (p.get("nome") or code).split()[0][:12],
                    "municipio": p.get("municipio"),
                    "lon": lon,
                    "lat": lat,
                }
            )
    if FOZES_GEOJSON.exists():
        fozes = json.loads(FOZES_GEOJSON.read_text(encoding="utf-8"))
        for feat in fozes.get("features") or []:
            p = feat.get("properties") or {}
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            family = str(p.get("family_code") or p.get("cocursodag") or "")
            label = p.get("label") or f"foz {family}"
            short = {
                "7868": "foz Prata",
                "7866": "foz Carreiro",
                "7864": "foz Guaporé",
                "7862": "foz Forqueta",
            }.get(family, f"foz {family}")
            candidates.append(
                {
                    "kind": "foz",
                    "code": family,
                    "label": label,
                    "short_label": short,
                    "municipio": None,
                    "lon": float(coords[0]),
                    "lat": float(coords[1]),
                    "prefer_axis": {
                        "7864": "guapore",
                        "7862": "forqueta",
                        "7868": "tronco_taquari_antas",
                        "7866": "tronco_taquari_antas",
                    }.get(family),
                }
            )

    markers: list[dict[str, Any]] = []
    for c in candidates:
        px, py = TO_UTM.transform(c["lon"], c["lat"])
        pt = ShPoint(px, py)
        best_aid = None
        best_dist = 1e18
        best_along = None
        prefer = c.get("prefer_axis")
        axis_ids = list(axis_utm.keys())
        if prefer and prefer in axis_utm:
            axis_ids = [prefer] + [a for a in axis_ids if a != prefer]
        for aid in axis_ids:
            line_u = axis_utm[aid]
            d = float(line_u.distance(pt))
            # Prefer preferred axis even if slightly farther.
            score = d * (0.55 if prefer and aid == prefer else 1.0)
            if score < best_dist:
                best_dist = score
                best_aid = aid
                best_along = float(line_u.project(pt))
        true_dist = float(axis_utm[best_aid].distance(pt)) if best_aid else 1e18
        if best_aid is None or true_dist > max_off_axis_m:
            continue
        series = (profiles_by_id.get(best_aid) or {}).get("series") or []
        dist_km = round((best_along or 0.0) / 1000.0, 3)
        elev = elev_at_distance(series, dist_km)
        marker = {
            **c,
            "axis_id": best_aid,
            "distance_km": dist_km,
            "off_axis_m": round(true_dist, 1),
            "elev_m": None if elev is None else round(elev, 1),
        }
        markers.append(marker)
        # attach to profile list
        profiles_by_id[best_aid].setdefault("markers", []).append(marker)

    # rebuild SVGs with markers
    for aid, prof in profiles_by_id.items():
        marks = prof.get("markers") or []
        marks = sorted(marks, key=lambda m: float(m.get("distance_km") or 0))
        prof["markers"] = marks
        prof["svg"] = svg_polyline(prof["series"], markers=marks)

    markers.sort(key=lambda m: (m.get("axis_id") or "", float(m.get("distance_km") or 0)))
    return markers


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
    """Perfil por município: hipsometria na área do município ∩ G040."""
    if not MUN_GEOJSON.exists():
        print("WARN: municipal geojson missing", MUN_GEOJSON)
        return []
    mun = json.loads(MUN_GEOJSON.read_text(encoding="utf-8"))
    g040 = load_g040_polygon()
    print("G040 polygon loaded, area_km2", round(area_km2(g040), 1))
    axis_utm = {
        aid: shapely_transform(lambda x, y: TO_UTM.transform(x, y), line)
        for aid, line in axis_lines.items()
    }
    out: list[dict[str, Any]] = []
    skipped_empty = 0
    for feat in mun["features"]:
        props = feat.get("properties") or {}
        nome = props.get("nome") or props.get("NM_MUN") or "Município"
        cod = str(props.get("cod_mun") or props.get("CD_MUN") or "")
        poly_full = shape(feat["geometry"])
        if not poly_full.is_valid:
            poly_full = poly_full.buffer(0)
        if poly_full.is_empty:
            continue

        poly_in = poly_full.intersection(g040)
        if not poly_in.is_valid:
            poly_in = poly_in.buffer(0)
        if poly_in.is_empty:
            skipped_empty += 1
            continue

        area_full = area_km2(poly_full)
        area_in = area_km2(poly_in)
        pct_geom = round(100.0 * area_in / area_full, 1) if area_full > 0 else None

        hypo = sample_hypsometry(dem, poly_in)
        if hypo is None:
            skipped_empty += 1
            continue
        hypo_svg = svg_hypsometry(hypo)

        # River clips against the full municipal polygon (axes already in-basin).
        stretches: list[dict[str, Any]] = []
        for aid, line in axis_lines.items():
            inter = line.intersection(poly_full)
            parts = line_parts(inter)
            if not parts:
                continue
            ranked: list[tuple[float, LineString]] = []
            for part in parts:
                mid = part.interpolate(0.5, normalized=True)
                ranked.append((project_point_m(axis_utm[aid], mid.x, mid.y), part))
            ranked.sort(key=lambda t: t[0])
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

        primary = None
        if stretches:
            primary = max(stretches, key=lambda s: float(s["summary"].get("length_km") or 0))

        border = bool(pct_geom is not None and pct_geom < 99.5)
        out.append(
            {
                "id": f"mun_{cod}",
                "cod_mun": cod,
                "nome": nome,
                "pct_na_bacia": pct_geom if pct_geom is not None else props.get("pct_na_bacia"),
                "pct_na_bacia_attr": props.get("pct_na_bacia"),
                "status_borda_bacia": "parcial" if border else "total",
                "hypsometry_domain": "municipio_intersect_g040",
                "area_mun_km2": round(area_full, 2),
                "area_in_basin_km2": round(area_in, 2),
                "hypsometry": {
                    **{k: v for k, v in hypo.items() if k != "curve"},
                    "curve": hypo["curve"],
                },
                "svg": hypo_svg,
                "axes": [s["axis_id"] for s in stretches],
                "stretches": stretches,
                "primary_axis_id": None if primary is None else primary["axis_id"],
                "river_summary": None if primary is None else primary["summary"],
                "river_svg": None if primary is None else primary["svg"],
                "summary": {
                    "area_km2": hypo["area_km2"],
                    "area_mun_km2": round(area_full, 2),
                    "area_in_basin_km2": round(area_in, 2),
                    "elev_min_m": hypo["elev_min_m"],
                    "elev_max_m": hypo["elev_max_m"],
                    "elev_mean_m": hypo["elev_mean_m"],
                    "elev_median_m": hypo["elev_median_m"],
                    "relief_m": hypo["relief_m"],
                    "n_pixels": hypo["n_pixels"],
                    "river_length_km": None
                    if primary is None
                    else primary["summary"].get("length_km"),
                },
                "label_pt": f"{nome} · hipsometria na G040",
                "note_pt": (
                    "Perfil por município = hipsometria SRTM na interseção "
                    "polígono IBGE ∩ bacia oficial G040 (cota vs % de área abaixo). "
                    + (
                        "Trecho de rio no eixo BHO6 é complementar."
                        if stretches
                        else "Município não cruza os eixos tronco/Guaporé/Forqueta plotados."
                    )
                    + (
                        f" Borda: {pct_geom}% da área municipal dentro da G040 "
                        f"({round(area_in, 1)} de {round(area_full, 1)} km²)."
                        if border
                        else ""
                    )
                ),
            }
        )
    out.sort(
        key=lambda m: (
            -float((m.get("summary") or {}).get("relief_m") or 0),
            m["nome"],
        )
    )
    print("municipal profiles", len(out), "skipped_empty", skipped_empty)
    return out


def simplify_centerlines_for_map(
    centerlines: dict[str, Any],
    max_pts_per_line: int = 400,
) -> dict[str, Any]:
    """Downsample LineString coords so Leaflet payload stays small."""
    out_feats: list[dict[str, Any]] = []
    for feat in centerlines.get("features") or []:
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "LineString" or len(coords) <= max_pts_per_line:
            out_feats.append(feat)
            continue
        step = max(1, len(coords) // max_pts_per_line)
        kept = list(coords[::step])
        if kept[-1] != coords[-1]:
            kept.append(coords[-1])
        out_feats.append(
            {
                "type": "Feature",
                "properties": feat.get("properties") or {},
                "geometry": {"type": "LineString", "coordinates": kept},
            }
        )
    return {"type": "FeatureCollection", "features": out_feats}


def markers_table_html(markers: list[dict[str, Any]]) -> str:
    if not markers:
        return ""
    rows = []
    for m in markers:
        kind = "flu" if m.get("kind") == "flu" else "foz"
        rows.append(
            "<tr>"
            f"<td>{kind}</td>"
            f"<td>{m.get('short_label') or m.get('label')}</td>"
            f"<td>{m.get('code')}</td>"
            f"<td>{m.get('distance_km')}</td>"
            f"<td>{m.get('elev_m')}</td>"
            f"<td>{m.get('off_axis_m')}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap markers-table"><table>'
        "<thead><tr><th>Tipo</th><th>Marcador</th><th>Código</th>"
        "<th>km eixo</th><th>cota m</th><th>off-axis m</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


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
        marks = p.get("markers") or []
        mark_note = (
            f'<p class="note">{len(marks)} marcadores (postos-chave + fozes projetados no eixo).</p>'
            if marks
            else ""
        )
        cards.append(
            f"""<section class="profile">
  <h2>{p['label_pt']}</h2>
  <div class="meta">{meta}</div>
  <p class="note">{p.get('note_pt') or ''}</p>
  {p['svg']}
  {mark_note}
  {markers_table_html(marks)}
</section>"""
        )

    mun_cards = []
    for m in report.get("municipal_profiles") or []:
        s = m["summary"]
        axes_attr = " ".join(m.get("axes") or [])
        pct = m.get("pct_na_bacia")
        meta = (
            f"área na G040 {s.get('area_in_basin_km2') or s.get('area_km2')} km² · "
            f"% mun {pct} · "
            f"cota {s.get('elev_min_m')}–{s.get('elev_max_m')} m · "
            f"mediana {s.get('elev_median_m')} m · "
            f"relevo {s.get('relief_m')} m"
        )
        river_block = ""
        if m.get("river_svg"):
            rs = m.get("river_summary") or {}
            river_block = (
                f'<p class="note">Trecho de rio complementar '
                f"({m.get('primary_axis_id')}): "
                f"{rs.get('length_km')} km · queda {rs.get('drop_m')} m</p>"
                f"{m['river_svg']}"
            )
        mun_cards.append(
            f"""<section class="profile mun" data-axes="{axes_attr}" data-nome="{(m.get('nome') or '').lower()}" data-has-river="{'1' if m.get('river_svg') else '0'}">
  <h2>{m.get('nome')}</h2>
  <div class="meta">{meta}</div>
  <p class="note">{m.get('note_pt') or ''}</p>
  {m['svg']}
  {river_block}
</section>"""
        )

    n_mun = len(report.get("municipal_profiles") or [])
    n_mark = len(report.get("axis_markers") or [])
    map_payload = {
        "centerlines": report.get("map_centerlines_simplified")
        or {"type": "FeatureCollection", "features": []},
        "markers": report.get("axis_markers") or [],
    }
    map_json = json.dumps(map_payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Perfis por município · G040 · MDT SRTM</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
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
.markers-table {{ margin-top:.55rem; }}
table {{ border-collapse:collapse; width:100%; font-size:.84rem; }}
th,td {{ border-bottom:1px solid #e2e4dc; padding:.35rem .45rem; text-align:left; }}
th {{ color:var(--muted); font-weight:650; }}
#axisMap {{ height:min(420px,55vh); width:100%; border-radius:10px; border:1px solid var(--line); }}
.map-legend {{ color:var(--muted); font-size:.8rem; margin:.35rem 0 0; }}
</style>
</head>
<body>
<header>
  <span class="pill">pesquisa · não é alerta</span>
  <span class="pill">G040 · SRTM</span>
  <span class="pill">perfil por município</span>
  <span class="pill">{n_mun} municípios</span>
  <span class="pill">{n_mark} marcadores de eixo</span>
  <h1>Perfis por município · bacia Taquari–Antas (G040)</h1>
  <p class="lede">{report['purpose_pt']}</p>
</header>
<main>
<h2 class="section-title" id="municipios">Perfis por município</h2>
<p class="note">Hipsometria SRTM na interseção município IBGE ∩ bacia oficial G040 (cota × % da área abaixo). Trecho de rio nos eixos BHO6 é complementar. {n_mun} municípios.</p>
<div class="filters" id="axisFilters">
  <button type="button" class="active" data-axis="all">todos</button>
  <button type="button" data-axis="tronco_taquari_antas">com tronco</button>
  <button type="button" data-axis="guapore">com Guaporé</button>
  <button type="button" data-axis="forqueta">com Forqueta</button>
  <button type="button" data-axis="sem_eixo">só área (sem eixo)</button>
</div>
<p><input id="munSearch" type="search" placeholder="Filtrar município…" aria-label="Filtrar município"/></p>
<div class="table-wrap" style="margin-bottom:.8rem">
<table>
<thead><tr><th>Município</th><th>% G040</th><th>Área na G040 km²</th><th>Cota min–max</th><th>Mediana</th><th>Relevo m</th><th>Eixos</th></tr></thead>
<tbody>
{''.join(
    f"<tr><td>{m.get('nome')}</td>"
    f"<td>{m.get('pct_na_bacia')}</td>"
    f"<td>{(m.get('summary') or {}).get('area_in_basin_km2') or (m.get('summary') or {}).get('area_km2')}</td>"
    f"<td>{(m.get('summary') or {}).get('elev_min_m')}–{(m.get('summary') or {}).get('elev_max_m')}</td>"
    f"<td>{(m.get('summary') or {}).get('elev_median_m')}</td>"
    f"<td>{(m.get('summary') or {}).get('relief_m')}</td>"
    f"<td>{', '.join(m.get('axes') or []) or '—'}</td></tr>"
    for m in (report.get('municipal_profiles') or [])
)}
</tbody>
</table>
</div>
{''.join(mun_cards)}

<h2 class="section-title" id="mapa">Mapa dos eixos (complementar)</h2>
<p class="note">Tronco, Guaporé e Forqueta (BHO6) com postos-chave e fozes projetados no eixo mais próximo.</p>
<div id="axisMap" role="img" aria-label="mapa dos eixos longitudinais G040"></div>
<p class="map-legend">Linha verde = tronco · azul = Guaporé · ocre = Forqueta · círculos = flu · losangos = foz.</p>

<h2 class="section-title">Eixos da bacia (complementar)</h2>
{''.join(cards)}
</main>
<p class="foot">Gerado {report['generated_at_utc']} · MDT {report['dem']['source']} ·
rede ANA BHO6 · municípios IBGE (pacote vulnerabilidade PREVINE) ·
cota amostrada no terreno (não leito hidráulico). {report['discipline']['caveat_pt']}</p>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script id="mapData" type="application/json">{map_json}</script>
<script>
(function() {{
  const buttons = Array.from(document.querySelectorAll('#axisFilters button'));
  const cards = Array.from(document.querySelectorAll('section.mun'));
  const search = document.getElementById('munSearch');
  let axis = 'all';
  function apply() {{
    const q = (search && search.value || '').trim().toLowerCase();
    cards.forEach(function(card) {{
      const axesRaw = (card.getAttribute('data-axes') || '').trim();
      const axes = axesRaw ? axesRaw.split(/\\s+/) : [];
      const nome = card.getAttribute('data-nome') || '';
      const hasRiver = card.getAttribute('data-has-river') === '1';
      let okAxis = true;
      if (axis === 'sem_eixo') okAxis = !hasRiver;
      else if (axis !== 'all') okAxis = axes.indexOf(axis) >= 0;
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

  const raw = document.getElementById('mapData');
  if (!raw || typeof L === 'undefined') return;
  const payload = JSON.parse(raw.textContent || '{{}}');
  const map = L.map('axisMap').setView([-29.15, -51.55], 8);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap',
    maxZoom: 16
  }}).addTo(map);
  const colors = {{
    tronco_taquari_antas: '#0f5c45',
    guapore: '#1d6f9c',
    forqueta: '#8a5a12'
  }};
  const layers = [];
  if (payload.centerlines && payload.centerlines.features) {{
    const cl = L.geoJSON(payload.centerlines, {{
      style: function(feat) {{
        const id = (feat.properties && feat.properties.id) || '';
        return {{ color: colors[id] || '#333', weight: 3.2, opacity: 0.92 }};
      }},
      onEachFeature: function(feat, layer) {{
        const p = feat.properties || {{}};
        layer.bindPopup((p.label_pt || p.id || '') +
          '<br>L=' + (p.length_km || '?') + ' km · queda ' + (p.drop_m || '?') + ' m');
      }}
    }}).addTo(map);
    layers.push(cl);
  }}
  (payload.markers || []).forEach(function(m) {{
    if (m.lat == null || m.lon == null) return;
    const isFoz = m.kind === 'foz';
    const marker = L.circleMarker([m.lat, m.lon], {{
      radius: isFoz ? 7 : 5.5,
      color: '#fff',
      weight: 1.4,
      fillColor: isFoz ? '#8a5a12' : '#12241c',
      fillOpacity: 0.95
    }}).addTo(map);
    marker.bindPopup(
      '<strong>' + (m.short_label || m.label || '') + '</strong><br>' +
      (m.kind || '') + ' · ' + (m.code || '') + '<br>' +
      'eixo ' + (m.axis_id || '') + ' · ' + (m.distance_km || '?') + ' km · ' +
      (m.elev_m != null ? m.elev_m + ' m' : 'cota n/d')
    );
    layers.push(marker);
  }});
  if (layers.length) {{
    const group = L.featureGroup(layers);
    map.fitBounds(group.getBounds().pad(0.08));
  }}
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

    profiles_by_id = {p["id"]: p for p in profiles_out}
    axis_markers = attach_axis_markers(axis_lines, profiles_by_id)
    print("axis markers", len(axis_markers))

    report = {
        "schema_version": "g040_basin_profiles_v5",
        "generated_at_utc": utc_now(),
        "status": "research_profiles_ready",
        "purpose_pt": (
            "Perfil por município na bacia oficial Taquari–Antas (G040): hipsometria SRTM "
            "na interseção município IBGE ∩ G040 (cota × % da área abaixo). Complementar: "
            "eixos BHO6 (tronco 786, Guaporé 7864, Forqueta 7862) com marcadores de "
            "postos/fozes. Diagnóstico de relevo — não é seção hidráulica nem alerta."
        ),
        "discipline": {
            "not_hydraulic_cross_section": True,
            "not_channel_bed_survey": True,
            "not_hec_ras": True,
            "research_not_alert": True,
            "dem_is_srtm_surface_approx": True,
            "municipal_profiles_are_hypsometry": True,
            "municipal_hypsometry_clipped_to_g040": True,
            "municipal_river_clips_are_complementary": True,
            "markers_are_axis_projections": True,
            "border_mun_use_full_polygon": False,
            "caveat_pt": (
                "SRTM ≈ superfície/terreno grosso (~30 m). Perfil municipal = hipsometria "
                "na área do município dentro da G040 (IBGE ∩ bacia oficial). "
                "pct_na_bacia vem da geometria. Trechos de rio e marcadores são "
                "complementares. Não é leito hidráulico nem alerta."
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
            "basin_source": str(BACIAS_GEOJSON.relative_to(ROOT)).replace("\\", "/"),
            "postos_source": str(POSTOS_GEOJSON.relative_to(ROOT)).replace("\\", "/"),
            "fozes_source": str(FOZES_GEOJSON.relative_to(ROOT)).replace("\\", "/"),
        },
        "profiles": profiles_out,
        "axis_markers": axis_markers,
        "axis_marker_count": len(axis_markers),
        "map_centerlines_simplified": simplify_centerlines_for_map(centerlines),
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

    html = build_html(report)
    # Keep simplified centerlines out of the audit JSON (full lines live in geojson).
    report.pop("map_centerlines_simplified", None)

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
