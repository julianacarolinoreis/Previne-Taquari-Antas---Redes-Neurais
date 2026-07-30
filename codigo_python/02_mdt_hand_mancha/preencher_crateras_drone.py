#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Preenche "crateras de interpolação" nos MDTs brutos de drone (Muçum e Santa
Tereza) — pontos baixos circulares, de gradiente radial, típicos de buraco
na nuvem de pontos (água/sombra/oclusão) preenchido por IDW no processamento
fotogramétrico. Não são talvegue real (que é longo/fino, não circular).

ACHADO (confirmado por reprodução própria, 2026-07-30, a partir de um
relatório técnico repassado por outra sessão/agente — números batidos, não
herdados às cegas):
  Santa Tereza: 20 blobos classificados como cratera (de 32 candidatos com
    diff<-5m vs ANADEM e tamanho>=50px), o pior com erro de ~42m vs ANADEM
    (elevmin=12.5m onde ANADEM diz ~54,5m, em -51.73490,-29.17521).
  Muçum: 1 blobo cratera (elevmin=32.0m onde ANADEM diz ~38.5m, em
    -51.86229,-29.16395) — bate com o relatório externo (139x115px lá,
    45x37px aqui; a diferença de bbox é só o critério de limiar usado pra
    delimitar a mancha, o CENTRO e a ELEVAÇÃO MÍNIMA batem exatamente).

MÉTODO (shape-based, não fill_depressions() cego)
--------------------------------------------------
Um teste inicial com WhiteboxTools fill_depressions() no raster inteiro
"resolveu" as 68 crateras de Santa Tereza — mas junto elevou o mínimo global
de 12,5m pra 60,5m e alterou 8,8% de TODOS os pixels: ele encheu o VALE
INTEIRO (incluindo o talvegue real), porque num tile de drone recortado
(~2km) o rio muitas vezes não tem exutório de verdade até a borda do tile
numa cota baixa o bastante — o algoritmo trata o vale todo como uma única
depressão fechada. Exatamente o risco que foi pedido pra evitar
("preservando o talvegue real, que tem exutório, não é uma depressão
fechada"). Por isso o preenchimento aqui é CIRÚRGICO, só nos blobos
classificados como cratera:

1. Reprojeta ANADEM (30m, já validado/sem cratera) pra grade do drone.
2. diff = drone - anadem_reprojetado; suspeita = diff < -5m (profundidade
   sugerida).
3. Componentes conectados (scipy.ndimage.label) nos pixels suspeitos.
4. Pra cada blobo >=50px, calcula fill_ratio=área/(bbox_w*bbox_h) e
   aspect=max(w,h)/min(w,h). Cratera de IDW é ~círculo: fill alto (perto de
   π/4≈0,785) e aspect baixo (~1). Talvegue real é longo/fino: fill baixo,
   aspect alto. Corte empírico (validado nos 2 exemplos conhecidos de cada
   lado): fill>=0.55 E aspect<=2.2 -> CRATERA; senão, deixa intocado.
5. Só nos blobos CRATERA (identificados no limiar ESTRITO): CRESCE a máscara
   por histerese até um limiar FROUXO (ver correção abaixo), daí interpola o
   INTERIOR dessa máscara crescida via scipy.interpolate.griddata (linear,
   com nearest de fallback fora do casco convexo), usando um anel de pontos
   de controle bem afastado da máscara. O talvegue real e qualquer blobo
   "irregular" que não bateu o critério de forma ficam byte-a-byte idênticos
   ao original.

CORREÇÃO 2026-07-30 — auréola bem maior que o núcleo (limiar duplo/histerese)
------------------------------------------------------------------------------
Primeira versão usava só o limiar -5m tanto pra DETECTAR quanto pra definir
o que preencher, com anel de amostragem de só 5px de dilatação em volta do
blobo. Verificação (perfil radial do diff drone-ANADEM em torno da pior
cratera de Santa Tereza) mostrou que isso preenche mal: a 5px do núcleo o
diff ainda era -33m (praticamente sem mudança); só cruzava perto de 0m por
volta de 50-60px de raio. Confirmado por inspeção visual (mapa 300x300px em
torno do centro): "bullseye" quase perfeito, bem maior que o núcleo de
>5m de erro — a transição gradual em volta do núcleo AINDA está contaminada,
só não passa mais do limiar de detecção. Preencher usando esse anel
contaminado como referência resultava em preenchimento subindo só até
~50m onde deveria chegar a ~54,5m (ANADEM) — melhora real (era 42m de erro,
ficou ~4m) mas não o suficiente.
Correção: HISTERESE (como limiar duplo de Canny) — usa o blobo do limiar
ESTRITO (-5m) só como SEMENTE de alta confiança, mas CRESCE a máscara de
preenchimento até um limiar bem mais FROUXO (-1m), cobrindo a auréola
inteira. O anel de amostragem fica bem mais afastado dessa máscara já
crescida (20px), o que garante que os pontos de referência estão de fato
fora da região afetada.

CORREÇÃO 2 — crescimento LIMITADO geometricamente, não flood-fill livre
--------------------------------------------------------------------------
Primeira tentativa de histerese usou ndimage.binary_propagation (flood-fill
livre dentro da máscara frouxa) — quebrou feio: o talvegue real tem diff
vs ANADEM naturalmente abaixo de -1m em trechos longos (rio de verdade É
mais encaixado que a suavização do ANADEM 30m mostra), então o flood-fill
"vazou" de uma semente pequena e seguiu o CANAL por centenas de pixels,
convergindo pro mesmíssimo ponto que já tinha sido validado como talvegue
real (id=5, centro -51.73288,-29.16480) — ou seja, ia REESCREVER o rio de
verdade, o erro exato que o método inteiro existe pra evitar. Detectado
comparando o centro do blobo "crescido" #3 com a lista de blobos já
classificados como talvegue/irregular na fase de confirmação: bateu quase
exato, non-coincidência.
Corrigido trocando o flood-fill livre por um crescimento GEOMETRICAMENTE
LIMITADO: dilata a semente por um raio fixo (CRESCIMENTO_PX) e só então
intersecta com o limiar frouxo — `dilatada & suspeita_frouxa`. Isso cobre a
auréola (que por inspeção não passa de ~25px além da borda da semente) sem
conseguir se propagar arbitrariamente longe ao longo de um canal, não
importa quão conectado ele esteja no limiar frouxo.

Uso: python codigo_python/02_mdt_hand_mancha/preencher_crateras_drone.py [mucum|santa_tereza]
Sobrescreve o próprio arquivo mdt_<cidade>_drone_1m.tif (git guarda o antes).
"""
import os
import sys
import numpy as np
import rasterio
import rasterio.warp
from scipy import ndimage
from scipy.interpolate import griddata

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

CIDADES = {
    "santa_tereza": {
        "drone": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_drone_1m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_anadem_30m.tif"),
    },
    "mucum": {
        "drone": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_drone_1m.tif"),
        "anadem": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_anadem_30m.tif"),
    },
}

LIMIAR_DIFF_ESTRITO_M = -5.0   # semente (alta confiança de ser cratera)
LIMIAR_DIFF_FROUXO_M = -1.0    # crescimento por histerese (cobre a auréola)
TAM_MIN_PX = 50
FILL_MIN = 0.55
ASPECT_MAX = 2.2
CRESCIMENTO_PX = 25            # limite geométrico do crescimento além da semente
DILATACAO_ANEL_PX = 20         # anel de amostragem, afastado da máscara já crescida


def preenche(cidade):
    cfg = CIDADES[cidade]
    print(f"=== {cidade} ===")
    with rasterio.open(cfg["drone"]) as ds:
        drone = ds.read(1).astype("float64")
        nodata = ds.nodata
        transform_d = ds.transform
        crs_d = ds.crs
        profile = ds.profile.copy()
    drone_orig = np.where(drone == nodata, np.nan, drone)
    ny, nx = drone_orig.shape

    with rasterio.open(cfg["anadem"]) as ds:
        anadem = ds.read(1).astype("float64")
        nodata_a = ds.nodata
        transform_a = ds.transform
        crs_a = ds.crs
    anadem = np.where(anadem == nodata_a, np.nan, anadem)
    anadem_r = np.full((ny, nx), np.nan)
    rasterio.warp.reproject(
        source=anadem, destination=anadem_r,
        src_transform=transform_a, src_crs=crs_a,
        dst_transform=transform_d, dst_crs=crs_d,
        resampling=rasterio.warp.Resampling.bilinear,
    )

    diff = drone_orig - anadem_r
    suspeita_estrita = diff < LIMIAR_DIFF_ESTRITO_M
    suspeita_frouxa = diff < LIMIAR_DIFF_FROUXO_M
    lbl, n = ndimage.label(suspeita_estrita)
    sizes = ndimage.sum(suspeita_estrita, lbl, range(1, n + 1))

    drone_corrigido = drone_orig.copy()
    n_crateras = 0
    px_alterados = 0
    for i in range(n):
        if sizes[i] < TAM_MIN_PX:
            continue
        semente = lbl == (i + 1)
        ys, xs = np.where(semente)
        h = ys.max() - ys.min() + 1
        w = xs.max() - xs.min() + 1
        fill_ratio = sizes[i] / (h * w)
        aspect = max(w, h) / min(w, h)
        if not (fill_ratio >= FILL_MIN and aspect <= ASPECT_MAX):
            continue
        n_crateras += 1
        # cresce a semente (limiar estrito) até o limiar frouxo, mas SÓ dentro de um raio
        # fixo (não flood-fill livre) -- evita vazar ao longo de um talvegue real conectado
        dil_semente = ndimage.binary_dilation(semente, iterations=CRESCIMENTO_PX)
        mask_i = dil_semente & suspeita_frouxa
        ys, xs = np.where(mask_i)
        h = ys.max() - ys.min() + 1
        w = xs.max() - xs.min() + 1
        dil = ndimage.binary_dilation(mask_i, iterations=DILATACAO_ANEL_PX)
        anel = dil & ~mask_i
        r0, r1 = max(0, ys.min() - DILATACAO_ANEL_PX - 1), min(ny, ys.max() + DILATACAO_ANEL_PX + 2)
        c0, c1 = max(0, xs.min() - DILATACAO_ANEL_PX - 1), min(nx, xs.max() + DILATACAO_ANEL_PX + 2)
        sub_anel = anel[r0:r1, c0:c1]
        sub_mask = mask_i[r0:r1, c0:c1]
        sub_drone = drone_orig[r0:r1, c0:c1]
        ry, rx = np.where(sub_anel & ~np.isnan(sub_drone))
        vals = sub_drone[ry, rx]
        iy, ix = np.where(sub_mask)
        interp = griddata((ry, rx), vals, (iy, ix), method="linear")
        nanmask = np.isnan(interp)
        if nanmask.any():
            interp[nanmask] = griddata((ry, rx), vals, (iy[nanmask], ix[nanmask]), method="nearest")
        drone_corrigido[r0:r1, c0:c1][iy, ix] = interp
        px_alterados += int(mask_i.sum())
        cy, cx = ys.mean(), xs.mean()
        lon, lat = transform_d * (cx, cy)
        print(f"  cratera #{n_crateras}: semente {int(sizes[i])}px -> crescida {int(mask_i.sum())}px bbox={w}x{h} "
              f"fill={fill_ratio:.2f} aspect={aspect:.2f} elevmin={drone_orig[ys, xs].min():.1f}m "
              f"-> {np.nanmin(interp):.1f}-{np.nanmax(interp):.1f}m centro=({lon:.5f},{lat:.5f})")

    print(f"  total: {n_crateras} crateras, {px_alterados} px alterados "
          f"({100 * px_alterados / np.sum(~np.isnan(drone_orig)):.3f}% da área válida)")
    print(f"  elevação mínima: antes {np.nanmin(drone_orig):.2f}m -> depois {np.nanmin(drone_corrigido):.2f}m")

    saida = np.where(np.isnan(drone_corrigido), nodata, drone_corrigido).astype("float32")
    with rasterio.open(cfg["drone"], "w", **profile) as ds:
        ds.write(saida, 1)
    print(f"  sobrescrito: {os.path.relpath(cfg['drone'], RAIZ)}")
    print()


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else None
    for cidade in ([alvo] if alvo else CIDADES.keys()):
        preenche(cidade)
