# PREVINE Taquari-Antas - Redes Neurais

Site publico e interativo com os resultados das redes neurais de previsao de nivel para Santa Tereza, na bacia Taquari-Antas.

## O que ha no site

- Painel com 239 modelos auditaveis de 2h, 4h, 8h e 12h.
- Ranking por familia, horizonte, montagem alternativa/convencional e metricas de desempenho.
- Graficos de persistencia, erro em centimetros, equilibrio validacao/teste e inputs mais usados.
- Tabela filtravel com metricas rastreaveis por modelo.

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
