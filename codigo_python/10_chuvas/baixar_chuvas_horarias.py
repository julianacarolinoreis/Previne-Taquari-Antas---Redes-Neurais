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
O sidecar .provenance.json vincula cada captura ao hash do CSV. Seus horarios
sao os inicios das consultas UTC, nao horarios individuais dos sensores.
Uma captura apos o fim do intervalo comprova reconsulta, nao a cobertura de
todas as leituras sub-horarias. A retencao de oito dias e pelas etiquetas BRT,
nao pelo mtime dos arquivos; falha total nao regrava nem renova as capturas.

Uso:
  python codigo_python/10_chuvas/baixar_chuvas_horarias.py [--inicio 2022-12-01] [--fim 2026-08-04]
"""
import os
import sys
import csv
import time
import json
import gzip
import hashlib
import math
import tempfile
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
    CEMADEN_URL,
    INMET_ESTACAO,
    INMET_URL,
    parse_cemaden_chuva,
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


def _agora_utc():
    return dt.datetime.now(dt.timezone.utc)


def _captura_utc():
    return _agora_utc().astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _numero_observado(valor):
    """Zero retornado e valido; ausencias, negativos e nao finitos nao sao."""
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) and numero >= 0 else None


def _validar_captura(valor):
    if not isinstance(valor, str):
        return None
    try:
        captura = dt.datetime.fromisoformat(valor.replace("Z", "+00:00"))
        if captura.tzinfo is None or captura.utcoffset() != dt.timedelta(0):
            return None
        return captura.isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def sha256_arquivo(caminho):
    digest = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def carregar_proveniencia():
    """Metadata ausente/invalida/descasada nunca confirma o CSV legado."""
    try:
        with open(SAIDA + ".provenance.json", encoding="utf-8") as arquivo:
            metadata = json.load(arquivo)
        if (
            not isinstance(metadata, dict)
            or type(metadata.get("schema_version")) is not int
            or metadata.get("schema_version") != 1
            or metadata.get("csv_sha256") != sha256_arquivo(SAIDA)
            or not isinstance(metadata.get("cells"), dict)
        ):
            return {}
        cells = {}
        for coluna, horas_coluna in metadata["cells"].items():
            if not isinstance(horas_coluna, dict):
                return {}
            if coluna not in COLUNAS:
                continue
            for codigo, captura in horas_coluna.items():
                try:
                    hora = dt.datetime.strptime(codigo, "%Y%m%d%H%M")
                except (TypeError, ValueError):
                    continue
                captura = _validar_captura(captura)
                if codigo != cod_seq(hora) or hora.minute or captura is None:
                    continue
                cells.setdefault(coluna, {})[codigo] = captura
        return cells
    except (OSError, ValueError, TypeError):
        return {}


def podar_proveniencia(cells, series, agora_utc):
    """Conserva capturas antigas (inclusive locks) das etiquetas dos 8 dias.

    A retencao e por intervalo BRT, nao por idade da captura. Nao fabrica uma
    captura nova para uma celula preservada sem resposta da fonte.
    """
    ultima = agora_utc.astimezone(BRT).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    primeira = ultima - dt.timedelta(days=8)
    resultado = {}
    for coluna, capturas in cells.items():
        for codigo, captura in capturas.items():
            hora = dt.datetime.strptime(codigo, "%Y%m%d%H%M")
            if primeira <= hora <= ultima and hora in series.get(coluna, {}):
                resultado.setdefault(coluna, {})[codigo] = captura
    return resultado


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


def http_get(url, timeout=90, tentativas=3, headers=None, captura=None):
    ult = None
    for k in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            if captura is not None:
                # Cada tentativa tem seu proprio inicio, antes de qualquer I/O.
                captura["captured_at_utc"] = _captura_utc()
            resp = urllib.request.urlopen(req, timeout=timeout)
            try:
                dados = resp.read()
                comprimido = resp.headers.get("Content-Encoding", "").lower() == "gzip"
            finally:
                resp.close()
            if comprimido or dados[:2] == b"\x1f\x8b":
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
                numero = _numero_observado(valor)
                if numero is not None:
                    series[coluna][t] = numero
    return series, primeira, ultima


def mesclar_observacoes(destino, novas, proveniencia=None, capturas=None):
    """Acrescenta somente numeros observados; nunca sobrescreve com ausencia."""
    aceitas = 0
    for hora, valor in (novas or {}).items():
        numero = _numero_observado(valor)
        if numero is not None:
            destino[hora] = numero
            aceitas += 1
            if proveniencia is not None:
                captura = _validar_captura((capturas or {}).get(hora))
                if captura is None:
                    proveniencia.pop(cod_seq(hora), None)
                else:
                    proveniencia[cod_seq(hora)] = captura
    return aceitas


def _ultima_hora(serie):
    return max(serie) if serie else None


# -------------------------------------------------------------------- ANA ---
def ana_chuva_horaria(cod, inicio, fim, *, capturas=None):
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
            consulta = {}
            xml = http_get(url, timeout=120, captura=consulta)
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
                    v = _numero_observado(ch)
                    if v is None:
                        continue
                    h = t.replace(minute=0, second=0, microsecond=0)
                    total = _numero_observado(serie.get(h, 0.0) + v)
                    if total is not None:
                        serie[h] = total
                        if capturas is not None:
                            capturas[h] = consulta["captured_at_utc"]
            print(f"[ANA {cod}] {ini_m:%Y-%m} +{len(serie)-n0} horas")
        except Exception as e:
            print(f"[ANA {cod}] {ini_m:%Y-%m} erro: {e}")
        ini_m = prox
    return serie


# ------------------------------------------------------------------ INMET ---
def inmet_chuva_horaria(cod, inicio, fim, *, capturas=None):
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
            consulta = {}
            bruto = http_get(url, timeout=120, headers={"Accept": "application/json"}, captura=consulta)
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
                ch = _numero_observado(r.get("CHUVA"))
                if not data or hr is None or ch is None:
                    continue
                try:
                    hh = int(str(hr)[:2])
                    t_utc = dt.datetime.strptime(data, "%Y-%m-%d") + dt.timedelta(hours=hh)
                    # UTC->BRT (-3h) e -1h de rotulo: CHUVA do INMET e o
                    # acumulado da hora que termina no carimbo.
                    t_inicio_brt = t_utc - dt.timedelta(hours=4)
                    serie[t_inicio_brt] = ch
                    if capturas is not None:
                        capturas[t_inicio_brt] = consulta["captured_at_utc"]
                except Exception:
                    continue
            print(f"[INMET {cod}] {ini_m:%Y-%m} +{len(serie)-n0} horas")
        except Exception as e:
            print(f"[INMET {cod}] {ini_m:%Y-%m} erro: {e}")
        ini_m = prox
    return serie


# ---------------------------------------------------------------- CEMADEN ---
def cemaden_chuva_horaria(cod, inicio, fim, *, capturas=None):
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
                consulta = {}
                dados = json.loads(http_get(f"{base}?{q}", timeout=120,
                                            headers={"token": token}, captura=consulta))
                n0 = len(serie)
                for r in (dados if isinstance(dados, list) else dados.get("dados", [])):
                    t_utc = _parse_hora(r.get("datahora") or r.get("data"))
                    v = _numero_observado(r.get("valor") if r.get("valor") is not None else r.get("chuva"))
                    if t_utc is None or v is None:
                        continue
                    h_brt = (t_utc - dt.timedelta(hours=3)).replace(
                        minute=0, second=0, microsecond=0
                    )
                    total = _numero_observado(serie.get(h_brt, 0.0) + v)
                    if total is not None:
                        serie[h_brt] = total
                        if capturas is not None:
                            capturas[h_brt] = consulta["captured_at_utc"]
                print(f"[CEMADEN {cod}] PED {ini_m:%Y-%m} +{len(serie)-n0} horas")
            except Exception as e:
                print(f"[CEMADEN {cod}] PED {ini_m:%Y-%m} erro: {e}")
            ini_m = prox
    else:
        print(f"[CEMADEN {cod}] sem token; usando grade horaria publica recente")

    try:
        consulta = {}
        bruto = http_get(
            CEMADEN_URL.format(id_estacao=CEMADEN_ID, horas_menos_um=167),
            timeout=30, tentativas=2, headers={"Accept": "application/json"}, captura=consulta,
        )
        recente = parse_cemaden_chuva(json.loads(bruto.decode("utf-8-sig")), codigo_esperado=cod)
        recente = {hora: valor for hora, valor in recente.items() if inicio <= hora <= fim}
        mesclar_observacoes(serie, recente)
        if capturas is not None:
            for hora, valor in recente.items():
                if _numero_observado(valor) is not None:
                    capturas[hora] = consulta["captured_at_utc"]
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
    ap.add_argument("--fim", default=_agora_utc().astimezone(BRT).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    existentes, primeira_existente, ultima_existente = carregar_existente(COLUNAS)
    proveniencia = carregar_proveniencia()
    if args.inicio:
        inicio = dt.datetime.strptime(args.inicio, "%Y-%m-%d")
    elif ultima_existente:
        inicio = min(
            _agora_utc().astimezone(BRT).replace(tzinfo=None) - dt.timedelta(days=8),
            ultima_existente,
        ).replace(minute=0, second=0, microsecond=0)
    else:
        inicio = dt.datetime(2022, 12, 1)
    fim = dt.datetime.strptime(args.fim, "%Y-%m-%d").replace(hour=23)
    print(f"Janela: {inicio:%Y-%m-%d} -> {fim:%Y-%m-%d} (BRT, horaria)")

    series = existentes
    aceitas = 0
    for coluna, cod in ANA_ESTACOES.items():
        capturas = {}
        novas = ana_chuva_horaria(cod, inicio, fim, capturas=capturas)
        aceitas += mesclar_observacoes(series[coluna], novas,
                                      proveniencia.setdefault(coluna, {}), capturas)
    for coluna, cod, coletor in (
        ("chuva_inmet_A894", INMET_ESTACAO, inmet_chuva_horaria),
        ("chuva_cemaden_4320404010A", CEMADEN_ESTACAO, cemaden_chuva_horaria),
    ):
        capturas = {}
        novas = coletor(cod, inicio, fim, capturas=capturas)
        aceitas += mesclar_observacoes(series[coluna], novas,
                                      proveniencia.setdefault(coluna, {}), capturas)

    if not aceitas:
        print("Nenhuma observacao valida retornada; CSV e proveniencia anteriores preservados")
        return

    agora_utc = _agora_utc()
    agora = agora_utc.astimezone(BRT).replace(tzinfo=None)
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
    cells = podar_proveniencia(proveniencia, series, agora_utc)
    gravar_csv_e_proveniencia(series, saida_inicio, saida_fim, cells)

    print("\n=== cobertura (horas com dado) ===")
    total = sum(1 for _ in horas(saida_inicio, saida_fim))
    for c in COLUNAS:
        n = len(series[c])
        print(f"  {c:30s} {n:6d} / {total} horas ({100*n/total:4.1f}%)")
    print(f"-> {SAIDA}")


def gravar_csv_e_proveniencia(series, inicio, fim, cells):
    """Prepara ambos antes de substituir; consumidor deve verificar o hash.

    Dois os.replace nao sao uma transacao. Interrupcao entre eles deixa hash
    descasado (fail-closed no consumidor), nunca autoriza a metadata antiga.
    """
    pasta = os.path.dirname(os.path.abspath(SAIDA))
    temporarios = []
    cells_gravadas = {}
    try:
        with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                         dir=pasta, prefix="rain-", suffix=".csv.tmp",
                                         delete=False) as arquivo:
            temporarios.append(arquivo.name)
            writer = csv.writer(arquivo)
            writer.writerow(["COD_SEQUENCIAL", "ANO", "MES", "DIA", "HORA"] + COLUNAS)
            for hora in horas(inicio, fim):
                linha = [cod_seq(hora), hora.year, hora.month, hora.day, hora.hour]
                for coluna in COLUNAS:
                    numero = _numero_observado(series[coluna].get(hora))
                    linha.append("" if numero is None else round(numero, 2))
                    captura = cells.get(coluna, {}).get(cod_seq(hora))
                    if numero is not None and captura is not None:
                        cells_gravadas.setdefault(coluna, {})[cod_seq(hora)] = captura
                writer.writerow(linha)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        metadata = {"schema_version": 1, "csv_sha256": sha256_arquivo(temporarios[0]), "cells": cells_gravadas}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=pasta,
                                         prefix="rain-", suffix=".json.tmp", delete=False) as arquivo:
            temporarios.append(arquivo.name)
            json.dump(metadata, arquivo, ensure_ascii=False, sort_keys=True, allow_nan=False)
            arquivo.write("\n")
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporarios[0], SAIDA)
        os.replace(temporarios[1], SAIDA + ".provenance.json")
    finally:
        for caminho in temporarios:
            if os.path.exists(caminho):
                os.unlink(caminho)


if __name__ == "__main__":
    main()
