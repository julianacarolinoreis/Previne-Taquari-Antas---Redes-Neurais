#!/usr/bin/env python3
"""Unify estudo catalog state after HEC twin Muçum v1.2.

Keeps JSON/HTML/index/forçantes/dois_modelos from contradicting each other.
Does not recalibrate hydrology.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"

HEC_STATUS = "hec_twin_mucum_v1_4_eventwise_scored_stz_q_blocked"
NEXT = [
    "Muçum: usar params eventwise (common-search só se testes externos/LOO ok).",
    "STZ: anexar curva-chave oficial 86472600 (HIDROWEB/ANA/SGB) — sem inventar N→Q.",
    "Após curva: converter Nivel→Q e calibrar modelo STZ truncado.",
    "Opcional: densificar chuva e revisar E19 com massa de montante.",
    "Manter Guaporé/Forqueta fora do recorte.",
]
DOIS_DISCIPLINE = (
    "Dois modelos-alvo no CORREDOR Ate Muçum. Nao sao a bacia G040. "
    "Guapore/Forqueta/Baixo ficam de fora dos dois. "
    "HEC twin v1.4: Muçum E19–E31 + 2851072 + externos; STZ Q bloqueado ate curva-chave. "
    "Nao promover common-search Muçum sem testes ok."
)
FORCANTES_DISCIPLINE = (
    "Contrato de ENTRADAS candidato (nivel/chuva). "
    "Trilho paralelo ao HEC twin: forçantes nao substituem rain_stations HEC de evento. "
    "HEC twin Muçum v1.4 ja rodou (inclui 2851072); STZ Q ainda bloqueado."
)


def patch_json(path: Path, **fields) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_ul_after_h2(text: str, h2: str, items: list[str]) -> str:
    steps = "".join(f"<li>{html.escape(x)}</li>" for x in items)
    return re.sub(
        rf"(<h2>{re.escape(h2)}</h2>\s*<ul>)(.*?)(</ul>)",
        rf"\1{steps}\3",
        text,
        count=1,
        flags=re.S,
    )


def main() -> None:
    hec = json.loads((OUT / "hec_twin_stz_mucum_v1_latest.json").read_text(encoding="utf-8"))
    assert hec["status"] == HEC_STATUS

    # dois_modelos
    dois_path = OUT / "dois_modelos_stz_mucum_latest.json"
    patch_json(
        dois_path,
        status=HEC_STATUS,
        discipline_rule=DOIS_DISCIPLINE,
        next_steps=NEXT,
        hec_twin_artifact=hec["artifacts"],
    )
    dois_html = OUT / "dois_modelos_stz_mucum.html"
    t = dois_html.read_text(encoding="utf-8")
    t = replace_ul_after_h2(t, "Proximos passos (ainda disciplina)", NEXT)
    if "HEC twin v1" not in t:
        t = t.replace(
            '<div class="notice bad"><strong>Rotulo honesto:</strong>',
            '<div class="notice ok"><strong>Estado HEC:</strong> Muçum eventwise+common-search no gêmeo; '
            "STZ Q bloqueado até curva-chave. "
            '<a href="hec_twin_stz_mucum_v1.html">hec_twin_stz_mucum_v1.html</a>.</div>\n'
            '    <div class="notice bad"><strong>Rotulo honesto:</strong>',
        )
    dois_html.write_text(t, encoding="utf-8")

    # estrutura
    est_path = OUT / "estrutura_stz_mucum_latest.json"
    est = json.loads(est_path.read_text(encoding="utf-8"))
    est["status"] = "estrutura_com_hec_twin_v1"
    est["next_steps"] = NEXT
    est["hec_twin_artifact"] = hec["artifacts"]
    est_path.write_text(json.dumps(est, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    est_html = OUT / "estrutura_stz_mucum.html"
    et = est_html.read_text(encoding="utf-8")
    et = et.replace(
        "<h1>Dois esqueletos — ainda sem calibração</h1>",
        "<h1>Dois esqueletos — com HEC twin Muçum; STZ Q bloqueado</h1>",
    )
    et = replace_ul_after_h2(et, "Próximos", NEXT)
    if "hec_twin_stz_mucum_v1.html" not in et:
        et = et.replace(
            '<a href="estrutura_stz_mucum_latest.json">JSON</a>',
            '<a href="estrutura_stz_mucum_latest.json">JSON</a> ·\n'
            '      <a href="hec_twin_stz_mucum_v1.html">HEC twin</a>',
        )
    est_html.write_text(et, encoding="utf-8")

    # forcantes
    forc_path = OUT / "forcantes_stz_mucum_latest.json"
    forc = json.loads(forc_path.read_text(encoding="utf-8"))
    forc["discipline_rule"] = FORCANTES_DISCIPLINE
    forc["next_steps"] = [
        "Forçantes continuam o contrato de entradas RNA/nível.",
        "HEC twin usa rain_stations de evento (ANA raw_ana), não substituir por esta lista aspiracional.",
        *NEXT[:2],
    ]
    forc["hec_twin_artifact"] = hec["artifacts"]
    forc["status"] = "forcantes_congeladas_v1_hec_twin_aware"
    forc_path.write_text(json.dumps(forc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    forc_html = OUT / "forcantes_stz_mucum.html"
    if forc_html.exists():
        ft = forc_html.read_text(encoding="utf-8")
        ft = replace_ul_after_h2(ft, "Proximos", forc["next_steps"]) if "Proximos" in ft else ft
        ft = replace_ul_after_h2(ft, "Próximos", forc["next_steps"]) if "Próximos" in ft else ft
        forc_html.write_text(ft, encoding="utf-8")

    # index
    idx = OUT / "index.html"
    text = idx.read_text(encoding="utf-8")
    text = text.replace(
        "Ver <a href=\"estrutura_stz_mucum.html\">estrutura_stz_mucum.html</a>. Ainda sem calibração.",
        "Ver <a href=\"estrutura_stz_mucum.html\">estrutura_stz_mucum.html</a>. "
        "HEC twin Muçum scored; STZ Q bloqueado.",
    )
    text = text.replace(
        "Ver <a href=\"forcantes_stz_mucum.html\">forcantes_stz_mucum.html</a>. Ainda sem HEC.",
        "Ver <a href=\"forcantes_stz_mucum.html\">forcantes_stz_mucum.html</a>. "
        "Contrato de entradas; HEC twin usa telemetria de evento ANA.",
    )
    text = text.replace(
        "Chuva STZ com buracos; A894 vazio no CSV; HEC ainda bloqueado; RNA com máscara possível.",
        "Chuva STZ com buracos; A894 vazio no CSV; HEC twin Muçum já rodou (STZ Q bloqueado); RNA com máscara paralela.",
    )
    text = text.replace(
        '<div class="notice bad"><strong>Parar antes do HEC:</strong> escolher A corredor Mucum, B G040 completa, ou C hibrido.\n'
        '    Fatos e opcoes em <a href="recorte_modelo.html">recorte_modelo.html</a>.</div>',
        '<div class="notice"><strong>Histórico A/B/C:</strong> supersedido pela decisão STZ+Muçum (corredor). '
        'Mantido em <a href="recorte_modelo.html">recorte_modelo.html</a>.</div>',
    )
    steps = "".join(f"<li>{html.escape(x)}</li>" for x in NEXT)
    text = re.sub(
        r"(<h2>Proximos passos de ESTUDO</h2>\s*<ul>)(.*?)(</ul>)",
        rf"\1{steps}\3",
        text,
        flags=re.S,
    )
    idx.write_text(text, encoding="utf-8")

    # hec twin next_steps + honesty note already in JSON; patch HTML common-search title if needed
    hec_html = OUT / "hec_twin_stz_mucum_v1.html"
    ht = hec_html.read_text(encoding="utf-8")
    ht = ht.replace(
        "<h2>Common-search (regra transferível)</h2>",
        "<h2>Common-search (diagnóstico — NÃO promover)</h2>",
    )
    if "NSE comum fraco" not in ht:
        ht = ht.replace(
            '<div class="notice">{html.escape(common.get(\'note\', \'\'))}</div>'.replace(
                "{html.escape(common.get('note', ''))}", ""
            ),
            "",
        )
    # simpler string replace on rendered notice
    ht = ht.replace(
        "Regra comum transferível nos eventos com fit eventwise NSE&gt;=0.",
        "Hipótese de params comuns nos eventos com NSE≥0 — NSE médio comum fraco; NÃO promover.",
    )
    # the HTML may have unescaped >=
    ht = ht.replace(
        "Regra comum transferível nos eventos com fit eventwise NSE>=0. Não há hold-out formal; promoção operacional bloqueada.",
        "Hipótese de params comuns nos eventos com NSE≥0. NSE médio comum fraco; sem hold-out; NÃO promover.",
    )
    hec["next_steps"] = NEXT
    hec["catalog_sync"] = "sync_estudo_hec_catalog_state_v1"
    (OUT / "hec_twin_stz_mucum_v1_latest.json").write_text(
        json.dumps(hec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # refresh hec html next steps ul
    ht = re.sub(
        r"(<h2>Próximos</h2>\s*<ul>)(.*?)(</ul>)",
        r"\1" + "".join(f"<li>{html.escape(x)}</li>" for x in NEXT) + r"\3",
        ht,
        flags=re.S,
    )
    hec_html.write_text(ht, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "hec_status": HEC_STATUS,
                "patched": [
                    "dois_modelos",
                    "estrutura",
                    "forcantes",
                    "index",
                    "hec_twin_html",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
