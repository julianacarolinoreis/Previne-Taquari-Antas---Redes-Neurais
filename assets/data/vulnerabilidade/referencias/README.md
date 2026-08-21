# Camadas de referência do mapa

Gerado em `2026-08-19T20:53:18Z`.

## Índice municipal de resiliência

- Fonte: [Observatório da Resiliência RS](https://observatoriodaresiliencia.org/indicadores/) / arquivos P1–P7 no Azure Blob (`https://plancon.blob.core.windows.net/indicadores`).
- Os sete semáforos são municipais; a consolidação segue a regra publicada no próprio visualizador.
- `irm_score_0a100` é uma transformação auxiliar da média 1–3 para facilitar leitura; não é probabilidade, risco ou alerta.
- Municípios sem os indicadores no snapshot permanecem `irm_status=unknown`; eles não foram convertidos em vermelho.

## Estradas

A interface consulta sob demanda a camada oficial **DAER/Rodovias_RS**, em EPSG:4674, via ArcGIS REST/GeoJSON. A consulta é limitada à janela visível e só é habilitada em zoom local para não sobrecarregar o serviço.

## Open Buildings

`open_buildings_tiles.geojson` é o catálogo das células S2 que cobrem a área do mapa. Ele traz contagem e URL de cada célula; os footprints individuais são baixados sob demanda pelo usuário a partir do Google Research (cada célula pode ter centenas de MB ou mais) e não são copiados para o GitHub Pages. O dataset v3 deriva polígonos de imagens de satélite e não identifica uso, endereço ou ocupação do prédio.

## Óbitos

`obitos.geojson` é uma conversão para GeoJSON dos pontos válidos fornecidos em `OBITOS/obitos.shp`.
O arquivo de origem tem 185 registros: 179 coordenadas válidas são desenhadas e 6 registros sem
coordenadas permanecem contabilizados nos metadados, mas não podem aparecer no mapa. A fonte está em
EPSG:4674 (SIRGAS 2000 geográfico); o GeoJSON é publicado em EPSG:4326/RFC 7946. Há 73 pontos
dentro da bacia publicada e 106 fora dela; a camada mantém os pontos fora do recorte para não alterar
o arquivo fornecido. Os registros não trazem data, causa, município ou identificação nominal, portanto
a camada é apenas uma referência espacial e não permite inferir taxa, série temporal ou causa de morte.
