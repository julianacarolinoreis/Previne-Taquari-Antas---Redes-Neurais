/* PREVINE · Mesa Muçum V002 — plantão, zonas, scoreboard e exportação. */
(function (global) {
  'use strict';

  var R = global.PREVINE_RESPOSTA;
  var MUC_MESA_KEY = 'previne:muc-v002:exercise:v1';
  var MUC_MESA_SCHEMA = 1;

  function $(id) { return document.getElementById(id); }

  function setText(id, text) {
    var el = $(id);
    if (el) el.textContent = text == null ? '—' : String(text);
  }

  function fmtM(cm) {
    if (cm == null || !Number.isFinite(Number(cm))) return '—';
    return (Number(cm) / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' m';
  }

  function readState() {
    try {
      var raw = localStorage.getItem(MUC_MESA_KEY);
      if (!raw) return null;
      var s = JSON.parse(raw);
      return s && s.schema_version === MUC_MESA_SCHEMA ? s : null;
    } catch (e) { return null; }
  }

  function writeState(patch) {
    var base = readState() || {
      schema_version: MUC_MESA_SCHEMA,
      saved_at: new Date().toISOString(),
      mode: 'cenario',
      timeline_min: 0,
      zone_id: 'Z-01',
      validation: {},
      metrics: {},
      log: []
    };
    Object.assign(base, patch || {});
    base.saved_at = new Date().toISOString();
    try { localStorage.setItem(MUC_MESA_KEY, JSON.stringify(base)); } catch (e) { /* ignore */ }
    return base;
  }

  function horizonFromFeed(feed, slot) {
    if (!feed || !feed.horizontes) return null;
    return feed.horizontes[slot] || null;
  }

  function renderHorizons(feed) {
    var h2 = horizonFromFeed(feed, '2h') || feed;
    var h8 = horizonFromFeed(feed, '8h');
    var h8s = horizonFromFeed(feed, '8h_versao_b');
    setText('h2-level', fmtM(h2.nivel_previsto_cm != null ? h2.nivel_previsto_cm : h2.nivel_modelo_cm));
    setText('h2-model', (h2.modelo || '—').slice(0, 42));
    setText('h8-level', h8 ? fmtM(h8.nivel_previsto_cm) : '—');
    setText('h8-model', h8 ? (h8.modelo || '—').slice(0, 42) : '—');
    setText('h8s-level', h8s ? fmtM(h8s.nivel_previsto_cm) : '—');
    setText('h8s-model', h8s ? (h8s.modelo || '—').slice(0, 42) : '—');
    setText('h8s-badge', h8s && h8s.modelo_papel === 'comparativo' ? 'SOMBRA · rank 2' : 'SOMBRA');
  }

  function renderSaceClock(feed) {
    var age = feed && (feed.idade_telemetria_min != null ? feed.idade_telemetria_min : feed.idade_leitura_min);
    var fresh = R.classifyFreshness(feed || {});
    setText('sace-age', age != null ? age + ' min' : '—');
    setText('sace-status', R.freshnessLabelPt(fresh));
    setText('sace-station', feed ? feed.estacao + ' · ANA-SACE' : '86510000 · ANA-SACE');
    var badge = $('fresh-badge');
    if (badge) {
      badge.textContent = R.freshnessLabelPt(fresh);
      badge.className = 'fresh' + (fresh.kind === 'stale' ? ' stale' : (fresh.kind === 'unknown' ? ' unknown' : ''));
    }
  }

  function renderProxyMontante(feedMuc, feedSt) {
    var stLevel = feedSt ? (feedSt.nivel_rio_agora_cm || feedSt.telemetria_ultima_nivel_cm) : null;
    setText('proxy-st-level', R.fmtLevel(stLevel));
    setText('proxy-st-note', feedSt
      ? 'Montante ST · leitura ' + R.fmtWhen(feedSt.nivel_rio_agora_em || feedSt.telemetria_ultima_em)
      : 'Feed ST indisponível — proxy não substitui telemetria local');
  }

  function renderZones(contract, selectedId) {
    var zones = (contract && contract.zones) || [];
    var box = $('zone-grid');
    if (!box) return;
    box.innerHTML = zones.map(function (z) {
      var sel = z.id === selectedId ? ' zone-selected' : '';
      return '<button type="button" class="zone-card' + sel + '" data-zone="' + z.id + '">' +
        '<span class="zone-id">' + z.id + '</span>' +
        '<strong>' + z.label + '</strong>' +
        '<span>~' + z.population.toLocaleString('pt-BR') + ' pessoas · HAND ~' + z.hand_m + ' m</span>' +
        '</button>';
    }).join('');
    box.querySelectorAll('[data-zone]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        writeState({ zone_id: btn.getAttribute('data-zone') });
        renderZones(contract, btn.getAttribute('data-zone'));
        renderScoreboard(readState(), contract);
      });
    });
    var z = zones.find(function (x) { return x.id === selectedId; }) || zones[0];
    if (z) {
      setText('zone-detail', z.id + ' · ' + z.label + ' · ~' + z.population + ' pessoas · ' + z.homes + ' dom.');
    }
  }

  function renderTimeline(contract, offsetMin) {
    var tl = (contract && contract.timeline) || [];
    var track = $('timeline-track');
    if (!track) return;
    track.innerHTML = tl.map(function (step) {
      var cls = step.offset_min < offsetMin ? ' done' : (step.offset_min === offsetMin ? ' current' : '');
      return '<button type="button" class="tl-step' + cls + '" data-offset="' + step.offset_min + '">' +
        '<span>' + step.label + '</span><small>' + step.phase + '</small></button>';
    }).join('');
    track.querySelectorAll('[data-offset]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var off = Number(btn.getAttribute('data-offset'));
        writeState({ timeline_min: off });
        renderTimeline(contract, off);
        setText('timeline-decision', (tl.filter(function (s) { return s.offset_min === off; })[0] || {}).decision || '—');
      });
    });
    var cur = tl.filter(function (s) { return s.offset_min === offsetMin; })[0] || tl[0];
    setText('event-clock', cur ? cur.label : 'T+00:00');
    setText('timeline-decision', cur ? cur.decision : '—');
  }

  function renderScoreboard(state, contract) {
    var m = (state && state.metrics) || {};
    setText('metricFirstDecision', m.firstDecisionMin != null ? m.firstDecisionMin + ' min' : '—');
    setText('metricRouteConfirm', m.routeConfirmMin != null ? m.routeConfirmMin + ' min' : '—');
    setText('metricUnlocated', m.unlocated != null ? String(m.unlocated) : '—');
    setText('metricShelterGap', m.shelterGap != null ? String(m.shelterGap) : '—');
    setText('metricCriticalFailures', m.criticalFailures != null ? String(m.criticalFailures) : '—');
    var active = getActiveContingency(state, contract);
    setText('metricContingencyResult', active ? (m.contingencyResult || 'pendente') : '—');
    var prog = R.mesaChecklistProgress ? R.mesaChecklistProgress(MUC_MESA_KEY) : R.checklistProgress(R.loadChecklist());
    setText('validationProgress', prog.done + '/' + prog.total);
  }

  function renderExposure(exposure) {
    if (!exposure) return;
    var peakHand = 17.02;
    var peak = exposure.niveis && exposure.niveis.find(function (n) { return Math.abs(n.hand_m - peakHand) < 0.01; });
    if (!peak) return;
    var isV2 = exposure.schema_version === 2;
    setText('exp-pop', peak.grade_200m.pop.toLocaleString('pt-BR'));
    setText('exp-dom', peak.grade_200m.dom.toLocaleString('pt-BR'));
    setText('exp-pct', peak.pct_pop_municipio + '%');
    setText('exp-idosos', (peak.setores_censitarios.idosos_70_mais || 0).toLocaleString('pt-BR'));
    var note = $('exp-method-note');
    if (note) note.textContent = isV2
      ? 'Exposição v2 areal · interseção HAND × grade 200 m · pico jul/2020 @ 17,02 m'
      : 'Exposição v1 centroide · pico jul/2020 @ 17,02 m';
  }

  var CONTINGENCY_LABELS = {
    route: 'rota principal fechada',
    shelter: 'abrigo lotado',
    comms: 'sem comunicação',
    night: 'noite / baixa visibilidade',
    combo: 'noite + ponte + abrigo lotado'
  };

  var CONTINGENCY_TEXT = {
    route: 'Bloquear orientação pelo corredor principal, registrar reconhecimento e só retomar após corredor alternativo confirmado.',
    shelter: 'Parar de indicar abrigo principal, registrar transbordo e escalonar transporte.',
    comms: 'Usar rádio, telefone e ponto de encontro; registrar mensagem para sincronizar depois.',
    night: 'Reduzir circulação, confirmar iluminação e equipe, priorizar transporte assistido.',
    combo: 'Cenário composto: corredor bloqueado + abrigo lotado + baixa visibilidade. Exercitar transbordo e corredor alternativo.'
  };

  function getZone(contract, state) {
    var zones = (contract && contract.zones) || [];
    return zones.find(function (z) { return z.id === (state && state.zone_id); }) || zones[0];
  }

  function getActiveContingency(state, contract) {
    if (!state || !state.contingencyActive) return null;
    var zone = getZone(contract, state);
    if (!zone || state.contingencyActive.zoneId !== zone.id) return null;
    return state.contingencyActive;
  }

  function contingencyIs(state, contract, flag) {
    var active = getActiveContingency(state, contract);
    if (!active) return false;
    if (active.value === 'combo') return flag === 'route' || flag === 'shelter' || flag === 'night';
    return active.value === flag;
  }

  function initContingency(contract) {
    var select = $('contingencySelect');
    if (!select) return;

    function renderContingencyPanel() {
      var state = readState() || {};
      var zone = getZone(contract, state);
      var value = select.value;
      setText('contingencyText', (zone ? zone.id + ' · ' : '') + (CONTINGENCY_TEXT[value] || ''));
      var active = getActiveContingency(state, contract);
      setText('contingencyStatus', active
        ? 'Aplicada · ' + active.label + ' · ' + ((state.metrics && state.metrics.contingencyResult) ? 'resultado registrado' : 'resultado pendente') + ' · sem efeito fora desta página.'
        : 'Nenhuma contingência aplicada.');
      var outcome = $('contingencyOutcome');
      if (outcome && document.activeElement !== outcome && !outcome.dataset.dirty) {
        outcome.value = (state.metrics && state.metrics.contingencyResult) || '';
      }
      renderScoreboard(state, contract);
    }

    select.addEventListener('change', renderContingencyPanel);
    $('contingencyApply') && $('contingencyApply').addEventListener('click', function () {
      var state = readState() || writeState({});
      var zone = getZone(contract, state);
      var value = select.value;
      var entry = {
        value: value,
        label: CONTINGENCY_LABELS[value],
        zoneId: zone.id,
        applied_at: new Date().toISOString()
      };
      var log = (state.log || []).slice();
      log.unshift({
        time: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
        text: 'Contingência aplicada · ' + CONTINGENCY_LABELS[value] + ' · ' + zone.id
      });
      writeState({ contingencyActive: entry, log: log.slice(0, 50) });
      R.appendDecision({ place: 'Muçum', action: 'contingencia', note: CONTINGENCY_LABELS[value] + ' · ' + zone.id });
      renderContingencyPanel();
    });
    var outcomeEl = $('contingencyOutcome');
    if (outcomeEl) {
      outcomeEl.addEventListener('input', function () { this.dataset.dirty = '1'; });
      outcomeEl.addEventListener('change', function () {
        var st = readState() || writeState({});
        st.metrics = st.metrics || {};
        st.metrics.contingencyResult = this.value.trim();
        writeState({ metrics: st.metrics });
        this.dataset.dirty = '';
        renderContingencyPanel();
      });
    }
    renderContingencyPanel();
  }

  function exportExerciseRecord(contract, feed) {
    var state = readState() || {};
    var zone = ((contract && contract.zones) || []).find(function (z) { return z.id === state.zone_id; });
    var checklist = R.loadChecklist();
    var payload = {
      export_schema_version: 'exercise_record_v2',
      exported_at: new Date().toISOString(),
      timezone: 'America/Sao_Paulo',
      artifact: { id: contract.artifact_id, operational_gate: contract.operational_gate.status },
      event: { scenario: contract.event.scenario_id, zone: zone ? zone.id : null, mode: state.mode || 'cenario' },
      validation_checklist: checklist,
      exercise_metrics: state.metrics || {},
      telemetry: feed ? {
        station: feed.estacao,
        level_cm: feed.nivel_rio_agora_cm,
        freshness: R.classifyFreshness(feed).label
      } : null,
      source_provenance: { files: contract.sources || [] }
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'previne-exercicio-mucum-' + (zone ? zone.id.toLowerCase() : 'mesa') + '.json';
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function renderShelters(plano) {
    if (!plano) return;
    var res = plano.resumo_capacidade || {};
    setText('sh-count', res.alojamentos_quadro_13 || (plano.abrigos && plano.abrigos.length));
    setText('sh-cap13', (res.capacidade_quadro_13_pessoas || '—') + ' pessoas');
    setText('sh-cap2', (res.capacidade_quadro_2_pessoas || '—') + ' pessoas');
    setText('sh-cap5', (res.capacidade_anexo_5_pessoas || '—') + ' pessoas');
    var list = $('shelter-list');
    if (!list || !plano.abrigos) return;
    list.innerHTML = plano.abrigos.slice(0, 6).map(function (s) {
      var cap = s.capacidade_quadro_13 != null ? s.capacidade_quadro_13 + ' pessoas' : '—';
      var coord = (s.lat != null && s.lon != null) ? ' · no mapa' : ' · sem coord.';
      return '<a href="mucum-rota-fuga-ruas.html"><b>' + s.nome + '</b><span>' + cap + coord + '</span></a>';
    }).join('');
    if (plano.abrigos.length > 6) {
      list.innerHTML += '<p class="section-intro" style="grid-column:1/-1;margin:0">+' + (plano.abrigos.length - 6) + ' alojamentos no JSON completo.</p>';
    }
  }

  function init(contract, exposure, plano) {
    var state = readState() || writeState({});
    renderZones(contract, state.zone_id || 'Z-01');
    renderTimeline(contract, state.timeline_min || 0);
    renderExposure(exposure);
    renderShelters(plano);
    renderScoreboard(state, contract);
    initContingency(contract);

    document.querySelectorAll('[data-mode]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var mode = btn.getAttribute('data-mode');
        writeState({ mode: mode });
        document.querySelectorAll('[data-mode]').forEach(function (b) {
          b.setAttribute('aria-pressed', b.getAttribute('data-mode') === mode ? 'true' : 'false');
        });
        setText('mode-note', mode === 'plantao'
          ? 'Plantão: feed ao vivo atualiza telemetria e RNA; gate permanece bloqueado.'
          : 'Cenário jul/2020: referência HAND@17,02 m e zonas de exposição.');
      });
    });

    var plantaoTimer = null;
    function refreshPlantao() {
      Promise.all([R.fetchLive('mucum'), R.fetchLive('santa')]).then(function (parts) {
        var feed = parts[0];
        var summary = R.summarizePlace(feed, 'mucum');
        setText('live-level', summary.levelLabel);
        $('live-meta').innerHTML =
          'RNA ' + summary.horizon + ' → ' + summary.predLabel + '<br>' +
          summary.gapLabel + '<br>Observação: ' + summary.levelAtLabel;
        renderHorizons(feed);
        renderSaceClock(feed);
        renderProxyMontante(feed, parts[1]);
        global.__MUCUM_LIVE_SUMMARY = summary;
        global.__MUCUM_LIVE_FEED = feed;
      });
    }

    $('refresh-live') && $('refresh-live').addEventListener('click', refreshPlantao);
    refreshPlantao();
    plantaoTimer = setInterval(refreshPlantao, 120000);

    $('export-json') && $('export-json').addEventListener('click', function () {
      exportExerciseRecord(contract, global.__MUCUM_LIVE_FEED);
    });

    $('record-decision') && $('record-decision').addEventListener('click', function () {
      var st = readState() || writeState({});
      if (st.metrics && st.metrics.firstDecisionMin == null) {
        st.metrics.firstDecisionMin = st.timeline_min || 0;
        writeState({ metrics: st.metrics });
        renderScoreboard(readState(), contract);
      }
      R.appendDecision({ place: 'Muçum', action: 'decisao_exercicio', note: 'Zona ' + (st.zone_id || 'Z-01') });
    });

    $('export-unified') && $('export-unified').addEventListener('click', function () {
      if (R.exportUnifiedAta) R.downloadCsv('previne-ata-unificada.csv', R.exportUnifiedAta());
    });

    return function cleanup() { if (plantaoTimer) clearInterval(plantaoTimer); };
  }

  global.PREVINE_MESA_MUCUM = {
    MUC_MESA_KEY: MUC_MESA_KEY,
    init: init,
    readState: readState,
    writeState: writeState,
    contingencyIs: contingencyIs,
    getActiveContingency: getActiveContingency
  };
})(typeof window !== 'undefined' ? window : globalThis);
