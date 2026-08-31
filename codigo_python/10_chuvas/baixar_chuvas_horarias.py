#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ROBO — Chuvas horarias das estacoes (dez/2022 -> agora), com codigo sequencial.

Roda no GitHub Actions (sem custo em token). Baixa a chuva HORARIA de cada
fonte, alinha tudo no fuso local (BRT, UTC-3) e grava um CSV horario unico,
ja com o COD_SEQUENCIAL (yyyymmddHHMM) usado nos modelos:

  assets/data/chuvas_horarias.csv
  colunas: COD_SEQUENCIAL, ANO, MES, DIA, HORA,
           chuva_86472600, chuva_86472000, chuva_02851072,     (ANA)
           chuva_inmet_A894,                                    (INMET)
           chuva_cemaden_4320404010A                            (CEMADEN)

Fontes e limites (o log imprime a cobertura real de cada estacao):
  - ANA (86472600, 86472000, 02851044): telemetria SOAP DadosHidrometeorologicos,
    em janelas mensais. So retorna o periodo que a estacao tem telemetria retida;
    para historico profundo pode faltar -> nesse caso usar o HidroWebService da ANA
    com credencial (variaveis de ambiente ANA_HIDRO_ID / ANA_HIDRO_SENHA — o robo
    tenta se estiverem setadas).
  - INMET A894: apitempo.inmet.gov.br (UTC -> BRT). Quando a estacao estiver em
    pane, o endpoint pode responder sem dados; isso e ausencia, nunca chuva zero.
  - CEMADEN 432040401A: grade horaria publica recente; historico profundo usa
    CEMADEN_TOKEN quando disponivel. O nome legado da coluna conserva o zero
    extra apenas para compatibilidade.

O arquivo anterior e mesclado antes da gravacao: falha transitoria de uma API
nao apaga observacoes reais ja publicadas.

Uso:
  python codigo_python/10_chuvas/baixar_chuvas_horarias.py [--inicio 2022-12-01] [--fim 2026-08-04]
"""
import os
import sys
import csv
import time
import json
import gzip
import argparse
import datetime as dt
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from previne.robo.fontes_chuva_8h import (  # noqa: E402
    CEMADEN_ESTACAO,
    CEMADEN_ID,
    INMET_ESTACAO,
    INMET_URL,
    baixar_cemaden_chuva_recente,
)

SAIDA = os.path.join(RAIZ, "assets", "data", "chuvas_horarias.csv")
BRT = dt.timezone(dt.timedelta(hours=-3))
UA = {"User-Agent": "previne-robo-chuva/1.0"}

ANA_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"

ANA_ESTACOES = {
    "chuva_86472600": "86472600",
    "chuva_86472000": "86472000",
    "chuva_02851072": "2851072",
}
COLUNAS = [
    "chuva_86472600",
    "chuva_86472000",
    "chuva_02851044",  # legado preservado; nao e input do Excel-mae de 8h
    "chuva_02851072",
    "chuva_inmet_A894",
    "chuva_cemaden_4320404010A",
]


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


def http_get(url, timeout=90, tentativas=3, headers=None):
    ult = None
    for k in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            resp = urllib.request.urlopen(req, timeout=timeout)
            dados = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip" or dados[:2] == b"\x1f\x8b":
                dados = gzip.decompress(dados)      # INMET costuma responder gzip
            return dados
        except Exception as e:
            ult = e
            time.sleep(3 * k)
    raise ult


def carregar_existente(colunas):
    """Le o CSV publicado para preservar toda observacao nao vazia existente."""
    series = {coluna: {} for coluna in colunas}
    primeira = ultima = None
    if not os.path.exists(SAIDA):
        return series, primeira, ultima
    with open(SAIDA, newline="", encoding="utf-8-sig") as arquivo:
        for linha in csv.DictReader(arquivo):
            try:
                t = dt.datetime.strptime(str(linha.get("COD_SEQUENCIAL") or ""), "%Y%m%d%H%M")
            except ValueError:
                continue
            primeira = t if primeira is None or t < primeira else primeira
            ultima = t if ultima is None or t > ultima else ultima
            for coluna in colunas:
                valor = linha.get(coluna)
                if valor in (None, ""):
                    continue
                try:
                    numero = float(str(valor).replace(",", "."))
                except ValueError:
                    continue
                if numero >= 0:
                    series[coluna][t] = numero
    return series, primeira, ultima


def mesclar_observacoes(destino, novas):
    """Acrescenta somente numeros observados; nunca sobrescreve com ausencia."""
    for hora, valor in (novas or {}).items():
        if valor is not None and float(valor) >= 0:
            destino[hora] = float(valor)


def _ultima_hora(serie):
    return max(serie) if serie else None


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
    """Chuva horaria (mm) do INMET (apitempo), em janelas mensais (mais robusto
    que anuais). Converte UTC -> BRT."""
    serie = {}
    ini_m = inicio.replace(day=1)
    while ini_m <= fim:
        prox = (ini_m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        a_ini = max(inicio, ini_m).date()
        a_fim = min(fim, prox - dt.timedelta(days=1)).date()
        url = INMET_URL.format(ini=a_ini.isoformat(), fim=a_fim.isoformat(), cod=cod)
        try:
            bruto = http_get(url, timeout=120, headers={"Accept": "application/json"})
            try:
                dados = json.loads(bruto)
            except Exception:
                amostra = bruto[:160].decode("utf-8", "replace").replace("\n", " ")
                print(f"[INMET {cod}] {ini_m:%Y-%m} resposta nao-JSON ({len(bruto)}b): {amostra}")
                ini_m = prox
                continue
            n0 = len(serie)
            for r in dados:
                data = r.get("DT_MEDICAO"); hr = r.get("HR_MEDICAO")
                ch = r.get("CHUVA")
                if not data or hr is None or ch in (None, ""):
                    continue
                try:
                    hh = int(str(hr)[:2])
                    t_utc = dt.datetime.strptime(data, "%Y-%m-%d") + dt.timedelta(hours=hh)
                    # UTC->BRT (-3h) e -1h de rotulo: CHUVA do INMET e o
                    # acumulado da hora que termina no carimbo.
                    t_inicio_brt = t_utc - dt.timedelta(hours=4)
                    serie[t_inicio_brt] = float(str(ch).replace(",", "."))
                except Exception:
                    continue
            print(f"[INMET {cod}] {ini_m:%Y-%m} +{len(serie)-n0} horas")
        except Exception as e:
            print(f"[INMET {cod}] {ini_m:%Y-%m} erro: {e}")
        ini_m = prox
    return serie


# ---------------------------------------------------------------- CEMADEN ---
def cemaden_chuva_horaria(cod, inicio, fim):
    """Chuva CEMADEN exata: API autenticada profunda + grade publica recente."""
    token = os.environ.get("CEMADEN_TOKEN")
    serie = {}
    if token:
        base = "https://sws.cemaden.gov.br/PED/rest/pcds/dados_pcd"
        ini_m = inicio.replace(day=1)
        while ini_m <= fim:
            prox = (ini_m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            fim_m = min(prox - dt.timedelta(days=1), fim)
            q = urllib.parse.urlencode({"codigo": cod, "inicio": ini_m.strftime("%Y%m%d"),
                                        "fim": fim_m.strftime("%Y%m%d"), "sensor": "chuva"})
            try:
                req = urllib.request.Request(f"{base}?{q}", headers={**UA, "token": token})
                dados = json.loads(urllib.request.urlopen(req, timeout=120).read())
                n0 = len(serie)
                for r in (dados if isinstance(dados, list) else dados.get("dados", [])):
                    t_utc = _parse_hora(r.get("datahora") or r.get("data"))
                    v = r.get("valor") if r.get("valor") is not None else r.get("chuva")
                    if t_utc is None or v in (None, ""):
                        continue
                    h_brt = (t_utc - dt.timedelta(hours=3)).replace(
                        minute=0, second=0, microsecond=0
                    )
                    serie[h_brt] = serie.get(h_brt, 0.0) + float(str(v).replace(",", "."))
                print(f"[CEMADEN {cod}] PED {ini_m:%Y-%m} +{len(serie)-n0} horas")
            except Exception as e:
                print(f"[CEMADEN {cod}] PED {ini_m:%Y-%m} erro: {e}")
            ini_m = prox
    else:
        print(f"[CEMADEN {cod}] sem token; usando grade horaria publica recente")

    try:
        recente = baixar_cemaden_chuva_recente(
            id_estacao=CEMADEN_ID,
            codigo=cod,
            horas=168,
            timeout=30,
            tentativas=2,
        )
        recente = {hora: valor for hora, valor in recente.items() if inicio <= hora <= fim}
        serie.update(recente)
        print(f"[CEMADEN {cod}] publico recente +{len(recente)} horas")
    except Exception as e:
        print(f"[CEMADEN {cod}] publico recente erro: {e}")
    return serie


# --------------------------------------------------------------------- main -
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--inicio",
        default=None,
        help="YYYY-MM-DD; sem valor atualiza somente os ultimos 8 dias e preserva o CSV",
    )
    ap.add_argument("--fim", default=dt.datetime.now(BRT).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    existentes, primeira_existente, ultima_existente = carregar_existente(COLUNAS)
    if args.inicio:
        inicio = dt.datetime.strptime(args.inicio, "%Y-%m-%d")
    elif ultima_existente:
        inicio = min(
            dt.datetime.now(BRT).replace(tzinfo=None) - dt.timedelta(days=8),
            ultima_existente,
        ).replace(minute=0, second=0, microsecond=0)
    else:
        inicio = dt.datetime(2022, 12, 1)
    fim = dt.datetime.strptime(args.fim, "%Y-%m-%d").replace(hour=23)
    print(f"Janela: {inicio:%Y-%m-%d} -> {fim:%Y-%m-%d} (BRT, horaria)")

    series = existentes
    for coluna, cod in ANA_ESTACOES.items():
        mesclar_observacoes(series[coluna], ana_chuva_horaria(cod, inicio, fim))
    mesclar_observacoes(
        series["chuva_inmet_A894"],
        inmet_chuva_horaria(INMET_ESTACAO, inicio, fim),
    )
    mesclar_observacoes(
        series["chuva_cemaden_4320404010A"],
        cemaden_chuva_horaria(CEMADEN_ESTACAO, inicio, fim),
    )

    agora = dt.datetime.now(BRT).replace(tzinfo=None)
    if fim >= agora - dt.timedelta(days=1):
        ultima_cemaden = _ultima_hora(series["chuva_cemaden_4320404010A"])
        atraso_h = None if ultima_cemaden is None else (agora - ultima_cemaden).total_seconds() / 3600
        if atraso_h is None or atraso_h > 8:
            raise SystemExit(
                "QA FALHOU: CEMADEN 432040401A sem observacao nas ultimas 8 horas; "
                "CSV anterior foi preservado e nao sera substituido"
            )
        ultima_a894 = _ultima_hora(series["chuva_inmet_A894"])
        print(
            "[QA recente] CEMADEN ultima=",
            ultima_cemaden.isoformat(timespec="minutes"),
            "A894 ultima=",
            ultima_a894.isoformat(timespec="minutes") if ultima_a894 else "sem_dado (estacao em pane)",
        )

    saida_inicio = min(x for x in (primeira_existente, inicio) if x is not None)
    saida_fim = max(x for x in (ultima_existente, fim) if x is not None)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    temporario = SAIDA + ".tmp"
    with open(temporario, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["COD_SEQUENCIAL", "ANO", "MES", "DIA", "HORA"] + COLUNAS)
        for t in horas(saida_inicio, saida_fim):
            linha = [cod_seq(t), t.year, t.month, t.day, t.hour]
            for c in COLUNAS:
                v = series[c].get(t)
                linha.append("" if v is None else round(v, 2))
            w.writerow(linha)
    os.replace(temporario, SAIDA)

    print("\n=== cobertura (horas com dado) ===")
    total = sum(1 for _ in horas(saida_inicio, saida_fim))
    for c in COLUNAS:
        n = len(series[c])
        print(f"  {c:30s} {n:6d} / {total} horas ({100*n/total:4.1f}%)")
    print(f"-> {SAIDA}")


if __name__ == "__main__":
    main()
