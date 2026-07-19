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
             idosos_60_69, idosos_70m, indigenas, domicilios, densidade (hab/km²).

Se um código de coluna do IBGE não bater (layout muda entre releases), o script
IMPRIME o cabeçalho real e falha com mensagem clara — ajustar COLMAP e rodar de novo.
"""
import os, io, json, zipfile, unicodedata
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
    "cor_raca":   {"setor": ["CD_SETOR", "CD_setor"], "indigenas": ["V01321"]},
}

def acha_col(df, cands, tabela, papel):
    for c in cands:
        for v in (c, c.lower(), c.upper()):
            if v in df.columns: return v
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

def prepara(df, tabela, campos):
    cs = COLMAP[tabela]
    sc = acha_col(df, cs["setor"], tabela, "setor")
    d = pd.DataFrame({"setor": df[sc].astype(str).str.strip()})
    for papel in campos:                              # soma as colunas do papel
        total = None
        for code in cs[papel]:
            v = num(df[acha_col(df, [code], tabela, papel)])
            total = v if total is None else total + v
        d[papel] = total.values
    return d[d["setor"].str.startswith("43")]         # RS

bas = prepara(bas, "basico", ["pop", "dom"])
dem = prepara(dem, "demografia", ["mulheres", "c0_4", "c5_9", "i60_69", "i70m"])
cor = prepara(cor, "cor_raca", ["indigenas"])

tab = bas.merge(dem, on="setor", how="left").merge(cor, on="setor", how="left").fillna(0)
setg["setor"] = setg["setor"].astype(str)
g = setg.merge(tab, on="setor", how="left").fillna(0)

# densidade por setor (hab/km²)
akm = g.to_crs(5880).geometry.area / 1e6
g["dens"] = (g["pop"] / akm.replace(0, pd.NA)).fillna(0).round(1)

CAMPOS = ["pop", "dom", "mulheres", "c0_4", "c5_9", "i60_69", "i70m", "indigenas"]

# ---------- saídas ----------
# brutos recortados (auditável)
tab[tab["setor"].str[:7].isin(inter["cod"].astype(str))].to_csv(f"{OUT}/brutos/setores_bacia_indicadores.csv", index=False)

# município: agrega setores
agg = g.groupby("cod_mun")[CAMPOS].sum().reset_index()
m = inter.rename(columns={"cod": "cod_mun"}).merge(agg, on="cod_mun", how="left").fillna(0)
akm_m = m.to_crs(5880).geometry.area / 1e6
m["dens"] = (m["pop"] / akm_m).round(1).values
m["geometry"] = m.to_crs(5880).geometry.simplify(120).to_crs(4326)   # leve p/ visão geral
m.to_file(f"{OUT}/municipios.geojson", driver="GeoJSON")

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
- Malha de setores censitários 2022: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/
- Malha municipal 2022: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2022/
- Limite da bacia Taquari-Antas: {_fonte_bacia}
Os CSVs aqui são o RECORTE dos municípios que intersectam a bacia; o estadual completo está nas URLs acima.
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
assert 800_000 < tot["pop"] < 1_800_000, f"população da bacia suspeita ({int(tot['pop'])}; esperado ~1,2–1,3 milhão)"
assert (m["mulheres"] <= m["pop"]).all(), "mulheres > pop em algum município"
assert all(checks), ("proporções fora do esperado — conferir COLMAP contra o dicionário "
                     "impresso no log do passo de download")
print("PROCESSAMENTO COMPLETO ->", OUT)
