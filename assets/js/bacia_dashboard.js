/* PREVINE · dashboard integrado da bacia
 * Os valores são lidos dos artefatos publicados; este arquivo não inventa uma
 * probabilidade conjunta nem transforma score em probabilidade calibrada.
 */
(function () {
  'use strict';

  const root = document.querySelector('[data-bacia-dashboard]');
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const state = { station: 'basin', horizon: 72, feeds: {}, research: null, lastLoadedAt: null };
  const researchUrl = 'assets/data/research_basin_screening_latest.json';
  const stations = {
    santa: {
      key: 'santa', label: 'Santa Tereza', code: '86472600', threshold: 1500,
      pattern: 'assets/data/research_visual_patterns_santa_tereza_latest.json',
      weather: 'assets/data/research_weather_santa_tereza_latest.json',
      live: 'previsao_ao_vivo.json',
      status: 'pesquisa_status.html',
      kind: 'Santa Tereza'
    },
    mucum: {
      key: 'mucum', label: 'Muçum', code: '86510000', threshold: 1800,
      pattern: 'assets/data/research_visual_patterns_mucum_latest.json',
      weather: 'assets/data/research_weather_mucum_latest.json',
      live: 'previsao_ao_vivo_mucum.json',
      status: 'pesquisa_status_mucum.html',
      kind: 'Muçum'
    }
  };
  const zoneDefinitions = [
    ['Pontos monitorados a montante', 'sinal espacial de chuva que pode chegar', 'A média das células IFS únicas ligadas aos pontos monitorados funciona como proxy. Não é a média de toda a bacia.', 'var(--blue)', '42%'],
    ['Cobertura hidrológica da bacia', 'máscara e ponderação por área', 'Ainda pendente de validação. O site não substitui essa cobertura pelo proxy de estações.', 'var(--green)', '66%'],
    ['Perto da estação', 'ponto de leitura', 'A chuva no ponto e o nível ANA/SGB são mostrados quando a fonte os publica.', 'var(--amber)', '82%'],
    ['Jusante / foz', 'propagação', 'Ainda não há série zonal independente e tempo de propagação validados neste painel.', 'var(--purple)', '33%']
  ];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[c]));
  }
  function safeHttpUrl(value) {
    const url = String(value == null ? '' : value).trim();
    return /^https?:\/\//i.test(url) ? url : '';
  }
  function num(value) {
    if (value == null || (typeof value === 'string' && value.trim() === '')) return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  function fmt(value, digits = 1) {
    const n = num(value);
    return n == null ? '—' : n.toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function fmtSmall(value) {
    const n = num(value);
    if (n == null) return '—';
    return n < 1 && n !== 0 ? n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : fmt(n, 1);
  }
  function pct(value) {
    const n = num(value);
    return n == null ? '—' : `${n.toLocaleString('pt-BR', { minimumFractionDigits: n < 1 ? 2 : 1, maximumFractionDigits: n < 1 ? 2 : 1 })}%`;
  }
  function parseDate(value) {
    if (value == null || value === '') return null;
    let s = String(value).trim().replace(' ', 'T');
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) s += 'T00:00:00';
    // Older feeds used local BRT without an offset. Treat that explicitly as
    // BRT instead of letting the browser interpret it in an unknown zone.
    if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += '-03:00';
    const d = new Date(s);
    return Number.isFinite(d.getTime()) ? d : null;
  }
  function when(value) {
    const d = parseDate(value);
    return d ? d.toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
  }
  function shortDate(value) {
    const d = parseDate(value);
    return d ? d.toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', year: 'numeric' }) : 'data desconhecida';
  }
  function ageHours(value) {
    const d = parseDate(value);
    return d ? Math.max(0, (Date.now() - d.getTime()) / 3600000) : null;
  }
  function ageLabel(hours) {
    if (hours == null) return 'sem horário válido';
    if (hours < 1) return `atualizado há ${Math.max(1, Math.round(hours * 60))} min`;
    return `atualizado há ${fmt(hours, 1)} h`;
  }
  function finiteText(value, fallback = '—') { return value == null || value === '' ? fallback : String(value); }
  function first(...values) { return values.find((v) => num(v) != null) ?? null; }
  function rowFor(feed, hours) {
    const rows = Array.isArray(feed && feed.horizons) ? feed.horizons : [];
    return rows.find((row) => Number(row.hours) === Number(hours)) || null;
  }
  function stationFeed(key) { return state.feeds[key] || {}; }
  function stationSnapshot(key, hours = state.horizon) {
    const s = stations[key];
    const f = stationFeed(key);
    const p = rowFor(f.pattern, hours) || {};
    const w = rowFor(f.weather, hours) || {};
    const live = f.live || {};
    const obs = f.weather && f.weather.observation ? f.weather.observation : {};
    const liveLevel = first(live.telemetria_ultima_nivel_cm, live.nivel_atual_cm, live.nivel_rio_agora_cm);
    const level = first(liveLevel, obs.level_cm);
    const levelAt = live.telemetria_ultima_em_utc || live.telemetria_ultima_em || live.nivel_rio_agora_em || obs.observed_at_utc;
    const pointRain = first(w.rain_point_mm, p.point_mm, p.ifs_direct_mm);
    const basinMean = first(w.basin_mean_mm, p.ifs_mean_mm);
    const basinMax = first(w.basin_max_mm, p.ifs_max_mm);
    const meanRain = first(basinMean, w.rain_ecmwf_direct_mm, p.ifs_direct_mm);
    const maxRain = first(basinMax, w.rain_ifs_proxy_mm, p.ifs_proxy_mm);
    const directRain = first(w.rain_ecmwf_direct_mm, p.ifs_direct_mm);
    const ifsProxyRain = first(w.rain_ifs_proxy_mm, p.ifs_proxy_mm);
    const gefsProxyRain = first(w.rain_gefs_proxy_mm, p.gefs_proxy_mm);
    const soil = first(w.soil_moisture_model_mean_m3m3, p.soil_moisture_m3m3);
    // The integrated research feed is the authority for freshness.  Keep an
    // archived score available for audit, but never present a stale score or
    // binary decision as if it were a current estimate.
    const integrated = researchRow(key === 'santa' ? 'santa_tereza' : key, hours) || {};
    const integratedRisk = integrated.risk || {};
    const archivedRisk = first(integratedRisk.probability_percent, p.probability_percent, w.flood_probability_percent, num(w.flood_probability) == null ? null : w.flood_probability * 100);
    const riskUsable = integratedRisk.usable_as_current_probability === true && integratedRisk.state !== 'stale';
    const risk = riskUsable ? archivedRisk : null;
    const score = first(p.rna_score_percent, w.rna_score_percent);
    const archivedDecision = integratedRisk.decision || p.decision || w.flood_decision || (w.flood_answer && /VAI/.test(w.flood_answer) ? 'VAI' : null);
    const decision = riskUsable ? archivedDecision : null;
    const generated = f.pattern && f.pattern.generated_at_utc || f.weather && f.weather.generated_at_utc;
    const forecastAge = ageHours(generated);
    const observedAge = ageHours(levelAt);
    const coverage = num(w.rain_hours_available);
    return { key, horizon: hours, station: s, pattern: f.pattern, weather: f.weather, live, p, w, obs, level, levelAt, pointRain, basinMean, basinMax, meanRain, maxRain, directRain, ifsProxyRain, gefsProxyRain, soil, risk, archivedRisk, riskUsable, riskState: integratedRisk.state || 'unknown', riskGenerated: integratedRisk.generated_at_utc, riskCalibration: integratedRisk.calibration_status, decision, archivedDecision, generated, forecastAge, observedAge, coverage };
  }
  function qualityFor(snapshot) {
    const obsGood = snapshot.level != null && (snapshot.observedAge == null || snapshot.observedAge <= 3);
    const forecastGood = snapshot.meanRain != null && (snapshot.forecastAge == null || snapshot.forecastAge <= 72);
    const partial = snapshot.coverage != null && snapshot.coverage < snapshot.horizon;
    if (!obsGood && !forecastGood) return { label: 'REVISAR', className: 'unknown' };
    if (partial || !obsGood) return { label: 'PARCIAL', className: 'warn' };
    return { label: 'ACOMPANHAR', className: 'good' };
  }
  function decisionLabel(value) {
    if (value === 'VAI') return 'VAI · pesquisa';
    if (value === 'NAO_VAI' || value === 'NAO VAI') return 'NÃO VAI · pesquisa';
    return 'SEM DECISÃO';
  }
  function decisionClass(value) {
    if (value === 'VAI') return 'warn';
    if (value === 'NAO_VAI' || value === 'NAO VAI') return 'good';
    return 'unknown';
  }
  function displayRain(snap) {
    if (snap.key === 'mucum') return { value: snap.directRain, label: 'IFS direto no ponto', source: 'ECMWF IFS' };
    return { value: snap.meanRain, label: 'média das células monitoradas a montante', source: 'ECMWF IFS' };
  }
  function sourceGenerated(snap) {
    const values = [snap.weather && snap.weather.generated_at_utc, snap.pattern && snap.pattern.generated_at_utc].filter(Boolean);
    return values.sort((a, b) => (parseDate(b)?.getTime() || 0) - (parseDate(a)?.getTime() || 0))[0] || null;
  }
  function liveSourceText(snap) {
    const src = snap.live && snap.live.estacao ? snap.live.estacao : snap.obs && snap.obs.source ? snap.obs.source : `ANA/SGB ${snap.station.code}`;
    return src;
  }

  function researchStation(key) {
    return state.research && state.research.stations && state.research.stations[key] || null;
  }
  function researchRow(key, hours) {
    const station = researchStation(key);
    const rows = Array.isArray(station && station.horizons) ? station.horizons : [];
    return rows.find((row) => Number(row.hours) === Number(hours)) || null;
  }
  function researchStateLabel(value) {
    if (value === 'fresh' || value === 'current_window') return 'atualizado';
    if (value === 'stale') return 'atrasado';
    if (value === 'pending') return 'pendente';
    return 'sem estado';
  }
  function researchMetric(label, value, note, cls = '') {
    return `<div class="research-metric ${cls}"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
  }
  function sourceStatusLabel(value) {
    if (value === 'identified') return 'FONTE IDENTIFICADA';
    if (value === 'conditional') return 'ACESSO CONDICIONAL';
    if (value === 'integrated') return 'INTEGRADA E VALIDADA';
    return String(value || 'SEM STATUS').replace(/_/g, ' ').toUpperCase();
  }
  function renderResearchSources(registry) {
    const sources = registry && Array.isArray(registry.sources) ? registry.sources : [];
    if (!sources.length) return '<div class="empty-block">O registro de fontes ainda não foi publicado.</div>';
    const cards = sources.map((source) => {
      const url = safeHttpUrl(source.url);
      const metadata = safeHttpUrl(source.metadata_url);
      const link = url ? `<a class="research-source-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">abrir fonte oficial ↗</a>` : '';
      const metadataLink = metadata ? `<a class="research-source-meta" href="${esc(metadata)}" target="_blank" rel="noopener noreferrer">metadados ↗</a>` : '';
      const status = source.status === 'integrated' ? 'integrated' : source.status === 'conditional' ? 'conditional' : 'identified';
      return `<article class="research-source-card"><div class="research-source-head"><div><span class="research-source-type">${esc(source.type || 'fonte')}</span><h3>${esc(source.label || source.id || 'Fonte')}</h3></div><span class="research-source-status ${status}">${esc(sourceStatusLabel(source.status))}</span></div><p class="research-source-role"><strong>Gate:</strong> ${esc(String(source.gate || 'não associado').replace(/_/g, ' '))} · ${esc(source.role || 'papel não informado')}</p><p class="research-source-next"><strong>Próximo passo:</strong> ${esc(source.next_step || 'validar recorte, unidade, tempo e qualidade antes de integrar')}</p><div class="research-source-links">${link}${metadataLink}</div></article>`;
    }).join('');
    return `<div class="research-sources-head"><strong>${esc(registry.title || 'Fontes oficiais priorizadas')}</strong><span>revisado em ${esc(shortDate(registry.last_reviewed_utc))}</span></div><p class="research-sources-note">${esc(registry.note || 'Fonte identificada não é camada validada.')}</p><div class="research-source-list">${cards}</div>`;
  }
  function renderResearchContext() {
    const grid = $('research-context-grid'); const gates = $('research-context-gates'); const upstream = $('research-upstream'); const registry = $('research-source-registry'); const status = $('research-context-status');
    if (!grid || !gates || !upstream || !registry || !status) return;
    if (!state.research || !state.research.stations) {
      status.textContent = 'Feed integrado indisponível';
      grid.innerHTML = '<div class="empty-block">O contexto da pesquisa ainda não foi publicado.</div>';
      gates.innerHTML = '';
      upstream.innerHTML = '';
      registry.innerHTML = '';
      return;
    }
    const keys = state.station === 'basin' ? ['santa_tereza', 'mucum'] : [state.station === 'santa' ? 'santa_tereza' : state.station];
    const labels = { santa_tereza: 'Santa Tereza', mucum: 'Muçum' };
    const h = state.horizon;
    grid.innerHTML = keys.map((key) => {
      const item = researchStation(key) || {}; const row = researchRow(key, h) || {}; const rain = row.rain || {}; const head = rain.headwater || {}; const risk = row.risk || {}; const current = item.current || {};
      const short = Array.isArray(item.short_forecasts) && item.short_forecasts.length ? item.short_forecasts.map((f) => `+${f.hours} h: ${fmt(f.level_forecast_cm, 0)} cm`).join(' · ') : 'previsão curta sem valor';
      const headValue = head.mean_mm == null ? '—' : `${fmt(head.mean_mm, 1)} mm`;
      const headNote = head.max_mm == null ? 'sem máximo publicado' : `máx. ${fmt(head.max_mm, 1)} mm · ${head.status === 'shared_santa_reference' ? 'proxy compartilhada' : 'células monitoradas'}`;
      const point = rain.point_mm != null ? `${fmt(rain.point_mm, 1)} mm` : rain.ifs_direct_mm != null ? `${fmt(rain.ifs_direct_mm, 1)} mm` : '—';
      const archived = risk.probability_percent == null ? '' : ` · arquivado: ${pct(risk.probability_percent)}`;
      const usable = risk.usable_as_current_probability === true && risk.state !== 'stale';
      const prob = usable ? pct(risk.probability_percent) : '—';
      const probNote = usable ? `${researchStateLabel(risk.state)} · cota ${fmt(item.threshold_cm, 0)} cm · ${risk.calibration_status}` : `${researchStateLabel(risk.state)} · não utilizável como leitura atual${archived}`;
      const quality = item.quality || {};
      return `<article class="research-context-card ${quality.status === 'DEGRADED' ? 'is-degraded' : ''}">
        <div class="research-context-card-head"><div><span class="research-station-kicker">${esc(labels[key] || key)}</span><h3>${esc(item.station_code || 'estação')}</h3></div><span class="research-quality ${quality.status === 'DEGRADED' ? 'warn' : ''}">${esc(quality.status || 'SEM STATUS')}</span></div>
        <div class="research-metrics">
          ${researchMetric('Nível observado', current.level_cm == null ? '—' : `${fmt(current.level_cm, 0)} cm`, `${researchStateLabel(current.state)} · ${when(current.observed_at_utc)}`, 'observed')}
          ${researchMetric('Pontos a montante · proxy', headValue, headNote, head.status === 'shared_santa_reference' ? 'proxy' : 'forecast')}
          ${researchMetric('Chuva no ponto', point, `acumulado previsto · +${h} h`, 'forecast')}
          ${researchMetric('Cruzamento da cota', prob, probNote, 'risk')}
        </div>
        <p class="research-context-short"><strong>Robô ao vivo:</strong> ${esc(short)}.</p>
        <p class="research-context-source"><strong>Fonte:</strong> ${esc(item.forecast && item.forecast.provider || 'não informada')} · feed ${esc(researchStateLabel(item.forecast && item.forecast.state))} (${esc(when(item.forecast && item.forecast.generated_at_utc))}).</p>
        ${head.status === 'shared_santa_reference' ? '<p class="research-context-warning">Muçum ainda não tem máscara hidrológica independente; este agregado é uma referência compartilhada dos pontos monitorados a montante, não a média da bacia de Muçum.</p>' : '<p class="research-context-warning">O agregado espacial resume pontos monitorados a montante; não é uma média ponderada de toda a bacia.</p>'}
      </article>`;
    }).join('');
    const pending = Array.isArray(state.research.gates) ? state.research.gates.filter((gate) => gate.status !== 'complete') : [];
    gates.innerHTML = `<div class="research-gates-head"><strong>Gates científicos da pesquisa</strong><span>${pending.length} itens ainda sem validação final</span></div><div class="research-gates-list">${pending.map((gate) => `<span class="research-gate ${gate.status === 'research_partial' ? 'partial' : ''}"><b>${esc(gate.id.replace(/_/g, ' '))}</b><small>${esc(gate.reason)}</small></span>`).join('')}</div>`;
    const gauges = state.research.basin && state.research.basin.upstream_gauges && Array.isArray(state.research.basin.upstream_gauges.stations) ? state.research.basin.upstream_gauges.stations : [];
    upstream.innerHTML = gauges.length ? `<div class="research-upstream-head"><strong>Âncoras observadas a montante</strong><span>não confundir com chuva da bacia</span></div><div class="research-upstream-list">${gauges.map((gauge) => `<span class="research-upstream-item"><b>${esc(gauge.name || gauge.station_code)}</b><small>${gauge.current_level_cm == null ? 'nível —' : `${fmt(gauge.current_level_cm, 0)} cm`} · ${esc(gauge.lag_hours_declared == null ? 'defasagem não declarada' : `lag declarado ${fmt(gauge.lag_hours_declared, 0)} h`)}</small></span>`).join('')}</div>` : '';
    registry.innerHTML = renderResearchSources(state.research.source_registry);
    status.textContent = `Contexto gerado em ${when(state.research.generated_at_utc)} · pesquisa, sem alerta automático`;
  }

  function renderAnswer() {
    const hours = state.horizon;
    const answerTitle = $('answer-title');
    const answerText = $('answer-text');
    const answerState = $('answer-state');
    if (state.station === 'basin') {
      const a = stationSnapshot('santa', hours); const b = stationSnapshot('mucum', hours);
      const ar = displayRain(a); const br = displayRain(b);
      answerTitle.textContent = `Na bacia, os modelos não contam uma história única em +${hours} h`;
      const riskNote = ((a.risk == null || b.risk == null) && (a.archivedRisk != null || b.archivedRisk != null)) ? ' Os scores antigos foram ocultados porque estão atrasados; permanecem nos JSONs para auditoria.' : '';
      answerText.textContent = `Santa Tereza: ${fmt(ar.value, 2)} mm (${ar.label}); Muçum: ${fmt(br.value, 2)} mm (${br.label}). As estimativas experimentais utilizáveis de cruzar a cota são ${pct(a.risk)} e ${pct(b.risk)}, respectivamente. Não há probabilidade conjunta publicada.${riskNote}`;
      answerState.textContent = 'COMPARAÇÃO'; answerState.className = 'answer-state warn';
      return;
    }
    const snap = stationSnapshot(state.station, hours); const rain = displayRain(snap);
    const riskText = snap.risk == null ? 'sem estimativa experimental utilizável' : `${pct(snap.risk)} de cruzar ${fmt(snap.station.threshold / 100, 2)} m (${fmt(snap.station.threshold, 0)} cm)`;
    const modelText = snap.decision ? decisionLabel(snap.decision).toLowerCase() : 'sem decisão binária publicada';
    answerTitle.textContent = `${snap.station.label}: janela de +${hours} h`;
    const coverageNote = snap.coverage != null && snap.coverage < hours ? ` A cobertura publicada é parcial (${fmt(snap.coverage, 0)}/${hours} h).` : '';
    answerText.textContent = `Previsão principal: ${fmt(rain.value, 2)} mm (${rain.label}). O modelo de pesquisa indica ${riskText}; decisão exibida: ${modelText}.${coverageNote} É um resultado experimental, não um alerta e não uma garantia de que vai ou não vai inundar.`;
    answerState.textContent = snap.risk == null ? 'SEM VALOR' : 'PESQUISA';
    answerState.className = `answer-state ${snap.risk == null ? 'unknown' : snap.risk >= 50 ? 'warn' : ''}`;
  }

  function renderKpis() {
    const hours = state.horizon;
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    const snaps = keys.map((key) => stationSnapshot(key, hours));
    const level = snaps.map((s) => `${s.station.label}: ${fmt(s.level, 0)} cm`).join(' · ');
    const rain = snaps.map((s) => { const r = displayRain(s); return `${s.station.label}: ${fmt(r.value, 2)} mm`; }).join(' · ');
    const risk = snaps.map((s) => `${s.station.label}: ${pct(s.risk)}`).join(' · ');
    const qualities = snaps.map(qualityFor);
    const worst = qualities.some((q) => q.className === 'unknown') ? { label: 'REVISAR', className: 'unknown' } : qualities.some((q) => q.className === 'warn') ? { label: 'PARCIAL', className: 'warn' } : { label: 'ACOMPANHAR', className: 'good' };
    $('kpi-level').textContent = level || '—';
    $('kpi-level-note').textContent = snaps.length === 1 ? `${liveSourceText(snaps[0])} · ${ageLabel(snaps[0].observedAge)}` : 'duas estações de referência · não é média da bacia';
    $('kpi-rain').textContent = rain || '—';
    $('kpi-rain-note').textContent = `horizonte +${hours} h · fonte principal de cada estação`;
    $('kpi-risk').textContent = risk || '—';
    $('kpi-risk-note').textContent = snaps.some((s) => s.risk == null && s.archivedRisk != null) ? 'score atrasado ocultado; arquivo preservado para auditoria' : 'estimativa experimental; não calibrada como alerta';
    $('kpi-freshness').textContent = worst.label;
    $('kpi-freshness').className = `kpi-value ${worst.className}`;
    $('kpi-freshness-note').textContent = `${qualities.map((q, i) => `${stations[keys[i]].label}: ${q.label.toLowerCase()}`).join(' · ')}`;
  }

  function renderStationComparison() {
    const html = Object.keys(stations).map((key) => {
      const s = stationSnapshot(key, state.horizon); const rain = displayRain(s); const q = qualityFor(s);
      const coverage = s.coverage == null ? 'cobertura não informada' : `${fmt(s.coverage, 0)}/${state.horizon} h de cobertura`;
      return `<article class="station-card ${state.station === key ? 'selected' : ''}">
        <div class="station-card-head"><div><h3>${esc(s.station.label)}</h3><span class="station-code">ANA/SGB ${esc(s.station.code)} · cota ${fmt(s.station.threshold / 100, 2)} m</span></div><span class="station-decision ${decisionClass(s.decision)}">${esc(decisionLabel(s.decision))}</span></div>
        <div class="station-card-main"><div class="station-mini"><strong>${fmt(s.level, 0)} cm</strong><span>nível observado · ${ageLabel(s.observedAge)}</span></div><div class="station-mini"><strong>${fmt(rain.value, 2)} mm</strong><span>${esc(rain.label)} · +${state.horizon} h</span></div><div class="station-mini"><strong>${pct(s.risk)}</strong><span>estimativa experimental de cruzar a cota</span></div></div>
        <p class="station-foot"><b>${esc(q.label)}</b> · ${coverage} · emissão ${when(sourceGenerated(s))} · <a href="${esc(s.station.status)}">abrir estação →</a></p>
      </article>`;
    }).join('');
    $('station-comparison').innerHTML = html || '<div class="empty-block">Sem dados de estação.</div>';
  }

  function zoneValue(snap, zoneIndex) {
    if (!snap && state.station === 'basin' && zoneIndex === 0) {
      const a = stationSnapshot('santa', state.horizon);
      return { value: a.basinMean == null ? '—' : `${fmt(a.basinMean, 1)} mm`, note: `média das células monitoradas a montante · ${stations.santa.label} · +${state.horizon} h` };
    }
    if (!snap && state.station === 'basin' && zoneIndex === 1) {
      const a = stationSnapshot('santa', state.horizon);
      return { value: '—', note: 'máscara hidrológica e ponderação por área ainda não validadas' };
    }
    if (!snap && state.station === 'basin' && zoneIndex === 2) {
      const a = stationSnapshot('santa', state.horizon); const b = stationSnapshot('mucum', state.horizon);
      return { value: `S ${fmt(a.pointRain, 1)} · M ${fmt(b.pointRain, 1)} mm`, note: 'ponto/célula próxima · Santa / Muçum' };
    }
    if (!snap) return { value: '—', note: 'sem estação selecionada' };
    if (zoneIndex === 0) {
      const reference = snap.basinMean == null ? stationSnapshot('santa', state.horizon).basinMean : snap.basinMean;
      return { value: reference == null ? '—' : `${fmt(reference, 1)} mm`, note: `média das células monitoradas a montante · +${state.horizon} h${snap.basinMean == null ? ' · proxy compartilhada' : ''}` };
    }
    if (zoneIndex === 1) {
      const reference = snap.basinMean == null && snap.basinMax == null ? stationSnapshot('santa', state.horizon) : snap;
      const mean = reference.basinMean, max = reference.basinMax;
      return { value: '—', note: 'a cobertura hidrológica da bacia ainda não foi validada' };
    }
    if (zoneIndex === 2) {
      const r = displayRain(snap);
      return { value: r.value == null ? '—' : `${fmt(r.value, 2)} mm`, note: `${r.label} · +${state.horizon} h` };
    }
    return { value: '—', note: 'camada zonal independente ainda não publicada' };
  }
  function renderZones() {
    const snap = state.station === 'basin' ? null : stationSnapshot(state.station, state.horizon);
    $('zone-cards').innerHTML = zoneDefinitions.map((z, i) => {
      const v = zoneValue(snap, i);
      return `<article class="zone-card" style="--zone-color:${z[3]};--zone-width:${z[4]}"><h3>${esc(z[0])}</h3><span class="zone-role">${esc(z[1])}</span><p><strong>${esc(v.value)}</strong><br>${esc(v.note)}</p><span class="zone-state">${v.value !== '—' ? 'proxy publicado' : 'integração pendente'}</span></article>`;
    }).join('');
  }

  function modelCard(name, type, value, unit, description, source, color, extraClass = '') {
    const n = num(value); const max = unit === '%' ? 100 : unit === 'm³/m³' ? .6 : 200;
    const width = n == null ? 0 : Math.max(0, Math.min(100, n / max * 100));
    return `<article class="model-card ${extraClass}"><h3>${esc(name)}</h3><div class="model-type">${esc(type)}</div><div class="model-value"><strong>${n == null ? '—' : fmtSmall(n)}</strong><span>${esc(unit)}</span></div><div class="meter" aria-hidden="true"><i style="width:${width.toFixed(1)}%;--meter-color:${color}"></i></div><p>${esc(description)}</p><span class="model-source">${esc(source)}</span></article>`;
  }
  function renderModels() {
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    const cards = [];
    keys.forEach((key) => {
      const s = stationSnapshot(key, state.horizon); const prefix = state.station === 'basin' ? `${s.station.label} · ` : '';
      if (key === 'santa') {
        cards.push(modelCard(`${prefix}IFS · média monitorada a montante`, 'PREVISÃO · chuva acumulada', s.meanRain, 'mm', 'Média simples das células únicas ligadas aos pontos monitorados. Não é média de toda a bacia.', 'ECMWF IFS', '#c47a10'));
        cards.push(modelCard(`${prefix}IFS · máximo monitorado`, 'PREVISÃO · chuva acumulada', s.maxRain, 'mm', 'Maior célula entre os pontos monitorados a montante; não representa a bacia inteira.', 'ECMWF IFS', '#d59a33'));
        cards.push(modelCard(`${prefix}IFS · ponto`, 'PREVISÃO · chuva acumulada', s.pointRain, 'mm', 'Valor do ponto/célula mais próxima da estação.', 'ECMWF IFS', '#e2b85c'));
        cards.push(modelCard(`${prefix}RNA do feed`, 'SCORE · não calibrado', s.score, '%', 'Score do modelo de pesquisa. Não é frequência nem chance real.', 'RNA / feed visual', '#7650b4', 'experimental-card'));
        cards.push(modelCard(`${prefix}GEFS`, 'PROBABILIDADE · experimental', s.risk, '%', s.riskUsable ? 'Estimativa experimental de cruzar a cota; não é alerta oficial.' : `Score arquivado não utilizável como leitura atual (${researchStateLabel(s.riskState)}).`, 'NOAA GEFS · proxy/rodada', '#6541a7', 'experimental-card'));
      } else {
        cards.push(modelCard(`${prefix}IFS direto`, 'PREVISÃO · ponto Muçum', s.directRain, 'mm', 'Chuva acumulada direta no ponto/rodada IFS.', 'ECMWF IFS', '#c47a10'));
        cards.push(modelCard(`${prefix}IFS proxy`, 'PROXY · célula espacial', s.ifsProxyRain, 'mm', 'Proxy espacial usado na conferência; não é medição local.', 'ECMWF IFS / célula', '#d59a33'));
        cards.push(modelCard(`${prefix}GEFS proxy`, 'PROXY · ensemble', s.gefsProxyRain, 'mm', 'Proxy da célula GEFS que alimenta o ajuste de pesquisa.', 'NOAA GEFS / célula', '#e2b85c'));
        cards.push(modelCard(`${prefix}Cruzamento da cota`, 'PROBABILIDADE · experimental', s.risk, '%', s.riskUsable ? 'Score logístico de pesquisa; não calibrado operacionalmente.' : `Score arquivado não utilizável como leitura atual (${researchStateLabel(s.riskState)}).`, 'Modelo logístico · cota 1.800 cm', '#6541a7', 'experimental-card'));
        cards.push(modelCard(`${prefix}Solo modelado`, 'PROXY · umidade', s.soil, 'm³/m³', 'Memória hídrica modelada. Não é sensor local de saturação.', 'Produto modelado', '#4d9b79'));
      }
    });
    $('model-cards').innerHTML = cards.join('') || '<div class="empty-block">Sem modelos publicados para este recorte.</div>';
    $('model-panel-note').textContent = `Valores do horizonte +${state.horizon} h · barras são apenas escala visual (chuva 0–200 mm; risco 0–100)`;
  }

  function allEvents() {
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    return keys.flatMap((key) => {
      const f = stationFeed(key); const rows = Array.isArray(f.pattern && f.pattern.events) ? f.pattern.events : [];
      return rows.map((event) => ({ ...event, sourceKey: key, sourceLabel: stations[key].label }));
    }).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  }
  function renderEvents() {
    const events = allEvents();
    $('timeline-note').textContent = events.length ? `${events.length} picos no recorte visual · Santa Tereza usa 5 eventos no cartão de validação` : 'Sem eventos publicados';
    $('event-timeline').innerHTML = events.length ? events.map((e) => {
      const confirmed = /confirm|cota de pesquisa|acima da cota/i.test(String(e.status || ''));
      const rain = [e.rain_24h_mm, e.rain_72h_mm, e.rain_168h_mm];
      const hasRain = rain.some((v) => num(v) != null);
      const rainHtml = hasRain ? `<div class="event-rain"><div><b>${fmt(e.rain_24h_mm, 1)}</b><span>chuva 24 h · mm</span></div><div><b>${fmt(e.rain_72h_mm, 1)}</b><span>chuva 72 h · mm</span></div><div><b>${fmt(e.rain_168h_mm, 1)}</b><span>chuva 168 h · mm</span></div></div>` : '<div class="event-rain"><div><b>—</b><span>chuva por evento</span></div><div><b>—</b><span>ainda não ligada</span></div><div><b>—</b><span>base em integração</span></div></div>';
      return `<article class="event-card ${confirmed ? 'confirmed' : ''}"><span class="event-date">${esc(e.sourceLabel)} · ${esc(shortDate(e.date))}</span><h3>${esc(e.id || 'Evento catalogado')}</h3><div class="event-peak">${fmt(e.peak_cm, 0)} <span>cm no pico observado</span></div><span class="event-status">${esc(e.status || 'status não informado')}</span>${rainHtml}</article>`;
    }).join('') : '<div class="empty-block">Os eventos históricos ainda não estão disponíveis neste feed.</div>';
  }

  function evaluationBlock(key) {
    const p = stationFeed(key).pattern || {}; const ev = p.evaluation || {}; const rows = Array.isArray(ev.by_horizon) ? ev.by_horizon : [];
    const verdict = ev.model_verdict || 'SEM_AVALIACAO';
    const title = verdict === 'NAO_FUNCIONA_DE_FORMA_CONFIAVEL' ? 'sinal não confiável ainda' : verdict === 'SINAL_PARCIAL_REQUER_VALIDACAO' ? 'sinal parcial; requer validação' : 'avaliação insuficiente';
    const table = rows.length ? `<div class="table-scroll"><table class="evaluation-table"><thead><tr><th>Horizonte</th><th>Recall</th><th>Amostra</th><th>Leitura</th></tr></thead><tbody>${rows.map((r) => `<tr><td>+${esc(r.hours)} h</td><td class="num">${pct(r.sensitivity_percent)}</td><td class="num">n=${esc(r.held_out_events == null ? '—' : r.held_out_events)}</td><td><span class="result-pill ${r.result === 'FORTE' ? 'strong' : ''}">${esc(r.result || '—')}</span></td></tr>`).join('')}</tbody></table></div>` : '<p class="method-note">Sem métricas por horizonte neste feed.</p>';
    return `<div class="evaluation-summary"><strong>${esc(title)}</strong><span>${esc(ev.threshold_used || 'limiar não informado')} · resultados retrospectivos, não promessa operacional.</span></div>${table}<p class="method-note">${esc(ev.false_positive_metrics || 'Taxa de falsos positivos não publicada para esta base.')}</p>`;
  }
  function renderEvaluation() {
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    $('evaluation-content').innerHTML = keys.map((key) => { const summary = (stationFeed(key).pattern || {}).summary || {}; const count = summary.model_card_event_count ?? summary.event_count ?? '—'; return `<section class="evaluation-station"><h3>${esc(stations[key].label)} <span>· ${esc(count)} eventos no cartão de validação</span></h3>${evaluationBlock(key)}</section>`; }).join('');
  }

  function freshnessState(snap) {
    const feedAge = snap.forecastAge; const observedAge = snap.observedAge;
    if (feedAge == null) return ['desconhecido', 'pending'];
    if (feedAge > 72 || (observedAge != null && observedAge > 3)) return ['parcial / atrasado', 'proxy'];
    return ['publicado', ''];
  }
  function provenanceRow(label, detail, status, cls = '') {
    return `<div class="provenance-row"><div><strong>${esc(label)}</strong><span>${esc(detail)}</span></div><span class="provenance-state ${cls}">${esc(status)}</span></div>`;
  }
  function renderProvenance() {
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    const html = keys.map((key) => {
      const s = stationSnapshot(key, state.horizon); const [feedState, feedClass] = freshnessState(s); const soilState = key === 'mucum' ? 'proxy' : 'indisponível';
      const rain = displayRain(s);
      return `<section class="provenance-station"><h3>${esc(s.station.label)} <span>· rodada ${esc(when(sourceGenerated(s)))}</span></h3>${provenanceRow('Nível ANA/SGB', `${liveSourceText(s)} · ${when(s.levelAt)} · ${ageLabel(s.observedAge)}`, s.level == null ? 'UNKNOWN' : s.observedAge != null && s.observedAge > 3 ? 'atrasado' : 'observado', s.level == null || (s.observedAge != null && s.observedAge > 3) ? 'pending' : '')}${provenanceRow('Chuva prevista', `${rain.label} · fonte principal · +${state.horizon} h`, rain.value == null ? 'UNKNOWN' : feedState, feedClass)}${provenanceRow('Risco de pesquisa', `estimativa experimental · ${s.pattern && s.pattern.sources && s.pattern.sources.probability || 'JSON de probabilidade'}`, s.risk == null ? 'UNKNOWN' : 'experimental', s.risk == null ? 'pending' : 'proxy')}${provenanceRow('Solo / saturação', key === 'mucum' ? 'umidade modelada; não é medição local' : 'medição local não publicada', soilState, 'proxy')}${provenanceRow('Zonas e propagação', 'polígonos, radar/QPE e tempos de viagem', 'integração pendente', 'pending')}</section>`;
    }).join('');
    $('provenance-content').innerHTML = html;
  }

  function renderStatus() {
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    const loaded = state.lastLoadedAt ? ` · consulta ${when(state.lastLoadedAt)}` : '';
    $('control-status').textContent = `${keys.map((key) => { const s = stationSnapshot(key, state.horizon); return `${stations[key].label}: feed ${ageLabel(s.forecastAge)} · observação ${ageLabel(s.observedAge)}`; }).join(' · ')} · horário em BRT${loaded}`;
  }
  function render() {
    renderAnswer(); renderResearchContext(); renderKpis(); renderStationComparison(); renderZones(); renderModels(); renderEvents(); renderEvaluation(); renderProvenance(); renderStatus();
  }

  async function loadJson(url) {
    try {
      const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}cb=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) return null;
      return await response.json();
    } catch (_) { return null; }
  }
  async function loadFeeds() {
    const pairs = Object.entries(stations);
    await Promise.all(pairs.map(async ([key, cfg]) => {
      const [pattern, weather, live] = await Promise.all([loadJson(cfg.pattern), loadJson(cfg.weather), loadJson(cfg.live)]);
      state.feeds[key] = { pattern, weather, live };
    }));
    state.research = await loadJson(researchUrl);
    state.lastLoadedAt = new Date().toISOString();
    const available = pairs.filter(([key]) => stationFeed(key).pattern || stationFeed(key).weather).length;
    $('control-status').textContent = available ? `Feeds publicados carregados às ${when(state.lastLoadedAt)} · escolha local e horizonte` : 'Feeds indisponíveis no momento · tente atualizar a página';
    render();
  }

  const refresh = $('refresh-feeds');
  if (refresh) {
    refresh.addEventListener('click', async () => {
      refresh.disabled = true;
      refresh.setAttribute('aria-busy', 'true');
      refresh.textContent = 'Atualizando…';
      $('control-status').textContent = 'Consultando feeds publicados…';
      try { await loadFeeds(); }
      finally {
        refresh.disabled = false;
        refresh.removeAttribute('aria-busy');
        refresh.textContent = 'Atualizar dados';
      }
    });
  }

  root.querySelectorAll('[data-station]').forEach((button) => {
    button.addEventListener('click', () => {
      state.station = button.dataset.station || 'basin';
      root.querySelectorAll('[data-station]').forEach((b) => { b.classList.toggle('is-active', b === button); b.setAttribute('aria-pressed', b === button ? 'true' : 'false'); });
      render();
    });
  });
  root.querySelectorAll('[data-horizon]').forEach((button) => {
    button.addEventListener('click', () => {
      state.horizon = Number(button.dataset.horizon) || 72;
      root.querySelectorAll('[data-horizon]').forEach((b) => { b.classList.toggle('is-active', b === button); b.setAttribute('aria-pressed', b === button ? 'true' : 'false'); });
      render();
    });
  });
  loadFeeds();
})();
