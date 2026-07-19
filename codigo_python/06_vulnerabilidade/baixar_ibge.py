#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBÔ Vulnerabilidade — etapa 1: DOWNLOAD (roda no GitHub Actions).

Baixa para ./_ibge_raw/ :
  1) Malha municipal RS 2022 (IBGE)
  2) Malha de setores censitários RS — Censo 2022 (IBGE)
  3) Agregados por Setores Censitários — Censo 2022: Básico, Demografia, Cor ou raça
     (descobre os arquivos LISTANDO o diretório oficial — resistente a mudança de layout)
  4) Limite da bacia Taquari-Antas (IEDE-RS/FEPAM; pode ser sobrescrito com env BACIA_URL)

Sandbox do Claude NÃO alcança o IBGE (proxy 403) — este script foi feito para o runner.
"""
import os, re, sys, io, zipfile, urllib.request

RAW = "_ibge_raw"
os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "previne-vulnerabilidade/1.0 (projeto FAPERGS 06/2024)"}

def get(url, timeout=300):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def save(url, nome):
    dest = os.path.join(RAW, nome)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"[ok-cache] {nome}")
        return dest
    print(f"[baixando] {url}")
    data = get(url)
    open(dest, "wb").write(data)
    print(f"[ok] {nome} ({len(data)//1024} KB)")
    return dest

def primeiro_que_funciona(cands, nome):
    erros = []
    for u in cands:
        try:
            return save(u, nome)
        except Exception as e:
            erros.append(f"  {u} -> {e}")
    raise RuntimeError(f"nenhum candidato funcionou para {nome}:\n" + "\n".join(erros))

def listar_dir(url):
    """Lista um diretório HTTP do ftp.ibge (HTML) e devolve os hrefs."""
    html = get(url).decode("utf-8", "replace")
    return re.findall(r'href="([^"?/][^"]*)"', html)

# ---------- 1) malha municipal RS 2022 ----------
primeiro_que_funciona([
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2022/UFs/RS/RS_Municipios_2022.zip",
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2023/UFs/RS/RS_Municipios_2023.zip",
], "municipios_rs.zip")

# ---------- 2) malha de setores censitários RS (Censo 2022) ----------
primeiro_que_funciona([
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/setores/gpkg/UF/RS/RS_Malha_Preliminar_2022.gpkg",
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/setores/shp/UF/RS/RS_Malha_Preliminar_2022.zip",
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/setores/gpkg/UF/RS/RS_setores_CD2022.gpkg",
], "setores_rs.bin")   # extensão resolvida na preparação (gpkg ou zip de shp)

# ---------- 3) agregados por setores (descoberta por listagem) ----------
BASES = [
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/",
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/",
]
TEMAS = {  # nome_destino: regex no nome do arquivo
    "agregados_basico.zip":     r"basico.*\.zip$",
    "agregados_demografia.zip": r"demografia.*\.zip$",
    "agregados_cor_raca.zip":   r"cor.*ra.a.*\.zip$",
}
faltando = dict(TEMAS)
for base in BASES:
    if not faltando: break
    try:
        hrefs = listar_dir(base)
    except Exception as e:
        print(f"[aviso] não listei {base}: {e}"); continue
    print(f"[dir] {base} -> {len(hrefs)} itens")
    for nome, rx in list(faltando.items()):
        alvo = [h for h in hrefs if re.search(rx, h, re.I)]
        if alvo:
            save(base + alvo[0], nome)
            faltando.pop(nome)
    # desce um nível em subpastas prováveis
    for sub in [h for h in hrefs if h.endswith("/") and re.search(r"csv|setor", h, re.I)]:
        if not faltando: break
        try:
            hrefs2 = listar_dir(base + sub)
        except Exception:
            continue
        for nome, rx in list(faltando.items()):
            alvo = [h for h in hrefs2 if re.search(rx, h, re.I)]
            if alvo:
                save(base + sub + alvo[0], nome)
                faltando.pop(nome)
if faltando:
    raise RuntimeError(f"agregados não encontrados: {list(faltando)} — revisar BASES/TEMAS")

# ---------- 4) bacia Taquari-Antas ----------
bacia_cands = []
if os.environ.get("BACIA_URL"):
    bacia_cands.append(os.environ["BACIA_URL"])
# IEDE-RS (GeoServer WFS -> GeoJSON) — nomes de camada prováveis
for layer in ("sema:bacias_hidrograficas", "fepam:bacias_hidrograficas",
              "iede:bacias_hidrograficas_rs", "sema:bacia_hidrografica"):
    bacia_cands.append(
        "https://iede.rs.gov.br/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeNames={layer}&outputFormat=application/json")
ok = False
for u in bacia_cands:
    try:
        save(u, "bacias_rs.geojson"); ok = True; break
    except Exception as e:
        print(f"[bacia] falhou {u[:90]}...: {e}")
if not ok:
    # última cartada: descobrir a camada pelo GetCapabilities
    try:
        caps = get("https://iede.rs.gov.br/geoserver/ows?service=WFS&request=GetCapabilities").decode("utf-8","replace")
        nomes = re.findall(r"<Name>([^<]*baci[^<]*)</Name>", caps, re.I)
        print("[bacia] camadas candidatas no IEDE:", nomes[:10])
        for layer in nomes:
            try:
                save("https://iede.rs.gov.br/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature"
                     f"&typeNames={layer}&outputFormat=application/json", "bacias_rs.geojson")
                ok = True; break
            except Exception as e:
                print(f"[bacia] {layer}: {e}")
    except Exception as e:
        print(f"[bacia] GetCapabilities falhou: {e}")
if not ok:
    raise RuntimeError("não obtive o limite da bacia — defina BACIA_URL (geojson/zip de shapefile) e rode de novo")

print("DOWNLOAD COMPLETO em", RAW)
