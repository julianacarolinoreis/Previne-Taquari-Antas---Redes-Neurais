# PREVINE Taquari-Antas - Redes Neurais

Site publico e interativo com os resultados das redes neurais de previsao de nivel para Santa Tereza e Muçum, na bacia Taquari-Antas.

## O que ha no site

- Painel de modelos auditaveis de 2h, 4h, 8h e 12h (contagem dinamica no `index.html`).
- Ranking por familia, horizonte, montagem alternativa/convencional e metricas de desempenho.
- Graficos de persistencia, erro em centimetros, equilibrio validacao/teste e inputs mais usados.
- Tabela filtravel com metricas rastreaveis por modelo.
- Catalogo vivo de pesquisas em `pesquisas.html` e agenda estruturada de avanco em `pesquisas/agenda-avanco.html`.
- Sala de decisao V002 em `pesquisas/estudo-caso-resposta-santa-tereza.html`, com briefing, checklist, contingencias, metricas de exercicio e exportacao local.

## Robo ao vivo (fonte canonica)

- **Santa Tereza:** `previne/robo/gerar_previsao_ao_vivo.py` via `.github/workflows/previsao-ao-vivo.yml` (cron a cada **5 min**).
- **Muçum:** `codigo_python/01_previsao_ao_vivo/gerar_previsao_ao_vivo_mucum.py` via `.github/workflows/previsao-ao-vivo-mucum.yml` (cron a cada **5 min**).
- O arquivo legado `codigo_python/01_previsao_ao_vivo/gerar_previsao_ao_vivo.py` **nao** e o robo de producao; nao editar para operacao.

## Organizacao

Este repositorio e a fonte oficial do painel PREVINE. Os dados e scripts usados
pela publicacao devem permanecer aqui, sem sincronizacao com repositorios de
outros projetos.

## Publicacao

Para publicar pelo GitHub Pages:

1. Abra `Settings -> Pages` neste repositorio.
2. Em `Build and deployment`, selecione `Deploy from a branch`.
3. Escolha a branch `main` e a pasta `/(root)`.
4. Salve. O site ficara disponivel no endereco informado pelo GitHub.

## Dados auditaveis

As planilhas auditaveis completas ficam fora do HTML para nao deixar o site pesado demais. O painel ja contem as metricas consolidadas; os dados ponto a ponto das planilhas podem ser adicionados depois em arquivos `data/` para graficos de observado versus previsto e subidas de eventos.

## Agenda de avanço

`assets/data/agenda_pesquisas.json` é o registro estruturado das cinco linhas prioritárias de pesquisa. Cada linha registra pergunta, impacto humano, evidência atual, dados necessários, método, métricas, fontes e gate de avanço. A agenda separa duas frentes: ciência da previsão e pessoas/resposta.

Os estados `pesquisa`, `validar`, `completar` e `exercitar` descrevem maturidade do trabalho; nenhum deles equivale a alerta oficial, rota liberada, abrigo confirmado ou despacho. A promoção operacional permanece bloqueada até validação independente, exercícios seguros, revisão institucional e autorização da autoridade competente.

## Exercício de resposta V002

O contrato `assets/data/estudo_caso_resposta_v002.json` mantém a separação entre cenário didático, snapshot da RNA, grade espacial preliminar e dados de resposta ainda desconhecidos. A sala registra decisões, confirmação de rota, contagens agregadas, capacidade do abrigo, contingências e falhas críticas sem substituir sistemas oficiais.

Estados `UNKNOWN` e `STALE` devem bloquear a ação. A grade de 30 m e os corredores são sintéticos e não validados para ruas, pontes, declividades ou acessibilidade. O horizonte de 8h é experimental/sombra; não é alerta oficial, ordem de evacuação, navegação, despacho ou alocação de recursos.
