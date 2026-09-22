#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Converte Pts-Transladados.TXT (N, E, Z) em KML e shapefile para ArcGIS.

O TXT de campo vem no formato brasileiro de topografia:

    nome,norte,este,cota

As coordenadas planas são SIRGAS 2000 / UTM fuso 22S (EPSG:31982).
Isso foi conferido no RN1 25892 RÉGUA SGB, que cai a ~6 m da estação
ANA/SGB 86472600 (Santa Tereza, -29.1781, -51.7322).

Uso:
    python codigo_python/11_levantamento_campo/txt_para_kml_shapefile.py

Dependências: pyproj, pyshp
"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import shapefile
from pyproj import CRS, Transformer

RAIZ = Path(__file__).resolve().parents[2]
FONTE = RAIZ / "assets/data/levantamento_campo/fonte/Pts-Transladados.TXT"
SAIDA = RAIZ / "assets/data/levantamento_campo"
SHP_DIR = SAIDA / "shapefile"
ZIP_ARCGIS = SAIDA / "Pts-Transladados_ArcGIS.zip"

CRS_UTM = "EPSG:31982"
CRS_WGS84 = "EPSG:4326"
ESTACAO_ANA = (-51.7322, -29.1781)  # lon, lat — 86472600 Santa Tereza

# WKT no dialeto ESRI, para o ArcGIS ler o .prj sem perguntar o datum.
PRJ_ESRI = CRS.from_epsg(31982).to_wkt(version="WKT1_ESRI")

PARA_WGS84 = Transformer.from_crs(CRS_UTM, CRS_WGS84, always_xy=True)
PARA_UTM = Transformer.from_crs(CRS_WGS84, CRS_UTM, always_xy=True)


def tipo_ponto(nome: str) -> str:
    n = nome.strip().upper()
    if n.startswith("BASE"):
        return "BASE"
    if n.startswith("RN"):
        return "RN"
    if n.startswith("H"):
        return "H"
    if n.startswith("V"):
        return "V"
    return "OUTRO"


def ler_pontos(caminho: Path) -> list[dict]:
    pontos = []
    with caminho.open(encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            partes = [p.strip() for p in linha.split(",")]
            if len(partes) != 4:
                raise ValueError(f"Linha inválida (esperado nome,norte,este,cota): {linha}")
            nome, norte_s, este_s, cota_s = partes
            norte = float(norte_s)
            este = float(este_s)
            cota = float(cota_s)
            lon, lat = PARA_WGS84.transform(este, norte)
            pontos.append(
                {
                    "nome": nome,
                    "tipo": tipo_ponto(nome),
                    "norte": norte,
                    "este": este,
                    "cota": cota,
                    "lon": lon,
                    "lat": lat,
                }
            )
    if not pontos:
        raise ValueError(f"Nenhum ponto lido em {caminho}")
    return pontos


def escrever_shapefile(pontos: list[dict], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()
    for ext in (".shx", ".dbf", ".prj", ".cpg"):
        extra = destino.with_suffix(ext)
        if extra.exists():
            extra.unlink()

    with shapefile.Writer(str(destino), shapeType=shapefile.POINTZ) as shp:
        shp.field("NOME", "C", 80)
        shp.field("TIPO", "C", 10)
        shp.field("NORTE", "N", 18, 3)
        shp.field("ESTE", "N", 18, 3)
        shp.field("COTA", "N", 12, 3)
        shp.field("LAT", "N", 12, 7)
        shp.field("LON", "N", 12, 7)
        for p in pontos:
            shp.pointz(p["este"], p["norte"], p["cota"])
            shp.record(
                p["nome"][:80],
                p["tipo"],
                p["norte"],
                p["este"],
                p["cota"],
                round(p["lat"], 7),
                round(p["lon"], 7),
            )
    destino.with_suffix(".prj").write_text(PRJ_ESRI + "\n", encoding="utf-8")
    destino.with_suffix(".cpg").write_text("UTF-8\n", encoding="ascii")


def _estilo_kml(sid: str, cor_abgr: str) -> str:
    return f"""    <Style id="{sid}">
      <IconStyle>
        <color>{cor_abgr}</color>
        <scale>1.1</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/paddle/wht-blank.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>0.9</scale>
      </LabelStyle>
    </Style>"""


def escrever_kml(pontos: list[dict], destino: Path) -> None:
    estilos = {
        "BASE": "ff0055ff",  # laranja
        "RN": "ff0000ff",  # vermelho
        "H": "ff00aa00",  # verde
        "V": "ffffaa00",  # azul
        "OUTRO": "ff888888",
    }
    blocos_estilo = "\n".join(_estilo_kml(f"st-{tipo}", cor) for tipo, cor in estilos.items())
    lons = [p["lon"] for p in pontos]
    lats = [p["lat"] for p in pontos]
    lon0 = (min(lons) + max(lons)) / 2
    lat0 = (min(lats) + max(lats)) / 2

    placemarks = []
    for p in pontos:
        nome = escape(p["nome"])
        placemarks.append(
            f"""      <Placemark>
        <name>{nome}</name>
        <styleUrl>#st-{p['tipo']}</styleUrl>
        <ExtendedData>
          <Data name="NOME"><value>{nome}</value></Data>
          <Data name="TIPO"><value>{p['tipo']}</value></Data>
          <Data name="NORTE"><value>{p['norte']:.3f}</value></Data>
          <Data name="ESTE"><value>{p['este']:.3f}</value></Data>
          <Data name="COTA"><value>{p['cota']:.3f}</value></Data>
          <Data name="LAT"><value>{p['lat']:.7f}</value></Data>
          <Data name="LON"><value>{p['lon']:.7f}</value></Data>
        </ExtendedData>
        <Point>
          <altitudeMode>absolute</altitudeMode>
          <coordinates>{p['lon']:.8f},{p['lat']:.8f},{p['cota']:.3f}</coordinates>
        </Point>
      </Placemark>"""
        )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Pts-Transladados</name>
    <description>Pontos de campo transladados — Santa Tereza/RS. Plano: SIRGAS 2000 / UTM 22S (EPSG:31982). KML em WGS84. Cota em metros.</description>
    <LookAt>
      <longitude>{lon0:.8f}</longitude>
      <latitude>{lat0:.8f}</latitude>
      <altitude>0</altitude>
      <heading>0</heading>
      <tilt>0</tilt>
      <range>2500</range>
    </LookAt>
{blocos_estilo}
    <Folder>
      <name>Pontos</name>
{chr(10).join(placemarks)}
    </Folder>
  </Document>
</kml>
"""
    destino.write_text(xml, encoding="utf-8")


def escrever_geojson(pontos: list[dict], destino: Path) -> None:
    features = []
    for p in pontos:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "NOME": p["nome"],
                    "TIPO": p["tipo"],
                    "NORTE": p["norte"],
                    "ESTE": p["este"],
                    "COTA": p["cota"],
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(p["lon"], 8), round(p["lat"], 8), p["cota"]],
                },
            }
        )
    fc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    destino.write_text(json.dumps(fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def escrever_csv_wgs84(pontos: list[dict], destino: Path) -> None:
    with destino.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["nome", "tipo", "norte", "este", "cota", "lat", "lon"])
        for p in pontos:
            w.writerow(
                [
                    p["nome"],
                    p["tipo"],
                    f"{p['norte']:.3f}",
                    f"{p['este']:.3f}",
                    f"{p['cota']:.3f}",
                    f"{p['lat']:.7f}",
                    f"{p['lon']:.7f}",
                ]
            )


def montar_zip(kml: Path, shp: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(kml, arcname=kml.name)
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            arq = shp.with_suffix(ext)
            zf.write(arq, arcname=f"shapefile/{arq.name}")
        leia = SAIDA / "LEIA-ME.md"
        if leia.exists():
            zf.write(leia, arcname="LEIA-ME.md")


def distancia_estacao(ponto: dict) -> float:
    e0, n0 = PARA_UTM.transform(*ESTACAO_ANA)
    return ((ponto["este"] - e0) ** 2 + (ponto["norte"] - n0) ** 2) ** 0.5


def main() -> None:
    pontos = ler_pontos(FONTE)
    SAIDA.mkdir(parents=True, exist_ok=True)
    SHP_DIR.mkdir(parents=True, exist_ok=True)

    shp = SHP_DIR / "Pts-Transladados.shp"
    kml = SAIDA / "Pts-Transladados.kml"
    geojson = SAIDA / "Pts-Transladados.geojson"
    csv_wgs = SAIDA / "Pts-Transladados_wgs84.csv"

    escrever_shapefile(pontos, shp)
    escrever_kml(pontos, kml)
    escrever_geojson(pontos, geojson)
    escrever_csv_wgs84(pontos, csv_wgs)
    montar_zip(kml, shp, ZIP_ARCGIS)

    rn1 = next((p for p in pontos if p["nome"].upper().startswith("RN1")), None)
    lons = [p["lon"] for p in pontos]
    lats = [p["lat"] for p in pontos]
    print(f"Pontos lidos: {len(pontos)}")
    print(f"CRS plano: {CRS_UTM} (SIRGAS 2000 / UTM 22S)")
    print(f"KML/GeoJSON: {CRS_WGS84}")
    print(f"Bbox WGS84: lon {min(lons):.6f}..{max(lons):.6f}  lat {min(lats):.6f}..{max(lats):.6f}")
    if rn1:
        dist = distancia_estacao(rn1)
        print(
            f"RN1 {rn1['nome']}: {rn1['lat']:.6f}, {rn1['lon']:.6f}  "
            f"cota {rn1['cota']:.3f} m  dist. estação 86472600 = {dist:.1f} m"
        )
    print(f"Shapefile: {shp}")
    print(f"KML: {kml}")
    print(f"ZIP ArcGIS: {ZIP_ARCGIS}")


if __name__ == "__main__":
    main()
