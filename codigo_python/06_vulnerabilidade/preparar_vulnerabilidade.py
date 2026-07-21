#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBÔ Vulnerabilidade — etapa 2: PROCESSAMENTO (roda no GitHub Actions).

Entrada:  ./_ibge_raw/  (gerado por baixar_ibge.py)
Saída:    assets/data/vulnerabilidade/
  - municipios.geojson            (municípios da bacia + indicadores agregados)
  - setores/<cod_mun>.geojson     (setores simplificados, indicadores por setor)
  - indicadores_municipios.json   (tabela para ranking/busca no site)
  - brutos/*.csv + FONTES.md      (recorte da bacia das tabelas do IBGE)

Indicadores: pop_total, mulheres, criancas_0_4, criancas_5_9,
             idosos_60_69, idosos_70m, indigenas, domicilios, densidade (hab/km²),
             pretos_pardos, dom_agua e dom_esgoto (nº de domicílios com rede geral;
             % contra 'dom'), e renda_resp (rendimento médio mensal do responsável;
             média ponderada pelo nº de responsáveis no município).
             Os opcionais são pulados com aviso se o código IBGE não bater (não
             regridem os que já funcionam). Energia elétrica não consta no
             agregado de domicílios por setor do Censo 2022.

Se um código de coluna do IBGE não bater (layout muda entre releases), o script
IMPRIME o cabeçalho real e falha com mensagem clara — ajustar COLMAP e rodar de novo.
"""
import os, io, json, glob, zipfile, unicodedata
import pandas as pd
import geopandas as gpd

RAW = "_ibge_raw"
OUT = "assets/data/vulnerabilidade"
os.makedirs(f"{OUT}/setores", exist_ok=True)
os.makedirs(f"{OUT}/brutos", exist_ok=True)

# ---- mapeamento de colunas (dicionário dos Agregados por Setores, Censo 2022) ----
# Cada indicador é a SOMA das colunas listadas. Na demografia, as faixas etárias
# vêm separadas por sexo (V01009+ = homens, V01020+ = mulheres) — somamos os dois.
# O passo de download imprime o dicionário oficial no log: conferir lá se mudar.
COLMAP = {
    "basico":     {"setor": ["CD_SETOR", "CD_setor"], "pop": ["V0001"], "dom": ["V0002"]},
    "demografia": {"setor": ["CD_SETOR", "CD_setor"],
                   "mulheres":  ["V01008"],
                   "c0_4":      ["V01009", "V01020"],   # 0–4: homens + mulheres
                   "c5_9":      ["V01010", "V01021"],   # 5–9: homens + mulheres
                   "i60_69":    ["V01018", "V01029"],   # 60–69: homens + mulheres
                   "i70m":      ["V01019", "V01030"]},  # 70+: homens + mulheres
    # cor ou raça: V01317 Branca, V01318 Preta, V01319 Amarela, V01320 Parda, V01321 Indígena
    "cor_raca":   {"setor": ["CD_SETOR", "CD_setor"],
                   "indigenas":     ["V01321"],
                   "pretos_pardos": ["V01318", "V01320"]},   # preta + parda
    # características do domicílio (universo 2022) — códigos confirmados no dicionário:
    # V00111 = utiliza rede geral de distribuição de água; V00309 = destinação do
    # esgoto é rede geral. (Energia elétrica NÃO consta neste agregado por setor.)
    "domicilio":  {"setor": ["setor", "CD_SETOR", "CD_setor"],
                   "dom_agua":   ["V00111"],   # domicílios que usam rede geral de água
                   "dom_esgoto": ["V00309"]},  # domicílios com esgoto em rede geral
    # Rendimento do Responsável por setor (pasta à parte, 2026): V06004 = rendimento
    # médio mensal do responsável; V06001 = nº de responsáveis (peso p/ média municipal).
    "renda":      {"setor": ["CD_SETOR", "CD_setor"],
                   "renda_resp": ["V06004"],
                   "n_resp":     ["V06001"]},
}
# indicadores OPCIONAIS: se as colunas não existirem, o robô avisa e segue.
OPCIONAIS = {"pretos_pardos", "dom_agua", "dom_esgoto", "renda_resp", "n_resp"}

def acha_col(df, cands, tabela, papel, opcional=False):
    for c in cands:
        for v in (c, c.lower(), c.upper()):
            if v in df.columns: return v
    if opcional:
        print(f"[aviso] coluna de '{papel}' ({cands}) não achada em {tabela} — indicador PULADO")
        return None
    print(f"\n[ERRO] coluna de '{papel}' não encontrada na tabela {tabela}.")
    print("Cabeçalho real:", list(df.columns)[:60])
    raise SystemExit(f"ajuste COLMAP['{tabela}']['{papel}'] — o dicionário impresso no "
                     f"passo de download mostra o significado de cada código")

def ler_zip_csv(nome):
    z = zipfile.ZipFile(os.path.join(RAW, nome))
    csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
    # RS = código UF 43; se o zip for BR, filtra depois pelo setor (começa com 43)
    alvo = sorted(csvs, key=lambda n: ("rs" not in n.lower(), len(n)))[0]
    print(f"[csv] {nome} -> {alvo}")
    df = pd.read_csv(z.open(alvo), sep=";", dtype=str, encoding="latin-1")
    if df.shape[1] == 1:  # separador errado
        df = pd.read_csv(z.open(alvo), sep=",", dtype=str, encoding="latin-1")
    return df

def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False), errors="coerce").fillna(0)

def slug(t):
    t = unicodedata.normalize("NFD", str(t)).encode("ascii", "ignore").decode()
    return t.strip()

# ---------- geometria: municípios, setores, bacia ----------
def ler_vetor(path_bin):
    p = os.path.join(RAW, path_bin)
    head = open(p, "rb").read(4)
    if head[:2] == b"PK":   # zip de shapefile
        return gpd.read_file(f"zip://{p}")
    return gpd.read_file(p)  # gpkg/geojson

mun = ler_vetor("municipios_rs.zip").to_crs(4326)
cod_col = next(c for c in mun.columns if c.upper().startswith("CD_MUN"))
nom_col = next(c for c in mun.columns if c.upper().startswith("NM_MUN"))
mun = mun.rename(columns={cod_col: "cod", nom_col: "nome"})[["cod", "nome", "geometry"]]

# contorno do RS para o mini-mapa de localização (dissolve da malha municipal)
_rs = mun.to_crs(5880).union_all().simplify(1000)
gpd.GeoDataFrame({"nome": ["Rio Grande do Sul"]},
                 geometry=gpd.GeoSeries([_rs], crs=5880).to_crs(4326),
                 ).to_file(f"{OUT}/rs_contorno.geojson", driver="GeoJSON")
print("[rs] contorno do estado gerado para o mini-mapa")

bac = gpd.read_file(os.path.join(RAW, "bacias_rs.geojson"))
if bac.crs is None: bac = bac.set_crs(4326)
bac = bac.to_crs(4326)
def _txt(r): return slug(" ".join(map(str, r.drop(labels="geometry").values))).lower()
alvo = bac[bac.apply(lambda r: "taquari" in _txt(r), axis=1)]
com_antas = alvo[alvo.apply(lambda r: "antas" in _txt(r), axis=1)] if len(alvo) else alvo
if len(com_antas): alvo = com_antas                  # evita Taquari-Mirim (rio Pardo) etc.
if alvo.empty and len(bac) <= 5: alvo = bac          # geojson já recortado (BACIA_URL manual)
if alvo.empty:
    print("[ERRO] nenhuma feição com 'Taquari' na camada de bacias. Atributos:", list(bac.columns))
    raise SystemExit("verifique bacias_rs.geojson / BACIA_URL")
bacia = alvo.union_all() if hasattr(alvo, "union_all") else alvo.unary_union
print(f"[bacia] {len(alvo)} feição(ões) 'Taquari' unidas")

inter = mun[mun.geometry.intersects(bacia)].copy()
area = inter.to_crs(5880)
bac_m = gpd.GeoSeries([bacia], crs=4326).to_crs(5880).iloc[0]
area_bacia = bac_m.area / 1e6
print(f"[bacia] área {area_bacia:,.0f} km² (oficial ~26.400 km²)")
assert 20_000 <= area_bacia <= 33_000, f"área da bacia suspeita ({area_bacia:,.0f} km²) — camada errada?"
inter["pct_na_bacia"] = (area.geometry.intersection(bac_m).area / area.geometry.area * 100).round(1).values
inter = inter[inter["pct_na_bacia"] >= 1.0]      # descarta toques de borda irrelevantes
print(f"[municipios] {len(inter)} intersectam a bacia")

setg = ler_vetor("setores_rs.bin").to_crs(4326)
scod = next(c for c in setg.columns if c.upper() in ("CD_SETOR", "CD_SET", "CD_GEO", "CD_SETOR_2022") or c.upper().startswith("CD_SETOR"))
setg = setg.rename(columns={scod: "setor"})
setg["cod_mun"] = setg["setor"].astype(str).str[:7]
setg = setg[setg["cod_mun"].isin(inter["cod"].astype(str))][["setor", "cod_mun", "geometry"]]
print(f"[setores] {len(setg)} setores nos municípios da bacia")

# ---------- tabelas ----------
bas = ler_zip_csv("agregados_basico.zip")
dem = ler_zip_csv("agregados_demografia.zip")
cor = ler_zip_csv("agregados_cor_raca.zip")
def ler_domicilio():
    """O tema Domicílio vem em PARTES (agregados_domicilio_1.zip, _2.zip...) e cada
    parte tem colunas diferentes. Água (V00111) e esgoto (V00309) estão na Parte 2.
    Lê todas as partes e mantém setor + as colunas de que precisamos, juntando."""
    zips = sorted(glob.glob(os.path.join(RAW, "agregados_domicilio_*.zip")))
    if not zips: return None
    precisa = {c.upper() for papel in ("dom_agua", "dom_esgoto") for c in COLMAP["domicilio"].get(papel, [])}
    out = None
    for zp in zips:
        z = zipfile.ZipFile(zp)
        for n in [x for x in z.namelist() if x.lower().endswith(".csv")]:
            df = pd.read_csv(z.open(n), sep=";", dtype=str, encoding="latin-1")
            if df.shape[1] == 1:
                df = pd.read_csv(z.open(n), sep=",", dtype=str, encoding="latin-1")
            # blinda contra BOM/espaço no cabeçalho (a Parte 2 tem formatação diferente)
            df.columns = [str(c).replace("﻿", "").strip() for c in df.columns]
            up = {c.upper(): c for c in df.columns}
            sc = next((up[k] for k in up if k.replace(" ", "").startswith("CD_SETOR")), None)
            achadas = [up[c] for c in precisa if c in up]
            perto = [c for c in df.columns if c.upper().startswith(("V001", "V003"))][:10]
            print(f"[domicilio-diag] {os.path.basename(zp)}/{n}: {df.shape[1]} cols, setor={sc!r}, "
                  f"V00111={'V00111' in up}, V00309={'V00309' in up}, V001x/V003x={perto}")
            if not sc or not achadas: continue
            sub = df[[sc] + achadas].rename(columns={sc: "setor"})
            sub["setor"] = sub["setor"].astype(str).str.strip()
            out = sub if out is None else out.merge(sub, on="setor", how="outer")
            print(f"[domicilio] {os.path.basename(zp)}/{n}: {achadas}")
    return out

dfdom = ler_domicilio()
dfrenda = ler_zip_csv("agregados_renda.zip") if os.path.exists(os.path.join(RAW, "agregados_renda.zip")) else None

def prepara(df, tabela, campos):
    cs = COLMAP[tabela]
    sc = acha_col(df, cs["setor"], tabela, "setor")
    d = pd.DataFrame({"setor": df[sc].astype(str).str.strip()})
    for papel in campos:                              # soma as colunas do papel
        opc = papel in OPCIONAIS
        total = None
        for code in cs[papel]:
            col = acha_col(df, [code], tabela, papel, opcional=opc)
            if col is None:                           # 1º código já não existe → pula o campo
                total = None; break
            v = num(df[col])
            total = v if total is None else total + v
        if total is not None:
            d[papel] = total.values
    return d[d["setor"].str.startswith("43")]         # RS

bas = prepara(bas, "basico", ["pop", "dom"])
dem = prepara(dem, "demografia", ["mulheres", "c0_4", "c5_9", "i60_69", "i70m"])
cor = prepara(cor, "cor_raca", ["indigenas", "pretos_pardos"])

tab = bas.merge(dem, on="setor", how="left").merge(cor, on="setor", how="left")
if dfdom is not None:
    dom = prepara(dfdom, "domicilio", ["dom_agua", "dom_esgoto"])
    tab = tab.merge(dom, on="setor", how="left")
if dfrenda is not None:
    rnd = prepara(dfrenda, "renda", ["renda_resp", "n_resp"])
    tab = tab.merge(rnd, on="setor", how="left")
tab = tab.fillna(0)
setg["setor"] = setg["setor"].astype(str)
g = setg.merge(tab, on="setor", how="left").fillna(0)

# densidade por setor (hab/km²)
akm = g.to_crs(5880).geometry.area / 1e6
g["dens"] = (g["pop"] / akm.replace(0, pd.NA)).fillna(0).round(1)

# setores DENTRO do polígono da bacia (ponto representativo) — valida a
# delineação de verdade e diz quanto de cada município está na bacia
dentro = g.geometry.representative_point().within(bacia)
g["na_bacia"] = dentro.astype(int)
pop_dentro = float(g.loc[dentro, "pop"].sum())

# campos SOMÁVEIS (base + opcionais que entraram). Renda é MÉDIA (não soma) — tratada à parte.
CAMPOS = ["pop", "dom", "mulheres", "c0_4", "c5_9", "i60_69", "i70m", "indigenas"]
CAMPOS += [c for c in ("pretos_pardos", "dom_agua", "dom_esgoto", "n_resp") if c in g.columns]
tem_renda = "renda_resp" in g.columns
print("[campos] indicadores publicados:", CAMPOS + (["renda_resp (média)"] if tem_renda else []))

# ---------- saídas ----------
# brutos recortados (auditável), com flag de setor dentro do polígono
rec = tab[tab["setor"].str[:7].isin(inter["cod"].astype(str))].copy()
rec["na_bacia"] = rec["setor"].map(dict(zip(g["setor"], g["na_bacia"]))).fillna(0).astype(int)
rec.to_csv(f"{OUT}/brutos/setores_bacia_indicadores.csv", index=False)

# município: agrega setores
agg = g.groupby("cod_mun")[CAMPOS].sum().reset_index()
m = inter.rename(columns={"cod": "cod_mun"}).merge(agg, on="cod_mun", how="left").fillna(0)
akm_m = m.to_crs(5880).geometry.area / 1e6
m["dens"] = (m["pop"] / akm_m).round(1).values
popb = g.loc[dentro].groupby("cod_mun")["pop"].sum()
m["pop_bacia"] = m["cod_mun"].map(popb).fillna(0).astype(int)   # pop do município DENTRO da bacia

# renda do responsável no município = MÉDIA PONDERADA pelo nº de responsáveis
# (renda_resp é média por setor; somar não faz sentido)
if tem_renda:
    gr = g[g["n_resp"] > 0]
    num = (gr["renda_resp"] * gr["n_resp"]).groupby(gr["cod_mun"]).sum()
    den = gr["n_resp"].groupby(gr["cod_mun"]).sum()
    m["renda_resp"] = (m["cod_mun"].map(num) / m["cod_mun"].map(den)).round(0).fillna(0)
m["geometry"] = m.to_crs(5880).geometry.simplify(120).to_crs(4326)   # leve p/ visão geral
m.to_file(f"{OUT}/municipios.geojson", driver="GeoJSON")

# contorno da bacia (para o mapa)
gpd.GeoDataFrame({"nome": ["Bacia Taquari-Antas"]},
                 geometry=[gpd.GeoSeries([bacia], crs=4326).to_crs(5880).simplify(100).to_crs(4326).iloc[0]],
                 crs=4326).to_file(f"{OUT}/bacia.geojson", driver="GeoJSON")

# setores por município (simplificados)
g["geometry"] = g.to_crs(5880).geometry.simplify(15).to_crs(4326)
for cod, gg in g.groupby("cod_mun"):
    gg.drop(columns=["cod_mun"]).to_file(f"{OUT}/setores/{cod}.geojson", driver="GeoJSON")

json.dump({
    "fonte": "IBGE — Censo Demográfico 2022, Agregados por Setores Censitários",
    "municipios": m.drop(columns="geometry").to_dict("records"),
}, open(f"{OUT}/indicadores_municipios.json", "w"), ensure_ascii=False)

_fonte_bacia = "IEDE-RS (https://iede.rs.gov.br)"
_fp = os.path.join(RAW, "bacia_fonte.txt")
if os.path.exists(_fp):
    _fonte_bacia = open(_fp).read().strip()
open(f"{OUT}/brutos/FONTES.md", "w").write(
f"""# Fontes (dados completos oficiais)
- Agregados por Setores Censitários — Censo 2022: https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/
  Temas usados: Básico (população, domicílios), Demografia (faixas etárias por sexo),
  Cor ou raça (indígenas; pretos + pardos), Domicílio (água por rede geral, esgoto por rede geral).
- Rendimento do Responsável por setor — Censo 2022 (pasta à parte, publicada em 2026):
  https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/
  Variável V06004 = rendimento nominal médio mensal das pessoas responsáveis.
- Malha de setores censitários 2022: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/
- Malha municipal 2022: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2022/
- Limite da bacia Taquari-Antas: {_fonte_bacia}
Os CSVs aqui são o RECORTE dos municípios que intersectam a bacia; o estadual completo está nas URLs acima.
Energia elétrica não consta no agregado de características do domicílio por setor (Censo 2022).
""")

# sanidade — o robô RECUSA publicar dados fora do plausível
print("\n== SANIDADE ==")
print(m[["nome", "pop", "dom", "dens", "pct_na_bacia"]].sort_values("pop", ascending=False).head(8).to_string(index=False))
tot = m[CAMPOS].sum()
print("Totais bacia:", {k: int(v) for k, v in tot.items()})

def faixa(nome, valor, lo, hi):
    frac = valor / tot["pop"]
    ok = lo <= frac <= hi
    print(f"  {nome}: {frac*100:.2f}% da pop (esperado {lo*100:.1f}–{hi*100:.1f}%) {'OK' if ok else '** FORA **'}")
    return ok

checks = [
    faixa("mulheres",      tot["mulheres"],  0.49,   0.54),
    faixa("crianças 0-4",  tot["c0_4"],      0.035,  0.075),
    faixa("crianças 5-9",  tot["c5_9"],      0.040,  0.080),
    faixa("idosos 60-69",  tot["i60_69"],    0.055,  0.110),
    faixa("idosos 70+",    tot["i70m"],      0.045,  0.100),
    faixa("indígenas",     tot["indigenas"], 0.0002, 0.020),
]
# indicadores novos: só INFORMATIVO (não derruba o robô) — serve para conferir os
# códigos IBGE no log antes de confiar no dado. Faixas plausíveis no RS:
#   pretos+pardos ~15–35% da pop; energia ~98–100%, água por rede ~80–99%,
#   esgoto por rede ~40–90% dos domicílios.
if "pretos_pardos" in CAMPOS:
    print(f"  pretos+pardos: {tot['pretos_pardos']/tot['pop']*100:.1f}% da pop "
          f"(esperado ~15–35%) {'OK' if 0.08 <= tot['pretos_pardos']/tot['pop'] <= 0.45 else '** CONFERIR CÓDIGO **'}")
for k, lab, lo, hi in [("dom_agua","água rede",0.55,1.01), ("dom_esgoto","esgoto rede",0.20,1.01)]:
    if k in CAMPOS:
        frac = tot[k]/tot["dom"] if tot["dom"] else 0
        print(f"  {lab}: {frac*100:.1f}% dos domicílios (esperado {lo*100:.0f}–100%) "
              f"{'OK' if lo <= frac <= hi else '** CONFERIR CÓDIGO **'}")
if tem_renda:
    rr = m.loc[m["renda_resp"] > 0, "renda_resp"]
    md = float(rr.median()) if len(rr) else 0
    print(f"  renda do responsável: mediana municipal R$ {md:,.0f} "
          f"(esperado ~R$ 1.500–4.500) {'OK' if 800 <= md <= 8000 else '** CONFERIR CÓDIGO **'}")
print(f"População dos municípios que TOCAM a bacia (inteiros): {int(tot['pop']):,}")
print(f"População DENTRO do polígono da bacia (setores): {int(pop_dentro):,}")
assert 900_000 < pop_dentro < 1_700_000, (f"população dentro da bacia suspeita ({int(pop_dentro):,}; "
                                          f"esperado ~1,2–1,3 milhão) — delineação errada?")
assert (m["mulheres"] <= m["pop"]).all(), "mulheres > pop em algum município"
assert all(checks), ("proporções fora do esperado — conferir COLMAP contra o dicionário "
                     "impresso no log do passo de download")
print("PROCESSAMENTO COMPLETO ->", OUT)
