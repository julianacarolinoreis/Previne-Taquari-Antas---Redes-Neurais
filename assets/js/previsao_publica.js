/* Leitura pública do mesmo feed: sem modelos comparativos ou replay histórico. */
(function () {
  'use strict';
  const keys = ['2h', '4h', '8h'];
  let connectionError = false;
  const fmt = () => window.PrevineFmtQuando;
  const put = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
  const numeric = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const level = cm => numeric(cm) ? (Number(cm) / 100).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' m' : '—';
  function age(value) {
    const date = fmt().parseWhen(value);
    return date ? Math.max(0, (Date.now() - date.getTime()) / 60000) : null;
  }
  function isReady(key, data) {
    if (!keys.includes(key) || !data || data.disponivel === false || data.shadow_only || String(data.modo).toLowerCase() === 'replay') return false;
    if (/sem hora v[aá]lida|sem previs[aã]o|inputs incompletos|indispon[ií]vel/.test(String(data.status || '').toLowerCase())) return false;
    const base = fmt().parseWhen(data.hora_modelo), target = fmt().parseWhen(data.hora_alvo);
    const hasValue = numeric(data.nivel_previsto_cm) || (Array.isArray(data.passos) && data.passos.some(row => Array.isArray(row) && numeric(row.length > 3 ? row[3] : row[2])));
    return !!(hasValue && base && target && target.getTime() > Date.now());
  }
  function renderHorizons(live, active, ready) {
    connectionError = false;
    const horizons = live && live.horizontes || {};
    const missing = [];
    document.querySelectorAll('#live-hz [data-live-hz]').forEach(button => {
      const key = button.dataset.liveHz, data = horizons[key];
      const ok = ready(key, data);
      button.disabled = !ok;
      button.classList.toggle('on', ok && key === active);
      button.setAttribute('aria-pressed', ok && key === active ? 'true' : 'false');
      const label = document.createElement('span'); label.textContent = '+' + key.replace('h', ' h');
      const when = document.createElement('small'); when.textContent = ok ? fmt().fmtClock(data.hora_alvo) : 'indisponível';
      button.replaceChildren(label, when);
      button.title = ok ? 'Previsão para ' + fmt().fmtClockDate(data.hora_alvo) : 'Previsão de ' + key.replace('h', ' horas') + ' indisponível';
      if (!ok) missing.push(key.replace('h', ' h'));
    });
    const status = document.getElementById('live-horizon-status');
    if (status) {
      status.textContent = missing.length ? 'Sem previsão disponível: ' + missing.join(', ') + '.' : '';
      status.style.display = missing.length ? '' : 'none';
    }
  }
  function update(options) {
    const live = options.live;
    if (!live) return;
    document.body.dataset.publicState = 'ready';
    const selected = options.selected || live;
    const telemetryWhen = live.telemetria_ultima_em || live.nivel_rio_agora_em || selected.telemetria_ultima_em;
    const telemetryAge = age(telemetryWhen);
    const robotAge = age(live.consultado_em || live.gerado_em);
    const ready = options.readyKeys || [];
    const hasForecast = ready.includes(options.horizon) && numeric(options.forecastCm);
    const notes = [];
    if (connectionError) notes.push('Não foi possível confirmar a atualização. Os últimos dados carregados continuam visíveis.');
    if (telemetryAge === null) notes.push('O horário da última leitura não está disponível.');
    else if (telemetryAge > 60) notes.push('A leitura do rio está atrasada. Confira o horário abaixo do nível observado.');
    if (robotAge !== null && robotAge > 15) notes.push('A atualização do painel está atrasada.');
    if (!ready.length) notes.push('As previsões estão indisponíveis no momento.');
    if (selected.qualidade_ao_vivo && selected.qualidade_ao_vivo.status === 'ATENCAO') notes.push('A previsão exige atenção: o desempenho recente ficou abaixo do esperado.');
    const notice = String(live.aviso || '').trim();
    if (notice && !/^EXPERIMENTAL\b/i.test(notice)) notes.push(notice);
    const qualityWarning = selected.qualidade_ao_vivo && selected.qualidade_ao_vivo.status === 'ATENCAO';
    const warning = connectionError || telemetryAge === null || telemetryAge > 60 || robotAge > 15 || !ready.length || qualityWarning;
    const badge = document.getElementById('public-status');
    badge.classList.toggle('warn', warning);
    badge.textContent = connectionError ? 'Atualização não confirmada' : telemetryAge > 60 ? 'Leitura com atraso' : robotAge > 15 ? 'Atualização com atraso' : !ready.length ? 'Previsão indisponível' : telemetryAge === null ? 'Horário indisponível' : qualityWarning ? 'Previsão em atenção' : 'Dados atualizados';
    put('s-now-label', 'Último nível observado');
    put('s-now', level(options.nowCm));
    put('public-observed-when', telemetryWhen ? fmt().fmtClockDate(telemetryWhen) + (telemetryAge !== null ? ' · ' + fmt().fmtAge(telemetryAge) : '') : 'Horário da leitura indisponível');
    put('s-hz', hasForecast ? '+' + options.horizon.replace('h', ' h') : 'sem previsão');
    put('s-fore', hasForecast ? level(options.forecastCm) : '—');
    put('public-forecast-when', hasForecast ? 'Para ' + fmt().fmtClockDate(selected.hora_alvo) : 'Aguardando uma nova previsão');
    put('public-map-caption', 'Água estimada em ' + document.body.dataset.cityName + (hasForecast ? ' · previsão para ' + fmt().fmtClock(selected.hora_alvo) : ' · sem previsão disponível'));
    put('map-accessible-summary', document.body.dataset.cityName + ': último nível observado ' + level(options.nowCm) + '. ' + (hasForecast ? 'Previsão de ' + options.horizon.replace('h', ' horas') + ': ' + level(options.forecastCm) + ', para ' + fmt().fmtClockDate(selected.hora_alvo) + '. ' : 'Sem previsão disponível. ') + 'A mancha é uma estimativa de pesquisa. Não é alerta oficial.');
    const note = document.getElementById('public-service-note');
    note.textContent = notes.join(' ');
    note.hidden = !notes.length;
  }
  function failed(initial) {
    connectionError = true;
    const badge = document.getElementById('public-status');
    badge.classList.add('warn');
    badge.textContent = 'Atualização não confirmada';
    if (initial) {
      document.body.dataset.publicState = 'error';
      put('public-observed-when', 'Não foi possível carregar os dados atuais.');
      put('public-forecast-when', 'Previsão indisponível');
      put('public-map-caption', 'Dados atuais indisponíveis para ' + document.body.dataset.cityName);
    }
    const note = document.getElementById('public-service-note');
    note.textContent = initial ? 'Os dados atuais não carregaram. Tente novamente em instantes.' : 'Não foi possível confirmar a atualização. Os últimos dados carregados continuam visíveis.';
    note.hidden = false;
  }
  window.PREVINE_PUBLIC = {isReady, renderHorizons, update, failed};
})();
