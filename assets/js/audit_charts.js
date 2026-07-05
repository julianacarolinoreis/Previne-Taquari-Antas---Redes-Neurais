(function () {
  const DATA_URL = 'assets/data/auditaveis_series.json';
  const INVENTORY_URL = 'assets/data/auditoria_inventario.json';
  const RAW_BUNDLE_URL = 'assets/data/logs_metricas_brutos.zip';
  const COLORS = {
    treino: '#898781',
    validacao: '#2a78d6',
    teste: '#d4271e',
    obs: '#151812',
    rna: '#2a78d6',
    riseObs: '#1f8d49',
    riseRna: '#c78d00',
    bar: '#1e5b3c'
  };
  const SET_NAMES = ['Treino', 'Validação', 'Teste', 'Outro'];
  const SCOPE_LABELS = { all: 'Geral', '0': 'Treino', '1': 'Validação', '2': 'Teste' };
  const FAMILY_ORDER = ['2H_ALT', '2H_CONV', '4H_ALT', '4H_CONV', '8H_ALT', '8H_CONV', '12H_ALT', '12H_CONV'];
  const POSITIVE_PERS_KEYS = ['PERS_geral', 'PERS_treino', 'PERS_validacao', 'PERS_teste'];
  const nf = new Intl.NumberFormat('pt-BR');

  let payload = null;
  let inventory = null;
  let inventoryLoading = null;
  let mainModels = [];
  let state = { family: 'TODAS', modelId: '', eventKey: '', scope: 'all', mainModelName: '' };

  function init() {
    enforceLightAndLayout();
    mainModels = readMainModels();
    const wrap = document.querySelector('.wrap') || document.body;
    const notes = document.querySelector('.notes');
    const section = document.createElement('section');
    section.className = 'sec audit-sec';
    section.id = 'graficos-auditaveis';
    section.innerHTML = [
      '<h2>Gráficos, métricas e logs auditáveis</h2>',
      '<p class="sec-sub">Clique em qualquer modelo do pódio, ranking, gráfico ou tabela: este painel seleciona o modelo correspondente e mostra dispersão, ondas, subidas, métricas e arquivos de rastreio.</p>',
      '<div class="audit-toolbar">',
      '  <div class="audit-field"><label for="audit-model">Modelo auditável</label><select id="audit-model"></select></div>',
      '  <div class="audit-field"><label for="audit-family">Família</label><select id="audit-family"></select></div>',
      '  <div class="audit-field"><label for="audit-event">Evento/onda</label><select id="audit-event"></select></div>',
      '  <div class="audit-field"><label for="audit-scope">Dispersão</label><select id="audit-scope"><option value="all">Geral</option><option value="0">Treino</option><option value="1">Validação</option><option value="2">Teste</option></select></div>',
      '</div>',
      '<div class="audit-selected" id="audit-selected"></div>',
      '<div class="audit-kpis" id="audit-kpis"></div>',
      '<div class="audit-grid">',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Observado x RNA</div><div class="audit-sub">Dispersão do recorte escolhido: geral, treino, validação ou teste</div></figcaption><div class="audit-legend" id="audit-leg-scatter"></div><div class="audit-chart" id="audit-scatter"></div></figure>',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Série do evento</div><div class="audit-sub">Onda observada e prevista no evento selecionado</div></figcaption><div class="audit-legend" id="audit-leg-series"></div><div class="audit-chart" id="audit-series"></div></figure>',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Subida do evento</div><div class="audit-sub">Variação acumulada em relação ao início da onda</div></figcaption><div class="audit-legend" id="audit-leg-rise"></div><div class="audit-chart" id="audit-rise"></div></figure>',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Maiores subidas observadas</div><div class="audit-sub">Eventos com maior aumento de nível em toda a base auditável</div></figcaption><div class="audit-chart" id="audit-top-rises"></div></figure>',
      '</div>',
      '<div class="audit-grid audit-grid-wide">',
      '  <section class="audit-card audit-wide"><h3>Métricas calculadas da planilha auditável</h3><div id="audit-metrics-table"></div></section>',
      '  <section class="audit-card audit-wide"><h3>Métricas do planilhão/modelo clicado</h3><div id="audit-main-metrics"></div></section>',
      '</div>',
      '<section class="audit-card audit-wide audit-evidence-card">',
      '  <div class="audit-evidence-head"><div><h3>Logs, status, CSVs e arquivos associados</h3><p>Inventário completo da varredura: logs brutos, CSVs de status/resultado, planilhas, MAT e códigos encontrados.</p></div><button type="button" id="audit-load-inventory">Carregar logs</button></div>',
      '  <div id="audit-evidence"></div>',
      '</section>',
      '<p class="audit-note" id="audit-note"></p>'
    ].join('');
    const refs = sectionByHeading('Referências') || [...document.querySelectorAll('section.sec')].find(sec => {
      const h = sec.querySelector('h2');
      return h && norm(h.textContent) === 'REFERENCIAS';
    });
    if (refs && refs.parentNode) refs.parentNode.insertBefore(section, refs);
    else if (notes && notes.parentNode) notes.parentNode.insertBefore(section, notes);
    else wrap.appendChild(section);
    rewriteIntroForResults();

    fetch(DATA_URL, { cache: 'no-store' })
      .then(resp => {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(data => {
        payload = data;
        applyPositivePersFilterToAuditPayload();
        rewriteIntroForResults();
        setupControls();
        installModelClickBridge();
        selectFromUrlHash();
        renderAll();
      })
      .catch(err => {
        section.querySelector('#audit-scatter').innerHTML =
          '<div class="audit-empty">Não foi possível carregar a base dos auditáveis: ' + escapeHtml(err.message) + '.</div>';
      });
  }

  function enforceLightAndLayout() {
    document.documentElement.setAttribute('data-theme', 'light');
    const vars = {
      '--page': '#f7f8f1',
      '--surface': '#ffffff',
      '--surface-2': '#f1f5ec',
      '--ink': '#151812',
      '--ink-2': '#4e564a',
      '--muted': '#6f786c',
      '--grid': '#e4e8dc',
      '--baseline': '#c8cfbd',
      '--border': 'rgba(21,24,18,.13)',
      '--accent': '#2a78d6',
      '--chrome': '#1e5b3c',
      '--shadow': '0 12px 32px rgba(38,49,31,.08)'
    };
    Object.entries(vars).forEach(([key, value]) => {
      document.documentElement.style.setProperty(key, value, 'important');
    });
    if (document.getElementById('audit-light-override')) return;
    const style = document.createElement('style');
    style.id = 'audit-light-override';
    style.textContent = `
      :root, :root[data-theme="light"], :root[data-theme="dark"] {
        --page:#f7f8f1 !important;
        --surface:#ffffff !important;
        --surface-2:#f1f5ec !important;
        --ink:#151812 !important;
        --ink-2:#4e564a !important;
        --muted:#6f786c !important;
        --grid:#e4e8dc !important;
        --baseline:#c8cfbd !important;
        --border:rgba(21,24,18,.13) !important;
        --accent:#2a78d6 !important;
        --chrome:#1e5b3c !important;
        --shadow:0 12px 32px rgba(38,49,31,.08) !important;
      }
      html, body { background:#f7f8f1 !important; color:#151812 !important; }
      body, .wrap, main, section, .sec { color:#151812 !important; }
      #kpis { display:none !important; }
      .grid2 { grid-template-columns:1fr !important; }
      .grid2 > *, .grid2 figure.card, .grid2 .card { width:100% !important; min-width:0 !important; }
      .card, figure.card, .audit-card, .audit-selected, .audit-toolbar { background:#fff !important; color:#151812 !important; }
      .muted, .sec-sub, figcaption, .audit-sub { color:#6f786c !important; }
      .modal-card, #modal .card { background:#fff !important; color:#151812 !important; }
      .soon, .step.soon, .m-soon, [data-audit-hide="true"] { display:none !important; }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function rewriteIntroForResults() {
    const kpis = document.getElementById('kpis');
    if (kpis) kpis.setAttribute('data-audit-hide', 'true');

    document.querySelectorAll('.step, .s-card, .steps > *, article, .card').forEach(el => {
      const text = norm(el.textContent);
      if (text.includes('PROXIMO_PASSO') && text.includes('DISPERSOES_E_SUBIDAS')) {
        el.setAttribute('data-audit-hide', 'true');
      }
    });

    document.querySelectorAll('#soon, .soon, [id*="soon"]').forEach(el => {
      el.setAttribute('data-audit-hide', 'true');
    });

    rewriteStaticCopy();

    document.querySelectorAll('li, p, .find').forEach(el => {
      const text = norm(el.textContent);
      if (text.includes('SERAO_ANEXADAS_AO_PAINEL') ||
          text.includes('EM_PREPARACAO_PARA_ESTE_MODELO') ||
          text.includes('O_4H_FICOU_FORA_DESTA_LEITURA')) {
        el.setAttribute('data-audit-hide', 'true');
      }
    });
  }

  function rewriteStaticCopy() {
    const sub = document.querySelector('header .sub');
    if (sub) {
      sub.innerHTML = 'Varredura dos modelos RNA treinados para prever o nível do rio na bacia Taquari-Antas com antecedência de 2h, 4h, 8h e 12h, integrando planilhão, planilhas auditáveis, arquivos <span style="font-variant-numeric:tabular-nums">.mat</span>, logs, CSVs e métricas rastreáveis.';
    }

    const stamp = document.getElementById('stamp');
    if (stamp) {
      stamp.textContent = 'Pesquisa em desenvolvimento · ' + nf.format(mainModels.length || 158) + ' modelos com todos os PERS positivos no planilhão principal' + (payload && payload.meta ? ' + ' + nf.format(payload.meta.modelCount) + ' séries auditáveis filtradas' : '') + ' · base atualizada em 05/07/2026';
    }

    const src = document.getElementById('src');
    if (src) {
      src.textContent = 'Dados integrados: planilhão principal, planilhas auditáveis ponto a ponto, arquivos MAT, logs e CSVs de status/resultado. Clique em qualquer modelo para abrir a ficha auditável com gráficos, métricas e fontes associadas.';
    }

    rewriteStep('PASSO_3', {
      title: 'Cenários, inputs e rotações',
      text: 'A pesquisa não compara ALT e CONV como se fossem duas equações de saída diferentes. Cada rodada precisa ser lida pela própria ficha auditável: horizonte de antecedência, conjunto de inputs, defasagens, número de neurônios, rotação dos eventos de cheia, planilha, arquivo .mat, logs e métricas calculadas. Assim, o resultado não é só o nome da família; é o pacote completo que acompanha aquele modelo.'
    });

    setSectionSub('Desempenho por família',
      'Leitura comparativa por família e métrica. As barras ajudam a localizar modelos de interesse, mas a escolha precisa ser conferida na ficha auditável: dispersão, ondas, subidas, planilha, MAT, logs e CSVs associados.');
    setSectionSub('Modelo de referência de cada família',
      'Um modelo representativo por família, escolhido para inspeção. Use como ponto de entrada para auditoria, não como decisão final isolada.');
    setSectionSub('Principais achados',
      'Síntese do planilhão principal, agora complementada pelo painel auditável com séries ponto a ponto. Onde o texto antigo dependia de anexar planilhas, a auditoria já está disponível abaixo.');
    setSectionTitle('Exploração dos 239 modelos', 'Exploração dos modelos com PERS positivos');

    replaceTextNode('.lb-note', 'A barra mostra o valor relativo dentro da família; clique no modelo para abrir gráficos, métricas e arquivos auditáveis.');
    replaceTextNode('#fcount', '');
    rewriteChartTitle('Inputs mais usados pelos melhores modelos', 'Inputs mais frequentes no recorte');
    rewriteChartSubtitle('% de modelos que usam cada input', '% de modelos que usam cada input no recorte selecionado');
    rewriteChartTitle('Ranking — top 12 pelo score de equilíbrio', 'Modelos para inspeção pelo score de equilíbrio');

    document.querySelectorAll('.m-soon').forEach(el => el.setAttribute('data-audit-hide', 'true'));
  }

  function rewriteStep(stepToken, copy) {
    document.querySelectorAll('.step').forEach(step => {
      const num = step.querySelector('.s-num');
      if (!num || !norm(num.textContent).includes(stepToken)) return;
      const title = step.querySelector('.s-title');
      const text = step.querySelector('.s-text');
      if (title) title.textContent = copy.title;
      if (text) text.textContent = copy.text;
    });
  }

  function setSectionSub(title, copy) {
    const section = sectionByHeading(title);
    const sub = section && section.querySelector('.sec-sub');
    if (sub) sub.textContent = copy;
  }

  function setSectionTitle(oldTitle, newTitle) {
    const section = sectionByHeading(oldTitle);
    const h = section && section.querySelector('h2');
    if (h) h.textContent = newTitle;
  }

  function sectionByHeading(title) {
    const want = norm(title);
    return [...document.querySelectorAll('section.sec')].find(section => {
      const h = section.querySelector('h2');
      return h && norm(h.textContent) === want;
    });
  }

  function replaceTextNode(selector, text) {
    const node = document.querySelector(selector);
    if (node) node.textContent = text;
  }

  function rewriteChartTitle(oldText, newText) {
    document.querySelectorAll('.c-title').forEach(node => {
      if (norm(node.textContent) === norm(oldText)) node.textContent = newText;
    });
  }

  function rewriteChartSubtitle(oldStart, newText) {
    document.querySelectorAll('.c-sub').forEach(node => {
      if (norm(node.textContent).startsWith(norm(oldStart))) node.textContent = newText;
    });
  }

  function readMainModels() {
    const node = document.getElementById('data');
    if (!node) return [];
    try {
      const data = JSON.parse(node.textContent || '{}');
      return Array.isArray(data.models) ? data.models.filter(hasAllPositivePers) : [];
    } catch (err) {
      return [];
    }
  }


  function hasAllPositivePers(model) {
    return !!model && POSITIVE_PERS_KEYS.every(key => typeof model[key] === 'number' && model[key] > 0);
  }

  function applyPositivePersFilterToAuditPayload() {
    if (!payload || !Array.isArray(payload.models) || !mainModels.length) return;
    payload.models = payload.models.filter(model => !!findMainForAudit(model));
    const keptNames = new Set(payload.models.flatMap(model => [norm(model.id), norm(model.name)]).filter(Boolean));
    payload.eventRiseTop = (payload.eventRiseTop || []).filter(row => keptNames.has(norm(row.model)));
    const families = {};
    let pointCount = 0;
    payload.models.forEach(model => {
      const family = model.family || 'OUTROS';
      families[family] = (families[family] || 0) + 1;
      if (model.scatterBySet) {
        Object.values(model.scatterBySet).forEach(points => { pointCount += Array.isArray(points) ? points.length : 0; });
      } else if (Array.isArray(model.scatter)) {
        pointCount += model.scatter.length;
      }
    });
    payload.meta = Object.assign({}, payload.meta || {}, {
      modelCount: payload.models.length,
      pointCount: pointCount || (payload.meta && payload.meta.pointCount) || 0,
      families,
      positivePersFilter: 'Mantidos apenas modelos associados a registros do planilhão com PERS_geral, PERS_treino, PERS_validacao e PERS_teste positivos.'
    });
  }

  function setupControls() {
    const families = ['TODAS'].concat([...new Set(payload.models.map(m => m.family || 'OUTROS'))]
      .sort((a, b) => familyRank(a) - familyRank(b) || String(a).localeCompare(String(b))));
    const familySelect = document.getElementById('audit-family');
    familySelect.replaceChildren(...families.map(f => option(f, f === 'TODAS' ? 'Todas' : labelFamily(f))));
    familySelect.value = state.family;
    familySelect.addEventListener('change', () => {
      state.family = familySelect.value;
      state.modelId = '';
      state.mainModelName = '';
      fillModels();
      renderAll();
    });

    document.getElementById('audit-model').addEventListener('change', ev => {
      state.modelId = ev.target.value;
      state.mainModelName = '';
      fillEvents();
      renderAll();
      updateHash();
    });
    document.getElementById('audit-event').addEventListener('change', ev => {
      state.eventKey = ev.target.value;
      renderAll();
    });
    document.getElementById('audit-scope').addEventListener('change', ev => {
      state.scope = ev.target.value;
      renderAll();
    });
    document.getElementById('audit-load-inventory').addEventListener('click', () => {
      loadInventory().then(renderEvidence);
    });

    fillModels();
  }

  function familyRank(f) {
    const i = FAMILY_ORDER.indexOf(f);
    return i < 0 ? 99 : i;
  }

  function fillModels() {
    const modelSelect = document.getElementById('audit-model');
    const rows = filteredModels().sort((a, b) => {
      const ac = a.metrics.corr == null ? -2 : a.metrics.corr;
      const bc = b.metrics.corr == null ? -2 : b.metrics.corr;
      return (bc - ac) || ((a.metrics.mae || 1e9) - (b.metrics.mae || 1e9)) || a.name.localeCompare(b.name);
    });
    modelSelect.replaceChildren(...rows.map(m => option(m.id, labelModel(m))));
    state.modelId = state.modelId || (rows[0] && rows[0].id) || '';
    modelSelect.value = state.modelId;
    fillEvents();
  }

  function fillEvents() {
    const eventSelect = document.getElementById('audit-event');
    const model = currentModel();
    if (!model) {
      eventSelect.replaceChildren();
      state.eventKey = '';
      return;
    }
    const keys = Object.keys(model.series || {});
    const opts = keys.map(key => {
      const ev = model.events.find(x => x.key === key);
      const label = ev
        ? eventLabel(ev, true) + ' - ' + ev.conjunto + ' | subida ' + fmtCm(ev.riseObs) + ' | MAE ' + fmtCm(ev.mae)
        : key;
      return option(key, label);
    });
    eventSelect.replaceChildren(...opts);
    if (!keys.includes(state.eventKey)) state.eventKey = keys[0] || '';
    eventSelect.value = state.eventKey;
  }

  function filteredModels() {
    if (!payload) return [];
    return payload.models.filter(m => state.family === 'TODAS' || m.family === state.family);
  }

  function currentModel() {
    return payload && payload.models.find(m => m.id === state.modelId);
  }

  function currentMainModel() {
    const audit = currentModel();
    if (state.mainModelName) {
      const exact = mainModels.find(m => norm(m.modelo) === norm(state.mainModelName));
      if (exact) return exact;
    }
    if (!audit) return null;
    return findMainForAudit(audit);
  }

  function renderAll() {
    if (!payload) return;
    const model = currentModel();
    renderSelected(model);
    renderKpis(model);
    renderLegend('audit-leg-scatter', state.scope === 'all'
      ? [['Treino', COLORS.treino], ['Validação', COLORS.validacao], ['Teste', COLORS.teste]]
      : [[SCOPE_LABELS[state.scope], setColor(Number(state.scope))]]);
    renderLegend('audit-leg-series', [['Observado', COLORS.obs], ['RNA', COLORS.rna]]);
    renderLegend('audit-leg-rise', [['Subida observada', COLORS.riseObs], ['Subida RNA', COLORS.riseRna]]);
    renderScatter(model);
    renderSeries(model);
    renderRise(model);
    renderTopRises();
    renderAuditMetrics(model);
    renderMainMetrics(currentMainModel(), model);
    renderEvidence();
    const note = document.getElementById('audit-note');
    note.textContent = 'Base gerada em ' + payload.meta.generatedAt + ': ' +
      nf.format(payload.meta.modelCount) + ' modelos com série auditável, ' +
      nf.format(payload.meta.pointCount) + ' pontos, famílias ' +
      Object.entries(payload.meta.families).map(([k, v]) => labelFamily(k) + ' (' + v + ')').join(', ') +
      '. Planilhas não lidas/parseadas: ' + nf.format(payload.meta.skippedCount || 0) + '.';
  }

  function renderSelected(model) {
    const box = document.getElementById('audit-selected');
    if (!model) {
      box.innerHTML = '<div class="audit-empty">Nenhum modelo auditável selecionado.</div>';
      return;
    }
    const main = currentMainModel();
    const source = model.sourceRef || model.file || '-';
    const workbook = model.workbookUrl
      ? '<a class="audit-download-btn" href="' + escapeAttr(model.workbookUrl) + '" download>Baixar planilha auditavel (.xlsx)</a>'
      : '<span class="audit-muted">Planilha individual nao copiada para o site.</span>';
    const mat = model.matUrl
      ? '<a class="audit-download-btn audit-download-mat" href="' + escapeAttr(model.matUrl) + '" download>Baixar modelo treinado (.mat)</a>'
      : '<span class="audit-muted">Modelo treinado (.mat) ainda nao publicado para este item.</span>';
    box.innerHTML = [
      '<div><strong>Selecionado:</strong> ' + escapeHtml(model.name) + '</div>',
      '<div><strong>Família:</strong> ' + escapeHtml(labelFamily(model.family)) + '</div>',
      '<div><strong>Fonte auditável:</strong> <code>' + escapeHtml(source) + '</code></div>',
      '<div class="audit-selected-actions">' + workbook + mat + '<a class="audit-secondary-link" href="#audit-evidence">Ver logs/MAT associados</a></div>',
      main ? '<div><strong>Modelo do planilhão associado:</strong> <code>' + escapeHtml(main.modelo) + '</code></div>' : '<div><strong>Modelo do planilhão associado:</strong> não encontrado por nome/combinação.</div>'
    ].join('');
  }

  function renderKpis(model) {
    const box = document.getElementById('audit-kpis');
    if (!model) {
      box.innerHTML = '<div class="audit-empty">Nenhum modelo encontrado para o filtro atual.</div>';
      return;
    }
    const m = (model.metricsBySet && model.metricsBySet[state.scope]) || model.metrics || {};
    const items = [
      ['Pontos ' + SCOPE_LABELS[state.scope].toLowerCase(), nf.format(m.n || 0)],
      ['MAE', fmtCm(m.mae)],
      ['RMSE', fmtCm(m.rmse)],
      ['Erro máximo', fmtCm(m.maxAbs)],
      ['Correlação', m.corr == null ? '-' : Number(m.corr).toFixed(3).replace('.', ',')],
      ['Viés médio', fmtCm(m.bias)]
    ];
    box.replaceChildren(...items.map(([k, v]) => {
      const el = document.createElement('div');
      el.className = 'audit-kpi';
      el.innerHTML = '<div class="audit-k">' + escapeHtml(k) + '</div><div class="audit-v">' + escapeHtml(v) + '</div>';
      return el;
    }));
  }

  function renderScatter(model) {
    const box = document.getElementById('audit-scatter');
    box.replaceChildren();
    const rows = model && model.scatterBySet ? (model.scatterBySet[state.scope] || []) : (model && model.scatter);
    if (!model || !rows || !rows.length) return empty(box);
    const W = 620, H = 330, pad = { l: 54, r: 18, t: 18, b: 42 };
    const vals = rows.flatMap(p => [p[0], p[1]]).filter(v => typeof v === 'number');
    const minV = Math.floor(Math.min(...vals) / 100) * 100;
    const maxV = Math.ceil(Math.max(...vals) / 100) * 100;
    const x = scale(minV, maxV, pad.l, W - pad.r);
    const y = scale(minV, maxV, H - pad.b, pad.t);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Dispersão observado contra RNA' });
    ticks(minV, maxV, 5).forEach(t => {
      svg.append(svgEl('line', { x1: x(t), x2: x(t), y1: pad.t, y2: H - pad.b, class: 'audit-gridline' }));
      svg.append(svgEl('line', { x1: pad.l, x2: W - pad.r, y1: y(t), y2: y(t), class: 'audit-gridline' }));
      svgText(svg, x(t), H - pad.b + 18, fmtShort(t), 'audit-axis', 'middle');
      svgText(svg, pad.l - 8, y(t) + 4, fmtShort(t), 'audit-axis', 'end');
    });
    svg.append(svgEl('line', { x1: x(minV), y1: y(minV), x2: x(maxV), y2: y(maxV), class: 'audit-diagonal' }));
    rows.forEach(p => {
      svg.append(svgEl('circle', {
        cx: x(p[0]), cy: y(p[1]), r: state.scope === 'all' ? 3.2 : 3.7,
        fill: setColor(p[2]), opacity: p[2] === 2 ? 0.78 : 0.5
      }));
    });
    svgText(svg, (pad.l + W - pad.r) / 2, H - 8, 'Observado (cm)', 'audit-axis', 'middle');
    const yl = svgText(svg, 13, (pad.t + H - pad.b) / 2, 'RNA (cm)', 'audit-axis', 'middle');
    yl.setAttribute('transform', `rotate(-90 13 ${(pad.t + H - pad.b) / 2})`);
    box.append(svg);
  }

  function renderSeries(model) {
    const box = document.getElementById('audit-series');
    box.replaceChildren();
    const rows = model && model.series && model.series[state.eventKey];
    if (!rows || !rows.length) return empty(box);
    renderLineChart(box, rows, {
      columns: [{ i: 1, color: COLORS.obs }, { i: 2, color: COLORS.rna }],
      yLabel: 'Nível (cm)',
      aria: 'Série temporal do evento'
    });
  }

  function renderRise(model) {
    const box = document.getElementById('audit-rise');
    box.replaceChildren();
    const rows = model && model.series && model.series[state.eventKey];
    if (!rows || !rows.length) return empty(box);
    renderLineChart(box, rows, {
      columns: [{ i: 4, color: COLORS.riseObs }, { i: 5, color: COLORS.riseRna }],
      yLabel: 'Subida (cm)',
      zeroLine: true,
      aria: 'Subida acumulada do evento'
    });
  }

  function renderLineChart(box, rows, cfg) {
    const W = 620, H = 330, pad = { l: 58, r: 18, t: 18, b: 48 };
    const vals = rows.flatMap(r => cfg.columns.map(c => r[c.i])).filter(v => typeof v === 'number');
    if (!vals.length) return empty(box);
    let minV = Math.min(...vals), maxV = Math.max(...vals);
    const span = Math.max(1, maxV - minV);
    minV = Math.floor((minV - span * 0.08) / 50) * 50;
    maxV = Math.ceil((maxV + span * 0.08) / 50) * 50;
    if (cfg.zeroLine) {
      minV = Math.min(minV, 0);
      maxV = Math.max(maxV, 0);
    }
    const x = scale(0, Math.max(1, rows.length - 1), pad.l, W - pad.r);
    const y = scale(minV, maxV, H - pad.b, pad.t);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': cfg.aria });
    ticks(minV, maxV, 5).forEach(t => {
      svg.append(svgEl('line', { x1: pad.l, x2: W - pad.r, y1: y(t), y2: y(t), class: t === 0 ? 'audit-baseline' : 'audit-gridline' }));
      svgText(svg, pad.l - 8, y(t) + 4, fmtShort(t), 'audit-axis', 'end');
    });
    const xTicks = [0, Math.floor((rows.length - 1) / 2), rows.length - 1].filter((v, i, a) => a.indexOf(v) === i);
    xTicks.forEach(i => {
      svg.append(svgEl('line', { x1: x(i), x2: x(i), y1: pad.t, y2: H - pad.b, class: 'audit-gridline' }));
      svgText(svg, x(i), H - pad.b + 17, rows[i][0].slice(5), 'audit-axis', 'middle');
    });
    cfg.columns.forEach(col => {
      const d = rows.map((r, i) => [x(i), y(r[col.i])]).filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]));
      svg.append(svgEl('path', { d: pathLine(d), fill: 'none', stroke: col.color, 'stroke-width': 2.4, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    });
    svgText(svg, 14, (pad.t + H - pad.b) / 2, cfg.yLabel, 'audit-axis', 'middle')
      .setAttribute('transform', `rotate(-90 14 ${(pad.t + H - pad.b) / 2})`);
    box.append(svg);
  }

  function renderTopRises() {
    const box = document.getElementById('audit-top-rises');
    box.replaceChildren();
    const rows = (payload.eventRiseTop || []).slice(0, 14);
    if (!rows.length) return empty(box);
    const W = 620, rowH = 22, H = 34 + rows.length * rowH + 28, pad = { l: 150, r: 46, t: 14, b: 22 };
    const maxV = Math.max(...rows.map(r => r.riseObs || 0), 1);
    const x = scale(0, maxV, pad.l, W - pad.r);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Maiores subidas observadas por evento' });
    ticks(0, maxV, 4).forEach(t => {
      svg.append(svgEl('line', { x1: x(t), x2: x(t), y1: pad.t, y2: H - pad.b, class: 'audit-gridline' }));
      svgText(svg, x(t), H - 5, fmtShort(t), 'audit-axis', 'middle');
    });
    rows.forEach((r, i) => {
      const y = pad.t + i * rowH + 5;
      svgText(svg, pad.l - 9, y + 11, eventLabel(r, false), 'audit-label', 'end');
      const width = Math.max(1, x(r.riseObs || 0) - pad.l);
      svg.append(svgEl('rect', { x: pad.l, y, width, height: 15, rx: 4, fill: COLORS.bar, opacity: 0.86 }));
      svgText(svg, pad.l + width + 6, y + 12, fmtCm(r.riseObs), 'audit-value', 'start');
    });
    const note = document.createElement('div');
    note.className = 'audit-event-note';
    note.textContent = '* A data exibida é o início da onda na planilha auditável; quando há fim registrado, o seletor mostra o período completo.';
    box.append(svg, note);
  }

  function renderAuditMetrics(model) {
    const box = document.getElementById('audit-metrics-table');
    if (!model || !model.metricsBySet) return empty(box);
    const rows = [['all', 'Geral'], ['0', 'Treino'], ['1', 'Validação'], ['2', 'Teste']]
      .map(([key, label]) => Object.assign({ key, label }, model.metricsBySet[key] || {}));
    box.innerHTML = tableHtml(['Recorte', 'N', 'MAE', 'RMSE', 'Viés', 'Erro máx.', 'Corr.'],
      rows.map(r => [r.label, nf.format(r.n || 0), fmtCm(r.mae), fmtCm(r.rmse), fmtCm(r.bias), fmtCm(r.maxAbs), r.corr == null ? '-' : Number(r.corr).toFixed(4).replace('.', ',')]));
  }

  function renderMainMetrics(main, audit) {
    const box = document.getElementById('audit-main-metrics');
    if (!main) {
      box.innerHTML = '<div class="audit-empty">Sem modelo equivalente no planilhão embutido para este auditável. As métricas calculadas da planilha continuam acima.</div>';
      return;
    }
    const preferred = [
      'modelo', 'familia', 'rotacao', 'combo_id', 'evento_teste', 'eventos_validacao',
      'n_inputs', 'neuronios', 'nit', 'ciclos', 'J',
      'N_geral', 'N_treino', 'N_validacao', 'N_teste',
      'PERS_geral', 'PERS_treino', 'PERS_validacao', 'PERS_teste', 'score_equilibrio',
      'MAE_geral_cm', 'MAE_validacao_cm', 'MAE_teste_cm',
      'E95_geral_cm', 'E95_validacao_cm', 'E95_teste_cm',
      'NASH_validacao_csv', 'NASH_teste_csv', 'correlacao_teste_csv',
      'fim', 'usar_decisao'
    ];
    const keys = preferred.filter(k => Object.prototype.hasOwnProperty.call(main, k))
      .concat(Object.keys(main).filter(k => !preferred.includes(k) && k !== 'inputs' && k !== 'obs'));
    const rows = keys.map(k => [humanKey(k), formatAny(main[k])]);
    if (audit && audit.sourceRef) rows.push(['Fonte auditável selecionada', audit.sourceRef]);
    box.innerHTML = tableHtml(['Campo', 'Valor'], rows);
  }

  function loadInventory() {
    if (inventory) return Promise.resolve(inventory);
    if (inventoryLoading) return inventoryLoading;
    const box = document.getElementById('audit-evidence');
    box.innerHTML = '<div class="audit-empty">Carregando inventário de logs e métricas...</div>';
    inventoryLoading = fetch(INVENTORY_URL, { cache: 'no-store' })
      .then(resp => {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(data => {
        inventory = data;
        return inventory;
      })
      .catch(err => {
        box.innerHTML = '<div class="audit-empty">Não foi possível carregar o inventário: ' + escapeHtml(err.message) + '.</div>';
        throw err;
      });
    return inventoryLoading;
  }

  function renderEvidence() {
    const box = document.getElementById('audit-evidence');
    if (!box) return;
    if (!inventory) {
      box.innerHTML = '<div class="audit-empty">Clique em “Carregar logs” para abrir o inventário completo. O pacote bruto fica disponível em <a href="' + RAW_BUNDLE_URL + '">logs_metricas_brutos.zip</a>.</div>';
      return;
    }
    const model = currentModel();
    const main = currentMainModel();
    const scoredFiles = scoreInventoryFiles(model, main, inventory.files || []).filter(x => x.score > 0).slice(0, 80);
    const logs = scoreInventoryFiles(model, main, inventory.textLogs || []).filter(x => x.score > 0).slice(0, 10);
    const csvs = scoreInventoryFiles(model, main, inventory.csvTables || []).filter(x => x.score > 0).slice(0, 8);
    const matGroups = splitMatSummaries(model, scoreInventoryFiles(model, main, inventory.matSummaries || []).filter(x => x.score > 0));
    const associatedFiles = scoredFiles.filter(x => !(x.item && x.item.ext === '.mat'));
    const summary = inventory.meta || {};
    box.innerHTML = [
      '<div class="audit-inventory-summary">',
      '<span><strong>' + nf.format(summary.fileCount || 0) + '</strong> arquivos inventariados</span>',
      '<span><strong>' + nf.format(summary.auditModelCount || 0) + '</strong> modelos com série</span>',
      '<span><strong>' + nf.format(summary.csvTableCount || 0) + '</strong> CSVs parseados</span>',
      '<span><strong>' + nf.format(summary.textLogCount || 0) + '</strong> logs/textos</span>',
      '<span><strong>' + nf.format(summary.matParsedCount || 0) + '</strong> MAT lidos</span>',
      '<span><strong>' + nf.format(summary.rawBundleFileCount || 0) + '</strong> arquivos no pacote bruto</span>',
      '</div>',
      renderDownloadPanel(model, associatedFiles),
      renderMatSummaries(matGroups.primary, matGroups.related),
      renderAssociatedFiles(associatedFiles),
      renderCsvTables(csvs),
      renderLogPreviews(logs),
      renderSkipped(inventory.skippedWorkbooks || [])
    ].join('');
  }

  function renderDownloadPanel(model, scoredFiles) {
    const workbookLinks = [];
    if (model && model.workbookUrl) {
      workbookLinks.push({
        href: model.workbookUrl,
        label: 'Baixar planilha auditavel do modelo',
        note: model.workbookFile || model.name,
        kind: 'xlsx'
      });
    }
    if (model && model.matUrl) {
      workbookLinks.push({
        href: model.matUrl,
        label: 'Baixar modelo treinado (.mat)',
        note: model.matFile || model.matSourceRef || model.name,
        kind: 'mat'
      });
    }
    scoredFiles.filter(x => x.item && x.item.downloadUrl && x.item.ext !== '.mat' && x.item.downloadUrl !== (model && model.workbookUrl))
      .slice(0, 5)
      .forEach(x => workbookLinks.push({
        href: x.item.downloadUrl,
        label: 'Baixar planilha associada',
        note: x.item.name || x.item.ref,
        kind: 'xlsx'
      }));

    const links = workbookLinks.map(x =>
      '<a class="audit-download-btn' + (x.kind === 'mat' ? ' audit-download-mat' : '') + '" href="' + escapeAttr(x.href) + '" download>' +
      '<span>' + escapeHtml(x.label) + '</span><small>' + escapeHtml(x.note || '') + '</small></a>'
    ).join('');

    return '<section class="audit-evidence-group audit-downloads">' +
      '<h4>Downloads auditaveis</h4>' +
      '<div class="audit-download-list">' +
      (links || '<div class="audit-empty">Nenhuma planilha individual encontrada para este modelo.</div>') +
      '<a class="audit-download-btn audit-download-raw" href="' + RAW_BUNDLE_URL + '" download><span>Baixar pacote bruto</span><small>logs, CSVs, JSON, TXT, M e PS1</small></a>' +
      '</div></section>';
  }

  function renderAssociatedFiles(scored) {
    if (!scored.length) return '<section class="audit-evidence-group"><h4>Arquivos associados</h4><div class="audit-empty">Nenhum arquivo associado por família/combo/rotação. Veja o inventário completo no pacote bruto.</div></section>';
    return '<section class="audit-evidence-group"><h4>Arquivos associados ao modelo/recorte</h4>' +
      tableHtml(['Tipo', 'Família', 'Arquivo', 'Tamanho', 'Modificado', 'Ação'],
        scored.slice(0, 40).map(x => [
          x.item.category || '-',
          labelFamily(x.item.family || ''),
          '<code>' + escapeHtml(x.item.ref || '') + '</code>',
          fmtBytes(x.item.size || 0),
          x.item.modified || '-',
          fileActionHtml(x.item)
        ]), true) + '</section>';
  }

  function fileActionHtml(item) {
    if (item && item.downloadUrl) {
      const isMat = item.ext === '.mat' || item.matFile || /\.mat($|\?)/i.test(String(item.downloadUrl || item.name || item.ref || ''));
      return '<a class="audit-mini-link" href="' + escapeAttr(item.downloadUrl) + '" download>' + (isMat ? 'Baixar MAT' : 'Baixar') + '</a>';
    }
    if (item && item.ext === '.mat') return '<span class="audit-muted">Resumo no bloco MAT</span>';
    return '<span class="audit-muted">No pacote bruto</span>';
  }

  function splitMatSummaries(model, scored) {
    const primary = scored.find(x => isPrimaryMat(model, x.item)) || syntheticPrimaryMat(model);
    const related = scored
      .filter(x => !isPrimaryMat(model, x.item))
      .slice(0, 10);
    return { primary, related };
  }

  function syntheticPrimaryMat(model) {
    if (!model || !model.matUrl) return null;
    return {
      item: {
        ref: model.matSourceRef || model.matFile || model.name,
        name: model.matFile || model.name,
        family: model.family,
        size: model.matSize || 0,
        downloadUrl: model.matUrl,
        matFile: model.matFile,
        ext: '.mat',
        metrics: [],
        variables: []
      },
      score: 999
    };
  }

  function isPrimaryMat(model, item) {
    if (!model || !item) return false;
    const ref = cleanRef(item.ref);
    const src = cleanRef(model.matSourceRef);
    const file = String(model.matFile || '').toLowerCase();
    if (src && ref && ref === src) return true;
    if (model.matUrl && item.downloadUrl === model.matUrl) return true;
    if (file && String(item.matFile || item.name || '').toLowerCase() === file) return true;
    return false;
  }

  function cleanRef(value) {
    return String(value || '').replace(/\\/g, '/').toLowerCase();
  }

  function renderMatSummaries(primary, related) {
    const item = primary && primary.item;
    if (!item) {
      return '<section class="audit-evidence-group"><h4>MAT principal do modelo</h4><div class="audit-empty">Sem MAT principal associado para este modelo no inventário.</div></section>';
    }
    const picked = matExtractSummary(item);
    const metrics = (item.metrics || []).filter(m => matMetricAllowed(m.name)).slice(0, 80);
    const vars = (item.variables || []).slice(0, 40);
    const metricBadges = picked.length
      ? '<div class="audit-mat-metrics">' + picked.map(kv => '<span><strong>' + escapeHtml(kv[0]) + '</strong> ' + escapeHtml(formatAny(kv[1])) + '</span>').join('') + '</div>'
      : '<div class="audit-muted">Métricas pequenas do MAT disponíveis no detalhe, quando extraídas.</div>';
    const relatedBlock = related && related.length
      ? '<details class="audit-detail audit-related-mats"><summary>Ver outros MAT parecidos encontrados no inventário (' + nf.format(related.length) + ')</summary>' +
        '<p class="audit-related-note">Esses arquivos não são novas opções do modelo selecionado; são rastros de auditoria com nomes/famílias próximos.</p>' +
        tableHtml(['MAT relacionado', 'Família', 'Tamanho', 'Ação'], related.map(x => [
          '<code>' + escapeHtml(x.item.ref || '') + '</code>',
          labelFamily(x.item.family || ''),
          fmtBytes(x.item.size || 0),
          fileActionHtml(x.item)
        ]), true) + '</details>'
      : '';
    return '<section class="audit-evidence-group"><h4>MAT principal do modelo selecionado</h4>' +
      '<div class="audit-mat-main">' +
      '<div><div class="audit-mat-label">Arquivo treinado</div><code>' + escapeHtml(item.ref || item.name || '') + '</code></div>' +
      '<div class="audit-mat-actions">' + fileActionHtml(item) + '</div>' +
      '<div><div class="audit-mat-label">Tamanho</div><strong>' + fmtBytes(item.size || 0) + '</strong></div>' +
      '<div><div class="audit-mat-label">Família</div><strong>' + escapeHtml(labelFamily(item.family || '')) + '</strong></div>' +
      '</div>' +
      metricBadges +
      '<details class="audit-detail"><summary>Ver métricas e variáveis extraídas do MAT principal</summary>' +
      '<h5>Métricas extraídas do MAT</h5>' +
      tableHtml(['Campo', 'Valor'], metrics.map(m => [m.name, formatMatValue(m.value)])) +
      '<h5>Variáveis do MAT</h5>' +
      tableHtml(['Variável', 'Dimensão', 'Classe'], vars.map(v => [
        v.name || '-',
        Array.isArray(v.shape) ? v.shape.join(' x ') : '-',
        v.class || '-'
      ])) +
      '</details>' +
      relatedBlock +
      '</section>';
  }

  function renderCsvTables(scored) {
    if (!scored.length) return '<section class="audit-evidence-group"><h4>CSVs de métricas/status associados</h4><div class="audit-empty">Sem CSV associado por chave. Os CSVs seguem no inventário bruto.</div></section>';
    return '<section class="audit-evidence-group"><h4>CSVs de métricas/status associados</h4>' + scored.map(x => {
      const rows = (x.item.rows || []).slice(0, 12);
      const cols = (x.item.columns || []).slice(0, 8);
      const body = rows.map(r => cols.map(c => formatAny(r[c])));
      return '<details class="audit-detail"><summary><code>' + escapeHtml(x.item.ref) + '</code> · ' +
        nf.format(x.item.rowCountShown || rows.length) + ' linhas' + (x.item.truncated ? ' (prévia)' : '') + '</summary>' +
        tableHtml(cols, body) + '</details>';
    }).join('') + '</section>';
  }

  function renderLogPreviews(scored) {
    if (!scored.length) return '<section class="audit-evidence-group"><h4>Logs/textos associados</h4><div class="audit-empty">Sem log textual associado por chave. O pacote bruto contém os logs encontrados.</div></section>';
    return '<section class="audit-evidence-group"><h4>Logs/textos associados</h4>' + scored.map(x => {
      const txt = x.item.truncated && x.item.tail ? x.item.tail : x.item.preview;
      return '<details class="audit-detail"><summary><code>' + escapeHtml(x.item.ref) + '</code> · ' +
        nf.format(x.item.chars || 0) + ' caracteres' + (x.item.truncated ? ' (fim do arquivo)' : '') + '</summary>' +
        '<pre>' + escapeHtml(txt || '') + '</pre></details>';
    }).join('') + '</section>';
  }

  function renderSkipped(rows) {
    if (!rows.length) return '';
    return '<section class="audit-evidence-group"><h4>Planilhas encontradas mas não lidas</h4>' +
      tableHtml(['Arquivo', 'Motivo', 'Tamanho'], rows.slice(0, 20).map(r => [
        '<code>' + escapeHtml(r.ref) + '</code>',
        r.reason || '-',
        fmtBytes(r.size || 0)
      ]), true) + '</section>';
  }

  function matExtractSummary(item) {
    const wanted = ['J', 'PERS', 'NASH', 'NASH_VAL', 'CORRELACAO', 'ERRO_RELATIVO', 'emed_abs', 'emed_abs_mean', 'e95', 'input', 'nh', 'nit', 'Cic', 'EVmin'];
    const metrics = new Map((item.metrics || []).map(m => [String(m.name || '').toUpperCase(), m.value]));
    return wanted
      .filter(name => metrics.has(name.toUpperCase()))
      .map(name => [name, metrics.get(name.toUpperCase())])
      .slice(0, 10);
  }

  function matMetricAllowed() {
    return true;
  }

  function formatMatValue(value) {
    if (Array.isArray(value)) {
      const shown = value.slice(0, 10).map(v => typeof v === 'number' ? nf.format(Math.round(v * 1000000) / 1000000) : String(v));
      return shown.join(', ') + (value.length > shown.length ? ' ... (' + nf.format(value.length) + ' valores)' : '');
    }
    if (value && typeof value === 'object') {
      const text = JSON.stringify(value);
      return text.length > 260 ? text.slice(0, 260) + '...' : text;
    }
    return formatAny(value);
  }

  function scoreInventoryFiles(model, main, items) {
    if (!items || !items.length) return [];
    const keys = matchTokens(model, main);
    return items.map(item => {
      const hay = norm([item.ref, item.name, item.family, item.rotation, item.category, (item.auditModels || []).join(' ')].join(' '));
      let score = 0;
      keys.strong.forEach(k => { if (k && hay.includes(k)) score += 12; });
      keys.medium.forEach(k => { if (k && hay.includes(k)) score += 5; });
      if (model && item.family && norm(item.family) === norm(model.family)) score += 8;
      if (main && item.family && norm(item.family) === norm(main.familia)) score += 8;
      return { item, score };
    }).sort((a, b) => b.score - a.score || String(a.item.ref).localeCompare(String(b.item.ref)));
  }

  function matchTokens(model, main) {
    const strong = [];
    const medium = [];
    if (model) {
      strong.push(norm(model.name), norm(model.id), norm(model.combo), norm(model.rotation));
      medium.push(norm(model.family), norm(model.horizon), norm(model.type));
    }
    if (main) {
      strong.push(norm(main.modelo), norm(main.combo_id), norm(main.rotacao));
      medium.push(norm(main.familia), norm(main.horizonte), norm(main.tipo));
    }
    return {
      strong: [...new Set(strong.filter(Boolean))],
      medium: [...new Set(medium.filter(Boolean))]
    };
  }

  function installModelClickBridge() {
    document.addEventListener('click', ev => {
      if (ev.target.closest('#graficos-auditaveis')) return;
      if (ev.target.closest('#m-close,#m-backdrop')) return;
      const likely = ev.target.closest('.champ,.lb-item,#tbody tr.clickable,svg rect,svg circle,svg path');
      if (!likely) return;
      const scope = inferScopeFromClick(ev.target);
      setTimeout(() => {
        const name = modalModelName();
        if (!name) return;
        const main = mainModels.find(m => norm(m.modelo) === norm(name));
        selectFromMainModel(main || { modelo: name }, scope, true);
        closeExistingModal();
      }, 80);
    }, true);
  }

  function inferScopeFromClick(target) {
    const tab = target.closest('#lb') ? document.querySelector('#lb-tabs .tab[aria-pressed="true"]') : null;
    const label = tab ? norm(tab.textContent) : '';
    if (label.includes('TESTE')) return '2';
    if (label.includes('VALID')) return '1';
    if (label.includes('TREINO')) return '0';
    return 'all';
  }

  function modalModelName() {
    const node = document.querySelector('#m-body .m-name');
    if (!node) return '';
    return node.textContent.trim();
  }

  function closeExistingModal() {
    const modal = document.getElementById('modal');
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    document.body.style.overflow = '';
  }

  function selectFromMainModel(main, scope, scroll) {
    if (!payload || !main) return;
    const match = findAuditForMain(main);
    state.mainModelName = main.modelo || '';
    state.scope = scope || 'all';
    document.getElementById('audit-scope').value = state.scope;
    if (match) {
      state.family = match.family || 'TODAS';
      state.modelId = match.id;
      document.getElementById('audit-family').value = state.family;
      fillModels();
      state.modelId = match.id;
      document.getElementById('audit-model').value = state.modelId;
      fillEvents();
    } else if (main.familia) {
      state.family = main.familia;
      document.getElementById('audit-family').value = state.family;
      state.modelId = '';
      fillModels();
    }
    renderAll();
    updateHash();
    if (scroll) {
      document.getElementById('graficos-auditaveis').scrollIntoView({ behavior: 'smooth', block: 'start' });
      loadInventory().then(renderEvidence).catch(() => {});
    }
  }

  function findAuditForMain(main) {
    if (!main) return null;
    const exact = payload.models.find(m => norm(m.name) === norm(main.modelo) || norm(m.id) === norm(main.modelo));
    if (exact) return exact;
    const combo = norm(main.combo_id);
    const rot = norm(main.rotacao);
    const fam = norm(main.familia);
    const scored = payload.models.map(m => {
      let score = 0;
      if (fam && norm(m.family) === fam) score += 25;
      if (combo && (norm(m.combo) === combo || norm(m.name).includes(combo))) score += 25;
      if (rot && (norm(m.rotation) === rot || norm(m.name).includes(rot))) score += 25;
      if (norm(m.name).includes(norm(main.modelo)) || norm(main.modelo).includes(norm(m.name))) score += 40;
      return { m, score };
    }).filter(x => x.score >= 40).sort((a, b) => b.score - a.score);
    return scored[0] && scored[0].m;
  }

  function findMainForAudit(audit) {
    if (!audit || !mainModels.length) return null;
    const exact = mainModels.find(m => norm(m.modelo) === norm(audit.name) || norm(m.modelo) === norm(audit.id));
    if (exact) return exact;
    const combo = norm(audit.combo);
    const rot = norm(audit.rotation);
    const fam = norm(audit.family);
    const scored = mainModels.map(m => {
      let score = 0;
      if (fam && norm(m.familia) === fam) score += 20;
      if (combo && (norm(m.combo_id) === combo || norm(m.modelo).includes(combo))) score += 25;
      if (rot && (norm(m.rotacao) === rot || norm(m.modelo).includes(rot))) score += 20;
      if (norm(audit.name).includes(norm(m.modelo)) || norm(m.modelo).includes(norm(audit.name))) score += 40;
      return { m, score };
    }).filter(x => x.score >= 40).sort((a, b) => b.score - a.score);
    return scored[0] && scored[0].m;
  }

  function selectFromUrlHash() {
    const params = new URLSearchParams((location.hash || '').replace(/^#/, ''));
    const model = params.get('auditModel');
    if (!model || !payload) return;
    const match = payload.models.find(m => norm(m.id) === norm(model) || norm(m.name) === norm(model));
    if (!match) return;
    state.family = match.family || 'TODAS';
    state.modelId = match.id;
    state.scope = params.get('scope') || 'all';
    const fs = document.getElementById('audit-family');
    const sc = document.getElementById('audit-scope');
    if (fs) fs.value = state.family;
    if (sc) sc.value = state.scope;
    fillModels();
  }

  function updateHash() {
    const model = currentModel();
    if (!model) return;
    const params = new URLSearchParams();
    params.set('auditModel', model.id);
    params.set('scope', state.scope);
    history.replaceState(null, '', '#' + params.toString());
  }

  function tableHtml(headers, rows, trusted) {
    return '<div class="audit-table-wrap"><table class="audit-table"><thead><tr>' +
      headers.map(h => '<th>' + escapeHtml(h) + '</th>').join('') +
      '</tr></thead><tbody>' +
      rows.map(r => '<tr>' + r.map(v => '<td>' + (trusted ? String(v) : escapeHtml(v)) + '</td>').join('') + '</tr>').join('') +
      '</tbody></table></div>';
  }

  function renderLegend(id, items) {
    const box = document.getElementById(id);
    if (!box) return;
    box.replaceChildren(...items.map(([label, color]) => {
      const s = document.createElement('span');
      s.innerHTML = '<i class="audit-swatch" style="background:' + color + '"></i>' + escapeHtml(label);
      return s;
    }));
  }

  function empty(box) {
    const div = document.createElement('div');
    div.className = 'audit-empty';
    div.textContent = 'Sem pontos auditáveis neste recorte.';
    box.append(div);
  }

  function option(value, label) {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    return opt;
  }

  function labelFamily(f) {
    return String(f || 'OUTROS').replace(/_/g, ' ');
  }

  function labelModel(m) {
    return labelFamily(m.family) + ' | ' + m.name + ' | MAE ' + fmtCm(m.metrics.mae);
  }

  function humanKey(k) {
    return String(k).replace(/_/g, ' ').replace(/\bcm\b/i, '(cm)').replace(/\bcsv\b/i, 'CSV').replace(/\bpers\b/i, 'PERS').replace(/\bnash\b/i, 'NASH');
  }

  function formatAny(v) {
    if (v == null || v === '') return '-';
    if (typeof v === 'number') return nf.format(Math.round(v * 10000) / 10000);
    if (Array.isArray(v)) return v.join(', ');
    return String(v);
  }

  function fmtCm(v) {
    return v == null ? '-' : nf.format(Math.round(v)) + ' cm';
  }

  function fmtBytes(v) {
    if (v >= 1024 * 1024) return nf.format(Math.round(v / 1024 / 102.4) / 10) + ' MB';
    if (v >= 1024) return nf.format(Math.round(v / 102.4) / 10) + ' kB';
    return nf.format(v) + ' B';
  }

  function fmtShort(v) {
    if (Math.abs(v) >= 1000) return nf.format(Math.round(v / 100) / 10) + 'k';
    return nf.format(Math.round(v));
  }

  function fmtDate(value) {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? match[3] + '/' + match[2] + '/' + match[1] : '';
  }

  function fmtMonthYear(value) {
    const months = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    const match = String(value || '').match(/^(\d{4})-(\d{2})-/);
    if (!match) return '';
    const index = Number(match[2]) - 1;
    return months[index] ? months[index] + '/' + match[1].slice(2) : '';
  }

  function eventLabel(ev, full) {
    const base = 'Evento ' + (ev && ev.evento != null ? ev.evento : '-');
    if (!ev) return base;
    if (!full) {
      const month = fmtMonthYear(ev.start);
      return base + (month ? ' · ' + month : '');
    }
    const start = fmtDate(ev.start);
    const end = fmtDate(ev.end);
    const period = start && end ? start + ' a ' + end : start;
    return base + (period ? ' · ' + period : '');
  }

  function scale(a, b, x0, x1) {
    const span = b - a || 1;
    return v => x0 + (x1 - x0) * ((v - a) / span);
  }

  function ticks(min, max, n) {
    const span = Math.max(1, max - min);
    const raw = span / n;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].find(m => raw <= m * pow) * pow;
    const start = Math.ceil(min / step) * step;
    const out = [];
    for (let t = start; t <= max + step * 0.001; t += step) out.push(Math.round(t * 1000) / 1000);
    return out;
  }

  function pathLine(points) {
    return points.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  }

  function setColor(code) {
    return code === 2 ? COLORS.teste : code === 1 ? COLORS.validacao : code === 0 ? COLORS.treino : '#777';
  }

  function svgEl(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, v));
    return el;
  }

  function svgText(svg, x, y, text, cls, anchor) {
    const t = svgEl('text', { x, y, class: cls || '', 'text-anchor': anchor || 'start' });
    t.textContent = text;
    svg.append(t);
    return t;
  }

  function norm(value) {
    return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
