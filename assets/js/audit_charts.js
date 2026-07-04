(function () {
  const DATA_URL = 'assets/data/auditaveis_series.json';
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
  const SET_NAMES = ['Treino', 'Validacao', 'Teste', 'Outro'];
  const FAMILY_ORDER = ['2H_ALT', '2H_CONV', '4H_ALT', '4H_CONV', '8H_ALT', '8H_CONV', '12H_ALT', '12H_CONV'];
  const nf = new Intl.NumberFormat('pt-BR');

  let payload = null;
  let state = { family: 'TODAS', modelId: '', eventKey: '' };

  function init() {
    const wrap = document.querySelector('.wrap') || document.body;
    const notes = document.querySelector('.notes');
    const section = document.createElement('section');
    section.className = 'sec audit-sec';
    section.id = 'graficos-auditaveis';
    section.innerHTML = [
      '<h2>Gráficos dos auditáveis</h2>',
      '<p class="sec-sub">Séries ponto a ponto extraídas das planilhas auditáveis: observado x RNA, evolução por evento e subidas de nível.</p>',
      '<div class="audit-toolbar">',
      '  <div class="audit-field"><label for="audit-model">Modelo</label><select id="audit-model"></select></div>',
      '  <div class="audit-field"><label for="audit-family">Família</label><select id="audit-family"></select></div>',
      '  <div class="audit-field"><label for="audit-event">Evento</label><select id="audit-event"></select></div>',
      '</div>',
      '<div class="audit-kpis" id="audit-kpis"></div>',
      '<div class="audit-grid">',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Observado x RNA</div><div class="audit-sub">Cada ponto é uma linha auditável do modelo selecionado</div></figcaption><div class="audit-legend" id="audit-leg-scatter"></div><div class="audit-chart" id="audit-scatter"></div></figure>',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Série do evento</div><div class="audit-sub">Nível observado e previsto ao longo do evento escolhido</div></figcaption><div class="audit-legend" id="audit-leg-series"></div><div class="audit-chart" id="audit-series"></div></figure>',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Subida do evento</div><div class="audit-sub">Variação acumulada em relação ao início do evento</div></figcaption><div class="audit-legend" id="audit-leg-rise"></div><div class="audit-chart" id="audit-rise"></div></figure>',
      '  <figure class="audit-card"><figcaption><div class="audit-title">Maiores subidas observadas</div><div class="audit-sub">Eventos com maior aumento de nível nas planilhas auditáveis</div></figcaption><div class="audit-chart" id="audit-top-rises"></div></figure>',
      '</div>',
      '<p class="audit-note" id="audit-note"></p>'
    ].join('');
    if (notes && notes.parentNode) notes.parentNode.insertBefore(section, notes);
    else wrap.appendChild(section);

    fetch(DATA_URL, { cache: 'no-store' })
      .then(resp => {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(data => {
        payload = data;
        setupControls();
        renderAll();
      })
      .catch(err => {
        section.querySelector('#audit-scatter').innerHTML =
          '<div class="audit-empty">Não foi possível carregar a base dos auditáveis: ' + escapeHtml(err.message) + '.</div>';
      });
  }

  function setupControls() {
    const families = ['TODAS'].concat([...new Set(payload.models.map(m => m.family || 'OUTROS'))]
      .sort((a, b) => (FAMILY_ORDER.indexOf(a) < 0 ? 99 : FAMILY_ORDER.indexOf(a)) -
                      (FAMILY_ORDER.indexOf(b) < 0 ? 99 : FAMILY_ORDER.indexOf(b))));
    const familySelect = document.getElementById('audit-family');
    familySelect.replaceChildren(...families.map(f => option(f, f === 'TODAS' ? 'Todas' : labelFamily(f))));
    familySelect.value = state.family;
    familySelect.addEventListener('change', () => {
      state.family = familySelect.value;
      state.modelId = '';
      fillModels();
      renderAll();
    });

    document.getElementById('audit-model').addEventListener('change', ev => {
      state.modelId = ev.target.value;
      fillEvents();
      renderAll();
    });
    document.getElementById('audit-event').addEventListener('change', ev => {
      state.eventKey = ev.target.value;
      renderAll();
    });

    fillModels();
  }

  function fillModels() {
    const modelSelect = document.getElementById('audit-model');
    const rows = filteredModels().sort((a, b) => {
      const ac = a.metrics.corr == null ? -2 : a.metrics.corr;
      const bc = b.metrics.corr == null ? -2 : b.metrics.corr;
      return (bc - ac) || ((a.metrics.mae || 1e9) - (b.metrics.mae || 1e9));
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
        ? 'Evento ' + ev.evento + ' - ' + ev.conjunto + ' | subida ' + fmtCm(ev.riseObs) + ' | MAE ' + fmtCm(ev.mae)
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

  function renderAll() {
    if (!payload) return;
    const model = currentModel();
    renderKpis(model);
    renderLegend('audit-leg-scatter', [
      ['Treino', COLORS.treino], ['Validacao', COLORS.validacao], ['Teste', COLORS.teste]
    ]);
    renderLegend('audit-leg-series', [['Observado', COLORS.obs], ['RNA', COLORS.rna]]);
    renderLegend('audit-leg-rise', [['Subida observada', COLORS.riseObs], ['Subida RNA', COLORS.riseRna]]);
    renderScatter(model);
    renderSeries(model);
    renderRise(model);
    renderTopRises();
    const note = document.getElementById('audit-note');
    note.textContent = 'Base gerada em ' + payload.meta.generatedAt + ': ' +
      nf.format(payload.meta.modelCount) + ' modelos, ' +
      nf.format(payload.meta.pointCount) + ' pontos auditáveis, famílias ' +
      Object.entries(payload.meta.families).map(([k, v]) => labelFamily(k) + ' (' + v + ')').join(', ') + '.';
  }

  function renderKpis(model) {
    const box = document.getElementById('audit-kpis');
    if (!model) {
      box.innerHTML = '<div class="audit-empty">Nenhum modelo encontrado para o filtro atual.</div>';
      return;
    }
    const items = [
      ['Pontos auditáveis', nf.format(model.metrics.n)],
      ['MAE geral', fmtCm(model.metrics.mae)],
      ['Erro máximo', fmtCm(model.metrics.maxAbs)],
      ['Correlação', model.metrics.corr == null ? '-' : model.metrics.corr.toFixed(3).replace('.', ',')],
      ['Viés médio', fmtCm(model.metrics.bias)]
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
    if (!model || !model.scatter || !model.scatter.length) return empty(box);
    const W = 620, H = 330, pad = { l: 54, r: 18, t: 18, b: 42 };
    const vals = model.scatter.flatMap(p => [p[0], p[1]]).filter(v => typeof v === 'number');
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
    model.scatter.forEach(p => {
      svg.append(svgEl('circle', {
        cx: x(p[0]), cy: y(p[1]), r: 3.2,
        fill: setColor(p[2]), opacity: p[2] === 2 ? 0.78 : 0.45
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
      columns: [{ i: 1, color: COLORS.obs, label: 'Observado' }, { i: 2, color: COLORS.rna, label: 'RNA' }],
      yLabel: 'Nivel (cm)',
      aria: 'Série temporal do evento'
    });
  }

  function renderRise(model) {
    const box = document.getElementById('audit-rise');
    box.replaceChildren();
    const rows = model && model.series && model.series[state.eventKey];
    if (!rows || !rows.length) return empty(box);
    renderLineChart(box, rows, {
      columns: [{ i: 4, color: COLORS.riseObs, label: 'Subida observada' }, { i: 5, color: COLORS.riseRna, label: 'Subida RNA' }],
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
    const rows = (payload.eventRiseTop || []).slice(0, 12);
    if (!rows.length) return empty(box);
    const W = 620, rowH = 24, H = 34 + rows.length * rowH + 28, pad = { l: 112, r: 46, t: 14, b: 22 };
    const maxV = Math.max(...rows.map(r => r.riseObs || 0), 1);
    const x = scale(0, maxV, pad.l, W - pad.r);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Maiores subidas observadas por evento' });
    ticks(0, maxV, 4).forEach(t => {
      svg.append(svgEl('line', { x1: x(t), x2: x(t), y1: pad.t, y2: H - pad.b, class: 'audit-gridline' }));
      svgText(svg, x(t), H - 5, fmtShort(t), 'audit-axis', 'middle');
    });
    rows.forEach((r, i) => {
      const y = pad.t + i * rowH + 6;
      svgText(svg, pad.l - 9, y + 12, 'Evento ' + r.evento, 'audit-label', 'end');
      const width = Math.max(1, x(r.riseObs || 0) - pad.l);
      svg.append(svgEl('rect', { x: pad.l, y, width, height: 16, rx: 4, fill: COLORS.bar, opacity: 0.86 }));
      svgText(svg, pad.l + width + 6, y + 12, fmtCm(r.riseObs), 'audit-value', 'start');
    });
    box.append(svg);
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
    return String(f || 'OUTROS').replace('_', ' ');
  }

  function labelModel(m) {
    return labelFamily(m.family) + ' | ' + m.name + ' | MAE ' + fmtCm(m.metrics.mae);
  }

  function fmtCm(v) {
    return v == null ? '-' : nf.format(Math.round(v)) + ' cm';
  }

  function fmtShort(v) {
    if (Math.abs(v) >= 1000) return nf.format(Math.round(v / 100) / 10) + 'k';
    return nf.format(Math.round(v));
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

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
