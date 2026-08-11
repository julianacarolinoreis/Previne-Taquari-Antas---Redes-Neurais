#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera mucum_inundacao.html como CÓPIA FIEL de santa_tereza_inundacao.html
(cheias anteriores com chips de eventos), trocando apenas os dados de Muçum.

Uso: python codigo_python/01_previsao_ao_vivo/gerar_pagina_inundacao_mucum.py
"""
from __future__ import annotations

import json
import os
import re
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ST = os.path.join(RAIZ, "santa_tereza_inundacao.html")
MANUAL_ATUAL = os.path.join(RAIZ, "mucum_inundacao.html")
SAIDA = os.path.join(RAIZ, "mucum_inundacao.html")
sys.path.insert(0, os.path.dirname(__file__))
from mucum_eventos_payload import COTA_INUND_CM, eventos_payload_json  # noqa: E402

ESTACAO = {"lat": -29.1672, "lon": -51.8686, "code": "86510000"}


def hand_payload() -> str:
    """Mantém o HAND/mosaico já publicado em mucum_inundacao.html."""
    mh = open(MANUAL_ATUAL, encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', mh, re.DOTALL)
    if not m:
        raise SystemExit("hand-data ausente no mucum_inundacao.html atual")
    p = json.loads(m.group(1))
    out = {
        "cols": p["cols"],
        "rows": p["rows"],
        "S": p["S"],
        "W": p["W"],
        "N": p["N"],
        "E": p["E"],
        "station": ESTACAO,
        "ponte": None,
        "bankfull_cm": p.get("bankfull_cm", 500),
        "fonte": p.get("fonte")
        or "Mosaico 2 m: drone + ANADEM — ver codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py",
        "hand_png_b64": p["hand_png_b64"],
    }
    # campos legados úteis ao painel Muçum
    if "estacao_alvo" in p:
        out["estacao_alvo"] = p["estacao_alvo"]
    if "estacao_montante" in p:
        out["estacao_montante"] = p["estacao_montante"]
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def main():
    html = open(ST, encoding="utf-8").read()

    html = re.sub(
        r'(<script id="hand-data" type="application/json">).*?(</script>)',
        lambda m: m.group(1) + hand_payload() + m.group(2),
        html,
        count=1,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'(<script id="event-data" type="application/json">).*?(</script>)',
        lambda m: m.group(1) + eventos_payload_json() + m.group(2),
        html,
        count=1,
        flags=re.DOTALL,
    )

    subs = [
        (
            "PREVINE · Até onde a água pode chegar — Santa Tereza",
            "PREVINE · Cheias anteriores — Muçum",
        ),
        (
            "PREVINE · Cheias anteriores — Santa Tereza",
            "PREVINE · Cheias anteriores — Muçum",
        ),
        ("Santa Tereza · bacia Taquari-Antas", "Muçum · bacia Taquari-Antas"),
        (
            ".bindPopup('<b>Estação '+st.code+'</b><br>Santa Tereza')",
            ".bindPopup('<b>Estação '+st.code+'</b><br>Muçum')",
        ),
        (
            "A estação 86472600 informa o nível atual do rio em Santa Tereza.",
            "A estação 86510000 informa o nível atual do rio em Muçum; a montante 86472600 (Santa Tereza) entra na RNA.",
        ),
        ("const COTA_INUND=1500;", f"const COTA_INUND={COTA_INUND_CM};"),
        (
            "let handArr=null, curEv=Object.keys(EVENTS)[0];\nlet bankfull=400",
            "let handArr=null, curEv=Object.keys(EVENTS)[0];\nlet bankfull=500",
        ),
        (
            '<input type="range" id="bankfull" min="100" max="700" step="10" value="400"',
            '<input type="range" id="bankfull" min="100" max="900" step="10" value="500"',
        ),
        (
            "assets/data/santa_tereza_inundacao/contornos_mancha.json",
            "assets/data/mucum_inundacao/contornos_mancha.json",
        ),
        (
            "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_10m.json",
            "assets/data/mucum_inundacao/mdt/altitude_terreno_10m.json",
        ),
        ("cota de inundação · 15 m", "cota de inundação · 18 m"),
        ("estação 86472600", "estação 86510000"),
        ("estação Santa Tereza/SGB-ANA", "estação Muçum/SGB-ANA"),
        ("Nível do rio informado pela estação 86472600", "Nível do rio informado pela estação 86510000"),
        (
            "Padrão provisório calibrado em <b>4,0 m</b>",
            "Padrão provisório adotado em <b>5,0 m</b>",
        ),
        (
            "Terreno: mosaico 2&nbsp;m (drone + ANADEM). O nível normal (HAND 0) foi estimado em ~405 cm e arredondado para <b>400 cm</b>. A cota de inundação oficial permanece <b>15 m</b> (SGB/SACE). Fora do footprint do drone a borda segue a resolução do ANADEM.",
            "Terreno: mosaico 2&nbsp;m (drone + ANADEM). O nível normal (HAND 0) adotado é <b>500 cm</b> na régua 86510000. A cota de inundação oficial é <b>18 m</b> (SGB/CPRM). Fora do footprint do drone a borda segue a resolução do ANADEM.",
        ),
        (
            "O nível normal usado na mancha foi estimado pelo MDT ANADEM 30 m em ~405 cm e arredondado para 400 cm. A cota de inundação oficial permanece 15 m (SGB/SACE). O refinamento depende de validação com mancha observada.",
            "Nível normal (HAND 0) adotado em 500 cm na régua 86510000. A cota de inundação oficial é 18 m (SGB/CPRM). O refinamento depende de validação com manchas observadas.",
        ),
        ("em Santa Tereza", "em Muçum"),
        ("de Santa Tereza", "de Muçum"),
        ("para Santa Tereza", "para Muçum"),
    ]
    for a, b in subs:
        if a not in html and a != b:
            print("AVISO: trecho não encontrado:", a[:70])
        html = html.replace(a, b)

    open(SAIDA, "w", encoding="utf-8").write(html)
    ev = json.loads(
        re.search(
            r'<script id="event-data" type="application/json">(.*?)</script>', html, re.DOTALL
        ).group(1)
    )
    ilustra = sum(1 for v in ev.values() if v.get("ilustra") and not v.get("estatico"))
    est = sum(1 for v in ev.values() if v.get("estatico"))
    testes = sum(1 for v in ev.values() if not v.get("ilustra") and not v.get("estatico"))
    print(
        f"escrito {SAIDA} | eventos={len(ev)} "
        f"(testes={testes}, cheias={ilustra}, referencia={est})"
    )


if __name__ == "__main__":
    main()
