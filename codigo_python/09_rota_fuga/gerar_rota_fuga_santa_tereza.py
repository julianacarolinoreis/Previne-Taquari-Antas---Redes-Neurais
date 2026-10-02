#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ROBÔ — Rota de fuga de Santa Tereza (Etapa 1: prova de conceito por quadra).

Cruza três coisas que já existem no projeto, SEM custo em token (roda no
GitHub Actions):

   1. TERRENO  -> HAND embutido em santa_tereza_previsao_inundacao.html, validado contra
      o contrato de campo. O limiar de régua do proxy em cada célula é
      ZERO_REGUA + HAND; não constitui observação de inundação.
   2. PREVISÃO -> previsao_ao_vivo.json, com origem na telemetria e alvos absolutos.
      Estima o cruzamento de limiares do proxy HAND, sem extrapolar a RNA.
      Horizontes de bases distintas são apresentados separadamente.
   3. FUGA     -> caminhada simulada até um destino de exercício, em linha reta
     com fator de desvio, na velocidade de um idoso (a maioria da população).

   margem simulada = estimativa de cruzamento do limiar − caminhada simulada

Saídas (commitadas pelo workflow):
  santa_tereza_rota_fuga.html          — mapa interativo (Leaflet)
  assets/data/rota_fuga_santa_tereza.json — dados por quadra (auditável)

ETAPA 1 é grosseira de propósito (grade de ~30 m, por quadra, linha reta):
serve para mostrar que a cadeia fecha e quanta margem a cidade teria numa
cheia — NÃO para orientar ninguém ainda. O terreno fino (drone), os endereços
e o roteamento por ruas entram nas etapas seguintes.

Uso:
  python codigo_python/09_rota_fuga/gerar_rota_fuga_santa_tereza.py [--cenario sintetico]

O alias legado --cenario 22jul produz somente o cenário sintético em arquivos
próprios; não recria nem sobrescreve os produtos históricos congelados.
"""
import os
import re
import io
import json
import base64
import sys
import hashlib
import html as html_lib
import argparse
import datetime as dt
from math import radians, cos, sin, asin, sqrt, isfinite

import numpy as np
from PIL import Image

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))
PAGINA_HAND = os.path.join(RAIZ, "santa_tereza_previsao_inundacao.html")
FORECAST = os.path.join(RAIZ, "previsao_ao_vivo.json")


def caminhos_saida(cenario):
    if cenario == "ao_vivo":
        return (os.path.join(RAIZ, "santa_tereza_rota_fuga.html"),
                os.path.join(RAIZ, "assets", "data", "rota_fuga_santa_tereza.json"))
    if cenario in {"sintetico", "22jul"}:
        return (os.path.join(RAIZ, "santa_tereza_rota_fuga_cenario_sintetico.html"),
                os.path.join(RAIZ, "assets", "data", "rota_fuga_santa_tereza_cenario_sintetico.json"))
    raise ValueError("cenário desconhecido; nenhum destino de escrita selecionado")

# ------------------------------------------------------------------ parâmetros
ZERO_REGUA_M = 1.60         # calibração de campo: 1,60 m na régua = HAND 0
BLOCO_M = 30.0              # tamanho da "quadra" na Etapa 1
VEL_IDOSO_MS = 0.9          # caminhada de idoso/criança (m/s) — conservador
VEL_ADULTO_MS = 1.3         # caminhada adulto (m/s), para comparação
FATOR_DESVIO = 1.4          # linha reta -> caminho real (Etapa 1; ruas entram depois)
FUSO_FEED = dt.timezone(dt.timedelta(hours=-3), "America/Sao_Paulo")
MAX_IDADE_TELEMETRIA_MIN = 120
TOLERANCIA_RELOGIO_MIN = 5
HORAS_HORIZONTES = {"2h": 2, "4h": 4, "8h": 8}
CENARIO_DURACAO_MIN = 360   # somente cenário sintético explícito, nunca extensão da RNA
CAVEAT = (
    "Pesquisa/exercício; não é alerta oficial. Estimativa de cruzamento de limiar "
    "do proxy HAND do rio principal, por interpolação linear entre alvos admissíveis, "
    "sem extrapolação da RNA. Não afirma água observada, tempo real de chegada da "
    "água, rota segura, necessidade de resgate ou ordem de evacuação. A caminhada "
    "é simulada em linha reta e o destino de exercício não está confirmado. "
    "Minutos e margens são medidos desde o horário da régua de referência."
)

# >>> PONTO SEGURO — A CONFIRMAR COM A DEFESA CIVIL <<<
# Placeholder no Centro (Av. Itália, 474 é a Prefeitura). NÃO é a coordenada
# oficial do ginásio: serve só para a prova de conceito rodar. Trocar assim
# que a Defesa Civil confirmar o(s) ponto(s) seguro(s).
PONTO_SEGURO = {
    "lat": -29.1745, "lon": -51.7305,
    "nome": "Destino de exercício (PLACEHOLDER — confirmar com a Defesa Civil)",
    "confirmado": False,
}

# recorte urbano aproximado (bbox) para a Etapa 1 — evita espalhar a grade pela
# encosta/mata. Ajustável quando os endereços (CNEFE) entrarem.
URBANO_BBOX = {"S": -29.190, "N": -29.160, "W": -51.745, "E": -51.720}


# --------------------------------------------------------------------- terreno
def decodifica_hand(payload: dict):
    """Valida o contrato antes de abrir o PNG; NoData e saturação viram NaN.

    O import é local para permitir testar a trajetória sem carregar terreno;
    ausência do validador impede o carregamento, sem alternativa permissiva.
    """
    from santa_tereza_hand_field_contract import validate_raster_payload

    contract = validate_raster_payload(payload)
    png = base64.b64decode(payload["hand_png_b64"], validate=True)
    if hashlib.sha256(png).hexdigest() != contract["hand_png_sha256"]:
        raise ValueError("digest do PNG HAND diverge do contrato validado")
    with Image.open(io.BytesIO(png)) as image:
        if image.format != "PNG" or image.mode != "L":
            raise ValueError("HAND precisa ser PNG monocromático de 8 bits, sem conversão")
        if image.size != (payload["cols"], payload["rows"]):
            raise ValueError("dimensões do PNG HAND divergem do payload")
        dm = np.array(image, dtype=np.float32)
    nodata = dm == payload["nodata"]
    saturated = dm == payload["saturated_value"]
    if np.any((dm > payload["saturated_value"]) & ~nodata):
        raise ValueError("PNG HAND contém códigos não definidos no contrato")
    hand = dm / 10.0
    hand[nodata | saturated] = np.nan
    geo = dict(payload)
    geo["raster_contract"] = contract
    geo["_nodata_mask"] = nodata
    geo["_saturated_mask"] = saturated
    return hand, geo


def carrega_hand():
    with open(PAGINA_HAND, encoding="utf-8") as stream:
        s = stream.read()
    m = re.search(r'id="hand-data"[^>]*>(\{.*?\})</script>', s, re.S)
    if m is None:
        raise ValueError("payload hand-data não encontrado")
    return decodifica_hand(json.loads(m.group(1)))


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


# ------------------------------------------------------------------- previsão
def _hora(value):
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError("horário ISO ausente ou inválido")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=FUSO_FEED)
    return parsed.astimezone(FUSO_FEED)


def _nivel_cm(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or not -500 <= value <= 5000):
        raise ValueError("nível ausente, não finito ou fora de -500 a 5000 cm")
    return float(value)


def trajetoria_nivel(forecast: dict, now=None, cenario="ao_vivo") -> dict:
    """Constrói trajetória e proveniência sem I/O; `now` aceita datetime ou ISO.

    `pontos` contém (minutos desde a telemetria, régua em m) da base principal.
    `grupos` conserva cada base, inclusive 8h separado; nenhuma base é fundida.
    Status de qualidade ATENCAO do feed é registrado como ressalva, não apagado.
    """
    if cenario not in {"ao_vivo", "sintetico", "22jul"}:
        raise ValueError("cenário desconhecido")
    checked_at = _hora(now if now is not None else dt.datetime.now(dt.timezone.utc))
    criteria = {
        "fuso_horarios_sem_offset": "America/Sao_Paulo (UTC-03:00)",
        "max_idade_telemetria_min": MAX_IDADE_TELEMETRIA_MIN,
        "tolerancia_relogio_min": TOLERANCIA_RELOGIO_MIN,
        "input_grade": "hourly_exact", "input_contract_version": "hourly_exact_v1",
        "horizonte_ativo": "disponivel=true; sem shadow_only=true/ativo_ao_vivo=false; status iniciado em ok",
        "auditoria_inputs": "NORMAL, fórmula conferida e zero inputs não exatos/ausentes",
        "faixa_nivel_cm": [-500, 5000],
        "idade_base_max_min": {key: hours * 60 for key, hours in HORAS_HORIZONTES.items()},
        "alvo": "hora_alvo = hora_modelo + horizonte; futuro em relação a now e telemetria",
        "extrapolacao_rna": False,
    }
    result = {
        "cenario": "ao_vivo" if cenario == "ao_vivo" else "sintetico",
        "status": "telemetria_indisponivel", "avaliado_em": checked_at.isoformat(),
        "origem_em": None, "campo_origem": None, "nivel_atual_cm": None,
        "idade_telemetria_min": None, "pontos": [], "grupos": [],
        "base_principal_em": None, "horizontes_principais": [],
        "horizontes_aceitos": [], "horizontes_separados": [],
        "horizontes_rejeitados": [], "alvos": {}, "criterios_validade": criteria,
        "caveat": CAVEAT, "rotulo": "estimativa de cruzamento de limiar — indisponível",
    }
    if cenario != "ao_vivo":
        result.update({
            "rotulo": "cenário sintético de exercício — telemetria indisponível",
            "caveat": "Cenário sintético explícito, não é replay nem previsão de RNA. " + CAVEAT,
            "parametros_cenario": {"taxa_subida_cm_por_hora": 40, "duracao_min": CENARIO_DURACAO_MIN,
                                   "nivel_inicial": "telemetria_validada", "natureza": "sintetico_nao_replay"},
        })
    horizons = forecast.get("horizontes") or {}
    if not isinstance(horizons, dict):
        horizons = {}
    reasons = []
    try:
        result["nivel_atual_cm"] = _nivel_cm(forecast.get("telemetria_ultima_nivel_cm"))
    except ValueError as exc:
        reasons.append(str(exc))
    field = ("telemetria_ultima_hora" if forecast.get("telemetria_ultima_hora")
             else "telemetria_ultima_em")
    result["campo_origem"] = field
    origin = None
    try:
        origin = _hora(forecast.get(field))
        result["origem_em"] = origin.isoformat()
        age = (checked_at - origin).total_seconds() / 60
        result["idade_telemetria_min"] = round(age, 2)
        if age > MAX_IDADE_TELEMETRIA_MIN:
            reasons.append("telemetria_vencida")
        if age < -TOLERANCIA_RELOGIO_MIN:
            reasons.append("telemetria_no_futuro")
    except ValueError as exc:
        reasons.append(str(exc))
    if reasons:
        result["motivos_indisponibilidade"] = reasons
        for key in HORAS_HORIZONTES:
            item = horizons.get(key) or {}
            result["alvos"][key] = {
                "hora_modelo": item.get("hora_modelo") if isinstance(item, dict) else None,
                "hora_alvo": item.get("hora_alvo") if isinstance(item, dict) else None,
            }
            result["horizontes_rejeitados"].append({"horizonte": key, "motivos": reasons[:]})
        return result

    anchor = (0.0, result["nivel_atual_cm"] / 100.0)
    result["pontos"] = [anchor]
    if cenario in {"sintetico", "22jul"}:
        result.update({
            "status": "cenario_sintetico", "rotulo": "cenário sintético de exercício (+40 cm/h)",
            "pontos": [(minute, anchor[1] + 0.40 * minute / 60)
                       for minute in range(0, CENARIO_DURACAO_MIN + 1, 10)],
        })
        return result

    groups = {}
    for key, hours in HORAS_HORIZONTES.items():
        item = horizons.get(key)
        rejected = []
        if not isinstance(item, dict):
            result["horizontes_rejeitados"].append({"horizonte": key, "motivos": ["horizonte_ausente"]})
            continue
        info = {
            "horizonte": key, "hora_modelo": item.get("hora_modelo"),
            "hora_alvo": item.get("hora_alvo"), "status_feed": item.get("status"),
            "fallback_ativo": item.get("fallback_ativo", False),
            "qualidade_ao_vivo": item.get("qualidade_ao_vivo"),
        }
        result["alvos"][key] = info
        if item.get("disponivel") is not True:
            rejected.append("horizonte_indisponivel")
        if item.get("shadow_only") is True or item.get("ativo_ao_vivo") is False:
            rejected.append("horizonte_comparativo_ou_inativo")
        if not str(item.get("status") or "").lower().startswith("ok"):
            rejected.append("status_feed_nao_ok")
        if (item.get("input_grade") != "hourly_exact"
                or item.get("input_contract_version") != "hourly_exact_v1"):
            rejected.append("contrato_temporal_invalido")
        audit = item.get("auditoria_inputs") or {}
        if (not isinstance(audit, dict) or audit.get("status") != "NORMAL"
                or audit.get("formula_conferida_com_montador") is not True
                or audit.get("n_inputs_nao_exatos", 0) != 0
                or audit.get("n_interpolados", 0) != 0
                or audit.get("n_vizinhos_mais_proximos", 0) != 0
                or audit.get("n_inputs_ausentes", 0) != 0
                or audit.get("n_inputs_atrasados", 0) != 0
                or audit.get("n_inputs_fora_faixa", 0) != 0
                or item.get("inputs_faltantes_n", 0) != 0):
            rejected.append("inputs_nao_validados")
        predicted = None
        try:
            # O timestamp em passos[0] é a base do modelo, NÃO o alvo previsto.
            predicted = _nivel_cm(item.get("nivel_previsto_cm"))
        except ValueError as exc:
            rejected.append(str(exc))
        base, target = None, None
        try:
            base, target = _hora(item.get("hora_modelo")), _hora(item.get("hora_alvo"))
            info.update({"hora_modelo": base.isoformat(), "hora_alvo": target.isoformat(),
                         "minutos_desde_telemetria": (target - origin).total_seconds() / 60,
                         "idade_base_min": round((checked_at - base).total_seconds() / 60, 2)})
            if base.minute or base.second or base.microsecond:
                rejected.append("base_fora_grade_horaria")
            if abs((target - base).total_seconds() - hours * 3600) > 1e-6:
                rejected.append("alvo_incompativel_com_horizonte")
            if target <= checked_at or target <= origin:
                rejected.append("alvo_vencido")
            if (checked_at - base).total_seconds() / 60 > hours * 60:
                rejected.append("base_vencida")
            if (base - origin).total_seconds() / 60 > TOLERANCIA_RELOGIO_MIN:
                rejected.append("base_posterior_a_telemetria")
        except ValueError as exc:
            rejected.append(str(exc))
        if rejected:
            result["horizontes_rejeitados"].append({**info, "motivos": rejected})
            continue
        info["nivel_previsto_cm"] = predicted
        info["ressalvas"] = []
        if "atencao" in str(item.get("status")).lower() or "atenção" in str(item.get("status")).lower():
            info["ressalvas"].append("feed_com_ressalva_de_qualidade_ou_base")
        group = groups.setdefault(base.isoformat(), {
            "base_em": base.isoformat(), "origem_em": origin.isoformat(),
            "horizontes": [], "pontos": [anchor],
        })
        group["horizontes"].append(key)
        group["pontos"].append((info["minutos_desde_telemetria"], predicted / 100.0))
        result["horizontes_aceitos"].append(key)

    result["grupos"] = list(groups.values())
    if groups:
        # Ordem 2h/4h/8h: o primeiro horizonte admissível define a base principal.
        primary = result["grupos"][0]
        result["base_principal_em"] = primary["base_em"]
        result["horizontes_principais"] = primary["horizontes"]
        for group in result["grupos"]:
            group["pontos"].sort(key=lambda point: point[0])
            group["usado_na_classificacao"] = group is primary
            if group is not primary:
                result["horizontes_separados"].extend(group["horizontes"])
        result["pontos"] = primary["pontos"]
        result["status"] = "ok"
        result["rotulo"] = "estimativa de cruzamento de limiar — RNA " + "/".join(primary["horizontes"])
    else:
        result["status"] = "sem_previsao_admissivel"
        result["rotulo"] = "estimativa de cruzamento de limiar — sem previsão admissível"
    return result


def tempo_ate(cota_m, pts):
    """Estima o primeiro cruzamento do limiar, sem extrapolar nem observar água."""
    if not pts:
        return None
    if pts[0][1] >= cota_m:
        return 0.0
    for (ma, na), (mb, nb) in zip(pts, pts[1:]):
        if nb >= cota_m:
            if nb == na:
                return mb
            return ma + (mb - ma) * (cota_m - na) / (nb - na)
    return None


# --------------------------------------------------------------------- grade
def monta_quadras(hand, geo, trajetoria):
    pts = trajetoria["pontos"]
    ny, nx = hand.shape
    S, W, N, E = geo["S"], geo["W"], geo["N"], geo["E"]
    dlat = (N - S) / ny            # graus por pixel (lat, positivo p/ cima na img invertida)
    dlon = (E - W) / nx
    lat0 = (S + N) / 2
    m_por_grau_lat = 111320.0
    m_por_grau_lon = 111320.0 * cos(radians(lat0))
    px_por_bloco_y = max(1, int(round(BLOCO_M / (abs(dlat) * m_por_grau_lat))))
    px_por_bloco_x = max(1, int(round(BLOCO_M / (abs(dlon) * m_por_grau_lon))))

    quadras = []
    for by in range(0, ny, px_por_bloco_y):
        for bx in range(0, nx, px_por_bloco_x):
            blk = hand[by:by + px_por_bloco_y, bx:bx + px_por_bloco_x]
            if blk.size == 0:
                continue
            # centro da célula em lat/lon (imagem: linha 0 = Norte)
            cy = by + blk.shape[0] / 2
            cx = bx + blk.shape[1] / 2
            lat = N - dlat * cy
            lon = W + dlon * cx
            if not (URBANO_BBOX["S"] <= lat <= URBANO_BBOX["N"]
                    and URBANO_BBOX["W"] <= lon <= URBANO_BBOX["E"]):
                continue
            valid = np.isfinite(blk)
            h = float(np.min(blk[valid])) if np.any(valid) else None
            # Não confundir código NoData/saturação com HAND 0, que é válido.
            sat_mask = geo.get("_saturated_mask")
            has_saturation = (bool(np.any(sat_mask[by:by + blk.shape[0], bx:bx + blk.shape[1]]))
                              if sat_mask is not None else False)
            cota = ZERO_REGUA_M + h if h is not None else None
            tw = tempo_ate(cota, pts) if cota is not None else None
            if h is None:
                status = "terreno_saturado" if has_saturation else "sem_dado_terreno"
            elif tw == 0:
                status = "limiar_atingido_na_origem"
            elif tw is not None:
                status = "estimativa_cruzamento"
            elif len(pts) < 2:
                status = "previsao_indisponivel"
            else:
                status = "sem_cruzamento_no_intervalo"
            dist = haversine_m(lat, lon, PONTO_SEGURO["lat"], PONTO_SEGURO["lon"]) * FATOR_DESVIO
            t_idoso = dist / VEL_IDOSO_MS / 60.0
            t_adulto = dist / VEL_ADULTO_MS / 60.0
            margem = tw - t_idoso if tw is not None else None
            quadras.append({
                "lat": round(lat, 6), "lon": round(lon, 6),
                "hand_m": round(h, 2) if h is not None else None,
                "limiar_regua_m": round(cota, 2) if cota is not None else None,
                "min_ate_limiar": round(tw, 1) if tw is not None else None,
                "status": status,
                "fracao_raster_valida": round(float(np.mean(valid)), 4),
                "terreno_parcial": not bool(np.all(valid)),
                "dist_m": round(dist, 0),
                "min_caminhada_idoso": round(t_idoso, 1),
                "min_caminhada_adulto": round(t_adulto, 1),
                "margem_min": round(margem, 1) if margem is not None else None,
                "classe": classe(margem, tw, status),
            })
    passo_lat = abs(dlat) * px_por_bloco_y
    passo_lon = abs(dlon) * px_por_bloco_x
    return quadras, passo_lat, passo_lon


def classe(margem, tw, status=None):
    if status in {"sem_dado_terreno", "terreno_saturado"}:
        return status
    if status == "previsao_indisponivel":
        return "indisponivel"
    if tw is None:
        return "sem_cruzamento"
    if tw <= 0:
        return "limiar_na_origem"
    if margem < 0:
        return "margem_negativa"
    if margem < 15:
        return "margem_ate_15"
    if margem < 60:
        return "margem_15_60"
    return "margem_acima_60"


# ---------------------------------------------------------------------- saída
CORES = {"limiar_na_origem": "#1e5fbf", "margem_negativa": "#b3382c",
         "margem_ate_15": "#e8730c", "margem_15_60": "#d49f00",
         "margem_acima_60": "#537c9f", "sem_cruzamento": "#7b8491",
         "indisponivel": "#966fa5", "sem_dado_terreno": "#505050",
         "terreno_saturado": "#635c42"}


def escreve_json(quadras, meta, SAIDA_JSON):
    os.makedirs(os.path.dirname(SAIDA_JSON), exist_ok=True)
    resumo = {c: sum(1 for q in quadras if q["classe"] == c) for c in CORES}
    doc = {"meta": meta, "resumo": resumo, "quadras": quadras}
    json.dump(doc, open(SAIDA_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return resumo


def render_html(quadras, passo_lat, passo_lon, meta, resumo):
    """Renderização pura para verificação em memória, sem gerar artefatos."""
    ps = PONTO_SEGURO
    caveat = meta["temporal"]["caveat"]
    banner_conf = '<div class="aviso">' + html_lib.escape(caveat) + '</div>'
    temporal = meta["temporal"]
    esc = lambda value: html_lib.escape(str(value if value is not None else "indisponível"))
    temporal_lines = []
    for key, info in temporal["alvos"].items():
        if key in temporal["horizontes_aceitos"]:
            scope = ("comparação separada; fora dos tempos por quadra"
                     if key in temporal["horizontes_separados"] else "usado na estimativa por quadra")
            quality = " · ressalva de qualidade/base no feed" if info["ressalvas"] else ""
            temporal_lines.append(
                f'<li>{esc(key)}: base {esc(info["hora_modelo"])}; alvo {esc(info["hora_alvo"])} '
                f'(+{info["minutos_desde_telemetria"]:.0f} min da referência); '
                f'régua prevista {info["nivel_previsto_cm"] / 100:.2f} m; {scope}{quality}.</li>'
            )
    rejected_labels = {
        "horizonte_ausente": "horizonte ausente", "horizonte_indisponivel": "previsão indisponível",
        "horizonte_comparativo_ou_inativo": "modelo comparativo ou inativo",
        "status_feed_nao_ok": "estado inválido no feed", "contrato_temporal_invalido": "contrato temporal inválido",
        "inputs_nao_validados": "entradas incompletas ou não validadas",
        "base_fora_grade_horaria": "base fora da grade horária", "alvo_incompativel_com_horizonte": "alvo incompatível com a base",
        "alvo_vencido": "alvo vencido", "base_vencida": "base vencida",
        "base_posterior_a_telemetria": "base posterior à referência observada",
        "telemetria_vencida": "telemetria vencida", "telemetria_no_futuro": "horário da telemetria no futuro",
    }
    for rejected in temporal["horizontes_rejeitados"]:
        reasons = "; ".join(rejected_labels.get(reason, reason) for reason in rejected["motivos"])
        temporal_lines.append(f'<li>{esc(rejected["horizonte"])} indisponível: {esc(reasons)}.</li>')
    temporal_html = (
        '<div class="sub">Referência da régua: ' + esc(temporal["origem_em"]) + '</div>'
        '<div class="sub">Validade conferida em: ' + esc(temporal["avaliado_em"]) + '</div>'
        '<details class="sub"><summary>Horizontes, bases e alvos</summary><ul>'
        + ''.join(temporal_lines) + '</ul></details>'
    )
    dados = json.dumps({"quadras": quadras, "dlat": passo_lat, "dlon": passo_lon,
                        "seguro": ps, "estacao": meta["estacao"], "ponte": meta["ponte"],
                        "cores": CORES}, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    return (_TEMPLATE.replace("__DADOS__", dados).replace("__BANNER__", banner_conf)
            .replace("__NIVEL__", esc(meta["nivel_txt"]))
            .replace("__CENARIO__", esc(meta["cenario_rotulo"]))
            .replace("__GERADO__", esc(meta["gerado_em"]))
            .replace("__TEMPORAL__", temporal_html).replace("__RESUMO__", json.dumps(resumo)))


def escreve_html(quadras, passo_lat, passo_lon, meta, resumo, SAIDA_HTML):
    with open(SAIDA_HTML, "w", encoding="utf-8") as stream:
        stream.write(render_html(quadras, passo_lat, passo_lon, meta, resumo))


_TEMPLATE = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rotas de exercício — Santa Tereza (pesquisa)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#12211b}
 #map{position:absolute;top:0;bottom:0;left:0;right:0}
 .hud{position:absolute;z-index:500;top:10px;left:10px;background:#fff;border-radius:10px;
       box-shadow:0 2px 12px rgba(0,0,0,.15);padding:12px 14px;
       max-width:min(340px,calc(100vw - 60px));max-height:50vh;overflow:auto}
 .hud h1{font:600 16px Georgia,serif;margin:0 0 4px}
 .hud .lv{font-variant-numeric:tabular-nums;color:#0f6b4a;font-weight:700}
 .hud .sub{color:#5b6b62;font-size:12.5px;margin:2px 0}
 .aviso{background:#fdecea;border:1px solid #f2b8b2;color:#b3382c;border-radius:8px;
        padding:8px 10px;font-size:12px;margin-top:8px}
 .leg{position:absolute;z-index:500;bottom:14px;left:10px;background:#fff;border-radius:10px;
       box-shadow:0 2px 12px rgba(0,0,0,.15);padding:10px 12px;font-size:12.5px;
       max-width:min(340px,calc(100vw - 60px));max-height:30vh;overflow:auto}
 .leg i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-2px}
 .leaflet-popup-content{font-size:13px}
</style></head><body>
<div id="map"></div>
<div class="hud">
  <h1>Rotas de exercício · Santa Tereza</h1>
  <div class="sub">Prova de conceito (Etapa 1) — <b>__CENARIO__</b></div>
  <div class="sub">Calibração de campo: régua 1,60 m = HAND 0 · somente rio principal.</div>
  <div class="sub">Conversão: HAND = max(0, régua_m − 1,60).</div>
  <div class="sub">Nível: <span class="lv">__NIVEL__</span></div>
  <div class="sub">Gerado: __GERADO__</div>
  __TEMPORAL__
  __BANNER__
</div>
<div class="leg" id="leg"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D=__DADOS__, RES=__RESUMO__;
const map=L.map('map');
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
 {maxZoom:19,attribution:'Esri World Imagery'}).addTo(map);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
 {maxZoom:19,opacity:.9}).addTo(map);
const ROT={limiar_na_origem:'limiar atingido pela régua de referência',
  margem_negativa:'margem simulada negativa',margem_ate_15:'margem simulada de 0 a menos de 15 min',
  margem_15_60:'margem simulada de 15 a menos de 60 min',margem_acima_60:'margem simulada de 60 min ou mais',
  sem_cruzamento:'sem cruzamento no intervalo disponível',indisponivel:'estimativa temporal indisponível',
  sem_dado_terreno:'sem dado de terreno',terreno_saturado:'terreno saturado no raster (≥25 m)'};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const b=L.latLngBounds();
D.quadras.forEach(q=>{
  const dy=D.dlat/2, dx=D.dlon/2;
  const rect=L.rectangle([[q.lat-dy,q.lon-dx],[q.lat+dy,q.lon+dx]],
    {stroke:false,fillColor:D.cores[q.classe],fillOpacity:.65});
  const tempo=Number.isFinite(q.min_ate_limiar)
    ? (q.min_ate_limiar===0?'limiar atingido na referência':q.min_ate_limiar+' min desde a referência')
    : ROT[q.classe];
  const margem=Number.isFinite(q.margem_min)?q.margem_min+' min':'indisponível';
  const terreno=Number.isFinite(q.hand_m)?`limiar de régua: ${q.limiar_regua_m} m · HAND ${q.hand_m} m`:'sem limiar espacial estimável';
  rect.bindPopup(`<b>Quadra de exercício</b><br>Estimativa de cruzamento de limiar: <b>${tempo}</b><br>`+
    `Caminhada simulada ao destino (0,9 m/s): <b>${q.min_caminhada_idoso} min</b> · ${q.dist_m} m<br>`+
    `Margem simulada desde a referência: <b>${margem}</b> — ${ROT[q.classe]}<br>`+
    `<span style="color:#5b6b62">${terreno}${q.terreno_parcial?' · cobertura de terreno parcial':''}</span><br>`+
    `<small>Pesquisa: não é alerta oficial nem confirmação de água ou rota segura.</small>`);
  rect.addTo(map); b.extend([q.lat,q.lon]);
});
// destino de exercício
const seg=L.marker([D.seguro.lat,D.seguro.lon]).addTo(map);
seg.bindPopup('<b>'+esc(D.seguro.nome)+'</b>'); b.extend([D.seguro.lat,D.seguro.lon]);
L.circleMarker([D.estacao.lat,D.estacao.lon],{radius:6,color:'#1e5fbf',fillColor:'#1e5fbf',fillOpacity:1})
  .bindPopup('Estação '+esc(D.estacao.code)).addTo(map);
if(D.ponte) L.circleMarker([D.ponte.lat,D.ponte.lon],{radius:5,color:'#555',fillColor:'#999',fillOpacity:1})
  .bindPopup(esc(D.ponte.label||'Ponte')).addTo(map);
map.fitBounds(b.pad(0.15));
// legenda
const ordem=Object.keys(D.cores);
document.getElementById('leg').innerHTML='<b>Margem simulada e disponibilidade</b><br>'+ordem.map(c=>
 `<i style="background:${D.cores[c]}"></i>${ROT[c]} <span style="color:#5b6b62">(${RES[c]||0})</span>`).join('<br>');
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cenario", default="ao_vivo", choices=["ao_vivo", "sintetico", "22jul"],
                    help="22jul é alias de sintetico; históricos congelados nunca são regravados")
    args = ap.parse_args()

    cenario = "sintetico" if args.cenario == "22jul" else args.cenario
    SAIDA_HTML, SAIDA_JSON = caminhos_saida(cenario)
    hand, geo = carrega_hand()
    with open(FORECAST, encoding="utf-8") as stream:
        forecast = json.load(stream)
    temporal = trajetoria_nivel(forecast, cenario=cenario)
    nivel_cm = temporal["nivel_atual_cm"]
    quadras, passo_lat, passo_lon = monta_quadras(hand, geo, temporal)

    nivel_txt = (f"{nivel_cm/100:.2f} m (régua de referência)"
                 if nivel_cm is not None and temporal["status"] != "telemetria_indisponivel"
                 else "telemetria indisponível para estimativa")
    meta = {
        "schema_version": "stz_route_research_v2",
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cenario": cenario, "argumento_cenario": args.cenario, "cenario_rotulo": temporal["rotulo"],
        "nivel_atual_cm": nivel_cm, "nivel_txt": nivel_txt,
        "zero_regua_m": ZERO_REGUA_M, "bloco_m": BLOCO_M,
        "formula_regua_para_hand": "HAND = max(0, regua_m - 1.60)",
        "raster_contract": geo["raster_contract"], "temporal": temporal,
        "ponto_seguro": PONTO_SEGURO, "etapa": 1,
        "estacao": geo["station"], "ponte": geo.get("ponte"),
        "status": "pesquisa_exercicio_nao_operacional", "aviso": temporal["caveat"],
    }
    resumo = escreve_json(quadras, meta, SAIDA_JSON)
    escreve_html(quadras, passo_lat, passo_lon, meta, resumo, SAIDA_HTML)
    print(f"cenario={cenario} nivel={nivel_txt} quadras={len(quadras)} resumo={resumo}")
    print(f"-> {SAIDA_HTML}")
    print(f"-> {SAIDA_JSON}")


if __name__ == "__main__":
    main()
