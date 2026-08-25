#!/usr/bin/env python3
"""Valida a cobertura temporal e as proteções dos gráficos de eventos de Muçum."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
FORMATO_DATA = "%Y-%m-%d %H:%M"
MODELO_REFERENCIA = "020_alt_MUC_H04_V30_LJJ_CA_CHUVA_AUDITADO_SEM32_R05_T33_V18-20-21"


def carregar_modelos_publicados(html: str) -> set[str]:
    match = re.search(
        r'<script id="data-mucum" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    assert match, "index.html: payload #data-mucum não encontrado"
    payload = json.loads(match.group(1))
    return {str(modelo["modelo"]).upper() for modelo in payload.get("models", [])}


def validar_motor_do_grafico(html: str) -> None:
    obrigatorios = (
        "function parseAuditTime(value)",
        "function auditTimeline(rows)",
        "function eventCoverageText(rows)",
        "times[i]-times[i-1]>AUDIT_HOUR_MS*1.5",
        "lacunas não conectadas",
    )
    ausentes = [trecho for trecho in obrigatorios if trecho not in html]
    assert not ausentes, f"index.html: proteções temporais ausentes: {ausentes}"
    assert "ev.n+' horas'" not in html, "index.html: quantidade de pontos ainda rotulada como horas"


def main() -> None:
    html = (RAIZ / "index.html").read_text(encoding="utf-8")
    validar_motor_do_grafico(html)
    publicados = carregar_modelos_publicados(html)

    base = json.loads(
        (RAIZ / "assets" / "data" / "mucum_auditaveis_series.json").read_text(encoding="utf-8")
    )
    auditaveis = {str(modelo.get("name", "")).upper(): modelo for modelo in base.get("models", [])}
    faltantes = sorted(publicados - auditaveis.keys())
    assert not faltantes, f"modelos publicados sem série auditável: {faltantes}"

    eventos = 0
    eventos_com_lacuna = 0
    horas_sem_ponto = 0
    referencia = None
    for nome in sorted(publicados):
        modelo = auditaveis[nome]
        for chave, linhas in (modelo.get("series") or {}).items():
            assert linhas, f"{nome} / {chave}: evento sem linhas"
            datas = [datetime.strptime(str(linha[0]), FORMATO_DATA) for linha in linhas]
            assert datas == sorted(datas), f"{nome} / {chave}: timestamps fora de ordem"
            assert len(datas) == len(set(datas)), f"{nome} / {chave}: timestamps duplicados"
            duracao_h = (datas[-1] - datas[0]).total_seconds() / 3600
            assert duracao_h.is_integer(), f"{nome} / {chave}: duração não alinhada à hora"
            horas = int(duracao_h) + 1
            lacunas = max(0, horas - len(datas))
            eventos += 1
            if lacunas:
                eventos_com_lacuna += 1
                horas_sem_ponto += lacunas
            if nome == MODELO_REFERENCIA.upper() and chave == "19|Treino":
                referencia = (len(datas), horas, lacunas)

    assert referencia == (44, 53, 9), f"evento de referência divergente: {referencia}"
    print(
        "VALIDAÇÃO GRÁFICOS MUÇUM: OK | "
        f"modelos={len(publicados)} eventos={eventos} "
        f"eventos_com_lacuna={eventos_com_lacuna} horas_sem_ponto={horas_sem_ponto} "
        "referencia_evento19=44_pontos_em_53_horas_9_lacunas"
    )


if __name__ == "__main__":
    main()
