#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ROTA DE FUGA POR RUAS (Etapa 2) — Santa Tereza e Muçum.

Roteamento REAL a pé ate o ponto de encontro/abrigo oficial mais proximo.
A origem e cada edificacao (casa a casa):
  1. REDE   -> vias do OpenStreetMap transitaveis a pe (ruas, caminhos,
               escadarias), cacheadas por cidade.
  2. RELEVO -> cota de cada no tirada do MDT mosaico 2 m. O custo de cada
               trecho e TEMPO de caminhada (idoso, 0,9 m/s no plano) com a
               rampa do r.walk do GRASS (Naismith + correcao de Langmuir):
               subir custa mais, descer suave ajuda, descer ingreme custa.
               Grafo direcionado: ida e volta do mesmo trecho custam diferente.
  3. AGUA   -> raster da cota que alaga cada pixel (gerar_cota_alaga.py, HAND
               ligado ao rio, 0-25 m). Cada trecho guarda o perfil amostrado
               a cada 4 m; no nivel L, a FRACAO do trecho abaixo de L e
               penalizada (nao apagada: quem esta dentro precisa poder sair).
               Ponte so alaga se uma das cabeceiras alaga.
  4. ABRIGOS-> pontos de encontro oficiais (abrigos.geojson, filtrados pela
               cidade). Abrigo que alaga no nivel sai do roteamento.
  5. CASAS  -> edificacoes do OSM. Cada casa liga na via mais proxima
               (pe da perpendicular) e herda o caminho desse ponto ao abrigo.
               Situacao: ok, excede (na agua e acima do tempo maximo), ilhada
               (fora da agua, mas a rota cruza agua) ou sem_rota.
  6. CANDIDATOS -> casas na mancha acima de --tempo-max, casas em trechos de
               rede sem caminho ate abrigo oficial (outra margem) e casas
               ilhadas recebem LOCAIS CANDIDATOS (2 m acima do nivel, rampa ate
               15 %) por cobertura gulosa: cada novo local e o que atende mais
               casas ainda sem solucao em ate --tempo-max. Diagnostico para a Defesa
               Civil validar — nao substitui os pontos oficiais. A demanda
               (pessoas IBGE divididas pelas casas) sai por destino.
  7. NIVEIS -> alem do nivel de projeto, rotas recalculadas de 0 a 25 m HAND
               (passo 1 m) para o painel, a margem e o impacto.
  8. SAIDA  -> JSON (rede + casas + candidatos + niveis) e HTML Leaflet:
               clique numa casa e veja a rota ate o abrigo.

Metodo de tempo com declive e pontos de encontro dinamicos inspirados em
Gandra Franco, G. (2026), doi:10.5281/zenodo.20402230.

Nivel da mancha (--fonte):
  live    -> le a previsao ao vivo (RNA) e usa o PICO (atual/2h/4h); rio abaixo
             do bankfull => sem mancha. Telemetria com mais de 3 h e marcada.
  cenario -> cota oficial de inundacao da cidade.
  fixo    -> nivel HAND passado em --nivel.

Uso:
  python codigo_python/09_rota_fuga/gerar_cota_alaga.py mucum     (uma vez por MDT)
  python codigo_python/09_rota_fuga/gerar_rota_fuga_ruas.py --cidade santa_tereza
  python codigo_python/09_rota_fuga/gerar_rota_fuga_ruas.py --cidade mucum --fonte live
  python codigo_python/09_rota_fuga/gerar_rota_fuga_ruas.py --cidade mucum --fonte cenario
"""
import os, json, math, time, argparse, datetime as dt
import urllib.request, urllib.parse
import numpy as np
import networkx as nx
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape, Point, LineString, Polygon, GeometryCollection
from shapely.ops import unary_union
from shapely.strtree import STRtree

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ABRIGOS = os.path.join(RAIZ, "assets", "data", "servicos", "abrigos.geojson")
PENAL_AGUA = 60.0
CACHE_DIAS = 30
SNAP_CASA_M = 80.0          # casa mais longe que isso da via fica sem rota
IGNORAR_BUILDING = {
    "roof", "ruins", "construction", "proposed", "bridge", "greenhouse",
    "garage", "shed", "garages", "service", "bunker", "collapsed",
    "transformer_tower", "pavilion",
    # não residenciais: ninguém mora (o abrigo oficial entra à parte)
    "industrial", "warehouse", "commercial", "retail", "office", "supermarket", "kiosk",
    "school", "university", "college", "kindergarten", "hospital", "public", "civic",
    "government", "church", "chapel", "cathedral", "religious", "temple", "mosque",
    "train_station", "transportation", "sports_hall", "sports_centre", "stadium", "grandstand",
    "hangar", "barn", "stable", "cowshed", "sty", "silo", "storage_tank", "farm_auxiliary",
    "parking", "toilets", "gatehouse", "water_tower",
}
CASA_AREA_MIN_M2 = 20.0     # menor que isso e anexo/abrigo de carro
CASA_AREA_MAX_M2 = 1000.0   # maior que isso e galpao, ginasio, escola
VIAS_EXCLUIDAS = "motorway|motorway_link|construction|proposed|raceway|bus_guideway|escape|elevator|platform|abandoned|razed"
SO_PE = {"footway", "path", "steps", "pedestrian", "corridor", "bridleway"}
MARGEM_VIAS_GRAUS = 0.015

# r.walk (GRASS) em s/m para o caminhante de referencia (0,72 s/m = 1,39 m/s).
VEL_IDOSO = 0.9
RW_A, RW_B, RW_C, RW_D = 0.72, 6.0, 1.9998, -1.9998
RW_RAMPA_INGREME = -0.2125
FATOR_IDOSO = 1.0 / (RW_A * VEL_IDOSO)     # escala o r.walk para 0,9 m/s no plano
VEL_MAX_DESCIDA = 1.1       # idoso nao desce mais rapido que isso, mesmo em descida suave
RAMPA_MAX = 0.35            # rampas maiores no MDT em via sao ruido (muro, talude, ponte)
FATOR_ESCADA = 1.5

COTA_NAO_ALAGA = 65535      # gerar_cota_alaga.py: nao alaga ate NIVEL_MAX_M
NIVEL_MAX_M = 25.0
PASSO_PERFIL_M = 4.0
NIVEIS_ROTA_M = [float(n) for n in range(0, int(NIVEL_MAX_M) + 1)]
AGUA_ILHADA_M = 0.0         # casa seca cuja rota cruza qualquer agua fica "ilhada" (mesma regra do painel)
TELEMETRIA_VELHA_MIN = 180

TEMPO_MAX_MIN = 30.0
CAND_FOLGA_COTA_M = 2.0     # candidato so alaga pelo menos 2 m acima do nivel de projeto
CAND_RAMPA_MAX = 0.15
CAND_GANHO_MIN = 5          # novo candidato precisa atender 5 casas ainda sem solucao...
CAND_URG_MIN = 3            # ... ou 3 na agua / sem rota
CAND_MAX = 8
MIN_COMP_NOS = 50           # trecho de rede desconectado menor que isso e ruido do OSM

CASAS_CAMPOS = ["lat", "lon", "proj_lat", "proj_lon", "no", "abrigo", "dist_m",
                "agua_m", "na_mancha", "tempo_s", "subida_m", "excede",
                "tempo_direto_s", "agua_direto_m", "cota_alaga", "situacao",
                "cand", "tempo_cand_s", "no_cand", "pessoas"]

CIDADES = {
    "santa_tereza": {
        "slug": "santa_tereza", "municipio": "Santa Tereza", "cod": "4317251",
        "bbox": dict(S=-29.192, N=-29.158, W=-51.748, E=-51.718),
        "contornos": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "contornos_mancha.json"),
        "mdt": os.path.join(RAIZ, "assets", "data", "santa_tereza_inundacao", "mdt", "mdt_santa_tereza_mosaico_2m.tif"),
        "forecast": os.path.join(RAIZ, "previsao_ao_vivo.json"),
        # Calibração de campo: régua 1,60 m = HAND 0 no rio principal, válida só
        # sobre o HAND LiDAR de contornos_mancha.json (gerar_hand_lidar_santa_tereza.py);
        # por isso a cota de alagamento sai dos contornos e não do mosaico 2 m.
        "zero_regua_m": 1.6, "nivel_padrao": 13.4, "cenario_regua_cm": 1500.0,
        "cota_de_contornos": True,
        "alarmes_regua_m": {"inundacao": 15.0},
        "html": os.path.join(RAIZ, "santa_tereza_rota_fuga_ruas{suf}.html"),
    },
    "mucum": {
        "slug": "mucum", "municipio": "Muçum", "cod": "4312609",
        "bbox": dict(S=-29.171, N=-29.150, W=-51.892, E=-51.855),
        "contornos": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "contornos_mancha.json"),
        "mdt": os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_mosaico_2m.tif"),
        "forecast": os.path.join(RAIZ, "previsao_ao_vivo_mucum.json"),
        # Mesmo bankfull operacional da mancha/RNA (gerar_mancha_mucum.py,
        # gerar_previsao_ao_vivo_mucum.py, mucum_inundacao.html): 500 cm na
        # régua 86510000 = cota de atenção do Plano de Contingência. HAND 0
        # quando o rio deixa a calha. Definitivo ainda depende do RN SGB/ANA.
        "zero_regua_m": 5.0, "nivel_padrao": 8.0, "cenario_regua_cm": 1800.0,
        "alarmes_regua_m": {"atencao": 5.0, "alerta": 10.0, "inundacao": 18.0},
        "html": os.path.join(RAIZ, "mucum_rota_fuga_ruas{suf}.html"),
    },
}


def haversine(lon1, lat1, lon2, lat2):
    R = 6371000.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def cache_osm(cfg):
    return os.path.join(RAIZ, "assets", "data", "rota_fuga", f"osm_vias_pe_ampla_{cfg['slug']}.json")


def cache_casas(cfg):
    return os.path.join(RAIZ, "assets", "data", "rota_fuga", f"osm_casas_{cfg['slug']}.json")


def caminhos_saida(cfg, fonte):
    suf = {"live": "", "cenario": "_cenario", "fixo": "_fixo"}.get(fonte, "")
    return (os.path.join(RAIZ, "assets", "data", "rota_fuga", f"rota_fuga_ruas_{cfg['slug']}{suf}.json"),
            cfg["html"].format(suf=suf))


def _idade_min(iso):
    try:
        return round((dt.datetime.now() - dt.datetime.fromisoformat(iso)).total_seconds() / 60.0)
    except (TypeError, ValueError):
        return None


def nivel_de_projeto(cfg, fonte, nivel_fixo):
    """Devolve (hand_m, meta) do nivel de inundacao a evitar."""
    z = cfg["zero_regua_m"]
    extra = {"bankfull_m": z, "alarmes_regua_m": cfg.get("alarmes_regua_m") or {}}
    if fonte == "fixo":
        extra["calibrar_regua"] = z is None
        return nivel_fixo, {"fonte": "fixo", "rotulo": f"nivel fixo HAND {nivel_fixo:.1f} m", **extra}
    if z is None:
        raise SystemExit(f"{cfg['slug']}: sem zero_regua_m — use --fonte fixo --nivel HAND")
    if fonte == "cenario":
        regua = cfg["cenario_regua_cm"] or (z + 7.0) * 100
        rotulo = f"cenário de inundação oficial (régua {regua/100:.0f} m)"
        return regua/100.0 - z, {"fonte": "cenario", "rotulo": rotulo,
                                 "nivel_regua_cm": regua, **extra}
    d = json.load(open(cfg["forecast"], encoding="utf-8"))
    atual = d.get("telemetria_ultima_nivel_cm") or d.get("nivel_atual_cm") or 0
    niveis = [atual]
    for hk in ("2h", "4h"):
        hv = (d.get("horizontes") or {}).get(hk) or {}
        if hv.get("disponivel") is False:
            continue
        niveis += [p[2] for p in hv.get("passos") or [] if len(p) > 2 and p[2] is not None]
    pico_cm = max(niveis); hand = pico_cm/100.0 - z
    idade = _idade_min(d.get("telemetria_ultima_em"))
    return hand, {"fonte": "live", "rotulo": "previsão ao vivo (RNA 2h/4h)",
                  "nivel_atual_cm": atual, "nivel_pico_cm": pico_cm,
                  "telemetria_em": d.get("telemetria_ultima_em"), "idade_telemetria_min": idade,
                  "dados_desatualizados": idade is None or idade > TELEMETRIA_VELHA_MIN,
                  "transbordando": hand > 0, **extra}


def _baixa_overpass(query, cache, rotulo):
    if os.path.exists(cache):
        idade = (time.time() - os.path.getmtime(cache)) / 86400.0
        if idade <= CACHE_DIAS:
            print(f"{rotulo} do cache ({idade:.1f} dias): {cache}")
            return json.load(open(cache, encoding="utf-8"))
    eps = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
    for ep in eps:
        try:
            print(f"baixando {rotulo} de {ep} ...")
            req = urllib.request.Request(ep, data=("data=" + urllib.parse.quote(query)).encode(),
                                         headers={"User-Agent": "previne-rota-fuga/1.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=120).read())
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            json.dump(d, open(cache, "w", encoding="utf-8"))
            return d
        except Exception as e:
            print(f"  falhou: {str(e)[:70]}"); time.sleep(3)
    raise RuntimeError(f"Overpass indisponivel e sem cache ({rotulo})")


def baixa_osm(cfg):
    """Vias transitáveis a pé: ruas, caminhos, calçadões e escadarias.

    O recorte das vias é maior que o das casas: estradas que saem do recorte
    urbano só se ligam à cidade por fora dele.
    """
    bb = cfg["bbox"]; m = MARGEM_VIAS_GRAUS
    q = (f'[out:json][timeout:120];'
         f'way["highway"]["highway"!~"{VIAS_EXCLUIDAS}"]["foot"!="no"]["area"!="yes"]'
         f'({bb["S"] - m},{bb["W"] - m},{bb["N"] + m},{bb["E"] + m});(._;>;);out body;')
    return _baixa_overpass(q, cache_osm(cfg), f"vias OSM ({cfg['slug']})")


def baixa_casas(cfg):
    """Edificações OSM (ways e nós com tag building) no mesmo recorte das ruas."""
    bbox = cfg["bbox"]
    q = (f'[out:json][timeout:90];'
         f'(way["building"]({bbox["S"]},{bbox["W"]},{bbox["N"]},{bbox["E"]});'
         f'node["building"]({bbox["S"]},{bbox["W"]},{bbox["N"]},{bbox["E"]}););'
         f'out body; >; out skel qt;')
    return _baixa_overpass(q, cache_casas(cfg), f"casas OSM ({cfg['slug']})")


def _geom_casa(coords):
    if len(coords) >= 4:
        ring = coords if coords[0] == coords[-1] else coords + [coords[0]]
        g = Polygon(ring)
        if not g.is_valid:
            g = g.buffer(0)
        if not g.is_empty:
            if g.geom_type == "MultiPolygon":
                g = max(g.geoms, key=lambda p: p.area)
            if g.geom_type == "Polygon" and g.area > 0:
                return g
    if len(coords) >= 2:
        return LineString(coords)
    return Point(coords[0])


def _origem_casa(geom):
    if geom.geom_type == "Polygon":
        return geom.representative_point()
    if geom.geom_type == "LineString":
        return geom.interpolate(0.5, normalized=True)
    return geom.centroid


def casas_de_osm(osm):
    """Uma origem por edificação residencial: ponto interno do polígono (ou o próprio nó).

    Fica de fora tag não residencial e polígono fora de CASA_AREA_MIN_M2..CASA_AREA_MAX_M2.
    """
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in osm["elements"] if e["type"] == "node" and "lon" in e}
    vistos = set(); out = []
    for e in osm["elements"]:
        tags = e.get("tags") or {}
        if "building" not in tags or e["id"] in vistos:
            continue
        tag = tags.get("building") or "yes"
        if tag in IGNORAR_BUILDING:
            continue
        vistos.add(e["id"])
        if e["type"] == "node" and "lon" in e:
            geom = Point(e["lon"], e["lat"])
        elif e["type"] == "way":
            coords = [nodes[n] for n in e.get("nodes") or [] if n in nodes]
            if len(coords) < 2:
                continue
            geom = _geom_casa(coords)
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type == "Polygon":
                c = geom.centroid
                area = geom.area * 111320.0 * math.cos(math.radians(c.y)) * 110540.0
                if not CASA_AREA_MIN_M2 <= area <= CASA_AREA_MAX_M2:
                    continue
        else:
            continue
        p = _origem_casa(geom)
        out.append({"id": e["id"], "tag": tag, "lon": p.x, "lat": p.y, "geom": geom})
    return out


def carrega_mancha(cfg, nivel):
    d = json.load(open(cfg["contornos"], encoding="utf-8"))
    niveis = sorted({f["properties"]["nivel_m"] for f in d["features"]})
    if nivel <= min(niveis):
        return GeometryCollection(), 0.0
    nn = min(niveis, key=lambda x: abs(x - nivel))
    ps = [shape(f["geometry"]).buffer(0) for f in d["features"] if abs(f["properties"]["nivel_m"] - nn) < 1e-6]
    return unary_union(ps), nn


class Inundacao:
    """Cota (m HAND) em que cada ponto alaga, do raster de gerar_cota_alaga.py.

    `cota` devolve inf para "não alaga até 25 m" e para pontos fora do raster.
    """

    def __init__(self, cfg):
        caminho = os.path.join(RAIZ, "assets", "data", "rota_fuga", f"cota_alaga_{cfg['slug']}.tif")
        if not os.path.exists(caminho):
            raise SystemExit(f"falta {caminho}: rode gerar_cota_alaga.py {cfg['slug']}")
        with rasterio.open(caminho) as r:
            self.a = r.read(1)
            self.tr = r.transform
        self.inv = ~self.tr
        self.cfg = cfg
        self.max_contorno = None

    def cota(self, lons, lats):
        lons = np.atleast_1d(np.asarray(lons, dtype=float))
        lats = np.atleast_1d(np.asarray(lats, dtype=float))
        col, lin = self.inv * (lons, lats)
        col = np.floor(col).astype(int); lin = np.floor(lin).astype(int)
        h, w = self.a.shape
        ok = (col >= 0) & (col < w) & (lin >= 0) & (lin < h)
        out = np.full(lons.shape, np.inf)
        v = self.a[lin[ok], col[ok]].astype(float)
        out[ok] = np.where(v >= COTA_NAO_ALAGA, np.inf, v / 10.0)
        return out

    def cota_geom(self, geom):
        """Menor cota entre o ponto interno e os vértices da edificação."""
        if geom.geom_type == "Polygon":
            xy = list(geom.exterior.coords) + [tuple(geom.representative_point().coords[0])]
        else:
            xy = list(geom.coords)
        a = np.asarray(xy)
        return float(self.cota(a[:, 0], a[:, 1]).min())

    def mancha(self, nivel):
        """Polígono para exibir: contornos do site até 15 m; acima, o próprio raster."""
        if nivel <= 0:
            return GeometryCollection(), 0.0
        if self.max_contorno is None:
            d = json.load(open(self.cfg["contornos"], encoding="utf-8"))
            self.max_contorno = max(f["properties"]["nivel_m"] for f in d["features"])
        if nivel <= self.max_contorno + 0.05:
            return carrega_mancha(self.cfg, nivel)
        m = (self.a <= round(min(nivel, NIVEL_MAX_M) * 10)).astype(np.uint8)
        ps = [shape(g) for g, _v in shapes(m, mask=m.astype(bool), transform=self.tr)]
        return unary_union(ps).simplify(0.00004), round(min(nivel, NIVEL_MAX_M), 1)


def carrega_abrigos(cfg):
    d = json.load(open(ABRIGOS, encoding="utf-8")); out = []
    for f in d["features"]:
        p = f["properties"]
        if p.get("municipio") != cfg["municipio"]:
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        out.append({"id": p.get("id"), "nome": p.get("nome"), "lon": lon, "lat": lat})
    return out


def cotas_dos_nos(cfg, osm):
    """Cota (m) do MDT em cada nó das vias; None fora do raster ou sem dado."""
    nodes = [(e["id"], e["lon"], e["lat"]) for e in osm["elements"] if e["type"] == "node" and "lon" in e]
    if not nodes or not os.path.exists(cfg.get("mdt") or ""):
        print("MDT ausente: tempo sem declive")
        return {}
    out = {}
    with rasterio.open(cfg["mdt"]) as r:
        nd = r.nodata
        for (nid, _lo, _la), v in zip(nodes, r.sample([(lo, la) for _n, lo, la in nodes])):
            z = float(v[0])
            out[nid] = None if (nd is not None and z == nd) or not math.isfinite(z) else z
    ok = sum(z is not None for z in out.values())
    print(f"cotas MDT: {ok}/{len(out)} nos")
    return out


def tempo_trecho(d, dh, escada=False):
    """Segundos de caminhada (idoso) num trecho de d metros com desnível dh (+ sobe)."""
    if d <= 0:
        return 0.0
    rampa = max(-RAMPA_MAX, min(RAMPA_MAX, dh / d))
    dh = rampa * d
    t = RW_A * d
    if dh > 0:
        t += RW_B * dh
    elif dh < 0:
        t += (RW_C if rampa > RW_RAMPA_INGREME else RW_D) * dh
    t = max(t * FATOR_IDOSO, d / VEL_MAX_DESCIDA)
    return t * (FATOR_ESCADA if escada else 1.0)


def _perfil_linha(p1, p2, comp):
    """Pontos a cada PASSO_PERFIL_M entre p1 e p2 (lon, lat), pontas incluídas."""
    n = max(2, int(math.ceil(comp / PASSO_PERFIL_M)) + 1)
    f = np.linspace(0.0, 1.0, n)
    return p1[0] + (p2[0] - p1[0]) * f, p1[1] + (p2[1] - p1[1]) * f


def monta_grafo(osm, cotas, inund, min_comp=None):
    """Grafo direcionado das vias a pé, sem nível: use aplica_nivel antes de rotear.

    Arestas: comp (m), t (s), dh, perfil (cotas de alagamento ao longo do trecho).
    Nós: lon, lat, z (MDT), hand (cota em que o nó alaga) e comp (0 = rede
    principal). min_comp=None guarda só a rede principal; senão, também os
    trechos desconectados com pelo menos min_comp nós.
    """
    cotas = cotas or {}
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in osm["elements"] if e["type"] == "node"}
    ways = [e for e in osm["elements"] if e["type"] == "way" and "nodes" in e]
    trechos, xs, ys = [], [], []
    for w in ways:
        tags = w.get("tags", {})
        nd = [n for n in w["nodes"] if n in nodes]
        if len(nd) < 2:
            continue
        hw = tags.get("highway", "")
        elevada = tags.get("bridge", "no") != "no" or tags.get("tunnel", "no") != "no"
        comps = [haversine(*nodes[a], *nodes[b]) for a, b in zip(nd, nd[1:])]
        total = sum(comps) or 1.0
        za, zb = cotas.get(nd[0]), cotas.get(nd[-1])
        for (a, b), comp in zip(zip(nd, nd[1:]), comps):
            if a == b:
                continue
            if elevada:
                dh = (zb - za) * comp / total if za is not None and zb is not None else 0.0
                # ponte/túnel: alaga quando alguma cabeceira do way alaga
                px, py = [nodes[nd[0]][0], nodes[nd[-1]][0]], [nodes[nd[0]][1], nodes[nd[-1]][1]]
            else:
                z1, z2 = cotas.get(a), cotas.get(b)
                dh = (z2 - z1) if z1 is not None and z2 is not None else 0.0
                px, py = _perfil_linha(nodes[a], nodes[b], comp)
            i0 = len(xs); xs.extend(px); ys.extend(py)
            trechos.append((a, b, comp, dh, hw, tags.get("name", ""), elevada, i0, len(xs)))
    cz = inund.cota(xs, ys) if xs else np.array([])
    G = nx.DiGraph()
    for a, b, comp, dh, hw, nome, elevada, i0, i1 in trechos:
        perfil = cz[i0:i1].min(keepdims=True) if elevada else cz[i0:i1].astype(np.float32)
        for u, v, s in ((a, b, 1.0), (b, a, -1.0)):
            t = tempo_trecho(comp, s * dh, hw == "steps")
            if G.has_edge(u, v) and G[u][v]["t"] <= t:
                continue
            G.add_edge(u, v, comp=comp, t=t, peso=t, dh=s * dh, alaga=0.0, perfil=perfil,
                       nome=nome, so_pe=hw in SO_PE, elevada=elevada)
    ids = list(G.nodes)
    hand = inund.cota([nodes[n][0] for n in ids], [nodes[n][1] for n in ids])
    for nid, h in zip(ids, hand):
        lo, la = nodes[nid]
        G.nodes[nid].update(lon=lo, lat=la, z=cotas.get(nid), hand=float(h))
    comps = sorted(nx.weakly_connected_components(G), key=len, reverse=True)
    comps = comps[:1] if min_comp is None else [c for k, c in enumerate(comps) if k == 0 or len(c) >= min_comp]
    for k, c in enumerate(comps):
        for n in c:
            G.nodes[n]["comp"] = k
    return G.subgraph(set().union(*comps)).copy()


def aplica_nivel(G, nivel):
    """Fração alagada e peso de cada aresta no nível HAND dado. Devolve nº de trechos com água."""
    n = 0
    for _u, _v, e in G.edges(data=True):
        f = float(np.count_nonzero(e["perfil"] <= nivel)) / len(e["perfil"])
        e["alaga"] = f
        e["peso"] = e["t"] * (1.0 + PENAL_AGUA * f)
        n += f > 0
    return n // 2


def snap(G, lon, lat, nos=None):
    return min(G.nodes if nos is None else nos,
               key=lambda n: haversine(lon, lat, G.nodes[n]["lon"], G.nodes[n]["lat"]))


def roteia(G, fontes, peso_aresta="peso"):
    """Caminho de menor custo de cada nó até a fonte mais próxima.

    fontes: {no: id_destino}. Devolve dicts por nó: prox, destino, peso, dist, agua, t, subida.
    peso_aresta="t" ignora a penalidade de água (rota direta).
    """
    R = G.reverse(copy=False)
    peso, paths = nx.multi_source_dijkstra(R, set(fontes), weight=peso_aresta)
    out = {"prox": {}, "destino": {}, "peso": peso, "dist": {}, "agua": {}, "t": {}, "subida": {}}
    for n, cam in paths.items():
        out["destino"][n] = fontes[cam[0]]
        out["prox"][n] = cam[-2] if len(cam) > 1 else n
        dr = ag = tt = sb = 0.0
        for x, y in zip(cam, cam[1:]):
            e = R[x][y]
            dr += e["comp"]; ag += e["comp"] * e["alaga"]; tt += e["t"]; sb += max(e["dh"], 0.0)
        out["dist"][n] = dr; out["agua"][n] = ag; out["t"][n] = tt; out["subida"][n] = sb
    return out


def _xy(lon, lat, lon0, lat0):
    kx = 111320.0 * math.cos(math.radians(lat0))
    return (lon - lon0) * kx, (lat - lat0) * 110540.0


def _ll(x, y, lon0, lat0):
    kx = 111320.0 * math.cos(math.radians(lat0))
    return lon0 + x / kx, lat0 + y / 110540.0


def projeta_casas(casas, G, inund, lon0, lat0):
    """Pé da perpendicular de cada casa na via mais próxima (independe do nível).

    Ponte e túnel não contam: não se sai de casa direto para o tabuleiro.
    """
    vistos, linhas, pares = set(), [], []
    for a, b, e in G.edges(data=True):
        k = (a, b) if a < b else (b, a)
        if k in vistos or e["elevada"]:
            continue
        vistos.add(k)
        ax, ay = _xy(G.nodes[a]["lon"], G.nodes[a]["lat"], lon0, lat0)
        bx, by = _xy(G.nodes[b]["lon"], G.nodes[b]["lat"], lon0, lat0)
        if ax == bx and ay == by:
            continue
        linhas.append(LineString([(ax, ay), (bx, by)])); pares.append((a, b))
    tree = STRtree(linhas)
    out = []
    for c in casas:
        pt = Point(_xy(c["lon"], c["lat"], lon0, lat0))
        i = int(tree.nearest(pt))
        line, (a, b) = linhas[i], pares[i]
        along = float(line.project(pt))
        proj = line.interpolate(along)
        d_casa = float(pt.distance(proj))
        frac = min(1.0, max(0.0, along / (float(line.length) or 1.0)))
        plon, plat = _ll(proj.x, proj.y, lon0, lat0)
        px, py = _perfil_linha((c["lon"], c["lat"]), (plon, plat), d_casa)
        out.append({"lat": c["lat"], "lon": c["lon"], "x": pt.x, "y": pt.y, "plat": plat, "plon": plon,
                    "a": a, "b": b, "frac": frac, "d": d_casa,
                    "cota": inund.cota_geom(c["geom"]), "perfil_con": inund.cota(px, py)})
    return out


def custo_casas(proj, G, rot, nivel, peso_aresta="peso"):
    """Melhor lado da via para cada casa, dado um roteamento. None = sem rota."""
    res = []
    for p in proj:
        if p["d"] > SNAP_CASA_M:
            res.append(None); continue
        t_con = p["d"] / VEL_IDOSO
        f_con = float(np.mean(p["perfil_con"] <= nivel)) if p["d"] > 0.5 else 0.0
        fator = 1.0 + PENAL_AGUA * f_con if peso_aresta == "peso" else 1.0
        a, b, f = p["a"], p["b"], p["frac"]
        opcoes = []
        for no, outro, parte in ((a, b, f), (b, a, 1.0 - f)):
            if no not in rot["peso"]:
                continue
            e = G[outro][no]            # trecho percorrido do pé da perpendicular rumo a `no`
            opcoes.append((t_con * fator + parte * e[peso_aresta] + rot["peso"][no], no, parte, e))
        if not opcoes:
            res.append(None); continue
        pz, no, parte, e = min(opcoes, key=lambda o: o[0])
        res.append({
            "no": no, "destino": rot["destino"][no], "peso": pz,
            "dist": p["d"] + parte * e["comp"] + rot["dist"][no],
            "agua": p["d"] * f_con + parte * e["comp"] * e["alaga"] + rot["agua"][no],
            "t": t_con + parte * e["t"] + rot["t"][no],
            "subida": parte * max(e["dh"], 0.0) + rot["subida"][no],
        })
    return res


def _rampa_no(G, n):
    rs = [abs(e["dh"]) / e["comp"] for _u, _v, e in G.out_edges(n, data=True) if e["comp"] >= 10.0]
    if not rs:
        rs = [abs(e["dh"]) / e["comp"] for _u, _v, e in G.out_edges(n, data=True) if e["comp"] > 0]
    return float(np.median(rs)) if rs else 0.0


def casas_alvo(proj, custos, nivel, tempo_max_s):
    """{índice da casa: motivo} das casas que precisam de outro ponto de encontro.

    tempo    -> na área que alaga e acima do tempo máximo até o abrigo;
    sem_rota -> ligada à rede, mas num trecho sem caminho até abrigo seco;
    ilhada   -> fora da água, mas a rota cruza mais de AGUA_ILHADA_M de água.
    """
    out = {}
    for i, (p, c) in enumerate(zip(proj, custos)):
        if p["d"] > SNAP_CASA_M:
            continue
        if c is None:
            out[i] = "sem_rota"
        elif p["cota"] <= nivel:
            if c["t"] > tempo_max_s:
                out[i] = "tempo"
        elif c["agua"] > AGUA_ILHADA_M:
            out[i] = "ilhada"
    return out


def _arvore(G, no):
    """Dijkstra (peso) a partir de `no`: {nó: (peso, t, água)} pelo caminho de menor peso."""
    pred, dist = nx.dijkstra_predecessor_and_distance(G, no, weight="peso")
    acc = {no: (0.0, 0.0, 0.0)}
    for v in sorted(dist, key=dist.get):
        if v == no:
            continue
        u = pred[v][0]
        e = G[u][v]
        _p, t, ag = acc[u]
        acc[v] = (dist[v], t + e["t"], ag + e["comp"] * e["alaga"])
    return acc


def sugere_pontos(G, proj, fontes_oficiais, nivel, tempo_max_s):
    """Cobertura gulosa: a cada passo, o local que atende mais casas de casas_alvo.

    Locais que atendem pelo menos CAND_URG_MIN casas na água ou sem rota vêm
    antes; as ilhadas (secas) só desempatam e depois ganham locais próprios.

    Local = nó que só alaga CAND_FOLGA_COTA_M acima do nível, em rampa de até
    CAND_RAMPA_MAX. Atende a casa se ela chega lá em até tempo_max_s (idoso)
    pelo caminho de menor peso e, se a casa é ilhada, cruzando no máximo
    AGUA_ILHADA_M de água. Para quando o ganho fica abaixo de CAND_GANHO_MIN
    casas ou em CAND_MAX locais. G já com aplica_nivel(nivel).
    """
    fontes = dict(fontes_oficiais)
    custos0 = custo_casas(proj, G, roteia(G, fontes), nivel)
    alvo_mot = casas_alvo(proj, custos0, nivel, tempo_max_s)
    seco = {n for n in G.nodes
            if G.nodes[n]["hand"] > nivel + CAND_FOLGA_COTA_M and _rampa_no(G, n) <= CAND_RAMPA_MAX}
    arv = {}
    cobre = {}                  # nó -> {casa: peso até lá}
    for i, mot in alvo_mot.items():
        p = proj[i]
        f_con = float(np.mean(p["perfil_con"] <= nivel)) if p["d"] > 0.5 else 0.0
        t_con = p["d"] / VEL_IDOSO
        melhor = {}
        for no, outro, parte in ((p["a"], p["b"], p["frac"]), (p["b"], p["a"], 1.0 - p["frac"])):
            e = G[outro][no]
            b_p = t_con * (1.0 + PENAL_AGUA * f_con) + parte * e["peso"]
            b_t = t_con + parte * e["t"]
            b_a = p["d"] * f_con + parte * e["comp"] * e["alaga"]
            if no not in arv:
                arv[no] = _arvore(G, no)
            for n, (pz, t, ag) in arv[no].items():
                if n in seco and (n not in melhor or b_p + pz < melhor[n][0]):
                    melhor[n] = (b_p + pz, b_t + t, b_a + ag)
        p_oficial = custos0[i]["peso"] if custos0[i] is not None else math.inf
        for n, (pz, t, ag) in melhor.items():
            # o roteamento escolhe o destino de menor peso: o local só atende se ganhar do oficial
            if t <= tempo_max_s and pz < p_oficial and (mot != "ilhada" or ag <= AGUA_ILHADA_M):
                cobre.setdefault(n, {})[i] = pz
    candidatos, livres = [], set(alvo_mot)
    while livres and len(candidatos) < CAND_MAX:
        alvo = None
        for n, cs in cobre.items():
            if n in fontes:
                continue
            ganho = [pz for i, pz in cs.items() if i in livres]
            urg = sum(1 for i in cs if i in livres and alvo_mot[i] != "ilhada")
            chave = (urg if urg >= CAND_URG_MIN else 0, len(ganho), -sum(ganho))
            if ganho and (alvo is None or chave > alvo[0]):
                alvo = (chave, n)
        if alvo is None or (alvo[0][0] < CAND_URG_MIN and alvo[0][1] < CAND_GANHO_MIN):
            break
        n = alvo[1]
        cid = f"candidato_{len(candidatos) + 1}"
        fontes[n] = cid
        livres -= set(cobre[n])
        candidatos.append({"id": cid, "node": n, "lat": G.nodes[n]["lat"], "lon": G.nodes[n]["lon"],
                           "ordem": len(candidatos) + 1, "n_cobre": alvo[0][1],
                           "cota_alaga_m": None if math.isinf(G.nodes[n]["hand"]) else round(G.nodes[n]["hand"], 1),
                           "rampa": round(_rampa_no(G, n), 3)})
    custos = custo_casas(proj, G, roteia(G, fontes), nivel)
    por_id = {cd["id"]: cd for cd in candidatos}
    for cd in candidatos:
        cd.update(n_casas=0, motivos={}, _antes=[], _depois=[])
    for i, mot in alvo_mot.items():
        c = custos[i]
        cd = por_id.get(c["destino"]) if c else None
        if cd is None:
            continue
        cd["n_casas"] += 1
        cd["motivos"][mot] = cd["motivos"].get(mot, 0) + 1
        if custos0[i] is not None:
            cd["_antes"].append(custos0[i]["t"])
        cd["_depois"].append(c["t"])
    for cd in candidatos:
        a, d = cd.pop("_antes"), cd.pop("_depois")
        cd["pior_antes_min"] = round(max(a) / 60, 1) if a else None
        cd["pior_depois_min"] = round(max(d) / 60, 1) if d else None
        cd["medio_depois_min"] = round(sum(d) / len(d) / 60, 1) if d else None
    depois = casas_alvo(proj, custos, nivel, tempo_max_s)
    resumo = {m: {"antes": sum(v == m for v in alvo_mot.values()), "depois": sum(v == m for v in depois.values())}
              for m in ("tempo", "sem_rota", "ilhada")}
    return candidatos, resumo, fontes


def pessoas_por_casa(cfg, proj):
    """População da grade IBGE 2022 dividida entre as casas de cada célula.

    Casa fora das células com moradores fica com None (não residencial ou
    construída depois do Censo). Devolve (pessoas por casa, população total,
    população em células sem casa).
    """
    caminho = os.path.join(RAIZ, "assets", "data", "vulnerabilidade", "grade", f"{cfg['cod']}.geojson")
    out = [None] * len(proj)
    if not os.path.exists(caminho):
        print(f"grade IBGE ausente ({caminho}): sem pessoas por casa")
        return out, 0.0, 0.0
    tree = STRtree([Point(p["lon"], p["lat"]) for p in proj])
    total = sem_casa = 0.0
    for f in json.load(open(caminho, encoding="utf-8"))["features"]:
        pop = float(f["properties"].get("pop", 0) or 0)
        if pop <= 0:
            continue
        total += pop
        dentro = tree.query(shape(f["geometry"]), predicate="contains")
        if not len(dentro):
            sem_casa += pop
            continue
        for i in dentro:
            out[int(i)] = (out[int(i)] or 0.0) + pop / len(dentro)
    return out, total, sem_casa


def fontes_secas(abrigos, nivel):
    """Abrigos que não alagam no nível; se todos alagam, nenhum."""
    return {a["node"]: a["id"] for a in abrigos if a["cota_alaga"] > nivel}


def situacao(p, c, nivel, tempo_max_s):
    if c is None:
        return "sem_rota"
    if p["cota"] <= nivel:
        return "excede" if c["t"] > tempo_max_s else "ok"
    return "ilhada" if c["agua"] > AGUA_ILHADA_M else "ok"


def _num(x, nd=0):
    if x is None or (isinstance(x, float) and math.isinf(x)):
        return None
    return round(x, nd) if nd else int(round(x))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cidade", choices=list(CIDADES), default="santa_tereza")
    ap.add_argument("--fonte", choices=["live", "cenario", "fixo"], default="live")
    ap.add_argument("--nivel", type=float, default=None)
    ap.add_argument("--tempo-max", type=float, default=TEMPO_MAX_MIN, help="minutos a pé (idoso) até o abrigo")
    args = ap.parse_args()
    cfg = CIDADES[args.cidade]
    fonte = args.fonte
    if cfg["zero_regua_m"] is None and fonte != "fixo":
        fonte = "fixo"  # cidade sem regua calibrada -> nivel HAND fixo
    nivel_fixo = args.nivel if args.nivel is not None else cfg["nivel_padrao"]
    tempo_max_s = args.tempo_max * 60.0
    SAIDA_JSON, SAIDA_HTML = caminhos_saida(cfg, fonte)

    hand_nivel, meta_nivel = nivel_de_projeto(cfg, fonte, nivel_fixo)
    inund = Inundacao(cfg)
    acima = hand_nivel > NIVEL_MAX_M
    if acima:
        print(f"AVISO: nivel HAND {hand_nivel:.1f} m acima do mapeado ({NIVEL_MAX_M:.0f} m); usando {NIVEL_MAX_M:.0f} m")
    nivel = min(hand_nivel, NIVEL_MAX_M)
    mancha, nn = inund.mancha(nivel)
    if meta_nivel.get("dados_desatualizados"):
        print(f"AVISO: telemetria de {meta_nivel.get('telemetria_em')} "
              f"({meta_nivel.get('idade_telemetria_min')} min) — dados desatualizados")
    print(f"[{cfg['slug']}/{fonte}] {meta_nivel.get('rotulo')} -> " +
          ("SEM mancha (rio baixo)" if nivel <= 0 else f"HAND {nivel:.1f} m"))
    abrigos = carrega_abrigos(cfg)
    if not abrigos:
        raise SystemExit(f"Nenhum abrigo em abrigos.geojson para {cfg['municipio']}")
    osm = baixa_osm(cfg)
    G = monta_grafo(osm, cotas_dos_nos(cfg, osm), inund, MIN_COMP_NOS)
    lon0 = (cfg["bbox"]["W"] + cfg["bbox"]["E"]) / 2.0
    lat0 = (cfg["bbox"]["S"] + cfg["bbox"]["N"]) / 2.0
    proj = projeta_casas(casas_de_osm(baixa_casas(cfg)), G, inund, lon0, lat0)
    # trecho desconectado só fica se alguma casa depende dele
    com_casa = {0} | {G.nodes[p["a"]]["comp"] for p in proj if p["d"] <= SNAP_CASA_M}
    G.remove_nodes_from([n for n in list(G.nodes) if G.nodes[n]["comp"] not in com_casa])
    n_flood = aplica_nivel(G, nivel)
    n_pe = sum(1 for _a, _b, d in G.edges(data=True) if d["so_pe"]) // 2
    n_iso = sum(1 for p in proj if p["d"] <= SNAP_CASA_M and G.nodes[p["a"]]["comp"] > 0)
    print(f"grafo: {G.number_of_nodes()} nos, {G.number_of_edges() // 2} trechos "
          f"({n_flood} com agua, {n_pe} so a pe)" +
          (f" · {len(com_casa) - 1} trecho(s) desconectado(s) com {n_iso} casas" if n_iso else ""))

    principal = [n for n in G.nodes if G.nodes[n]["comp"] == 0]
    for a in abrigos:
        gn = snap(G, a["lon"], a["lat"], principal); a["node"] = gn
        a["snap_m"] = round(haversine(a["lon"], a["lat"], G.nodes[gn]["lon"], G.nodes[gn]["lat"]), 1)
        a["cota_alaga"] = float(inund.cota(a["lon"], a["lat"])[0])
    fontes = fontes_secas(abrigos, nivel)
    alagados = [a["nome"] for a in abrigos if a["cota_alaga"] <= nivel]
    for a in abrigos:
        cz = "nao alaga ate 25 m" if math.isinf(a["cota_alaga"]) else f"alaga em HAND {a['cota_alaga']:.1f} m"
        print(f"  abrigo {a['nome']}: {cz}")
    if alagados:
        print(f"AVISO: abrigos alagados em HAND {nivel:.1f} m: {alagados}")
    if not fontes:
        print("AVISO: todos os abrigos alagam neste nivel; rotas para eles mesmo assim")
        fontes = {a["node"]: a["id"] for a in abrigos}
    rot = roteia(G, fontes)

    custos = custo_casas(proj, G, rot, nivel)
    diretos = custo_casas(proj, G, roteia(G, fontes, "t"), nivel, "t")
    candidatos, resumo_cand, fontes_cand = sugere_pontos(G, proj, fontes, nivel, tempo_max_s)
    restantes = resumo_cand["tempo"]["depois"]
    rot_cand = roteia(G, fontes_cand) if candidatos else None
    custos_cand = custo_casas(proj, G, rot_cand, nivel) if candidatos else [None] * len(proj)
    pessoas, pop_total, pop_sem_casa = pessoas_por_casa(cfg, proj)

    # o painel usa o primeiro nível >= slider: sem o nível exato do cenário, 13,4 viraria 14
    niveis_m = sorted(set(NIVEIS_ROTA_M) | ({round(nivel, 1)} if 0 <= nivel <= NIVEL_MAX_M else set()))
    print(f"rotas por nivel (HAND {niveis_m[0]:.0f}-{niveis_m[-1]:.0f} m)...")
    por_nivel = []
    for nv in niveis_m:
        aplica_nivel(G, nv)
        fs = fontes_secas(abrigos, nv)
        if not fs:
            por_nivel.append(None); continue
        r = roteia(G, fs)
        por_nivel.append((r, custo_casas(proj, G, r, nv)))
    aplica_nivel(G, nivel)

    bb = cfg["bbox"]; f = 0.003
    manter = {n for n in G.nodes
              if bb["S"] - f <= G.nodes[n]["lat"] <= bb["N"] + f and bb["W"] - f <= G.nodes[n]["lon"] <= bb["E"] + f}
    manter |= {a["node"] for a in abrigos} | {cd["node"] for cd in candidatos}
    rotas = [(rot, custos)] + ([(rot_cand, custos_cand)] if rot_cand else []) + [x for x in por_nivel if x]
    for r, cs in rotas:
        seguidos = set()
        for n in list(manter) + [c["no"] for c in cs if c is not None]:
            while n is not None and n not in seguidos:
                seguidos.add(n); manter.add(n)
                nx_ = r["prox"].get(n)
                n = None if nx_ == n else nx_
    nos = [n for n in G.nodes if n in manter]
    idx = {n: i for i, n in enumerate(nos)}
    abr_idx = {a["id"]: i for i, a in enumerate(abrigos)}

    casas, sit_cnt = [], {}
    demanda = {}
    for p, c, cd, cc, pes in zip(proj, custos, diretos, custos_cand, pessoas):
        dentro = int(p["cota"] <= nivel)
        st = situacao(p, c, nivel, tempo_max_s)
        sit_cnt[st] = sit_cnt.get(st, 0) + 1
        base = [round(p["lat"], 6), round(p["lon"], 6)]
        pj = [round(p["plat"], 6), round(p["plon"], 6)] if p["d"] <= SNAP_CASA_M else [None, None]
        cota = _num(p["cota"], 1)
        cand = cc["destino"] if cc and cc["destino"] not in abr_idx else None
        tc = round(cc["t"]) if cand else None
        no_c = idx[cc["no"]] if cand else None
        # demanda: quem está na água vai ao destino mais próximo (candidato ou oficial);
        # ilhada/sem rota fora da água só conta no candidato
        destino = (cand or (c["destino"] if c else None)) if dentro else (cand if st in ("ilhada", "sem_rota") else None)
        if destino:
            dm = demanda.setdefault(destino, {"casas": 0, "pessoas": 0.0, "casas_isoladas": 0,
                                              "pessoas_isoladas": 0.0, "casas_fora_censo": 0})
            if dentro:
                dm["casas"] += 1; dm["pessoas"] += pes or 0.0
            else:
                dm["casas_isoladas"] += 1; dm["pessoas_isoladas"] += pes or 0.0
            dm["casas_fora_censo"] += pes is None
        pes_r = None if pes is None else round(pes, 1)
        if c is None:
            casas.append(base + pj + [-1, None, None, None, dentro, None, None, 0, None, None,
                                      cota, st, cand, tc, no_c, pes_r])
            continue
        casas.append(base + pj + [idx[c["no"]], c["destino"],
                                  round(c["dist"], 1), round(c["agua"], 1), dentro,
                                  round(c["t"]), round(c["subida"], 1), int(st == "excede"),
                                  round(cd["t"]) if cd else None, round(cd["agua"], 1) if cd else None,
                                  cota, st, cand, tc, no_c, pes_r])
    for dm in demanda.values():
        dm["pessoas"] = round(dm["pessoas"]); dm["pessoas_isoladas"] = round(dm["pessoas_isoladas"])

    n_sem = sit_cnt.get("sem_rota", 0)
    n_mancha = sum(c[8] for c in casas)
    n_exc = sit_cnt.get("excede", 0)
    n_mancha_sem = sum(1 for c in casas if c[8] and c[15] == "sem_rota")
    print(f"casas: {len(casas)} ({n_mancha} na mancha) · situacao {sit_cnt} · "
          f"{n_mancha_sem} na mancha sem rota")
    tm = sorted(c[9] for c in casas if c[8] and c[9] is not None)
    td = sorted(c[12] for c in casas if c[8] and c[12] is not None)
    if tm:
        print(f"  na mancha: rota evitando agua mediana {tm[len(tm)//2]/60:.0f} min, max {tm[-1]/60:.0f} min; "
              f"direta pela agua mediana {td[len(td)//2]/60:.0f} min; {n_exc} acima de {args.tempo_max:.0f} min")
    for cd in candidatos:
        dm = demanda.get(cd["id"], {})
        print(f"  {cd['id']} (cobre {cd['n_cobre']}): {cd['n_casas']} casas {cd['motivos']}, pior "
              f"{cd['pior_antes_min']} -> {cd['pior_depois_min']} min · alaga em "
              f"{cd['cota_alaga_m'] if cd['cota_alaga_m'] is not None else '>25'} m · rampa {cd['rampa']} · "
              f"demanda {dm.get('pessoas', 0)} pessoas na agua + {dm.get('pessoas_isoladas', 0)} isoladas")
    for m, r in resumo_cand.items():
        if r["antes"]:
            print(f"  {m}: {r['antes']} casas -> {r['depois']} com candidatos")
    for a in abrigos:
        dm = demanda.get(a["id"])
        if dm:
            print(f"  demanda {a['nome']}: {dm['casas']} casas na agua, ~{dm['pessoas']} pessoas")
    n_fora_censo = sum(p is None for p in pessoas)
    print(f"  pessoas (IBGE 2022): {pop_total:.0f}, {pop_sem_casa:.0f} em celulas sem casa mapeada; "
          f"{n_fora_censo} casas fora das celulas com moradores")

    EDGES, vistos = [], set()
    for a, b, d in G.edges(data=True):
        k = (a, b) if a < b else (b, a)
        if k in vistos or a not in idx or b not in idx:
            continue
        vistos.add(k)
        EDGES.append([idx[a], idx[b], round(d["alaga"], 2), int(d["so_pe"]), _num(float(d["perfil"].min()), 1)])

    def coords_poly(geom):
        if geom.is_empty: return []
        gs = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon"]
        return [[[round(y, 6), round(x, 6)] for x, y in g.exterior.coords] for g in gs]

    def serie_nivel(r, cs):
        if r is None:
            vazio = [-1] * len(nos)
            return vazio, vazio, vazio, [-1] * len(proj), [-1] * len(proj), [-1] * len(proj)
        return ([idx.get(r["prox"].get(n), -1) for n in nos],
                [abr_idx.get(r["destino"].get(n), -1) for n in nos],
                [round(r["t"][n]) if n in r["t"] else -1 for n in nos],
                [idx[c["no"]] if c else -1 for c in cs],
                [round(c["t"]) if c else -1 for c in cs],
                [round(c["agua"]) if c else -1 for c in cs])

    series = [serie_nivel(*(x if x else (None, None))) for x in por_nivel]
    niveis_doc = {"hand_m": niveis_m}
    for k, nome in enumerate(["prox", "dest", "tempo_s", "casa_no", "casa_tempo_s", "casa_agua_m"]):
        niveis_doc[nome] = [s[k] for s in series]

    m_simpl = mancha if mancha.is_empty else mancha.simplify(0.00008)
    doc = {
        "meta": {"municipio": cfg["municipio"], "nivel_projeto_m": round(nivel, 2), "nivel_mancha_m": nn,
                 "nivel_acima_do_mapeado": acima, "nivel_max_mapeado_m": NIVEL_MAX_M,
                 "penal_agua": PENAL_AGUA,
                 "gerado_em": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "n_nos": len(nos), "n_arestas": len(EDGES), "n_casas": len(casas),
                 "n_casas_mancha": n_mancha, "n_casas_sem_rota": n_sem,
                 "n_casas_excede": n_exc, "n_casas_excede_com_candidatos": restantes,
                 "n_casas_mancha_sem_rota": n_mancha_sem, "n_casas_ilhadas": sit_cnt.get("ilhada", 0),
                 "candidatos_resumo": resumo_cand,
                 "pop_total": round(pop_total), "pop_sem_casa": round(pop_sem_casa),
                 "n_casas_fora_censo": n_fora_censo,
                 "fonte_pessoas": "IBGE grade estatística 2022 (domicílios ocupados) dividida entre as casas OSM "
                                  "de cada célula; casa fora das células com moradores = null",
                 "agua_ilhada_m": AGUA_ILHADA_M, "abrigos_alagados": alagados,
                 "snap_casa_m": SNAP_CASA_M, "vel_idoso_ms": VEL_IDOSO, "tempo_max_min": args.tempo_max,
                 "casas_campos": CASAS_CAMPOS, "etapa": 2, "nivel": meta_nivel,
                 "modelo_tempo": "r.walk (Naismith + Langmuir) escalado p/ idoso 0,9 m/s; MDT mosaico 2 m",
                 "modelo_agua": "fração do trecho abaixo do nível (cota_alaga_<cidade>.tif, HAND ligado ao rio); "
                                "ponte alaga pela cabeceira",
                 "referencia_metodo": "Gandra Franco (2026), doi:10.5281/zenodo.20402230",
                 "fonte_rede": "© OpenStreetMap contributors (ODbL), vias a pé",
                 "fonte_casas": "© OpenStreetMap contributors (ODbL), building",
                 "fonte_mancha": "HAND mosaico 2m (contornos_mancha.json até 15 m; raster acima)"},
        "abrigos": [{"id": a["id"], "nome": a["nome"], "lat": round(a["lat"], 6), "lon": round(a["lon"], 6),
                     "node": idx.get(a["node"], -1), "snap_m": a["snap_m"],
                     "cota_alaga_m": _num(a["cota_alaga"], 1), "demanda": demanda.get(a["id"])} for a in abrigos],
        "candidatos": [{**{k: v for k, v in cd.items() if k != "node"}, "node": idx[cd["node"]],
                        "lat": round(cd["lat"], 6), "lon": round(cd["lon"], 6),
                        "demanda": demanda.get(cd["id"])} for cd in candidatos],
        "nos": [[round(G.nodes[n]["lat"], 6), round(G.nodes[n]["lon"], 6)] for n in nos],
        "cota_m": [None if G.nodes[n]["z"] is None else round(G.nodes[n]["z"], 1) for n in nos],
        "cota_alaga_m": [_num(G.nodes[n]["hand"], 1) for n in nos],
        "prox": [idx.get(rot["prox"].get(n), -1) for n in nos],
        "dest": [rot["destino"].get(n) for n in nos],
        # None: nó sem caminho até abrigo seco (trecho desconectado)
        "dist_m": [round(rot["dist"][n], 1) if n in rot["dist"] else None for n in nos],
        "agua_m": [round(rot["agua"][n], 1) if n in rot["agua"] else None for n in nos],
        "tempo_s": [round(rot["t"][n]) if n in rot["t"] else None for n in nos],
        "subida_m": [round(rot["subida"][n], 1) if n in rot["subida"] else None for n in nos],
        "rota_cand": ({"prox": [idx.get(rot_cand["prox"].get(n), -1) for n in nos],
                       "dest": [rot_cand["destino"].get(n) for n in nos]} if rot_cand else None),
        "niveis": niveis_doc,
        "edges": EDGES, "casas": casas, "mancha": coords_poly(m_simpl),
    }
    os.makedirs(os.path.dirname(SAIDA_JSON), exist_ok=True)
    js = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    open(SAIDA_JSON, "w", encoding="utf-8").write(js)
    open(SAIDA_HTML, "w", encoding="utf-8").write(_TEMPLATE.replace("__DADOS__", js))
    print(f"nos exportados: {len(nos)}/{G.number_of_nodes()} · casas com rota: {len(casas) - n_sem}/{len(casas)}"
          f" · {len(js) / 1e6:.1f} MB")
    print(f"-> {SAIDA_JSON}\n-> {SAIDA_HTML}")


_TEMPLATE = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rota de fuga por ruas — Etapa 2</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 html,body{height:100%;margin:0}
 body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#12211b}
 #map{position:fixed;top:0;left:0;width:100vw;height:100vh}
 .hud{position:absolute;z-index:500;top:10px;left:10px;background:#fff;border-radius:10px;
      box-shadow:0 2px 12px rgba(0,0,0,.15);padding:12px 14px;max-width:360px;max-height:calc(100vh - 40px);overflow:auto}
 .hud h1{font:600 16px Georgia,serif;margin:0 0 4px}
 .hud .sub{color:#4a5a52;font-size:13px;margin:2px 0}
 .aviso{background:#fdecea;border:1px solid #f2b8b2;color:#8f2a20;border-radius:8px;padding:8px 10px;font-size:13px;margin-top:8px}
 .rota{background:#eaf5ef;border:1px solid #bfe0cd;border-radius:8px;padding:8px 10px;font-size:14px;margin-top:8px}
 .diag{background:#f4effa;border:1px solid #d6c6ec;color:#4b2c78;border-radius:8px;padding:8px 10px;font-size:13px;margin-top:8px}
 .leg{position:absolute;z-index:500;bottom:24px;left:10px;background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.15);padding:10px 12px;font-size:13px}
 .leg i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-2px}
 .dobra{border:0;background:#eef3f0;border-radius:6px;padding:2px 8px;font:600 12px inherit;cursor:pointer;float:right}
 .hud.min .corpo{display:none}
 @media (max-width:600px){.hud{max-width:calc(100vw - 24px);font-size:14px}}
</style></head><body>
<div id="map"></div>
<div class="hud" id="hud">
  <button class="dobra" onclick="const h=this.parentNode;h.classList.toggle('min');document.getElementById('leg').style.display=h.classList.contains('min')?'none':''">–</button>
  <h1>Rota de fuga · <span id="cid"></span></h1>
  <div class="corpo">
  <div class="sub">Cada casa do OpenStreetMap · tempo a pé (idoso) com subidas, até o abrigo oficial, evitando a área que alaga</div>
  <div class="sub" id="meta"></div>
  <div class="aviso" id="alertas" style="display:none"></div>
  <div class="aviso">Protótipo (Etapa 2). Pontos de encontro oficiais (Defesa Civil). Não substitui orientação oficial em emergência.</div>
  <div class="diag" id="diag" style="display:none"></div>
  </div>
  <div class="rota" id="rota">Toque numa casa para ver a rota até o abrigo mais próximo.</div>
</div>
<div class="leg" id="leg"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D=__DADOS__;
const F=Object.fromEntries(D.meta.casas_campos.map((k,i)=>[k,i]));
const TMAX=D.meta.tempo_max_min||30;
document.getElementById('cid').textContent=D.meta.municipio;
const map=L.map('map');
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Imagens Esri · Ruas e edificações © OpenStreetMap contributors (ODbL)'}).addTo(map);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,opacity:.9}).addTo(map);
const ZR=(D.meta.nivel||{}).bankfull_m;
const regua=h=>ZR!=null?` (régua ${(h+ZR).toFixed(1).replace('.',',')} m)`:'';
(function(){const nv=D.meta.nivel||{};let t='';
 const al=nv.alarmes_regua_m||{};
 const alTxt=(al.atencao&&al.alerta&&al.inundacao)?` · alarmes ${al.atencao}/${al.alerta}/${al.inundacao} m`:'';
 if(nv.fonte==='live'){const at=(nv.nivel_atual_cm/100).toFixed(2),pk=(nv.nivel_pico_cm/100).toFixed(2);
   t=`Ao vivo: rio ${at} m · pico previsto ${pk} m`+(nv.transbordando?` · área que alaga em HAND ${D.meta.nivel_projeto_m} m`:` · abaixo do transbordamento (${nv.bankfull_m} m)`)+alTxt;}
 else{t=`${nv.rotulo||''}`+(nv.calibrar_regua?' (nível provisório — calibrar régua)':'')+alTxt;}
 const nc=D.meta.n_casas||0, nm=D.meta.n_casas_mancha||0;
 document.getElementById('meta').textContent=t+` · ${nc} casas`+(nm?` (${nm} na área que alaga)`:'')+` · ${D.meta.gerado_em}`;
 const al2=[];
 if(nv.dados_desatualizados)al2.push(`Dados do rio de ${nv.telemetria_em||'?'} — desatualizados.`);
 if(D.meta.nivel_acima_do_mapeado)al2.push(`Nível acima do mapeado (${D.meta.nivel_max_mapeado_m} m HAND): área que alaga subestimada.`);
 if((D.meta.abrigos_alagados||[]).length)al2.push(`Abrigo(s) que alagam neste nível: ${D.meta.abrigos_alagados.join(', ')}.`);
 if(al2.length){const e=document.getElementById('alertas');e.style.display='';e.innerHTML=al2.join('<br>');}
 const ne=D.meta.n_casas_excede||0, cands=D.candidatos||[], nsr=D.meta.n_casas_mancha_sem_rota||0, nil=D.meta.n_casas_ilhadas||0;
 const RC=D.meta.candidatos_resumo||{}, dep=m=>(RC[m]||{}).depois;
 const comC=m=>cands.length&&dep(m)!=null?` Com os candidatos: <b>${dep(m)}</b>.`:'';
 const linhas=[];
 if(ne)linhas.push(`<b>${ne}</b> casa(s) na área que alaga levam mais de <b>${TMAX} min</b> até o abrigo oficial.`+comC('tempo'));
 if(nsr&&!(RC.sem_rota||{}).antes)linhas.push(`<b>${nsr}</b> casa(s) na área que alaga sem caminho mapeado até um abrigo oficial seco.`);
 if((RC.sem_rota||{}).antes)linhas.push(`<b>${RC.sem_rota.antes}</b> casa(s) ligadas a ruas sem caminho até abrigo oficial (outra margem ou trecho isolado).`+comC('sem_rota'));
 if(nil)linhas.push(`<b>${nil}</b> casa(s) fora da água ficam <b>ilhadas</b>: a rota até o abrigo oficial passa por área que alaga.`+comC('ilhada'));
 if(cands.length)linhas.push(`${cands.length} local(is) candidato(s) em roxo — sugestão para a Defesa Civil avaliar, não ponto oficial.`);
 if(linhas.length){const dg=document.getElementById('diag');dg.style.display='';dg.innerHTML=linhas.join('<br>');}
})();
D.mancha.forEach(p=>L.polygon(p,{color:'#1e5fbf',weight:1,fillColor:'#1e5fbf',fillOpacity:.18}).addTo(map));
D.edges.forEach(([a,c,ag,pe])=>{const A=D.nos[a],C=D.nos[c];
  L.polyline([A,C],{color:ag?'#b3382c':'#8fa7b8',weight:ag?2.5:1.5,opacity:ag?.7:.5,dashArray:pe?'3 4':null}).addTo(map);});
const b=L.latLngBounds();
const CASAS=D.casas||[];
const ESTILO={excede:['#6b1a1a','#c0392b'],ilhada:['#4b2c78','#a689d6'],sem_rota:['#666','#c5c5c5']};
CASAS.forEach((c,i)=>{
  const dentro=c[F.na_mancha], st=c[F.situacao]||'ok';
  const [cor,fill]=ESTILO[st]||(dentro?['#9a3412','#e8730c']:['#3d4a44','#f4f7f5']);
  const m=L.circleMarker([c[F.lat],c[F.lon]],{radius:dentro||st!=='ok'?4.5:3.2,weight:st==='excede'?2.2:1,
    color:cor,fillColor:fill,fillOpacity:dentro?.95:.85}).addTo(map);
  m.on('click',ev=>{if(ev.originalEvent)L.DomEvent.stopPropagation(ev.originalEvent);mostraCasa(i);});
  b.extend([c[F.lat],c[F.lon]]);
});
const txtDemanda=dm=>!dm?'':`<br>Demanda no cenário: ~<b>${dm.pessoas}</b> pessoas de ${dm.casas} casas na água`+
  (dm.casas_isoladas?` + ~${dm.pessoas_isoladas} de ${dm.casas_isoladas} casas isoladas`:'')+' (Censo 2022 dividido pelas casas)'+
  (dm.casas_fora_censo?`; ${dm.casas_fora_censo} casas sem moradores no Censo contam 0`:'')+'.';
const MOT={tempo:m=>`${m} passam de ${TMAX} min até o abrigo oficial`,sem_rota:m=>`${m} sem caminho até abrigo oficial`,ilhada:m=>`${m} ilhadas (rota cruza água)`};
const txtMotivos=cd=>Object.entries(cd.motivos||{}).map(([k,v])=>(MOT[k]||(m=>m+' '+k))(v)).join(', ');
D.abrigos.forEach(a=>{b.extend([a.lat,a.lon]);L.marker([a.lat,a.lon]).addTo(map).bindPopup('<b>'+a.nome+'</b><br>ponto de encontro / abrigo oficial'+
  (a.cota_alaga_m!=null?`<br>alaga a partir de HAND ${a.cota_alaga_m} m${regua(a.cota_alaga_m)}`:'')+txtDemanda(a.demanda));});
(D.candidatos||[]).forEach(cd=>L.circleMarker([cd.lat,cd.lon],{radius:10,color:'#5b2a86',weight:3,dashArray:'4 3',fillColor:'#d9c6f0',fillOpacity:.7}).addTo(map)
  .bindPopup(`<b>Local candidato</b> (não oficial)<br>Grupo de ${cd.n_casas} casas: ${txtMotivos(cd)}.<br>`+
    (cd.pior_antes_min!=null&&cd.pior_depois_min!=null?`Pior tempo: ${Math.round(cd.pior_antes_min)} → ${Math.round(cd.pior_depois_min)} min.<br>`:
     cd.pior_depois_min!=null?`Pior tempo até aqui: ${Math.round(cd.pior_depois_min)} min.<br>`:'')+
    `Alaga: ${cd.cota_alaga_m!=null?'HAND '+cd.cota_alaga_m+' m'+regua(cd.cota_alaga_m):'não alaga até '+D.meta.nivel_max_mapeado_m+' m'} · rampa ${Math.round(cd.rampa*100)}%.`+
    txtDemanda(cd.demanda)+`<br><i>Capacidade não avaliada. Validar com a Defesa Civil.</i>`));
const BB=b.pad(0.05);function ajusta(){map.invalidateSize();map.fitBounds(BB);}
ajusta();setTimeout(ajusta,300);window.addEventListener('resize',ajusta);
let cam=null,camC=null,sel=null;
function m2(la1,lo1,la2,lo2){const dy=(la1-la2)*110540,dx=(lo1-lo2)*111320*Math.cos(la1*Math.PI/180);return dy*dy+dx*dx;}
function fmin(s){const m=Math.max(1,Math.round(s/60));return m<60?m+' min':Math.floor(m/60)+' h '+String(m%60).padStart(2,'0');}
function cadeia(c,prox,ini){const pts=[[c[F.lat],c[F.lon]]];
  if(c[F.proj_lat]!=null) pts.push([c[F.proj_lat],c[F.proj_lon]]);
  let j=ini,g=0;
  while(j>=0&&g++<6000){pts.push(D.nos[j]);const nx=prox[j];if(nx===j||nx<0)break;j=nx;}
  return pts;}
function mostraCasa(i){
  const c=CASAS[i]; if(!c) return;
  [cam,camC,sel].forEach(l=>{if(l)map.removeLayer(l);}); cam=camC=null;
  sel=L.circleMarker([c[F.lat],c[F.lon]],{radius:8,color:'#0f8b46',fillColor:'#fff',fillOpacity:1,weight:3}).addTo(map);
  let txtC='';
  if(c[F.cand]&&D.rota_cand&&c[F.no_cand]!=null){
    camC=L.polyline(cadeia(c,D.rota_cand.prox,c[F.no_cand]),{color:'#5b2a86',weight:4,opacity:.9,dashArray:'6 6'}).addTo(map);
    txtC=`<br><span style="color:#4b2c78">Até o local candidato (roxo, não oficial): <b>${fmin(c[F.tempo_cand_s])}</b>.</span>`;
  }
  if(c[F.no]<0){
    document.getElementById('rota').innerHTML=c[F.proj_lat]==null
      ?'<b>Casa sem rota</b><br>A via mapeada mais próxima fica a mais de '+(D.meta.snap_casa_m||80)+' m.'
      :'<b>Sem caminho até abrigo oficial</b><br>As ruas desta casa não se ligam, no mapa, às do abrigo (outra margem do rio ou trecho isolado).'+txtC;
    return;
  }
  cam=L.polyline(cadeia(c,D.prox,c[F.no]),{color:'#0f8b46',weight:5,opacity:.95}).addTo(map);
  const ab=D.abrigos.find(x=>x.id===c[F.abrigo])||D.abrigos[0];
  const ag=c[F.agua_m]||0, sb=c[F.subida_m]||0, st=c[F.situacao];
  const cota=c[F.cota_alaga];
  document.getElementById('rota').innerHTML=`<b>Rota até ${ab?ab.nome:'abrigo'}</b><br>A pé: <b>${(c[F.dist_m]/1000).toFixed(2)} km</b> · <b>${fmin(c[F.tempo_s])}</b> (idoso)`+
    (sb>=1?` · sobe ${Math.round(sb)} m`:'')+
    (cota!=null?`<br>A casa alaga a partir de HAND ${cota} m${regua(cota)}.`:'<br>A casa não alaga até o nível mapeado.')+
    (st==='excede'?`<br><span style="color:#6b1a1a">Passa de ${TMAX} min até o abrigo oficial.</span>`:'')+
    (st==='ilhada'?`<br><span style="color:#4b2c78"><b>Ilhada</b>: a casa fica seca, mas a rota cruza água. Sair cedo ou abrigar-se no local.</span>`:'')+
    (ag>0?`<br><span style="color:#b3382c">⚠ ${Math.round(ag)} m passam por área que alaga.</span>`:`<br><span style="color:#0f8b46">Rota fora da área que alaga.</span>`)+txtC+
    (c[F.tempo_direto_s]!=null&&c[F.tempo_direto_s]<0.8*c[F.tempo_s]&&(c[F.agua_direto_m]||0)>0?
      `<br><span style="color:#4a5a52">O caminho mais curto (${fmin(c[F.tempo_direto_s])}) atravessa ${Math.round(c[F.agua_direto_m]||0)} m de área que alaga — só serve antes da água chegar.</span>`:'');
}
map.on('click',e=>{
  let best=-1,bd=1e18;
  for(let i=0;i<CASAS.length;i++){const d=m2(e.latlng.lat,e.latlng.lng,CASAS[i][F.lat],CASAS[i][F.lon]);if(d<bd){bd=d;best=i;}}
  if(best<0||Math.sqrt(bd)>60){document.getElementById('rota').textContent='Nenhuma casa a menos de 60 m deste ponto.';return;}
  mostraCasa(best);
});
window.mostraCasa=mostraCasa;
if(innerWidth<600){document.getElementById('hud').classList.add('min');document.getElementById('leg').style.display='none';}
document.getElementById('leg').innerHTML='<b>Mapa</b><br><i style="background:#0f8b46"></i>rota da casa até o abrigo<br>'+
 '<i style="background:#e8730c;border-radius:50%"></i>casa na área que alaga<br>'+
 '<i style="background:#c0392b;border-radius:50%"></i>na área que alaga, acima de '+TMAX+' min<br>'+
 '<i style="background:#a689d6;border-radius:50%"></i>ilhada (rota cruza água)<br>'+
 '<i style="background:#c5c5c5;border-radius:50%"></i>sem caminho até abrigo oficial<br>'+
 '<i style="background:#f4f7f5;border:1px solid #3d4a44;border-radius:50%;box-sizing:border-box"></i>casa fora da água<br>'+
 '<i style="background:#d9c6f0;border:2px dashed #5b2a86;border-radius:50%;box-sizing:border-box"></i>local candidato (não oficial)<br>'+
 '<i style="background:#b3382c"></i>via que alaga<br><i style="background:#8fa7b8"></i>via seca (tracejada: só a pé)<br><i style="background:#1e5fbf;opacity:.4"></i>área que alaga';
</script></body></html>"""


if __name__ == "__main__":
    main()
