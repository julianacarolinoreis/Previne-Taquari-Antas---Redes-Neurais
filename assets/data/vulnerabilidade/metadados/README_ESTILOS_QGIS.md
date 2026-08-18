# Como usar os estilos QGIS incluídos

Os arquivos `.qml` são estilos simples de ponto de partida para camadas do
GeoPackage. Eles não alteram os dados e não incluem a legenda de fonte/data da
composição final.

## Estilos

- `estilo_icm_municipios.qml`: camada `municipios_combinados`, campo
  `mun_icm_faixa`, quatro classes A–D.
- `estilo_risco_sgb.qml`: camada
  `perigo_setores_risco_sgb_santa_tereza`, campo `grau_risco`, quatro classes
  de risco do SGB.

## Aplicação no QGIS

1. Extraia `geopackage_arcgis_qgis.zip` e abra
   `previne_vulnerabilidade.gpkg`.
2. Clique com o botão direito na camada correspondente → **Propriedades →
   Simbologia → Estilo → Carregar estilo…**.
3. Selecione o `.qml` deste diretório. Confirme que o campo de classificação
   existe; o Shapefile pode ter o nome abreviado em `campos.csv`.
4. Reprojete o projeto para EPSG:31982 antes de medir área ou distância.
5. Adicione à legenda a fonte, a data e a cobertura indicadas em
   `INVENTARIO_CAMADAS.csv`. Para o SGB, mantenha a nota “somente Santa Tereza,
   37 setores; ausência fora da cobertura não significa ausência de perigo”.

Para indicadores sociais, use `ESTILOS_QGIS_ARCGIS.md`: a rampa roxa e os
quantis precisam ser aplicados ao campo selecionado (por exemplo, `pop` ou
`mulheres`) e ao grão correto. Não reutilize o estilo do ICM para setores como
se fosse uma classificação setorial.
