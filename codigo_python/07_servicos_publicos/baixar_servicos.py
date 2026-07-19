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
import os, re, json, unicodedata, urllib.request

RAW = "_servicos_raw"
os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "previne-servicos/1.0 (projeto FAPERGS 06/2024)"}
ROOTS = ["https://iede.rs.gov.br/server/rest/services",
         "https://iede.rs.gov.br/arcgis/rest/services"]

TIPOS = {   # tipo: (regex no nome do serviço/camada, faixa plausível no RS inteiro)
    "hospitais": (r"hospit",                                          (80,   2500)),
    "escolas":   (r"escola",                                          (2000, 20000)),
    "bombeiros": (r"bombeiro",                                        (30,   800)),
    "ubs":       (r"\bubs\b|unidade.*basica|atencao.*basica|posto.*saude", (600, 8000)),
}

def get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def j(url):
    return json.loads(get(url))

def slug(t):
    return unicodedata.normalize("NFD", str(t)).encode("ascii", "ignore").decode().lower()

def query_todos(base):
    """Todas as feições de uma camada ArcGIS, paginando com resultOffset."""
    feats, offset = [], 0
    while True:
        gj = j(f"{base}/query?where=1%3D1&outFields=*&returnGeometry=true"
               f"&outSR=4326&f=geojson&resultOffset={offset}")
        lote = gj.get("features", [])
        feats += lote
        excedeu = gj.get("exceededTransferLimit") or gj.get("properties", {}).get("exceededTransferLimit")
        if not lote or not excedeu or offset > 100_000:
            return feats
        offset += len(lote)

def catalogo(root):
    idx = j(root + "?f=json")
    servs = [s["name"] for s in idx.get("services", [])]
    for pasta in idx.get("folders", []):
        try:
            servs += [s["name"] for s in j(f"{root}/{pasta}?f=json").get("services", [])]
        except Exception:
            pass
    return servs

achados = {}
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
                    pontos = [f_ for f_ in feats if f_.get("geometry", {}).get("type") == "Point"]
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
if len(achados) < 2:
    raise RuntimeError(f"só encontrei {list(achados)} — catálogo mudou? revisar TIPOS/ROOTS")
print("DOWNLOAD COMPLETO:", achados)
