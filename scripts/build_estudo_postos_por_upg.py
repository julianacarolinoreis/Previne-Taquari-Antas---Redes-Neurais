#!/usr/bin/env python3
"""STUDY: inventory of ANA stations inside Taquari-Antas by UPG and BHO6 family.

No HEC. Assigns each station inside G040 to:
  - SEMA UPG (7 polygons)
  - BHO6 family (786 / 7868 Prata / 7866 Carreiro / 7864 Guapore / 7862 Forqueta / other 786x)

Sources: ANA HidroInventario (RS, codes 86*), PREVINE known codes, UPG geojson, BHO6 snap.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import Point, shape
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
UA = {"User-Agent": "PREVINE-estudo-postos/1.0"}
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx"
BHO6 = (
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)

FAMILY_LABEL = {
    "786": "tronco Antas/Taquari (786)",
    "7868": "sistema Prata / Turvo-Humatã (7868)",
    "7866": "Rio Carreiro (7866)",
    "7864": "Rio Guaporé (7864)",
    "7862": "sistema Forqueta (7862)",
}

UPG_FAMILY_HINT = {
    "Prata": "7868",
    "Carreiro": "7866",
    "Guaporé": "7864",
    "Forqueta": "7862",
    "Alto Taquari-Antas": "786",
    "Médio Taquari-Antas": "786",
    "Baixo Taquari-Antas": "786",
}

PREVINE_SEED = {
    "86510000": {"previne_role": "alvo Mucum RNA/HEC corredor"},
    "86472600": {"previne_role": "alvo/montante Santa Tereza"},
    "86472000": {"previne_role": "controle Antas / Linha Jose Julio"},
    "86507000": {"previne_role": "input RNA Carreiro"},
    "86125130": {"previne_role": "input RNA Ituim"},
    "86298000": {"previne_role": "input RNA Castro Alves"},
    "86125500": {"previne_role": "input RNA Jararaca/Prata"},
    "86448000": {"previne_role": "input RNA Monte Claro"},
    "86306000": {"previne_role": "input operacional Nova Roma"},
    "86430900": {"previne_role": "input operacional"},
    "86447000": {"previne_role": "input operacional"},
    "86505500": {"previne_role": "input operacional / chuva Carreiro"},
    "2851072": {"previne_role": "chuva Carreiro-Prata"},
    "2851044": {"previne_role": "chuva Carreiro"},
    "86488000": {"previne_role": "chuva Carreiro"},
    "86490500": {"previne_role": "chuva Carreiro"},
    "86497000": {"previne_role": "chuva Carreiro"},
}


def http_bytes(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def http_json(url: str) -> Any:
    return json.loads(http_bytes(url).decode("utf-8"))


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_ana_tables(raw: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    text = (root.text or "").strip()
    if text.startswith("<"):
        root = ET.fromstring(text)
    rows: list[dict[str, str]] = []
    for table in root.iter():
        if local_tag(table.tag) != "Table":
            continue
        row = {local_tag(c.tag): (c.text or "").strip() for c in list(table)}
        if row.get("Codigo"):
            rows.append(row)
    return rows


def ana_inventario(**params: str) -> list[dict[str, str]]:
    q = {
        "codEstDE": "",
        "codEstATE": "",
        "tpEst": "",
        "nmEst": "",
        "nmRio": "",
        "codSubBacia": "",
        "codBacia": "",
        "nmMunicipio": "",
        "nmEstado": "",
        "sgResp": "",
        "sgOper": "",
        "telemetrica": "",
    }
    q.update({k: v for k, v in params.items() if v is not None})
    url = ANA + "/HidroInventario?" + urllib.parse.urlencode(q)
    return parse_ana_tables(http_bytes(url))


def ana_one(code: str) -> dict[str, str] | None:
    # legacy single-code endpoint used in repo
    url = (
        f"{ANA}/HidroInventario?codEstacao={code}&nomeEstacao=&codSubBacia="
        f"&codBacia=&nomeResponsavel=&nomeOperadora="
    )
    try:
        rows = parse_ana_tables(http_bytes(url, timeout=60))
    except Exception:
        # fallback range query for one code
        rows = ana_inventario(codEstDE=code, codEstATE=code)
    return rows[0] if rows else None


def fnum(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", "."))
    except ValueError:
        return None


def family_from_cocursodag(code: str | None) -> str | None:
    if not code:
        return None
    s = str(code)
    if not s.startswith("786"):
        return "fora_786"
    for fam in ("7868", "7866", "7864", "7862"):
        if s.startswith(fam):
            return fam
    if s == "786" or s.startswith("786"):
        # other 786x tributaries inside main tree
        if s == "786" or re.fullmatch(r"786", s):
            return "786"
        # e.g. 7860, 7861, 7863, 7865, 7867, 7869...
        if len(s) >= 4 and s[:4] in {"7860", "7861", "7863", "7865", "7867", "7869"}:
            return s[:4]
        return "786"
    return None


def snap_bho6(lon: float, lat: float) -> dict[str, Any] | None:
    """Nearest BHO6 reach within ~8 km of the station."""
    geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}})
    params = {
        "geometry": geom,
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": 8000,
        "units": "esriSRUnit_Meter",
        "outFields": "fid,cocursodag,nuareamont,noriocomp,noespecif,cobacia",
        "returnGeometry": "false",
        "resultRecordCount": 20,
        "f": "json",
    }
    try:
        payload = http_json(BHO6 + "?" + urllib.parse.urlencode(params))
    except Exception:
        return None
    feats = payload.get("features") or []
    if not feats:
        return None
    # prefer reaches in 786* with largest upstream area among candidates
    scored = []
    for f in feats:
        a = f.get("attributes") or {}
        coc = str(a.get("cocursodag") or "")
        area = float(a.get("nuareamont") or 0)
        bonus = 1e9 if coc.startswith("786") else 0
        scored.append((bonus + area, a))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][1]
    fam = family_from_cocursodag(best.get("cocursodag"))
    return {
        "cocursodag": best.get("cocursodag"),
        "cobacia": best.get("cobacia"),
        "nuareamont_km2": fnum(best.get("nuareamont")),
        "noriocomp": best.get("noriocomp") or best.get("noespecif"),
        "family": fam,
        "family_label": FAMILY_LABEL.get(fam or "", fam),
    }


def load_previne_extras() -> dict[str, dict[str, Any]]:
    extras: dict[str, dict[str, Any]] = dict(PREVINE_SEED)
    mucum = ROOT / "assets" / "data" / "mucum_modelo_inputs.json"
    if mucum.exists():
        data = json.loads(mucum.read_text(encoding="utf-8"))
        for code, meta in (data.get("estacoes_input") or {}).items():
            extras.setdefault(str(code), {})["previne_role"] = meta.get("papel") or extras.get(str(code), {}).get(
                "previne_role"
            )
            extras[str(code)]["municipio_previne"] = meta.get("municipio")
            extras[str(code)]["rio_previne"] = meta.get("rio")
            if meta.get("lat") is not None:
                extras[str(code)]["lat"] = meta.get("lat")
                extras[str(code)]["lon"] = meta.get("lon")
    return extras


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading UPG + G040 polygons...")
    ugs = json.loads((OUT / "ugs_g040.geojson").read_text(encoding="utf-8"))
    bacias = json.loads((OUT / "bacias_rs_25.geojson").read_text(encoding="utf-8"))
    g040_feat = next(f for f in bacias["features"] if f["properties"]["codigo"] == "G040")
    g040 = shape(g040_feat["geometry"])
    if not g040.is_valid:
        g040 = g040.buffer(0)

    upg_polys = []
    upg_props = []
    for f in ugs["features"]:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        upg_polys.append(g)
        upg_props.append(f["properties"])
    tree = STRtree(upg_polys)

    def assign_upg(lon: float, lat: float) -> dict[str, Any] | None:
        pt = Point(lon, lat)
        if not g040.covers(pt) and not g040.intersects(pt.buffer(0.01)):
            # allow tiny buffer for riverside stations on boundary
            if not g040.buffer(0.02).covers(pt):
                return None
        idxs = tree.query(pt)
        for i in idxs:
            if upg_polys[int(i)].covers(pt) or upg_polys[int(i)].intersects(pt.buffer(0.005)):
                p = upg_props[int(i)]
                return {
                    "upg": p.get("sub_bacia") or p.get("upg"),
                    "cod_bacia": p.get("cod_bacia"),
                    "hint_family": UPG_FAMILY_HINT.get(p.get("sub_bacia") or "", None),
                }
        # nearest UPG if inside G040 but on a gap
        if g040.buffer(0.02).covers(pt):
            dists = [(upg_polys[i].distance(pt), i) for i in range(len(upg_polys))]
            dists.sort()
            i = dists[0][1]
            p = upg_props[i]
            return {
                "upg": p.get("sub_bacia") or p.get("upg"),
                "cod_bacia": p.get("cod_bacia"),
                "hint_family": UPG_FAMILY_HINT.get(p.get("sub_bacia") or "", None),
                "assignment": "nearest_upg",
            }
        return None

    print("fetching ANA flu+plu RS codes 86* (telem + convencional)...")
    rows: list[dict[str, str]] = []
    for tp in ("1", "2"):
        print(" ", f"tpEst={tp}")
        batch = ana_inventario(
            codEstDE="86000000",
            codEstATE="86999999",
            tpEst=tp,
            nmEstado="Rio Grande do Sul",
        )
        print("   ->", len(batch))
        rows.extend(batch)

    # short-code PREVINE rain posts (28xxxxx)
    extras = load_previne_extras()
    for code in list(extras):
        if not any(r.get("Codigo") == code for r in rows):
            print("  fetch seed", code)
            one = ana_one(code)
            if one:
                rows.append(one)

    # dedupe by codigo
    by_code: dict[str, dict[str, str]] = {}
    for r in rows:
        code = r.get("Codigo")
        if not code:
            continue
        prev = by_code.get(code)
        if prev is None or (r.get("Latitude") and not prev.get("Latitude")):
            by_code[code] = r

    print("unique ANA rows", len(by_code))
    stations_in: list[dict[str, Any]] = []
    stations_out: list[dict[str, Any]] = []

    for code, r in sorted(by_code.items()):
        lat = fnum(r.get("Latitude"))
        lon = fnum(r.get("Longitude"))
        # fill from previne extras if missing
        ex = extras.get(code) or {}
        if lat is None:
            lat = fnum(ex.get("lat"))
        if lon is None:
            lon = fnum(ex.get("lon"))
        tipo = r.get("TipoEstacao") or r.get("tpEstacao") or ""
        tipo_nome = {"1": "fluviometrica", "2": "pluviometrica"}.get(str(tipo), str(tipo) or "desconhecido")
        base = {
            "codigo": code,
            "nome": r.get("Nome") or ex.get("nome"),
            "tipo": tipo_nome,
            "lat": lat,
            "lon": lon,
            "altitude_m": fnum(r.get("Altitude")),
            "area_drenagem_km2": fnum(r.get("AreaDrenagem")),
            "rio": r.get("Rio") or r.get("CursoDagua") or ex.get("rio_previne"),
            "municipio": r.get("Municipio") or r.get("MunicipioNome") or ex.get("municipio_previne"),
            "uf": r.get("Estado") or r.get("EstadoSigla") or "RS",
            "operadora": r.get("OperadoraSigla") or r.get("Operadora"),
            "responsavel": r.get("ResponsavelSigla") or r.get("Responsavel"),
            "telemetrica": r.get("Telemetrica") or r.get("telemetrica"),
            "operando": r.get("Operando"),
            "previne_role": ex.get("previne_role"),
            "in_previne_seed": code in extras,
        }
        if lat is None or lon is None:
            base["upg"] = None
            base["inside_g040"] = False
            base["note"] = "sem coordenadas"
            stations_out.append(base)
            continue
        upg = assign_upg(lon, lat)
        if not upg:
            base["inside_g040"] = False
            stations_out.append(base)
            continue
        base["inside_g040"] = True
        base["upg"] = upg.get("upg")
        base["upg_assignment"] = upg.get("assignment", "polygon")
        print(f"  snap BHO6 {code} ({base['nome']})...")
        snap = snap_bho6(lon, lat)
        if snap:
            base["bho6"] = snap
            fam = snap.get("family")
        else:
            fam = upg.get("hint_family")
            base["bho6"] = {
                "family": fam,
                "family_label": FAMILY_LABEL.get(fam or "", fam),
                "source": "upg_hint_only",
            }
        # if snap family is outside 786 but UPG hint exists, keep both
        if fam and str(fam).startswith("786"):
            base["bho6_family"] = fam
        else:
            base["bho6_family"] = upg.get("hint_family") or fam
        base["bho6_family_label"] = FAMILY_LABEL.get(
            base["bho6_family"] or "", base["bho6_family"]
        )
        stations_in.append(base)

    stations_in.sort(key=lambda s: (s.get("upg") or "", s.get("bho6_family") or "", s["codigo"]))

    by_upg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in stations_in:
        by_upg[s.get("upg") or "sem_upg"].append(compact(s))
        by_family[s.get("bho6_family") or "sem_familia"].append(compact(s))

    coverage = {
        "upg_with_stations": sorted(k for k, v in by_upg.items() if v),
        "upg_without_stations": sorted(
            set(UPG_FAMILY_HINT) - set(by_upg.keys())
        ),
        "families_with_stations": sorted(by_family.keys()),
        "previne_seeds_inside_g040": [s["codigo"] for s in stations_in if s.get("in_previne_seed")],
        "previne_seeds_outside_or_unlocated": [
            c
            for c in extras
            if c not in {s["codigo"] for s in stations_in}
        ],
    }

    report = {
        "schema_version": "estudo_postos_por_upg_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "inventario de postos ANA dentro de G040 por UPG e familia BHO6; nao e HEC",
        "method": {
            "ana": "HidroInventario RS, codigos 86000000-86999999, flu+plu (telem e nao-telem), + seeds PREVINE",
            "spatial": "ponto dentro do poligono G040 e UPG (ugs_g040.geojson)",
            "bho6": "snap a trecho BHO6 num raio de 8 km; fallback = hint da UPG",
        },
        "counts": {
            "ana_unique_fetched": len(by_code),
            "inside_g040": len(stations_in),
            "flu_inside": sum(1 for s in stations_in if s["tipo"] == "fluviometrica"),
            "plu_inside": sum(1 for s in stations_in if s["tipo"] == "pluviometrica"),
            "previne_seed_inside": sum(1 for s in stations_in if s.get("in_previne_seed")),
            "outside_or_no_coords": len(stations_out),
        },
        "coverage_gaps": coverage,
        "reading": {
            "guapore_forqueta": (
                "Se Guapore/Forqueta tiverem poucos ou nenhum posto PREVINE, isso confirma "
                "que o corredor Ate Mucum nao observa essas UPG — coerente com fozes a jusante."
            ),
            "prata_carreiro": (
                "Prata (7868) e Carreiro (7866) devem aparecer com postos se o inventario ANA "
                "estiver completo; sao entradas hidrologicas a montante de Santa Tereza/Mucum."
            ),
            "implication": (
                "Inventario por UPG e o passo antes de escolher o recorte de modelo. "
                "Ainda nao e estrutura HEC."
            ),
        },
        "by_upg": {k: v for k, v in sorted(by_upg.items())},
        "by_bho6_family": {k: v for k, v in sorted(by_family.items())},
        "stations_inside_g040": stations_in,
        "artifacts": {
            "json": "postos_por_upg_latest.json",
            "geojson": "postos_g040.geojson",
            "mapa": "mapa_postos_upg.html",
        },
    }

    (OUT / "postos_por_upg_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    fc = {
        "type": "FeatureCollection",
        "name": "postos_g040",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                "properties": compact(s),
            }
            for s in stations_in
            if s.get("lon") is not None and s.get("lat") is not None
        ],
    }
    (OUT / "postos_g040.geojson").write_text(json.dumps(fc, ensure_ascii=False) + "\n", encoding="utf-8")

    merge_estudo(report)
    write_map(report, ugs, fc)
    print(
        json.dumps(
            {
                "ok": True,
                "inside": report["counts"]["inside_g040"],
                "by_upg": {k: len(v) for k, v in report["by_upg"].items()},
                "by_family": {k: len(v) for k, v in report["by_bho6_family"].items()},
                "gaps_upg": coverage["upg_without_stations"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def compact(s: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "codigo",
        "nome",
        "tipo",
        "lat",
        "lon",
        "area_drenagem_km2",
        "rio",
        "municipio",
        "telemetrica",
        "operando",
        "upg",
        "bho6_family",
        "bho6_family_label",
        "previne_role",
        "in_previne_seed",
    ]
    out = {k: s.get(k) for k in keys}
    if isinstance(s.get("bho6"), dict):
        out["bho6_cocursodag"] = s["bho6"].get("cocursodag")
        out["bho6_nuareamont_km2"] = s["bho6"].get("nuareamont_km2")
    return out


def merge_estudo(report: dict[str, Any]) -> None:
    path = OUT / "estudo_bacia_latest.json"
    if not path.exists():
        return
    prev = json.loads(path.read_text(encoding="utf-8"))
    prev["postos_por_upg"] = {
        "status": "inventariado",
        "counts": report["counts"],
        "coverage_gaps": report["coverage_gaps"],
        "reading": report["reading"],
        "artifacts": report["artifacts"],
        "updated_at_utc": report["generated_at_utc"],
    }
    known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
    for item in [
        f"Inventario ANA dentro de G040: {report['counts']['inside_g040']} postos com UPG/familia BHO6.",
        f"UPGs sem posto no inventario atual: {', '.join(report['coverage_gaps']['upg_without_stations']) or 'nenhuma'}.",
    ]:
        if item not in known:
            known.append(item)
    unknown = prev.setdefault("known_vs_unknown", {}).setdefault("unknown_or_unreconciled", [])
    prev["known_vs_unknown"]["unknown_or_unreconciled"] = [
        u
        for u in unknown
        if "Inventario" not in u and "postos por UPG" not in u and "Inventario de postos" not in u
    ]
    prev["next_study_steps_only"] = [
        "Completar postos sem coordenada / fora do range 86* (INMET/CEMADEN) se forem relevantes.",
        "Decidir com Juliana o recorte de modelo: G040 inteira vs corredor Ate Mucum vs outro.",
        "So depois discutir estrutura HEC alinhada ao recorte e aos postos por UPG.",
    ]
    path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_map(report: dict[str, Any], ugs: dict, postos_fc: dict) -> None:
    fam_colors = {
        "786": "#0a6f9c",
        "7868": "#2a9d8f",
        "7866": "#c45c16",
        "7864": "#6b4c9a",
        "7862": "#9a5b12",
    }
    upg_rows = "".join(
        f"<tr><td>{upg}</td><td class='num'>{len(rows)}</td>"
        f"<td>{', '.join(r['codigo'] for r in rows[:8])}{'…' if len(rows)>8 else ''}</td></tr>"
        for upg, rows in report["by_upg"].items()
    )
    fam_rows = "".join(
        f"<tr><td>{fam}</td><td>{FAMILY_LABEL.get(fam, fam)}</td>"
        f"<td class='num'>{len(rows)}</td></tr>"
        for fam, rows in report["by_bho6_family"].items()
    )
    gaps = ", ".join(report["coverage_gaps"]["upg_without_stations"]) or "nenhuma"
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Postos por UPG · Taquari-Antas</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; }}
    body {{ margin:0; color:var(--ink); font:16px/1.5 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1180px; margin:auto; padding:24px 16px 56px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(26px,4vw,40px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:24px; color:var(--accent); }}
    #map {{ height:540px; border-radius:14px; border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:7px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }} td.num {{ text-align:right; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:900px) {{ .grid {{ grid-template-columns:1fr 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · postos por UPG</div>
    <h1>Quem observa cada pedaco da bacia?</h1>
    <p class="muted">{report['generated_at_utc']}</p>
    <div class="notice"><strong>Ainda sem HEC.</strong> {report['reading']['implication']}</div>
  </header>
  <section>
    <div class="grid">
      <div class="stat"><strong>{report['counts']['inside_g040']}</strong><span>postos dentro de G040</span></div>
      <div class="stat"><strong>{report['counts']['flu_inside']}</strong><span>fluviometricos</span></div>
      <div class="stat"><strong>{report['counts']['plu_inside']}</strong><span>pluviometricos</span></div>
      <div class="stat"><strong>{report['counts']['previne_seed_inside']}</strong><span>seeds PREVINE no inventario</span></div>
    </div>
  </section>
  <section>
    <h2>Mapa</h2>
    <div id="map"></div>
    <p class="muted">Poligonos = 7 UPG. Pontos coloridos por familia BHO6 (azul tronco, verde Prata, laranja Carreiro, roxo Guapore, âmbar Forqueta).</p>
  </section>
  <section>
    <h2>Por UPG</h2>
    <div class="notice">UPGs sem posto neste inventario: <strong>{gaps}</strong></div>
    <table><thead><tr><th>UPG</th><th class="num">n</th><th>codigos (amostra)</th></tr></thead><tbody>{upg_rows}</tbody></table>
  </section>
  <section>
    <h2>Por familia BHO6</h2>
    <table><thead><tr><th>Familia</th><th>Label</th><th class="num">n</th></tr></thead><tbody>{fam_rows}</tbody></table>
  </section>
  <section>
    <h2>Arquivos</h2>
    <ul>
      <li><a href="postos_por_upg_latest.json">postos_por_upg_latest.json</a></li>
      <li><a href="postos_g040.geojson">postos_g040.geojson</a></li>
      <li><a href="mapa_hierarquia_rs.html">hierarquia RS</a></li>
      <li><a href="index.html">estudo-base</a></li>
    </ul>
  </section>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const ugs = {json.dumps(ugs, ensure_ascii=False)};
const postos = {json.dumps(postos_fc, ensure_ascii=False)};
const colors = {json.dumps(fam_colors)};
const map = L.map('map').setView([-29.1, -51.5], 8);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom:18, attribution:'&copy; OSM'}}).addTo(map);
L.geoJSON(ugs, {{
  style: {{color:'#0a6f9c', weight:1.2, fillColor:'#7eb8d4', fillOpacity:0.18}},
  onEachFeature: (f, layer) => layer.bindPopup(`<strong>${{f.properties.sub_bacia}}</strong>`)
}}).addTo(map);
L.geoJSON(postos, {{
  pointToLayer: (f, latlng) => L.circleMarker(latlng, {{
    radius: f.properties.in_previne_seed ? 7 : 5,
    color: '#fff', weight:1,
    fillColor: colors[f.properties.bho6_family] || '#555',
    fillOpacity: 0.9
  }}),
  onEachFeature: (f, layer) => layer.bindPopup(
    `<strong>${{f.properties.codigo}}</strong> ${{f.properties.nome||''}}<br>`+
    `${{f.properties.tipo}} · UPG ${{f.properties.upg}}<br>`+
    `BHO6 ${{f.properties.bho6_family_label||f.properties.bho6_family||'?'}}`
  )
}}).addTo(map);
try {{
  const b = L.latLngBounds(postos.features.map(f => [f.geometry.coordinates[1], f.geometry.coordinates[0]]));
  map.fitBounds(b.pad(0.12));
}} catch (e) {{}}
</script>
</body>
</html>
"""
    (OUT / "mapa_postos_upg.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
