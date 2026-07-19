# Serviços públicos — bacia Taquari-Antas (IEDE-RS)

Robô que baixa do **IEDE-RS** as camadas de **hospitais, escolas, bombeiros e UBS**,
recorta para os municípios da bacia e publica os geojson que o mapa lê — base do
futuro **mapa de densidade de serviços públicos**.

## Como rodar (sem programar nada)
GitHub → aba **Actions** → workflow **"Serviços públicos — dados IEDE"** →
botão **Run workflow**. Também roda sozinho todo dia 4 do mês.

## O que produz (`assets/data/servicos/`)
| Arquivo | Conteúdo |
|---|---|
| `hospitais.geojson` etc. | pontos na bacia com nome e município |
| `contagem_municipios.json` | nº de cada serviço por município |
| `FONTES.md` | URL oficial de cada camada usada |

## Se falhar
- O log lista os **serviços candidatos** encontrados no catálogo do IEDE por tipo —
  se o certo não estiver entre eles, ajustar os regex em `TIPOS` (`baixar_servicos.py`).
- Um tipo ausente no IEDE vira **AVISO** (o robô segue com os demais); a alternativa
  é fonte federal (CNES para saúde, INEP para escolas) na iteração seguinte.
- Contagens implausíveis (faixas em `FAIXA_BACIA`) param o robô antes de publicar.
