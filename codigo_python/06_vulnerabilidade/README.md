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
| `indicadores_municipios.json` | tabela para ranking/busca |
| `brutos/*.csv` + `FONTES.md` | recorte auditável das tabelas do IBGE + URLs oficiais |

## Indicadores por setor e por município
população total · mulheres · crianças **0–4** · crianças **5–9** ·
idosos **60–69** · idosos **70+** · indígenas · domicílios · densidade (hab/km²)

## Se falhar
- O log imprime o **cabeçalho real** das tabelas quando um código de coluna do
  IBGE muda → ajustar `COLMAP` em `preparar_vulnerabilidade.py`.
- Se o limite da bacia não vier do IEDE-RS, rode de novo informando
  `bacia_url` (campo do botão Run workflow) com um geojson/shapefile da bacia.
