#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera mucum_previsao_inundacao.html como CÓPIA FIEL de
santa_tereza_previsao_inundacao.html, trocando apenas os dados:
  - relevo (HAND) -> ANADEM de Muçum (recortado de mucum_inundacao.html)
  - eventos (cheias anteriores) -> campeões por horizonte de Muçum,
    reescritos no MESMO schema do ST: series [time, agora, obs, previsto]
    com o deslocamento do horizonte (agora=obs(t); obs=obs(t+H); prev=rna(t+H))
  - fonte do ao vivo -> previsao_ao_vivo_mucum.json
  - rótulos/estação/nível normal -> Muçum (86510000, montante 86472600, 500 cm)
A página e o JS ficam idênticos ao Santa Tereza — mesma aparência e interação.
"""
import os, re, json, sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ST = os.path.join(RAIZ, "santa_tereza_previsao_inundacao.html")
MANUAL = os.path.join(RAIZ, "mucum_inundacao.html")
SAIDA = os.path.join(RAIZ, "mucum_previsao_inundacao.html")
sys.path.insert(0, os.path.dirname(__file__))
from mucum_eventos_payload import COTA_INUND_CM, eventos_payload_json  # noqa: E402

ESTACAO = {"lat": -29.1672, "lon": -51.8686, "code": "86510000"}


def hand_payload():
    """HAND/mosaico de Muçum + schema da previsão (station/ponte/fonte)."""
    mh = open(MANUAL, encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', mh, re.DOTALL)
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
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def eventos_payload():
    return eventos_payload_json()


def main():
    html = open(ST, encoding="utf-8").read()

    # 1) troca o bloco de relevo (hand-data)
    html = re.sub(r'(<script id="hand-data" type="application/json">).*?(</script>)',
                  lambda m: m.group(1) + hand_payload() + m.group(2), html, count=1, flags=re.DOTALL)
    # 2) troca o bloco de eventos (event-data)
    html = re.sub(r'(<script id="event-data" type="application/json">).*?(</script>)',
                  lambda m: m.group(1) + eventos_payload() + m.group(2), html, count=1, flags=re.DOTALL)

    # 3) rótulos e config (substituições textuais)
    subs = [
        ("PREVINE · Até onde a água pode chegar — Santa Tereza",
         "PREVINE · Previsão de inundação ao vivo — Muçum"),
        ("Santa Tereza · bacia Taquari-Antas", "Muçum · bacia Taquari-Antas"),
        ("A estação 86472600 informa o nível atual do rio em Santa Tereza.",
         "A estação 86510000 informa o nível atual do rio em Muçum; a montante 86472600 (Santa Tereza) entra na RNA com ~16h de trânsito."),
        ("  {code:'86472600',name:'Santa Tereza',lat:-29.1781,lon:-51.7322,role:'Estação alvo'},\n",
         "  {code:'86510000',name:'Muçum',lat:-29.1672,lon:-51.8686,role:'Estação alvo'},\n"
         "  {code:'86472600',name:'Santa Tereza',lat:-29.1781,lon:-51.7322,role:'Montante'},\n"),
        ("const target=meta.code==='86472600';",
         "const target=meta.code==='86510000';"),
        ("const COTA_INUND=1500;", f"const COTA_INUND={COTA_INUND_CM};"),
        ("let handArr=null, curEv=Object.keys(EVENTS)[0];\nlet bankfull=400",
         "let handArr=null, curEv=Object.keys(EVENTS)[0];\nlet bankfull=500"),
        ('<input type="range" id="bankfull" min="100" max="700" step="10" value="400"',
         '<input type="range" id="bankfull" min="100" max="900" step="10" value="500"'),
        ("previsao_ao_vivo.json", "previsao_ao_vivo_mucum.json"),
        ("historico_previsoes_ao_vivo.json", "historico_previsoes_ao_vivo_mucum.json"),
        ("assets/data/santa_tereza_inundacao/contornos_extravasamento.json",
         "assets/data/mucum_inundacao/contornos_extravasamento.json"),
        ("assets/data/santa_tereza_inundacao/mdt/altitude_terreno_10m.json",
         "assets/data/mucum_inundacao/mdt/altitude_terreno_10m.json"),
        ("cota de inundação · 15 m", "cota de inundação · 18 m"),
        ('<b id="s-cota">15,00 m</b>', '<b id="s-cota">18,00 m</b>'),
        ("O nível normal usado na mancha foi estimado pelo MDT ANADEM 30 m em ~405 cm e arredondado para 400 cm. O contorno HAND 0 é removido da camada colorida para não representar o leito normal como inundação. A cota de inundação oficial permanece 15 m (SGB/SACE). O refinamento depende de máscara observada do leito e validação com manchas de cheias.",
         "Nível normal (zero operacional da mancha) adotado provisoriamente em 500 cm na régua 86510000. O contorno HAND 0 é removido da camada colorida para não representar o leito normal como inundação. A cota de inundação oficial de Muçum é 18,00 m (1800 cm) — SGB/CPRM, boletim SAH Rio Taquari; 500 cm é cota de atenção, não confirmação de inundação. O refinamento depende de máscara observada do leito e validação com manchas de cheias."),
        ("estação Santa Tereza/SGB-ANA", "estação Muçum/SGB-ANA"),
        ("Nível do rio informado pela estação 86472600",
         "Nível do rio informado pela estação 86510000"),
        ("Padrão provisório calibrado em <b>4,0 m</b>",
         "Padrão provisório adotado em <b>5,0 m</b>"),
        ("Estação de Santa Tereza sem dado recente da ANA neste momento",
         "Estação de Muçum sem dado recente da ANA neste momento"),
        ("a previsão de 2h/4h/cascata volta assim que a telemetria retornar; o robô tenta a cada ~15 min.",
         "a previsão de 2h/4h volta assim que a telemetria retornar; o robô tenta a cada ~5 min."),
        ("bankfull_cm?liveData.bankfull_cm:400",
         "bankfull_cm?liveData.bankfull_cm:500"),
        ("bankfull_cm||(liveData&&liveData.bankfull_cm)||400",
         "bankfull_cm||(liveData&&liveData.bankfull_cm)||500"),
        ("bankfull_cm||400", "bankfull_cm||500"),
    ]
    for a, b in subs:
        if a not in html:
            print("AVISO: trecho não encontrado p/ substituir:", a[:60])
        html = html.replace(a, b)

    # 4) qualquer "Santa Tereza" remanescente em texto vira Muçum
    html = html.replace("em Santa Tereza", "em Muçum")

    # fallback de evento ao vivo: ST usa mai24_2h; Muçum usa a cheia recorde tipada
    html = html.replace("liveFromEvent('mai24_2h','ALT')", "liveFromEvent('ev27_2h','ALT')")
    html = html.replace('liveFromEvent("mai24_2h","ALT")', 'liveFromEvent("ev27_2h","ALT")')
    html = html.replace("mai24_2h", "ev27_2h")

    html = html.replace(
        "🔴 Ver previsão AO VIVO (teste interno · 2h, 4h e cascata)",
        "🔴 Ver previsão AO VIVO (teste interno · 2h e 4h)",
    )
    html = html.replace(
        "🔴 Ver previsão AO VIVO (teste interno · 2h, 4h, cascata, 8h e 12h)",
        "🔴 Ver previsão AO VIVO (teste interno · 2h e 4h)",
    )
    html = html.replace(
        "🔴 Ver previsão AO VIVO (teste interno · 2h, 4h, cascata e 8h)",
        "🔴 Ver previsão AO VIVO (teste interno · 2h e 4h)",
    )
    html = html.replace('      <button data-live-hz="4h_cascata">4h cascata</button>\n', "")
    html = html.replace('      <button data-live-hz="8h">8h</button>\n', "")
    html = html.replace('      <button data-live-hz="12h">12h</button>\n', "")
    html = html.replace(
        '      <button data-live-hz="4h_cascata">4h cascata</button>\n'
        '      <button data-live-hz="8h">8h</button>\n'
        '      <button data-live-hz="12h">12h</button>\n',
        "",
    )

    open(SAIDA, "w", encoding="utf-8").write(html)
    ev = json.loads(re.search(r'<script id="event-data" type="application/json">(.*?)</script>', html, re.DOTALL).group(1))
    print(f"escrito {SAIDA} | eventos: {len(ev)} ({', '.join(list(ev)[:8])})")


if __name__ == "__main__":
    main()
