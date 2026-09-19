#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibilidade: encaminha para o robô canônico de Santa Tereza.

Este caminho antigo é mantido apenas para scripts locais que ainda o chamem.
A lógica operacional NÃO deve ser duplicada aqui. O código oficial fica em:
    previne/robo/gerar_previsao_ao_vivo.py
"""
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "previne" / "robo" / "gerar_previsao_ao_vivo.py"

if __name__ == "__main__":
    if not CANONICAL.exists():
        raise SystemExit(f"robô canônico não encontrado: {CANONICAL}")
    runpy.run_path(str(CANONICAL), run_name="__main__")
