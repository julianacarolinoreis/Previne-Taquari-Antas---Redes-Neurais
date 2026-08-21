"""Build small, auditable reference layers for the vulnerability map.

The page is static, so large external datasets are not copied into the web
bundle.  This script snapshots the municipal resilience semaphores and the
Open Buildings v3 S2-cell catalogue; road features remain a lazy DAER REST
query in the browser.  Every generated file carries its source URL and the
retrieval timestamp.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "data" / "vulnerabilidade"
OUT = DATA / "referencias"
MUNICIPIOS = DATA / "municipios.geojson"
OBS_BASE = "https://plancon.blob.core.windows.net/indicadores"
OBS_PAGE = "https://observatoriodaresiliencia.org/indicadores/"
OPEN_TILES = "https://openbuildings-public-dot-gweb-research.uw.r.appspot.com/public/tiles.geojson"
OPEN_THRESHOLDS = "https://storage.googleapis.com/open-buildings-data/v3/score_thresholds_s2_level_4.csv"


def get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "PREVINE-reference-builder/1.0"})
    with urlopen(req, timeout=90) as r:
        return r.read()


def norm(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(c for c in raw if not unicodedata.combining(c)).replace("’", "'").strip()


def safe_number(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def load_observatorio(municipios):
    by_name: dict[str, dict] = {}
    for i in range(1, 8):
        raw = get(f"{OBS_BASE}/P{i}.csv").decode("utf-8-sig")
        for row in csv.DictReader(io.StringIO(raw)):
            by_name.setdefault(norm(row.get("municipio")), {})[f"P{i}"] = row

    out = []
    for feature in municipios.get("features", []):
        p = feature.get("properties", {})
        name = p.get("nome", "")
        rows = by_name.get(norm(name), {})
        statuses = {f"P{i}": (rows.get(f"P{i}", {}).get("valor") or "unknown").lower() for i in range(1, 8)}
        values = [s for s in statuses.values() if s in {"verde", "amarelo", "vermelho"}]
        score = {"verde": 3, "amarelo": 2, "vermelho": 1}
        avg = sum(score[s] for s in values) / len(values) if values else None
        # This is the exact consolidation rule used by the Observatorio V1;
        # keep the numeric average as an audit aid, never as a risk score.
        faixa = "verde" if avg is not None and avg >= 2.4 else "amarelo" if avg is not None and avg >= 1.7 else "vermelho" if avg is not None else None
        out.append({
            "cod_mun": p.get("cod_mun"),
            "nome": name,
            "irm_faixa": faixa,
            "irm_score_1a3": round(avg, 3) if avg is not None else None,
            "irm_score_0a100": round(avg / 3 * 100, 1) if avg is not None else None,
            "irm_n_indicadores": len(values),
            "irm_n_verde": values.count("verde"),
            "irm_n_amarelo": values.count("amarelo"),
            "irm_n_vermelho": values.count("vermelho"),
            "irm_status": "published" if values else "unknown",
            **{f"irm_{k}": v for k, v in statuses.items()},
        })
    return out, len(by_name)


def bbox_points(geometry):
    points = []

    def visit(node):
        if isinstance(node, list) and node and isinstance(node[0], (int, float)):
            points.append(node)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(geometry.get("coordinates", []))
    return points


def make_open_buildings(municipios):
    # Use the basin's municipal envelope as a conservative, reproducible
    # prefilter.  The tile catalogue is only a few hundred KB; footprints are
    # hundreds of MB/GB per S2 cell and are linked, not copied.
    all_points = [pt for f in municipios.get("features", []) for pt in bbox_points(f.get("geometry", {}))]
    minx = min(p[0] for p in all_points)
    maxx = max(p[0] for p in all_points)
    miny = min(p[1] for p in all_points)
    maxy = max(p[1] for p in all_points)
    tiles = json.loads(get(OPEN_TILES).decode("utf-8"))
    thresholds = {}
    for row in csv.DictReader(io.StringIO(get(OPEN_THRESHOLDS).decode("utf-8-sig"))):
        thresholds[str(row.get("s2_token"))] = row

    features = []
    for tile in tiles.get("features", []):
        pts = bbox_points(tile.get("geometry", {}))
        if not pts:
            continue
        tx = [p[0] for p in pts]
        ty = [p[1] for p in pts]
        if max(tx) < minx or min(tx) > maxx or max(ty) < miny or min(ty) > maxy:
            continue
        prop = tile.get("properties", {})
        tid = str(prop.get("tile_id", ""))
        score = thresholds.get(tid, {})
        merged = {
            "tile_id": tid,
            "tile_url": prop.get("tile_url"),
            "size_mb": safe_number(prop.get("size_mb")),
            "building_count": int(safe_number(score.get("building_count")) or 0),
            "building_count_90pct": int(safe_number(score.get("building_count_90%_precision")) or 0),
            "confidence_threshold_90pct": safe_number(score.get("confidence_threshold_90%_precision")),
            "source": "Google Research Open Buildings v3",
            "vintage_imagery": "2023 (inference on imagery through May 2023)",
        }
        features.append({"type": "Feature", "geometry": tile.get("geometry"), "properties": merged})
    return {"type": "FeatureCollection", "features": features}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    municipios = json.loads(MUNICIPIOS.read_text(encoding="utf-8"))
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    resiliencia, source_count = load_observatorio(municipios)
    (OUT / "resiliencia_municipios.json").write_text(json.dumps({
        "schema": 1,
        "gerado_em_utc": generated,
        "fonte": OBS_PAGE,
        "fonte_dados": f"{OBS_BASE}/P1.csv ... {OBS_BASE}/P7.csv",
        "metodo": "Consolidação V1 do Observatório: verde=3, amarelo=2, vermelho=1; média >=2,4 verde, >=1,7 amarelo; sem dado permanece unknown.",
        "observacoes": "IRM é municipal e não é risco. A cobertura é parcial; desconhecidos não entram na média.",
        "municipios_fonte": source_count,
        "features": resiliencia,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    buildings = make_open_buildings(municipios)
    for feature in buildings["features"]:
        feature["properties"]["gerado_em_utc"] = generated
    (OUT / "open_buildings_tiles.geojson").write_text(json.dumps(buildings, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(f"""# Camadas de referência do mapa\n\nGerado em `{generated}`.\n\n## Índice municipal de resiliência\n\n- Fonte: [Observatório da Resiliência RS]({OBS_PAGE}) / arquivos P1–P7 no Azure Blob (`{OBS_BASE}`).\n- Os sete semáforos são municipais; a consolidação segue a regra publicada no próprio visualizador.\n- `irm_score_0a100` é uma transformação auxiliar da média 1–3 para facilitar leitura; não é probabilidade, risco ou alerta.\n- Municípios sem os indicadores no snapshot permanecem `irm_status=unknown`; eles não foram convertidos em vermelho.\n\n## Estradas\n\nA interface consulta sob demanda a camada oficial **DAER/Rodovias_RS**, em EPSG:4674, via ArcGIS REST/GeoJSON. A consulta é limitada à janela visível e só é habilitada em zoom local para não sobrecarregar o serviço.\n\n## Open Buildings\n\n`open_buildings_tiles.geojson` é o catálogo das células S2 que cobrem a área do mapa. Ele traz contagem e URL de cada célula; os footprints individuais são baixados sob demanda pelo usuário a partir do Google Research (cada célula pode ter centenas de MB ou mais) e não são copiados para o GitHub Pages. O dataset v3 deriva polígonos de imagens de satélite e não identifica uso, endereço ou ocupação do prédio.\n\n## Óbitos\n\n`obitos.geojson` é uma referência espacial derivada do arquivo fornecido `OBITOS/obitos.shp`; o arquivo original e as limitações detalhadas ficam em `README_OBITOS.md`. O builder das referências não baixa nem substitui essa fonte local.\n""", encoding="utf-8")
    print(json.dumps({"status": "OK", "resiliencia": len(resiliencia), "fonte_municipios": source_count, "open_buildings_tiles": len(buildings["features"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
