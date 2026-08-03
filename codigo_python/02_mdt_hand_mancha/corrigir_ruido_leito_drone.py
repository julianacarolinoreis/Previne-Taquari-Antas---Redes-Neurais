#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Corrige ruído de fotogrametria DENTRO DO LEITO DO RIO nos MDTs de drone —
tanto "crateras" (pontos baixos demais, já corrigidas antes por
preencher_crateras_drone.py) quanto "platôs" (pontos altos demais, achado
novo de 2026-08-01). Substitui preencher_crateras_drone.py: mesma técnica,
agora unificada pros dois sinais de erro numa passada só.

POR QUE UNIFICAR (achado que motivou a reescrita)
----------------------------------------------------
A usuária reparou em trechos DENTRO do leito do rio com elevação ALTA
demais (tipo um degrau/platô), suspeitando do mesmo tipo de problema do
drone que causou as crateras. Confirmado por reprodução própria: em Santa
Tereza, os "platôs" (diff > +5m vs ANADEM, dentro da faixa do rio) ficam
a 5-69m (a maioria <10m) das crateras já corrigidas antes — e 3 de 5
batem em cima de água branca turbulenta (corredeira) na imagem de
satélite Esri. Ou seja: cratera e platô não são dois bugs separados, são
o MESMO fenômeno (água difícil pra fotogrametria — turva, com reflexo ou
turbulenta — quebra a correlação estereoscópica de imagem) manifestando
ruído dos dois sinais na mesma zona.

Corrigir os dois separadamente é arriscado: o anel de pontos de
referência usado pra reinterpolar uma cratera pode acabar pegando pixels
que fazem parte do platô vizinho (ainda contaminados), e vice-versa.
Por isso aqui as duas máscaras (baixa e alta) crescem e se FUNDEM numa
zona só antes de qualquer interpolação, e a reinterpolação usa só pontos
de referência fora de QUALQUER zona suspeita (não só da zona sendo
corrigida no momento).

RISCO DE CONECTIVIDADE DO TALVEGUE (confirmado, não hipotético — e
CONTINUA parcialmente aberto mesmo depois da correção, ver abaixo)
--------------------------------------------------------------------
No mosaico de 2m (resolução em produção hoje) a reamostragem dilui os
platôs pequenos e a máscara de talvegue não quebra. MAS na resolução
NATIVA de 1m do drone (relevante pras rotas de fuga, que vão precisar de
precisão casa a casa) o platô em -51.73590,-29.17410 (65,5m, corte de
percentil-50 da faixa ali = 63,47m) FICAVA DE FORA da máscara candidata
do talvegue antes da correção — quebrava a conectividade nesse ponto.
A elevação nesse ponto específico já foi corrigida (confirmado: caiu
pra ~60,6m, valor plausível). MAS a fragmentação da máscara de talvegue
em 1m nativo continua igual antes/depois (56-57 componentes conectados,
maior componente ~96% do total, esse ponto específico continua fora do
maior componente) — ou seja, a fragmentação em 1m nativo NÃO é causada
(só) pelos artefatos corrigidos aqui. É uma característica do próprio
método de detecção de talvegue (corte por percentil-50 dentro de uma
faixa) quando aplicado em resolução muito fina: variação natural real do
terreno (pedras, bancos de areia, micro-relevo que o drone capta certo)
também excede esse corte em trechos curtos. Fica registrado como
pendência separada pra quem for desenhar o algoritmo de rotas — não é
escopo deste script tentar resolver.

MÉTODO
------
1. Reprojeta ANADEM pra grade do drone; diff = drone - anadem.
2. RESTRIÇÃO ASSIMÉTRICA por sinal (achado corrigindo um erro do
   primeiro rascunho — ver "BUGS ENCONTRADOS" abaixo): crateras (BAIXO)
   são detectadas SEM restrição de área — o mesmo critério de forma já
   validado na investigação original é suficiente sozinho, porque uma
   encosta real nunca fica artificialmente MAIS BAIXA que o ANADEM
   suavizado por dezenas de metros (só fica artificialmente mais ALTA).
   Platôs (ALTO) continuam restritos à FAIXA DO RIO (talvegue oficial do
   ANADEM, dilatado FAIXA_RIO_DILATACAO_PX): sem essa restrição, uma
   varredura simples pega ~500 blobs em Santa Tereza, quase tudo encosta
   real que o ANADEM (30m) suaviza e o drone (1m) capta certo.
3. Componentes conectados em |diff| > LIMIAR_ESTRITO_M (semente de alta
   confiança), classificados por forma (fill_ratio=área/bbox,
   aspect=lado_maior/lado_menor): fill>=0.55 E aspect<=2.2 -> ok por
   forma (círculo/blob de erro de fotogrametria; talvegue real é
   longo/fino).
4. Sementes que NÃO passam no teste de forma sozinhas mas estão a até
   RAIO_PROXIMIDADE_M de alguma que passou (e tem tamanho abaixo de
   TAM_MAX_PROXIMIDADE_PX, pra nunca varrer um blob de relevo real de
   centenas de milhares de pixels só por estar por perto) também entram
   -- é o caso dos platôs com forma mais irregular que ainda assim estão
   coladinhos numa cratera já confirmada por forma.

BUGS ENCONTRADOS NA VALIDAÇÃO (2026-08-01) — não hipotéticos, achados
testando de verdade antes de aceitar o resultado
------------------------------------------------------------------------
1. RESTRIÇÃO SIMÉTRICA DEMAIS (primeira versão): o primeiro rascunho
   restringia TAMBÉM as crateras (BAIXO) à faixa do rio, não só os
   platôs. Ao reconstruir a correção do zero (restaurando o .tif bruto
   original pra unificar cratera+platô numa passada só), isso fez a
   "cratera #1" (já corrigida numa sessão anterior por
   preencher_crateras_drone.py, elevmin 13,2m -> ~72-81m, em
   -51.73580,-29.16319) SUMIR da detecção — ela fica perto de um corpo
   d'água que não é o canal principal traçado a partir do talvegue do
   ANADEM, então cai fora da faixa. Percebido na validação: elevação
   mínima do raster voltou a 13,2m depois da "correção", quando deveria
   ter subido. Corrigido tornando a restrição assimétrica (item 2 do
   MÉTODO acima).
2. CRESCIMENTO POR HISTERESE VAZAVA PRA TERRENO BOM (mais sério, achado
   na comparação visual antes/depois): a versão seguinte crescia a
   semente com `binary_dilation(seed, iterations=N) & suspeita_frouxa`
   -- um disco cheio de raio fixo, ANDado com o limiar frouxo. Isso não
   exige conectividade real: qualquer pixel frouxo dentro do disco
   entra, mesmo isolado, mesmo que seja terreno bom (o ANADEM tem
   ±1-2m de incerteza própria, então "diff>1m" acontece à toa em
   terreno correto, sobretudo perto de encostas). Resultado visível:
   uma zona em -51.73794,-29.17275 engoliu faixa de elevação original
   21,5-73,8m (a cratera de verdade E um pedaço de banco real ao lado)
   e a reinterpolação achatou tudo pra ~54-55m — apagou terreno bom,
   ficou visível como um "diamante" escuro artificial na comparação
   antes/depois. Corrigido em duas frentes: (a) trocado por dilatação
   CONDICIONADA (`binary_dilation(seed, mask=suspeita_frouxa,
   iterations=CRESCIMENTO_PX)`) — cresce só por conectividade de
   verdade dentro do limiar frouxo, não pega mais pixel frouxo isolado
   só por estar dentro do raio; (b) limiar frouxo subiu de 1,0m pra
   2,0m — 1,0m ainda deixava "pontes" de ruído natural do terreno
   conectarem o núcleo da cratera a terreno bom via caminho genuíno
   (não just artefato de disco). Revalidado visualmente depois: sem
   mais blobs artificiais, mudanças concentradas e na direção certa.
5. Cada semente aceita cresce por histerese até o limiar FROUXO
   (LIMIAR_FROUXO_M), limitada geometricamente (CRESCIMENTO_PX de
   dilatação, não flood-fill livre -- ver preencher_crateras_drone.py
   pra por que isso importa: flood-fill livre já vazou pro talvegue real
   uma vez).
6. UNIÃO de todas as máscaras crescidas, relabeled em componentes
   conectados -- isso funde automaticamente cratera+platô vizinhos numa
   zona só quando as máscaras crescidas se tocam.
7. Cada zona final é reinterpolada (scipy.interpolate.griddata, linear
   com nearest de fallback) usando um anel de pontos de referência que
   exclui QUALQUER pixel ainda no limiar frouxo (não só os desta zona) --
   garante que a referência é sempre terreno limpo, mesmo perto de outra
   zona ainda não fundida.

Uso:
  python corrigir_ruido_leito_drone.py [mucum|santa_tereza] --listar
      (so mostra a classificacao, nao grava nada -- usar pra revisar antes)
  python corrigir_ruido_leito_drone.py [mucum|santa_tereza]
      (aplica de verdade, sobrescreve mdt_<cidade>_drone_1m.tif)
"""
import os
import sys

import numpy as np
import rasterio
import rasterio.warp
from scipy import ndimage
from scipy.interpolate import griddata

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gerar_mancha_mosaico import le, talvegue_anadem  # noqa: E402

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

FAIXA_RIO_DILATACAO_PX = 15    # largura da faixa do rio em volta da linha do talvegue (px=m)
LIMIAR_ESTRITO_M = 5.0         # |diff| pra semente de alta confianca
LIMIAR_FROUXO_M = 2.0          # |diff| pro crescimento por histerese (1.0 deixava
                                # "pontes" de ruido natural do terreno -- ANADEM tem
                                # +-1-2m de incerteza propria -- conectarem o nucleo
                                # da cratera a terreno bom real; 2.0 reduz isso mantendo
                                # folga sobre a aureola real (que no pior caso ja visto
                                # chegava a -20/-30m bem alem do nucleo)
TAM_MIN_PX = 15                # tamanho minimo pra sequer considerar uma semente
FILL_MIN = 0.55
ASPECT_MAX = 2.2
RAIO_PROXIMIDADE_M = 50        # semente que falha forma mas esta perto de uma que passou tambem entra
TAM_MAX_PROXIMIDADE_PX = 3000  # trava de seguranca: nunca aceita por proximidade um blob deste tamanho pra cima
CRESCIMENTO_PX = 25            # limite geometrico do crescimento por histerese (nao flood-fill livre)
DILATACAO_ANEL_PX = 20         # anel de amostragem, afastado de qualquer zona suspeita


def carrega(cidade):
    cfg = CIDADES[cidade]
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

    dem_a_full, transform_a2, crs_a2, _ = le(cfg["anadem"])
    thal_a = talvegue_anadem(dem_a_full)
    thal_drone_grid = np.zeros((ny, nx), dtype=np.uint8)
    rasterio.warp.reproject(
        source=thal_a.astype(np.uint8), destination=thal_drone_grid,
        src_transform=transform_a2, src_crs=crs_a2,
        dst_transform=transform_d, dst_crs=crs_d,
        resampling=rasterio.warp.Resampling.nearest,
    )
    faixa_rio = ndimage.binary_dilation(thal_drone_grid.astype(bool), iterations=FAIXA_RIO_DILATACAO_PX)

    return drone_orig, anadem_r, faixa_rio, transform_d, nodata, profile


def classifica(drone_orig, anadem_r, faixa_rio, transform_d):
    """RESTRIÇÃO ASSIMÉTRICA (achado 2026-08-01, corrigindo um erro do primeiro
    rascunho deste script): craterras (BAIXO) usam o mesmo criterio de forma
    ja validado na investigacao original, SEM restringir a faixa do rio --
    coarse-ANADEM-vs-drone so gera falso positivo de encosta real do lado
    ALTO (uma encosta real nunca fica artificialmente MAIS BAIXA que o
    ANADEM suavizado por dezenas de metros; so fica artificialmente mais
    ALTA). Platos (ALTO) continuam restritos a faixa do rio, porque sem essa
    restricao uma varredura simples pegava ~500 blobs em Santa Tereza, quase
    todos encosta real que o ANADEM (30m) suaviza e o drone (1m) capta certo.
    Restringir TAMBEM o lado BAIXO por faixa do rio (erro do primeiro
    rascunho) fez a "cratera #1" (ja corrigida numa sessao anterior, fora da
    faixa por nao ficar junto do canal principal tracado a partir do
    ANADEM) sumir da deteccao quando o dado bruto foi restaurado pra
    reconstruir a correcao do zero -- pego na validacao (elevacao minima
    voltou a 13,2m depois da "correcao", quando deveria ter subido)."""
    diff = drone_orig - anadem_r
    suspeita_estrita = (
        ((diff < -LIMIAR_ESTRITO_M))
        | ((diff > LIMIAR_ESTRITO_M) & faixa_rio)
    )
    suspeita_frouxa = (
        ((diff < -LIMIAR_FROUXO_M))
        | ((diff > LIMIAR_FROUXO_M) & faixa_rio)
    )

    lbl, n = ndimage.label(suspeita_estrita)
    sizes = ndimage.sum(suspeita_estrita, lbl, range(1, n + 1))

    candidatos = []
    for i in range(n):
        if sizes[i] < TAM_MIN_PX:
            continue
        seed = lbl == (i + 1)
        ys, xs = np.where(seed)
        h = ys.max() - ys.min() + 1
        w = xs.max() - xs.min() + 1
        fill = sizes[i] / (h * w)
        aspect = max(w, h) / min(w, h)
        cy, cx = ys.mean(), xs.mean()
        lon, lat = transform_d * (cx, cy)
        sinal = "ALTO" if diff[seed].mean() > 0 else "BAIXO"
        forma_ok = fill >= FILL_MIN and aspect <= ASPECT_MAX
        candidatos.append({
            "idx": i, "seed": seed, "sz": int(sizes[i]), "fill": fill, "aspect": aspect,
            "lon": lon, "lat": lat, "sinal": sinal, "forma_ok": forma_ok,
        })

    aceitos_forma = [c for c in candidatos if c["forma_ok"]]

    def dist_m(c1, c2):
        dlon = (c1["lon"] - c2["lon"]) * 96000  # aprox p/ latitude ~-29
        dlat = (c1["lat"] - c2["lat"]) * 111320
        return (dlon**2 + dlat**2) ** 0.5

    aceitos = []
    for c in candidatos:
        motivo = None
        if c["forma_ok"]:
            motivo = "forma"
        elif c["sz"] < TAM_MAX_PROXIMIDADE_PX and aceitos_forma:
            dmin = min(dist_m(c, a) for a in aceitos_forma)
            if dmin <= RAIO_PROXIMIDADE_M:
                motivo = f"proximidade ({dmin:.0f}m de uma zona confirmada por forma)"
        if motivo:
            c["motivo"] = motivo
            aceitos.append(c)

    return aceitos, suspeita_frouxa, diff


def cresce_e_funde(aceitos, suspeita_frouxa, drone_orig):
    """CORREÇÃO 2026-08-01 (achada na validação visual, não hipotética): a
    primeira versão crescia a semente com `binary_dilation(seed, iters) &
    suspeita_frouxa` -- um disco cheio de raio fixo, ANDado com o limiar
    frouxo. Isso NÃO exige conectividade real: qualquer pixel frouxo dentro
    do disco entra, mesmo que seja um pedaço de terreno bom isolado (o
    ANADEM tem ±1-2m de incerteza própria, então "diff>1m" acontece à toa
    em terreno correto, especialmente perto de encostas). Resultado visível:
    zonas como a de -51.73794,-29.17275 engoliram faixa de elevação original
    21,5-73,8m (a cratera de verdade E um pedaço de banco/encosta real ao
    lado) e a reinterpolação achatou tudo pra ~54-55m -- apagou terreno bom.
    Corrigido trocando por dilatação CONDICIONADA (`mask=suspeita_frouxa`):
    cresce só por conectividade de verdade dentro do limiar frouxo, no
    máximo CRESCIMENTO_PX passos -- não pega mais pixels frouxos isolados
    que só calham de estar dentro do raio, e continua sem risco do
    flood-fill livre (sem tampa) que já tinha sido descartado antes por
    vazar pro talvegue real."""
    ny, nx = drone_orig.shape
    uniao = np.zeros((ny, nx), dtype=bool)
    for c in aceitos:
        crescida = ndimage.binary_dilation(c["seed"], mask=suspeita_frouxa, iterations=CRESCIMENTO_PX)
        uniao |= crescida
    lbl_zonas, n_zonas_bruto = ndimage.label(uniao)
    sizes = ndimage.sum(uniao, lbl_zonas, range(1, n_zonas_bruto + 1))

    # A uniao pega qualquer pixel |diff|>1m dentro do raio de crescimento de uma
    # semente aceita -- inclui specks isolados (1-poucos px) de ruido natural
    # (diff pouco acima de 1m acontece por acaso ate em terreno correto, dado
    # que o proprio ANADEM tem +-1-2m de incerteza) que calharam de cair dentro
    # desse raio mas nao sao de fato parte da semente (nao tocam ela). Filtra
    # zonas pequenas demais pra serem correcao de verdade, ao inves de tentar
    # "consertar" um punhado de pixels que provavelmente e so ruido de medicao.
    lbl_final = np.zeros_like(lbl_zonas)
    prox_id = 1
    n_zonas = 0
    for zi in range(1, n_zonas_bruto + 1):
        if sizes[zi - 1] < TAM_MIN_PX:
            continue
        lbl_final[lbl_zonas == zi] = prox_id
        prox_id += 1
        n_zonas += 1
    return lbl_final, n_zonas


def preenche_zonas(lbl_zonas, n_zonas, drone_orig, suspeita_frouxa, transform_d):
    ny, nx = drone_orig.shape
    drone_corrigido = drone_orig.copy()
    resumo = []
    for zi in range(1, n_zonas + 1):
        mask_i = lbl_zonas == zi
        ys, xs = np.where(mask_i)
        h = ys.max() - ys.min() + 1
        w = xs.max() - xs.min() + 1
        dil = ndimage.binary_dilation(mask_i, iterations=DILATACAO_ANEL_PX)
        anel = dil & ~mask_i & ~suspeita_frouxa
        r0, r1 = max(0, ys.min() - DILATACAO_ANEL_PX - 1), min(ny, ys.max() + DILATACAO_ANEL_PX + 2)
        c0, c1 = max(0, xs.min() - DILATACAO_ANEL_PX - 1), min(nx, xs.max() + DILATACAO_ANEL_PX + 2)
        sub_anel = anel[r0:r1, c0:c1]
        sub_mask = mask_i[r0:r1, c0:c1]
        sub_drone = drone_orig[r0:r1, c0:c1]
        ry, rx = np.where(sub_anel & ~np.isnan(sub_drone))
        if len(ry) < 4:
            # anel sem pontos limpos suficientes (zona grande demais / cercada de ruido) -- pula, nao adivinha
            cy, cx = ys.mean(), xs.mean()
            lon, lat = transform_d * (cx, cy)
            resumo.append({"zona": zi, "sz": int(mask_i.sum()), "status": "PULADO (anel sem pontos limpos)",
                            "lon": lon, "lat": lat})
            continue
        vals = sub_drone[ry, rx]
        iy, ix = np.where(sub_mask)
        interp = griddata((ry, rx), vals, (iy, ix), method="linear")
        nanmask = np.isnan(interp)
        if nanmask.any():
            interp[nanmask] = griddata((ry, rx), vals, (iy[nanmask], ix[nanmask]), method="nearest")
        drone_corrigido[r0:r1, c0:c1][iy, ix] = interp
        cy, cx = ys.mean(), xs.mean()
        lon, lat = transform_d * (cx, cy)
        elev_antes = drone_orig[ys, xs]
        resumo.append({
            "zona": zi, "sz": int(mask_i.sum()), "bbox": f"{w}x{h}",
            "elev_antes_min": float(np.nanmin(elev_antes)), "elev_antes_max": float(np.nanmax(elev_antes)),
            "elev_depois_min": float(np.nanmin(interp)), "elev_depois_max": float(np.nanmax(interp)),
            "lon": lon, "lat": lat, "status": "OK",
        })
    return drone_corrigido, resumo


def processa(cidade, listar_apenas):
    print(f"=== {cidade} ===")
    drone_orig, anadem_r, faixa_rio, transform_d, nodata, profile = carrega(cidade)
    aceitos, suspeita_frouxa, diff = classifica(drone_orig, anadem_r, faixa_rio, transform_d)

    print(f"  sementes aceitas: {len(aceitos)}")
    for c in sorted(aceitos, key=lambda c: -c["sz"]):
        print(f"    sz={c['sz']:6d} fill={c['fill']:.2f} aspect={c['aspect']:.2f} sinal={c['sinal']:5s} "
              f"motivo={c['motivo']:35s} centro=({c['lon']:.5f},{c['lat']:.5f})")

    if not aceitos:
        print("  nada a corrigir.")
        print()
        return

    lbl_zonas, n_zonas = cresce_e_funde(aceitos, suspeita_frouxa, drone_orig)
    print(f"  zonas finais apos fusao (cratera+plato proximos viram 1 so): {n_zonas}")

    if listar_apenas:
        for zi in range(1, n_zonas + 1):
            mask_i = lbl_zonas == zi
            sz = int(mask_i.sum())
            ys, xs = np.where(mask_i)
            cy, cx = ys.mean(), xs.mean()
            lon, lat = transform_d * (cx, cy)
            print(f"    zona {zi}: {sz}px centro=({lon:.5f},{lat:.5f}) [--listar: nao alterado]")
        print()
        return

    drone_corrigido, resumo = preenche_zonas(lbl_zonas, n_zonas, drone_orig, suspeita_frouxa, transform_d)
    for r in resumo:
        if r["status"] == "OK":
            print(f"    zona {r['zona']}: {r['sz']}px bbox={r['bbox']} "
                  f"elev {r['elev_antes_min']:.1f}-{r['elev_antes_max']:.1f}m -> "
                  f"{r['elev_depois_min']:.1f}-{r['elev_depois_max']:.1f}m centro=({r['lon']:.5f},{r['lat']:.5f})")
        else:
            print(f"    zona {r['zona']}: {r['sz']}px {r['status']} centro=({r['lon']:.5f},{r['lat']:.5f})")

    px_alterados = int(np.sum(lbl_zonas > 0))
    print(f"  total: {px_alterados} px alterados ({100 * px_alterados / np.sum(~np.isnan(drone_orig)):.3f}% da area valida)")

    saida = np.where(np.isnan(drone_corrigido), nodata, drone_corrigido).astype("float32")
    cfg = CIDADES[cidade]
    with rasterio.open(cfg["drone"], "w", **profile) as ds:
        ds.write(saida, 1)
    print(f"  sobrescrito: {os.path.relpath(cfg['drone'], RAIZ)}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    listar = "--listar" in args
    alvos = [a for a in args if not a.startswith("--")]
    for cidade in (alvos if alvos else CIDADES.keys()):
        processa(cidade, listar)
