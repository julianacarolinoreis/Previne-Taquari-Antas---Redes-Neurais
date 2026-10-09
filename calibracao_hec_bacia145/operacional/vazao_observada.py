"""Fontes de nível/vazão observados nos controles (estado inicial q0 e correção pelo último observado).

Interface: fonte.obter(codigos, ini, fim) -> ({cod: {t: (nivel_cm, vazao_m3s, chuva_mm)}}, {cod: erro})
  TelemetriaANA      — HidroTelemetria ao vivo (a vazão é a que a ANA publica junto com o nível).
  ArquivoObservados  — dados/observados/<cod>_<janela>.csv.gz (retroativo; mesmos dados da calibração).
"""
import gzip
from pathlib import Path

import telemetria_ana as ta


class FonteObservados:
    def obter(self, codigos, ini, fim):
        raise NotImplementedError


class TelemetriaANA(FonteObservados):
    nome = "telemetria ANA"

    def __init__(self, ja_baixados=None):
        self.ja = ja_baixados or {}

    def obter(self, codigos, ini, fim):
        falta = [c for c in codigos if c not in self.ja]
        regs, falhas = ta.baixar_varios(falta, ini, fim) if falta else ({}, {})
        out = {c: {t: v for t, v in self.ja[c].items() if ini <= t <= fim} for c in codigos if c in self.ja}
        out.update(regs)
        return out, falhas


class ArquivoObservados(FonteObservados):
    nome = "arquivo dados/observados (telemetria ANA da calibração)"

    def __init__(self, janela, pasta):
        self.janela, self.pasta = janela, Path(pasta)

    def obter(self, codigos, ini, fim):
        out, falhas = {}, {}
        for c in codigos:
            f = self.pasta / f"{c}_{self.janela}.csv.gz"
            if not f.exists():
                falhas[c] = "sem arquivo"
                continue
            reg = ta.ler_csv_texto(gzip.decompress(f.read_bytes()).decode("utf-8"))
            out[c] = {t: v for t, v in reg.items() if ini <= t <= fim}
        return out, falhas
