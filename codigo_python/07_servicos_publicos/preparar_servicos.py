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
from datetime import datetime, timezone
import geopandas as gpd

RAW, OUT = "_servicos_raw", "assets/data/servicos"
os.makedirs(OUT, exist_ok=True)

FAIXA_BACIA = {  # contagem plausível DENTRO da bacia — o robô recusa fora disso
    "hospitais": (20, 400), "escolas": (500, 6000), "bombeiros": (8, 200), "ubs": (150, 2500),
}
TIPOS = tuple(sorted(FAIXA_BACIA))

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
    # não fatal: um tipo fora da faixa (ex.: camada de Porto Alegre, que não toca
    # a bacia) é PULADO com aviso — os demais tipos continuam sendo publicados.
    if not (lo <= n <= hi):
        print(f"[AVISO] {tipo}: {n} pontos na bacia (esperado {lo}–{hi}) — "
              f"camada provavelmente não cobre a bacia; NÃO publicado")
        continue
    out.to_file(f"{OUT}/{tipo}.geojson", driver="GeoJSON")
    for cod, k in out.groupby("cod_mun").size().items():
        contagem.setdefault(str(cod), {})[tipo] = int(k)
    ftxt = f"{RAW}/{tipo}_fonte.txt"
    fontes[tipo] = open(ftxt).read().strip() if os.path.exists(ftxt) else "IEDE-RS"

if not fontes:
    raise SystemExit("nenhum tipo de serviço caiu na bacia — verifique as fontes")

nomes = dict(zip(mun["cod_mun"].astype(str), mun["mun_nome"]))
# A ausência de uma feição no cadastro não é uma contagem observada igual a
# zero.  Mantemos ``None`` e um estado explícito por tipo para que consumidores
# possam distinguir "sem ponto publicado" de "zero pontos confirmados".
tipos_publicados = set(fontes)
municipios_saida = []
for cod in sorted(nomes):
    pontos = contagem.get(cod, {})
    registro = {"cod_mun": cod, "nome": nomes[cod]}
    for tipo in sorted(TIPOS):
        if tipo in pontos:
            registro[tipo] = int(pontos[tipo])
            registro[f"{tipo}_status"] = "published"
        else:
            registro[tipo] = None
            registro[f"{tipo}_status"] = "unknown"
    municipios_saida.append(registro)

cobertura = {}
for tipo in sorted(TIPOS):
    valores = [r[tipo] for r in municipios_saida]
    conhecidos = [v for v in valores if v is not None]
    cobertura[tipo] = {
        "municipios_total": len(municipios_saida),
        "municipios_com_ponto": sum(v > 0 for v in conhecidos),
        "municipios_sem_ponto_publicado": len(municipios_saida) - len(conhecidos),
        "pontos_publicados": sum(conhecidos),
        "status": "cadastro_IEDE_parcial_nao_inventario" if tipo in tipos_publicados else "camada_nao_publicada",
    }
with open(f"{OUT}/contagem_municipios.json", "w", encoding="utf-8", newline="\n") as stream:
    json.dump({
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "IEDE-RS (https://iede.rs.gov.br) — recorte: municípios da bacia Taquari-Antas",
        "tipos": sorted(TIPOS),
        "cobertura_por_tipo": cobertura,
        "municipios": municipios_saida,
    }, stream, ensure_ascii=False)
    stream.write("\n")

with open(f"{OUT}/FONTES.md", "w", encoding="utf-8", newline="\n") as fontes_stream:
    fontes_stream.write(
    "# Fontes — pontos de serviços publicados no IEDE-RS\n"
    + "".join(f"- {t}: {u}\n" for t, u in sorted(fontes.items()))
    + "Recorte: pontos dentro dos municípios que intersectam a bacia Taquari-Antas\n"
      "(polígonos municipais simplificados ~120 m — pontos exatamente na divisa podem\n"
      "cair fora). As camadas têm coberturas diferentes e não devem ser tratadas como\n"
      "inventário completo: ausência de ponto não prova ausência do serviço.\n"
      "Os cadastros estaduais consultados estão nas URLs acima.\n")

print("\n== SANIDADE ==")
tot = {t: sum(v.get(t, 0) for v in contagem.values()) for t in fontes}
print("Totais na bacia:", tot)
top = sorted(contagem.items(), key=lambda kv: -sum(kv[1].values()))[:6]
for cod, v in top:
    print(f"  {nomes.get(cod, cod)}: {v}")
print("PROCESSAMENTO COMPLETO ->", OUT)
