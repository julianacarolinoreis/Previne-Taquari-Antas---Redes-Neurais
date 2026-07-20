#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBÔ Serviços Públicos — etapa 2: RECORTE para a bacia (roda no GitHub Actions).

Entrada:  ./_servicos_raw/<tipo>.geojson  (estado inteiro, de baixar_servicos.py)
Saída:    assets/data/servicos/
  - <tipo>.geojson            (pontos dentro dos municípios da bacia: nome, município)
  - contagem_municipios.json  (nº de cada serviço por município — base do mapa de densidade)
  - FONTES.md

Usa os polígonos municipais já publicados pelo robô da vulnerabilidade
(assets/data/vulnerabilidade/municipios.geojson, simplificados ~120 m —
suficiente para atribuir pontos; pontos exatamente na borda podem cair fora).
"""
import os, re, glob, json
import geopandas as gpd

RAW, OUT = "_servicos_raw", "assets/data/servicos"
os.makedirs(OUT, exist_ok=True)

FAIXA_BACIA = {  # contagem plausível DENTRO da bacia — o robô recusa fora disso
    "hospitais": (20, 400), "escolas": (500, 6000), "bombeiros": (8, 200), "ubs": (150, 2500),
}

mun = gpd.read_file("assets/data/vulnerabilidade/municipios.geojson")
mun = mun.rename(columns={"nome": "mun_nome"})[["cod_mun", "mun_nome", "geometry"]]
if mun.crs is None: mun = mun.set_crs(4326)

def nome_col(df):
    """Escolhe a coluna de nome pelo CONTEÚDO (texto longo, variado), não só
    pelo cabeçalho — na rodada 3, hospitais vieram com 'REGIÃO 28' (coluna errada)."""
    ruins = re.compile(r"regi|macro|micro|^cd_|^cod|^id$|objectid|^fid|tipo|classe|situa|^uf$|fonte|data|shape", re.I)
    cands = []
    for c in df.columns:
        if c == "geometry" or ruins.search(str(c)): continue
        s = df[c].astype(str).str.strip()
        ok = s[(s != "") & (~s.str.lower().isin(["none", "nan", "null"]))]
        if ok.empty: continue
        medlen = float(ok.str.len().median())
        alpha = float(ok.str.contains(r"[A-Za-zÀ-ÿ]{3,}").mean())   # tem palavras de verdade
        uniq = ok.nunique() / len(ok)
        prefer = 1.5 if re.search(r"nome|name|denomina|fantasia|estabele|escola|unidade|quartel", str(c), re.I) else 1.0
        cands.append((prefer * alpha * (0.5 + uniq) * min(medlen, 40.0), c))
    cands.sort(reverse=True)
    print("  [nome] melhores colunas:", [(round(s, 1), c) for s, c in cands[:5]])
    return cands[0][1] if cands else None

contagem, fontes = {}, {}
for arq in sorted(glob.glob(f"{RAW}/*.geojson")):
    tipo = os.path.basename(arq)[:-8]
    g = gpd.read_file(arq)
    if g.crs is None: g = g.set_crs(4326)
    g = g.to_crs(4326)
    print(f"[{tipo}] colunas da fonte: {[c for c in g.columns if c != 'geometry']}")
    dentro = gpd.sjoin(g, mun, how="inner", predicate="within")
    nc = nome_col(g)
    out = gpd.GeoDataFrame({
        "nome":      dentro[nc].astype(str).str.strip() if nc else "",
        "municipio": dentro["mun_nome"].values,
        "cod_mun":   dentro["cod_mun"].astype(str).values,
    }, geometry=dentro.geometry.values, crs=4326)
    n = len(out)
    lo, hi = FAIXA_BACIA.get(tipo, (1, 10**6))
    print(f"[{tipo}] RS: {len(g)} pontos -> bacia: {n}")
    assert lo <= n <= hi, f"{tipo}: {n} pontos na bacia (esperado {lo}–{hi}) — camada ou junção errada"
    out.to_file(f"{OUT}/{tipo}.geojson", driver="GeoJSON")
    for cod, k in out.groupby("cod_mun").size().items():
        contagem.setdefault(str(cod), {})[tipo] = int(k)
    ftxt = f"{RAW}/{tipo}_fonte.txt"
    fontes[tipo] = open(ftxt).read().strip() if os.path.exists(ftxt) else "IEDE-RS"

nomes = dict(zip(mun["cod_mun"].astype(str), mun["mun_nome"]))
json.dump({
    "fonte": "IEDE-RS (https://iede.rs.gov.br) — recorte: municípios da bacia Taquari-Antas",
    "municipios": [{"cod_mun": c, "nome": nomes.get(c, "?"), **v} for c, v in sorted(contagem.items())],
}, open(f"{OUT}/contagem_municipios.json", "w"), ensure_ascii=False)

open(f"{OUT}/FONTES.md", "w").write(
    "# Fontes — serviços públicos (camadas estaduais completas)\n"
    + "".join(f"- {t}: {u}\n" for t, u in sorted(fontes.items()))
    + "Recorte: pontos dentro dos municípios que intersectam a bacia Taquari-Antas\n"
      "(polígonos municipais simplificados ~120 m — pontos exatamente na divisa podem\n"
      "cair fora). Estaduais completos nas URLs acima.\n")

print("\n== SANIDADE ==")
tot = {t: sum(v.get(t, 0) for v in contagem.values()) for t in fontes}
print("Totais na bacia:", tot)
top = sorted(contagem.items(), key=lambda kv: -sum(kv[1].values()))[:6]
for cod, v in top:
    print(f"  {nomes.get(cod, cod)}: {v}")
print("PROCESSAMENTO COMPLETO ->", OUT)
