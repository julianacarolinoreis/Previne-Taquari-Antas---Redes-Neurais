#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Sincroniza o HAND de mucum_previsao_inundacao.html com mucum_inundacao.html.

A página de inundação já carrega o mosaico 2 m (drone + ANADEM). A de previsão
ao vivo ficou com um PNG antigo e sem o campo `fonte`. Este script copia o
raster HAND e a fonte do mosaico, preservando o schema da previsão
(`station` / `ponte`), e inclui `bankfull_cm` e `fonte`.

Uso: python codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_mucum.py
"""
import json
import os
import re

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONTE = os.path.join(RAIZ, "mucum_inundacao.html")
ALVO = os.path.join(RAIZ, "mucum_previsao_inundacao.html")


def _extract(html, path):
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not m:
        raise SystemExit(f"ERRO: hand-data não encontrado em {path}")
    return m.group(0), json.loads(m.group(1))


def main():
    fonte_html = open(FONTE, encoding="utf-8").read()
    alvo_html = open(ALVO, encoding="utf-8").read()
    _, src = _extract(fonte_html, FONTE)
    _, dst = _extract(alvo_html, ALVO)

    # schema da previsão: station/ponte; da inundação: estacao_* / bankfull / fonte
    station = dst.get("station") or {
        "lat": -29.1672,
        "lon": -51.8686,
        "code": src.get("estacao_alvo") or "86510000",
    }
    merged = {
        "cols": src["cols"],
        "rows": src["rows"],
        "S": src["S"],
        "W": src["W"],
        "N": src["N"],
        "E": src["E"],
        "station": station,
        "ponte": dst.get("ponte", None),
        "bankfull_cm": src.get("bankfull_cm", 500),
        "fonte": src.get("fonte")
        or "Mosaico 2 m: drone + ANADEM 30 m — ver codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py",
        "hand_png_b64": src["hand_png_b64"],
    }
    payload = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
    alvo2, n = re.subn(
        r'<script id="hand-data" type="application/json">.*?</script>',
        f'<script id="hand-data" type="application/json">{payload}</script>',
        alvo_html,
        count=1,
        flags=re.DOTALL,
    )
    if n != 1:
        raise SystemExit(f"ERRO: hand-data não encontrado em {ALVO}")
    open(ALVO, "w", encoding="utf-8").write(alvo2)
    print(
        f"sincronizado HAND Muçum: inundacao → previsao "
        f"({merged['cols']}x{merged['rows']}, bankfull={merged['bankfull_cm']} cm)"
    )


if __name__ == "__main__":
    main()
