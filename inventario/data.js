window.INVENTORY = {
  meta: {
    title: "Painel de frentes PREVINE",
    subtitle: "Inventário auditável de pesquisas, código, MATLAB, documentos e publicações",
    snapshotDate: "2026-09-19",
    version: "snapshot-2026-09-19-v1",
    publicSafe: true,
    note: "A página é uma fotografia sanitizada. Ela não sincroniza automaticamente o computador, o Drive ou o histórico do Codex.",
    githubRepo: "julianacarolinoreis/Previne-taquari"
  },
  kpis: [
    { id: "fronts", value: "20", label: "frentes catalogadas", note: "unidades de trabalho agrupadas por tema e evidência" },
    { id: "codex", value: "110", label: "tarefas Codex", note: "39 visíveis + 71 arquivadas no inventário acessível" },
    { id: "chatgpt", value: "18", label: "conversas ChatGPT visíveis", note: "não representa todo o histórico da conta" },
    { id: "mat", value: "5.914", label: "arquivos .mat físicos", note: "PREVINE + worktrees; arquivos, não execuções" },
    { id: "queues", value: "25", label: "pastas de fila concluídas", note: "marcador explícito em log: 23 Muçum + 2 Santa Tereza" },
    { id: "hours", value: "16,37 h", label: "horas documentadas", note: "uma fila de 24 itens; não é o total histórico" }
  ],
  statusLabels: {
    concluido: "Concluído como entrega",
    publicado: "Publicado com ressalvas",
    auditado: "Auditado",
    quase: "Quase no acabamento",
    andamento: "Em andamento",
    bloqueado: "Bloqueado / aprovação pendente"
  },
  statusDescriptions: {
    concluido: "Existe uma entrega verificável. Isso não implica aprovação científica ou operação oficial.",
    publicado: "Há uma cópia pública ou página publicada, mas a publicação não substitui validação.",
    auditado: "A inspeção foi feita e deixou evidências; problemas ou limites podem permanecer.",
    quase: "A maior parte do material existe, porém há uma pendência objetiva de QA, reconciliação ou aprovação.",
    andamento: "Há trabalho material e próximo passo claro, mas o ciclo ainda não está fechado.",
    bloqueado: "O fechamento depende de evidência ou decisão ainda ausente; não é uma estimativa de atraso."
  },
  fronts: [
    {
      id: "relatorio-integrado",
      title: "Relatório integrado de frentes",
      theme: "Pesquisa e método",
      status: "concluido",
      confidence: "alta",
      tags: ["relatório", "agentes", "pesquisa"],
      horizon: [],
      evidence: "Relatório renderizado com experimento, refinamentos, erros e limites registrados.",
      next: "Se virar artigo ou documento institucional, fazer apenas a revisão editorial final e nova QA.",
      boundary: "Entrega concluída; não é aprovação operacional nem substituição oficial de modelo."
    },
    {
      id: "osm",
      title: "Correção OSM no site PREVINE",
      theme: "Site público",
      status: "publicado",
      confidence: "alta",
      tags: ["site", "OSM", "GitHub Pages"],
      horizon: [],
      evidence: "Falha reproduzida, causa identificada, correção publicada e página pública verificada.",
      next: "Monitorar regressão quando o mapa ou a política de referrer/CSP mudar.",
      boundary: "Publicação confirmada; isso não certifica os demais mapas ou dados do site."
    },
    {
      id: "catalogo",
      title: "Catálogo de pesquisas PREVINE",
      theme: "Site público",
      status: "auditado",
      confidence: "alta",
      tags: ["catálogo", "pesquisas", "site"],
      horizon: [],
      evidence: "Snapshot auditado com 55 entradas, 5 páginas e HTTP 200; outro scan encontrou 60 entradas.",
      next: "Reconciliar o número 55 versus 60 e registrar a versão canônica do catálogo.",
      boundary: "Os dois números são snapshots diferentes; não devem ser somados."
    },
    {
      id: "rna-stz",
      title: "RNA Santa Tereza — 2 h, 4 h e 8 h",
      theme: "RNA e MATLAB",
      status: "quase",
      confidence: "média",
      tags: ["RNA", "MATLAB", "Santa Tereza"],
      horizon: [2, 4, 8],
      evidence: "Manuscrito e arquivos no Drive; métricas selecionadas e auditoria do site. A reprodução MATLAB ponta a ponta não foi fechada.",
      next: "Congelar coorte, alvo, partição causal, entradas disponíveis ex-ante e baseline antes de publicar desempenho.",
      boundary: "Resultados experimentais; não são alerta nem promoção operacional."
    },
    {
      id: "rna-mucum",
      title: "RNA Muçum — filas Q57 a Q82",
      theme: "RNA e MATLAB",
      status: "andamento",
      confidence: "média",
      tags: ["RNA", "MATLAB", "Muçum", "eventos"],
      horizon: [2, 4, 8, 12],
      evidence: "23 pastas de fila Muçum com marcador de conclusão; Q82 aparece preparado sem MAT e Q77 tem apenas parte verificada.",
      next: "Reconciliar manifesto, MAT, XLSX, CSV, logs, partições e gate de qualidade por fila.",
      boundary: "Fila concluída não equivale a modelo reconciliado, aprovado ou live."
    },
    {
      id: "audit-matlab",
      title: "Auditoria de artefatos MATLAB Muçum",
      theme: "RNA e MATLAB",
      status: "auditado",
      confidence: "alta",
      tags: ["MATLAB", "auditoria", "Muçum"],
      horizon: [2, 4, 8, 12],
      evidence: "Inventário físico, hash/deduplicação e logs de filas realizados; não há fila promovida como operação oficial.",
      next: "Criar um registro canônico de execução que separe arquivo, modelo, seed, fila e resultado.",
      boundary: "A auditoria explica o estado dos artefatos; não valida sozinha a qualidade preditiva."
    },
    {
      id: "benchmarks",
      title: "Benchmarks de alternativas e robustez",
      theme: "RNA e MATLAB",
      status: "andamento",
      confidence: "média",
      tags: ["RNA", "XGBoost", "robustez", "comparação"],
      horizon: [2, 4, 8, 12],
      evidence: "Comparações por horizonte e baselines foram executadas; MAE e RMSE não apontam um vencedor universal.",
      next: "Consolidar análise por evento, pior caso, mediana e contrato causal de promoção.",
      boundary: "Comparação offline; variantes sem contrato de grafo validado permanecem não executadas."
    },
    {
      id: "transbordamento",
      title: "Previsão de transbordamento da bacia",
      theme: "Pesquisa e método",
      status: "bloqueado",
      confidence: "alta",
      tags: ["transbordamento", "chuva", "classificador"],
      horizon: [2, 4, 8, 12],
      evidence: "Dashboard comparativo publicado, mas o classificador não está operacional e a aprovação dos especialistas não foi fechada.",
      next: "Fixar alvo, evento, antecedência, negativos e alinhamento; repetir validação e coletar os veredictos necessários.",
      boundary: "Não emitir alerta, evacuação ou afirmação de que não haverá inundação."
    },
    {
      id: "hec-hms",
      title: "HEC-HMS + ECMWF/IFS",
      theme: "Hidrologia e previsão",
      status: "andamento",
      confidence: "média",
      tags: ["HEC-HMS", "ECMWF", "chuva", "DSS"],
      horizon: [],
      evidence: "Contextos, DSS/GeoTIFF e resultados foram publicados; ligação da grade na interface e validação retrospectiva permanecem abertas.",
      next: "Ligar Grid Data ao DSS correto e validar um evento observado antes de interpretar a saída.",
      boundary: "Cenário de pesquisa; não é previsão oficial nem prova de pico observado."
    },
    {
      id: "questionario",
      title: "Questionário de percepção de risco — Santa Tereza",
      theme: "Campo e documentos",
      status: "quase",
      confidence: "alta",
      tags: ["questionário", "campo", "Google Docs"],
      horizon: [],
      evidence: "59 perguntas em 11 seções, hierarquia e caminhos condicionais revisados; inspeção visual página a página e revisão institucional ainda faltam.",
      next: "Fazer QA visual final, confirmar consentimento e obter a revisão institucional antes do campo.",
      boundary: "Instrumento editado; ainda não é instrumento de campo aprovado."
    },
    {
      id: "hidrometria",
      title: "Relatório de hidrometria — Tupinambás",
      theme: "Campo e documentos",
      status: "andamento",
      confidence: "média",
      tags: ["hidrometria", "campo", "relatório"],
      horizon: [],
      evidence: "Documento com estrutura e métodos/resultados preliminares; dados de Andorinhas, topografia, laboratório, fotos e nomes faltam.",
      next: "Reunir as evidências de campo ausentes e só então fechar resultados e limitações.",
      boundary: "Rascunho técnico; não fechar conclusão hidrométrica com dados faltantes."
    },
    {
      id: "fotos-arcgis",
      title: "Relatório de fotos e ArcGIS",
      theme: "Campo e GIS",
      status: "quase",
      confidence: "média",
      tags: ["ArcGIS", "fotos", "GIS"],
      horizon: [],
      evidence: "Relatório Word com 34 registros/fotos foi entregue; planilha de origem e shapefile não ficaram comprovados na leitura.",
      next: "Reconciliar tabela, coordenadas, IDs e camada espacial antes de declarar a entrega georreferenciada completa.",
      boundary: "Fotos e relatório não substituem a camada vetorial auditável."
    },
    {
      id: "atlascampo",
      title: "AtlasCampo / aplicativo tipo Avenza",
      theme: "Campo e GIS",
      status: "andamento",
      confidence: "alta",
      tags: ["Flutter", "MBTiles", "GPS", "offline"],
      horizon: [],
      evidence: "Flutter analyze/test passaram; há suporte planejado para MBTiles, GPS, KML/KMZ/GPX/GeoJSON e contrato de sincronização.",
      next: "Testar dispositivo real, autenticação, sincronização assinada, permissões e administração.",
      boundary: "Protótipo técnico validado; não é produto de campo pronto."
    },
    {
      id: "manuscrito-vulnerabilidade",
      title: "Manuscrito de vulnerabilidade / dissertação",
      theme: "Pesquisa e método",
      status: "andamento",
      confidence: "média",
      tags: ["vulnerabilidade", "dissertação", "ABNT"],
      horizon: [],
      evidence: "Revisões e artefatos existem; aprovação independente e QA visual integral não ficaram comprovadas na última leitura.",
      next: "Congelar referências, figuras, limites científicos e executar a revisão final integral.",
      boundary: "Texto em evolução; não apresentar como artigo aprovado sem a revisão final."
    },
    {
      id: "mapbiomas",
      title: "Vulnerabilidade e camadas tipo MapBiomas",
      theme: "Campo e GIS",
      status: "publicado",
      confidence: "alta",
      tags: ["vulnerabilidade", "MapBiomas", "GeoPackage"],
      horizon: [],
      evidence: "Página pública corrigida, workflow aprovado e camadas/municípios catalogados; limites de pesquisa e segurança permanecem explícitos.",
      next: "Documentar a proveniência das camadas e repetir a reprodução com um pacote de dados versionado.",
      boundary: "Não converter mapa de pesquisa em rota aprovada, capacidade de abrigo ou ordem de evacuação."
    },
    {
      id: "custeio",
      title: "CUSTEIO / DIÁRIAS",
      theme: "Administração",
      status: "auditado",
      confidence: "alta",
      tags: ["auditoria", "administração"],
      horizon: [],
      evidence: "183 arquivos de recibos/declarações auditados; 5 discrepâncias numéricas e problemas de redação encontrados; nenhum arquivo foi alterado.",
      next: "Fazer a reconciliação humana e registrar a decisão antes de qualquer uso financeiro.",
      boundary: "Inventário privado; identificadores e documentos não entram nesta dashboard pública."
    },
    {
      id: "rotas",
      title: "Estudo de caso e rotas de fuga",
      theme: "Pesquisa e método",
      status: "bloqueado",
      confidence: "alta",
      tags: ["rotas", "estudo de caso", "agentes"],
      horizon: [2, 4, 8, 12],
      evidence: "60 combinações de modelos/horizontes e baselines testadas; poucos eventos de teste e nenhuma promoção/shadow aprovada.",
      next: "Fixar a versão experimental e obter os pareceres especializados que faltam.",
      boundary: "Pesquisa de rota; não é rota oficial, aviso ou ordem de evacuação."
    },
    {
      id: "anadem",
      title: "ANADEM e aquisição geoespacial",
      theme: "Campo e GIS",
      status: "andamento",
      confidence: "média",
      tags: ["ANADEM", "geoprocessamento", "AOI"],
      horizon: [],
      evidence: "Planejamento de AOI e camadas foi iniciado; aquisição e catálogo completo ainda não foram fechados.",
      next: "Baixar somente as camadas da AOI, registrar fonte, CRS, data e licença e validar a cobertura.",
      boundary: "Plano de aquisição; não presumir que uma camada planejada já está disponível."
    },
    {
      id: "chuva-dashboard",
      title: "Dashboard comparativo de chuva e régua",
      theme: "Site público",
      status: "publicado",
      confidence: "alta",
      tags: ["chuva", "nível", "dashboard", "estações"],
      horizon: [],
      evidence: "Comparação entre estações e escalas foi publicada, mantendo chuva, nível, solo e probabilidade experimental separados.",
      next: "Atualizar feeds e tornar indisponibilidade, atraso e proxy espacial visíveis na primeira leitura.",
      boundary: "Comparativo de pesquisa; não é alerta oficial."
    },
    {
      id: "site-rna",
      title: "Auditoria do site de RNA e robôs",
      theme: "Site público",
      status: "auditado",
      confidence: "alta",
      tags: ["site", "RNA", "robôs", "qualidade"],
      horizon: [2, 4, 8, 12],
      evidence: "60 entradas catalogadas em um scan, HTTP 200 e 81 testes com 80 passagens e 1 falha; frescor e semântica de probabilidade seguem pendentes.",
      next: "Corrigir o teste falho, testar frescor e manter o estado stale/unavailable explícito.",
      boundary: "HTTP 200 e status ok não provam qualidade do modelo nem atualização do feed."
    }
  ],
  finishQueue: [
    { priority: 1, title: "Fechar o registro Q77/Q82 de Muçum", reason: "Há filas e artefatos, mas a reconciliação MAT–XLSX–CSV–manifesto e a promoção não estão fechadas.", doneWhen: "Um registro por modelo, com partição, horizonte, fonte, hash, métricas e gate de qualidade." },
    { priority: 2, title: "Congelar o protocolo do artigo RNA Santa Tereza", reason: "O manuscrito existe, mas alvo, coorte, partição causal, entradas ex-ante e baseline precisam ser congelados.", doneWhen: "Cohort, target, inputs, splits, eventos, seeds, métricas e regra de promoção versionados." },
    { priority: 3, title: "Reconciliar catálogo 55 × 60", reason: "São dois snapshots auditados; a divergência impede uma contagem única de pesquisas publicadas.", doneWhen: "Uma fonte canônica e uma nota de versão explicando entradas adicionadas/removidas." },
    { priority: 4, title: "Validar o circuito HEC-HMS", reason: "Há DSS/contexto publicado, mas a ligação de grade e a validação retrospectiva ainda são abertas.", doneWhen: "Grade correta ligada, evento observado reproduzido e limites de previsão documentados." },
    { priority: 5, title: "Finalizar o questionário para o campo", reason: "A estrutura está pronta, mas falta QA visual e revisão institucional do consentimento.", doneWhen: "PDF página a página revisado e instrumento institucionalmente liberado." },
    { priority: 6, title: "Fechar hidrometria Tupinambás", reason: "O relatório tem base, mas ainda faltam evidências de campo que sustentem os resultados.", doneWhen: "Andorinhas, topografia, laboratório, fotos e nomes reconciliados no relatório." },
    { priority: 7, title: "Revisar estudo de rotas de fuga", reason: "O experimento avançou, mas poucos eventos e a ausência de veredictos impedem promoção.", doneWhen: "Versão experimental congelada, limitações registradas e pareceres recebidos." },
    { priority: 8, title: "Testar AtlasCampo em dispositivo real", reason: "O código passa nos testes locais, porém o uso de campo depende de permissões, sync e autenticação.", doneWhen: "Matriz de dispositivos, offline, GPS, sync, recuperação e segurança aprovada." }
  ],
  localInventory: {
    roots: [
      { name: "redes_neurais", files: 4291, bytes: 3301272429, scope: "inventário geral" },
      { name: "repo_site", files: 1355, bytes: 2424079724, scope: "inventário geral" },
      { name: "repo_site_mucum_weather", files: 1320, bytes: 1450838608, scope: "inventário geral" },
      { name: "worktrees", files: 4777, bytes: null, scope: "somente .mat contabilizados nesta linha" }
    ],
    mat: {
      currentPhysicalFiles: 5914,
      hashAuditPhysicalFiles: 5913,
      uniqueSha256: 723,
      duplicateHashGroups: 290,
      duplicateFilesInGroups: 5480,
      note: "A contagem física corrente e a fotografia usada na auditoria de hashes diferem por um arquivo novo; não tratar isso como nova execução."
    },
    horizonFiles: [
      { label: "2 h", value: 139 },
      { label: "4 h", value: 336 },
      { label: "8 h", value: 216 },
      { label: "12 h", value: 117 }
    ],
    matlab: {
      doneMarkers: 350,
      explicitQueueParents: 25,
      mucumQueueParents: 23,
      santaTerezaQueueParents: 2,
      explicitCountRecords: [107, 105, 11],
      documentedWallClockHours: 16.37,
      documentedRun: "24 itens, 2026-07-24 08:18:40 a 2026-07-25 00:40:25",
      note: "Logs diferentes podem ser cópias ou rodadas variantes; os três números de contagem não são somados como total histórico."
    }
  },
  conversationInventory: {
    codexVisible: 39,
    codexArchived: 71,
    codexTotal: 110,
    chatgptVisible: 18,
    note: "A leitura lista o que está acessível pelos conectores nesta sessão. Não é uma exportação integral da conta."
  },
  driveSignals: [
    { query: "RNA", count: 16, certainty: "contagem retornada" },
    { query: "MATLAB", count: 9, certainty: "contagem retornada" },
    { query: "HEC-HMS", count: 6, certainty: "contagem retornada" },
    { query: "Santa Tereza", count: 100, certainty: "limite da busca; pelo menos 100" },
    { query: "Muçum", count: 100, certainty: "limite da busca; pelo menos 100" },
    { query: "PREVINE", count: 100, certainty: "limite da busca; pelo menos 100" },
    { query: "vulnerabilidade", count: 100, certainty: "limite da busca; pelo menos 100" },
    { query: "pesquisa", count: 100, certainty: "limite da busca; pelo menos 100" },
    { query: "questionário", count: 100, certainty: "limite da busca; pelo menos 100" }
  ],
  publishedSnapshots: [
    { label: "Catálogo auditado", value: "55 entradas", note: "snapshot com 5 páginas e HTTP 200" },
    { label: "Scan do site RNA", value: "60 entradas", note: "snapshot posterior; não reconciliado com 55" },
    { label: "Repositórios GitHub acessíveis", value: "3", note: "um deles reservado para este painel" }
  ],
  timeline: [
    { date: "2026-09-19", title: "Inventário transversal", source: "Codex + local + Drive + GitHub", outcome: "Painel sanitizado em construção; números separados por tipo de evidência." },
    { date: "2026-09-17", title: "Calibragem HEC-HMS", source: "Drive / local", outcome: "Artefatos encontrados; validação de circuito ainda aberta." },
    { date: "2026-09-15", title: "Auditoria de site e RNA", source: "site público + Codex", outcome: "60 entradas e 81 testes observados; 1 falha e limites científicos registrados." },
    { date: "2026-09-14", title: "Muçum: eventos e PERS", source: "local + Codex", outcome: "Auditoria orientada a evento; alternativas seguem não-live." },
    { date: "2026-09-11", title: "Filas Q79/Q80", source: "logs MATLAB", outcome: "Marcadores explícitos de fila concluída; reconciliação e aprovação continuam separadas." },
    { date: "2026-09-09", title: "Q76 e relatório de campo", source: "logs + Drive", outcome: "Nova fila H04 e documentos de hidrometria/campo encontrados." },
    { date: "2026-08-31", title: "Catálogo de pesquisas", source: "site público", outcome: "55 entradas auditadas; manutenção/frescor identificados como pendência." },
    { date: "2026-07-25", title: "Rodada MATLAB documentada", source: "status diário", outcome: "24 itens em aproximadamente 16 h 22 min; um registro de duração, não o total histórico." }
  ],
  sources: [
    { label: "Conversas", status: "usado", detail: "Títulos, resumos e turnos acessíveis pelo Codex; agrupados em frentes, sem publicar IDs ou texto privado." },
    { label: "Computador", status: "usado", detail: "Raízes de trabalho PREVINE, logs, marcadores .done, MAT e worktrees; Windows/AppData e pastas pessoais não foram tratados como acervo científico." },
    { label: "Drive", status: "usado", detail: "Busca de metadados e sinais por palavra-chave; documentos privados, recibos, IDs e e-mail foram excluídos da página pública." },
    { label: "GitHub", status: "usado", detail: "Repositórios acessíveis e publicação deste snapshot; o repositório de origem permanece separado dos worktrees sujos." }
  ]
};

