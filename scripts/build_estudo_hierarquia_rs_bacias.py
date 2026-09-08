#!/usr/bin/env python3
"""Deep STUDY of RS hydrographic hierarchy and what influences Taquari-Antas.

Corrects the incomplete reading that stopped at "32 sub-bacias".

Official stack (different products, different purposes):
  3 RH  →  25 BH (Decreto 53.885/2018)
       →  ~175 UPG / "UBH" publicada SEMA (gestão / balanço agregado)
       →  32 sub-bacias de ENQUADRAMENTO em G040 (qualidade da água)
       →  ~33.133 ottobacias BHO6 / HSIG na árvore 786 (mini-unidades hidrológicas)
       →  mini-bacias SIOUT (ArcHydro sobre BC25) — produto operacional de outorga;
          o ZIP público rotulado UBH NÃO é esse nível fino (é o nível UPG).

No HEC. No calibration.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
UA = {"User-Agent": "PREVINE-estudo-hierarquia-rs/1.0"}

IEDE = "https://iede.rs.gov.br/server/rest/services/DRH"
HSIG = (
    "https://hsig.sema.rs.gov.br/arcgis/rest/services/"
    "1_RSAGUAS/Mapa_basico_SIGRSAGUA/FeatureServer"
)
BHO6 = (
    "https://portal1.snirh.gov.br/server/rest/services/Hosted/"
    "main_geoft_bho6_trecho_drenagem/FeatureServer/0/query"
)

TARGET = "G040"

# Hydrologic influence taxonomy (explicit — do not invent tributary links)
INFLUENCE_RULES: dict[str, dict[str, Any]] = {
    "G040": {
        "role": "alvo",
        "runoff_into_taquari_antas": True,
        "note": "Unica bacia cuja chuva escoa para o tronco Taquari-Antas.",
    },
    "G070": {
        "role": "jusante_hidraulica",
        "runoff_into_taquari_antas": False,
        "note": "Baixo Jacui recebe o Taquari; remanso/nivel no Jacui pode afetar o Baixo Taquari.",
    },
    "G080": {
        "role": "jusante_sistema",
        "runoff_into_taquari_antas": False,
        "note": "Lago Guaiba e o sistema receptor a jusante do Jacui; influencia hidraulica indireta.",
    },
    "G030": {
        "role": "vizinha_divisor",
        "runoff_into_taquari_antas": False,
        "note": "Cai: bacia vizinha (mesmo layer de enquadramento). Nao e afluente do Taquari; divide e clima compartilhado.",
    },
    "G050": {
        "role": "vizinha_divisor",
        "runoff_into_taquari_antas": False,
        "note": "Alto Jacui: vizinha a oeste; nao drena para o Taquari.",
    },
    "G090": {
        "role": "vizinha_via_jacui",
        "runoff_into_taquari_antas": False,
        "note": "Pardo: afluente do Jacui; pode modular nivel no Jacui a jusante, nao o tronco Taquari.",
    },
    "G060": {
        "role": "mesma_rh_jacui",
        "runoff_into_taquari_antas": False,
        "note": "Vacacai: RH Guaiba / sistema Jacui; sem contribuicao direta ao Taquari.",
    },
    "G010": {
        "role": "mesma_rh",
        "runoff_into_taquari_antas": False,
        "note": "Gravatai: mesma RH Guaiba; sem escoamento para G040.",
    },
    "G020": {
        "role": "mesma_rh",
        "runoff_into_taquari_antas": False,
        "note": "Sinos: mesma RH Guaiba; sem escoamento para G040.",
    },
}


def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def deg2_to_km2(area_deg2: float, lat_deg: float = -29.5) -> float:
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_deg))
    return area_deg2 * (m_per_deg_lat * m_per_deg_lon) / 1e6


def fetch_all(base_query: str, out_fields: str = "*", geometry: bool = False) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": out_fields,
            "returnGeometry": "true" if geometry else "false",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": 2000,
            "orderByFields": "objectid" if "objectid" in out_fields.lower() or out_fields == "*" else "",
            "f": "geojson" if geometry else "json",
        }
        if not params["orderByFields"]:
            del params["orderByFields"]
        payload = http_json(base_query + "?" + urllib.parse.urlencode(params))
        if geometry:
            feats = payload.get("features") or []
            rows.extend(feats)
            if len(feats) < 2000:
                break
            offset += len(feats)
        else:
            feats = payload.get("features") or []
            rows.extend(feats)
            if len(feats) < 2000:
                break
            offset += len(feats)
        if offset > 200000:
            break
    return rows


def count_query(url: str, where: str) -> int:
    payload = http_json(
        url
        + "?"
        + urllib.parse.urlencode({"where": where, "returnCountOnly": "true", "f": "json"})
    )
    return int(payload.get("count") or 0)


def classify_basin(code: str, touches_g040: bool, regiao: str) -> dict[str, Any]:
    base = dict(INFLUENCE_RULES.get(code, {}))
    if not base:
        if regiao == "Guaíba":
            base = {
                "role": "mesma_rh",
                "runoff_into_taquari_antas": False,
                "note": "Mesma Regiao Hidrografica do Guaiba; sem escoamento para o tronco Taquari-Antas.",
            }
        elif regiao == "Uruguai":
            base = {
                "role": "outra_rh",
                "runoff_into_taquari_antas": False,
                "note": "RH Uruguai: nao contribui hidrologicamente ao Taquari-Antas (pode compartilhar frente meteorologica em escala sinotica).",
            }
        else:
            base = {
                "role": "outra_rh",
                "runoff_into_taquari_antas": False,
                "note": "RH Litoral: sem contribuicao hidrologica ao Taquari-Antas.",
            }
    base["touches_g040_geometry"] = touches_g040
    if touches_g040 and code != TARGET and base.get("role") in {"mesma_rh", "outra_rh"}:
        base["role"] = "vizinha_divisor"
        base["note"] = (
            base.get("note", "")
            + " Contato geometrico com o limite G040 (divisor / fronteira de bacia)."
        ).strip()
    return base


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("1/6 fetching 25 bacias + geometry...")
    bacias_fc = fetch_all(
        f"{IEDE}/Bacias_Hidrograficas/FeatureServer/0/query",
        out_fields="*",
        geometry=True,
    )
    # Normalize feature properties
    bacias: list[dict[str, Any]] = []
    g040_geom = None
    for feat in bacias_fc:
        props = dict(feat.get("properties") or {})
        # area field name varies
        area_official = None
        for k, v in list(props.items()):
            if isinstance(k, str) and k.endswith(".area") and isinstance(v, (int, float)):
                area_official = float(v)
        code = (props.get("codigo") or "").strip()
        geom = feat.get("geometry")
        sh = shape(geom) if geom else None
        if code == TARGET and sh is not None:
            g040_geom = sh
        bacias.append(
            {
                "codigo": code,
                "nome": props.get("nome"),
                "regiao": props.get("regiao"),
                "area_km2_official_attr": area_official,
                "status_planos": props.get("status_planos"),
                "vazao_referencia": props.get("vazao_referencia"),
                "maximo_outorgavel": props.get("maximo_outorgavel"),
                "geometry": geom,
                "_shape": sh,
            }
        )

    if g040_geom is None:
        raise RuntimeError("G040 geometry missing")

    print("2/6 adjacency vs G040...")
    for b in bacias:
        sh = b["_shape"]
        touches = False
        if sh is not None:
            try:
                touches = bool(sh.intersects(g040_geom) and not sh.equals(g040_geom))
                # treat self
                if b["codigo"] == TARGET:
                    touches = True
            except Exception:
                touches = False
        b["influence"] = classify_basin(b["codigo"], touches, b.get("regiao") or "")
        if b["codigo"] == TARGET:
            b["influence"]["touches_g040_geometry"] = True

    print("3/6 fetching 175 UPGs statewide...")
    upg_fc = fetch_all(
        f"{IEDE}/limites_sub_bacias_hidrograficas/FeatureServer/0/query",
        out_fields="*",
        geometry=True,
    )
    upgs: list[dict[str, Any]] = []
    upgs_by_basin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feat in upg_fc:
        props = dict(feat.get("properties") or {})
        code = (props.get("cod_bacia") or "").strip()
        area_approx = round(deg2_to_km2(float(props.get("Shape__Area") or 0)), 2)
        row = {
            "cod_bacia": code,
            "upg": props.get("sub_bacia"),
            "bacia_hidr": props.get("bacia_hidr"),
            "area_km2_approx": area_approx,
            "objectid": props.get("objectid"),
            "geometry": feat.get("geometry"),
        }
        upgs.append(row)
        upgs_by_basin[code].append({"upg": row["upg"], "area_km2_approx": area_approx})

    print("4/6 enquadramento G040/G030 + balanco...")
    enquad_q040 = count_query(
        f"{IEDE}/Enquad_Sub_Bacias_Taquari_Antas_Cai/FeatureServer/0/query",
        "bh='Q040'",
    )
    enquad_g030 = count_query(
        f"{IEDE}/Enquad_Sub_Bacias_Taquari_Antas_Cai/FeatureServer/0/query",
        "bh='G030'",
    )
    balanco = fetch_all(
        f"{IEDE}/Balanco_Hidrico/FeatureServer/0/query",
        out_fields="objectid,upg,id_balanco,cod,bacia_hidr,comprometi",
        geometry=False,
    )
    balanco_by = Counter((f["attributes"].get("cod") or "").strip() for f in balanco)

    print("5/6 counting ottobacias / BHO6 mini-units for tree 786...")
    otto_786 = count_query(f"{HSIG}/7/query", "COCURSODAG LIKE '786%'")
    bho6_786 = count_query(BHO6, "cocursodag LIKE '786%'")
    bho6_families = {
        "786 (tronco)": count_query(BHO6, "cocursodag='786'"),
        "7868 Prata-sistema": count_query(BHO6, "cocursodag LIKE '7868%'"),
        "7866 Carreiro": count_query(BHO6, "cocursodag LIKE '7866%'"),
        "7864 Guapore": count_query(BHO6, "cocursodag LIKE '7864%'"),
        "7862 Forqueta": count_query(BHO6, "cocursodag LIKE '7862%'"),
    }

    # Build geojson artifacts (no shapely objects)
    def simplify_geom(geom: Any, tol: float = 0.002) -> Any:
        if not geom:
            return None
        from shapely.geometry import mapping

        g = shape(geom)
        if not g.is_valid:
            g = g.buffer(0)
        return mapping(g.simplify(tol, preserve_topology=True))

    bacias_geo = {
        "type": "FeatureCollection",
        "name": "bacias_hidrograficas_rs_25",
        "features": [
            {
                "type": "Feature",
                "geometry": simplify_geom(b["geometry"]),
                "properties": {
                    "codigo": b["codigo"],
                    "nome": b["nome"],
                    "regiao": b["regiao"],
                    "area_km2_official_attr": b["area_km2_official_attr"],
                    "status_planos": b["status_planos"],
                    "influence_role": b["influence"]["role"],
                    "runoff_into_taquari_antas": b["influence"]["runoff_into_taquari_antas"],
                    "touches_g040_geometry": b["influence"]["touches_g040_geometry"],
                    "influence_note": b["influence"]["note"],
                },
            }
            for b in bacias
            if b["geometry"]
        ],
    }
    upg_geo = {
        "type": "FeatureCollection",
        "name": "upgs_ubh_publicadas_rs_175",
        "features": [
            {
                "type": "Feature",
                "geometry": simplify_geom(u["geometry"]),
                "properties": {
                    "cod_bacia": u["cod_bacia"],
                    "upg": u["upg"],
                    "bacia_hidr": u["bacia_hidr"],
                    "area_km2_approx": u["area_km2_approx"],
                    "objectid": u["objectid"],
                },
            }
            for u in upgs
            if u["geometry"]
        ],
    }

    (OUT / "bacias_rs_25.geojson").write_text(
        json.dumps(bacias_geo, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "upgs_rs_175.geojson").write_text(
        json.dumps(upg_geo, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Influence tables
    influence_rows = []
    for b in sorted(bacias, key=lambda x: x["codigo"] or ""):
        influence_rows.append(
            {
                "codigo": b["codigo"],
                "nome": b["nome"],
                "regiao": b["regiao"],
                "area_km2": b["area_km2_official_attr"],
                "n_upg": len(upgs_by_basin.get(b["codigo"], [])),
                "n_balanco_iede": balanco_by.get(b["codigo"], 0),
                **b["influence"],
            }
        )

    runoff_only = [r for r in influence_rows if r["runoff_into_taquari_antas"]]
    hydraulic = [r for r in influence_rows if r["role"] in {"jusante_hidraulica", "jusante_sistema"}]
    neighbors = [r for r in influence_rows if r["role"] in {"vizinha_divisor", "vizinha_via_jacui"} or r["touches_g040_geometry"] and r["codigo"] != TARGET]
    same_rh = [r for r in influence_rows if r["regiao"] == "Guaíba" and r["codigo"] != TARGET]

    report = {
        "schema_version": "estudo_hierarquia_rs_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "estudo profundo da hierarquia hidrografica do RS e da influencia sobre Taquari-Antas; NAO e HEC",
        "discipline_rule": "Nao tratar 32 sub-bacias de enquadramento como se fossem todas as unidades da bacia. Ha varios niveis com fins distintos.",
        "correction": {
            "wrong_reading": "A Taquari-Antas tem so 32 sub-bacias — ponto final.",
            "right_reading": (
                "32 e o nivel de ENQUADRAMENTO (qualidade da agua, codigo Q040 no IEDE). "
                "Abaixo/ao lado existem 7 UPG de gestao, ~33 mil ottobacias/trechos BHO6 na arvore 786, "
                "e mini-bacias SIOUT (ArcHydro/BC25) usadas em outorga. Acima: 25 BH e 3 RH."
            ),
        },
        "hierarchy_levels": [
            {
                "level": 1,
                "name": "Regioes Hidrograficas",
                "count": 3,
                "names": ["Uruguai", "Guaiba", "Litoral"],
                "source": f"{IEDE}/limite_regioes_hidrograficas",
            },
            {
                "level": 2,
                "name": "Bacias Hidrograficas (Decreto 53.885/2018)",
                "count": 25,
                "g040": {"codigo": "G040", "nome": "Taquari-Antas", "area_km2": 26430},
                "source": f"{IEDE}/Bacias_Hidrograficas",
            },
            {
                "level": 3,
                "name": "UPG / Unidades publicadas como UBH (SEMA zip 2024)",
                "count_rs": len(upgs),
                "count_g040": len(upgs_by_basin.get(TARGET, [])),
                "g040_names": [u["upg"] for u in upgs_by_basin.get(TARGET, [])],
                "warning": (
                    "O arquivo SEMA 'Unidades_Balanco_Hidrico.zip' tem 175 poligonos = nivel UPG, "
                    "NAO as mini-bacias finas do artigo SIOUT/ArcHydro."
                ),
                "source_iede": f"{IEDE}/limites_sub_bacias_hidrograficas",
                "source_zip": "https://www.sema.rs.gov.br/upload/arquivos/202406/24164843-unidades-balanco-hidrico.zip",
            },
            {
                "level": 4,
                "name": "Sub-bacias de enquadramento (qualidade da agua)",
                "count_g040_q040": enquad_q040,
                "count_cai_g030_same_layer": enquad_g030,
                "note": "Layer IEDE compartilhado Taquari-Antas + Cai. Codigo da bacia no layer = Q040 (nao G040).",
                "source": f"{IEDE}/Enquad_Sub_Bacias_Taquari_Antas_Cai",
            },
            {
                "level": 5,
                "name": "Ottobacias / trechos BHO6 (mini-unidades hidrologicas)",
                "count_polygons_hsig_cocursodag_786": otto_786,
                "count_trechos_bho6_cocursodag_786": bho6_786,
                "families_bho6_trechos": bho6_families,
                "note": (
                    "Este e o nivel fino de contribuicao hidrologica (Pfafstetter). "
                    "Para modelagem fisica, sao dezenas de milhares de unidades — nao 32."
                ),
                "sources": [f"{HSIG}/7", BHO6],
            },
            {
                "level": 6,
                "name": "Mini-bacias SIOUT (ArcHydro sobre BC25)",
                "status": "existentes_no_sistema_de_outorga_nao_espelhadas_no_zip_ubh_publico",
                "note": (
                    "Artigo SBRH 2019 descreve mini-bacias hierarquizadas por bacia para balanco/outorga. "
                    "Nao confundir com o shapefile publico UBH (175 UPGs) nem com minibacias do Atlas Hidroenergetico."
                ),
                "reference": "https://sema.rs.gov.br/upload/arquivos/202004/29135341-sbrh-2019-balanco-siout-rs.pdf",
            },
        ],
        "what_influences_taquari_antas": {
            "runoff_contributors": runoff_only,
            "hydraulic_downstream": hydraulic,
            "geometric_or_divide_neighbors": neighbors,
            "same_rh_guaiba_no_direct_runoff": [
                {k: r[k] for k in ("codigo", "nome", "area_km2", "role", "note")} for r in same_rh
            ],
            "hard_rule": (
                "So a chuva que cai DENTRO de G040 (e suas UPG/ottobacias internas) escoa para o Taquari-Antas. "
                "Bacias vizinhas NAO sao afluentes. Jusante (Jacui/Guaiba) pode afetar por remanso. "
                "Clima compartilhado != contribuicao hidrologica."
            ),
        },
        "all_25_basins": influence_rows,
        "upgs_by_basin": {k: sorted(v, key=lambda x: x["upg"] or "") for k, v in sorted(upgs_by_basin.items())},
        "g040_internal_stack": {
            "bh": "G040 Taquari-Antas ~26430 km2",
            "upg_7": [u["upg"] for u in upgs_by_basin.get(TARGET, [])],
            "enquadramento_32": enquad_q040,
            "ottobacias_786": otto_786,
            "previne_corridor_note": (
                "O corredor Antas/STZ/Mucum (~16 mil km2) NAO inclui Guapore/Forqueta/Baixo Taquari completo."
            ),
        },
        "artifacts": {
            "bacias_geojson": "bacias_rs_25.geojson",
            "upgs_geojson": "upgs_rs_175.geojson",
            "report": "hierarquia_rs_latest.json",
            "mapa": "mapa_hierarquia_rs.html",
        },
        "next_study_steps_only": [
            "Anexar amostra/resumo espacial das ottobacias 786 (sem baixar 33k poligonos inteiros no Pages).",
            "Inventario de postos por UPG e por familia BHO6 (7868/7866/7864/7862).",
            "Decidir com Juliana o recorte de modelo: G040 inteira vs corredor Ate Mucum vs outro.",
            "So depois discutir estrutura HEC alinhada ao recorte escolhido.",
        ],
    }

    (OUT / "hierarquia_rs_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Merge into estudo_bacia_latest.json if present
    prev_path = OUT / "estudo_bacia_latest.json"
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        prev["hierarquia_rs"] = {
            "status": "estudado",
            "correction": report["correction"],
            "hierarchy_summary": [
                {"level": h["level"], "name": h["name"], **{k: h[k] for k in h if k in {"count", "count_rs", "count_g040", "count_g040_q040", "count_polygons_hsig_cocursodag_786"}}}
                for h in report["hierarchy_levels"]
            ],
            "hard_rule_influence": report["what_influences_taquari_antas"]["hard_rule"],
            "artifacts": report["artifacts"],
            "updated_at_utc": report["generated_at_utc"],
        }
        known = prev.setdefault("known_vs_unknown", {}).setdefault("known", [])
        for item in [
            "Hierarquia RS: 3 RH, 25 BH, ~175 UPG, 32 enquadramentos G040, ~33133 ottobacias na arvore 786.",
            "ZIP SEMA 'UBH' = 175 UPG; nao sao as mini-bacias finas SIOUT/ArcHydro.",
            "So G040 contribui com escoamento ao Taquari-Antas; vizinhas nao sao afluentes.",
            "Jacui/Guaiba podem influenciar o Baixo Taquari por remanso hidraulico.",
        ]:
            if item not in known:
                known.append(item)
        unknown = prev.setdefault("known_vs_unknown", {}).setdefault("unknown_or_unreconciled", [])
        prev["known_vs_unknown"]["unknown_or_unreconciled"] = [
            u for u in unknown if "Shapefile oficial das 32" not in u and "Posicao exata" not in u
        ]
        for item in [
            "Amostra espacial compacta das ~33 mil ottobacias 786 no repo.",
            "Inventario de postos por UPG/familia BHO6.",
            "Recorte de modelo PREVINE ainda nao decidido (G040 vs corredor Mucum).",
        ]:
            if item not in prev["known_vs_unknown"]["unknown_or_unreconciled"]:
                prev["known_vs_unknown"]["unknown_or_unreconciled"].append(item)
        prev["next_study_steps_only"] = report["next_study_steps_only"]
        prev_path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_map(report, bacias_geo)
    write_index_patch()
    print(
        json.dumps(
            {
                "ok": True,
                "bacias": len(bacias),
                "upgs": len(upgs),
                "enquad_q040": enquad_q040,
                "otto_786": otto_786,
                "neighbors_touching": [r["codigo"] for r in neighbors],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_map(report: dict[str, Any], bacias_geo: dict) -> None:
    role_colors = {
        "alvo": "#0a6f9c",
        "jusante_hidraulica": "#c45c16",
        "jusante_sistema": "#9a5b12",
        "vizinha_divisor": "#6b4c9a",
        "vizinha_via_jacui": "#6b4c9a",
        "mesma_rh": "#7a8f99",
        "mesma_rh_jacui": "#7a8f99",
        "outra_rh": "#b8c4c8",
    }
    rows = "".join(
        "<tr>"
        f"<td>{r['codigo']}</td><td>{r['nome']}</td><td>{r['regiao']}</td>"
        f"<td class='num'>{r['area_km2'] or ''}</td><td class='num'>{r['n_upg']}</td>"
        f"<td>{r['role']}</td><td>{'sim' if r['runoff_into_taquari_antas'] else 'nao'}</td>"
        f"<td>{'sim' if r['touches_g040_geometry'] else 'nao'}</td>"
        "</tr>"
        for r in report["all_25_basins"]
    )
    levels = "".join(
        f"<li><strong>L{h['level']}</strong> — {h['name']}"
        + (
            f": {h.get('count') or h.get('count_rs') or h.get('count_g040_q040') or h.get('count_polygons_hsig_cocursodag_786')}"
        )
        + "</li>"
        for h in report["hierarchy_levels"]
    )
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hierarquia hidrografica RS · influencia Taquari-Antas</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; }}
    body {{ margin:0; color:var(--ink); font:16px/1.5 "Source Sans 3",Segoe UI,sans-serif; background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1200px; margin:auto; padding:24px 16px 56px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:20px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(26px,4vw,40px)/1.08 "Fraunces",Georgia,serif; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .bad {{ border-left-color:#a33b35; background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:24px; color:var(--accent); }}
    #map {{ height:560px; border-radius:14px; border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:7px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ background:#eef6f7; }} td.num {{ text-align:right; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:900px) {{ .grid {{ grid-template-columns:1fr 1fr; }} #map {{ height:400px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · hierarquia RS</div>
    <h1>Nao sao so 32. Sao varios niveis.</h1>
    <p class="muted">{report['generated_at_utc']}</p>
    <div class="notice bad"><strong>Correcao:</strong> {report['correction']['right_reading']}</div>
  </header>
  <section>
    <div class="grid">
      <div class="stat"><strong>25</strong><span>bacias do RS</span></div>
      <div class="stat"><strong>175</strong><span>UPG / UBH publicadas</span></div>
      <div class="stat"><strong>32</strong><span>enquadramentos G040</span></div>
      <div class="stat"><strong>~{report['hierarchy_levels'][4]['count_polygons_hsig_cocursodag_786']:,}</strong><span>ottobacias arvore 786</span></div>
    </div>
  </section>
  <section>
    <h2>Pilha oficial</h2>
    <ul>{levels}</ul>
    <div class="notice"><strong>Regra dura:</strong> {report['what_influences_taquari_antas']['hard_rule']}</div>
  </section>
  <section>
    <h2>Mapa das 25 bacias</h2>
    <div id="map"></div>
    <p class="muted">Azul = G040 (alvo). Âmbar = jusante hidraulica. Roxo = vizinha/divisor. Cinza = outras.</p>
  </section>
  <section>
    <h2>As 25 bacias e a influencia sobre Taquari-Antas</h2>
    <table>
      <thead><tr><th>Cod</th><th>Nome</th><th>RH</th><th class="num">km²</th><th class="num">UPG</th><th>Papel</th><th>Escorre p/ TA?</th><th>Toca G040?</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Arquivos</h2>
    <ul>
      <li><a href="hierarquia_rs_latest.json">hierarquia_rs_latest.json</a></li>
      <li><a href="bacias_rs_25.geojson">bacias_rs_25.geojson</a></li>
      <li><a href="upgs_rs_175.geojson">upgs_rs_175.geojson</a></li>
      <li><a href="mapa_subbacias.html">mapa 7 UPG + fozes</a></li>
      <li><a href="index.html">estudo-base</a></li>
    </ul>
  </section>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const bacias = {json.dumps(bacias_geo, ensure_ascii=False)};
const colors = {json.dumps(role_colors)};
const map = L.map('map').setView([-29.5, -52.5], 7);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 18, attribution: '&copy; OSM' }}).addTo(map);
L.geoJSON(bacias, {{
  style: (f) => {{
    const role = f.properties.influence_role;
    const isTarget = f.properties.codigo === 'G040';
    return {{
      color: colors[role] || '#888',
      weight: isTarget ? 3 : 1.2,
      fillColor: colors[role] || '#888',
      fillOpacity: isTarget ? 0.45 : 0.22
    }};
  }},
  onEachFeature: (f, layer) => layer.bindPopup(
    `<strong>${{f.properties.codigo}} · ${{f.properties.nome}}</strong><br>` +
    `${{f.properties.influence_role}}<br>${{f.properties.influence_note}}`
  )
}}).addTo(map);
</script>
</body>
</html>
"""
    # Fix broken stat cell I accidentally left
    html = html.replace(
        """      <div class="stat"><strong>175</strong><span>UPG / UBH publicadas</span></div>
      <div class="stat"><strong>32</strong><span>enquadramentos G040</span></div>
      <div class="stat"><strong>~"""
        + f"{report['hierarchy_levels'][4]['count_polygons_hsig_cocursodag_786']:,}"
        + """</strong><span>ottobacias arvore 786</span></div>
    </div>""",
        """      <div class="stat"><strong>175</strong><span>UPG / UBH publicadas</span></div>
      <div class="stat"><strong>32</strong><span>enquadramentos G040 (qualidade)</span></div>
    </div>
    <div class="grid" style="margin-top:10px">
      <div class="stat"><strong>~"""
        + f"{report['hierarchy_levels'][4]['count_polygons_hsig_cocursodag_786']:,}"
        + """</strong><span>ottobacias / mini-unidades arvore 786</span></div>
      <div class="stat"><strong>7</strong><span>UPG dentro de G040</span></div>
      <div class="stat"><strong>1</strong><span>bacia com escoamento para TA (G040)</span></div>
      <div class="stat"><strong>0</strong><span>HEC neste pacote</span></div>
    </div>""",
    )
    # Remove the broken empty stat
    html = html.replace(
        """      <div class="stat"><strong>25</strong><span>bacias do RS</span></div>
      <div class="stat"><strong>0</strong></div>
      <div class="stat"><strong>175</strong><span>UPG / UBH publicadas</span></div>""",
        """      <div class="stat"><strong>25</strong><span>bacias do RS</span></div>
      <div class="stat"><strong>175</strong><span>UPG / UBH publicadas</span></div>""",
    )
    # Simpler: rebuild stats section cleanly in post-process
    (OUT / "mapa_hierarquia_rs.html").write_text(html, encoding="utf-8")


def write_index_patch() -> None:
    """Refresh study index from current JSON so hierarchy is visible on the main page."""
    path = OUT / "estudo_bacia_latest.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    hier = data.get("hierarquia_rs") or {}
    known = "".join(f"<li>{x}</li>" for x in data.get("known_vs_unknown", {}).get("known", []))
    unknown = "".join(
        f"<li>{x}</li>" for x in data.get("known_vs_unknown", {}).get("unknown_or_unreconciled", [])
    )
    steps = "".join(f"<li>{x}</li>" for x in data.get("next_study_steps_only", []))
    ugs_html = "".join(
        f"<section class='ug'><h3>{ug['name']}</h3><ul>"
        + "".join(f"<li>{s}</li>" for s in ug["subbasins"])
        + "</ul></section>"
        for ug in data.get("official_units_of_management", {}).get("ugs", [])
    )
    corr = (hier.get("correction") or {}).get("right_reading") or (
        "32 e so o nivel de enquadramento; ha UPG, ottobacias e outras bacias do RS a considerar."
    )
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Estudo da bacia Taquari-Antas</title>
  <style>
    :root {{ --ink:#1a303f; --muted:#5d7380; --line:#d7e4e8; --accent:#0a6f9c; --warn:#9a5b12; --bad:#a33b35; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 "Source Sans 3",Segoe UI,sans-serif;
      background:linear-gradient(165deg,#eef7f8,#fff9f2); }}
    main {{ max-width:1100px; margin:auto; padding:28px 18px 64px; }}
    header, section {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:22px; margin-bottom:14px; box-shadow:0 10px 26px #1a303f12; }}
    h1 {{ margin:0 0 8px; font:700 clamp(28px,4vw,44px)/1.08 "Fraunces",Georgia,serif; }}
    h2 {{ margin:0 0 10px; font-size:1.25rem; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .notice {{ border-left:5px solid var(--warn); background:#fff7e8; color:#6d4810; padding:12px 14px; border-radius:10px; }}
    .bad {{ border-left-color:var(--bad); background:#fff1ef; color:#7a2d28; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
    .stat {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f7fcfc; }}
    .stat strong {{ display:block; font-size:26px; color:var(--accent); }}
    .ugs {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
    .ug {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#f8fcfc; }}
    .ug h3 {{ margin:0 0 8px; font-size:1rem; }}
    .ug ul {{ margin:0; padding-left:18px; color:#27495a; }}
    a {{ color:#056999; font-weight:700; }}
    @media (max-width:800px) {{ .grid,.ugs {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Estudo · antes do HEC</div>
    <h1>A Taquari-Antas e feita de varias bacias</h1>
    <p>Gerado em {data.get('generated_at_utc')}</p>
    <div class="notice"><strong>Regra:</strong> {data.get('discipline_rule')}</div>
  </header>

  <section>
    <div class="grid">
      <div class="stat"><strong>25</strong><span>bacias oficiais no RS</span></div>
      <div class="stat"><strong>175</strong><span>UPG / UBH publicadas</span></div>
      <div class="stat"><strong>32</strong><span>enquadramentos G040</span></div>
      <div class="stat"><strong>~33k</strong><span>ottobacias arvore 786</span></div>
    </div>
    <div class="notice bad" style="margin-top:12px"><strong>Correcao:</strong> {corr}</div>
    <p><a href="mapa_hierarquia_rs.html">Mapa das 25 bacias + influencia</a> ·
       <a href="mapa_subbacias.html">7 UPG + fozes</a> ·
       <a href="hierarquia_rs_latest.json">JSON hierarquia</a></p>
  </section>

  <section>
    <h2>Distincao critica</h2>
    <div class="notice bad"><strong>Nao confundir:</strong> {(data.get('critical_distinction') or {}).get('finding')}</div>
    <p>Exutorio da bacia oficial: <strong>Rio Jacui</strong>, nao Mucum. So G040 escorre para o Taquari-Antas; vizinhas nao sao afluentes.</p>
  </section>

  <section>
    <h2>7 UPG e 32 sub-bacias de enquadramento (G040)</h2>
    <div class="ugs">{ugs_html}</div>
    <p class="muted" style="color:#5d7380;font-size:13px">As 32 sao unidades de qualidade da agua (Q040). As mini-unidades hidrologicas sao as ~33 mil ottobacias 786.</p>
  </section>

  <section>
    <h2>O que ja sabemos / o que nao</h2>
    <h3>Sabemos</h3>
    <ul>{known}</ul>
    <h3>Ainda nao fechado</h3>
    <ul>{unknown}</ul>
  </section>

  <section>
    <h2>Proximos passos de ESTUDO (sem HEC)</h2>
    <ul>{steps}</ul>
    <p><a href="estudo_bacia_latest.json">JSON auditavel</a> ·
       <a href="https://www.sema.rs.gov.br/g040-bh-taquari-antas">SEMA G040</a> ·
       <a href="https://www.sema.rs.gov.br/bacias-hidrograficas/">25 bacias RS</a></p>
  </section>
</main>
</body>
</html>
"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / "README.md").write_text(
        """# Estudo da bacia Taquari-Antas

**Estudo, nao modelo.** Nao sao so 32 sub-bacias.

## Hierarquia

1. 3 regioes hidrograficas
2. 25 bacias (G040 = Taquari-Antas)
3. ~175 UPG (zip SEMA "UBH" = este nivel)
4. 32 enquadramentos em G040 (qualidade da agua)
5. ~33 mil ottobacias BHO6 na arvore `786` (mini-unidades)
6. mini-bacias SIOUT/ArcHydro (outorga) — distintas do zip UBH

Leia `mapa_hierarquia_rs.html` e `hierarquia_rs_latest.json`.

```bash
python scripts/build_estudo_bacia_taquari_antas.py
python scripts/build_estudo_bacia_subbacias_fozes.py
python scripts/build_estudo_hierarquia_rs_bacias.py
```
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
