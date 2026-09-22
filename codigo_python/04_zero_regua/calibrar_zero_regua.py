#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conferência da conversão régua ↔ HAND — Santa Tereza 86472600.

CONVENÇÃO OPERACIONAL ATUAL
---------------------------
A espacialização usa a calibração de campo:

    régua 1,60 m = HAND 0

Logo:

    nivel_HAND_m = max(0, nivel_regua_m - 1,60)

A cota de 15,00 m continua registrada separadamente como limiar de
transbordamento/estado. Ela NÃO é o zero vertical da mancha.

Exemplos:
    15,00 m -> HAND 13,40 m
    19,14 m -> HAND 17,54 m
    23,57 m -> HAND 21,97 m

Esta é uma calibração operacional de pesquisa. Não transforma a leitura da
régua em altitude absoluta e deve continuar sendo confrontada com marcas de
cheia, manchas observadas e modelagem hidráulica/hidrodinâmica.
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
HAND_ZERO_CM = 160                  # 1,60 m na régua = HAND 0 (calibração de campo)
BANKFULL_CM = 1500                   # 15,00 m = limiar de transbordamento/estado

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

    hand_zero = float(HAND_ZERO_CM)
    bankfull = float(BANKFULL_CM)
    cota_cidade = hand_zero + 100.0 * H_cidade

    print("=== Calibração do zero da mancha (Santa Tereza 86472600) ===")
    print(f"cota do leito (talvegue) ANADEM   E_rio    = {E_rio:6.1f} m")
    print(f"cota do terraço da cidade (p25)   E_cidade = {E_cidade:6.1f} m")
    print(f"HAND da cidade                    H_cidade = {H_cidade:6.1f} m")
    print(f"zero espacial de campo            = {hand_zero:.0f} cm ({hand_zero/100:.2f} m)")
    print(f"limiar de transbordamento/estado  = {bankfull:.0f} cm ({bankfull/100:.2f} m)")
    print(f"terraço de referência (HAND {H_cidade:.1f} m) -> régua ~{cota_cidade:.0f} cm ({cota_cidade/100:.1f} m)")
    print()
    print("Conferência da conversão operacional:")
    for nivel_cm in (1500, 1914, 2357):
        print(f"  régua {nivel_cm/100:.2f} m -> HAND {(nivel_cm-hand_zero)/100:.2f} m")
    print()
    print("OBS.: calibração operacional de pesquisa; validar com marcas/manchas observadas e modelagem hidráulica.")

if __name__ == "__main__":
    main()
