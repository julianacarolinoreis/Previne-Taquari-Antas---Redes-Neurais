#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta a ficha oficial da estação na ANA — Santa Tereza 86472600.

Serve para obter os dados de referência da estação (altitude, coordenadas,
responsável/operadora e, quando disponível, a cota de referência) que ajudam a
fixar o ZERO DA RÉGUA e amarrá-lo ao datum do MDT.

IMPORTANTE
----------
- A API `HidroInventario` traz metadados da estação (inclui `Altitude`).
- A **cota oficial do zero da régua** costuma estar no NIVELAMENTO / ficha
  descritiva (RN) da estação, que nem sempre vem nesta API. Se não vier aqui,
  buscar no relatório/descritivo da estação no portal do SGB/ANA.
- Rodar onde a ANA é acessível (o sandbox do assistente bloqueia ana.gov.br;
  o GitHub Actions e um PC comum acessam normalmente).

Uso:  python consulta_estacao_ana.py [codEstacao]
"""
import sys
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx"

def local(tag):
    return tag.rsplit("}", 1)[-1]

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "previne-consulta/1.0"})
    return urllib.request.urlopen(req, timeout=60).read()

def inventario(cod):
    url = (f"{BASE}/HidroInventario?codEstacao={cod}&nomeEstacao=&codSubBacia="
           f"&codBacia=&nomeResponsavel=&nomeOperadora=")
    root = ET.fromstring(get(url))
    # o inventário pode vir como XML aninhado dentro de <string>
    if not any(local(e.tag) == "Table" for e in root.iter()) and (root.text or "").strip().startswith("<"):
        root = ET.fromstring(root.text)
    campos = {}
    for row in root.iter():
        for ch in row:
            campos.setdefault(local(ch.tag), (ch.text or "").strip())
    return campos

def main(cod):
    print(f"Consultando estação {cod} na ANA (HidroInventario)...")
    try:
        campos = inventario(cod)
    except Exception as e:
        print(f"ERRO ao consultar a ANA: {e}")
        print("Rode este script onde a ANA é acessível (PC/servidor, não no sandbox).")
        return
    interesse = ["Codigo", "Nome", "Latitude", "Longitude", "Altitude",
                 "AreaDrenagem", "Rio", "SubBacia", "Bacia", "Municipio",
                 "Estado", "Responsavel", "Operadora", "CotaNivelDescarga"]
    print("\n--- campos de interesse ---")
    for k in interesse:
        if k in campos:
            print(f"  {k:16s}: {campos[k]}")
    print("\n--- todos os campos retornados ---")
    for k, v in sorted(campos.items()):
        if v:
            print(f"  {k}: {v}")
    print("\nSe a cota do zero da régua NÃO aparecer acima, ela está no")
    print("nivelamento/descritivo da estação (SGB/ANA) — pegar de lá.")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "86472600")
