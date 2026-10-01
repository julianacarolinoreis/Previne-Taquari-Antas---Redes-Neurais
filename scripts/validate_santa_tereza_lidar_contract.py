#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falha o deploy se Santa Tereza voltar a usar terreno/mancha legados.

Contrato atual:
- HAND e barreiras: LiDAR bruto CLIP_MOSAICO_LIDAR_RS.tif;
- FILL/FLOWDIR/FLOWACC: somente roteamento;
- régua 1,60 m = HAND 0;
- payload web ~5 m e MDT same-source ~10 m;
- páginas atual e histórica com o mesmo payload HAND;
- pipelines drone+ANADEM proibidos para Santa Tereza.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LIVE = ROOT / "santa_tereza_previsao_inundacao.html"
HIST = ROOT / "santa_tereza_inundacao.html"
DIAG = ROOT / "assets/data/santa_tereza_inundacao/hand_lidar_5m_diagnostic.json"
ELEV = ROOT / "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_lidar_10m.json"
REFRESH = ROOT / ".github/workflows/refresh-spatial-30m.yml"
LEGACY_MOSAIC = ROOT / "codigo_python/02_mdt_hand_mancha/gerar_mosaico_mdt.py"
LEGACY_HAND = ROOT / "codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py"
LEGACY_CONTOURS = ROOT / "codigo_python/02_mdt_hand_mancha/gerar_contornos_vetoriais.py"
ROUTE = ROOT / "codigo_python/09_rota_fuga/gerar_rota_fuga_santa_tereza.py"
UNIFIED = ROOT / "pesquisas/replay-hidrologico-espacial.html"
LEGACY_REFINER = ROOT / "codigo_python/02_mdt_hand_mancha/refinar_mdt_santa_tereza.py"
PUBLIC_SURFACES = (
    ROOT / "pesquisas/santa-tereza-mapa-impacto.html",
    ROOT / "santa_tereza_rota_fuga.html",
    ROOT / "santa_tereza_rota_fuga_cenario.html",
    ROOT / "santa_tereza_rota_fuga_ruas_cenario.html",
    ROOT / "pesquisas/santa-tereza-rota-fuga-ruas-cenario.html",
)

EXPECTED_ELEVATION = "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_lidar_10m.json"
FORBIDDEN_ACTIVE = (
    "mdt_santa_tereza_mosaico_2m.tif",
    "altitude_terreno_10m_refinado.json",
    "mdt_santa_tereza_10m_refinado_visual.png",
    "mdt_santa_tereza_anadem_30m.tif",
    "mdt_santa_tereza_drone_1m_ortho.tif",
)


def fail(msg: str) -> None:
    raise SystemExit("ERRO contrato LiDAR Santa Tereza: " + msg)


def read(path: Path) -> str:
    if not path.exists():
        fail(f"arquivo ausente: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def payload(page: Path) -> tuple[str, dict]:
    html = read(page)
    m = re.search(
        r'<script id="hand-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if not m:
        fail(f"hand-data ausente em {page.name}")
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        fail(f"hand-data inválido em {page.name}: {exc}")
    return html, data


live_html, live = payload(LIVE)
hist_html, hist = payload(HIST)

for page, html, data in ((LIVE, live_html, live), (HIST, hist_html, hist)):
    source = str(data.get("fonte") or "")
    if "CLIP_MOSAICO_LIDAR_RS.tif" not in source:
        fail(f"{page.name} não confirma o LiDAR bruto na fonte do HAND")
    if "FILL/FLOWDIR/FLOWACC usados somente para roteamento" not in source:
        fail(f"{page.name} não limita FILL/FLOWDIR/FLOWACC ao roteamento")
    if int(data.get("hand_zero_cm", -1)) != 160:
        fail(f"{page.name}: hand_zero_cm deve ser 160")
    if float(data.get("max_hand_m", -1)) != 25.0:
        fail(f"{page.name}: max_hand_m deve ser 25")
    if data.get("crs") != "EPSG:4326":
        fail(f"{page.name}: payload web deve estar em EPSG:4326")
    if EXPECTED_ELEVATION not in html:
        fail(f"{page.name} não usa MDT same-source LiDAR")
    for token in FORBIDDEN_ACTIVE:
        if token in html:
            fail(f"{page.name} voltou a referenciar ativo legado: {token}")

keys = ("cols", "rows", "S", "W", "N", "E", "hand_zero_cm", "max_hand_m", "fonte")
for key in keys:
    if live.get(key) != hist.get(key):
        fail(f"página ao vivo e histórica divergiram no campo {key}")

unified_html = read(UNIFIED)
for required in ("LiDAR bruto", "0–25 m", "HAND = max(0, régua − 1,60 m)"):
    if required not in unified_html:
        fail(f"sala/replay integrado não confirma contrato atual de Santa Tereza: {required}")
for token in FORBIDDEN_ACTIVE:
    if token in unified_html:
        fail(f"sala/replay integrado voltou a referenciar ativo legado: {token}")

for surface in PUBLIC_SURFACES:
    html = read(surface)
    for token in FORBIDDEN_ACTIVE + (
        "mancha_preliminar_santa_tereza",
        "cenario_dem_na9765_santa_tereza",
    ):
        if token in html:
            fail(
                f"superfície pública de Santa Tereza voltou a referenciar legado: "
                f"{surface.relative_to(ROOT)} -> {token}"
            )

diag = json.loads(read(DIAG))
if str(diag.get("terreno_bruto_lidar", "")).replace("\\", "/").split("/")[-1] != "CLIP_MOSAICO_LIDAR_RS.tif":
    fail("diagnóstico não confirma CLIP_MOSAICO_LIDAR_RS.tif como terreno")
if diag.get("fill_usado_como_superficie_inundacao") is not False:
    fail("FILL não pode ser superfície de inundação")
if diag.get("terrain_modified_by_water_filter") is not False:
    fail("filtro de conectividade não pode alterar o terreno")
if int(diag.get("hand_zero_cm", -1)) != 160:
    fail("diagnóstico: hand_zero_cm deve ser 160")
if float(diag.get("contour_max_m", -1)) < 25.0:
    fail("diagnóstico: contornos não chegam a 25 m")
if int(diag.get("contornos_features", 0)) < 251:
    fail("diagnóstico: menos de 251 contornos")
if float(diag.get("drained_fraction", 0)) < 0.90:
    fail("diagnóstico: drenagem ao rio principal abaixo de 90%")
if int(diag.get("unresolved_cells", 1)) != 0:
    fail("diagnóstico: existem células D8 não resolvidas")
if "raw-LiDAR" not in str(diag.get("hydraulic_hand_method", "")):
    fail("diagnóstico: método hidráulico não confirma barreira no LiDAR bruto")

elev = json.loads(read(ELEV))
if elev.get("fonte") != "CLIP_MOSAICO_LIDAR_RS.tif":
    fail("MDT web não vem do LiDAR bruto")
if elev.get("same_source_as_hand") is not True:
    fail("MDT web não declara same_source_as_hand=true")
if elev.get("terrain_surface") != "raw_lidar_unfilled":
    fail("MDT web não preserva a superfície LiDAR bruta")
if elev.get("crs") != "EPSG:4326":
    fail("MDT web deve estar em EPSG:4326")

refresh = read(REFRESH)
if re.search(r"santa_tereza|santa-tereza", refresh, flags=re.I):
    fail("workflow espacial legado de 30 m voltou a tocar Santa Tereza")

mosaic = read(LEGACY_MOSAIC)
if 'def monta(cidade):\n    if cidade == "santa_tereza":' not in mosaic:
    fail("gerador de mosaico legado não está bloqueado em nível de função")

legacy_hand = read(LEGACY_HAND)
if 'def processa(cidade):\n    if cidade == "santa_tereza":' not in legacy_hand:
    fail("gerador HAND legado não está bloqueado em nível de função")
if 'def injeta_santa_tereza(payload_extra):\n    raise RuntimeError' not in legacy_hand:
    fail("injetor HAND legado de Santa Tereza não está bloqueado")

legacy_contours = read(LEGACY_CONTOURS)
if 'def gera(cidade):\n    if cidade == "santa_tereza":' not in legacy_contours:
    fail("gerador de contornos legado não está bloqueado em nível de função")

route = read(ROUTE)
if 'PAGINA_HAND = os.path.join(RAIZ, "santa_tereza_previsao_inundacao.html")' not in route:
    fail("rota de fuga não lê a página LiDAR autoritativa")

legacy_refiner = read(LEGACY_REFINER)
if 'LEGACY_AUDIT_FLAG = "--legacy-audit-only"' not in legacy_refiner:
    fail("refinador drone+ANADEM legado não exige flag explícita de auditoria")
if "Execução bloqueada: este refinamento drone + ANADEM é legado" not in legacy_refiner:
    fail("refinador drone+ANADEM legado não está bloqueado por padrão")

print(
    "OK contrato LiDAR Santa Tereza: "
    f"{live['cols']}x{live['rows']}, HAND0={live['hand_zero_cm']} cm, "
    f"contornos={diag['contornos_features']}, drenagem={diag['drained_fraction']:.2%}"
)
