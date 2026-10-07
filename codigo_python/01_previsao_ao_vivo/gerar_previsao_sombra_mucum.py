#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robô em SOMBRA — RNAs v2 de Muçum (4 h e 8 h com estações a montante).

Não altera o feed público (previsao_ao_vivo_mucum.json). Roda de hora em hora,
grava previsao_sombra_mucum.json e um histórico permanente
(historico_previsao_sombra_mucum.jsonl) para comparar com o observado antes de
qualquer promoção ao site.

Contrato dos modelos: assets/data/mucum_modelos_sombra.json. Diferenças em
relação ao robô principal, exigidas pelo treino v2:
  * chuva "media_dos_acumulados_por_posto": acumulado de k horas por posto só
    se as k horas existem; média dos postos com valor; chuva da hora H = soma
    das leituras com carimbo em (H-1h, H];
  * limites mínimo/máximo por estação (barragens em cota absoluta);
  * controle de qualidade ao vivo: leitura <= 0, erro de bit (~16384 em régua
    < 50 m) e sensor travado (>= 6 h com o mesmo valor enquanto Muçum varia
    > 30 cm) viram dado ausente;
  * hierarquia de reserva por horizonte: usa o primeiro nível com todas as
    entradas e base com antecedência suficiente; publica o nível usado e o motivo;
  * faixa de incerteza (E95 da auditoria por situação: subida / >= 1500 cm / geral).
O mesmo script atende Santa Tereza: `--contrato assets/data/santa_tereza_modelos_sombra.json`
(o contrato define "alvo", "saida_json" e "historico_jsonl").
EXPERIMENTAL — não é alerta oficial.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import xml.etree.ElementTree as ET

AQUI = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("robo_mucum", os.path.join(AQUI, "gerar_previsao_ao_vivo_mucum.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

RAIZ = R.RAIZ
CONTRATO = os.path.join(RAIZ, "assets", "data", "mucum_modelos_sombra.json")
SAIDA = os.path.join(RAIZ, "previsao_sombra_mucum.json")
HISTORICO = os.path.join(RAIZ, "historico_previsao_sombra_mucum.jsonl")
ALVO = R.ALVO
DIAS_JANELA = 4          # lags até 24 h + chuva 48 h + diferença 24/48 h
TRAVADO_H = 6
TRAVADO_VARIACAO_ALVO_CM = 30.0


# ---------------------------------------------------------------- leitura ANA
def _parse_xml(xml):
    root = ET.fromstring(xml)
    linhas = [row for row in root.iter()]
    if not any(_campo(r, "DataHora") for r in linhas) and (root.text or "").strip().startswith("<"):
        linhas = list(ET.fromstring(root.text).iter())
    return linhas


def _campo(row, nome):
    for ch in row:
        if R._local(ch.tag) == nome:
            return (ch.text or "").strip()
    return None


def series_da_resposta(xml):
    """(nível em hora cheia exata, chuva por hora com rótulo (H-1, H])."""
    niveis, chuva = {}, {}
    for row in _parse_xml(xml):
        dh = _campo(row, "DataHora")
        if not dh:
            continue
        t = R._parse_hora(dh)
        if t is None:
            continue
        nv = _campo(row, "Nivel")
        if nv not in (None, "") and t.minute == 0 and t.second == 0:
            try:
                niveis[t] = float(nv.replace(",", "."))
            except ValueError:
                pass
        ch = _campo(row, "Chuva")
        if ch not in (None, ""):
            try:
                v = float(ch.replace(",", "."))
            except ValueError:
                continue
            if v < 0 or v > 100:
                continue
            hora = t if (t.minute == 0 and t.second == 0) else t.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
            chuva[hora] = chuva.get(hora, 0.0) + v
    return niveis, chuva


def baixar(cod):
    xml = R._obter_xml_ana(cod, DIAS_JANELA, R.ANA_TIMEOUT_NIVEL_S, R.ANA_RETRIES_NIVEL, R._serie_de_xml, "ANA sombra")
    if xml is None:
        return {}, {}
    return series_da_resposta(xml)


# ------------------------------------------------------- controle de qualidade
def qc_niveis(cod, serie, limites, alvo_serie=None):
    lim = limites.get(cod, {})
    mn, mx = float(lim.get("min", 0.0)), float(lim.get("max", R.NIVEL_PLAUSIVEL_MAX_CM))
    limpa = {}
    for t, v in serie.items():
        if v <= 0 or v < mn or v > mx:
            continue
        if mx <= 5000 and 16000 <= v <= 21384:
            continue
        limpa[t] = v
    # salto impossível (mesma regra do treino): |v - última leitura aceita| > salto_max_1h
    # é descartado até o nível voltar; só uma interrupção real da série bruta (> 3 h sem
    # leitura) refaz a âncora
    salto = lim.get("salto_max_1h")
    if salto:
        ancora, anterior = None, None
        for t in sorted(limpa):
            v = limpa[t]
            continua = anterior is not None and t - anterior <= dt.timedelta(hours=3)
            anterior = t
            if ancora is not None and continua and abs(v - ancora) > float(salto):
                limpa.pop(t)
                continue
            ancora = v
    if cod == ALVO or not limpa:
        return limpa
    horas = sorted(limpa)
    i = 0
    while i < len(horas):
        j = i
        while (j + 1 < len(horas) and horas[j + 1] - horas[j] == dt.timedelta(hours=1)
               and limpa[horas[j + 1]] == limpa[horas[i]]):
            j += 1
        if j - i + 1 >= TRAVADO_H and alvo_serie:
            vals = [alvo_serie[h] for h in horas[i:j + 1] if h in alvo_serie]
            if vals and max(vals) - min(vals) > TRAVADO_VARIACAO_ALVO_CM:
                for h in horas[i:j + 1]:
                    limpa.pop(h, None)
        i = j + 1
    return limpa


# -------------------------------------------------------------------- entradas
def _n(niveis, cod, t):
    return (niveis.get(cod) or {}).get(t)


def _acum_posto(chuva, posto, fim, janela):
    vals = [(chuva.get(posto) or {}).get(fim - dt.timedelta(hours=h)) for h in range(janela)]
    return None if any(v is None for v in vals) else float(sum(vals))


def _media_acumulados(inp, chuva, t, deslocamento=0):
    fim = t - dt.timedelta(hours=deslocamento)
    acc = [_acum_posto(chuva, p, fim, int(inp["janela_h"])) for p in inp["estacoes"]]
    acc = [a for a in acc if a is not None]
    return sum(acc) / len(acc) if acc else None


def montar_entradas(inputs, niveis, chuva, t):
    x, faltam = [], []
    for inp in inputs:
        cod, tipo, h = inp.get("estacao"), inp["tipo"], int(inp.get("defasagem_h") or 0)
        v = None
        if tipo == "nivel":
            v = _n(niveis, cod, t - dt.timedelta(hours=h))
        elif tipo == "vel_nivel":
            a, b = _n(niveis, cod, t), _n(niveis, cod, t - dt.timedelta(hours=h))
            v = None if None in (a, b) else a - b
        elif tipo == "acel_nivel":
            a, b = _n(niveis, cod, t), _n(niveis, cod, t - dt.timedelta(hours=1))
            c, d = _n(niveis, cod, t - dt.timedelta(hours=h)), _n(niveis, cod, t - dt.timedelta(hours=h + 1))
            v = None if None in (a, b, c, d) else (a - b) - (c - d)
        elif tipo == "chuva_acum":
            v = _media_acumulados(inp, chuva, t)
        elif tipo == "chuva_diferenca":
            # mesma definição do treino: média, entre os postos, da diferença de cada posto
            difs = []
            for p in inp["estacoes"]:
                pa = _acum_posto(chuva, p, t, int(inp["janela_h"]))
                pb = _acum_posto(chuva, p, t - dt.timedelta(hours=int(inp.get("janela_anterior_h") or inp["janela_h"])), int(inp["janela_h"]))
                if pa is not None and pb is not None:
                    difs.append(pa - pb)
            v = sum(difs) / len(difs) if difs else None
        else:
            raise ValueError(f"tipo de entrada não suportado: {tipo}")
        x.append(v)
        if v is None:
            faltam.append(inp.get("nome") or f"inp{inp.get('ordem')}")
    return x, faltam


# ------------------------------------------------------------------- previsão
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest().upper()


def faixa(modelo, nivel_base, subindo, previsto):
    fx = modelo.get("faixa_e95_cm") or {}
    if previsto >= 1500 and fx.get("acima_1500"):
        e, motivo = fx["acima_1500"], "nível previsto >= 1500 cm"
    elif subindo and fx.get("subida"):
        e, motivo = fx["subida"], "rio subindo"
    else:
        e, motivo = fx.get("geral"), "geral"
    if e is None:
        return None
    return {"min_cm": round(previsto - e), "max_cm": round(previsto + e), "e95_cm": round(e, 1), "situacao": motivo}


def prever_horizonte(nivel_cfg, niveis, chuva, horas_alvo, agora):
    """Percorre a hierarquia do horizonte; devolve (escolhido, todos)."""
    resultados, escolhido = [], None
    H = int(nivel_cfg["horizonte_h"])
    for m in sorted(nivel_cfg["modelos"], key=lambda m: m["nivel_hierarquia"]):
        mat = os.path.join(RAIZ, m["mat"])
        item = {"modelo": m["modelo_id"], "nivel_hierarquia": m["nivel_hierarquia"], "papel": m.get("papel"),
                "horizonte_h": H, "disponivel": False}
        if not os.path.exists(mat):
            item["status"] = "MAT ausente"
            resultados.append(item)
            continue
        if m.get("modelo_sha256") and _sha256(mat) != m["modelo_sha256"].upper():
            item["status"] = "sha256 do MAT não confere"
            resultados.append(item)
            continue
        base = None
        for t in reversed(horas_alvo[-13:]):
            x, faltam = montar_entradas(m["inputs"], niveis, chuva, t)
            if not faltam:
                base = (t, x)
                break
        if base is None:
            x, faltam = montar_entradas(m["inputs"], niveis, chuva, horas_alvo[-1]) if horas_alvo else ([], ["sem dado de Muçum"])
            item.update({"status": f"entradas incompletas ({len(faltam)})", "entradas_faltando": faltam})
            resultados.append(item)
            continue
        t, x = base
        antecedencia, ok = R.antecedencia_efetiva({"horizonte_h": H}, t, agora)
        variacao = R.prever(mat, x)
        nivel_base = niveis[ALVO][t]
        previsto = nivel_base + variacao
        subindo = (niveis[ALVO].get(t - dt.timedelta(hours=1)) or nivel_base) < nivel_base
        item.update({
            "hora_modelo": t.isoformat(timespec="minutes"),
            "hora_alvo": (t + dt.timedelta(hours=H)).isoformat(timespec="minutes"),
            "nivel_base_cm": round(nivel_base, 1), "nivel_previsto_cm": round(previsto, 1),
            "antecedencia_efetiva_h": round(antecedencia, 2),
            "faixa_incerteza": faixa(m, nivel_base, subindo, previsto),
            "fora_do_treino": bool(previsto > float(m.get("maximo_treino_nivel_cm", 1e9))),
        })
        if not ok:
            item["status"] = f"base desatualizada (antecedência {antecedencia:.1f} h)"
        elif not R.nivel_plausivel(previsto, ALVO):
            item["status"] = "previsão fora da faixa plausível"
        else:
            item["status"], item["disponivel"] = "ok", True
            if escolhido is None and m["nivel_hierarquia"] >= 1:   # nível 0 = controle, só registro
                escolhido = item
        resultados.append(item)
    return escolhido, resultados


# ------------------------------------------------------------------ histórico
def atualizar_historico(registros_novos, niveis_alvo):
    hist = {}
    if os.path.exists(HISTORICO):
        with open(HISTORICO, encoding="utf-8") as f:
            for linha in f:
                if linha.strip():
                    r = json.loads(linha)
                    hist[(r["modelo"], r["hora_modelo"])] = r
    for r in registros_novos:
        hist.setdefault((r["modelo"], r["hora_modelo"]), r)
    for r in hist.values():
        if r.get("observado_cm") is None:
            alvo = R._parse_hora(r["hora_alvo"])
            if alvo in niveis_alvo:
                r["observado_cm"] = round(niveis_alvo[alvo], 1)
                r["erro_cm"] = round(r["nivel_previsto_cm"] - r["observado_cm"], 1)
    with open(HISTORICO, "w", encoding="utf-8") as f:
        for r in sorted(hist.values(), key=lambda r: (r["hora_modelo"], r["modelo"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(hist)


def main(argv=None):
    global ALVO, SAIDA, HISTORICO, CONTRATO
    argv = sys.argv[1:] if argv is None else argv
    if "--contrato" in argv:
        CONTRATO = os.path.join(RAIZ, argv[argv.index("--contrato") + 1])
    agora = R.agora_brt()
    contrato = json.load(open(CONTRATO, encoding="utf-8"))
    ALVO = str(contrato.get("alvo") or ALVO)
    SAIDA = os.path.join(RAIZ, contrato.get("saida_json") or os.path.basename(SAIDA))
    HISTORICO = os.path.join(RAIZ, contrato.get("historico_jsonl") or os.path.basename(HISTORICO))
    limites = contrato.get("limites_estacao_cm", {})
    estacoes = [ALVO] + sorted({c for hz in contrato["horizontes"].values() for m in hz["modelos"]
                                for c in m.get("estacoes_nivel", []) + m.get("estacoes_chuva", [])} - {ALVO})
    niveis, chuva = {}, {}
    for cod in estacoes:
        n, c = baixar(cod)
        niveis[cod], chuva[cod] = n, c
    niveis[ALVO] = qc_niveis(ALVO, niveis.get(ALVO, {}), limites)
    for cod in estacoes:
        if cod != ALVO:
            niveis[cod] = qc_niveis(cod, niveis.get(cod, {}), limites, niveis[ALVO])
    horas_alvo = sorted(niveis[ALVO])
    saida = {"gerado_em": agora.isoformat(timespec="seconds"), "aviso": "SOMBRA EXPERIMENTAL — não publicado no site; não é alerta oficial.",
             "contrato": os.path.relpath(CONTRATO, RAIZ), "alvo": ALVO, "ultima_hora_alvo": horas_alvo[-1].isoformat() if horas_alvo else None,
             "estacoes_sem_dado": [c for c in estacoes if not niveis.get(c) and not chuva.get(c)], "horizontes": {}}
    novos = []
    for chave, cfg in contrato["horizontes"].items():
        escolhido, todos = prever_horizonte(cfg, niveis, chuva, horas_alvo, agora) if horas_alvo else (None, [])
        saida["horizontes"][chave] = {
            "horizonte_h": cfg["horizonte_h"],
            "nivel_usado": escolhido["nivel_hierarquia"] if escolhido else None,
            "modelo_usado": escolhido["modelo"] if escolhido else None,
            "previsao": escolhido,
            "motivo": None if escolhido else "nenhum nível da hierarquia com entradas completas e base atual",
            "niveis": todos,
        }
        for it in todos:
            if it.get("nivel_previsto_cm") is not None:
                novos.append({k: it.get(k) for k in ("modelo", "nivel_hierarquia", "horizonte_h", "hora_modelo", "hora_alvo",
                                                      "nivel_base_cm", "nivel_previsto_cm", "antecedencia_efetiva_h", "status")}
                             | {"observado_cm": None, "erro_cm": None, "usado": bool(escolhido and it["modelo"] == escolhido["modelo"])})
    saida["historico_registros"] = atualizar_historico(novos, niveis.get(ALVO, {}))
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)
    for chave, h in saida["horizontes"].items():
        p = h["previsao"]
        print(chave, "nível", h["nivel_usado"], h["modelo_usado"], p and p["nivel_previsto_cm"], p and p["antecedencia_efetiva_h"])


if __name__ == "__main__":
    sys.exit(main())
