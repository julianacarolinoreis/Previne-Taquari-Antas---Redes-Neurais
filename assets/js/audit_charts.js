(function () {
  // Lightweight safety patch: keep the page responsive on mobile.
  // The 36 MB audit series file is still available through the model modal,
  // but it is no longer downloaded automatically as soon as the page opens.
  for (let id = 1; id < 10000; id += 1) {
    clearTimeout(id);
  }

  const nf = new Intl.NumberFormat('pt-BR');
  const POSITIVE_PERS_KEYS = ['PERS_geral', 'PERS_treino', 'PERS_validacao', 'PERS_teste'];

  function init() {
    enforceLightAndLayout();
    rewriteIntroForResults();
    installAuditOpenHint();
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
    const mainModels = readMainModels();
    const kpis = document.getElementById('kpis');
    if (kpis) kpis.setAttribute('data-audit-hide', 'true');

    rewriteStaticCopy(mainModels.length || 158);

    document.querySelectorAll('.step, .s-card, .steps > *, article, .card').forEach(el => {
      const text = norm(el.textContent);
      if (text.includes('PROXIMO_PASSO') && text.includes('DISPERSOES_E_SUBIDAS')) {
        el.setAttribute('data-audit-hide', 'true');
      }
    });
    document.querySelectorAll('#soon, .soon, [id*="soon"], .m-soon').forEach(el => {
      el.setAttribute('data-audit-hide', 'true');
    });
  }

  function rewriteStaticCopy(modelCount) {
    const sub = document.querySelector('header .sub');
    if (sub) {
      sub.innerHTML = 'Varredura dos modelos RNA treinados para prever o nível do rio na bacia Taquari-Antas com antecedência de 2h, 4h, 8h e 12h, integrando planilhão, planilhas auditáveis, arquivos <span style="font-variant-numeric:tabular-nums">.mat</span>, logs, CSVs e métricas rastreáveis.';
    }

    const stamp = document.getElementById('stamp');
    if (stamp) {
      stamp.textContent = 'Pesquisa em desenvolvimento · ' + nf.format(modelCount) + ' modelos com todos os PERS positivos no planilhão principal · base atualizada em 05/07/2026';
    }

    const src = document.getElementById('src');
    if (src) {
      src.textContent = 'Dados integrados: planilhão principal, planilhas auditáveis ponto a ponto, arquivos MAT, logs e CSVs de status/resultado. Clique em qualquer modelo para abrir a ficha auditável com gráficos, métricas e fontes associadas.';
    }

    rewriteStep('PASSO_3', {
      title: 'Famílias e montagens testadas',
      text: 'As famílias são lidas por horizonte e por montagem: ALT e CONV não são um ranking único, mas formas diferentes de montar os inputs. A CONV preserva a leitura clássica das estações da bacia; a ALT concentra e reorganiza defasagens de Santa Tereza, montante e variáveis associadas. Cada comparação precisa ser conferida junto da rotação de eventos, das métricas e dos arquivos auditáveis.'
    });

    setSectionSub('Desempenho por família',
      'Leitura comparativa por família e métrica. As barras ajudam a localizar modelos de interesse, mas a escolha precisa ser conferida na ficha auditável: dispersão, ondas, subidas, planilha, MAT, logs e CSVs associados.');
    setSectionSub('Modelo de referência de cada família',
      'Um modelo representativo por família, escolhido para inspeção. Use como ponto de entrada para auditoria, não como decisão final isolada.');
    setSectionSub('Principais achados',
      'Síntese do planilhão principal, complementada pela ficha auditável de cada modelo com séries ponto a ponto, arquivos e métricas.');
    setSectionTitle('Exploração dos 239 modelos', 'Exploração dos modelos com PERS positivos');

    replaceTextNode('.lb-note', 'A barra mostra o valor relativo dentro da família; clique no modelo para abrir gráficos, métricas e arquivos auditáveis.');
    rewriteChartTitle('Inputs mais usados pelos melhores modelos', 'Inputs mais frequentes no recorte');
    rewriteChartSubtitle('% de modelos que usam cada input', '% de modelos que usam cada input no recorte selecionado');
    rewriteChartTitle('Ranking — top 12 pelo score de equilíbrio', 'Modelos para inspeção pelo score de equilíbrio');
  }

  function installAuditOpenHint() {
    document.addEventListener('click', ev => {
      const row = ev.target.closest('.champ,.lb-item,#tbody tr.clickable,svg rect,svg circle,svg path');
      if (!row) return;
      setTimeout(() => {
        const box = document.getElementById('m-audit');
        if (!box || box.querySelector('.audit-demand-note')) return;
        const note = document.createElement('div');
        note.className = 'm-load audit-demand-note';
        note.textContent = 'As séries auditáveis são carregadas sob demanda para o celular não travar ao abrir a página.';
        box.prepend(note);
      }, 120);
    }, true);
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

  function norm(value) {
    return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
