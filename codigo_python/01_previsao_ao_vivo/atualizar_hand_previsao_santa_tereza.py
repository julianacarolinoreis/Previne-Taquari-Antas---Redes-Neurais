#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Copia o payload <script id="hand-data"> de santa_tereza_inundacao.html
(mosaico 2m, drone corrigido de datum + ANADEM — ver gerar_mancha_mosaico.py)
para santa_tereza_previsao_inundacao.html (a página "ao vivo").

santa_tereza_previsao_inundacao.html não tem gerador próprio — foi montada
manualmente em algum momento e ficou parada no ANADEM 30m puro enquanto
santa_tereza_inundacao.html evoluiu (correção de datum, mosaico, contorno
vetorial). Esse script fecha essa defasagem copiando o payload já correto.

O schema das duas páginas é idêntico (cols/rows/S/W/N/E/station/ponte/
fonte/hand_png_b64), então é cópia direta — sem transformação.

Uso: python codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_santa_tereza.py
"""
import os
import re

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONTE = os.path.join(RAIZ, "santa_tereza_inundacao.html")
ALVO = os.path.join(RAIZ, "santa_tereza_previsao_inundacao.html")


def main():
    fonte_html = open(FONTE, encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', fonte_html, re.DOTALL)
    if not m:
        raise SystemExit(f"ERRO: hand-data não encontrado em {FONTE}")
    payload = m.group(1)

    alvo_html = open(ALVO, encoding="utf-8").read()
    alvo_html2, n = re.subn(
        r'<script id="hand-data" type="application/json">.*?</script>',
        f'<script id="hand-data" type="application/json">{payload}</script>',
        alvo_html, count=1, flags=re.DOTALL,
    )
    if n != 1:
        raise SystemExit(f"ERRO: hand-data não encontrado em {ALVO}")
    open(ALVO, "w", encoding="utf-8").write(alvo_html2)
    print(f"copiado hand-data de {os.path.basename(FONTE)} para {os.path.basename(ALVO)} ({len(payload)} chars)")


if __name__ == "__main__":
    main()
