#!/usr/bin/env python3
"""Assemble the HEC/REC twin public platform (JSON feed + map page).

One place where Muçum ~5d twin results land — like the RNA live platform —
with corridor rain on a map and links to audit JSON/HTML.

Research only. Does not touch RNA. Does not invent STZ rating curve.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_pyc_module(name: str):
    """Load a scripts/__pycache__ module when the .py source is absent."""
    import importlib.util

    cache = Path(__file__).resolve().parent / "__pycache__"
    matches = sorted(cache.glob(f"{name}.cpython-*.pyc"))
    if not matches:
        raise ModuleNotFoundError(name)
    spec = importlib.util.spec_from_file_location(name, matches[-1])
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Twin runtime sources may ship as bytecode-only in this environment.
for _dep in (
    "hec_twin_nested_v17",
    "run_hec_twin_stz_mucum_calibrate",
    "hec_twin_mucum_bacia_calibracao",
    "build_hec_twin_ifs_forcing_5d",
    "run_hec_twin_mucum_forward_5d",
):
    if _dep not in sys.modules:
        try:
            __import__(_dep)
        except ModuleNotFoundError:
            _load_pyc_module(_dep)

import plataforma_hec_twin_mucum_ui as platform_ui  # noqa: E402
import run_hec_twin_mucum_forward_5d as hec_fwd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
POINTS = ROOT / "assets" / "data" / "basin_forecast_points.json"

FEED_JSON = OUT / "plataforma_hec_twin_mucum_latest.json"
FEED_HTML = OUT / "plataforma_hec_twin_mucum.html"
ROOT_HTML = ROOT / "plataforma_hec_twin.html"

PAGES_BASE = (
    "https://julianacarolinoreis.github.io/Previne-Taquari-Antas---Redes-Neurais"
)
STUDY_REL = "assets/data/estudo_bacia_taquari_antas"

SUBBASIN_LABELS = {
    "SB_PRATA_7868": "Prata / Turvo-Humatã",
    "SB_ANTAS_RESIDUAL": "Antas residual",
    "SB_CARREIRO_7866": "Carreiro",
    "SB_STZ_RESIDUAL": "Residual até Santa Tereza",
    "SB_INC_MUCUM": "Incremento até Muçum",
}

SUBBASIN_OFFSETS = {
    "SB_PRATA_7868": (0.04, -0.06),
    "SB_ANTAS_RESIDUAL": (-0.02, 0.02),
    "SB_CARREIRO_7866": (0.0, 0.0),
    "SB_STZ_RESIDUAL": (0.03, 0.03),
    "SB_INC_MUCUM": (-0.03, -0.04),
}

# Sujeito espacial da plataforma = bacia oficial G040 (7 UGs).
# Domínio do gêmeo HEC/REC (produto ΔN Muçum) = corredor aninhado até Muçum.
UG_G040 = {
    "Alto Taquari-Antas",
    "Prata",
    "Carreiro",
    "Médio Taquari-Antas",
    "Guaporé",
    "Forqueta",
    "Baixo Taquari-Antas",
}
UG_TWIN_DOMAIN = {
    "Alto Taquari-Antas",
    "Prata",
    "Carreiro",
    "Médio Taquari-Antas",
}
UG_CORRIDOR = UG_TWIN_DOMAIN  # alias legado
UG_EXCLUDED_FROM_TWIN = UG_G040 - UG_TWIN_DOMAIN


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# Corridor anchoring catalog: forçantes HEC + monitores upstream + chuvas PREVINE.
# Codes without coords in basin_forecast_points are resolved from postos/pluvio inventories.
ANCHOR_SPEC: list[tuple[str, str, str]] = [
    # Alvo + controles de nível no corredor
    ("86510000", "target", "Muçum (alvo N)"),
    ("86509000", "level_control", "Rio Taquari em Muçum (controle)"),
    ("86472600", "level_control", "Santa Tereza (sem curva N↔Q)"),
    ("86472000", "level_control", "Antas / Linha José Júlio"),
    ("86507000", "level_control", "Carreiro / Cotiporã"),
    ("86125500", "level_control", "Prata / Jararaca"),
    ("86448000", "level_control", "Monte Claro barramento"),
    # Seeds PREVINE que faltavam no mapa + monitores de tronco
    ("86306000", "upstream_monitor", "UHE Castro Alves alça"),
    ("86298000", "upstream_monitor", "UHE Castro Alves RS-122"),
    ("86430900", "upstream_monitor", "PCH da Ilha barramento"),
    ("86447000", "upstream_monitor", "UHE Monte Claro balsa do Prata"),
    ("86470800", "upstream_monitor", "UHE 14 de Julho barramento"),
    ("86471000", "upstream_monitor", "UHE 14 de Julho jusante"),
    ("86329000", "upstream_monitor", "Rio das Antas / Nova Roma"),
    ("86480000", "upstream_monitor", "Passo Migliavaca / Carreiro"),
    ("86500000", "upstream_monitor", "Passo Carreiro"),
    ("86488000", "upstream_monitor", "PCH Caçador montante"),
    ("86490500", "upstream_monitor", "PCH Boa Fé montante"),
    ("86497000", "upstream_monitor", "PCH São Paulo jusante"),
    ("86505500", "upstream_monitor", "PCH Linha Emília jusante"),
    ("86125130", "upstream_monitor", "PCH Morro Grande jusante 2"),
    # Chuvas PREVINE + densificação INMET/CEMADEN no corredor
    ("2851072", "rain", "Ibiraiaras (chuva Carreiro–Prata)"),
    ("2851044", "rain", "Chuva Carreiro (código 2851044)"),
    ("A894", "rain", "Serafina INMET A894"),
    ("432040401A", "rain", "Serafina CEMADEN Centro"),
    ("B859", "rain", "Muçum INMET B859"),
    ("A840", "rain", "Bento Gonçalves INMET A840"),
    ("A880", "rain", "Vacaria INMET A880"),
    ("B817", "rain", "Caxias Criúva INMET B817"),
    ("B818", "rain", "Caxias Aeroporto INMET B818"),
    ("B858", "rain", "Casca INMET B858"),
]

ROLE_LABEL_PT = {
    "target": "alvo",
    "level_control": "nível / controle",
    "rain": "chuva",
    "upstream_monitor": "monitor montante",
}


def station_index() -> dict[str, dict[str, Any]]:
    """Merge basin IFS points + postos ANA + pluviometria for anchor coords."""
    out: dict[str, dict[str, Any]] = {}

    raw = load_json(POINTS) or {}
    for row in raw.get("points") or []:
        code = str(row.get("station_code") or "")
        if not code:
            continue
        out[code] = {
            "station_code": code,
            "name": row.get("name"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "role": row.get("role"),
            "source": "basin_forecast_points",
        }

    def _ingest_station(st: dict[str, Any], source: str) -> None:
        code = str(st.get("codigo") or st.get("code") or st.get("station_code") or "")
        if not code or code in out:
            return
        lat = st.get("lat") if st.get("lat") is not None else st.get("latitude")
        lon = st.get("lon") if st.get("lon") is not None else st.get("longitude")
        if lat is None or lon is None:
            return
        out[code] = {
            "station_code": code,
            "name": st.get("nome") or st.get("name"),
            "latitude": float(lat),
            "longitude": float(lon),
            "role": "inventory",
            "source": source,
        }

    postos = load_json(OUT / "postos_por_upg_latest.json") or {}
    by_upg = postos.get("by_upg")
    if isinstance(by_upg, dict):
        for rows in by_upg.values():
            if isinstance(rows, list):
                for st in rows:
                    if isinstance(st, dict):
                        _ingest_station(st, "postos_por_upg")
            elif isinstance(rows, dict):
                for st in rows.get("stations") or []:
                    if isinstance(st, dict):
                        _ingest_station(st, "postos_por_upg")
    for st in postos.get("stations_inside_g040") or []:
        if isinstance(st, dict):
            _ingest_station(st, "postos_g040")

    pluv = load_json(OUT / "pluviometria_g040_latest.json") or {}
    for st in pluv.get("stations") or []:
        code = str(st.get("codigo") or st.get("code") or "")
        if not code or code in out:
            continue
        lat = st.get("lat")
        lon = st.get("lon")
        if lat is None or lon is None:
            continue
        out[code] = {
            "station_code": code,
            "name": st.get("nome") or st.get("name"),
            "latitude": float(lat),
            "longitude": float(lon),
            "role": "rain_inventory",
            "source": "pluviometria_g040",
        }
    return out


def build_anchors(stations: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for code, role, label in ANCHOR_SPEC:
        st = stations.get(code) or {}
        lat = st.get("latitude")
        lon = st.get("longitude")
        if lat is None or lon is None:
            continue
        anchors.append(
            {
                "code": code,
                "role": role,
                "role_pt": ROLE_LABEL_PT.get(role, role),
                "label": label,
                "name": st.get("name") or label,
                "lat": float(lat),
                "lon": float(lon),
                "coord_source": st.get("source"),
            }
        )
    return anchors


def compact_primary(primary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(primary, dict):
        return None
    return {
        "event_id": primary.get("event_id"),
        "rise_cm": primary.get("rise_cm"),
        "peak_anchored_cm": primary.get("peak_anchored_cm"),
        "peak_time_utc": primary.get("peak_time_utc"),
        "peak_time_argmax_utc": primary.get("peak_time_argmax_utc"),
        "peak_time_method": primary.get("peak_time_method"),
    }


def series_sample(
    fwd: dict[str, Any] | None, step_hours: int = 6
) -> list[dict[str, Any]]:
    series = (fwd or {}).get("series_primary") or {}
    times = list(series.get("time_utc") or [])
    if not times:
        return []
    n_anch = list(series.get("n_mucum_anchored_cm") or [])
    d_n = list(series.get("delta_n_from_now_cm") or [])
    q = list(series.get("q_mucum_m3s") or [])
    rows: list[dict[str, Any]] = []
    for i, ts in enumerate(times):
        if i % step_hours != 0 and i != len(times) - 1:
            continue
        rows.append(
            {
                "time_utc": ts,
                "n_anchored_cm": n_anch[i] if i < len(n_anch) else None,
                "delta_n_cm": d_n[i] if i < len(d_n) else None,
                "q_mucum_m3s": q[i] if i < len(q) else None,
            }
        )
    return rows


def build_basin_network() -> dict[str, Any]:
    """Dense G040 station layer (flu + rain) beyond curated twin anchors."""
    features: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(
        code: str,
        name: str | None,
        lat: Any,
        lon: Any,
        kind: str,
        ug: str | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not code or code in seen or lat is None or lon is None:
            return
        if ug not in UG_G040:
            return
        seen.add(code)
        in_twin = ug in UG_TWIN_DOMAIN
        props = {
            "code": code,
            "name": name or code,
            "kind": kind,
            "ug": ug,
            "in_twin_domain": in_twin,
        }
        if extra:
            props.update(extra)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(lon), float(lat)],
                },
                "properties": props,
            }
        )

    postos = load_json(OUT / "postos_por_upg_latest.json") or {}
    by_upg = postos.get("by_upg") or {}
    for ug, rows in by_upg.items():
        lst = rows if isinstance(rows, list) else (rows or {}).get("stations") or []
        for st in lst:
            if not isinstance(st, dict):
                continue
            _add(
                str(st.get("codigo") or ""),
                st.get("nome"),
                st.get("lat"),
                st.get("lon"),
                "flu",
                str(st.get("upg") or ug),
                {
                    "previne_seed": bool(st.get("in_previne_seed")),
                    "area_km2": st.get("area_drenagem_km2"),
                },
            )

    pluv = load_json(OUT / "pluviometria_g040_latest.json") or {}
    for st in pluv.get("stations") or []:
        if not isinstance(st, dict):
            continue
        _add(
            str(st.get("codigo") or ""),
            st.get("nome"),
            st.get("lat"),
            st.get("lon"),
            "rain",
            str(st.get("upg") or ""),
            {
                "network": st.get("rede"),
                "previne_rain": bool(st.get("in_previne_rain")),
            },
        )

    n_flu = sum(1 for f in features if f["properties"]["kind"] == "flu")
    n_rain = sum(1 for f in features if f["properties"]["kind"] == "rain")
    n_twin = sum(1 for f in features if f["properties"].get("in_twin_domain"))
    return {
        "type": "FeatureCollection",
        "features": features,
        "counts": {
            "flu": n_flu,
            "rain": n_rain,
            "total": len(features),
            "in_twin_domain": n_twin,
            "outside_twin_domain": len(features) - n_twin,
        },
        "note_pt": (
            "Rede da bacia Taquari–Antas (G040, 7 UGs): inventário ANA/INMET/CEMADEN. "
            "Inclui Guaporé, Forqueta e Baixo. Âncoras curadas = produto gêmeo Muçum; "
            "esta camada mostra a bacia inteira."
        ),
    }


def ug_area_km2_lookup() -> dict[str, float]:
    """Official UG areas from ugs_g040.geojson (approx km²)."""
    path = OUT / "ugs_g040.geojson"
    raw = load_json(path) or {}
    out: dict[str, float] = {}
    for feat in raw.get("features") or []:
        props = feat.get("properties") or {}
        name = props.get("sub_bacia") or props.get("nome")
        area = props.get("area_km2_approx")
        if name and area is not None:
            out[str(name)] = float(area)
    return out


def g040_bbox_latlon() -> list[list[float]]:
    """Leaflet-friendly [[south, west], [north, east]] from UG polygons."""
    path = OUT / "ugs_g040.geojson"
    raw = load_json(path) or {}
    lats: list[float] = []
    lons: list[float] = []

    def _walk(coords: Any) -> None:
        if not isinstance(coords, (list, tuple)) or not coords:
            return
        if isinstance(coords[0], (int, float)) and len(coords) >= 2:
            lons.append(float(coords[0]))
            lats.append(float(coords[1]))
            return
        for item in coords:
            _walk(item)

    for feat in raw.get("features") or []:
        geom = feat.get("geometry") or {}
        _walk(geom.get("coordinates"))
    if not lats or not lons:
        return [[-29.95, -52.64], [-28.18, -49.93]]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def build_inventory_stats(network: dict[str, Any]) -> dict[str, Any]:
    """Per-UG station inventory for the full G040 basin (no HEC invented)."""
    areas = ug_area_km2_lookup()
    by_ug: dict[str, dict[str, Any]] = {
        ug: {
            "flu": 0,
            "rain": 0,
            "total": 0,
            "area_km2_approx": areas.get(ug),
            "in_twin_domain": ug in UG_TWIN_DOMAIN,
            "hec_forcing": ug in UG_TWIN_DOMAIN,
        }
        for ug in sorted(UG_G040)
    }
    for feat in network.get("features") or []:
        props = feat.get("properties") or {}
        ug = props.get("ug")
        if ug not in by_ug:
            continue
        kind = props.get("kind")
        if kind == "flu":
            by_ug[ug]["flu"] += 1
        elif kind == "rain":
            by_ug[ug]["rain"] += 1
        by_ug[ug]["total"] += 1
    counts = network.get("counts") or {}
    return {
        "by_ug": by_ug,
        "totals": {
            "flu": counts.get("flu"),
            "rain": counts.get("rain"),
            "total": counts.get("total"),
            "in_twin_domain": counts.get("in_twin_domain"),
            "outside_twin_domain": counts.get("outside_twin_domain"),
            "ugs": len(UG_G040),
            "ugs_twin": len(UG_TWIN_DOMAIN),
            "ugs_inventory_only": len(UG_EXCLUDED_FROM_TWIN),
        },
        "sources": [
            "postos_por_upg_latest.json",
            "pluviometria_g040_latest.json",
            "ugs_g040.geojson",
        ],
        "honesty_pt": (
            "Inventário da bacia G040. Guaporé/Forqueta/Baixo entram nas contagens; "
            "não há forçante HEC/ΔN inventada para essas UGs."
        ),
    }


def build_corridor_network() -> dict[str, Any]:
    """Back-compat alias — rede espacial agora é a bacia G040 completa."""
    return build_basin_network()


def compact_hindcast_events(hind: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-event LOO errors for platform skill panel."""
    rows: list[dict[str, Any]] = []
    for ev in (hind or {}).get("events") or []:
        if not isinstance(ev, dict) or ev.get("status") != "scored":
            continue
        abs_err = ev.get("rise_n_abs_err_cm")
        rel_err = ev.get("rise_n_rel_err")
        peak_err = ev.get("peak_q_rel_err")
        nse = ev.get("nse_loo")
        rain = ev.get("rain_mm_aw")
        tag = "ok"
        if rel_err is not None and abs(float(rel_err)) >= 0.8:
            tag = "worst_rel_dn"
        elif peak_err is not None and abs(float(peak_err)) >= 0.5:
            tag = "worst_peak_q"
        elif nse is not None and float(nse) < 0:
            tag = "negative_nse"
        elif rel_err is not None and abs(float(rel_err)) <= 0.12:
            tag = "best_rel_dn"
        self_fit = ev.get("self_fit_nse")
        rows.append(
            {
                "event_id": ev.get("event_id"),
                "rain_mm_aw": rain,
                "nse_loo": nse,
                "self_fit_nse": self_fit,
                "peak_q_rel_err": peak_err,
                "rise_n_abs_err_cm": abs_err,
                "rise_n_rel_err": rel_err,
                "obs_rise_n_cm": ev.get("obs_rise_n_cm"),
                "sim_rise_n_cm": ev.get("sim_rise_n_cm"),
                "analog_event_id": ev.get("analog_event_id"),
                "analog_members": (ev.get("analog_members") or [])[:5],
                "wet": bool(((ev.get("wetness") or {}).get("is_wet"))),
                "tag": tag,
            }
        )
    rows.sort(key=lambda r: abs(float(r.get("rise_n_rel_err") or 99)))
    return rows


def build_methodology(
    eventwise: dict[str, Any] | None,
    hind: dict[str, Any] | None,
    force_live: dict[str, Any] | None,
) -> dict[str, Any]:
    """Honest method card: which HEC/REC arm, events, LOO vs self-fit."""
    eng = (eventwise or {}).get("engine") or {}
    lib = (eventwise or {}).get("params_library_eventwise") or []
    self_fit_nses = [
        float(x["nse"]) for x in lib if isinstance(x, dict) and x.get("nse") is not None
    ]
    mean_self = sum(self_fit_nses) / len(self_fit_nses) if self_fit_nses else None
    hind_sum = (hind or {}).get("summary") or {}
    mean_loo = hind_sum.get("mean_nse_loo")
    point_map: list[dict[str, Any]] = []
    meta = (force_live or {}).get("subbasin_meta") or {}
    if isinstance(meta, dict):
        for sb_id, row in meta.items():
            if not isinstance(row, dict):
                continue
            point_map.append(
                {
                    "subbasin_id": sb_id,
                    "point_code": row.get("point_code") or row.get("station_code"),
                    "label": SUBBASIN_LABELS.get(str(sb_id), str(sb_id)),
                }
            )
    if not point_map:
        point_map = [
            {"subbasin_id": "SB_PRATA_7868", "point_code": "86472000", "label": "Prata"},
            {
                "subbasin_id": "SB_ANTAS_RESIDUAL",
                "point_code": "86472000",
                "label": "Antas residual",
            },
            {
                "subbasin_id": "SB_CARREIRO_7866",
                "point_code": "86507000",
                "label": "Carreiro",
            },
            {
                "subbasin_id": "SB_STZ_RESIDUAL",
                "point_code": "86472600",
                "label": "Residual STZ",
            },
            {
                "subbasin_id": "SB_INC_MUCUM",
                "point_code": "86510000",
                "label": "Incremento Muçum",
            },
        ]
    marginal = [
        m.get("event_id")
        for m in ((eventwise or {}).get("marginal_events") or [])
        if isinstance(m, dict)
    ]
    failed = [
        m.get("event_id")
        for m in ((eventwise or {}).get("excluded_events") or [])
        if isinstance(m, dict)
    ]
    return {
        "family_arm_pt": "Gêmeo Python HMS-like (não binário HEC-HMS)",
        "engine_name": eng.get("name")
        or "python_hms_twin_ic_clark_recession_muskingum",
        "not_hec_hms_binary": bool(eng.get("not_hec_hms_binary", True)),
        "not_hec_ras": True,
        "not_cwms": True,
        "methods": eng.get("methods") or eng.get("methods")
        or ["Initial+Constant", "Clark", "Recession", "Muskingum"],
        "why_pt": eng.get("why")
        or (
            "HEC-HMS 4.13 do projeto é Windows-only; no Linux/Pages roda o gêmeo "
            "auditável em Python."
        ),
        "forcing_pt": (
            "ECMWF IFS 0.25° via Open-Meteo — proxy pontual por sub-bacia "
            "(não máscara areal ECMWF/REC)."
        ),
        "forcing_point_map": point_map,
        "transfer_pt": (
            "Biblioteca eventwise + transferência por análogo "
            "(fingerprint AW + wetness blend LOO)."
        ),
        "rating_pt": (
            "ΔN em Muçum via curva-chave oficial 86510000. "
            "STZ = nível observado; sem curva N↔Q inventada."
        ),
        "domain_pt": (
            "Corredor aninhado ~15.965 km² (Alto+Prata+Carreiro+Médio). "
            "G040 (~26.430 km², 7 UGs) = inventário espacial; "
            "Guaporé/Forqueta/Baixo fora do balanço."
        ),
        "events": {
            "core": list((eventwise or {}).get("included_events") or []),
            "marginal": marginal,
            "failed": failed,
            "core_rule_pt": "NSE≥0,75 no ajuste eventwise",
        },
        "skill": {
            "mean_self_fit_nse": None if mean_self is None else round(mean_self, 4),
            "mean_nse_loo": mean_loo,
            "mean_rise_n_abs_err_cm": hind_sum.get("mean_rise_n_abs_err_cm"),
            "mean_rise_n_rel_err": hind_sum.get("mean_rise_n_rel_err"),
            "n_scored_loo": hind_sum.get("n_scored") or hind_sum.get("n_scored"),
            "verdict_level": ((hind or {}).get("verdict") or {}).get("level"),
            "contrast_pt": (
                f"Self-fit médio da biblioteca ≈{mean_self:.2f} "
                f"(ajuste no próprio evento). "
                f"NSE LOO de transferência ≈{mean_loo:.2f} "
                f"(métrica honesta de previsão). "
                "Não confunda os dois."
                if mean_self is not None and mean_loo is not None
                else "Contraste self-fit vs LOO indisponível neste build."
            ),
        },
        "live_verify_pt": (
            "Verify ao vivo é n=1 — acerto pontual não valida calibração operacional."
        ),
        "not_pt": [
            "Não é HEC-HMS 4.13 binário",
            "Não é HEC-RAS / mancha",
            "Não é CWMS",
            "Não é calibração da G040 inteira",
            "Não é máscara areal ECMWF/REC",
            "Não é alerta oficial",
            "Não toca a RNA de curto prazo",
        ],
        "label_honest": (eventwise or {}).get("label_honest"),
    }


def calibration_lessons(
    events: list[dict[str, Any]], summary: dict[str, Any] | None
) -> dict[str, Any]:
    """Where LOO is right/wrong — actionable research notes."""
    if not events:
        return {
            "best_event_id": None,
            "worst_rel_event_id": None,
            "worst_peak_event_id": None,
            "lessons_pt": [],
        }
    best = min(events, key=lambda r: abs(float(r.get("rise_n_rel_err") or 99)))
    worst_rel = max(events, key=lambda r: abs(float(r.get("rise_n_rel_err") or 0)))
    worst_peak = max(events, key=lambda r: abs(float(r.get("peak_q_rel_err") or 0)))
    lessons = [
        (
            f"Melhor ΔN relativo: {best.get('event_id')} "
            f"(|err|≈{abs(float(best.get('rise_n_rel_err') or 0))*100:.0f}%, "
            f"NSE={best.get('nse_loo')}) — fingerprint+blend funcionam em eventos médios."
        ),
        (
            f"Pior ΔN relativo: {worst_rel.get('event_id')} "
            f"(|err|≈{abs(float(worst_rel.get('rise_n_rel_err') or 0))*100:.0f}%, "
            f"chuva≈{worst_rel.get('rain_mm_aw')} mm) — eventos pequenos/úmidos "
            f"superestimam a subida; revisar análogos e IC."
        ),
        (
            f"Pior pico Q: {worst_peak.get('event_id')} "
            f"(|err|≈{abs(float(worst_peak.get('peak_q_rel_err') or 0))*100:.0f}%, "
            f"chuva≈{worst_peak.get('rain_mm_aw')} mm) — extremos secos→muito chuvosos "
            f"pedem amortecimento / especialista de regime."
        ),
        (
            "Calibração continua leave-one-out na biblioteca de eventos "
            f"({(summary or {}).get('n_scored', len(events))} marcados): "
            "não reajustar RNA; só parâmetros do gêmeo Python HMS-like."
        ),
        (
            "Self-fit médio da biblioteca (~0,87) NÃO é skill de previsão: "
            "use o NSE LOO (~0,27) e o erro de ΔN como métrica honesta."
        ),
        (
            "Domínio calibrado = corredor até Muçum (~16 mil km²). "
            "G040 (~26,4 mil km²) é inventário espacial — Guaporé/Forqueta/Baixo "
            "ainda sem produto HEC."
        ),
    ]
    return {
        "best_event_id": best.get("event_id"),
        "worst_rel_event_id": worst_rel.get("event_id"),
        "worst_peak_event_id": worst_peak.get("event_id"),
        "mean_rise_n_rel_err": (summary or {}).get("mean_rise_n_rel_err"),
        "mean_peak_q_rel_err": (summary or {}).get("mean_peak_q_rel_err"),
        "lessons_pt": lessons,
    }


def build_spatial(
    force: dict[str, Any] | None,
    stations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    meta = (force or {}).get("subbasin_meta") or {}
    aw = (force or {}).get("area_weighted_mean_mm") or {}
    features: list[dict[str, Any]] = []
    for sb_id, info in meta.items():
        code = str(info.get("point_code") or "")
        st = stations.get(code) or {}
        lat = st.get("latitude")
        lon = st.get("longitude")
        if lat is None or lon is None:
            continue
        dlat, dlon = SUBBASIN_OFFSETS.get(sb_id, (0.0, 0.0))
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(lon) + dlon, float(lat) + dlat],
                },
                "properties": {
                    "subbasin_id": sb_id,
                    "label": SUBBASIN_LABELS.get(sb_id, sb_id),
                    "point_code": code,
                    "point_name": st.get("name"),
                    "total_mm": info.get("total_mm"),
                    "past_mm": info.get("past_mm"),
                    "future_mm": info.get("future_mm"),
                },
            }
        )

    anchors = build_anchors(stations)
    network = build_basin_network()
    # Primary twin controls remain the IFS sample / target set.
    primary_codes = {"86510000", "86472600", "86472000", "86507000"}
    controls = [
        {
            "code": a["code"],
            "label": a["label"],
            "name": a["name"],
            "lat": a["lat"],
            "lon": a["lon"],
            "role": a["role"],
        }
        for a in anchors
        if a["code"] in primary_codes
    ]

    return {
        "note_pt": (
            "Sujeito espacial: bacia Taquari–Antas (G040, ~26,4 mil km², 7 UGs) — "
            "Alto, Prata, Carreiro, Médio, Guaporé, Forqueta e Baixo. "
            "Produto gêmeo HEC/REC (ΔN Muçum) usa só o corredor aninhado (~16 mil km²: "
            "Alto+Prata+Carreiro+Médio); Guaporé/Forqueta/Baixo entram no mapa da bacia "
            "mas não no balanço do gêmeo até Muçum. Chuva IFS do produto = proxy pontual "
            "por sub-bacia do corredor (ainda não máscara areal ECMWF/REC). "
            f"Âncoras do produto={len(anchors)}; rede inventário G040="
            f"{(network.get('counts') or {}).get('total', 0)} pontos."
        ),
        "basin_framing": {
            "spatial_subject": "g040_full_basin",
            "g040_label_pt": "Bacia Taquari–Antas (G040)",
            "g040_km2": 26430,
            "g040_ugs": sorted(UG_G040),
            "g040_bbox_latlon": g040_bbox_latlon(),
            "twin_domain_label_pt": "Produto gêmeo · corredor até Muçum",
            "twin_domain_km2": 15965.207,
            "twin_domain_ugs": sorted(UG_TWIN_DOMAIN),
            "excluded_ugs": sorted(UG_EXCLUDED_FROM_TWIN),
            "hec_twin_not_full_basin": True,
            "not_full_basin_model": True,
            "ifs_is_point_proxy_not_areal_ecmwf_mask": True,
            "click_shows_curve_pt": (
                "Clique numa âncora do produto: Muçum mostra N+chuva; "
                "STZ só nível/controle (sem N↔Q inventada); chuva mostra hietograma proxy."
            ),
        },
        "area_weighted_total_mm": aw.get("total_mm"),
        "area_weighted_past_mm": aw.get("past_mm"),
        "area_weighted_future_mm": aw.get("future_mm"),
        "window": (force or {}).get("window"),
        "rain_geojson": {"type": "FeatureCollection", "features": features},
        "controls": controls,
        "anchors": anchors,
        "anchor_count": len(anchors),
        "basin_network": network,
        "corridor_network": network,
        "inventory_stats": build_inventory_stats(network),
        "ug_filter": sorted(UG_G040),
        "ug_basin": sorted(UG_G040),
        "ug_twin_domain": sorted(UG_TWIN_DOMAIN),
        "ug_g040": sorted(UG_G040),
        "ug_geojson": "ugs_g040.geojson",
        "fozes_geojson": "fozes_principais_bho6.geojson",
    }



SUBBASIN_TO_UG = {
    "SB_PRATA_7868": "Prata",
    "SB_ANTAS_RESIDUAL": "Médio Taquari-Antas",
    "SB_CARREIRO_7866": "Carreiro",
    "SB_STZ_RESIDUAL": "Médio Taquari-Antas",
    "SB_INC_MUCUM": "Médio Taquari-Antas",
}

LIVE_ANCHOR_CM = 425.0
LIVE_ANCHOR_UTC = "2026-09-12T02:45:00Z"


def parse_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def age_hours(ts: str | None, now: datetime | None = None) -> float | None:
    dt = parse_utc(ts)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return round((now - dt.astimezone(timezone.utc)).total_seconds() / 3600.0, 2)


def series_max_delta(series: dict[str, Any] | None) -> float:
    vals = [
        float(v)
        for v in ((series or {}).get("delta_n_from_now_cm") or [])
        if v is not None
    ]
    return max(vals) if vals else 0.0


def rebuild_live_series(force_live: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rebuild anchored hydrograph from live-eval forcing (offline)."""
    if not force_live:
        return None
    level_now = {
        "ok": True,
        "stage_cm": LIVE_ANCHOR_CM,
        "observed_at_utc": LIVE_ANCHOR_UTC,
        "source": "platform_live_trace_rebuild",
        "station": "86510000",
    }
    orig = hec_fwd.fetch_mucum_level_now
    hec_fwd.fetch_mucum_level_now = lambda *, allow_network=True: level_now
    try:
        pkg = hec_fwd.build_package(dict(force_live), allow_network=False)
    except Exception:
        return None
    finally:
        hec_fwd.fetch_mucum_level_now = orig
    series = pkg.get("series_primary")
    return series if isinstance(series, dict) and series.get("time_utc") else None


def rain_hourly(force: dict[str, Any] | None) -> list[float]:
    aw = (force or {}).get("area_weighted_mean_mm") or {}
    return list(aw.get("hourly") or [])


def ug_rain_mm(force: dict[str, Any] | None) -> dict[str, float]:
    totals = ((force or {}).get("area_weighted_mean_mm") or {}).get(
        "totals_by_subbasin_mm"
    ) or {}
    bucket: dict[str, list[float]] = {}
    for sb_id, mm in totals.items():
        ug = SUBBASIN_TO_UG.get(str(sb_id))
        if not ug or mm is None:
            continue
        bucket.setdefault(ug, []).append(float(mm))
    return {ug: round(sum(vals) / len(vals), 2) for ug, vals in bucket.items() if vals}


def build_event_trace(
    *,
    live_series: dict[str, Any] | None,
    fwd_series: dict[str, Any] | None,
    force_live: dict[str, Any] | None,
    force_fwd: dict[str, Any] | None,
    prefer_live: bool,
) -> dict[str, Any]:
    live_delta = series_max_delta(live_series)
    fwd_delta = series_max_delta(fwd_series)
    use_live = prefer_live and live_series is not None and live_delta >= 5.0
    if use_live:
        series, force, source = live_series, force_live, "live_eval_rebuild"
        note = "Traço reconstruído da forçante live-eval (mesmo ΔN do headline)."
    elif fwd_series is not None and fwd_delta >= 5.0:
        series, force, source = fwd_series, force_fwd, "forward_5d"
        note = "Traço do forward operacional ~5d."
    elif live_series is not None:
        series, force, source = live_series, force_live, "live_eval_rebuild"
        note = "Forward seco/stale — traço do live-eval."
    else:
        series, force, source = fwd_series, force_fwd, "forward_5d"
        note = "Sem série live; amostra do forward."

    times = list((series or {}).get("time_utc") or [])
    n_anch = list((series or {}).get("n_mucum_anchored_cm") or [])
    rain = rain_hourly(force)
    step = 3
    pts: list[dict[str, Any]] = []
    rain_s: list[float] = []
    for i, ts in enumerate(times):
        if i % step != 0 and i != len(times) - 1:
            continue
        pts.append({"t": ts, "n_cm": n_anch[i] if i < len(n_anch) else None})
        if i < len(rain):
            rain_s.append(round(sum(rain[i : i + step]), 2))
        else:
            rain_s.append(0.0)
    return {
        "source": source,
        "note": note,
        "series": pts,
        "rain_mm": rain_s,
        "n_points": len(pts),
    }



def enrich_feed(feed: dict[str, Any]) -> dict[str, Any]:
    """Attach freshness, event trace, product cards and UI helpers."""
    fwd = load_json(OUT / "hec_twin_mucum_forward_5d_latest.json")
    live = load_json(OUT / "hec_twin_mucum_live_eval_latest.json")
    force_live = load_json(OUT / "hec_twin_ifs_forcing_live_eval_latest.json")
    force_fwd = load_json(OUT / "hec_twin_ifs_forcing_5d_latest.json")

    live_series = rebuild_live_series(force_live)
    fwd_series = (fwd or {}).get("series_primary")
    prefer_live = (feed.get("headline") or {}).get("source") == "live_eval"
    fwd_delta = series_max_delta(fwd_series)
    stale_forward = fwd_delta < 5.0

    live_age = age_hours((live or {}).get("generated_at_utc"))
    fwd_age = age_hours((fwd or {}).get("generated_at_utc"))

    primary = (feed.get("headline") or {}).get("primary") or {}
    score = (feed.get("headline") or {}).get("scorecard") or {}
    live_obs = ((live or {}).get("observations") or {}).get("level_now") or {}
    n_anchor = live_obs.get("stage_cm")
    if n_anchor is None:
        n_anchor = LIVE_ANCHOR_CM

    products = dict(feed.get("products") or {})
    live_p = dict(products.get("live_eval") or {})
    fwd_p = dict(products.get("forward_5d") or {})
    live_primary = live_p.get("primary") or {}
    fwd_primary = fwd_p.get("primary") or {}

    live_p.update(
        {
            "available": bool(live_primary.get("rise_cm") is not None),
            "artifact": ((feed.get("where_results_go") or {}).get("local") or {}).get(
                "live_eval_html"
            ),
            "age_hours": live_age,
            "timing_error_h": score.get("timing_error_h"),
            "note": "Replay do evento com âncora + verificação ANA.",
            "peak_delta_n_cm": live_primary.get("rise_cm"),
            "peak_n_cm": live_primary.get("peak_anchored_cm"),
            "peak_when_utc": live_primary.get("peak_time_utc"),
        }
    )
    fwd_p.update(
        {
            "available": fwd is not None,
            "artifact": ((feed.get("where_results_go") or {}).get("local") or {}).get(
                "forward_html"
            ),
            "age_hours": fwd_age,
            "stale": stale_forward,
            "note": (
                "Forward seco/stale — preferir live para o evento."
                if stale_forward
                else "Produto operacional de pesquisa (~5d)."
            ),
            "peak_delta_n_cm": fwd_primary.get("rise_cm"),
            "peak_n_cm": fwd_primary.get("peak_anchored_cm"),
            "peak_when_utc": fwd_primary.get("peak_time_utc"),
        }
    )
    local_paths = ((feed.get("where_results_go") or {}).get("local") or {})
    live_p["artifact"] = local_paths.get("live_eval_html")
    fwd_p["artifact"] = local_paths.get("forward_html")
    products["live_eval"] = live_p
    products["forward_5d"] = fwd_p

    spatial = dict(feed.get("spatial") or {})
    ug_rain = ug_rain_mm(force_live if prefer_live else (force_fwd or force_live))
    anchors = []
    for a in spatial.get("anchors") or []:
        row = dict(a)
        row["id"] = row.get("code")
        # Attach corridor rain to rain/target anchors when UG known via label heuristics.
        label = str(row.get("label") or row.get("name") or "")
        ug = None
        if "Muçum" in label or "Mucum" in label:
            ug = "Médio Taquari-Antas"
        elif "Carreiro" in label or "Cotiporã" in label or "Migliavaca" in label:
            ug = "Carreiro"
        elif "Prata" in label or "Jararaca" in label or "Ilha" in label:
            ug = "Prata"
        elif (
            "Antas" in label
            or "Santa Tereza" in label
            or "Monte Claro" in label
            or "Castro Alves" in label
            or "14 de Julho" in label
            or "Bento" in label
            or "Vacaria" in label
            or "Caxias" in label
        ):
            ug = "Médio Taquari-Antas"
        elif "Ibiraiaras" in label or "Serafina" in label or "Casca" in label:
            ug = "Carreiro"
        row["ug"] = ug
        row["rain_mm_window"] = ug_rain.get(ug) if ug else None
        anchors.append(row)
    spatial["anchors"] = anchors
    spatial["anchor_count"] = len(anchors)
    spatial["ug_rain_mm"] = ug_rain
    # Prefer existing key names used by current feed.
    if "ug_geojson" in spatial and "ug_geojson" not in spatial:
        pass
    spatial.setdefault("ug_geojson", spatial.get("ug_geojson") or "ugs_g040.geojson")

    auto = dict(feed.get("automation") or {})
    auto.setdefault("workflow_name", "HEC twin Muçum forward ~5d")
    auto.setdefault("schedule_cron", auto.get("schedule_cron") or auto.get("schedule_cron"))
    auto.setdefault("commit_author", "previne-hec-bot")
    auto.setdefault("pipeline", auto.get("steps_pt") or [])
    auto.setdefault("steps_pt", auto.get("steps_pt") or [])

    feed["schema_version"] = "plataforma_hec_twin_mucum_v2"
    feed["product"] = {
        "name": "Produto gêmeo · ΔN Muçum ~5d",
        "horizon": "~5 dias",
        "target": "Muçum (exutório N do produto)",
        "mode": "pesquisa · REC bacia",
        "domain_pt": "Prata + Antas residual + Carreiro + residual STZ + incremento Muçum",
        "nested_inside_pt": "Dentro da bacia G040 · não é a bacia inteira",
    }
    feed["summary"] = {
        "peak_n_cm": primary.get("peak_anchored_cm"),
        "peak_delta_n_cm": primary.get("rise_cm"),
        "peak_when_utc": primary.get("peak_time_utc"),
        "timing_error_h": score.get("timing_error_h"),
        "n_anchor_cm": n_anchor,
        "source": (feed.get("headline") or {}).get("source"),
    }
    feed["freshness"] = {
        "preferred_source": "live_eval" if prefer_live else "forward",
        "live_age_hours": live_age,
        "forward_age_hours": fwd_age,
        "stale_forward": stale_forward,
        "forward_max_delta_n_cm": round(fwd_delta, 2),
        "note_pt": (
            "Quando o forward está seco/stale, headline e hidrograma preferem o live eval."
            if stale_forward
            else "Forward e live disponíveis."
        ),
    }
    feed["products"] = products
    feed["spatial"] = spatial
    feed["event_trace"] = build_event_trace(
        live_series=live_series,
        fwd_series=fwd_series,
        force_live=force_live,
        force_fwd=force_fwd,
        prefer_live=prefer_live,
    )
    feed["automation"] = auto
    return feed


def build_feed() -> dict[str, Any]:
    fwd = load_json(OUT / "hec_twin_mucum_forward_5d_latest.json")
    live = load_json(OUT / "hec_twin_mucum_live_eval_latest.json")
    verify = load_json(OUT / "hec_twin_mucum_live_eval_verify_latest.json")
    hind = load_json(OUT / "hec_twin_mucum_hindcast_skill_5d_latest.json")
    force_live = load_json(OUT / "hec_twin_ifs_forcing_live_eval_latest.json")
    force_fwd = load_json(OUT / "hec_twin_ifs_forcing_5d_latest.json")
    eventwise = load_json(OUT / "modelo_mucum_eventwise_v1_fechado_latest.json")
    multi = load_json(OUT / "modelo_g040_multi_exutorio_v1_latest.json")
    stations = station_index()
    methodology = build_methodology(eventwise, hind, force_live)

    qs = (fwd or {}).get("quanto_sobe") or {}
    live_ans = (live or {}).get("answer_from_anchor") or {}
    live_ver = (live or {}).get("verification") or {}
    score = (verify or {}).get("scorecard") or {}

    live_primary = compact_primary(live_ans.get("primary"))
    use_live = live_primary is not None and live_primary.get("rise_cm") is not None

    if use_live:
        headline_source = "live_eval"
        headline_primary = live_primary
        headline_ensemble = live_ans.get("ensemble_rise_cm")
        headline_plain = live_ans.get("plain_pt") or (live or {}).get("plain_pt")
        rain_ifs = (live or {}).get("rain_ifs") or {}
        rain_total = rain_ifs.get("window_total_mm")
        if rain_total is None:
            rain_total = (rain_ifs.get("past_48h_mm") or 0) + (
                rain_ifs.get("next_72h_mm") or 0
            )
    else:
        headline_source = "forward"
        headline_primary = compact_primary(qs.get("primary"))
        headline_ensemble = qs.get("ensemble_rise_cm")
        headline_plain = qs.get("plain_pt")
        rain_total = qs.get("rain_forecast_mm_area_weighted")

    pages = {
        "platform_html": f"{PAGES_BASE}/{STUDY_REL}/plataforma_hec_twin_mucum.html",
        "platform_root": f"{PAGES_BASE}/plataforma_hec_twin.html",
        "platform_json": f"{PAGES_BASE}/{STUDY_REL}/plataforma_hec_twin_mucum_latest.json",
        "forward_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_forward_5d.html",
        "live_eval_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_live_eval.html",
        "verify_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_live_eval_verify.html",
        "hindcast_html": f"{PAGES_BASE}/{STUDY_REL}/hec_twin_mucum_hindcast_skill_5d.html",
        "mapa_subbacias": f"{PAGES_BASE}/{STUDY_REL}/mapa_subbacias.html",
        "rna_mucum_live": f"{PAGES_BASE}/mucum_previsao_inundacao.html",
    }

    local = {
        "platform_html": "plataforma_hec_twin_mucum.html",
        "platform_json": "plataforma_hec_twin_mucum_latest.json",
        "forward_html": "hec_twin_mucum_forward_5d.html",
        "forward_json": "hec_twin_mucum_forward_5d_latest.json",
        "live_eval_html": "hec_twin_mucum_live_eval.html",
        "live_eval_json": "hec_twin_mucum_live_eval_latest.json",
        "verify_html": "hec_twin_mucum_live_eval_verify.html",
        "verify_json": "hec_twin_mucum_live_eval_verify_latest.json",
        "hindcast_html": "hec_twin_mucum_hindcast_skill_5d.html",
        "hindcast_json": "hec_twin_mucum_hindcast_skill_5d_latest.json",
        "forcing_live_json": "hec_twin_ifs_forcing_live_eval_latest.json",
        "forcing_forward_json": "hec_twin_ifs_forcing_5d_latest.json",
        "mapa_subbacias": "mapa_subbacias.html",
        "multi_outlet_json": "modelo_g040_multi_exutorio_v1_latest.json",
        "multi_outlet_html": "modelo_g040_multi_exutorio_v1.html",
    }

    return {
        "schema_version": "plataforma_hec_twin_mucum_v1",
        "generated_at_utc": utc_now(),
        "status": "research_platform_ready",
        "label_pt": "Plataforma HEC/REC · bacia Taquari–Antas (G040)",
        "purpose_pt": (
            "Mapa e inventário da bacia oficial Taquari–Antas (G040, ~26,4 mil km², "
            "7 UGs). Produtos hidrológicos multi-exutório: (1) corredor Muçum ~16 mil km²; "
            "(2) Encantado após foz Guaporé ~19 mil km² (Muçum roteado + residual Guaporé). "
            "Foz Guaporé isolada, Forqueta e Baixo ainda gated sem Q oficial. "
            "Não é HEC-HMS binário / RAS / CWMS. STZ sem curva N↔Q inventada. Pesquisa."
        ),
        "methodology": methodology,
        "basin": {
            "label_pt": "Bacia Taquari–Antas (G040)",
            "area_km2": 26430,
            "ugs": sorted(UG_G040),
            "spatial_subject": True,
        },
        "corridor": {
            "label_pt": "Produto gêmeo · corredor até Muçum",
            "calibration_method": (
                (live or {}).get("param_selection") or {}
            ).get("method")
            or ((fwd or {}).get("param_selection") or {}).get("method")
            or "analog_basin_calibrated_aw_fingerprint_wetness_blend_v4",
            "calibration_artifact": "modelo_mucum_bacia_calibrado_v1_latest.json",
            "nested_area_km2": 15965.207,
            "outlet_pt": "Muçum (ΔN via curva-chave oficial)",
            "level_control_pt": "Santa Tereza (nível observado; Q diagnóstico sem curva)",
            "subbasins": [
                {
                    "id": "SB_PRATA_7868",
                    "label": "Prata / Turvo-Humatã",
                    "role": "montante",
                },
                {
                    "id": "SB_ANTAS_RESIDUAL",
                    "label": "Antas residual",
                    "role": "tronco",
                },
                {
                    "id": "SB_CARREIRO_7866",
                    "label": "Carreiro",
                    "role": "afluente",
                },
                {
                    "id": "SB_STZ_RESIDUAL",
                    "label": "Residual até Santa Tereza",
                    "role": "controle",
                },
                {
                    "id": "SB_INC_MUCUM",
                    "label": "Incremento STZ→Muçum",
                    "role": "trecho_final",
                },
            ],
            "excluded_pt": ["Guaporé", "Forqueta", "Baixo Taquari-Antas"],
            "not_full_g040": True,
            "not_only_stz_mucum_shortcut": True,
            "is_product_inside_basin": True,
        },
        "discipline": {
            "research_not_alert": True,
            "does_not_touch_rna": True,
            "no_invented_stz_rating_curve": True,
            "ifs_point_proxy_not_areal_mask": True,
            "corridor_not_full_g040": True,
            "basin_calibrated_analogs": True,
            "not_stz_mucum_only_shortcut": True,
            "not_hec_hms_binary": True,
            "not_full_g040_calibrated": True,
            "corridor_analog_transfer": True,
            "ifs_point_proxy": True,
            "multi_outlet_encantado_calibrated": True,
            "guapore_mouth_q_blocked": True,
            "forqueta_mouth_q_blocked": True,
        },
        "where_results_go": {
            "pages_base": PAGES_BASE,
            "study_dir": STUDY_REL,
            "pages": pages,
            "local": local,
            "pipeline_pt": [
                "IFS QPF → forçante por sub-bacia (JSON)",
                "Gêmeo Python HMS-like (IC+Clark+Muskingum) → Q Muçum → curva-chave → ΔN",
                "Feed estável plataforma_hec_twin_mucum_latest.json",
                "Página mapa plataforma_hec_twin_mucum.html (+ atalho raiz)",
                "Deploy Pages quando paths do estudo / plataforma mudam",
            ],
        },
        "headline": {
            "source": headline_source,
            "question_pt": (
                "Com a chuva do corredor (Prata–Carreiro–Antas→STZ→Muçum) e transferência "
                "por análogos LOO, quanto sobe o nível em Muçum?"
            ),
            "plain_pt": headline_plain,
            "primary": headline_primary,
            "ensemble_rise_cm": headline_ensemble,
            "rain_mm_area_weighted": rain_total,
            "verification_plain_pt": live_ver.get("plain_pt") or score.get("plain_pt"),
            "scorecard": {
                "verdict_level": score.get("verdict_level")
                or live_ver.get("verdict_level"),
                "peak_error_cm": score.get("peak_error_cm")
                or live_ver.get("peak_error_cm"),
                "timing_error_h": score.get("timing_error_h")
                or live_ver.get("timing_error_h"),
                "obs_peak_cm": score.get("obs_peak_cm") or live_ver.get("obs_peak_cm"),
                "predicted_peak_anchored_cm": (
                    ((verify or {}).get("forecast_ref") or {}).get(
                        "predicted_peak_anchored_cm"
                    )
                    or (headline_primary or {}).get("peak_anchored_cm")
                ),
            },
        },
        "products": {
            "forward_5d": {
                "status": (fwd or {}).get("status"),
                "generated_at_utc": (fwd or {}).get("generated_at_utc"),
                "plain_pt": qs.get("plain_pt"),
                "primary": compact_primary(qs.get("primary")),
                "ensemble_rise_cm": qs.get("ensemble_rise_cm"),
                "rain_forecast_mm": qs.get("rain_forecast_mm_area_weighted"),
                "level_now": qs.get("level_now"),
                "note_pt": (
                    "Produto operacional de pesquisa (~5d). Se a forçante estiver seca "
                    "ou a telemetria cair, o ΔN pode ir a zero — conferir live eval."
                ),
            },
            "live_eval": {
                "status": (live or {}).get("status"),
                "generated_at_utc": (live or {}).get("generated_at_utc"),
                "plain_pt": live_ans.get("plain_pt") or (live or {}).get("plain_pt"),
                "primary": compact_primary(live_ans.get("primary")),
                "ensemble_rise_cm": live_ans.get("ensemble_rise_cm"),
                "observations": (live or {}).get("observations"),
                "verification": live_ver,
            },
            "verify": {
                "status": (verify or {}).get("status"),
                "generated_at_utc": (verify or {}).get("generated_at_utc"),
                "plain_pt": (verify or {}).get("plain_pt"),
                "observed": (verify or {}).get("observed"),
                "scorecard": score,
            },
            "hindcast_skill": {
                "status": (hind or {}).get("status"),
                "generated_at_utc": (hind or {}).get("generated_at_utc"),
                "summary": {
                    **((hind or {}).get("summary") or {}),
                    "mean_self_fit_nse": (methodology.get("skill") or {}).get(
                        "mean_self_fit_nse"
                    ),
                    "contrast_pt": (methodology.get("skill") or {}).get("contrast_pt"),
                },
                "verdict": (hind or {}).get("verdict"),
                "events": compact_hindcast_events(hind),
                "calibration": calibration_lessons(
                    compact_hindcast_events(hind),
                    (hind or {}).get("summary"),
                ),
                "calibration_artifact": "modelo_mucum_bacia_calibrado_v1_latest.json",
                "method_pt": (
                    "Leave-one-out nos eventos da biblioteca: chuva observada como "
                    "proxy de QPF → gêmeo Python HMS-like → ΔN Muçum via curva oficial. "
                    "Self-fit ≠ skill de previsão."
                ),
            },
            "g040_multi_outlet": {
                "status": (multi or {}).get("status") or "research_multi_outlet",
                "generated_at_utc": (multi or {}).get("generated_at_utc"),
                "purpose_pt": (multi or {}).get("purpose_pt"),
                "outlets": (multi or {}).get("outlets") or [],
                "encantado": ((multi or {}).get("encantado_calibration") or {}),
                "areas_km2": (multi or {}).get("areas_km2"),
                "discipline": (multi or {}).get("discipline"),
                "blocked_next": (multi or {}).get("blocked_next") or [],
                "artifact_html": "modelo_g040_multi_exutorio_v1.html",
                "artifact_json": "modelo_g040_multi_exutorio_v1_latest.json",
            },
        },
        "spatial": build_spatial(force_live or force_fwd, stations),
        "hydrograph_sample_6h": series_sample(fwd, step_hours=6),
        "param_selection": {
            "forward": (fwd or {}).get("param_selection"),
            "live": (live or {}).get("param_selection"),
        },
        "artifacts": {
            "json": "plataforma_hec_twin_mucum_latest.json",
            "html": "plataforma_hec_twin_mucum.html",
            "root_entry": "plataforma_hec_twin.html",
        },
        "automation": {
            "robot_pt": "Robô GitHub Actions puxa IFS → gêmeo HEC → plataforma",
            "workflow": ".github/workflows/hec-twin-mucum-forward.yml",
            "schedule_cron": "12 */6 * * *",
            "schedule_pt": "a cada 6 horas (min :12) + disparo manual",
            "steps_pt": [
                "Busca chuva IFS (Open-Meteo) por sub-bacia do corredor",
                "Roda gêmeo HEC Muçum ~5d (âncora no nível ao vivo se houver)",
                "Reconstrói plataforma_hec_twin_mucum (mapa + feed)",
                "Publica no main → GitHub Pages atualiza",
            ],
            "does_not_touch_rna": True,
            "research_not_alert": True,
        },
    }


def render_html(feed: dict[str, Any]) -> str:
    return platform_ui.render_platform_html(feed)


def render_root_entry() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PREVINE · Plataforma HEC/REC</title>
<meta http-equiv="refresh" content="0; url=assets/data/estudo_bacia_taquari_antas/plataforma_hec_twin_mucum.html"/>
<link rel="canonical" href="assets/data/estudo_bacia_taquari_antas/plataforma_hec_twin_mucum.html"/>
<style>
  body { margin:0; font-family:"IBM Plex Sans", "Source Sans 3", sans-serif; background:#e8f0ea; color:#12241c;
    display:grid; place-items:center; min-height:100vh; }
  main { max-width:36rem; padding:2rem; }
  a { color:#0f5c45; font-weight:700; }
</style>
</head>
<body>
<main>
  <p><strong>PREVINE · Bacia Taquari–Antas (G040)</strong></p>
  <p>Redirecionando para o mapa da bacia e o produto gêmeo ΔN Muçum…</p>
  <p><a href="assets/data/estudo_bacia_taquari_antas/plataforma_hec_twin_mucum.html">Abrir plataforma da bacia</a>
     · <a href="mucum_previsao_inundacao.html">Plataforma RNA Muçum</a></p>
</main>
</body>
</html>
"""


def main() -> None:
    feed = enrich_feed(build_feed())
    FEED_JSON.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    FEED_HTML.write_text(render_html(feed), encoding="utf-8")
    ROOT_HTML.write_text(render_root_entry(), encoding="utf-8")
    print(f"wrote {FEED_JSON.relative_to(ROOT)}")
    print(f"wrote {FEED_HTML.relative_to(ROOT)}")
    print(f"wrote {ROOT_HTML.relative_to(ROOT)}")
    print(
        "headline",
        feed["headline"]["source"],
        feed["headline"]["primary"],
        "rain_features",
        len(feed["spatial"]["rain_geojson"]["features"]),
        "pages",
        feed["where_results_go"]["pages"]["platform_html"],
    )


if __name__ == "__main__":
    main()
