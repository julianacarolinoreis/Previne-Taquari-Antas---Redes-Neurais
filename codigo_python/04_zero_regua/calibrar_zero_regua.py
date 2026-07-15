#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calibração do "zero" da mancha (parâmetro bankfull) — Santa Tereza 86472600.

PROBLEMA
--------
A mancha converte um nível da régua (cm) em área inundada usando o HAND
(altura de cada ponto acima do rio). Para isso precisa de UM offset: a que
leitura da régua a água começa a sair do canal (HAND = 0). No código do site
esse offset é o parâmetro `bankfull_cm`. Ele estava chutado em 300 cm.

MÉTODO (ancorado na cota de inundação OFICIAL)
----------------------------------------------
1. Do MDT ANADEM (terreno nu), medimos:
     - a cota do leito do rio na estação (talvegue)  -> E_rio
     - a cota do terraço onde fica a cidade           -> E_cidade
   O HAND da cidade é  H_cidade = E_cidade - E_rio.
2. A cota de inundação oficial (SGB/SACE) em Santa Tereza é 15 m (1500 cm):
   é a leitura da régua em que a água atinge a cidade.
3. Logo, na régua = 1500 cm, a altura da água acima do rio deve igualar
   H_cidade. Como  altura = (regua - bankfull)/100 :
        (1500 - bankfull)/100 = H_cidade
     => bankfull_cm = 1500 - 100 * H_cidade
4. Conferência independente: abaixo de ~5 m a régua só oscila pelas barragens
   (o "efeito cobrinha") e NÃO transborda -> bankfull deve ficar perto de 500 cm.

LIMITAÇÃO
---------
E_rio e E_cidade vêm do ANADEM (~±1-2 m). O valor definitivo exige a
**cota oficial do zero da régua** (nivelamento SGB/ANA) amarrada ao mesmo
datum vertical — ver `consulta_estacao_ana.py`.
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
COTA_INUND = 1500                   # cm (15 m) — cota de inundação oficial

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

    bankfull = COTA_INUND - 100.0 * H_cidade

    print("=== Calibração do zero da mancha (Santa Tereza 86472600) ===")
    print(f"cota do leito (talvegue) ANADEM   E_rio    = {E_rio:6.1f} m")
    print(f"cota do terraço da cidade (p25)   E_cidade = {E_cidade:6.1f} m")
    print(f"HAND da cidade                    H_cidade = {H_cidade:6.1f} m")
    print(f"cota de inundação oficial                  = {COTA_INUND} cm (15 m)")
    print(f"-> bankfull recomendado = 1500 - 100*{H_cidade:.1f} = {bankfull:.0f} cm")
    print()
    print("Conferências independentes:")
    print(f"  água deixa o canal principal (HAND 0) na régua ~{bankfull:.0f} cm "
          f"({bankfull/100:.1f} m) -> só várzea/beira, ainda NÃO a cidade")
    print(f"  cidade (HAND {H_cidade:.0f} m) só alaga na régua "
          f"{bankfull + 100*H_cidade:.0f} cm = cota de inundação 15 m  [ok, por construção]")
    rec = 2582  # recorde mai/2024
    print(f"  recorde mai/2024 {rec} cm -> altura sobre o rio = "
          f"{(rec - bankfull)/100:.1f} m (catastrófico, esperado)")
    print()
    print("OBS.: valor sujeito a ±1-2 m do ANADEM. Definitivo requer a cota")
    print("      oficial do zero da régua (SGB/ANA) — ver consulta_estacao_ana.py.")

if __name__ == "__main__":
    main()
