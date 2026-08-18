# Estilos recomendados para QGIS e ArcGIS Pro

As sugestões abaixo são um ponto de partida para mapas de trabalho. O estilo
não transforma vulnerabilidade em risco e não substitui a leitura do dicionário
de campos. Sempre mantenha fonte, data, unidade e cobertura na composição do
mapa.

## Preparação do projeto

1. Prefira `geopackage_arcgis_qgis.zip` para preservar os nomes completos dos
   campos. Use `shapefiles_arcgis_qgis.zip` somente quando a compatibilidade do
   formato for necessária e consulte o `campos.csv` para os nomes abreviados.
2. Os arquivos distribuídos estão em WGS 84 / EPSG:4326. Para área, distância,
   densidade espacial ou seleção por metros, reprojete o projeto e as camadas
   para SIRGAS 2000 / UTM 22S (EPSG:31982), que cobre o recorte principal. Se o
   estudo se estender para oeste além da zona 22S, avalie EPSG:31981 ou um CRS
   regional equivalente antes de medir.
3. Mantenha a camada `bacia_taquari_antas` abaixo das camadas temáticas e não a
   trate como mancha de inundação.

## Vulnerabilidade social e exposição

Para `municipios_combinados`, `setores_na_bacia_combinados` e
`grade_200m_na_bacia` use uma rampa sequencial de cinco classes:

| Classe | Cor | Leitura |
|---|---|---|
| 1 | `#F3EEF6` | menor valor dentro do universo escolhido |
| 2 | `#D9C7E3` | faixa baixa |
| 3 | `#B394C9` | faixa intermediária |
| 4 | `#8759A8` | faixa alta |
| 5 | `#4D2A6E` | maior valor dentro do universo escolhido |

No QGIS, use **Simbologia → Graduado**, método Quantil, cinco classes, e
declare no título se a classificação é “quantis da bacia” ou “quantis da área
selecionada”. No ArcGIS Pro, use **Symbology → Graduated Colors**, método
Quantile e cinco classes. A legenda deve exibir a unidade, por exemplo
`pessoas`, `pessoas / população (%)`, `R$ nominais por mês` ou `domicílios /
domicílios ocupados (%)`.

Quando o indicador tiver zeros estruturais, reserve uma classe `zero` antes dos
quantis positivos. Para campos sujeitos a supressão, use cinza `#9AA3A0` com a
legenda `dado não divulgado pelo IBGE`; nunca recodifique nulo para zero.

Filtros úteis:

```text
setores_na_bacia_combinados:  "na_bacia" = 1
setor sem dado do indicador:   "sigilo_mulheres" = 1  (troque o campo)
municipio com parcela na bacia: "pop_bacia" > 0
```

Não compare visualmente o valor municipal inteiro com o setor dentro da bacia
sem uma indicação clara do grão. A camada municipal de borda pode conter
população fora do limite adotado.

## Capacidade municipal (ICM)

O ICM é categórico e municipal. Use **Simbologia → Categorizado** com o campo
`mun_icm_faixa` (camada municipal) ou `mun_icm_faixa` herdado apenas como
contexto em setores/grade. Cores sugeridas:

| Faixa | Cor | Texto obrigatório |
|---|---|---|
| A | `#2E7D32` | alta capacidade |
| B | `#C3D92C` | intermediária avançada |
| C | `#E8730C` | intermediária inicial |
| D | `#C0392B` | inicial |

Inclua uma legenda textual “A = mais preparo para gestão de risco” e, quando o
mapa estiver no nível de setor, a nota “ICM é municipal; a cor foi herdada do
município”. A cor sozinha não deve ser a única codificação: inclua o rótulo A–D
e a pontuação na tabela ou no rótulo.

## Setorização de risco do SGB

Para `perigo_setores_risco_sgb_santa_tereza`, use contorno escuro e preenchimento
por `grau_risco`, com classes `Alto` em `#F59E0B` e `Muito alto` em `#B91C1C`.
Mantenha a camada acima da base, com opacidade aproximada de 45%, e adicione
uma etiqueta fixa na composição:

> SGB — setorização oficial de risco, somente Santa Tereza, 37 setores,
> levantamento 2025. Ausência de polígono fora desta cobertura não significa
> ausência de perigo.

Não use branco/verde para áreas sem polígono e não desenhe uma “mancha” contínua
por interpolação. O produto preserva `grau_vulne`, `grau_risco`, tipologias e
recomendações do SGB sem reclassificação.

## Pontos de serviços e abrigos

Use símbolos pontuais distintos e acessíveis: UBS em azul `#2563EB`, hospitais
em vermelho `#B91C1C`, escolas em azul escuro `#1D4ED8`, bombeiros em laranja
`#EA580C` e abrigos/pontos de encontro em verde `#0F6B4A`. O rótulo deve conter
nome, município e fonte. Na legenda escreva `pontos cadastrados no IEDE-RS`,
nunca apenas `serviços`.

Para densidade `svc_*`, informe no título `pontos publicados / 10 mil habitantes`
e a data de captura. Um município sem ponto deve aparecer como `sem ponto
publicado nesta camada`, não como zero serviços.

## Composição e exportação

- Inclua título, indicador, grão, unidade, período de referência, fonte, CRS,
  data de download e cobertura espacial.
- Mantenha vulnerabilidade social, ICM, perigo e serviços em grupos de camadas
  separados. Um mapa com duas camadas não é, por si só, um mapa de risco.
- Use escala gráfica e seta norte somente quando a escala do mapa justificar.
- Para relatórios, exporte uma versão com legenda completa e uma ficha textual
  que registre filtros e classificação. Para publicação web, mantenha o link do
  catálogo e o hash do pacote.
- Ao usar impressão, prefira uma prancha por indicador. Evite colocar tabela de
  dezenas de linhas em uma página cartográfica; exporte a tabela como anexo.

## Equivalência entre formatos

O GeoPackage mantém nomes de campo completos e é o formato recomendado para
QGIS/ArcGIS Pro. O Shapefile limita nomes a dez caracteres e pode converter
tipos booleanos/estruturados em texto. Em qualquer conversão, preserve:

- `sigilo_<campo>` e nulos;
- `na_bacia` e `pct_na_bacia`;
- `cod_mun`, `setor`, `id_grade` e `num_setor`;
- data de referência e fonte no projeto, não apenas no nome da camada.
