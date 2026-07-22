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
import os, re, json

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ST = os.path.join(RAIZ, "santa_tereza_previsao_inundacao.html")
MANUAL = os.path.join(RAIZ, "mucum_inundacao.html")
EVENTOS = os.path.join(RAIZ, "assets", "data", "mucum_eventos_analise.json")
DADOS = os.path.join(RAIZ, "assets", "data", "mucum_data.json")
SAIDA = os.path.join(RAIZ, "mucum_previsao_inundacao.html")

# eventos em destaque (maiores picos; ev27 = maio/2024, a catástrofe)
EVENTOS_DESTAQUE = ["27", "24", "22", "28", "31"]
ESTACAO = {"lat": -29.1672, "lon": -51.8686, "code": "86510000"}
COTA_INUND_CM = 1800   # cota de inundação oficial de Muçum (86510000) — SGB/CPRM, boletim SAH Rio Taquari


def hand_payload():
    """Payload ANADEM de Muçum + marcador da estação 86510000."""
    mh = open(MANUAL, encoding="utf-8").read()
    m = re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', mh, re.DOTALL)
    p = json.loads(m.group(1))
    out = {"W": p["W"], "S": p["S"], "E": p["E"], "N": p["N"],
           "rows": p["rows"], "cols": p["cols"],
           "station": ESTACAO, "ponte": None,
           "hand_png_b64": p["hand_png_b64"]}
    return json.dumps(out, ensure_ascii=False)


def eventos_payload():
    ev = json.load(open(EVENTOS, encoding="utf-8"))
    dd = json.load(open(DADOS, encoding="utf-8"))
    pers_por_modelo = {m["modelo"]: m.get("PERS_teste") for m in dd["models"]}
    combo_por_modelo = {m["modelo"]: m.get("combo_id", m["modelo"]) for m in dd["models"]}
    picos = {str(e["evento"]): e["pico_cm"] for e in ev["eventos"]}
    out = {}
    # ordena horizontes 2h,4h,8h,12h
    def hnum(hk): return int(re.match(r"(\d+)h", hk).group(1))
    for evid in EVENTOS_DESTAQUE:
        for hk in sorted(ev["campeoes"].keys(), key=hnum):
            H = hnum(hk)
            modelo = hk.split("_", 1)[1]
            evs = ev["campeoes"][hk]
            if evid not in evs:
                continue
            serie = evs[evid]["serie"]      # [[time, obs, rna], ...] horário
            # reescreve no schema do ST com deslocamento do horizonte
            st_series = []
            for i in range(len(serie) - H):
                t = serie[i][0]
                agora = serie[i][1]              # nível atual em t
                obs = serie[i + H][1]            # observado em t+H
                prev = serie[i + H][2]           # RNA prevê t+H
                st_series.append([t, agora, obs, prev])
            if len(st_series) < 2:
                continue
            key = f"ev{evid}_{H}h"
            out[key] = {
                "label": f"Cheia {evs[evid].get('pico_data','')} · {H}h",
                "evento": int(evid),
                "combo": combo_por_modelo.get(modelo, modelo),
                "horizonte": f"{H}h",
                "pers": round(pers_por_modelo.get(modelo) or 0, 2),
                "n": len(st_series),
                "pico_obs_cm": int(picos.get(evid, max(s[2] for s in st_series))),
                "series": st_series,
            }
    return json.dumps(out, ensure_ascii=False)


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
        ("'<b>Estação '+st.code+'</b><br>Santa Tereza'",
         "'<b>Estação '+st.code+'</b><br>Muçum'"),
        ("const COTA_INUND=1500;", f"const COTA_INUND={COTA_INUND_CM};"),
        ("let handArr=null, curEv=Object.keys(EVENTS)[0];\nlet bankfull=400",
         "let handArr=null, curEv=Object.keys(EVENTS)[0];\nlet bankfull=500"),
        ('<input type="range" id="bankfull" min="100" max="700" step="10" value="400"',
         '<input type="range" id="bankfull" min="100" max="900" step="10" value="500"'),
        ("previsao_ao_vivo.json", "previsao_ao_vivo_mucum.json"),
        ("cota de inundação · 15 m", "cota de inundação · 18 m"),
        ('<b id="s-cota">15,00 m</b>', '<b id="s-cota">18,00 m</b>'),
        ("O nível normal usado na mancha foi estimado pelo MDT ANADEM 30 m em ~405 cm e arredondado para 400 cm. A cota de inundação oficial permanece 15 m (SGB/SACE). O refinamento depende de validação com mancha observada.",
         "Nível normal (zero da mancha) adotado em 500 cm na régua 86510000. Cota de inundação oficial de Muçum: 18,00 m (1800 cm) — SGB/CPRM, boletim SAH Rio Taquari; cota de atenção 500 cm, de alerta 900 cm. O refinamento depende de validação com mancha observada."),
    ]
    for a, b in subs:
        if a not in html:
            print("AVISO: trecho não encontrado p/ substituir:", a[:60])
        html = html.replace(a, b)

    # 4) qualquer "Santa Tereza" remanescente em texto vira Muçum
    html = html.replace("em Santa Tereza", "em Muçum")

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
