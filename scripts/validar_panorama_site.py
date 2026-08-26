#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validação estrutural das páginas de previsão e da camada extravasada."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
PROTEGIDOS = {
    "previsao_ao_vivo.json",
    "historico_previsoes_ao_vivo.json",
    "previsao_ao_vivo_mucum.json",
    "historico_previsoes_ao_vivo_mucum.json",
}
CASOS = {
    "santa_tereza_previsao_inundacao.html": {
        "history": "historico_previsoes_ao_vivo.json",
        "contour": "assets/data/santa_tereza_inundacao/contornos_extravasamento.json",
        "target": "const target=meta.code==='86472600';",
        "cota": "const COTA_INUND=1500;",
    },
    "mucum_previsao_inundacao.html": {
        "history": "historico_previsoes_ao_vivo_mucum.json",
        "contour": "assets/data/mucum_inundacao/contornos_extravasamento.json",
        "target": "const target=meta.code==='86510000';",
        "cota": "const COTA_INUND=1800;",
        "forbidden": (
            "Nível do rio informado pela estação 86472600",
            "Estação de Santa Tereza sem dado recente",
            "a previsão de 2h/4h volta assim que a telemetria retornar; o robô é agendado a cada ~5 min.",
            "bankfull_cm?liveData.bankfull_cm:400",
            "bankfull_cm||(liveData&&liveData.bankfull_cm)||400",
            "bankfull_cm||400",
        ),
    },
}


class Inspector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.stylesheets.append(values["href"])


def validar_html(nome: str, esperado: dict[str, str]) -> None:
    texto = (RAIZ / nome).read_text(encoding="utf-8")
    parser = Inspector()
    parser.feed(texto)
    duplicados = [item for item, count in Counter(parser.ids).items() if count > 1]
    assert not duplicados, f"{nome}: IDs duplicados: {duplicados}"
    for required in (
        "mode-s",
        "mode-t",
        "mode-p",
        "river-overview",
        "river-level-chart",
        "river-week-chart",
        "overview-week-status",
        "overview-legend",
        "overview-metrics",
    ):
        assert required in parser.ids, f"{nome}: falta #{required}"
    assert "assets/previsao_panorama.css" in parser.stylesheets, f"{nome}: CSS do panorama ausente"
    assert any(
        script.split("?", 1)[0] == "assets/previsao_panorama.js"
        for script in parser.scripts
    ), f"{nome}: JS do panorama ausente"
    assert esperado["history"] in texto, f"{nome}: histórico incorreto"
    assert f"const CONTORNOS_URL='{esperado['contour']}';" in texto, f"{nome}: contorno incorreto"
    assert esperado["target"] in texto, f"{nome}: estação-alvo incorreta"
    assert esperado["cota"] in texto, f"{nome}: cota oficial incorreta"
    for proibido in esperado.get("forbidden", ()):
        assert proibido not in texto, f"{nome}: fallback herdado incorreto: {proibido}"
    assert "Panorama Geral" in texto
    assert "Nível do rio nos últimos 7 dias" in texto
    assert "proxy de extravasamento" in texto
    assert "contornos_mancha.json';" not in texto, f"{nome}: ainda usa a mancha que inclui o leito"
    assert len(re.findall(r'id="play"', texto)) == 1, f"{nome}: controle play duplicado"
    assert len(re.findall(r'id="time"', texto)) == 1, f"{nome}: linha do tempo duplicada"
    print(f"OK HTML {nome}: {len(parser.ids)} IDs únicos")


def validar_componente_panorama() -> None:
    js = (RAIZ / "assets/previsao_panorama.js").read_text(encoding="utf-8")
    css = (RAIZ / "assets/previsao_panorama.css").read_text(encoding="utf-8")
    for token in (
        "--panorama-forecast-2",
        "--panorama-forecast-4",
        "--panorama-forecast-8",
        "--panorama-forecast-12",
    ):
        assert token in css, f"CSS: falta cor de horizonte {token}"
    for token in (
        "river-week-chart",
        "windowHours:168",
        "maxGapMs=90*60*1000",
        "placePointLabel",
        "baseTime",
        "Base da previsão",
        "renderWeekCoverage",
        "ResizeObserver",
    ):
        assert token in js, f"JS: falta proteção/componente {token}"
    assert "let previous=anchor" not in js, "JS: horizontes ainda estão encadeados apesar de terem bases distintas"
    assert "Nível do rio observado nas últimas 24 horas e previsões ativas da rede neural." not in js, "JS: tooltip global antigo ainda cobre o gráfico"
    print("OK componente: cores por horizonte, rótulos sem colisão e janela semanal")


def validar_geojson(relativo: str) -> None:
    caminho = RAIZ / relativo
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    features = dados.get("features") or []
    niveis = [round(float(f["properties"]["nivel_m"]), 1) for f in features]
    esperado = 250 if "/mucum_inundacao/" in relativo.replace("\\", "/") else 150
    nivel_final = esperado / 10
    assert len(features) == esperado, f"{relativo}: esperados {esperado} níveis, vieram {len(features)}"
    assert niveis[0] == 0.1 and niveis[-1] == nivel_final and 0.0 not in niveis
    assert all(float(f["properties"]["area_ha"]) >= 0 for f in features)
    assert all(f["properties"].get("interpretacao") for f in features)
    assert "proxy de extravasamento" in dados.get("metadata", {}).get("interpretacao", "")
    print(f"OK GEOJSON {relativo}: {esperado} níveis, HAND 0 excluído")


def validar_arquivos_protegidos() -> None:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=RAIZ,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    alterados = {linha[3:].replace("\\", "/") for linha in proc.stdout.splitlines() if len(linha) > 3}
    conflito = sorted(PROTEGIDOS & alterados)
    assert not conflito, f"arquivos do robô foram alterados: {conflito}"
    print("OK robô: nenhum dos quatro JSONs dinâmicos foi alterado")


def main() -> None:
    for nome, esperado in CASOS.items():
        validar_html(nome, esperado)
    validar_componente_panorama()
    validar_geojson("assets/data/santa_tereza_inundacao/contornos_extravasamento.json")
    validar_geojson("assets/data/mucum_inundacao/contornos_extravasamento.json")
    validar_arquivos_protegidos()
    print("VALIDAÇÃO DO PANORAMA: OK")


if __name__ == "__main__":
    main()
