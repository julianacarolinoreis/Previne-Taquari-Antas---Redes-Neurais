# Vulnerabilidade social — bacia Taquari-Antas (Censo IBGE 2022)

Robô que baixa os **dados brutos do IBGE**, recorta para os municípios que
intersectam a **bacia do Taquari-Antas** e publica os arquivos prontos que o
mapa de vulnerabilidade do site lê.

## Como rodar (sem programar nada)
GitHub → aba **Actions** → workflow **"Vulnerabilidade — dados IBGE"** →
botão **Run workflow**. Ele também roda sozinho todo dia 3 do mês.

## O que produz (`assets/data/vulnerabilidade/`)
| Arquivo | Conteúdo |
|---|---|
| `municipios.geojson` | municípios da bacia com indicadores agregados |
| `setores/<cod>.geojson` | setores censitários do município (simplificados) |
| `grade/<cod>.geojson` | grade estatística de 200 m, com `id_grade` oficial |
| `indicadores_municipios.json` | tabela para ranking/busca |
| `brutos/*.csv` + `FONTES.md` | recorte auditável das tabelas do IBGE + URLs oficiais |
| `downloads/dados_combinados_taquari_antas.zip` | CSV + GeoJSON combinados, catálogo, serviços e fontes |
| `downloads/shapefiles_arcgis_qgis.zip` | camadas Shapefile compatíveis com ArcGIS/QGIS |
| `downloads/geopackage_arcgis_qgis.zip` | um GeoPackage com campos completos para QGIS/ArcGIS Pro |
| `perigo/setores_risco_sgb_santa_tereza.geojson` | 37 setores oficiais de risco do SGB em Santa Tereza (2025) |

## Indicadores por setor e por município
população total · mulheres · crianças **0–4** · crianças **5–9** ·
idosos **60–69** · idosos **70+** · indígenas · pretos e pardos ·
domicílios totais · domicílios particulares permanentes ocupados · água por
rede geral · esgoto por rede geral · renda do responsável · densidade (hab/km²)

Água e esgoto têm como universo os domicílios particulares permanentes
ocupados e usam a variável oficial **V00001** como denominador. Valores `X`
omitidos por sigilo estatístico são publicados como nulos, acompanhados de
`sigilo_<campo>=1`; nunca devem ser interpretados como zero.

O perigo é mantido separado da vulnerabilidade social. Para atualizar e validar
o snapshot do SGB de Santa Tereza, rode
`python codigo_python/06_vulnerabilidade/baixar_setores_risco_sgb_santa_tereza.py`.

## Se falhar
- O passo de download imprime o **dicionário oficial** das variáveis (V010xx/V013xx);
  se um código de coluna do IBGE mudar, o log mostra o cabeçalho real → ajustar
  `COLMAP` em `preparar_vulnerabilidade.py`.
- O robô **recusa publicar dados implausíveis**: área da bacia fora de 20–33 mil km²
  ou proporções de mulheres/crianças/idosos/indígenas fora do esperado param o robô.
- Se o limite da bacia não vier do IEDE-RS, rode de novo informando
  `bacia_url` (campo do botão Run workflow) com um geojson/shapefile da bacia.
