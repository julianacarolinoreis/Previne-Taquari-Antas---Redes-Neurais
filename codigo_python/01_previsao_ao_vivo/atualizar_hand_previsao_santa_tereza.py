#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Propaga o payload <script id="hand-data"> da previsão de pesquisa
para a simulação e, quando existente, para a variante de usuário.

A fonte é o HAND hidráulico de LiDAR calibrado em campo: régua 1,60 m =
HAND 0, exclusivamente para o rio principal. A página operacional recebe
esse payload do gerador de LiDAR; a página de cenários deve usar exatamente
o mesmo raster, geometria e metadados. O sentido inverso é proibido: o
arquivo histórico da página de cenários não pode sobrescrever a calibração
de campo nem o georreferenciamento atual.

O schema das duas páginas é idêntico (cols/rows/S/W/N/E/station/ponte/
fonte/hand_png_b64), então é cópia direta — sem transformação.

Uso: python codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_santa_tereza.py
"""
import os
import re
import sys
import json

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONTE = os.path.join(RAIZ, "santa_tereza_previsao_inundacao.html")
ALVO = os.path.join(RAIZ, "santa_tereza_inundacao.html")
ALVO_USUARIO = os.path.join(RAIZ, "santa_tereza_previsao_inundacao_usuario.html")
sys.path.insert(0, os.path.join(RAIZ, "scripts"))
from santa_tereza_hand_field_contract import validate_raster_payload


def main():
    fonte_html = open(FONTE, encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', fonte_html, re.DOTALL)
    if not m:
        raise SystemExit(f"ERRO: hand-data não encontrado em {FONTE}")
    payload = m.group(1)
    validate_raster_payload(json.loads(payload))

    alvos = [ALVO] + ([ALVO_USUARIO] if os.path.isfile(ALVO_USUARIO) else [])
    preparados = []
    for alvo in alvos:
        alvo_html = open(alvo, encoding="utf-8").read()
        alvo_html2, n = re.subn(
            r'<script id="hand-data" type="application/json">.*?</script>',
            lambda _: f'<script id="hand-data" type="application/json">{payload}</script>',
            alvo_html, count=1, flags=re.DOTALL,
        )
        if n != 1:
            raise SystemExit(f"ERRO: hand-data não encontrado em {alvo}")
        preparados.append((alvo, alvo_html2))
    # Prepare all consumers before the first write; no partial structural sync.
    for alvo, html in preparados:
        open(alvo, "w", encoding="utf-8", newline="\n").write(html)
        print(f"copiado hand-data calibrado de {os.path.basename(FONTE)} para {os.path.basename(alvo)} ({len(payload)} chars)")


if __name__ == "__main__":
    main()
