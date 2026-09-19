#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conferência da conversão régua ↔ HAND — Santa Tereza 86472600.

CONVENÇÃO ADOTADA NO PROJETO
----------------------------
A leitura de 15,0 m (1500 cm) na régua é tratada como o início do
extravasamento do canal, isto é, HAND = 0. Portanto a altura relativa usada
na mancha não é a própria leitura da régua:

    nivel_HAND_m = max(0, nivel_regua_m - 15,0)

e, inversamente, um ponto com HAND = h passa a ser associado ao cenário:

    nivel_regua_m ≈ 15,0 + h

Exemplos: HAND 5 m -> ~20 m na régua; HAND 10 m -> ~25 m; HAND 15 m -> ~30 m.

O cálculo antigo inferia ~4 m como HAND 0 ao assumir que 15 m era a cota em
que a água já alcançava o terraço urbano. Essa interpretação foi removida:
15 m é o limiar de extravasamento adotado, não a cota de inundação de todos
os locais da cidade.

LIMITAÇÃO
---------
A conversão HAND continua sendo uma aproximação topográfica simplificada.
A validação definitiva requer datum vertical compatível, nivelamento da régua
e confrontação com manchas observadas/hidrodinâmicas.
"""
import os
import sys
import numpy as np
import rasterio

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MDT_PADRAO = os.path.normpath(os.path.join(
    _AQUI, "..", "..", "assets", "data", "santa_tereza_inundacao",
    "mdt", "mdt_santa_tereza_anadem_30m.tif"))
MDT = sys.argv[1] if len(sys.argv) > 1 else _MDT_PADRAO
LAT, LON   = -29.1781, -51.7322     # estação 86472600
BANKFULL_CM = 1500                  # cm (15 m) — início do extravasamento adotado

def main():
    with rasterio.open(MDT) as ds:
        dem = ds.read(1).astype("float64"); t = ds.transform
    sr = int((LAT - t.f) / t.e); sc = int((LON - t.c) / t.a)
    # refina para o mínimo local (talvegue) numa janela 7x7 em volta da estação
    r0, c0 = max(0, sr - 3), max(0, sc - 3)
    win = dem[r0:sr + 4, c0:sc + 4]
    dr, dc = np.unravel_index(np.argmin(win), win.shape)
    sr, sc = r0 + dr, c0 + dc
    E_rio = float(dem[sr, sc])

    # terraço da cidade: percentil 25 das cotas do entorno (~900 m), fora do canal
    R = 30
    sub = dem[max(0, sr - R):sr + R, max(0, sc - R):sc + R]
    sub = sub[(sub > 0) & (sub < 200)]
    E_cidade = float(np.percentile(sub, 25))
    H_cidade = E_cidade - E_rio

    bankfull = float(BANKFULL_CM)
    cota_cidade = bankfull + 100.0 * H_cidade

    print("=== Calibração do zero da mancha (Santa Tereza 86472600) ===")
    print(f"cota do leito (talvegue) ANADEM   E_rio    = {E_rio:6.1f} m")
    print(f"cota do terraço da cidade (p25)   E_cidade = {E_cidade:6.1f} m")
    print(f"HAND da cidade                    H_cidade = {H_cidade:6.1f} m")
    print(f"início do extravasamento adotado (HAND 0) = {bankfull:.0f} cm ({bankfull/100:.1f} m)")
    print(f"terraço de referência (HAND {H_cidade:.1f} m) -> régua ~{cota_cidade:.0f} cm ({cota_cidade/100:.1f} m)")
    print()
    print("Conferência da conversão:")
    print("  régua 15,0 m -> HAND 0 m")
    print("  régua 20,0 m -> HAND 5 m")
    print("  régua 25,0 m -> HAND 10 m")
    print("  régua 30,0 m -> HAND 15 m")
    rec = 2582  # referência mai/2024
    print(f"  referência mai/2024 {rec} cm -> altura sobre o rio = "
          f"{(rec - bankfull)/100:.1f} m (catastrófico, esperado)")
    print()
    print("OBS.: HAND é aproximação topográfica; validar com datum da régua e manchas observadas.")

if __name__ == "__main__":
    main()
