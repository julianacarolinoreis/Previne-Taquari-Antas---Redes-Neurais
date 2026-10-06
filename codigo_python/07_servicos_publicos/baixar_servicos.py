#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBÔ Serviços Públicos — etapa 1: DOWNLOAD (roda no GitHub Actions).

Varre o catálogo ArcGIS do IEDE-RS e baixa as camadas estaduais de:
  hospitais, escolas, bombeiros e UBS (atenção básica)
para ./_servicos_raw/<tipo>.geojson (estado inteiro; o recorte para a
bacia acontece em preparar_servicos.py).

Cada camada candidata é validada pela contagem de pontos (faixa plausível
para o RS) antes de ser aceita. Um tipo ausente vira AVISO (buscamos fonte
federal na iteração seguinte); com menos de 2 tipos encontrados o robô falha.
"""
import os, re, json, time, shutil, unicodedata, urllib.request

RAW = "_servicos_raw"
os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "previne-servicos/1.0 (projeto FAPERGS 06/2024)"}
ROOTS = ["https://iede.rs.gov.br/server/rest/services",
         "https://iede.rs.gov.br/arcgis/rest/services"]

TIPOS = {   # tipo: (regex no nome do serviço/camada, faixa plausível no RS inteiro)
    "hospitais": (r"hospit",                                          (80,   2500)),
    "escolas":   (r"escola",                                          (2000, 20000)),
    "bombeiros": (r"bombeiro",                                        (30,   800)),
    "ubs":       (r"\bubs\b|unidade.*basica|atencao.*basica|posto.*saude", (800, 20000)),
}

def get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def j(url):
    return json.loads(get(url))

def slug(t):
    return unicodedata.normalize("NFD", str(t)).encode("ascii", "ignore").decode().lower()

def query_todos(base, page=1000, max_paginas=80):
    """Todas as feições de uma camada ArcGIS, paginando com resultOffset.
    Blindado contra servidor que ignora o offset (repetiria a 1ª página para
    sempre): pede resultRecordCount fixo, para se a página se repetir e tem
    teto de páginas."""
    feats, offset, visto = [], 0, set()
    for _ in range(max_paginas):
        gj = j(f"{base}/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326"
               f"&f=geojson&resultOffset={offset}&resultRecordCount={page}")
        lote = gj.get("features", [])
        if not lote:
            break
        # assinatura da página: se repetir, o servidor ignora o offset -> paramos
        chave = (len(lote), json.dumps(lote[0].get("geometry"), sort_keys=True)[:120])
        if chave in visto:
            print(f"  [pag] servidor ignora resultOffset — encerrando com {len(feats)} feições")
            break
        visto.add(chave)
        feats += lote
        excedeu = gj.get("exceededTransferLimit") or gj.get("properties", {}).get("exceededTransferLimit")
        if not excedeu or len(lote) < page:
            break
        offset += len(lote)
    return feats

def catalogo(root):
    idx = j(root + "?f=json")
    servs = [s["name"] for s in idx.get("services", [])]
    for pasta in idx.get("folders", []):
        try:
            servs += [s["name"] for s in j(f"{root}/{pasta}?f=json").get("services", [])]
        except Exception:
            pass
    return servs

def _iede_disponivel():
    """Teste curto antes das consultas pesadas; evita esperar dezenas de minutos
    quando os dois endpoints do IEDE estão totalmente fora do ar."""
    for root in ROOTS:
        try:
            get(root + "?f=json", timeout=12)
            return True
        except Exception as e:
            print(f"[preflight] IEDE indisponível em {root}: {e}")
    return False

if not _iede_disponivel():
    recuperados = []
    cache_dir = "assets/data/servicos"
    for tipo in TIPOS:
        src = os.path.join(cache_dir, f"{tipo}.geojson")
        if not os.path.exists(src):
            continue
        try:
            pacote = json.load(open(src, encoding="utf-8"))
            feats = pacote.get("features", [])
            if not feats:
                continue
            shutil.copyfile(src, os.path.join(RAW, f"{tipo}.geojson"))
            open(os.path.join(RAW, f"{tipo}_fonte.txt"), "w", encoding="utf-8").write(
                "CACHE do último recorte publicado; IEDE-RS indisponível nesta rodada"
            )
            recuperados.append(tipo)
        except Exception as e:
            print(f"[preflight-cache] {tipo}: {e}")
    if len(recuperados) >= 2:
        print(f"[preflight-cache] preservando último conjunto validado: {recuperados}")
        raise SystemExit(0)
    print("[preflight] cache insuficiente; seguindo para as tentativas detalhadas")

achados = {}

# Camadas FIXAS (validadas em rodadas anteriores + indicação da equipe):
# tentadas direto, sem depender do catálogo — que oscila muito. A descoberta
# abaixo continua como reserva para quando alguma URL fixa quebrar.
# ubs_poa é só Porto Alegre (144 pontos, 0 na bacia) — fica como último recurso;
# a busca por UBS ESTADUAL nas pastas de saúde vem antes (ver bloco UBS abaixo).
FIXAS = {
    "hospitais": ["https://iede.rs.gov.br/server/rest/services/Hosted/Hospitais_Movimento_Massa/MapServer/3"],
    "escolas":   ["https://iede.rs.gov.br/server/rest/services/Hosted/Escolas_Movimento_Massa/MapServer/2"],
    "bombeiros": ["https://iede.rs.gov.br/server/rest/services/CBM_Bombeiros/CBM_Centroide_RS_SC/MapServer/0"],
}
def _aceita(tipo, feats, fonte):
    pontos = [f_ for f_ in feats if (f_.get("geometry") or {}).get("type") == "Point"]
    n, (lo, hi) = len(pontos), TIPOS[tipo][1]
    if not (lo <= n <= hi):
        print(f"[{tipo}] {fonte}: {n} pontos fora da faixa {(lo, hi)} — pulo")
        return False
    json.dump({"type": "FeatureCollection", "features": pontos},
              open(f"{RAW}/{tipo}.geojson", "w"), ensure_ascii=False)
    open(f"{RAW}/{tipo}_fonte.txt", "w").write(fonte)
    print(f"[ok] {tipo}: {n} pontos <- {fonte}")
    achados[tipo] = n
    return True

for tipo, urls in FIXAS.items():
    for u in urls:
        if tipo in achados: break
        for tent in (1, 2, 3):
            try:
                if _aceita(tipo, query_todos(u), u): pass
                break
            except Exception as e:
                print(f"[{tipo}] fixa (tentativa {tent}): {e}")
                if tent < 3: time.sleep(30)

# ---- UBS ESTADUAL: varre as pastas de saúde do IEDE atrás de uma camada de
# unidades básicas que cubra o estado (a ubs_poa é só Porto Alegre). ----
def _servicos_da_pasta(root, pasta):
    return [s["name"] for s in j(f"{root}/{pasta}?f=json").get("services", [])]

RX_UBS = r"\bubs\b|unidade.*basica|atencao.*(basica|primaria)|estrategia.*saude|\besf\b|\baps\b|posto.*saude|estabelecimento.*saude|unidades.*saude"
PASTAS_SAUDE = ["SES", "Hosted"]
if "ubs" not in achados:
    for root in ROOTS:
        if "ubs" in achados: break
        for pasta in PASTAS_SAUDE:
            if "ubs" in achados: break
            try:
                servs = _servicos_da_pasta(root, pasta)
            except Exception as e:
                print(f"[ubs] pasta {pasta} em {root}: {e}"); continue
            cand = [s for s in servs if re.search(RX_UBS, slug(s)) and "poa" not in slug(s)]
            print(f"[ubs] pasta {pasta}: {len(servs)} serviços, candidatos: {cand[:12]}")
            for sv in cand:
                if "ubs" in achados: break
                for kind in ("MapServer", "FeatureServer"):
                    if "ubs" in achados: break
                    try:
                        meta = j(f"{root}/{sv}/{kind}?f=json")
                    except Exception:
                        continue
                    camadas = meta.get("layers", [])
                    alvo = [ly for ly in camadas if re.search(RX_UBS, slug(ly.get("name", "")))] or camadas
                    for ly in alvo:
                        try:
                            if _aceita("ubs", query_todos(f"{root}/{sv}/{kind}/{ly['id']}"),
                                       f"{root}/{sv}/{kind}/{ly['id']}"):
                                break
                        except Exception as e:
                            print(f"[ubs] {sv}/{ly.get('name')}: {e}")

for rodada in (1, 2, 3):        # o catálogo do IEDE oscila — insiste com pausa
    if len(achados) == len(TIPOS): break
    if rodada > 1:
        print(f"[retry] catálogo indisponível — tentativa {rodada}/3 em 90 s"); time.sleep(90)
    for root in ROOTS:
        if len(achados) == len(TIPOS): break
        try:
            servs = catalogo(root)
        except Exception as e:
            print(f"[aviso] catálogo {root}: {e}"); continue
        print(f"[catálogo] {root}: {len(servs)} serviços")
        for tipo, (rx, faixa) in TIPOS.items():
            if tipo in achados: continue
            cand = [s for s in servs if re.search(rx, slug(s))]
            print(f"[{tipo}] serviços candidatos: {cand[:10]}")
            for sv in cand:
                if tipo in achados: break
                for kind in ("MapServer", "FeatureServer"):
                    if tipo in achados: break
                    try:
                        meta = j(f"{root}/{sv}/{kind}?f=json")
                    except Exception:
                        continue
                    camadas = meta.get("layers", [])
                    alvo = [ly for ly in camadas if re.search(rx, slug(ly.get("name", "")))] or camadas
                    for ly in alvo:
                        try:
                            feats = query_todos(f"{root}/{sv}/{kind}/{ly['id']}")
                        except Exception as e:
                            print(f"[{tipo}] {sv}/{ly.get('name')}: {e}"); continue
                        pontos = [f_ for f_ in feats if (f_.get("geometry") or {}).get("type") == "Point"]
                        n = len(pontos)
                        if not (faixa[0] <= n <= faixa[1]):
                            print(f"[{tipo}] {sv}/{ly.get('name')}: {n} pontos fora da faixa {faixa} — pulo")
                            continue
                        json.dump({"type": "FeatureCollection", "features": pontos},
                                  open(f"{RAW}/{tipo}.geojson", "w"), ensure_ascii=False)
                        open(f"{RAW}/{tipo}_fonte.txt", "w").write(f"{root}/{sv}/{kind}/{ly['id']}")
                        print(f"[ok] {tipo}: {n} pontos <- {sv}/{ly.get('name')}")
                        achados[tipo] = n
                        break

faltam = [t for t in TIPOS if t not in achados]
if faltam:
    print(f"[AVISO] tipos sem camada no IEDE: {faltam} — na próxima iteração buscamos fonte federal (CNES/INEP)")

# O IEDE pode ficar indisponível por dezenas de minutos. Nessa situação não
# apagamos nem invalidamos as camadas públicas que já foram validadas. O
# fallback reaproveita o último recorte publicado apenas para os tipos que não
# puderam ser baixados nesta rodada; a origem fica explicitamente marcada como
# cache e uma rodada futura tenta o IEDE novamente.
if len(achados) < 2:
    cache_dir = "assets/data/servicos"
    recuperados = []
    for tipo in TIPOS:
        if tipo in achados:
            continue
        src = os.path.join(cache_dir, f"{tipo}.geojson")
        if not os.path.exists(src):
            continue
        try:
            pacote = json.load(open(src, encoding="utf-8"))
            feats = pacote.get("features", [])
            if not feats:
                continue
            shutil.copyfile(src, os.path.join(RAW, f"{tipo}.geojson"))
            open(os.path.join(RAW, f"{tipo}_fonte.txt"), "w", encoding="utf-8").write(
                "CACHE do último recorte publicado; IEDE-RS indisponível nesta rodada"
            )
            achados[tipo] = len(feats)
            recuperados.append(tipo)
        except Exception as e:
            print(f"[cache] {tipo}: não foi possível preservar o último publicado: {e}")
    if recuperados:
        print(f"[cache] IEDE indisponível; preservando último conjunto validado para: {recuperados}")

if len(achados) < 2:
    raise RuntimeError(f"só encontrei {list(achados)} e não há cache suficiente — revisar TIPOS/ROOTS")
print("DOWNLOAD COMPLETO:", achados)
