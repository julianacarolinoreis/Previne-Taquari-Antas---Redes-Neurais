/* PREVINE · leitura operacional compartilhada (coordenação + campo).
   Pesquisa ≠ alerta oficial. UNKNOWN/STALE nunca significa “não vai inundar”. */
(function (global) {
  'use strict';

  var CHECKLIST_KEY = 'previne_resposta_checklist_v1';
  var ST_MESA_KEY = 'previne:stz-v002:exercise:v3';
  var ST_MESA_SCHEMA = 1;
  var DECISION_LOG_KEY = 'previne_resposta_decisions_v1';
  var CHECKLIST_ITEMS = [
    { id: 'forecast', label: 'Previsão e telemetria conferidas (fonte, horário, idade)' },
    { id: 'spatial', label: 'Zona/perigo espacial revisado (HAND ≠ inundação oficial)' },
    { id: 'routes', label: 'Ruas, pontes e corredores confirmados em campo' },
    { id: 'shelter', label: 'Abrigo: capacidade, acessibilidade e abertura verificadas' },
    { id: 'people', label: 'Pessoas prioritárias mapeadas (sem nomes no site)' },
    { id: 'comms', label: 'Canal oficial de comunicação acordado (DC/SGB/prefeitura)' },
    { id: 'resources', label: 'Equipe, veículos e suprimentos disponíveis' }
  ];

  var PLACES = {
    santa: {
      key: 'santa',
      label: 'Santa Tereza',
      code: '86472600',
      threshold: 1500,
      live: 'previsao_ao_vivo.json',
      mapa: 'santa_tereza_previsao_inundacao.html',
      rota: 'pesquisas/santa-tereza-rota-fuga-ruas.html',
      mesa: 'pesquisas/estudo-caso-resposta-santa-tereza.html',
      ficha: 'pesquisa_status.html'
    },
    mucum: {
      key: 'mucum',
      label: 'Muçum',
      code: '86510000',
      threshold: 1800,
      live: 'previsao_ao_vivo_mucum.json',
      mapa: 'mucum_previsao_inundacao.html',
      rota: 'pesquisas/mucum-rota-fuga-ruas.html',
      mesa: 'pesquisas/estudo-caso-resposta-mucum.html',
      ficha: 'pesquisa_status_mucum.html'
    }
  };

  var JUSANTE = {
    encantado: {
      key: 'encantado',
      label: 'Encantado',
      codIbge: '4306809',
      ficha: 'pesquisa_status_encantado.html',
      zenodoPoints: 91
    },
    roca_sales: {
      key: 'roca_sales',
      label: 'Roca Sales',
      codIbge: '4315800',
      ficha: 'pesquisa_status_roca_sales.html',
      zenodoPoints: 109
    },
    lajeado: {
      key: 'lajeado',
      label: 'Lajeado',
      codIbge: '4311403',
      ficha: 'pesquisa_status_lajeado.html',
      zenodoPoints: 15
    }
  };

  function num(v) {
    if (v == null || (typeof v === 'string' && v.trim() === '')) return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function parseDate(value) {
    if (value == null || value === '') return null;
    var s = String(value).trim().replace(' ', 'T');
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) s += 'T00:00:00';
    if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += '-03:00';
    var d = new Date(s);
    return Number.isFinite(d.getTime()) ? d : null;
  }

  function fmtLevel(cm) {
    var n = num(cm);
    return n == null ? 'UNKNOWN' : Math.round(n).toLocaleString('pt-BR') + ' cm';
  }

  function fmtWhen(value) {
    var d = parseDate(value);
    return d
      ? d.toLocaleString('pt-BR', {
          timeZone: 'America/Sao_Paulo',
          day: '2-digit',
          month: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        })
      : '—';
  }

  function classifyFreshness(feed) {
    var age = num(feed && (feed.idade_telemetria_min != null ? feed.idade_telemetria_min : feed.idade_leitura_min));
    var status = String((feed && feed.status_dados) || '').toLowerCase();
    if (!feed || feed.disponivel === false) return { kind: 'unknown', label: 'UNKNOWN', detail: 'Feed indisponível' };
    if (status.indexOf('atras') >= 0 || status.indexOf('stale') >= 0) return { kind: 'stale', label: 'STALE', detail: 'Telemetria atrasada' };
    if (age != null && age > 180) return { kind: 'stale', label: 'STALE', detail: 'Leitura com mais de 3 h' };
    if (age == null && !feed.nivel_rio_agora_cm) return { kind: 'unknown', label: 'UNKNOWN', detail: 'Sem nível publicado' };
    return { kind: 'fresh', label: 'RECENTE', detail: age != null ? 'Atualizado há ~' + age + ' min' : 'Telemetria publicada' };
  }

  function readMesaValidation() {
    try {
      var raw = localStorage.getItem(ST_MESA_KEY);
      if (!raw) return null;
      var saved = JSON.parse(raw);
      if (!saved || saved.schema_version !== ST_MESA_SCHEMA) return null;
      return saved.validation && typeof saved.validation === 'object' ? saved.validation : null;
    } catch (e) {
      return null;
    }
  }

  function writeMesaValidation(patch) {
    try {
      var raw = localStorage.getItem(ST_MESA_KEY);
      var saved = raw ? JSON.parse(raw) : null;
      if (!saved || saved.schema_version !== ST_MESA_SCHEMA) {
        saved = {
          schema_version: ST_MESA_SCHEMA,
          saved_at: new Date().toISOString(),
          validation: {}
        };
      }
      saved.validation = Object.assign({}, saved.validation || {}, patch);
      saved.saved_at = new Date().toISOString();
      localStorage.setItem(ST_MESA_KEY, JSON.stringify(saved));
      return true;
    } catch (e) {
      return false;
    }
  }

  function mergeChecklistSources() {
    var state = {};
    try {
      var raw = localStorage.getItem(CHECKLIST_KEY);
      if (raw) state = JSON.parse(raw) || {};
    } catch (e) { /* ignore */ }
    var mesa = readMesaValidation();
    if (mesa) {
      CHECKLIST_ITEMS.forEach(function (item) {
        if (mesa[item.id]) state[item.id] = true;
      });
    }
    return state;
  }

  function loadChecklist() {
    return mergeChecklistSources();
  }

  function saveChecklist(state) {
    try {
      localStorage.setItem(CHECKLIST_KEY, JSON.stringify(state));
    } catch (e) { /* quota / private mode */ }
    var mesaPatch = {};
    CHECKLIST_ITEMS.forEach(function (item) {
      mesaPatch[item.id] = !!state[item.id];
    });
    writeMesaValidation(mesaPatch);
  }

  function checklistProgress(state) {
    var done = CHECKLIST_ITEMS.filter(function (item) { return !!state[item.id]; }).length;
    return { done: done, total: CHECKLIST_ITEMS.length, pct: Math.round((done / CHECKLIST_ITEMS.length) * 100) };
  }

  function loadDecisionLog() {
    try {
      var raw = localStorage.getItem(DECISION_LOG_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function appendDecision(entry) {
    var log = loadDecisionLog();
    var row = Object.assign({
      id: 'd-' + Date.now(),
      at: new Date().toISOString(),
      place: '',
      action: '',
      note: '',
      observer: ''
    }, entry || {});
    log.unshift(row);
    if (log.length > 200) log.length = 200;
    try {
      localStorage.setItem(DECISION_LOG_KEY, JSON.stringify(log));
    } catch (e) { /* ignore */ }
    return row;
  }

  function clearDecisionLog() {
    try { localStorage.removeItem(DECISION_LOG_KEY); } catch (e) { /* ignore */ }
  }

  function csvEscape(value) {
    var s = value == null ? '' : String(value);
    if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function exportDecisionCsv(options) {
    options = options || {};
    var log = loadDecisionLog();
    var checklist = loadChecklist();
    var prog = checklistProgress(checklist);
    var lines = [
      ['exported_at', 'place', 'action', 'note', 'observer', 'decision_at'].map(csvEscape).join(','),
    ];
    log.forEach(function (row) {
      lines.push([
        row.at,
        row.place,
        row.action,
        row.note,
        row.observer,
        row.at
      ].map(csvEscape).join(','));
    });
    lines.push('');
    lines.push(['checklist_item', 'checked'].map(csvEscape).join(','));
    CHECKLIST_ITEMS.forEach(function (item) {
      lines.push([item.id, checklist[item.id] ? 'yes' : 'no'].map(csvEscape).join(','));
    });
    lines.push('');
    lines.push(['checklist_done', 'checklist_total', 'checklist_pct'].map(csvEscape).join(','));
    lines.push([prog.done, prog.total, prog.pct].map(csvEscape).join(','));
    if (options.includeMesaLog) {
      try {
        var raw = localStorage.getItem(ST_MESA_KEY);
        if (raw) {
          var saved = JSON.parse(raw);
          if (saved && Array.isArray(saved.log)) {
            lines.push('');
            lines.push(['mesa_time', 'mesa_text'].map(csvEscape).join(','));
            saved.log.forEach(function (item) {
              lines.push([item.time, item.text].map(csvEscape).join(','));
            });
          }
        }
      } catch (e) { /* ignore */ }
    }
    return lines.join('\n');
  }

  function downloadCsv(filename, content) {
    var blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function fetchLive(placeKey) {
    var place = PLACES[placeKey];
    if (!place) return Promise.resolve(null);
    return fetch(place.live, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function summarizePlace(feed, placeKey) {
    var place = PLACES[placeKey];
    var fresh = classifyFreshness(feed || {});
    var level = feed ? (feed.nivel_rio_agora_cm != null ? feed.nivel_rio_agora_cm : feed.telemetria_ultima_nivel_cm) : null;
    var pred = feed ? (feed.nivel_previsto_cm != null ? feed.nivel_previsto_cm : feed.nivel_modelo_cm) : null;
    var threshold = place.threshold;
    var gap = num(level) != null && num(threshold) != null ? threshold - num(level) : null;
    return {
      place: place,
      freshness: fresh,
      levelCm: level,
      levelLabel: fmtLevel(level),
      predLabel: fmtLevel(pred),
      levelAt: feed ? (feed.nivel_rio_agora_em || feed.telemetria_ultima_em) : null,
      levelAtLabel: fmtWhen(feed ? (feed.nivel_rio_agora_em || feed.telemetria_ultima_em) : null),
      horizon: feed ? (feed.rotulo || feed.horizonte || '—') : '—',
      statusDados: feed ? (feed.status_dados || '—') : '—',
      gapToThreshold: gap,
      gapLabel: gap == null ? '—' : gap.toLocaleString('pt-BR') + ' cm até cota ' + threshold.toLocaleString('pt-BR') + ' cm'
    };
  }

  function statusBrief(summary) {
    return [
      'PREVINE · leitura de pesquisa · não é alerta oficial',
      summary.place.label + ' · estação ' + summary.place.code,
      'Nível: ' + summary.levelLabel + ' (' + summary.freshness.label + ')',
      'Previsão RNA ' + summary.horizon + ': ' + summary.predLabel,
      'Margem até cota de pesquisa: ' + summary.gapLabel,
      'Atualizado: ' + summary.levelAtLabel
    ].join('\n');
  }

  global.PREVINE_RESPOSTA = {
    CHECKLIST_ITEMS: CHECKLIST_ITEMS,
    CHECKLIST_KEY: CHECKLIST_KEY,
    ST_MESA_KEY: ST_MESA_KEY,
    DECISION_LOG_KEY: DECISION_LOG_KEY,
    PLACES: PLACES,
    JUSANTE: JUSANTE,
    loadChecklist: loadChecklist,
    saveChecklist: saveChecklist,
    checklistProgress: checklistProgress,
    readMesaValidation: readMesaValidation,
    appendDecision: appendDecision,
    loadDecisionLog: loadDecisionLog,
    clearDecisionLog: clearDecisionLog,
    exportDecisionCsv: exportDecisionCsv,
    downloadCsv: downloadCsv,
    fetchLive: fetchLive,
    summarizePlace: summarizePlace,
    statusBrief: statusBrief,
    fmtLevel: fmtLevel,
    classifyFreshness: classifyFreshness
  };
})(typeof window !== 'undefined' ? window : globalThis);
