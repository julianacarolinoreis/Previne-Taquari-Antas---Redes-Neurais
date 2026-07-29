#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Gera a camada "visão fina" (MDT de drone, ~0,5 m) para Muçum e Santa Tereza.

DECISÃO (2026-07-29): o drone cobre só uma fração pequena da área que o
HAND processa hoje com ANADEM (~3% em Muçum, ~1,7% em Santa Tereza), e há
um offset vertical sistemático de ~6,7-6,9 m entre drone e ANADEM nas duas
cidades (mediana, checado por 2 métodos de reamostragem) — assinatura
típica de datum vertical diferente (elipsoidal x ortométrico), ainda não
resolvido. Por isso a mancha ANADEM de hoje (larga, calibrada com o
bankfull_cm oficial) NÃO é substituída nem mosaicada: o drone entra como
uma camada extra, "visão fina", limitada à própria extensão pequena dele.

Usa o MESMO algoritmo de HAND do gerar_mancha_mucum.py (semente = mínimo
global do raster, talvegue = filtro de mínimo local + corte de percentil,
HAND = cota - cota do talvegue mais próximo via distance transform),
aplicado ao TIF de drone, e escreve o payload num JSON À PARTE
(assets/data/<cidade>_inundacao/hand_zoom_<cidade>.json), buscado via
fetch() só quando o usuário liga o toggle "visão fina" no site — não
embutido no HTML. Motivo: o PNG fino em base64 pesa >1&nbsp;MB por
cidade; embutir infla o carregamento inicial de uma página de ALERTA DE
ENCHENTE pra todo mundo, mesmo quem nunca liga o toggle. Não mexe no
<script id="hand-data"> existente (ANADEM, inalterado).

Também recorta o ANADEM na mesma extensão do drone e roda o mesmo
algoritmo nesse recorte, só para IMPRIMIR a comparação de área alagada
(30 m vs 0,5 m) nos mesmos níveis — não entra no payload do site.

MÉTODO DE TALVEGUE NA GRADE FINA (importante)
-----------------------------------------------
A primeira tentativa foi rodar o MESMO algoritmo do gerar_mancha_mucum.py
(mínimo local + corte de percentil) direto na grade fina de 0,5 m — não
funcionou: numa janela de 9 células (~4,5 m em vez de ~270 m do ANADEM
30 m), o filtro de mínimo local vira ruído (encontra qualquer sarjeta,
pátio ou vala como "mínimo local"), e deu ou um talvegue gigante e
desconexo (Muçum: 13% dos pixels) ou praticamente vazio (Santa Tereza:
12 células, mancha ~0 ha em qualquer nível). Corrigido ancorando o
talvegue fino no talvegue já calculado na grade ANADEM (que tem escala
compatível com a largura real do vale): reprojeta a máscara booleana do
talvegue ANADEM pra grade fina (nearest), e dentro dessa faixa refina
pegando as células mais baixas (percentil 10 dos valores DENTRO da
faixa, conectadas à semente). Resultado: curvas nível→área monotônicas e
plausíveis nas duas cidades — ver saída impressa ao rodar.

Uso: python codigo_python/02_mdt_hand_mancha/gerar_mancha_zoom.py [mucum|santa_tereza]
     (sem argumento roda as duas cidades)
"""
import os, json, base64, io, sys
import numpy as np
import rasterio
import rasterio.windows
import rasterio.warp
from scipy import ndimage
from math import cos, radians
from PIL import Image

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NIVEL_MAX_M = 25.0

CIDADES = {
    "mucum": {
        "drone": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_drone_1m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_anadem_30m.tif"),
        "out_json": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "hand_zoom_mucum.json"),
        "estacao_alvo": "86510000",
        "estacao_montante": "86472600",
    },
    "santa_tereza": {
        "drone": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_drone_1m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_anadem_30m.tif"),
        "out_json": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "hand_zoom_santa_tereza.json"),
        "estacao_alvo": "86472600",
        "estacao_montante": None,
    },
}


def talvegue_coarse(dem, min_size=9):
    """Talvegue no padrão do gerar_mancha_mucum.py (janela calibrada p/ grade ~30 m)."""
    sr, sc = np.unravel_index(int(np.argmin(dem)), dem.shape)
    mn = ndimage.minimum_filter(dem, size=min_size)
    corte_vale = np.percentile(dem, 15)
    thal = (dem <= mn + 1.0) & (dem <= corte_vale)
    lbl, _ = ndimage.label(thal)
    return lbl == lbl[sr, sc]


def calcula_hand_fino(dem, W, S, E, N, nd, thal_coarse, transform_coarse, crs_coarse, crs_fino, pct=10):
    """HAND na grade fina, com talvegue ANCORADO no talvegue já calculado na
    grade ANADEM (reprojetado pra grade fina) e refinado localmente — ver
    docstring do módulo pra motivo (mínimo local puro não escala pra 0,5 m)."""
    ny, nx = dem.shape
    a = (E - W) / nx
    e = (S - N) / ny
    lat0 = (S + N) / 2
    cell_ha = (abs(a) * 111320) * (abs(e) * 111320 * cos(radians(lat0))) / 1e4

    if nd is not None:
        dem = np.where(dem == nd, np.nan, dem)
    if np.isnan(dem).any():
        dem = np.where(np.isnan(dem), np.nanmax(dem), dem)

    transform_fino = rasterio.transform.from_bounds(W, S, E, N, nx, ny)
    band = np.zeros((ny, nx), dtype=np.uint8)
    rasterio.warp.reproject(
        source=thal_coarse.astype(np.uint8), destination=band,
        src_transform=transform_coarse, src_crs=crs_coarse,
        dst_transform=transform_fino, dst_crs=crs_fino,
        resampling=rasterio.warp.Resampling.nearest,
    )
    band = band.astype(bool)
    if band.sum() == 0:
        raise SystemExit("ERRO: talvegue ANADEM reprojetado não cai dentro da extensão do drone")

    corte_fino = np.percentile(dem[band], pct)
    thal_cand = band & (dem <= corte_fino)
    sr, sc = np.unravel_index(int(np.argmin(dem)), dem.shape)
    lbl, _ = ndimage.label(thal_cand)
    lbl_seed = lbl[sr, sc]
    if lbl_seed == 0:
        # semente (mínimo global do tile) não caiu no candidato -> ancora no ponto mais baixo da própria faixa
        idx = np.argmin(np.where(band, dem, np.inf))
        sr, sc = np.unravel_index(int(idx), dem.shape)
        lbl_seed = lbl[sr, sc]
    thal = (lbl == lbl_seed) if lbl_seed != 0 else thal_cand

    _, (ri, rj) = ndimage.distance_transform_edt(~thal, return_indices=True)
    hand = dem - dem[ri, rj]
    hand[hand < 0] = 0

    def flood_ha(h):
        l, _ = ndimage.label(hand <= h)
        keep = set(np.unique(l[thal])) - {0}
        return int(np.isin(l, list(keep)).sum()) * cell_ha

    return dict(dem=dem, hand=hand, thal=thal, cell_ha=cell_ha, flood_ha=flood_ha,
                nx=nx, ny=ny, W=W, S=S, E=E, N=N, sr=sr, sc=sc)


def le_tif(path):
    with rasterio.open(path) as ds:
        dem = ds.read(1).astype("float64")
        b = ds.bounds
        nd = ds.nodata
    return dem, b.left, b.bottom, b.right, b.top, nd


def le_recorte(path, W, S, E, N):
    with rasterio.open(path) as ds:
        win = rasterio.windows.from_bounds(W, S, E, N, ds.transform).round_offsets().round_lengths()
        dem = ds.read(1, window=win).astype("float64")
        nd = ds.nodata
        t = rasterio.windows.transform(win, ds.transform)
    ny, nx = dem.shape
    Wc, Nc = t.c, t.f
    Ec, Sc = Wc + nx * t.a, Nc + ny * t.e
    return dem, Wc, Sc, Ec, Nc, nd


def compara(cidade, res_drone, res_anadem_full):
    dem_a, Wa, Sa, Ea, Na, nda = le_recorte(CIDADES[cidade]["anadem"], res_drone["W"], res_drone["S"], res_drone["E"], res_drone["N"])
    ny, nx = dem_a.shape
    if ny < 3 or nx < 3:
        print(f"  [ANADEM recortado pequeno demais: {ny}x{nx} px — pulando comparação]")
        return
    if nda is not None:
        dem_a = np.where(dem_a == nda, np.nan, dem_a)
    if np.isnan(dem_a).any():
        dem_a = np.where(np.isnan(dem_a), np.nanmax(dem_a), dem_a)
    a = (Ea - Wa) / nx
    e = (Sa - Na) / ny
    lat0 = (Sa + Na) / 2
    cell_ha_a = (abs(a) * 111320) * (abs(e) * 111320 * cos(radians(lat0))) / 1e4
    thal_a_local = talvegue_coarse(dem_a, min_size=3)
    _, (ri, rj) = ndimage.distance_transform_edt(~thal_a_local, return_indices=True)
    hand_a = dem_a - dem_a[ri, rj]
    hand_a[hand_a < 0] = 0

    def flood_ha_a(h):
        l, _ = ndimage.label(hand_a <= h)
        keep = set(np.unique(l[thal_a_local])) - {0}
        return int(np.isin(l, list(keep)).sum()) * cell_ha_a

    print(f"  ANADEM recorte: {nx}x{ny} px, {cell_ha_a:.3f} ha/cel")
    print(f"  DRONE         : {res_drone['nx']}x{res_drone['ny']} px, {res_drone['cell_ha']*10000:.2f} m²/cel")
    print("  nível(m) | área ANADEM 30m (ha) | área drone 0,5m (ha) | razão")
    for h in (1, 2, 3, 4, 6, 8, 10):
        aa = flood_ha_a(h)
        ad = res_drone["flood_ha"](h)
        raz = (ad / aa) if aa > 0 else float("nan")
        print(f"    {h:2d}    | {aa:10.2f}            | {ad:10.2f}            | {raz:.2f}")


def gera(cidade):
    cfg = CIDADES[cidade]
    print(f"=== {cidade} ===")
    dem_full, Wf, Sf, Ef, Nf, ndf = le_tif(cfg["anadem"])
    dem_full_c = np.where(dem_full == ndf, np.nan, dem_full) if ndf is not None else dem_full
    if np.isnan(dem_full_c).any():
        dem_full_c = np.where(np.isnan(dem_full_c), np.nanmax(dem_full_c), dem_full_c)
    thal_full = talvegue_coarse(dem_full_c, min_size=9)
    with rasterio.open(cfg["anadem"]) as ds:
        transform_coarse, crs_coarse = ds.transform, ds.crs

    dem, W, S, E, N, nd = le_tif(cfg["drone"])
    with rasterio.open(cfg["drone"]) as ds:
        crs_fino = ds.crs
    res = calcula_hand_fino(dem, W, S, E, N, nd, thal_full, transform_coarse, crs_coarse, crs_fino, pct=10)
    print(f"drone {res['ny']}x{res['nx']} | bounds W{W:.5f} S{S:.5f} E{E:.5f} N{N:.5f} | cel {res['cell_ha']*10000:.2f} m²")
    print(f"elev {np.nanmin(res['dem']):.1f}-{np.nanmax(res['dem']):.1f} m | talvegue {int(res['thal'].sum())} cel"
          f" | cota talvegue {res['dem'][res['thal']].min():.1f}->{res['dem'][res['thal']].max():.1f}")
    print("nível(m) | área_ha (só na extensão do drone)")
    for h in (2, 4, 6, 8, 10, 13):
        print(f"   {h:2d}    | {res['flood_ha'](h):8.2f}")

    compara(cidade, res, None)

    dm = np.clip(np.round(res["hand"] * 10), 0, int(NIVEL_MAX_M * 10)).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(dm, mode="L").save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()

    payload = {
        "cols": res["nx"], "rows": res["ny"],
        "S": round(S, 6), "W": round(W, 6), "N": round(N, 6), "E": round(E, 6),
        "estacao_alvo": cfg["estacao_alvo"], "estacao_montante": cfg["estacao_montante"],
        "fonte": "MDT derivado de levantamento aerofotogramétrico (drone), ~0,5 m — visão fina de cobertura LIMITADA ao centro urbano; datum vertical não confirmado (offset mediano observado vs. ANADEM ~6,7-6,9 m); use como complemento visual, não substitui a mancha ANADEM 30 m (calibrada) para leitura oficial.",
        "hand_png_b64": b64,
    }
    out_json = cfg["out_json"]
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tam_kb = os.path.getsize(out_json) / 1024
    print(f"payload zoom escrito em {os.path.relpath(out_json, RAIZ)} ({tam_kb:.0f} KB, png {len(buf.getvalue())} bytes) — buscado via fetch() sob demanda, não embutido no HTML")
    print()


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else None
    for cidade in ([alvo] if alvo else CIDADES.keys()):
        gera(cidade)
