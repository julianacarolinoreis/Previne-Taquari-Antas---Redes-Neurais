/* PREVINE · Plantão ao vivo — mesa ST V002 (fetch externo; HTML permanece autônomo). */
(function (global) {
  'use strict';

  var R = global.PREVINE_RESPOSTA;
  var timer = null;

  function horizonBlock(feed, slot) {
    if (!feed || !feed.horizontes) return null;
    return feed.horizontes[slot] || null;
  }

  function toIsoLocal(value) {
    if (!value) return null;
    var s = String(value).trim().replace(' ', 'T');
    if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += '-03:00';
    return s;
  }

  function buildLiveSnapshot(feed) {
    if (!feed) return null;
    var h8 = horizonBlock(feed, '8h');
    var h8s = horizonBlock(feed, '8h_v002') || horizonBlock(feed, '8h_versao_b');
    var observed = feed.telemetria_ultima_nivel_cm != null ? feed.telemetria_ultima_nivel_cm : feed.nivel_rio_agora_cm;
    var roundBase = h8 && (h8.nivel_atual_cm != null ? h8.nivel_atual_cm : h8.nivel_modelo_cm);
    if (roundBase == null && h8s) roundBase = h8s.nivel_atual_cm != null ? h8s.nivel_atual_cm : h8s.nivel_modelo_cm;
    function card(h, shadow) {
      if (!h) return null;
      return {
        label: h.rotulo || (shadow ? '8h V002' : '8h V001'),
        model: h.modelo || '—',
        forecast_cm: h.nivel_previsto_cm != null ? h.nivel_previsto_cm : h.nivel_modelo_cm,
        current_cm: h.nivel_atual_cm != null ? h.nivel_atual_cm : roundBase,
        inputs: h.inputs_total,
        status: (h.status_publicacao || h.status_dados || 'ATENCAO').toUpperCase().replace('Ã', 'A'),
        mae24: h.mae_24h_cm != null ? h.mae_24h_cm : (h.metricas && h.metricas.mae_24h_cm),
        maxabs: h.maior_erro_abs_24h_cm != null ? h.maior_erro_abs_24h_cm : null,
        publication: h.status_publicacao || (shadow ? 'sombra_experimental' : 'experimental'),
        shadow: !!shadow,
        active: h.ativo_ao_vivo !== false
      };
    }
    return {
      snapshot: toIsoLocal(feed.hora_modelo || feed.gerado_em),
      snapshot_raw: feed.hora_modelo || feed.gerado_em,
      timestamp_note: 'feed ao vivo · offset -03:00 assumido quando ausente na fonte',
      station: feed.estacao || '86472600',
      city: feed.local || 'Santa Tereza',
      bankfull_cm: feed.bankfull_cm || 400,
      contract: feed.input_contract_version || 'hourly_exact_v1',
      observed_cm: observed,
      observed_at: toIsoLocal(feed.telemetria_ultima_em || feed.nivel_rio_agora_em),
      consulted_at: toIsoLocal(feed.consultado_em || new Date().toISOString()),
      max_observation_age_min: 60,
      idade_telemetria_min: feed.idade_telemetria_min,
      status_dados: feed.status_dados,
      v001: card(h8, false),
      v002: card(h8s, true),
      feed: feed
    };
  }

  function freshnessFromSnapshot(snap) {
    if (!snap) return { status: 'UNKNOWN', note: 'feed indisponível; permanecer no snapshot incorporado' };
    var fresh = R.classifyFreshness(snap.feed || {});
    var age = snap.idade_telemetria_min;
    if (fresh.kind === 'unknown') {
      return { status: 'UNKNOWN', note: fresh.detail || 'sem telemetria válida no feed' };
    }
    if (fresh.kind === 'stale') {
      return {
        status: 'STALE',
        note: 'última leitura ' + (snap.observed_cm / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) +
          ' m · ' + (age != null ? age + ' min atrás' : 'atrasada') + ' · gate permanece bloqueado'
      };
    }
    return {
      status: 'ATENÇÃO',
      note: 'feed ao vivo · telemetria ' + (age != null ? 'há ~' + age + ' min' : 'publicada') +
        ' · RNA experimental; não substitui alerta oficial'
    };
  }

  function init(hooks) {
    hooks = hooks || {};
    var getMode = hooks.getMode || function () { return 'exercise'; };
    var onSnapshot = hooks.onSnapshot || function () {};
    var intervalMs = hooks.intervalMs || 120000;

    function refresh() {
      if (getMode() !== 'live') return;
      R.fetchLive('santa').then(function (feed) {
        var snap = buildLiveSnapshot(feed);
        if (snap) onSnapshot(snap, freshnessFromSnapshot(snap));
      });
    }

    function setMode(mode) {
      if (mode === 'live') {
        refresh();
        if (timer) clearInterval(timer);
        timer = setInterval(refresh, intervalMs);
      } else if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    return {
      refresh: refresh,
      setMode: setMode,
      buildLiveSnapshot: buildLiveSnapshot,
      freshnessFromSnapshot: freshnessFromSnapshot,
      cleanup: function () { if (timer) clearInterval(timer); timer = null; }
    };
  }

  global.PREVINE_MESA_ST = {
    init: init,
    buildLiveSnapshot: buildLiveSnapshot,
    freshnessFromSnapshot: freshnessFromSnapshot
  };
})(typeof window !== 'undefined' ? window : globalThis);
