#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from esda import Moran, Moran_Local
from libpysal.weights import KNN
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SECTOR_DIR = ROOT / "assets/data/vulnerabilidade/setores"
OUT_DIR = ROOT / "artifacts/vulnerabilidade_spatial_audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CRS_ANALYSIS = "EPSG:5880"
VARIABLES = ["income", "water", "sewage", "child", "elderly", "blackbrown"]
K_MAIN = 6
K_TEST = [4, 6, 8, 12]
GLOBAL_PERMUTATIONS = 999
LOCAL_PERMUTATIONS = 9999
SEED = 20261001

def val(x):
    if x is None or x == "":
        return np.nan
    try:
        y = float(x)
        return y if math.isfinite(y) else np.nan
    except Exception:
        return np.nan

def load_sectors():
    frames = []
    for path in sorted(SECTOR_DIR.glob("*.geojson")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for feat in doc.get("features", []):
            p = feat.get("properties", {})
            if int(p.get("na_bacia") or 0) != 1:
                continue
            pop = val(p.get("pop"))
            dom = val(p.get("dom_ocupados"))
            c0, c5 = val(p.get("c0_4")), val(p.get("c5_9"))
            e1, e2 = val(p.get("i60_69")), val(p.get("i70m"))
            bb = val(p.get("pretos_pardos"))
            wa, se = val(p.get("dom_agua")), val(p.get("dom_esgoto"))
            row = {
                "setor": str(p.get("setor")),
                "cod_mun": str(p.get("setor"))[:7],
                "pop": pop,
                "n_resp": val(p.get("n_resp")),
                "renda_resp": val(p.get("renda_resp")),
                "dom_ocupados": dom,
                "dom_agua": wa,
                "dom_esgoto": se,
                "c0_4": c0, "c5_9": c5,
                "i60_69": e1, "i70m": e2,
                "pretos_pardos": bb,
                "income": val(p.get("renda_resp")),
                "water": wa / dom if math.isfinite(dom) and dom > 0 and math.isfinite(wa) else np.nan,
                "sewage": se / dom if math.isfinite(dom) and dom > 0 and math.isfinite(se) else np.nan,
                "child": (c0 + c5) / pop if math.isfinite(pop) and pop > 0 and math.isfinite(c0) and math.isfinite(c5) else np.nan,
                "elderly": (e1 + e2) / pop if math.isfinite(pop) and pop > 0 and math.isfinite(e1) and math.isfinite(e2) else np.nan,
                "blackbrown": bb / pop if math.isfinite(pop) and pop > 0 and math.isfinite(bb) else np.nan,
                "geometry": shape(feat["geometry"]),
            }
            frames.append(row)
    gdf = gpd.GeoDataFrame(frames, geometry="geometry", crs="EPSG:4326")
    return gdf.to_crs(CRS_ANALYSIS)

def load_municipality_names():
    p = ROOT / "assets/data/vulnerabilidade/downloads/municipios_combinados.csv"
    df = pd.read_csv(p, sep=";", dtype={"cod_mun": str})
    return dict(zip(df["cod_mun"], df["nome"]))

def knn_weights(gdf, k):
    c = gdf.geometry.centroid
    coords = np.column_stack([c.x.to_numpy(), c.y.to_numpy()])
    w = KNN.from_array(coords, k=k)
    w.transform = "R"
    return w

def spatial_stats(gdf, names):
    np.random.seed(SEED)
    summary = {}
    local_maps = {}
    lisa_rows = pd.DataFrame({"setor": gdf["setor"].values, "cod_mun": gdf["cod_mun"].values})
    for var in VARIABLES:
        sub = gdf[gdf[var].notna()].copy().reset_index()
        y = sub[var].to_numpy(dtype=float)
        sensitivity = {}
        for k in K_TEST:
            w = knn_weights(sub, k)
            m = Moran(y, w, permutations=GLOBAL_PERMUTATIONS)
            sensitivity[str(k)] = {"I": float(m.I), "p_sim": float(m.p_sim)}
        w = knn_weights(sub, K_MAIN)
        ml = Moran_Local(y, w, permutations=LOCAL_PERMUTATIONS, seed=SEED)
        pvals = np.asarray(ml.p_sim, dtype=float)
        sig = pvals <= 0.05
        order = np.argsort(pvals)
        ranked = pvals[order]
        bh_line = 0.05 * (np.arange(1, len(ranked) + 1) / len(ranked))
        passed = ranked <= bh_line
        sig_fdr = np.zeros(len(sub), dtype=bool)
        bh_cutoff = None
        if passed.any():
            last = np.where(passed)[0].max()
            bh_cutoff = float(ranked[last])
            sig_fdr = pvals <= bh_cutoff
        labels = np.full(len(sub), "NS", dtype=object)
        labels_fdr = np.full(len(sub), "NS", dtype=object)
        qmap = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}
        for q, label in qmap.items():
            labels[sig & (ml.q == q)] = label
            labels_fdr[sig_fdr & (ml.q == q)] = label
        sub["lisa"] = labels
        sub["lisa_fdr"] = labels_fdr
        local_maps[var] = dict(zip(sub["setor"], sub["lisa_fdr"]))
        count = sub["lisa"].value_counts().to_dict()
        count_fdr = sub["lisa_fdr"].value_counts().to_dict()
        mun = sub.groupby(["cod_mun", "lisa"], observed=True).agg(
            sectors=("setor", "count"),
            pop=("pop", "sum"),
        ).reset_index()
        top_hh = mun[mun["lisa"] == "HH"].sort_values(["sectors", "pop"], ascending=False).head(15)
        top_ll = mun[mun["lisa"] == "LL"].sort_values(["sectors", "pop"], ascending=False).head(15)
        def mun_records(frame):
            out = []
            for _, r in frame.iterrows():
                out.append({
                    "cod_mun": r["cod_mun"],
                    "municipio": names.get(r["cod_mun"], r["cod_mun"]),
                    "sectors": int(r["sectors"]),
                    "pop": float(r["pop"]) if pd.notna(r["pop"]) else None,
                })
            return out
        summary[var] = {
            "n": int(len(sub)),
            "global": sensitivity[str(K_MAIN)],
            "sensitivity": sensitivity,
            "lisa_counts": {k: int(count.get(k, 0)) for k in ["HH", "LL", "HL", "LH", "NS"]},
            "lisa_counts_fdr_bh": {k: int(count_fdr.get(k, 0)) for k in ["HH", "LL", "HL", "LH", "NS"]},
            "fdr_bh_alpha": 0.05,
            "fdr_bh_cutoff_p_sim": bh_cutoff,
            "top_HH_municipalities": mun_records(top_hh),
            "top_LL_municipalities": mun_records(top_ll),
        }
        map_df = pd.DataFrame({"setor": sub["setor"], f"lisa_{var}": sub["lisa"], f"lisa_fdr_{var}": sub["lisa_fdr"]})
        lisa_rows = lisa_rows.merge(map_df, on="setor", how="left")
    return summary, local_maps, lisa_rows

def overlay_metrics(base, flood_geom, local_maps=None):
    geom = flood_geom
    rows = []
    for _, r in base.iterrows():
        if not r.geometry.intersects(geom):
            continue
        inter = r.geometry.intersection(geom)
        if inter.is_empty or inter.area <= 0:
            continue
        frac = min(1.0, max(0.0, inter.area / r.geometry.area)) if r.geometry.area else 0.0
        rec = {"setor": r["setor"], "frac": frac, "pop_proxy": (r["pop"] * frac) if pd.notna(r["pop"]) else np.nan}
        rows.append(rec)
    ov = pd.DataFrame(rows)
    if ov.empty:
        return {"sectors_touched": 0, "population_area_weighted_proxy": 0.0}
    merged = base.drop(columns="geometry").merge(ov, on="setor", how="inner")
    def weighted_count(field):
        m = merged[field].notna()
        return float((merged.loc[m, field] * merged.loc[m, "frac"]).sum()) if m.any() else None
    def ratio_fields(num_field, den_field):
        n = weighted_count(num_field)
        d = weighted_count(den_field)
        return n / d if n is not None and d not in (None, 0) else None
    child_n = None
    if merged["c0_4"].notna().any() and merged["c5_9"].notna().any():
        valid = merged["c0_4"].notna() & merged["c5_9"].notna()
        child_n = float(((merged.loc[valid, "c0_4"] + merged.loc[valid, "c5_9"]) * merged.loc[valid, "frac"]).sum())
        child_den = float((merged.loc[valid, "pop"] * merged.loc[valid, "frac"]).sum())
    else:
        child_den = None
    valid_e = merged["i60_69"].notna() & merged["i70m"].notna()
    elderly_n = float(((merged.loc[valid_e, "i60_69"] + merged.loc[valid_e, "i70m"]) * merged.loc[valid_e, "frac"]).sum()) if valid_e.any() else None
    elderly_den = float((merged.loc[valid_e, "pop"] * merged.loc[valid_e, "frac"]).sum()) if valid_e.any() else None
    valid_bb = merged["pretos_pardos"].notna()
    bb_n = float((merged.loc[valid_bb, "pretos_pardos"] * merged.loc[valid_bb, "frac"]).sum()) if valid_bb.any() else None
    bb_den = float((merged.loc[valid_bb, "pop"] * merged.loc[valid_bb, "frac"]).sum()) if valid_bb.any() else None
    valid_inc = merged["renda_resp"].notna() & merged["n_resp"].notna() & (merged["n_resp"] > 0)
    inc_num = float((merged.loc[valid_inc, "renda_resp"] * merged.loc[valid_inc, "n_resp"] * merged.loc[valid_inc, "frac"]).sum()) if valid_inc.any() else None
    inc_den = float((merged.loc[valid_inc, "n_resp"] * merged.loc[valid_inc, "frac"]).sum()) if valid_inc.any() else None
    out = {
        "sectors_touched": int(len(merged)),
        "population_area_weighted_proxy": float(merged["pop_proxy"].fillna(0).sum()),
        "children_share_proxy": child_n / child_den if child_n is not None and child_den else None,
        "elderly_share_proxy": elderly_n / elderly_den if elderly_n is not None and elderly_den else None,
        "blackbrown_share_proxy": bb_n / bb_den if bb_n is not None and bb_den else None,
        "water_network_share_proxy": ratio_fields("dom_agua", "dom_ocupados"),
        "sewage_network_share_proxy": ratio_fields("dom_esgoto", "dom_ocupados"),
        "income_weighted_proxy": inc_num / inc_den if inc_num is not None and inc_den else None,
    }
    if local_maps:
        out["lisa_touched"] = {}
        for var, mp in local_maps.items():
            cats = merged["setor"].map(mp).fillna("NA").value_counts().to_dict()
            out["lisa_touched"][var] = {str(k): int(v) for k, v in cats.items()}
    return out

def load_geojson(path):
    return json.loads(path.read_text(encoding="utf-8"))

def santa_events(gdf, local_maps):
    path = ROOT / "assets/data/estudo_caso_territorio/santa_tereza_event_spatial.json"
    doc = load_geojson(path)
    events_by_id = {e["case_id"]: e for e in doc.get("events", [])}
    base = gdf[gdf["cod_mun"] == "4317251"].copy()
    out = []
    for feat in doc.get("event_contours", {}).get("features", []):
        p = feat.get("properties", {})
        case = p.get("case_id")
        fg = gpd.GeoSeries([shape(feat["geometry"])], crs="EPSG:4326").to_crs(CRS_ANALYSIS).iloc[0]
        event = events_by_id.get(case, {})
        out.append({
            "case_id": case,
            "event_label": p.get("event_label"),
            "gauge_peak_m": event.get("gauge_peak_m", p.get("gauge_peak_m")),
            "hand_m": p.get("contour_level_m"),
            "published_scenario": event.get("scenario"),
            "sector_overlay": overlay_metrics(base, fg, local_maps),
        })
    return out

def mucum_scenarios(gdf, local_maps):
    path = ROOT / "assets/data/estudo_caso_territorio/mancha_mucum.geojson"
    doc = load_geojson(path)
    base = gdf[gdf["cod_mun"] == "4312609"].copy()
    out = []
    for feat in doc.get("features", []):
        p = feat.get("properties", {})
        fg = gpd.GeoSeries([shape(feat["geometry"])], crs="EPSG:4326").to_crs(CRS_ANALYSIS).iloc[0]
        out.append({
            "nivel_m": p.get("nivel_m"),
            "area_ha_published": p.get("area_ha"),
            "sector_overlay": overlay_metrics(base, fg, local_maps),
            "semantics": "research scenario contour; not an event-specific observed flood boundary",
        })
    return out

def sgb_santa_tereza(gdf, local_maps):
    path = ROOT / "assets/data/vulnerabilidade/perigo/setores_risco_sgb_santa_tereza.geojson"
    if not path.exists():
        return None
    doc = load_geojson(path)
    geoms = [shape(f["geometry"]) for f in doc.get("features", []) if f.get("geometry")]
    if not geoms:
        return None
    risk = gpd.GeoSeries([unary_union(geoms)], crs="EPSG:4326").to_crs(CRS_ANALYSIS).iloc[0]
    base = gdf[gdf["cod_mun"] == "4317251"].copy()
    return {
        "risk_features": len(geoms),
        "sector_overlay": overlay_metrics(base, risk, local_maps),
        "semantics": "SGB 2025 setorizacao de risco em Santa Tereza; not a continuous basin-wide hazard layer",
    }

def export_lisa_geojson(gdf, lisa_rows, names):
    cols = ["setor", "cod_mun", "pop"] + VARIABLES + ["geometry"]
    x = gdf[cols].merge(lisa_rows, on=["setor", "cod_mun"], how="left")
    x["municipio"] = x["cod_mun"].map(names)
    x["structural_ll_count"] = (
        x["lisa_fdr_income"].eq("LL").astype(int)
        + x["lisa_fdr_water"].eq("LL").astype(int)
        + x["lisa_fdr_sewage"].eq("LL").astype(int)
    )
    x["elderly_hh_plus_structural"] = (
        x["lisa_fdr_elderly"].eq("HH") & x["structural_ll_count"].ge(1)
    ).astype(int)
    x["child_hh_plus_structural"] = (
        x["lisa_fdr_child"].eq("HH") & x["structural_ll_count"].ge(1)
    ).astype(int)
    x = x.to_crs("EPSG:4326")
    x.to_file(OUT_DIR / "lisa_setores_bacia.geojson", driver="GeoJSON")

    compact = {
        "schema_version": 1,
        "method": {
            "weights": "KNN on projected centroids",
            "main_k": K_MAIN,
            "global_permutations": GLOBAL_PERMUTATIONS,
            "local_permutations": LOCAL_PERMUTATIONS,
            "fdr": "Benjamini-Hochberg alpha=0.05",
        },
        "sectors": {},
    }
    for _, r in x.drop(columns="geometry").iterrows():
        compact["sectors"][str(r["setor"])] = {
            "municipio": r["municipio"],
            "cod_mun": str(r["cod_mun"]),
            "pop": None if pd.isna(r["pop"]) else float(r["pop"]),
            "structural_ll_count": int(r["structural_ll_count"]),
            "elderly_hh_plus_structural": int(r["elderly_hh_plus_structural"]),
            "child_hh_plus_structural": int(r["child_hh_plus_structural"]),
            **{
                f"lisa_fdr_{v}": (None if pd.isna(r[f"lisa_fdr_{v}"]) else str(r[f"lisa_fdr_{v}"]))
                for v in VARIABLES
            },
        }
    (OUT_DIR / "lisa_classificacao_setores.json").write_text(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

def main():
    names = load_municipality_names()
    gdf = load_sectors()
    spatial, local_maps, lisa_rows = spatial_stats(gdf, names)
    export_lisa_geojson(gdf, lisa_rows, names)
    result = {
        "schema_version": 1,
        "analysis": "vulnerabilidade_social_spatial_full_basin",
        "research_only": True,
        "n_sectors": int(len(gdf)),
        "crs_analysis": CRS_ANALYSIS,
        "weights": {
            "type": "k-nearest-neighbors on projected sector centroids",
            "main_k": K_MAIN,
            "sensitivity_k": K_TEST,
            "global_permutations": GLOBAL_PERMUTATIONS,
            "local_permutations": LOCAL_PERMUTATIONS,
            "local_significance": 0.05,
            "multiple_testing_adjustment": "Benjamini-Hochberg FDR alpha=0.05 is reported alongside the exploratory p_sim<=0.05 classification",
        },
        "spatial_statistics": spatial,
        "santa_tereza_historical_events": santa_events(gdf, local_maps),
        "mucum_research_scenarios": mucum_scenarios(gdf, local_maps),
        "santa_tereza_sgb_risk": sgb_santa_tereza(gdf, local_maps),
        "limits": [
            "LISA is reported both at exploratory p_sim<=0.05 and with Benjamini-Hochberg FDR alpha=0.05.",
            "KNN uses projected polygon centroids, not queen contiguity.",
            "Area-weighted population and demographic overlays are geometric proxies, not individual counts.",
            "Historical Santa Tereza contours are LiDAR/HAND reconstructions, not observed flood boundaries or 2-D hydrodynamic simulations.",
            "Muçum contours are research scenarios and are not treated as historical event boundaries.",
            "SGB risk coverage is specific to Santa Tereza and cannot be extrapolated basin-wide.",
        ],
    }
    out = OUT_DIR / "analysis_vulnerabilidade_spatial_full.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    print("RESULT_JSON=" + compact)
    print("RESULT_PATH=" + str(out.relative_to(ROOT)))
    print("LISA_PATH=" + str((OUT_DIR / "lisa_setores_bacia.geojson").relative_to(ROOT)))

if __name__ == "__main__":
    main()
