# Painel de frentes PREVINE

Dashboard estática e interativa para acompanhar frentes de pesquisa, documentos, MATLAB, código, publicação e pendências de fechamento.

Página pública desta versão: <https://julianacarolinoreis.github.io/Previne-Taquari-Antas---Redes-Neurais/inventario/>.

Esta rodada reorganiza a primeira leitura para mostrar o próximo fechamento sugerido antes do inventário, torna o tablist navegável por teclado, anuncia o contador de filtros, oferece limpeza explícita, torna as barras proporcionais ao total de frentes e inclui um glossário técnico. A página continua sendo uma camada pública sanitizada e somente leitura; ela ainda não é o registro privado canônico nem um sincronizador automático.

O resumo público sanitizado das cinco prioridades desta rodada está em `closure-status.json`. Os dossiês completos de auditoria permanecem locais e privados.

## O que este snapshot é

Este repositório contém uma fotografia sanitizada em `data.js` e a interface em `index.html`. A página permite filtrar as frentes por tema, estado, horizonte e texto. Ela foi montada a partir de quatro camadas de evidência:

- conversas e tarefas acessíveis pelo Codex;
- inventários, logs e artefatos locais em raízes de trabalho PREVINE;
- buscas de metadados no Google Drive;
- repositórios e publicações acessíveis no GitHub.

Os números têm escopos diferentes e não devem ser somados. Em particular:

- uma tarefa/conversa não é uma pesquisa única;
- um arquivo `.mat` não é uma execução MATLAB;
- uma fila com log de conclusão não é um modelo reconciliado ou promovido;
- uma página publicada não é uma aprovação científica, operacional ou institucional.

## Como atualizar com segurança

1. Refaça a leitura das fontes e anote a data do snapshot.
2. Separe contagem física, contagem deduplicada, execução, publicação e aprovação.
3. Atualize somente os agregados sanitizados em `data.js`.
4. Não copie para este repositório textos privados do Drive, recibos, IDs, e-mail, caminhos pessoais ou credenciais.
5. Abra a página localmente e confira a visão geral, filtros, navegação por teclado, largura móvel e seção de evidências antes de publicar.

Para uma inspeção local simples:

```powershell
py -3 -m http.server 4173 --bind 127.0.0.1
```

Depois abra `http://127.0.0.1:4173/dashboard/` a partir da pasta que contém `dashboard/`, ou sirva diretamente a pasta `dashboard`.

## Limites desta versão

O painel não é um sincronizador em tempo real e não representa uma exportação integral da conta Google, do histórico do ChatGPT ou de todos os arquivos do computador. A cobertura é deliberadamente auditável: raízes de trabalho foram incluídas; pastas do sistema, `AppData`, credenciais e documentos privados não foram publicados.

As frentes bloqueadas preservam o motivo do bloqueio. Uma ausência de aprovação não foi convertida em “concluído” apenas porque há arquivos ou uma página pública.

