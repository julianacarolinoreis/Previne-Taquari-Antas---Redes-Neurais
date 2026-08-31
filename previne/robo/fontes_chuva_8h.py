#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fontes oficiais de chuva usadas pelos modelos STZ de 8 horas.

O modulo e deliberadamente independente de numpy/scipy para poder ser usado
tanto pelo robo ao vivo quanto pelo atualizador do CSV de contingencia.
Nenhuma funcao interpola, replica vizinhos ou converte ausencia em zero.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.request


INMET_ESTACAO = "A894"
INMET_URL = "https://apitempo.inmet.gov.br/estacao/{ini}/{fim}/{cod}"

# O codigo oficial atual nao possui o zero extra presente no nome legado da
# coluna do CSV (chuva_cemaden_4320404010A).
CEMADEN_ESTACAO = "432040401A"
CEMADEN_ID = 8928
CEMADEN_URL = (
    "https://mapservices.cemaden.gov.br/MapaInterativoWS/resources/"
    "horario/{id_estacao}/{horas_menos_um}"
)

UA = {"User-Agent": "previne-robo-chuva/2.0", "Accept": "application/json"}


def _numero(valor):
    if valor in (None, "", "-"):
        return None
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if numero >= 0 else None


def _http_json(url, *, timeout=15, tentativas=2):
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resposta:
                bruto = resposta.read()
            if not bruto:  # 204 do INMET quando a estacao nao possui dados
                return None
            return json.loads(bruto.decode("utf-8-sig"))
        except Exception as exc:
            ultimo_erro = exc
            if tentativa < tentativas:
                time.sleep(tentativa)
    raise ultimo_erro


def parse_inmet_chuva(payload):
    """Converte o JSON horario INMET para o rotulo usado no Excel-mae.

    O INMET carimba a precipitacao na hora em que o acumulado termina. Depois
    de UTC -> BRT (-3h), aplica-se -1h para rotular a hora em que o intervalo
    comeca, igual a ANA/CEMADEN. Esse alinhamento foi conferido na preparacao
    historica do A894 por correlacao cruzada com as demais estacoes.
    """
    serie = {}
    if not isinstance(payload, list):
        return serie
    for registro in payload:
        if not isinstance(registro, dict):
            continue
        data = registro.get("DT_MEDICAO")
        hora_txt = str(registro.get("HR_MEDICAO") or "")
        chuva = _numero(registro.get("CHUVA"))
        digitos = "".join(c for c in hora_txt if c.isdigit())
        if not data or len(digitos) < 2 or chuva is None:
            continue
        try:
            hora_utc = dt.datetime.strptime(data, "%Y-%m-%d") + dt.timedelta(
                hours=int(digitos[:2])
            )
        except (TypeError, ValueError):
            continue
        serie[hora_utc - dt.timedelta(hours=4)] = chuva
    return serie


def parse_cemaden_chuva(payload, *, codigo_esperado=CEMADEN_ESTACAO):
    """Converte a grade horaria publica do CEMADEN (UTC) para BRT.

    O endpoint organiza uma mesma grade de horas em uma linha por data; as
    posicoes fora daquela data sao nulas. Somente celulas observadas entram na
    serie.
    """
    if not isinstance(payload, dict):
        return {}
    estacao = payload.get("estacao") or {}
    codigo = str(estacao.get("codEstacao") or "")
    if codigo_esperado and codigo != codigo_esperado:
        raise ValueError(
            f"CEMADEN devolveu estacao {codigo or 'sem_codigo'}, esperado {codigo_esperado}"
        )
    horarios = payload.get("horarios") or []
    datas = payload.get("datas") or []
    acumulados = payload.get("acumulados") or []
    if not isinstance(horarios, list) or not isinstance(acumulados, list):
        return {}

    serie = {}
    for indice_data, data_txt in enumerate(datas):
        if indice_data >= len(acumulados) or not isinstance(acumulados[indice_data], list):
            continue
        try:
            data_utc = dt.datetime.strptime(str(data_txt), "%d/%m/%Y")
        except ValueError:
            continue
        linha = acumulados[indice_data]
        for indice_hora, valor in enumerate(linha[: len(horarios)]):
            chuva = _numero(valor)
            if chuva is None:
                continue
            hora_txt = str(horarios[indice_hora]).lower().split("h", 1)[0]
            try:
                hora_utc = data_utc + dt.timedelta(hours=int(hora_txt))
            except ValueError:
                continue
            serie[hora_utc - dt.timedelta(hours=3)] = chuva
    return serie


def baixar_inmet_chuva_recente(
    *, cod=INMET_ESTACAO, agora_brt=None, dias=8, timeout=15, tentativas=2
):
    agora_brt = agora_brt or dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).replace(
        tzinfo=None
    )
    inicio = (agora_brt - dt.timedelta(days=dias)).date().isoformat()
    fim = agora_brt.date().isoformat()
    payload = _http_json(
        INMET_URL.format(ini=inicio, fim=fim, cod=cod),
        timeout=timeout,
        tentativas=tentativas,
    )
    return parse_inmet_chuva(payload)


def baixar_cemaden_chuva_recente(
    *, id_estacao=CEMADEN_ID, codigo=CEMADEN_ESTACAO, horas=168,
    timeout=15, tentativas=2
):
    if horas < 1:
        raise ValueError("horas precisa ser positivo")
    payload = _http_json(
        CEMADEN_URL.format(id_estacao=id_estacao, horas_menos_um=horas - 1),
        timeout=timeout,
        tentativas=tentativas,
    )
    return parse_cemaden_chuva(payload, codigo_esperado=codigo)


def metadados_serie(serie, *, codigo, fonte, endpoint, estado=None):
    horas = sorted(serie)
    return {
        "codigo": codigo,
        "fonte": fonte,
        "endpoint": endpoint,
        "estado": estado or ("com_dados" if horas else "sem_dado_observado"),
        "horas_observadas": len(horas),
        "ultima_hora_brt": horas[-1].isoformat(timespec="minutes") if horas else None,
    }
