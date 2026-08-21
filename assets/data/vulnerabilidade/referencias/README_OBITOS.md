# Óbitos — camada de referência

## Fonte e conversão

- Fonte fornecida: `OBITOS/obitos.shp` (acompanhado por `.dbf`, `.shx`, `.prj` e `.cpg`).
- O pacote original pode ser baixado em `obitos_source.zip`.
- CRS de origem: EPSG:4674, SIRGAS 2000 geográfico.
- Publicação no mapa: `obitos.geojson`, longitude/latitude em EPSG:4326 conforme RFC 7946.
- O pacote preserva os registros válidos e as coordenadas repetidas; não faz deduplicação.

## Cobertura observada

- 185 registros no arquivo de origem.
- 179 registros com coordenadas válidas, desenhados no mapa.
- 6 registros sem coordenadas; eles permanecem no total de origem e não são desenhados.
- 73 pontos dentro da bacia publicada e 106 fora do recorte da bacia.

## Limitações

O arquivo não possui data do óbito, causa, município, pessoa ou identificador nominal. Assim,
esta camada é somente uma referência espacial dos registros recebidos: não é uma taxa de mortalidade,
série temporal, contagem por município ou mapa de causa de morte. Não é seguro inferir concentração,
risco ou tendência sem esses atributos e sem a documentação epidemiológica correspondente.
