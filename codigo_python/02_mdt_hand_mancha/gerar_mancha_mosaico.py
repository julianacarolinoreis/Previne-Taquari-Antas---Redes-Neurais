#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Gera a mancha de inundação (HAND) a partir do MOSAICO fino de 2 m — drone
corrigido de datum (geoide IBGE) no centro + ANADEM reamostrado nas bordas,
ver gerar_mosaico_mdt.py — e injeta no <script id="hand-data"> das duas
páginas (mucum_inundacao.html / santa_tereza_inundacao.html), SUBSTITUINDO
o payload ANADEM 30 m puro que estava lá. Essa é a troca de fonte pedida
originalmente, agora possível porque o datum foi corrigido (offset residual
~0,2 m, ver corrigir_datum_drone.py) e a cobertura parcial do drone foi
resolvida via mosaico (não encolhe a área processada).

MÉTODO DO TALVEGUE (por que não é o algoritmo simples de sempre)
------------------------------------------------------------------
Testado e descartado: rodar direto no mosaico de 2 m o mesmo algoritmo do
gerar_mancha_mucum.py (mínimo local + corte de percentil, janela física
escalada pra ~270 m) usando como semente o mínimo GLOBAL do raster. Resultado:
o mínimo global (dentro da área do drone, mais precisa) fica isolado — um
bolsão de ~40 células desconectado da rede de drenagem principal — porque
em resolução fina a costura mosaico/blend cria uma pequena barreira que o
filtro de mínimo local não atravessa, não importa a tolerância. Um "maior
componente conectado" *sem* âncora escolhe a rede principal, mas com cota
mínima da ANTIGA cota do ANADEM (não ganha a precisão do drone).

Solução: ancora no talvegue já validado do ANADEM (mesmo algoritmo do
gerar_mancha_mucum.py, na grade 30 m original — sempre conectado, é o que
já está em produção) reprojetado pra grade do mosaico (nearest), e dentro
dessa faixa pega o maior componente conectado abaixo do percentil 50 local
— isso preserva a topologia da rede (vem do ANADEM, testado) e ainda assim
capta a cota mais precisa do drone onde ele cobre.

RESSALVA (Santa Tereza): o diagnóstico atual do MDT de drone ortométrico
encontra mínimo de ~27,1 m, ainda abaixo da faixa do talvegue ANADEM ali
(49–72 m). A regeneração do mosaico já mascara as 7 células abaixo de 40 m;
o refinamento visual adicional é gerado separadamente por
refinar_mdt_santa_tereza.py e não altera o HAND publicado.

Uso: python codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py [mucum|santa_tereza]
"""
import os
import re
import sys
import json
import base64
import io
import numpy as np
import rasterio
import rasterio.warp
from scipy import ndimage
from math import cos, radians
from PIL import Image

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NIVEL_MAX_M = 25.0
NIVEIS_COMPARACAO = (2, 4, 6, 8, 10, 13)

CIDADES = {
    "mucum": {
        "mosaico": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_mosaico_2m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_anadem_30m.tif"),
        "pagina": os.path.join(RAIZ, "mucum_inundacao.html"),
    },
    "santa_tereza": {
        "mosaico": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_mosaico_2m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_anadem_30m.tif"),
        "pagina": os.path.join(RAIZ, "santa_tereza_inundacao.html"),
    },
}


def le(path):
    with rasterio.open(path) as ds:
        dem = ds.read(1).astype("float64")
        nd = ds.nodata
        transform = ds.transform
        crs = ds.crs
        b = ds.bounds
    dem = np.where(dem == nd, np.nan, dem) if nd is not None else dem
    if np.isnan(dem).any():
        dem = np.where(np.isnan(dem), np.nanmax(dem), dem)
    return dem, transform, crs, b


def talvegue_anadem(dem_a):
    sr, sc = np.unravel_index(int(np.argmin(dem_a)), dem_a.shape)
    mn = ndimage.minimum_filter(dem_a, size=9)
    corte = np.percentile(dem_a, 15)
    thal = (dem_a <= mn + 1.0) & (dem_a <= corte)
    lbl, _ = ndimage.label(thal)
    return lbl == lbl[sr, sc]


def talvegue_mosaico(dem, transform_f, crs_f, thal_a, transform_a, crs_a, pct=50):
    ny, nx = dem.shape
    band = np.zeros((ny, nx), dtype=np.uint8)
    rasterio.warp.reproject(
        source=thal_a.astype(np.uint8), destination=band,
        src_transform=transform_a, src_crs=crs_a,
        dst_transform=transform_f, dst_crs=crs_f,
        resampling=rasterio.warp.Resampling.nearest,
    )
    band = band.astype(bool)
    corte_fino = np.percentile(dem[band], pct)
    cand = band & (dem <= corte_fino)
    lbl, _ = ndimage.label(cand)
    sizes = np.bincount(lbl.ravel())
    sizes[0] = 0
    return lbl == sizes.argmax()


def processa(cidade):
    cfg = CIDADES[cidade]
    print(f"=== {cidade} ===")
    dem_a, transform_a, crs_a, _ = le(cfg["anadem"])
    thal_a = talvegue_anadem(dem_a)
    print(f"ANADEM (referência p/ ancorar): talvegue {int(thal_a.sum())} cel | cota {dem_a[thal_a].min():.1f}->{dem_a[thal_a].max():.1f}")

    dem, transform_f, crs_f, b = le(cfg["mosaico"])
    ny, nx = dem.shape
    W, S, E, N = b.left, b.bottom, b.right, b.top
    a = (E - W) / nx
    e = (S - N) / ny
    lat0 = (S + N) / 2
    cell_ha = (abs(a) * 111320) * (abs(e) * 111320 * cos(radians(lat0))) / 1e4

    thal = talvegue_mosaico(dem, transform_f, crs_f, thal_a, transform_a, crs_a)
    print(f"mosaico 2m: {ny}x{nx} px | talvegue {int(thal.sum())} cel | cota {dem[thal].min():.1f}->{dem[thal].max():.1f}")

    _, (ri, rj) = ndimage.distance_transform_edt(~thal, return_indices=True)
    hand = dem - dem[ri, rj]
    hand[hand < 0] = 0

    def flood_ha(h):
        l, _ = ndimage.label(hand <= h)
        keep = set(np.unique(l[thal])) - {0}
        return int(np.isin(l, list(keep)).sum()) * cell_ha

    # curva de comparação: mosaico 2m vs ANADEM 30m original (mesmo algoritmo de sempre)
    with rasterio.open(cfg["anadem"]) as _ds:
        b_a = _ds.bounds
    lat0_a = (b_a.bottom + b_a.top) / 2
    cell_ha_a = (abs(transform_a.a) * 111320) * (abs(transform_a.e) * 111320 * cos(radians(lat0_a))) / 1e4

    _, (ria, rja) = ndimage.distance_transform_edt(~thal_a, return_indices=True)
    hand_a = dem_a - dem_a[ria, rja]
    hand_a[hand_a < 0] = 0

    def flood_ha_a(h):
        l, _ = ndimage.label(hand_a <= h)
        keep = set(np.unique(l[thal_a])) - {0}
        return int(np.isin(l, list(keep)).sum()) * cell_ha_a

    print("nível(m) | mosaico 2m (ha) | ANADEM 30m (ha) | razão")
    comparacao = {}
    for h in NIVEIS_COMPARACAO:
        vm = flood_ha(h)
        va = flood_ha_a(h)
        comparacao[h] = (vm, va)
        print(f"   {h:2d}    | {vm:10.2f}      | {va:10.2f}     | {vm/va if va>0 else float('nan'):.2f}")

    dm = np.clip(np.round(hand * 10), 0, int(NIVEL_MAX_M * 10)).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(dm, mode="L").save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return dict(cols=nx, rows=ny, S=round(S, 6), W=round(W, 6), N=round(N, 6), E=round(E, 6),
                hand_png_b64=b64, comparacao=comparacao)


def injeta_mucum(payload_extra):
    pagina = CIDADES["mucum"]["pagina"]
    html = open(pagina, encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    old = json.loads(m.group(1))
    novo_payload = {
        "cols": payload_extra["cols"], "rows": payload_extra["rows"],
        "S": payload_extra["S"], "W": payload_extra["W"], "N": payload_extra["N"], "E": payload_extra["E"],
        "estacao_alvo": old.get("estacao_alvo", "86510000"),
        "estacao_montante": old.get("estacao_montante", "86472600"),
        "bankfull_cm": old.get("bankfull_cm", 500),
        "fonte": "Mosaico 2 m: drone (0,5 m, corrigido de datum via geoide IBGE hgeoHNOR2020/MAPGEO2015, offset residual ~0,24 m) no centro urbano + ANADEM 30 m reamostrado nas bordas — ver codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py",
        "hand_png_b64": payload_extra["hand_png_b64"],
    }
    novo_json = json.dumps(novo_payload, ensure_ascii=False)
    html2, n = re.subn(
        r'<script id="hand-data" type="application/json">.*?</script>',
        f'<script id="hand-data" type="application/json">{novo_json}</script>',
        html, count=1, flags=re.DOTALL,
    )
    assert n == 1
    open(pagina, "w", encoding="utf-8").write(html2)
    print(f"payload injetado em {os.path.basename(pagina)} ({len(novo_json)} chars)")


def injeta_santa_tereza(payload_extra):
    pagina = CIDADES["santa_tereza"]["pagina"]
    html = open(pagina, encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    old = json.loads(m.group(1))
    novo_payload = {
        "cols": payload_extra["cols"], "rows": payload_extra["rows"],
        "S": payload_extra["S"], "W": payload_extra["W"], "N": payload_extra["N"], "E": payload_extra["E"],
        "station": old.get("station"), "ponte": old.get("ponte"),
        "fonte": "Mosaico 2 m: drone (0,5 m, corrigido de datum via geoide IBGE hgeoHNOR2020/MAPGEO2015, offset residual ~0,20 m) no centro urbano + ANADEM 30 m reamostrado nas bordas — ver codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py. Diagnóstico atual: mínimo do drone ortométrico ~27 m; 7 células abaixo de 40 m são mascaradas na regeneração. O MDT refinado visual é separado e não altera o HAND.",
        "hand_png_b64": payload_extra["hand_png_b64"],
    }
    novo_json = json.dumps(novo_payload, ensure_ascii=False)
    html2, n = re.subn(
        r'<script id="hand-data" type="application/json">.*?</script>',
        f'<script id="hand-data" type="application/json">{novo_json}</script>',
        html, count=1, flags=re.DOTALL,
    )
    assert n == 1
    open(pagina, "w", encoding="utf-8").write(html2)
    print(f"payload injetado em {os.path.basename(pagina)} ({len(novo_json)} chars)")


def main():
    alvo = sys.argv[1] if len(sys.argv) > 1 else None
    injetores = {"mucum": injeta_mucum, "santa_tereza": injeta_santa_tereza}
    for cidade in ([alvo] if alvo else CIDADES.keys()):
        payload_extra = processa(cidade)
        injetores[cidade](payload_extra)
        print()


if __name__ == "__main__":
    main()
