#!/usr/bin/env python3
"""Arquiva a telemetria da ANA das 20 estações da Defesa Civil RS (DCRS) da bacia Taquari-Antas.

O serviço de telemetria da ANA guarda só alguns dias dessas estações (a rede começou em 12/08/2026) e responde
"Sem dados" para períodos antigos. Sem arquivo próprio, a chuva delas se perde e nunca poderá entrar em
calibração ou validação do HEC-HMS e das RNAs.

Grava assets/data/dcrs_telemetria/AAAA-MM/<codigo>.csv (data_hora;nivel_cm;chuva_mm), sem sobrescrever o que
já existe: só acrescenta ou completa registros. Nada é preenchido; ausência continua ausência.
Uso: python scripts/arquivar_telemetria_dcrs.py [dias_para_tras]   (padrão 3)
"""
from __future__ import annotations

import csv
import re
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "assets" / "data" / "dcrs_telemetria"
BASES = ["https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos",
         "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"]
ESTACOES = {
    "86095100": "Bom Jesus/Jaquirana", "86120050": "São Francisco de Paula-Cambará", "86297995": "Flores da Cunha-Antônio Prado",
    "86329001": "Nova Roma/Farroupilha", "86342000": "Muitos Capões/Lagoa Vermelha", "86410001": "Protásio Alves/Ipê",
    "86507220": "Cotiporã/Dois Lajeados", "86529500": "Marau", "86542000": "União da Serra", "86560020": "Guaporé-Anta Gorda",
    "86581000": "Muçum/Encantado", "86640900": "Putinga", "86700005": "Encantado", "86733330": "Encantado/Roca Sales",
    "86739850": "Imigrante", "86744900": "Travesseiro/Pouso Novo", "86746680": "Canudos do Vale", "86855000": "Teutônia",
    "86878700": "Arroio do Meio/Lajeado", "86888400": "Santa Cruz do Sul-Venâncio Aires",
}
CAB = ["data_hora", "nivel_cm", "chuva_mm"]


def parse(xml: str) -> dict[str, tuple[str, str]]:
    out = {}
    for blk in re.findall(r"<DadosHidrometereologicos .*?</DadosHidrometereologicos>", xml, re.S):
        def g(k):
            m = re.search(rf"<{k}>(.*?)</{k}>", blk)
            return m[1].strip() if m else ""
        dh = g("DataHora")
        if dh:
            out[dh[:19].replace("T", " ")] = (g("Nivel"), g("Chuva"))
    return out


def baixar(cod: str, ini: date, fim: date) -> dict[str, tuple[str, str]]:
    erro = None
    for tentativa in range(3):
        for base in BASES:
            try:
                url = f"{base}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}"
                return parse(urllib.request.urlopen(url, timeout=90).read().decode("utf-8", "ignore"))
            except Exception as exc:  # noqa: BLE001
                erro = exc
        time.sleep(3 * (tentativa + 1))
    raise RuntimeError(f"{cod}: {erro}")


def mesclar(cod: str, novos: dict[str, tuple[str, str]], pasta: Path = PASTA) -> int:
    """Acrescenta registros por mês. Valor já gravado nunca é alterado; preenche só o que faltava. Devolve o nº de linhas novas."""
    por_mes: dict[str, dict[str, tuple[str, str]]] = {}
    for k, v in novos.items():
        por_mes.setdefault(k[:7], {})[k] = v
    n_novas = 0
    for mes, regs in por_mes.items():
        arq = pasta / mes / f"{cod}.csv"
        atuais: dict[str, tuple[str, str]] = {}
        if arq.exists():
            with arq.open(encoding="utf-8", newline="") as h:
                for r in csv.DictReader(h, delimiter=";"):
                    atuais[r["data_hora"]] = (r["nivel_cm"], r["chuva_mm"])
        antes = len(atuais)
        for k, (nv, ch) in regs.items():
            if k not in atuais:
                atuais[k] = (nv, ch)
            else:
                a_nv, a_ch = atuais[k]
                atuais[k] = (a_nv or nv, a_ch or ch)
        n_novas += len(atuais) - antes
        if len(atuais) != antes or not arq.exists():
            arq.parent.mkdir(parents=True, exist_ok=True)
            with arq.open("w", encoding="utf-8", newline="") as h:
                w = csv.writer(h, delimiter=";", lineterminator="\n")
                w.writerow(CAB)
                for k in sorted(atuais):
                    w.writerow([k, *atuais[k]])
    return n_novas


def main() -> int:
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    fim = date.today()
    ini = fim - timedelta(days=dias)
    total, falhas = 0, []
    for cod, nome in ESTACOES.items():
        try:
            n = mesclar(cod, baixar(cod, ini, fim))
            total += n
            print(f"{cod} {nome}: +{n}")
        except Exception as exc:  # noqa: BLE001
            falhas.append(cod)
            print(f"FALHA {cod} {nome}: {exc}")
    print(f"linhas novas: {total}; falhas: {len(falhas)}")
    return 1 if len(falhas) == len(ESTACOES) else 0


if __name__ == "__main__":
    sys.exit(main())
