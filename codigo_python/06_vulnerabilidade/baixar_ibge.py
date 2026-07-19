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
import json as _json

def _tenta_bacia(url, nome="bacias_rs.geojson"):
    data = get(url)
    txt = data[:200].decode("utf-8", "replace")
    if "FeatureCollection" not in txt and '"features"' not in txt:
        raise RuntimeError(f"resposta não parece GeoJSON: {txt[:80]}")
    open(os.path.join(RAW, nome), "wb").write(data)
    print(f"[ok] bacia <- {url[:110]} ({len(data)//1024} KB)")
    return True

def bacia_geoserver(root):
    for caminho in ("/ows", "/wfs"):
        try:
            caps = get(root + caminho + "?service=WFS&request=GetCapabilities", timeout=60).decode("utf-8", "replace")
        except Exception as e:
            print(f"[bacia] caps {root}{caminho}: {e}"); continue
        nomes = re.findall(r"<Name>([^<]+)</Name>", caps)
        cand = [n for n in nomes if re.search(r"baci|hidrograf", n, re.I)]
        print(f"[bacia] {root}{caminho}: {len(nomes)} camadas, candidatas: {cand[:6]}")
        for layer in cand:
            for of in ("application/json", "json"):
                try:
                    return _tenta_bacia(f"{root}{caminho}?service=WFS&version=2.0.0&request=GetFeature&typeNames={layer}&outputFormat={of}")
                except Exception as e:
                    print(f"[bacia] {layer}/{of}: {e}")
    return False

def bacia_arcgis(root):
    def j(u):
        return _json.loads(get(u, timeout=60))
    try:
        idx = j(root + "?f=json")
    except Exception as e:
        print(f"[bacia] arcgis {root}: {e}"); return False
    servs = [s_["name"] for s_ in idx.get("services", [])]
    for pasta in idx.get("folders", []):
        try:
            servs += [s_["name"] for s_ in j(f"{root}/{pasta}?f=json").get("services", [])]
        except Exception:
            pass
    cand = [s_ for s_ in servs if re.search(r"baci|hidrograf", s_, re.I)]
    print(f"[bacia] {root}: {len(servs)} serviços, candidatos: {cand[:6]}")
    for sv in cand:
        for tipo in ("MapServer", "FeatureServer"):
            try:
                meta = j(f"{root}/{sv}/{tipo}?f=json")
            except Exception:
                continue
            for ly in meta.get("layers", []):
                if not re.search(r"baci", str(ly.get("name", "")), re.I):  continue
                try:
                    return _tenta_bacia(f"{root}/{sv}/{tipo}/{ly['id']}/query?where=1%3D1&outFields=*&returnGeometry=true&f=geojson")
                except Exception as e:
                    print(f"[bacia] {sv}/{ly.get('name')}: {e}")
    return False

ok = False
if os.environ.get("BACIA_URL"):
    try:
        ok = _tenta_bacia(os.environ["BACIA_URL"])
    except Exception as e:
        print(f"[bacia] BACIA_URL falhou: {e}")
if not ok:
    for root in ("https://iede.rs.gov.br/geoserver", "https://ide.sema.rs.gov.br/geoserver",
                 "https://geo.fepam.rs.gov.br/geoserver"):
        if bacia_geoserver(root): ok = True; break
if not ok:
    for root in ("https://iede.rs.gov.br/server/rest/services",
                 "https://iede.rs.gov.br/arcgis/rest/services",
                 "https://portal1.snirh.gov.br/server/rest/services",
                 "https://www.snirh.gov.br/arcgis/rest/services",
                 "https://geoservicos.ana.gov.br/arcgis/rest/services"):
        if bacia_arcgis(root): ok = True; break
if not ok:
    raise RuntimeError("não obtive o limite da bacia — informe bacia_url no Run workflow (geojson)")

print("DOWNLOAD COMPLETO em", RAW)
