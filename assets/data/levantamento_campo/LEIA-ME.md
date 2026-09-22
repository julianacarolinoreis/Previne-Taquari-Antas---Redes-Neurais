# Pts-Transladados — KML e shapefile (ArcGIS)

Pontos de campo de Santa Tereza/RS convertidos a partir de `fonte/Pts-Transladados.TXT`.

Formato de origem: `nome,norte,este,cota` (metros).

## Sistema de coordenadas

| Arquivo | CRS | Uso |
|---|---|---|
| `shapefile/Pts-Transladados.shp` | SIRGAS 2000 / UTM 22S (EPSG:31982) | ArcGIS Pro / ArcMap — coordenadas originais do levantamento |
| `Pts-Transladados.kml` | WGS84 (EPSG:4326) | Google Earth, ArcGIS (KML To Layer), QGIS |
| `Pts-Transladados.geojson` | WGS84 (EPSG:4326) | conferência / web |

O `.prj` do shapefile já traz o WKT no dialeto ESRI. Não defina o CRS na mão, a menos que o ArcGIS peça.

A âncora do datum é o ponto `RN1 25892 REGUA SGB`, que cai a cerca de 6 m da ficha da estação ANA/SGB 86472600 (−29,1781 / −51,7322).

Cotas estão em metros (ortométricas do levantamento). No KML a altitude vai como `absolute`.

## Como abrir no ArcGIS Pro

1. Baixe `Pts-Transladados_ArcGIS.zip` e descompacte.
2. **Shapefile (recomendado):** Map → Add Data → `shapefile/Pts-Transladados.shp`.
3. **KML:** Map → Add Data → `Pts-Transladados.kml`, ou Geoprocessing → *KML To Layer*.
4. Simbologia: use o campo `TIPO` (`BASE`, `RN`, `H`, `V`). Rótulo: `NOME`. Cota: `COTA`.

## Como abrir no ArcMap

1. Add Data → `Pts-Transladados.shp`.
2. Para o KML: ArcToolbox → Conversion Tools → From KML → *KML To Layer*.

## Campos

| Campo | Conteúdo |
|---|---|
| NOME | identificador do ponto |
| TIPO | BASE, RN, H ou V |
| NORTE | norte UTM (m) |
| ESTE | este UTM (m) |
| COTA | altitude (m) |
| LAT / LON | WGS84 (também no shapefile, para conferência) |

## Regenerar

```bash
python codigo_python/11_levantamento_campo/txt_para_kml_shapefile.py
```

Dependências: `pyproj`, `pyshp`.
