/* PREVINE · leitura operacional compartilhada (coordenação + campo).
   Pesquisa ≠ alerta oficial. UNKNOWN/STALE nunca significa “não vai inundar”. */
(function (global) {
  'use strict';

  var CHECKLIST_KEY = 'previne_resposta_checklist_v1';
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
      mesa: 'pesquisas/mucum-painel-evacuacao.html',
      ficha: 'pesquisa_status_mucum.html'
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

  function loadChecklist() {
    try {
      var raw = localStorage.getItem(CHECKLIST_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function saveChecklist(state) {
    try {
      localStorage.setItem(CHECKLIST_KEY, JSON.stringify(state));
    } catch (e) { /* quota / private mode */ }
  }

  function checklistProgress(state) {
    var done = CHECKLIST_ITEMS.filter(function (item) { return !!state[item.id]; }).length;
    return { done: done, total: CHECKLIST_ITEMS.length, pct: Math.round((done / CHECKLIST_ITEMS.length) * 100) };
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
    PLACES: PLACES,
    loadChecklist: loadChecklist,
    saveChecklist: saveChecklist,
    checklistProgress: checklistProgress,
    fetchLive: fetchLive,
    summarizePlace: summarizePlace,
    statusBrief: statusBrief,
    fmtLevel: fmtLevel,
    classifyFreshness: classifyFreshness
  };
})(typeof window !== 'undefined' ? window : globalThis);
