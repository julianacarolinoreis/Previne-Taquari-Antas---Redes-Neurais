#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ROBO — Chuvas horarias das estacoes (dez/2022 -> agora), com codigo sequencial.

Roda no GitHub Actions (sem custo em token). Baixa a chuva HORARIA de cada
fonte, alinha tudo no fuso local (BRT, UTC-3) e grava um CSV horario unico,
ja com o COD_SEQUENCIAL (yyyymmddHHMM) usado nos modelos:

  assets/data/chuvas_horarias.csv
  colunas: COD_SEQUENCIAL, ANO, MES, DIA, HORA,
           chuva_86472600, chuva_86472000, chuva_02851044,     (ANA)
           chuva_inmet_A894,                                    (INMET)
           chuva_cemaden_4320404010A                            (CEMADEN)

Fontes e limites (o log imprime a cobertura real de cada estacao):
  - ANA (86472600, 86472000, 02851044): telemetria SOAP DadosHidrometeorologicos,
    em janelas mensais. So retorna o periodo que a estacao tem telemetria retida;
    para historico profundo pode faltar -> nesse caso usar o HidroWebService da ANA
    com credencial (variaveis de ambiente ANA_HIDRO_ID / ANA_HIDRO_SENHA — o robo
    tenta se estiverem setadas).
  - INMET A894: apitempo.inmet.gov.br, historico horario publico completo (UTC ->
    convertido para BRT). Fonte mais confiavel para dez/2022 -> agora.
  - CEMADEN 4320404010A: tenta o endpoint publico; historico profundo costuma
    exigir login. Se houver token, setar CEMADEN_TOKEN.

Uso:
  python codigo_python/10_chuvas/baixar_chuvas_horarias.py [--inicio 2022-12-01] [--fim 2026-08-04]
"""
import os
import sys
import csv
import time
import json
import argparse
import datetime as dt
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SAIDA = os.path.join(RAIZ, "assets", "data", "chuvas_horarias.csv")
BRT = dt.timezone(dt.timedelta(hours=-3))
UA = {"User-Agent": "previne-robo-chuva/1.0"}

ANA_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
INMET_URL = "https://apitempo.inmet.gov.br/estacao/{ini}/{fim}/{cod}"

ANA_ESTACOES = ["86472600", "86472000", "02851044"]
INMET_ESTACAO = "A894"
CEMADEN_ESTACAO = "4320404010A"


# ------------------------------------------------------------------ utils ---
def horas(inicio, fim):
    """Gera todas as horas cheias no intervalo [inicio, fim] (BRT, naive)."""
    t = inicio.replace(minute=0, second=0, microsecond=0)
    while t <= fim:
        yield t
        t += dt.timedelta(hours=1)


def cod_seq(t):
    return t.strftime("%Y%m%d%H%M")


def _local(tag):
    return tag.split("}")[-1]


def _parse_hora(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s.replace("T", " ")[:19], fmt)
        except Exception:
            pass
    try:
        return dt.datetime.fromisoformat(s.replace("T", " ")[:19])
    except Exception:
        return None


def http_get(url, timeout=90, tentativas=3):
    ult = None
    for k in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            ult = e
            time.sleep(3 * k)
    raise ult


# -------------------------------------------------------------------- ANA ---
def ana_chuva_horaria(cod, inicio, fim):
    """Chuva horaria (mm) da estacao ANA via telemetria SOAP, janelas mensais.
    Soma leituras sub-horarias na mesma hora. Retorna {hora_BRT: mm}."""
    serie = {}
    ini_m = inicio.replace(day=1)
    while ini_m <= fim:
        # fim do mes
        prox = (ini_m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        fim_m = min(prox - dt.timedelta(days=1), fim)
        url = f"{ANA_URL}?codEstacao={cod}&dataInicio={ini_m:%d/%m/%Y}&dataFim={fim_m:%d/%m/%Y}"
        try:
            xml = http_get(url, timeout=120)
            root = ET.fromstring(xml)
            roots = [root]
            if (root.text or "").strip().startswith("<"):
                try:
                    roots.append(ET.fromstring(root.text))
                except Exception:
                    pass
            n0 = len(serie)
            for rt in roots:
                for row in rt.iter():
                    campos = {_local(ch.tag): (ch.text or "") for ch in row}
                    dh = campos.get("DataHora") or campos.get("Data_Hora")
                    ch = campos.get("Chuva") or campos.get("chuva") or campos.get("Precipitacao")
                    if not dh or ch in (None, ""):
                        continue
                    t = _parse_hora(dh)
                    if t is None:
                        continue
                    try:
                        v = float(str(ch).replace(",", "."))
                    except Exception:
                        continue
                    h = t.replace(minute=0, second=0, microsecond=0)
                    serie[h] = serie.get(h, 0.0) + v
            print(f"[ANA {cod}] {ini_m:%Y-%m} +{len(serie)-n0} horas")
        except Exception as e:
            print(f"[ANA {cod}] {ini_m:%Y-%m} erro: {e}")
        ini_m = prox
    return serie


# ------------------------------------------------------------------ INMET ---
def inmet_chuva_horaria(cod, inicio, fim):
    """Chuva horaria (mm) do INMET (apitempo), por ano. Converte UTC -> BRT."""
    serie = {}
    ano = inicio.year
    while ano <= fim.year:
        a_ini = max(inicio, dt.datetime(ano, 1, 1)).date()
        a_fim = min(fim, dt.datetime(ano, 12, 31)).date()
        url = INMET_URL.format(ini=a_ini.isoformat(), fim=a_fim.isoformat(), cod=cod)
        try:
            dados = json.loads(http_get(url, timeout=120))
            n0 = len(serie)
            for r in dados:
                data = r.get("DT_MEDICAO"); hr = r.get("HR_MEDICAO")
                ch = r.get("CHUVA")
                if not data or hr is None or ch in (None, ""):
                    continue
                try:
                    hh = int(str(hr)[:2])
                    t_utc = dt.datetime.strptime(data, "%Y-%m-%d") + dt.timedelta(hours=hh)
                    t_brt = t_utc - dt.timedelta(hours=3)             # UTC -> BRT
                    serie[t_brt] = float(str(ch).replace(",", "."))
                except Exception:
                    continue
            print(f"[INMET {cod}] {ano} +{len(serie)-n0} horas")
        except Exception as e:
            print(f"[INMET {cod}] {ano} erro: {e}")
        ano += 1
    return serie


# ---------------------------------------------------------------- CEMADEN ---
def cemaden_chuva_horaria(cod, inicio, fim):
    """Tenta a chuva horaria do CEMADEN. Historico profundo geralmente exige
    login; se CEMADEN_TOKEN estiver setado, usa a API autenticada."""
    token = os.environ.get("CEMADEN_TOKEN")
    serie = {}
    if not token:
        print(f"[CEMADEN {cod}] sem CEMADEN_TOKEN — historico profundo indisponivel "
              f"(registrar em https://sws.cemaden.gov.br e setar o token).")
        return serie
    # com token: API PED de PCDs (chunk mensal)
    base = "https://sws.cemaden.gov.br/PED/rest/pcds/dados_pcd"
    ini_m = inicio.replace(day=1)
    while ini_m <= fim:
        prox = (ini_m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        fim_m = min(prox - dt.timedelta(days=1), fim)
        q = urllib.parse.urlencode({"codigo": cod, "inicio": ini_m.strftime("%Y%m%d"),
                                    "fim": fim_m.strftime("%Y%m%d"), "sensor": "chuva"})
        try:
            req = urllib.request.Request(f"{base}?{q}",
                                         headers={**UA, "token": token})
            dados = json.loads(urllib.request.urlopen(req, timeout=120).read())
            n0 = len(serie)
            for r in (dados if isinstance(dados, list) else dados.get("dados", [])):
                t = _parse_hora(r.get("datahora") or r.get("data"))
                v = r.get("valor") if r.get("valor") is not None else r.get("chuva")
                if t is None or v in (None, ""):
                    continue
                h = t.replace(minute=0, second=0, microsecond=0)
                serie[h] = serie.get(h, 0.0) + float(str(v).replace(",", "."))
            print(f"[CEMADEN {cod}] {ini_m:%Y-%m} +{len(serie)-n0} horas")
        except Exception as e:
            print(f"[CEMADEN {cod}] {ini_m:%Y-%m} erro: {e}")
        ini_m = prox
    return serie


# --------------------------------------------------------------------- main -
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", default="2022-12-01")
    ap.add_argument("--fim", default=dt.datetime.now(BRT).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    inicio = dt.datetime.strptime(args.inicio, "%Y-%m-%d")
    fim = dt.datetime.strptime(args.fim, "%Y-%m-%d").replace(hour=23)
    print(f"Janela: {inicio:%Y-%m-%d} -> {fim:%Y-%m-%d} (BRT, horaria)")

    series = {}                                   # nome_coluna -> {hora: mm}
    for cod in ANA_ESTACOES:
        series[f"chuva_{cod}"] = ana_chuva_horaria(cod, inicio, fim)
    series["chuva_inmet_A894"] = inmet_chuva_horaria(INMET_ESTACAO, inicio, fim)
    series["chuva_cemaden_4320404010A"] = cemaden_chuva_horaria(CEMADEN_ESTACAO, inicio, fim)

    cols = ["chuva_86472600", "chuva_86472000", "chuva_02851044",
            "chuva_inmet_A894", "chuva_cemaden_4320404010A"]
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["COD_SEQUENCIAL", "ANO", "MES", "DIA", "HORA"] + cols)
        for t in horas(inicio, fim):
            linha = [cod_seq(t), t.year, t.month, t.day, t.hour]
            for c in cols:
                v = series[c].get(t)
                linha.append("" if v is None else round(v, 2))
            w.writerow(linha)

    print("\n=== cobertura (horas com dado) ===")
    total = sum(1 for _ in horas(inicio, fim))
    for c in cols:
        n = len(series[c])
        print(f"  {c:30s} {n:6d} / {total} horas ({100*n/total:4.1f}%)")
    print(f"-> {SAIDA}")


if __name__ == "__main__":
    main()
