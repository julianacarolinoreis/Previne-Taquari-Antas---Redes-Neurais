# PREVINE — dados combinados de vulnerabilidade social

Este diretório é a documentação técnica e de produto do pacote publicado em
`assets/data/vulnerabilidade/downloads/`. Os CSV, GeoJSON, Shapefile e GeoPackage
são dados estáticos, reproduzíveis e próprios para consulta no QGIS, ArcGIS Pro
ou em scripts. A interface web é uma forma de exploração; os arquivos e o
`catalogo.json` são a referência para auditoria.

## O que o pacote responde

O pacote descreve a distribuição espacial de população, domicílios e grupos
demográficos no recorte da bacia Taquari–Antas. Ele também agrega, com rótulo de
limitação, pontos cadastrados no IEDE-RS, o Indicador de Capacidade Municipal
(ICM) e a setorização de risco do SGB disponível para Santa Tereza.

Ele **não é** um alerta, uma previsão, um inventário completo de serviços ou um
mapa regional contínuo de perigo. Vulnerabilidade social, capacidade municipal,
perigo e risco devem permanecer como camadas separadas até existir uma camada de
perigo hidrológico regional validada e um método de cruzamento documentado.

## Escopos e unidades

| Camada | Unidade e cobertura | Como interpretar |
|---|---|---|
| `municipios_combinados` | 118 municípios que intersectam a bacia | Os indicadores são do município inteiro, inclusive quando somente uma parte está na bacia. Use `pct_na_bacia` e `pop_bacia` para conhecer a parcela espacial do recorte. |
| `setores_na_bacia_combinados` | 3.283 setores cujo ponto representativo está dentro do limite adotado | É o recorte recomendado para somas “dentro da bacia”. `na_bacia=1` identifica a seleção; `area_pct_bacia` mostra a fração geométrica que cruza o limite. |
| `setores_municipios_intersectantes_combinados` | 5.053 setores dos municípios que tocam a bacia, com geometria no GeoJSON/GPKG | Inclui setores dentro e fora; filtre `na_bacia=1` para reproduzir o recorte da bacia. `area_pct_bacia` permite auditar unidades de borda. |
| `grade_200m_na_bacia` | 36.723 células de aproximadamente 200 m dentro da bacia | A grade estatística oferece visualização regular; ela não substitui o setor censitário e possui apenas população e domicílios do produto IBGE. `area_pct_bacia` registra a fração geométrica. |
| `servicos/*` | Pontos publicados nas camadas consultadas do IEDE-RS | Cadastro parcial. Ausência de ponto significa “não localizado nesta camada”, não inexistência do equipamento. |
| `perigo_setores_risco_sgb_santa_tereza` | 37 polígonos oficiais em Santa Tereza | Setorização de risco do SGB; não é mancha contínua de inundação nem pode ser extrapolada para os demais municípios. |

O recorte setorial contém 1.328.737 habitantes segundo os agregados usados na
geração atual. O valor não deve ser comparado diretamente com a soma dos
municípios inteiros, que inclui população fora do limite da bacia.

## Camadas de referência adicionadas

- `referencias/resiliencia_municipios.json`: IRM V1 municipal do Observatório da Resiliência RS. A fonte contém sete indicadores e cobertura parcial; `unknown` significa sem correspondência, não baixo desempenho.
- `referencias/open_buildings_tiles.geojson`: índice leve das células Open Buildings v3 relevantes para a área. Cada célula aponta para o CSV.gz externo de footprints; esses arquivos são muito grandes e não são carregados automaticamente.
- Estradas DAER/RS: camada online consultada por janela visível no serviço oficial do DAER/IEDE. Ela mostra trechos registrados, não tempo de viagem, acessibilidade ou condição operacional.
- `referencias/obitos.geojson`: 179 pontos válidos derivados do arquivo fornecido `OBITOS/obitos.shp`; 6 registros sem coordenadas permanecem nos metadados. O arquivo não contém data, causa, município ou identificação nominal, portanto a camada é somente referência espacial, não taxa ou série temporal.

## Fontes e datas de referência

- **IBGE — Censo Demográfico 2022**, Agregados por Setores Censitários: população,
  domicílios, demografia, cor ou raça, água e esgoto. A renda usa a publicação
  separada de rendimento do responsável. Malhas de setores e municípios são as
  malhas 2022 do IBGE.
- **SEMA/DRH/IEDE-RS**: limite da bacia utilizado no recorte espacial e pontos
  públicos consultados. O arquivo original e a consulta estão em
  `brutos/FONTES.md` e `assets/data/servicos/FONTES.md`.
- **MIDR/Secretaria Nacional de Proteção e Defesa Civil — ICM**: classe e
  pontuação municipal. Esta publicação usa a **Base Completa do ICM, atualizada
  em 13/08/2026** (`base_completa_icm_082026.xlsx`); a data, a versão e o link
  oficial também ficam registrados em `assets/data/icm_municipios.json` e no
  `catalogo.json`.
- **SGB/CPRM**: setores de risco de Santa Tereza, levantamento de campo de 2025;
  proveniência e limitações estão em `perigo/README.md`.

O CRS de todos os produtos vetoriais de distribuição é **WGS 84 / EPSG:4326**.
Em GeoJSON, as coordenadas seguem longitude, latitude (RFC 7946). Para medir
área ou distância, reprojete para um CRS métrico adequado ao projeto antes do
cálculo.

## Regras estatísticas que precisam acompanhar qualquer uso

1. `pop`, `dom`, `mulheres`, faixas etárias e cor/raça são contagens no grão
   indicado pelo arquivo. Não some a camada municipal com a camada setorial.
2. `dom_agua` e `dom_esgoto` têm como denominador oficial `dom_ocupados`, a
   variável V00001 (domicílios particulares permanentes ocupados). Não use
   `dom` como denominador sem declarar a mudança.
3. `renda_resp` é rendimento nominal médio mensal das pessoas responsáveis
   (V06004, referência 2022), não renda atual nem mediana.
4. Os campos `sigilo_<campo>=1` representam X omitido pelo IBGE. O valor fica
   nulo e **não pode ser transformado em zero**. A geração atual registra 2.420
   setores com pelo menos um campo suprimido.
5. Campos `mun_*` em setores e células são contexto municipal herdado. Eles não
   são medições do setor/célula e não devem entrar em uma estatística setorial.
6. `mun_*_iede` e indicadores `svc_*` são pontos publicados / 10 mil habitantes
   quando a população municipal está disponível. O denominador e a cobertura do
   cadastro devem aparecer na legenda ou no relatório.
7. O ICM é municipal. Quando copiado para uma camada de setores ou grade, é uma
   referência do município, nunca uma classificação da unidade menor.
8. Cada indicador publicado traz `<campo>_n_validos`, `<campo>_n_total` e
   `<campo>_completude`. No município, o denominador do agregado inteiro é o
   número de setores do município; no recorte `_bacia`, é `n_setores_bacia`.
   Em setor/grade, o denominador da feição é 1. Use esses campos antes de
   ordenar, somar ou comparar valores parcialmente conhecidos.
9. `status_borda_bacia`, `area_pct_bacia`, `metodo_area_bacia` e
   `metodo_na_bacia` acompanham cada unidade. `status_borda_bacia=parcial`
   indica interseção geométrica incompleta; `na_bacia=1` continua sendo definido
   pelo ponto representativo e não pela fração de área.
10. Contagens de serviços ausentes no cadastro são `null`, com campo
    `<tipo>_status=unknown`; não são zeros observados. A cobertura por tipo está
    em `contagem_municipios.json` e no `catalogo.json`.
11. As geometrias distribuídas para web/GIS são generalizadas para desempenho
    (bacia ~100 m, municípios ~120 m, setores ~15 m). `na_bacia`,
    `area_pct_bacia` e os pontos representativos publicados são os campos de
    autoridade do recorte calculado antes da generalização; não os recalcule
    usando apenas os polígonos simplificados. Para medições de área/topologia,
    use o pacote de análise e registre a tolerância, CRS e versão.

## Reprodutibilidade e controle de versão

O arquivo `downloads/catalogo.json` registra contagens, CRS, advertências,
classificações e o hash SHA-256 das entradas. Arquivos gerados não devem ser
editados manualmente. Para atualizar:

```powershell
python codigo_python/06_vulnerabilidade/gerar_downloads_combinados.py
python -m json.tool assets/data/vulnerabilidade/downloads/catalogo.json > $null
```

Depois, conferir no catálogo: número de municípios/setores/células, população
setorial, cobertura de serviços, cobertura do ICM, quantidade de campos
suprimidos e os três CRS. A publicação só deve ocorrer após revisar mudanças de
fonte, data, cobertura, denominador e hash.

## Citação pronta

> PREVINE. **Dados combinados de vulnerabilidade social — bacia Taquari–Antas**.
> Censo Demográfico IBGE 2022; limite SEMA/DRH; cadastros de serviços IEDE-RS;
> Indicador de Capacidade Municipal (MIDR); setores de risco SGB/Santa Tereza
> (levantamento 2025). Versão e hash de entrada conforme `downloads/catalogo.json`.
> Disponível em: `<URL-base-do-repositório>/assets/data/vulnerabilidade/`.
> Acesso em: `<AAAA-MM-DD>`.

Para uma citação arquivável, copie também `gerado_em_utc` e
`hash_entradas_sha256` do `catalogo.json` consultado. Não cite um ranking ou uma
cor sem informar o indicador, o grão, a escala de classificação e a data de
referência.

## Próximas atualizações recomendadas

- manter uma tabela de versões com data de captura, fonte, cobertura, CRS,
  denominador e quebra metodológica;
- publicar séries comparáveis somente quando a definição da variável e a malha
  forem compatíveis (por exemplo, 2010–2022 com nota de comparabilidade);
- acrescentar camada regional de perigo com fonte e validação próprias antes de
  produzir cenários de pessoas, domicílios ou serviços atingidos;
- registrar no relatório de triagem a regra de seleção, pesos, filtros e
  unidades, evitando transformar uma triagem operacional em “nota de risco”.

O inventário de camadas, o dicionário de campos, os estilos recomendados e a
especificação de ficha/triagem/cenários estão nos arquivos deste diretório.
