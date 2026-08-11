#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monta o event-data de Muçum no mesmo schema/grupos de Santa Tereza."""
from __future__ import annotations

import json
import os
import re

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVENTOS = os.path.join(RAIZ, "assets", "data", "mucum_eventos_analise.json")
DADOS = os.path.join(RAIZ, "assets", "data", "mucum_data.json")

# Destaques: grandes cheias + holdouts de validação/teste
EVENTOS_DESTAQUE = ["27", "24", "22", "28", "31"]
COTA_INUND_CM = 1800


def _hnum(hk: str) -> int:
    return int(re.match(r"(\d+)h", hk).group(1))


def build_eventos_dict() -> dict:
    ev = json.load(open(EVENTOS, encoding="utf-8"))
    dd = json.load(open(DADOS, encoding="utf-8"))
    pers_por_modelo = {m["modelo"]: m.get("PERS_teste") for m in dd["models"]}
    combo_por_modelo = {m["modelo"]: m.get("combo_id", m["modelo"]) for m in dd["models"]}
    picos = {str(e["evento"]): e["pico_cm"] for e in ev["eventos"]}
    pico_data = {str(e["evento"]): e.get("pico_data") for e in ev["eventos"]}
    out = {}

    for evid in EVENTOS_DESTAQUE:
        pico = int(picos.get(evid) or 0)
        ilustra = pico >= COTA_INUND_CM  # cheias que transbordaram (cota oficial 18 m)
        for hk in sorted(ev["campeoes"].keys(), key=_hnum):
            H = _hnum(hk)
            modelo = hk.split("_", 1)[1]
            evs = ev["campeoes"][hk]
            if evid not in evs:
                continue
            serie = evs[evid]["serie"]  # [[time, obs, rna], ...]
            st_series = []
            for i in range(len(serie) - H):
                t = serie[i][0]
                agora = serie[i][1]
                obs = serie[i + H][1]
                prev = serie[i + H][2]
                st_series.append([t, agora, obs, prev])
            if len(st_series) < 2:
                continue
            data = evs[evid].get("pico_data") or pico_data.get(evid) or ""
            key = f"ev{evid}_{H}h"
            out[key] = {
                "label": f"Cheia {data} · {H}h",
                "evento": int(evid),
                "combo": combo_por_modelo.get(modelo, modelo),
                "horizonte": f"{H}h",
                "pers": round(pers_por_modelo.get(modelo) or 0, 2),
                "n": len(st_series),
                "pico_obs_cm": pico or int(max(s[2] for s in st_series if s[2] is not None)),
                "ilustra": bool(ilustra),
                "series": st_series,
            }

    # Referência estática — pico recorde maio/2024 (ev27), como record_2024 do ST
    pico27 = int(picos.get("27") or 2551)
    data27 = pico_data.get("27") or "2024-05-01"
    out["record_maio2024"] = {
        "label": f"Pico recorde · {data27}",
        "evento": 27,
        "combo": "referência",
        "horizonte": "—",
        "pers": None,
        "n": 1,
        "pico_obs_cm": pico27,
        "ilustra": True,
        "estatico": True,
        "series": [[f"pico recorde · {data27}", pico27, None, None]],
    }

    # Referência estática — julho/2020 (Zenodo / cota ~2211 cm), se existir no catálogo
    if "12" in picos:
        pico12 = int(picos["12"])
        data12 = pico_data.get("12") or "2020-07-08"
        out["record_jul2020"] = {
            "label": f"Pico jul/2020 · {data12}",
            "evento": 12,
            "combo": "referência",
            "horizonte": "—",
            "pers": None,
            "n": 1,
            "pico_obs_cm": pico12,
            "ilustra": True,
            "estatico": True,
            "series": [[f"pico jul/2020 · {data12}", pico12, None, None]],
        }

    return out


def eventos_payload_json() -> str:
    return json.dumps(build_eventos_dict(), ensure_ascii=False)


if __name__ == "__main__":
    d = build_eventos_dict()
    print(len(d), "cenas")
    for k, v in d.items():
        print(
            k,
            "pico",
            v.get("pico_obs_cm"),
            "ilustra",
            v.get("ilustra"),
            "estatico",
            v.get("estatico"),
            "n",
            v.get("n"),
        )
