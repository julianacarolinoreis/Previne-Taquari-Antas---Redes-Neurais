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
        "hydro",
        "hydro-accessible",
    ):
        assert required in parser.ids, f"{nome}: falta #{required}"
    assert any(
        href.split("?", 1)[0] == "assets/previsao_panorama.css"
        for href in parser.stylesheets
    ), f"{nome}: CSS do panorama ausente"
    assert any(
        script.split("?", 1)[0] == "assets/previsao_panorama.js"
        for script in parser.scripts
    ), f"{nome}: JS do panorama ausente"
    assert any(
        script.split("?", 1)[0] == "assets/js/fmt_quando.js"
        for script in parser.scripts
    ), f"{nome}: formatador de horário ausente"
    assert any(
        script.split("?", 1)[0] == "assets/js/live_feed.js"
        for script in parser.scripts
    ), f"{nome}: leitor do feed ao vivo ausente"
    assert "PrevineLiveFeed.fetchLive" in texto, f"{nome}: o ao vivo ainda aceita o JSON velho do Pages"
    assert "try{ return await fetchJsonWithTimeout(LIVE_PAGE_URL); }" not in texto, f"{nome}: fetchLiveJson ainda para no primeiro 200 do Pages"
    assert ".q #s-hz{text-transform:none" in texto, f"{nome}: o horário-alvo ainda herda caixa alta do rótulo"
    assert "m[4]}:${m[5]}" not in texto, f"{nome}: fmtWhen ainda imprime HH:MM com dois-pontos"
    assert "live-bar-copy" in texto, f"{nome}: banner ao vivo ainda quebra AO VIVO em nós de texto anônimos"
    assert "PrevineFmtQuando.fmtDuration" in texto, f"{nome}: duração do banner ainda cola hora e minuto"
    assert "PrevineFmtQuando.fmtAge" in texto, f"{nome}: idade ainda usa 13h20 como se fosse relógio"
    assert "${h}h${m}" not in texto, f"{nome}: durMin ainda imprime 13h20"
    assert "h${String(r).padStart" not in texto, f"{nome}: ageText ainda imprime 13h20"
    assert esperado["history"] in texto, f"{nome}: histórico incorreto"
    assert f"const CONTORNOS_URL='{esperado['contour']}';" in texto, f"{nome}: contorno incorreto"
    assert esperado["target"] in texto, f"{nome}: estação-alvo incorreta"
    assert esperado["cota"] in texto, f"{nome}: cota oficial incorreta"
    for proibido in esperado.get("forbidden", ()):
        assert proibido not in texto, f"{nome}: fallback herdado incorreto: {proibido}"
    assert "Panorama Geral" in texto
    assert "Nível do rio nos últimos 7 dias" in texto
    assert "proxy de extravasamento" in texto
    assert 'role="img" aria-label="Hidrograma do evento' in texto, f"{nome}: hidrograma sem nome acessível"
    assert 'aria-describedby="hydro-accessible"' in texto, f"{nome}: hidrograma sem descrição acessível"
    assert "document.getElementById('hydro').addEventListener('keydown'" in texto, f"{nome}: hidrograma sem navegação por teclado"
    if nome == "mucum_previsao_inundacao.html":
        assert "MAE é o erro absoluto médio e não tem sinal" in texto, f"{nome}: definição de MAE/viés ausente"
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
        "forecastMark(p,x,y,style.color)",
        "legend-point",
        "renderWeekCoverage",
        "ResizeObserver",
        "const forecastReferenceMs=Date.now();",
        "candidate.time.getTime()<forecastReferenceMs-ACTIVE_FORECAST_GRACE_MINUTES*60000",
    ):
        assert token in js, f"JS: falta proteção/componente {token}"
    assert "if(crossDay) return fmtWhen(d);" in js, "JS: eixo do panorama ainda usa 00:00"
    assert "function publishedForecasts(items)" in js, "JS: +2 h publicado some do gráfico quando o alvo já passou"
    assert "return fmtClock(d);" in js, "JS: ticks curtos do eixo ainda usam HH:MM"
    assert "PrevineFmtQuando.fmtAge" in js, "JS: idade do panorama ainda usa 13h20"
    assert "h${String(rest).padStart" not in js, "JS: ageText do panorama ainda cola hora e minuto"
    assert "candidate.time.getTime()<anchor.time.getTime()" not in js, "JS: validade do alvo depende da última leitura atrasada"
    assert "let previous=anchor" not in js, "JS: horizontes ainda estão encadeados apesar de terem bases distintas"
    assert "x1:px,y1:py,x2:x,y2:y" not in js, "JS: previsão ainda tem linha colorida entre base e ponto final"
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


def validar_deploy_pages() -> None:
    yml = (RAIZ / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "Previsao ao vivo - Santa Tereza" not in yml, "Pages ainda dispara no robô de 5 min de Santa Tereza"
    assert "Previsao ao vivo - Mucum" not in yml, "Pages ainda dispara no robô de 5 min de Muçum"
    assert "Chuvas horarias (ANA + INMET + CEMADEN)" not in yml, "Pages ainda dispara no robô horário de chuvas"
    assert "cancel-in-progress: true" in yml, "Pages ainda deixa um deploy waiting bloquear o grupo"
    assert "group: github-pages-site" in yml, "Pages ainda usa o grupo concurrency preso em waiting"
    assert "github.ref == 'refs/heads/main'" in yml, "Pages ainda publica fora do main"
    assert "previsao_ao_vivo.json|previsao_ao_vivo_mucum.json" in yml, "Pages ainda copia o JSON do robô para o artefato"
    assert 'cron: "41 */2 * * *"' in yml, "Pages perdeu a cópia de contingência do JSON"
    js = (RAIZ / "assets/js/live_feed.js").read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net/gh/" in js, "live_feed não lê o CDN quando o Pages 404"
    assert "raw.githubusercontent.com" in js, "live_feed não lê o Raw do GitHub"
    assert "kind !== 'github-api'" in js, "live_feed ainda gasta a cota da API em todo poll"
    print("OK Pages: robô de 5 min não enfileira deploy")


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
    validar_deploy_pages()
    for teste in ("test_fmt_quando.js", "test_live_feed.js"):
        proc = subprocess.run(
            ["node", str(RAIZ / "scripts" / teste)],
            cwd=RAIZ,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, f"{teste}: {proc.stdout}{proc.stderr}"
        print((proc.stdout or "").strip() or f"OK {teste}")
    print("VALIDAÇÃO DO PANORAMA: OK")


if __name__ == "__main__":
    main()
