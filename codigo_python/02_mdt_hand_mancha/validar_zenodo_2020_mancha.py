#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cruza o banco Zenodo da cheia de julho/2020 (Giordani et al.,
https://doi.org/10.5281/zenodo.4730371) com as manchas HAND do PREVINE
(Muçum e Santa Tereza).

Entradas esperadas em --zenodo-dir (default /tmp/zenodo_4730371):
  - Demarcated_points_*.shp
  - flooded_area_08_july_2020_n_0.030.tif (e opcionalmente n_0.045 / dia 09)

Saídas em assets/data/validacao_zenodo_2020/:
  - relatorio_cruzamento.json
  - pontos_mucum_08jul2020.geojson
  - resumo.md

Uso:
  python codigo_python/02_mdt_hand_mancha/validar_zenodo_2020_mancha.py
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.windows import from_bounds
from shapely.geometry import box, mapping

RAIZ = Path(__file__).resolve().parents[2]
OUT = RAIZ / "assets" / "data" / "validacao_zenodo_2020"

# Pico Muçum 08/07/2020 — ABRHidro / série 86510000 (Marcuzzo): 2202 cm
PICO_MUCUM_CM = 2202
BANKFULL_MUCUM_CM = 500
HAND_PICO_MUCUM_M = (PICO_MUCUM_CM - BANKFULL_MUCUM_CM) / 100.0  # 17.02 m

CIDADES = {
    "mucum": {
        "html": RAIZ / "mucum_inundacao.html",
        "bankfull_cm": BANKFULL_MUCUM_CM,
        "label": "Muçum",
    },
    "santa_tereza": {
        "html": RAIZ / "santa_tereza_inundacao.html",
        "bankfull_cm": 400,
        "label": "Santa Tereza",
    },
}


def load_hand(html_path: Path):
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', text, re.S)
    if not m:
        raise SystemExit(f"hand-data ausente em {html_path}")
    d = json.loads(m.group(1))
    png = base64.b64decode(d["hand_png_b64"])
    arr = np.array(Image.open(io.BytesIO(png)), dtype=np.float32) / 10.0  # dm -> m
    meta = {
        "W": float(d["W"]),
        "S": float(d["S"]),
        "E": float(d["E"]),
        "N": float(d["N"]),
        "cols": int(d["cols"]),
        "rows": int(d["rows"]),
        "bankfull_cm": d.get("bankfull_cm"),
        "fonte": d.get("fonte"),
    }
    if arr.shape != (meta["rows"], meta["cols"]):
        # PNG pode vir trocado; confia no array
        meta["rows"], meta["cols"] = int(arr.shape[0]), int(arr.shape[1])
    return arr, meta


def sample_hand(hand, meta, lon, lat):
    cols, rows = meta["cols"], meta["rows"]
    fx = (lon - meta["W"]) / (meta["E"] - meta["W"]) * cols
    fy = (meta["N"] - lat) / (meta["N"] - meta["S"]) * rows
    c, r = int(fx), int(fy)
    if c < 0 or r < 0 or c >= cols or r >= rows:
        return None
    return float(hand[r, c])


def load_points(zenodo_dir: Path) -> gpd.GeoDataFrame:
    frames = []
    for p in sorted(zenodo_dir.glob("Demarcated_points_*.shp")):
        g = gpd.read_file(p)
        g["data"] = p.stem.replace("Demarcated_points_", "")
        # Zenodo traz MultiPoint nos dias 08/09 — explode para Point
        g = g.explode(index_parts=False, ignore_index=True)
        frames.append(g)
    if not frames:
        raise SystemExit(f"nenhum shapefile em {zenodo_dir}")
    G = gpd.GeoDataFrame(pd_concat(frames), crs="EPSG:4326")
    G["lon"] = G.geometry.x
    G["lat"] = G.geometry.y
    return G


def pd_concat(frames):
    import pandas as pd

    return pd.concat(frames, ignore_index=True)


def mgb_window_mask(tif: Path, bounds, out_shape):
    """Reprojeta a máscara molhada do MGB para a grade HAND (rows, cols)."""
    W, S, E, N = bounds
    rows, cols = out_shape
    with rasterio.open(tif) as ds:
        win = from_bounds(W, S, E, N, ds.transform)
        src = ds.read(1, window=win, boundless=True, fill_value=ds.nodata)
        src = np.where((src == ds.nodata) | (src < 0), 0.0, src).astype("float32")
        src_transform = ds.window_transform(win)
        dst = np.zeros(out_shape, dtype="float32")
        dst_transform = rasterio.transform.from_bounds(W, S, E, N, cols, rows)
        reproject(
            source=src,
            destination=dst,
            src_transform=src_transform,
            src_crs=ds.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
        )
    wet = dst > 0
    depth = dst
    return wet, depth


def iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else None


def point_stats(G, hand, meta, city_box, mgb_depth=None):
    inside = G[G.geometry.within(city_box)].copy()
    rows = []
    for _, r in inside.iterrows():
        h = sample_hand(hand, meta, r.lon, r.lat)
        d_mgb = None
        if mgb_depth is not None and h is not None:
            # sample same grid
            cols, rows_n = meta["cols"], meta["rows"]
            fx = (r.lon - meta["W"]) / (meta["E"] - meta["W"]) * cols
            fy = (meta["N"] - r.lat) / (meta["N"] - meta["S"]) * rows_n
            c, rr = int(fx), int(fy)
            if 0 <= c < cols and 0 <= rr < rows_n:
                d_mgb = float(mgb_depth[rr, c])
        rows.append(
            {
                "cidade_zenodo": r.Cidade,
                "data": r.data,
                "id_ponto": int(r.ID_PONTO) if r.ID_PONTO == r.ID_PONTO else None,
                "lon": float(r.lon),
                "lat": float(r.lat),
                "hand_m": h,
                "mgb_depth": d_mgb,
                "mgb_wet": (d_mgb is not None and d_mgb > 0),
            }
        )
    return rows


def summarize_city(nome, rows, hand_threshold_m, bankfull_cm, pico_cm=None):
    vals = [r["hand_m"] for r in rows if r["hand_m"] is not None]
    covered = [r for r in rows if r["hand_m"] is not None and r["hand_m"] <= hand_threshold_m]
    covered_15 = [r for r in rows if r["hand_m"] is not None and r["hand_m"] <= 15.0]
    with_mgb = [r for r in rows if r["mgb_depth"] is not None]
    agree = [
        r
        for r in with_mgb
        if (r["hand_m"] is not None and r["hand_m"] <= hand_threshold_m) == bool(r["mgb_wet"])
    ]
    return {
        "cidade": nome,
        "n_pontos_no_bbox": len(rows),
        "n_com_hand": len(vals),
        "hand_min_m": float(np.min(vals)) if vals else None,
        "hand_p50_m": float(np.percentile(vals, 50)) if vals else None,
        "hand_p90_m": float(np.percentile(vals, 90)) if vals else None,
        "hand_max_m": float(np.max(vals)) if vals else None,
        "bankfull_cm": bankfull_cm,
        "pico_cm_referencia": pico_cm,
        "hand_threshold_m": hand_threshold_m,
        "cobertura_no_pico_pct": round(100 * len(covered) / len(vals), 1) if vals else None,
        "cobertura_hand15_pct": round(100 * len(covered_15) / len(vals), 1) if vals else None,
        "acordo_hand_vs_mgb_pct": round(100 * len(agree) / len(with_mgb), 1) if with_mgb else None,
        "n_mgb_wet": sum(1 for r in with_mgb if r["mgb_wet"]),
        "n_mgb_dry": sum(1 for r in with_mgb if not r["mgb_wet"]),
        "cidades_zenodo": dict(Counter(r["cidade_zenodo"] for r in rows)),
        "datas": dict(Counter(r["data"] for r in rows)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zenodo-dir", default="/tmp/zenodo_4730371")
    args = ap.parse_args()
    zdir = Path(args.zenodo_dir)
    OUT.mkdir(parents=True, exist_ok=True)

    G = load_points(zdir)
    report = {
        "fonte_zenodo": {
            "doi": "10.5281/zenodo.4730371",
            "titulo": "July 2020's flood database in the Taquari-Antas river basin",
            "autores": "Giordani, Fan & Alves (UFRGS/HGE)",
            "n_pontos_total": int(len(G)),
            "cidades": dict(Counter(G.Cidade)),
        },
        "referencia_pico_mucum": {
            "data": "2020-07-08",
            "cota_cm": PICO_MUCUM_CM,
            "fonte": "ABRHidro — maior cheia histórica em Muçum até 2020 (série 86510000)",
            "bankfull_cm_site": BANKFULL_MUCUM_CM,
            "hand_equivalente_m": HAND_PICO_MUCUM_M,
        },
        "cidades": {},
        "iou": {},
    }

    mgb030 = zdir / "flooded_area_08_july_2020_n_0.030.tif"
    mgb045 = zdir / "flooded_area_08_july_2020_n_0.045.tif"

    mucum_rows = []
    for key, cfg in CIDADES.items():
        hand, meta = load_hand(cfg["html"])
        if meta.get("bankfull_cm") is None:
            meta["bankfull_cm"] = cfg["bankfull_cm"]
        city_box = box(meta["W"], meta["S"], meta["E"], meta["N"])
        thr = HAND_PICO_MUCUM_M if key == "mucum" else 15.0
        pico = PICO_MUCUM_CM if key == "mucum" else None

        mgb_depth = None
        if mgb030.exists():
            wet, depth = mgb_window_mask(
                mgb030, (meta["W"], meta["S"], meta["E"], meta["N"]), hand.shape
            )
            mgb_depth = depth
            # IoU HAND vs MGB no pico (ou 15 m)
            hand_flood = hand <= thr
            # ignora nodata/fora — HAND sempre preenchido; MGB usa wet
            report["iou"][f"{key}_hand_vs_mgb_n0030_thr{thr:.2f}"] = {
                "iou": iou(hand_flood, wet),
                "hand_wet_px": int(hand_flood.sum()),
                "mgb_wet_px": int(wet.sum()),
                "inter_px": int(np.logical_and(hand_flood, wet).sum()),
            }
            if mgb045.exists():
                wet45, _ = mgb_window_mask(
                    mgb045, (meta["W"], meta["S"], meta["E"], meta["N"]), hand.shape
                )
                report["iou"][f"{key}_hand_vs_mgb_n0045_thr{thr:.2f}"] = {
                    "iou": iou(hand_flood, wet45),
                    "hand_wet_px": int(hand_flood.sum()),
                    "mgb_wet_px": int(wet45.sum()),
                    "inter_px": int(np.logical_and(hand_flood, wet45).sum()),
                }
            # melhor limiar HAND por IoU (0.5..24.5 step 0.5) — PNG vai até 25 m
            best = {"thr": None, "iou": -1}
            for t in np.arange(0.5, 24.51, 0.5):
                v = iou(hand <= t, wet)
                if v is not None and v > best["iou"]:
                    best = {"thr": float(t), "iou": float(v)}
            report["iou"][f"{key}_melhor_limiar_hand_vs_mgb_n0030"] = best

        rows = point_stats(G, hand, meta, city_box, mgb_depth)
        if key == "mucum":
            mucum_rows = rows
        summary = summarize_city(cfg["label"], rows, thr, meta["bankfull_cm"], pico_cm=pico)
        # subconjunto só com rótulo municipal "Muçum"
        if key == "mucum":
            only = [r for r in rows if str(r["cidade_zenodo"]).strip().lower() in ("muçum", "mucum")]
            summary["somente_rotulo_mucum"] = summarize_city(
                "Muçum (rótulo)", only, thr, meta["bankfull_cm"], pico_cm=pico
            )
            # matriz de confusão HAND@pico × MGB
            tp = fp = fn = tn = 0
            for r in rows:
                if r["hand_m"] is None or r["mgb_depth"] is None:
                    continue
                hw = r["hand_m"] <= thr
                mw = bool(r["mgb_wet"])
                if hw and mw:
                    tp += 1
                elif hw and not mw:
                    fp += 1
                elif (not hw) and mw:
                    fn += 1
                else:
                    tn += 1
            summary["confusao_hand_pico_vs_mgb"] = {
                "TP": tp,
                "FP": fp,
                "FN": fn,
                "TN": tn,
                "nota": "Pontos Zenodo são evidência de inundação; FP=HAND molha onde MGB não; FN=MGB molha onde HAND no pico não cobre.",
            }
        report["cidades"][key] = summary

    # GeoJSON Muçum 08/jul
    feats = []
    for r in mucum_rows:
        if r["data"] != "08_july_2020":
            continue
        thr = HAND_PICO_MUCUM_M
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    **{k: r[k] for k in r if k not in ("lon", "lat")},
                    "coberto_no_pico": r["hand_m"] is not None and r["hand_m"] <= thr,
                    "hand_threshold_m": thr,
                },
                "geometry": mapping(
                    __import__("shapely.geometry", fromlist=["Point"]).Point(r["lon"], r["lat"])
                ),
            }
        )
    geo = {
        "type": "FeatureCollection",
        "name": "pontos_zenodo_mucum_08jul2020",
        "features": feats,
    }
    (OUT / "pontos_mucum_08jul2020.geojson").write_text(
        json.dumps(geo, ensure_ascii=False), encoding="utf-8"
    )

    (OUT / "relatorio_cruzamento.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # resumo markdown
    mu = report["cidades"]["mucum"]
    mu_only = mu.get("somente_rotulo_mucum") or {}
    st = report["cidades"]["santa_tereza"]
    iou_mu = report["iou"].get("mucum_hand_vs_mgb_n0030_thr17.02", {})
    iou_mu45 = report["iou"].get("mucum_hand_vs_mgb_n0045_thr17.02", {})
    iou_st = report["iou"].get("santa_tereza_hand_vs_mgb_n0030_thr15.00", {})
    best = report["iou"].get("mucum_melhor_limiar_hand_vs_mgb_n0030", {})
    conf = mu.get("confusao_hand_pico_vs_mgb") or {}
    md = f"""# Cruzamento Zenodo 2020 × manchas HAND (PREVINE)

Fonte: [Giordani, Fan & Alves (2021)](https://doi.org/10.5281/zenodo.4730371) — cheia de julho/2020 no Taquari-Antas (pontos de vídeos/fotos + manchas MGB).

## Leitura rápida

- Em **Muçum**, o HAND do site no pico de 08/07/2020 (**2202 cm** → HAND **{HAND_PICO_MUCUM_M:.2f} m**) cobre **{mu['cobertura_no_pico_pct']}%** dos pontos Zenodo no bbox (e **{mu_only.get('cobertura_no_pico_pct')}%** só com rótulo municipal Muçum).
- Os contornos publicados só vão até **15 m** de HAND → cobririam **{mu['cobertura_hand15_pct']}%** desses pontos; o pico de 2020 pede ~17 m.
- Sobreposição espacial HAND × MGB (n=0,030) em Muçum: IoU **{(iou_mu.get('iou') or 0):.2f}** (n=0,045: **{(iou_mu45.get('iou') or 0):.2f}**). Concordância moderada — métodos diferentes (HAND estático vs hidrodinâmica MGB).
- **Santa Tereza** não tem pontos demarcados nesse Zenodo; só dá para comparar com o raster MGB (IoU@15 m ≈ **{(iou_st.get('iou') or 0):.2f}**).

## Muçum (detalhe)

- Pontos no bbox HAND: **{mu['n_pontos_no_bbox']}** ({mu['cidades_zenodo']})
- HAND nos pontos: min={mu['hand_min_m']}, p50={mu['hand_p50_m']}, p90={mu['hand_p90_m']}, max={mu['hand_max_m']}
- Confusão HAND@pico × MGB n=0,030 nos pontos: TP={conf.get('TP')} FP={conf.get('FP')} FN={conf.get('FN')} TN={conf.get('TN')}
  - Muitos FP: HAND no pico é mais generoso que o MGB nos pontos (ou MGB subestima / pontos fora do canal principal modelado).
- Melhor limiar HAND vs MGB (grade): **{best.get('thr')} m** (IoU={best.get('iou')})

## Santa Tereza

- Pontos Zenodo no bbox: **{st['n_pontos_no_bbox']}** (dataset focado no Vale do Taquari a jusante).
- IoU HAND@15 m × MGB n=0,030: **{(iou_st.get('iou') or 0):.2f}**

## Arquivos

- `relatorio_cruzamento.json` — métricas completas
- `pontos_mucum_08jul2020.geojson` — pontos do dia 08 com HAND amostrado

Script: `codigo_python/02_mdt_hand_mancha/validar_zenodo_2020_mancha.py`
"""
    (OUT / "resumo.md").write_text(md, encoding="utf-8")
    print(md)
    print("OUT:", OUT)


if __name__ == "__main__":
    main()
