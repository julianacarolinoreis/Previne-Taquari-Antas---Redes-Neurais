/* PREVINE · dashboard integrado da bacia
 * Os valores são lidos dos artefatos publicados; este arquivo não inventa uma
 * probabilidade conjunta nem transforma score em probabilidade calibrada.
 */
(function () {
  'use strict';

  const root = document.querySelector('[data-bacia-dashboard]');
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const state = { station: 'basin', horizon: 72, feeds: {}, research: null, rainSummary: null, rainSpatial: { grid: null, components: null, loading: false, error: null }, rainMapMode: 'forecast', rainMapHours: 72, basinGeometry: null, networkStatus: null, networkFilter: 'all', networkSource: 'all', networkUpg: 'all', networkVariable: 'all', networkModel: 'all', networkMode: 'health', selectedNetworkStationId: null, lastLoadedAt: null, loading: false };
  const researchUrl = 'assets/data/research_basin_screening_latest.json';
  const basinStatusUrl = 'assets/data/basin_station_status_latest.json';
  const rainSummaryUrl = 'assets/data/hec_hms_g040_full_basin/g040_adaptive_scenario_latest.json';
  const rainGridUrl = 'assets/data/hec_hms_g040_full_basin/whole_basin_rain_forcing_fullgrid_hourly.csv';
  const rainComponentsUrl = 'assets/data/hec_hms_g040_full_basin/whole_basin_rain_forcing_components_hourly.csv';
  const basinUrl = 'assets/data/estudo_bacia_taquari_antas/ugs_g040.geojson';
  const AUTO_REFRESH_MS = 5 * 60 * 1000;
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
    let s = String(value).trim();
    if (/\s+UTC$/i.test(s)) s = s.replace(/\s+UTC$/i, 'Z');
    s = s.replace(' ', 'T');
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
    return { key, horizon: hours, station: s, pattern: f.pattern, weather: f.weather, live, p, w, obs, level, levelAt, pointRain, basinMean, basinMax, meanRain, maxRain, directRain, ifsProxyRain, gefsProxyRain, soil, risk, archivedRisk, riskUsable, riskState: integratedRisk.state || 'unknown', riskGenerated: integratedRisk.generated_at_utc, riskCalibration: integratedRisk.calibration_status, score, decision, archivedDecision, generated, forecastAge, observedAge, coverage };
  }
  function qualityFor(snapshot) {
    const hasObs = snapshot.level != null;
    const hasForecast = snapshot.meanRain != null || snapshot.directRain != null;
    const obsGood = hasObs && (snapshot.observedAge == null || snapshot.observedAge <= 1.5);
    const obsUsable = hasObs && (snapshot.observedAge == null || snapshot.observedAge <= 3);
    const forecastGood = hasForecast && (snapshot.forecastAge == null || snapshot.forecastAge <= 18);
    const forecastUsable = hasForecast && (snapshot.forecastAge == null || snapshot.forecastAge <= 36);
    const partial = snapshot.coverage != null && snapshot.coverage < snapshot.horizon;
    if (!hasObs && !hasForecast) return { label: 'UNKNOWN', className: 'unknown' };
    if (partial || !obsUsable || !forecastUsable || !obsGood || !forecastGood) return { label: 'STALE / PARCIAL', className: 'warn' };
    return { label: 'FEEDS ATUALIZADOS', className: '' };
  }
  function scoreStateLabel(snap) {
    if (snap.riskState === 'stale' || (snap.risk == null && snap.archivedRisk != null)) return 'STALE · score ocultado';
    if (snap.risk == null) return 'UNKNOWN · sem score utilizável';
    return 'score experimental';
  }
  function scoreStateClass(snap) {
    if (snap.riskState === 'stale' || (snap.risk == null && snap.archivedRisk != null)) return 'warn';
    if (snap.risk == null) return 'unknown';
    return '';
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
  function liveRowsFor(key) {
    const feedKey = key === 'santa_tereza' ? 'santa' : key;
    const live = stationFeed(feedKey).live || {};
    const horizons = live.horizontes && typeof live.horizontes === 'object' ? live.horizontes : {};
    return Object.entries(horizons).map(([name, row]) => {
      const item = row && typeof row === 'object' ? row : {};
      const match = String(name).match(/^(\d+)/);
      const hours = Number(item.horizonte_h ?? (match ? match[1] : NaN));
      const level = num(item.nivel_previsto_cm);
      const available = item.disponivel !== false && level != null;
      // Some live producers leave modelo_papel empty and expose the role only
      // in horizonte/rotulo/versao. Keep the comparative scenario explicit so
      // two forecasts for the same horizon are never presented as one model.
      const roleHint = [name, item.horizonte, item.rotulo, item.versao, item.modelo_papel].filter(Boolean).join(' ');
      const role = /versao_b|versao b|v002|sombra|comparativo/i.test(roleHint)
        ? 'comparativo'
        : (item.modelo_papel || 'principal');
      const quality = item.qualidade_ao_vivo && item.qualidade_ao_vivo.status
        ? item.qualidade_ao_vivo.status
        : /atencao/i.test(String(item.status || '')) ? 'ATENCAO' : 'NORMAL';
      return {
        key: name,
        hours,
        role,
        level_forecast_cm: level,
        available,
        quality_status: quality,
        status: item.status || (available ? 'ok' : 'indisponível'),
      };
    }).filter((item) => Number.isFinite(item.hours)).sort((a, b) => a.hours - b.hours || a.key.localeCompare(b.key));
  }
  function liveGeneratedFor(key) {
    const feedKey = key === 'santa_tereza' ? 'santa' : key;
    const live = stationFeed(feedKey).live || {};
    return live.gerado_em_utc || live.gerado_em || live.consultado_em_utc || live.consultado_em || null;
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

  function nowFreshness(snapshot) {
    if (snapshot.level == null) return { label: 'SEM LEITURA', className: 'stale' };
    if (snapshot.observedAge == null || snapshot.observedAge <= 1.5) return { label: 'TELEMETRIA RECENTE', className: '' };
    if (snapshot.observedAge <= 3) return { label: 'ATENÇÃO À IDADE', className: 'warn' };
    return { label: 'TELEMETRIA ATRASADA', className: 'stale' };
  }
  function shortForecastRows(key) {
    return liveRowsFor(key)
      .filter((row) => row.available && num(row.level_forecast_cm) != null && row.hours <= 12)
      .sort((a, b) => a.hours - b.hours || (Number(a.role === 'comparativo') - Number(b.role === 'comparativo')) || a.key.localeCompare(b.key));
  }
  function renderNowStations() {
    const host = $('now-stations');
    if (!host) return;
    host.innerHTML = ['santa', 'mucum'].map((key) => {
      const snap = stationSnapshot(key);
      const fresh = nowFreshness(snap);
      const threshold = num(snap.station.threshold);
      const level = num(snap.level);
      const ratio = level != null && threshold ? Math.max(0, Math.min(100, level / threshold * 100)) : 0;
      const gap = level != null && threshold != null ? threshold - level : null;
      const gapText = gap == null
        ? 'sem distância calculável até a cota'
        : gap > 0
          ? `${fmt(gap / 100, 2)} m abaixo da cota de pesquisa`
          : gap < 0
            ? `${fmt(Math.abs(gap) / 100, 2)} m acima da cota de pesquisa`
            : 'na cota de pesquisa';
      const rows = shortForecastRows(key);
      const forecasts = rows.length ? rows.map((row) => {
        const comparative = row.role === 'comparativo' || row.role === 'sombra_experimental';
        return `<span class="now-forecast-chip ${comparative ? 'comparative' : ''}"><b>+${esc(row.hours)} h · ${fmt(row.level_forecast_cm / 100, 2)} m</b><span>${comparative ? 'comparativo' : 'principal'}${row.quality_status && row.quality_status !== 'NORMAL' ? ` · ${esc(row.quality_status)}` : ''}</span></span>`;
      }).join('') : '<span class="empty-block">Sem RNA curta publicada neste feed.</span>';
      const live = snap.live || {};
      const audit = live.auditoria_inputs || {};
      const missing = num(audit.n_inputs_ausentes ?? live.inputs_faltantes_n);
      const auditLabel = audit.status || (missing === 0 ? 'NORMAL' : 'ATENÇÃO');
      const issued = liveGeneratedFor(key);
      return `<article class="now-station-card ${fresh.className ? 'is-attention' : ''}">
        <div class="now-station-head"><div class="now-station-name"><h3>${esc(snap.station.label)}</h3><span>ANA/SGB ${esc(snap.station.code)}</span></div><span class="now-freshness ${fresh.className}">${esc(fresh.label)}</span></div>
        <div class="now-primary-grid">
          <div class="now-level"><strong>${level == null ? '—' : fmt(level / 100, 2)} <span>m</span></strong><small>${level == null ? 'sem nível observado' : `${fmt(level, 0)} cm · ${ageLabel(snap.observedAge)}`}</small></div>
          <div class="now-threshold"><div class="now-threshold-row"><strong>Cota de pesquisa</strong><span>${threshold == null ? '—' : `${fmt(threshold / 100, 2)} m`}</span></div><div class="now-level-track ${gap != null && gap <= 0 ? 'is-over' : ''}" aria-label="${esc(gapText)}"><i style="width:${ratio.toFixed(1)}%"></i></div><p class="now-threshold-note">${esc(gapText)}.</p></div>
        </div>
        <div class="now-short-title"><strong>RNA de nível · curto prazo</strong><span>centímetros convertidos para metros · cenários separados</span></div>
        <div class="now-forecast-row">${forecasts}</div>
        <div class="now-station-foot"><span><strong>Observado:</strong> ${esc(when(snap.levelAt))} BRT</span><span><strong>Rodada RNA:</strong> ${esc(when(issued))} BRT</span><span><strong>Inputs:</strong> ${esc(auditLabel)}${missing != null ? ` · ${fmt(missing, 0)} ausentes` : ''}</span><span><strong>Atualização automática:</strong> 5 min</span></div>
      </article>`;
    }).join('');
  }


  function geoRings(data) {
    if (!data) return [];
    const geometries = data.type === 'FeatureCollection'
      ? (data.features || []).map((f) => f && f.geometry).filter(Boolean)
      : data.type === 'Feature' ? [data.geometry] : [data];
    const rings = [];
    geometries.forEach((geometry) => {
      if (!geometry) return;
      if (geometry.type === 'Polygon') (geometry.coordinates || []).forEach((ring) => rings.push(ring));
      if (geometry.type === 'MultiPolygon') (geometry.coordinates || []).forEach((polygon) => (polygon || []).forEach((ring) => rings.push(ring)));
    });
    return rings.filter((ring) => Array.isArray(ring) && ring.length > 2);
  }

  function networkStations() {
    const rows = state.networkStatus && Array.isArray(state.networkStatus.stations) ? state.networkStatus.stations : [];
    return rows.filter((item) => item && num(item.latitude) != null && num(item.longitude) != null);
  }
  function networkSourceObservations(item) {
    return Array.isArray(item && item.source_observations) ? item.source_observations.filter((row) => row && typeof row === 'object') : [];
  }
  function networkLevelInfo(item) {
    const level = item && item.level && typeof item.level === 'object' ? item.level : {};
    const cm = num(level.current_cm);
    const rawCm = num(level.raw_current_cm);
    const plausible = cm != null && cm >= 0 && cm <= 5000 && level.measurement_classification !== 'cota_or_incompatible_scale';
    return { level, cm, rawCm, plausible, metres: plausible ? cm / 100 : null };
  }
  function networkObservation(item) {
    const dated = [];
    let hasValue = false;
    const levelInfo = networkLevelInfo(item);
    if (levelInfo.cm != null && levelInfo.plausible) {
      hasValue = true;
      if (parseDate(levelInfo.level.observed_at_utc)) dated.push(levelInfo.level.observed_at_utc);
    }
    const rain = item && item.observed_rain && typeof item.observed_rain === 'object' ? item.observed_rain : {};
    if (rain.state === 'available') {
      hasValue = true;
      if (parseDate(rain.last_observed_at_utc)) dated.push(rain.last_observed_at_utc);
    }
    networkSourceObservations(item).forEach((row) => {
      const sourceOk = row.source_status == null || String(row.source_status) === '0';
      if (num(row.value) == null || !sourceOk) return;
      hasValue = true;
      if (row.source !== 'CEMADEN' && parseDate(row.updated_at_utc)) dated.push(row.updated_at_utc);
    });
    if (!dated.length) return hasValue
      ? { status: 'no-time', ageHours: null, latestAt: null, hasValue: true }
      : { status: 'none', ageHours: null, latestAt: null, hasValue: false };
    dated.sort((a, b) => (parseDate(b)?.getTime() || 0) - (parseDate(a)?.getTime() || 0));
    const latestAt = dated[0];
    const age = ageHours(latestAt);
    if (age == null) return { status: 'no-time', ageHours: null, latestAt, hasValue: true };
    if (age <= .5) return { status: 'current', ageHours: age, latestAt, hasValue: true };
    if (age <= 1) return { status: 'attention', ageHours: age, latestAt, hasValue: true };
    if (age <= 3) return { status: 'delayed', ageHours: age, latestAt, hasValue: true };
    return { status: 'very-delayed', ageHours: age, latestAt, hasValue: true };
  }
  function networkStatusLabel(status) {
    if (status === 'current') return 'ATUAL · ≤30 min';
    if (status === 'attention') return 'ATENÇÃO · 30–60 min';
    if (status === 'delayed') return 'ATRASADO · 1–3 h';
    if (status === 'very-delayed') return 'MUITO ATRASADO · >3 h';
    if (status === 'no-time') return 'OBSERVADO · SEM HORA INDIVIDUAL';
    return 'SEM OBSERVADO';
  }
  function networkHasVariable(item, variable) {
    if (variable === 'all') return true;
    if (variable === 'level') {
      if (networkLevelInfo(item).cm != null) return true;
      return networkSourceObservations(item).some((row) => /nivel/i.test(String(row.metric || '')) && num(row.value) != null);
    }
    if (variable === 'rain') {
      if (item.observed_rain && item.observed_rain.state === 'available') return true;
      return networkSourceObservations(item).some((row) => /chuva/i.test(String(row.metric || '')) && num(row.value) != null);
    }
    if (variable === 'flow') return !!networkFlow(item);
    if (variable === 'rna') return !!(item.level && item.level.forecast_applicable);
    return true;
  }
  function networkMatchesFilter(item) {
    const observed = networkObservation(item);
    if (state.networkFilter === 'le1h' && !['current', 'attention'].includes(observed.status)) return false;
    if (state.networkFilter === '1to3' && observed.status !== 'delayed') return false;
    if (state.networkFilter === 'over3' && observed.status !== 'very-delayed') return false;
    if (state.networkFilter === 'no-time' && observed.status !== 'no-time') return false;
    if (state.networkFilter === 'no-current' && ['current', 'attention'].includes(observed.status)) return false;
    if (state.networkFilter === 'none' && observed.status !== 'none') return false;
    if (state.networkSource !== 'all' && !(item.source_networks || []).includes(state.networkSource)) return false;
    if (state.networkUpg !== 'all' && String(item.upg_label || 'UPG não informada') !== state.networkUpg) return false;
    if (!networkHasVariable(item, state.networkVariable)) return false;
    if (state.networkModel !== 'all') {
      const model = item.forecast && item.forecast.models && item.forecast.models[state.networkModel];
      if (!model || model.available !== true || model.precipitation_state === 'unavailable') return false;
    }
    return true;
  }
  function networkRainWindow(item, hours) {
    const windows = item && item.observed_rain && item.observed_rain.windows ? item.observed_rain.windows : {};
    return windows[String(hours) + 'h'] || {};
  }
  function networkCemadenRain(item) {
    return networkSourceObservations(item).find((row) =>
      row.source === 'CEMADEN' && row.metric === 'chuva_acumulada_24h_mm' &&
      num(row.value) != null && (row.source_status == null || String(row.source_status) === '0')
    ) || null;
  }
  function networkFlow(item) {
    return networkSourceObservations(item).find((row) => /vazao|vazão/i.test(String(row.metric || '')) && num(row.value) != null) || null;
  }
  function networkModelLabel(modelId) {
    const rows = state.networkStatus && Array.isArray(state.networkStatus.models) ? state.networkStatus.models : [];
    const found = rows.find((row) => row.id === modelId);
    return found && found.label ? found.label : modelId;
  }

  function populateNetworkUpgFilter() {
    const select = $('basin-upg-filter');
    if (!select) return;
    const values = [...new Set(networkStations().map((item) => String(item.upg_label || 'UPG não informada')).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, 'pt-BR'));
    const current = state.networkUpg;
    select.innerHTML = '<option value="all">Todas as sub-bacias</option>' + values.map((value) =>
      '<option value="' + esc(value) + '">' + esc(value) + '</option>'
    ).join('');
    select.value = values.includes(current) ? current : 'all';
    if (select.value === 'all') state.networkUpg = 'all';
  }

  function populateNetworkStationSearch() {
    const list = $('basin-station-options');
    if (!list) return;
    list.innerHTML = networkStations().slice()
      .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR'))
      .map((item) => '<option value="' + esc((item.code || '') + ' · ' + (item.name || 'Estação')) + '"></option>')
      .join('');
  }

  function findNetworkStation(query) {
    const raw = String(query || '').trim().toLocaleLowerCase('pt-BR');
    if (!raw) return null;
    const codeToken = raw.split('·')[0].trim();
    const rows = networkStations();
    return rows.find((item) => String(item.code || '').toLocaleLowerCase('pt-BR') === codeToken) ||
      rows.find((item) => String(item.name || '').toLocaleLowerCase('pt-BR') === raw) ||
      rows.find((item) => (String(item.code || '') + ' · ' + String(item.name || '')).toLocaleLowerCase('pt-BR') === raw) ||
      rows.find((item) => String(item.code || '').toLocaleLowerCase('pt-BR').includes(raw) || String(item.name || '').toLocaleLowerCase('pt-BR').includes(raw)) ||
      null;
  }

  function clearNetworkFilters() {
    state.networkFilter = 'all';
    state.networkSource = 'all';
    state.networkUpg = 'all';
    state.networkVariable = 'all';
    state.networkModel = 'all';
    root.querySelectorAll('[data-network-filter]').forEach((button) => {
      const active = button.dataset.networkFilter === 'all';
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    ['basin-source-filter', 'basin-upg-filter', 'basin-variable-filter', 'basin-model-filter'].forEach((id) => {
      const select = $(id);
      if (select) select.value = 'all';
    });
    const search = $('basin-station-search');
    if (search) search.value = '';
    const status = $('basin-search-status');
    if (status) status.textContent = '';
  }

  function networkSourceSummary(status) {
    const counts = status && status.source_counts && typeof status.source_counts === 'object' ? status.source_counts : {};
    const order = ['ANA/HidroWeb', 'SGB/SACE', 'CEMADEN', 'INMET'];
    return order.filter((key) => num(counts[key]) != null).map((key) =>
      '<span><b>' + esc(key) + '</b> ' + fmt(counts[key], 0) + '</span>'
    ).join('');
  }

  function networkForecastCoverageSummary(status) {
    const precipitation = status && status.metric_coverage && status.metric_coverage.precipitation;
    const models = precipitation && precipitation.models && typeof precipitation.models === 'object' ? precipitation.models : {};
    return Object.entries(models).map(([modelId, row]) => {
      const ratio = num(row && row.coverage_ratio);
      return '<span class="' + (ratio != null && ratio < .999 ? 'is-partial' : '') + '"><b>' + esc(networkModelLabel(modelId)) + '</b> ' + (ratio == null ? '—' : fmt(ratio * 100, 1) + '%') + '</span>';
    }).join('');
  }

  function networkUpgRows() {
    const groups = new Map();
    networkStations().forEach((item) => {
      const key = String(item.upg_label || 'UPG não informada');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    return [...groups.entries()].map(([label, rows]) => {
      const states = rows.map(networkObservation);
      const current30 = states.filter((row) => row.status === 'current').length;
      const attention = states.filter((row) => row.status === 'attention').length;
      const delayed = states.filter((row) => row.status === 'delayed').length;
      const veryDelayed = states.filter((row) => row.status === 'very-delayed').length;
      const noTime = states.filter((row) => row.status === 'no-time').length;
      const none = states.filter((row) => row.status === 'none').length;
      const current60 = current30 + attention;
      const observed = rows.length - none;
      return {
        label, total: rows.length, current30, attention, current60, delayed,
        veryDelayed, noTime, none, observed,
        currentRatio: rows.length ? current60 / rows.length : 0,
        observedRatio: rows.length ? observed / rows.length : 0
      };
    }).sort((a, b) => a.currentRatio - b.currentRatio || b.total - a.total || a.label.localeCompare(b.label, 'pt-BR'));
  }

  function renderUpgHealth() {
    const host = $('basin-upg-health');
    if (!host) return;
    const groups = networkUpgRows();
    if (!groups.length) {
      host.innerHTML = '<div class="empty-block">Sem sub-bacias disponíveis no snapshot atual.</div>';
      return;
    }
    const lowest = groups[0];
    host.innerHTML = '<div class="upg-health-head"><div><span class="now-eyebrow">Cobertura observacional por sub-bacia</span><h4>Lacunas de atualização da rede G040</h4></div><span>' + (lowest ? esc(lowest.label) + ': ' + fmt(lowest.current60, 0) + '/' + fmt(lowest.total, 0) + ' estações ≤1 h' : 'ordenado pela menor cobertura ≤1 h') + '</span></div>' +
      '<div class="upg-health-table-wrap"><table class="upg-health-table"><thead><tr><th>Sub-bacia</th><th>Estações</th><th>≤30 min</th><th>30–60 min</th><th>1–3 h</th><th>&gt;3 h</th><th>Sem hora</th><th>Sem observado</th><th>≤1 h</th></tr></thead><tbody>' +
      groups.map((row) => '<tr data-upg-row="' + esc(row.label) + '"><td><button type="button" class="upg-link" data-upg-select="' + esc(row.label) + '">' + esc(row.label) + '</button></td><td>' + fmt(row.total, 0) + '</td><td>' + fmt(row.current30, 0) + '</td><td>' + fmt(row.attention, 0) + '</td><td>' + fmt(row.delayed, 0) + '</td><td>' + fmt(row.veryDelayed, 0) + '</td><td>' + fmt(row.noTime, 0) + '</td><td>' + fmt(row.none, 0) + '</td><td><strong>' + fmt(row.currentRatio * 100, 0) + '%</strong></td></tr>').join('') +
      '</tbody></table></div><p class="upg-health-note">Esta é cobertura da rede observacional publicada no snapshot, não risco de inundação. “Sem hora” significa que há valor observado, mas a fonte não fornece relógio individual utilizável para classificar frescor.</p>';
    host.querySelectorAll('[data-upg-select]').forEach((button) => {
      button.addEventListener('click', () => {
        state.networkUpg = button.getAttribute('data-upg-select') || 'all';
        const select = $('basin-upg-filter');
        if (select) select.value = state.networkUpg;
        renderBasinMap();
      });
    });
  }

  function networkVariableCoverage() {
    const rows = networkStations();
    const hourlyRain = rows.filter((item) => item.observed_rain && item.observed_rain.state === 'available').length;
    const cemaden24 = rows.filter((item) => !!networkCemadenRain(item)).length;
    const level = rows.filter((item) => networkHasVariable(item, 'level')).length;
    const flow = rows.filter((item) => networkHasVariable(item, 'flow')).length;
    const rnaApplicable = rows.filter((item) => item.level && item.level.forecast_applicable).length;
    const rnaAvailable = rows.filter((item) => item.level && item.level.forecast_status === 'available').length;
    const observedAny = rows.filter((item) => networkObservation(item).hasValue).length;
    return { total: rows.length, hourlyRain, cemaden24, level, flow, rnaApplicable, rnaAvailable, observedAny };
  }

  function renderGapDiagnostics() {
    const host = $('basin-gap-diagnostics');
    if (!host) return;
    const rows = networkStations();
    if (!rows.length) {
      host.innerHTML = '<div class="empty-block">Snapshot por estação ainda indisponível para diagnosticar lacunas.</div>';
      return;
    }
    const coverage = networkVariableCoverage();
    const stale = rows.map((item) => ({ item, observed: networkObservation(item) }))
      .filter((row) => ['delayed', 'very-delayed'].includes(row.observed.status) && row.observed.ageHours != null)
      .sort((a, b) => b.observed.ageHours - a.observed.ageHours)
      .slice(0, 8);
    const blindSubBasins = networkUpgRows().slice()
      .sort((a, b) => (b.none / Math.max(1, b.total)) - (a.none / Math.max(1, a.total)) || b.none - a.none)
      .slice(0, 4);
    const noTime = rows.filter((item) => networkObservation(item).status === 'no-time').length;
    const cards = [
      ['Chuva horária', coverage.hourlyRain, coverage.total, 'rain', 'série observada com relógio'],
      ['CEMADEN 24 h', coverage.cemaden24, coverage.total, 'rain', 'acumulado observado'],
      ['Nível', coverage.level, coverage.total, 'level', 'valor hidrológico válido'],
      ['Vazão', coverage.flow, coverage.total, 'flow', 'vazão observada publicada'],
      ['RNA de nível', coverage.rnaAvailable, coverage.rnaApplicable, 'rna', 'disponível / aplicável']
    ];
    const staleHtml = stale.length ? stale.map((row) =>
      '<button type="button" class="gap-station-row" data-gap-station="' + esc(row.item.id || row.item.code || '') + '">' +
        '<span><strong>' + esc(row.item.name || 'Estação') + '</strong><small>' + esc(row.item.code || '') + ' · ' + esc(row.item.upg_label || 'sub-bacia não informada') + '</small></span>' +
        '<b>' + esc(ageLabel(row.observed.ageHours)) + '</b>' +
      '</button>'
    ).join('') : '<p class="network-detail-empty">Nenhuma estação com observação datada acima de 1 h neste snapshot.</p>';
    const blindHtml = blindSubBasins.map((row) => {
      const ratio = row.total ? row.none / row.total : 0;
      return '<button type="button" class="gap-subbasin-row" data-gap-subbasin="' + esc(row.label) + '">' +
        '<span><strong>' + esc(row.label) + '</strong><small>' + fmt(row.none, 0) + ' de ' + fmt(row.total, 0) + ' sem observado</small></span>' +
        '<b>' + fmt(ratio * 100, 0) + '%</b>' +
      '</button>';
    }).join('');
    host.innerHTML =
      '<div class="gap-diagnostics-head"><div><span class="now-eyebrow">Diagnóstico da rede</span><h4>Cobertura por variável e lacunas de atualização</h4></div><span>' + fmt(coverage.observedAny, 0) + '/' + fmt(coverage.total, 0) + ' com algum observado · ' + fmt(noTime, 0) + ' sem hora individual</span></div>' +
      '<div class="gap-coverage-grid">' + cards.map((row) => {
        const denominator = Number(row[2]) || 0;
        const numerator = Number(row[1]) || 0;
        const pct = denominator ? numerator / denominator * 100 : 0;
        return '<button type="button" class="gap-coverage-card" data-gap-variable="' + esc(row[3]) + '"><span>' + esc(row[0]) + '</span><strong>' + fmt(numerator, 0) + '<small>/' + fmt(denominator, 0) + '</small></strong><i><em style="width:' + Math.max(0, Math.min(100, pct)).toFixed(1) + '%"></em></i><small>' + esc(row[4]) + ' · ' + fmt(pct, 0) + '%</small></button>';
      }).join('') + '</div>' +
      '<div class="gap-diagnostics-split"><section><div class="network-detail-title"><strong>MAIORES ATRASOS COM HORÁRIO</strong><span>idade da última evidência observada</span></div><div class="gap-list">' + staleHtml + '</div></section>' +
      '<section><div class="network-detail-title"><strong>MAIOR PROPORÇÃO SEM OBSERVADO</strong><span>por sub-bacia G040</span></div><div class="gap-list">' + (blindHtml || '<p class="network-detail-empty">Sem sub-bacias calculáveis.</p>') + '</div></section></div>' +
      '<p class="gap-diagnostics-note">Este bloco mede cobertura e frescor da rede publicada. Não representa perigo, severidade da chuva, probabilidade de inundação ou prioridade de evacuação.</p>';

    host.querySelectorAll('[data-gap-variable]').forEach((button) => {
      button.addEventListener('click', () => {
        state.networkVariable = button.getAttribute('data-gap-variable') || 'all';
        const select = $('basin-variable-filter');
        if (select) select.value = state.networkVariable;
        renderBasinMap();
      });
    });
    host.querySelectorAll('[data-gap-station]').forEach((button) => {
      button.addEventListener('click', () => {
        const id = button.getAttribute('data-gap-station');
        clearNetworkFilters();
        state.selectedNetworkStationId = id;
        renderBasinMap();
      });
    });
    host.querySelectorAll('[data-gap-subbasin]').forEach((button) => {
      button.addEventListener('click', () => {
        state.networkUpg = button.getAttribute('data-gap-subbasin') || 'all';
        const select = $('basin-upg-filter');
        if (select) select.value = state.networkUpg;
        renderBasinMap();
      });
    });
  }

  function renderNetworkSummary() {
    const host = $('basin-network-summary');
    const note = $('basin-network-note');
    if (!host) return;
    const status = state.networkStatus || {};
    const scope = status.scope || {};
    const rows = networkStations();
    const total = num(scope.station_count) ?? rows.length;
    const forecast = num(scope.forecast_station_count);
    const observedAny = num(scope.observed_any_station_count);
    const observedStates = rows.map(networkObservation);
    const current30 = observedStates.filter((row) => row.status === 'current').length;
    const attention = observedStates.filter((row) => row.status === 'attention').length;
    const delayed = observedStates.filter((row) => row.status === 'delayed').length;
    const veryDelayed = observedStates.filter((row) => row.status === 'very-delayed').length;
    const noTime = observedStates.filter((row) => row.status === 'no-time').length;
    const none = observedStates.filter((row) => row.status === 'none').length;
    const ages = observedStates.map((row) => row.ageHours).filter((value) => value != null);
    const maxAge = ages.length ? Math.max(...ages) : null;
    const visible = rows.filter(networkMatchesFilter).length;
    const items = [
      ['G040', total == null ? '—' : fmt(total, 0), 'estações no catálogo', 'catalog'],
      ['Previsto', forecast == null ? '—' : fmt(forecast, 0) + '/' + fmt(total, 0), status.coverage && status.coverage.forecast_complete ? 'rodada completa' : 'cobertura parcial', 'forecast'],
      ['≤30 min', rows.length ? fmt(current30, 0) : '—', 'observação atual', 'current'],
      ['30–60 min', rows.length ? fmt(attention, 0) : '—', 'atenção à idade', 'attention'],
      ['1–3 h', rows.length ? fmt(delayed, 0) : '—', 'observação atrasada', 'delayed'],
      ['>3 h', rows.length ? fmt(veryDelayed, 0) : '—', 'muito atrasada', 'very-delayed'],
      ['Sem hora', rows.length ? fmt(noTime, 0) : '—', 'valor sem relógio individual', 'no-time'],
      ['Sem observado', rows.length ? fmt(none, 0) : '—', 'catálogo/previsão apenas', 'none']
    ];
    const sourceSummary = networkSourceSummary(status);
    const forecastCoverageSummary = networkForecastCoverageSummary(status);
    host.innerHTML = '<div class="network-summary-grid">' + items.map((row) =>
      '<div class="network-summary-card is-' + esc(row[3]) + '"><span>' + esc(row[0]) + '</span><strong>' + esc(row[1]) + '</strong><small>' + esc(row[2]) + '</small></div>'
    ).join('') + '</div>' +
      '<div class="network-source-strip"><span class="network-source-title">Catálogo integrado por fonte</span>' + (sourceSummary || '<span>fontes não resumidas</span>') + '</div>' +
      '<div class="network-model-coverage-strip"><span class="network-source-title">Cobertura de pontos previstos · precipitação</span>' + (forecastCoverageSummary || '<span>cobertura não resumida</span>') + '</div>' +
      '<p class="network-summary-note">' +
      (rows.length ? fmt(visible, 0) + ' pontos visíveis no filtro · algum observado ' + (observedAny == null ? '—' : fmt(observedAny, 0) + '/' + fmt(total, 0)) + ' · ' + (maxAge != null ? 'maior idade com relógio ' + ageLabel(maxAge) + ' · ' : '') : 'Resumo geral disponível; snapshot por estação ainda em atualização · ') +
      (status.generated_at_utc ? 'snapshot ' + when(status.generated_at_utc) + ' BRT · ' + ageLabel(ageHours(status.generated_at_utc)) : 'snapshot sem horário') + '.</p>';
    if (note) note.textContent = rows.length ? fmt(visible, 0) + ' de ' + fmt(total, 0) + ' estações visíveis · cor = idade do observado' : 'aguardando snapshot compacto por estação';
  }

  function renderNetworkStationDetail() {
    const host = $('basin-station-detail');
    if (!host) return;
    const rows = networkStations();
    if (!rows.length) {
      host.innerHTML = '<div class="loading-block">O resumo da G040 está disponível; o snapshot compacto por estação ainda está sendo publicado.</div>';
      return;
    }
    let item = rows.find((row) => String(row.id) === String(state.selectedNetworkStationId));
    if (!item) item = rows.find((row) => String(row.code) === '86472600') || rows[0];
    state.selectedNetworkStationId = item.id;
    const observed = networkObservation(item);
    const levelInfo = networkLevelInfo(item);
    const level = levelInfo.level;
    const flow = networkFlow(item);
    const rain = item.observed_rain || {};
    const cemaden = networkCemadenRain(item);
    const sources = (item.source_networks || []).join(' · ') || item.network || 'fonte não informada';
    const levelValue = levelInfo.plausible ? fmt(levelInfo.metres, 2) + ' m' : levelInfo.rawCm != null ? 'não exibido' : '—';
    const levelNote = levelInfo.plausible
      ? fmt(levelInfo.cm, 0) + ' cm · ' + (level.observed_at_utc ? when(level.observed_at_utc) + ' BRT' : 'sem horário')
      : levelInfo.rawCm != null
        ? 'valor bruto ' + fmt(levelInfo.rawCm / 100, 2) + ' m separado como cota/escala incompatível; não usado como nível do rio'
        : 'nível observado indisponível';
    const flowValue = flow ? fmt(flow.value, 2) + ' ' + (flow.unit || 'm³/s') : '—';
    const flowNote = flow ? (flow.source || 'fonte') + ' · ' + (flow.updated_at_utc ? when(flow.updated_at_utc) + ' BRT' : 'sem horário') : 'vazão não publicada neste feed';
    const lastObserved = observed.status === 'none' ? 'nenhuma observação válida' : observed.status === 'no-time' ? 'observação sem hora individual' : when(observed.latestAt) + ' BRT · ' + ageLabel(observed.ageHours);
    const rainHtml = [1,3,6,12,24,48,72].map((hours) => {
      const row = networkRainWindow(item, hours);
      const mm = num(row.mm);
      const cov = num(row.coverage_ratio);
      const small = mm == null ? 'indisponível' : row.complete ? 'janela completa' : fmt((cov || 0) * 100, 0) + '% da janela';
      return '<div class="network-rain-cell"><span>' + hours + ' h</span><strong>' + (mm == null ? '—' : fmt(mm, 1) + ' mm') + '</strong><small>' + esc(small) + '</small></div>';
    }).join('');
    const modelHtml = Object.entries(item.forecast && item.forecast.models || {}).map(([modelId, model]) => {
      const windows = model && model.precipitation_windows_mm || {};
      const h24 = num(windows['24h']);
      const h72 = num(windows['72h']);
      const pState = model && model.precipitation_state ? model.precipitation_state : (model && model.available ? 'available' : 'unavailable');
      const stateLabel = pState === 'complete' ? 'precipitação completa' : pState === 'partial' ? 'precipitação parcial' : pState === 'unavailable' ? 'precipitação indisponível' : 'modelo disponível';
      const stateClass = pState === 'partial' ? ' is-partial' : pState === 'unavailable' ? ' is-unavailable' : '';
      return '<div class="network-model-row' + stateClass + '"><strong>' + esc(networkModelLabel(modelId)) + '</strong><span>' + esc(stateLabel) + '</span><small>+24 h ' + (h24 == null ? '—' : fmt(h24, 1) + ' mm') + ' · +72 h ' + (h72 == null ? '—' : fmt(h72, 1) + ' mm') + '</small></div>';
    }).join('');
    let rnaRows = Array.isArray(level.forecasts) ? level.forecasts.slice() : [];
    if (!rnaRows.length && num(level.forecast_cm) != null) rnaRows = [{ label: 'RNA', cm: level.forecast_cm, time: level.forecast_at_utc }];
    const rnaHtml = level.forecast_applicable
      ? (rnaRows.length ? '<div class="network-rna-grid">' + rnaRows.map((row) =>
          '<div><span>' + esc(row.label || row.id || 'RNA') + '</span><strong>' + (num(row.cm) == null ? '—' : fmt(num(row.cm) / 100, 2) + ' m') + '</strong><small>' + (row.time ? when(row.time) + ' BRT' : 'horário não publicado') + '</small></div>'
        ).join('') + '</div>' : '<p class="network-detail-empty">RNA aplicável, mas sem previsão futura válida nesta rodada.</p>')
      : '<p class="network-detail-empty">RNA de nível não publicada para esta estação. A previsão meteorológica continua independente.</p>';
    const cemadenHtml = cemaden ? '<div class="network-cemaden-note"><strong>CEMADEN 24 h:</strong> ' + fmt(cemaden.value, 1) + ' mm <span>· horário é da atualização do painel, não do relógio individual do sensor' + (cemaden.updated_at_utc ? ' · painel ' + when(cemaden.updated_at_utc) + ' BRT' : '') + '</span></div>' : '';
    const traceParts = [];
    if (levelInfo.cm != null && levelInfo.plausible) {
      traceParts.push('<div class="network-trace-row"><div><strong>' + esc(level.source || 'telemetria de nível') + '</strong><span>nível observado</span></div><b>' + esc(fmt(levelInfo.cm, 0) + ' cm') + '</b><small>' + (level.observed_at_utc ? esc(when(level.observed_at_utc) + ' BRT') : 'sem horário publicado') + '</small></div>');
    } else if (levelInfo.rawCm != null) {
      traceParts.push('<div class="network-trace-row is-suspect"><div><strong>' + esc(level.source || 'telemetria de nível') + '</strong><span>valor vertical bruto bloqueado como nível</span></div><b>' + esc(fmt(levelInfo.rawCm, 0) + ' cm') + '</b><small>' + (level.observed_at_utc ? esc(when(level.observed_at_utc) + ' BRT') : 'sem horário publicado') + '</small></div>');
    }
    if (rain.state === 'available') {
      const rain1h = networkRainWindow(item, 1);
      const rainValue = num(rain1h.mm);
      traceParts.push('<div class="network-trace-row"><div><strong>' + esc(rain.source || 'série horária de chuva') + '</strong><span>chuva observada · última janela 1 h</span></div><b>' + (rainValue == null ? 'série disponível' : esc(fmt(rainValue, 1) + ' mm')) + '</b><small>' + (rain.last_observed_at_utc ? esc(when(rain.last_observed_at_utc) + ' BRT') : 'sem horário publicado') + '</small></div>');
    }
    networkSourceObservations(item).forEach((row) => {
      const value = num(row.value);
      const metric = String(row.metric || 'observação').replace(/_/g, ' ');
      const unit = row.unit ? ' ' + row.unit : '';
      traceParts.push('<div class="network-trace-row"><div><strong>' + esc(row.source || 'fonte') + '</strong><span>' + esc(metric) + '</span></div><b>' + (value == null ? '—' : esc(fmt(value, 2) + unit)) + '</b><small>' + (row.updated_at_utc ? esc(when(row.updated_at_utc) + ' BRT') : 'sem horário publicado') + '</small></div>');
    });
    if (item.forecast && item.forecast.state === 'available') {
      traceParts.push('<div class="network-trace-row is-forecast"><div><strong>Previsão meteorológica multi-modelo</strong><span>ECMWF · GFS · ICON · GEM · Météo-France</span></div><b>previsto</b><small>' + (item.forecast.fetched_at_utc ? esc(when(item.forecast.fetched_at_utc) + ' BRT') : 'sem horário de coleta') + '</small></div>');
    }
    const traceRows = traceParts.join('');
    const traceHtml = '<div class="network-detail-section"><div class="network-detail-title"><strong>RASTREABILIDADE DA ESTAÇÃO</strong><span>fonte · variável · valor · horário publicado</span></div><div class="network-trace-grid">' +
      (traceRows || '<p class="network-detail-empty">Sem dados rastreáveis publicados para esta estação.</p>') +
      '</div><p class="network-trace-note">O horário é preservado conforme cada fonte. Horário de atualização de painel não é tratado como relógio individual do sensor. Valores verticais incompatíveis permanecem auditáveis, mas não são exibidos como nível do rio.</p></div>';
    host.innerHTML =
      '<article class="network-detail-card"><div class="network-detail-head"><div><span class="network-detail-kicker">' + esc(item.upg_label || 'G040') + '</span><h4>' + esc(item.name || 'Estação') + ' <small>' + esc(item.code || '') + '</small></h4><p>' + esc(sources) + (item.type_label ? ' · ' + esc(item.type_label) : '') + '</p></div><span class="network-status-pill ' + esc(observed.status) + '">' + esc(networkStatusLabel(observed.status)) + '</span></div>' +
      '<div class="network-detail-primary"><div><span>NÍVEL OBSERVADO</span><strong>' + levelValue + '</strong><small>' + esc(levelNote) + '</small></div><div><span>VAZÃO OBSERVADA</span><strong>' + flowValue + '</strong><small>' + esc(flowNote) + '</small></div><div><span>ÚLTIMA EVIDÊNCIA OBSERVADA</span><strong>' + (observed.status === 'none' ? '—' : observed.status === 'no-time' ? 'sem hora individual' : ageLabel(observed.ageHours)) + '</strong><small>' + esc(lastObserved) + '</small></div></div>' +
      '<div class="network-detail-section"><div class="network-detail-title"><strong>CHUVA OBSERVADA</strong><span>' + (rain.state === 'available' ? esc(rain.source || 'série horária') : 'série horária indisponível') + '</span></div><div class="network-rain-grid">' + rainHtml + '</div>' + cemadenHtml + '</div>' +
      '<div class="network-detail-split"><div class="network-detail-section"><div class="network-detail-title"><strong>PREVISÃO METEOROLÓGICA</strong><span>separada do observado</span></div><div class="network-model-grid">' + (modelHtml || '<p class="network-detail-empty">Sem resumo de modelos.</p>') + '</div></div><div class="network-detail-section"><div class="network-detail-title"><strong>RNA DE NÍVEL</strong><span>' + (level.forecast_applicable ? 'modelo específico da estação' : 'não aplicável') + '</span></div>' + rnaHtml + '</div></div>' + traceHtml + '</article>';
  }

  function renderBasinMap() {
    const host = $('basin-map');
    if (!host) return;
    renderNetworkSummary();
    renderGapDiagnostics();
    renderUpgHealth();
    const rings = geoRings(state.basinGeometry);
    const all = networkStations();
    if (!rings.length) {
      host.innerHTML = '<div class="empty-block">Limite da G040 indisponível.</div>';
      renderNetworkStationDetail();
      return;
    }
    if (!all.length) {
      host.innerHTML = '<div class="empty-block">Limite da G040 carregado; snapshot compacto por estação ainda em atualização.</div>';
      renderNetworkStationDetail();
      return;
    }
    const coords = rings.flat();
    const lons = coords.map((p) => Number(p[0])).filter(Number.isFinite);
    const lats = coords.map((p) => Number(p[1])).filter(Number.isFinite);
    let minLat = Math.min(...lats), maxLat = Math.max(...lats);
    const cosLat = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
    const xs = lons.map((lon) => lon * cosLat);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const width = 760, height = 430, pad = 26;
    const project = (lon, lat) => [
      pad + ((lon * cosLat - minX) / Math.max(.000001, maxX - minX)) * (width - pad * 2),
      pad + ((maxLat - lat) / Math.max(.000001, maxLat - minLat)) * (height - pad * 2)
    ];
    const paths = rings.map((ring) => {
      const step = Math.max(1, Math.ceil(ring.length / 1200));
      const pts = ring.filter((_, i) => i % step === 0 || i === ring.length - 1).map((p) => project(Number(p[0]), Number(p[1])));
      return pts.length ? 'M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('L') + 'Z' : '';
    }).filter(Boolean).map((d) => '<path class="basin-shape" d="' + d + '"></path>').join('');
    const visible = all.filter(networkMatchesFilter);
    let selected = visible.find((item) => String(item.id) === String(state.selectedNetworkStationId));
    if (!selected && visible.length) {
      selected = visible.find((item) => String(item.code) === '86472600') || visible[0];
      state.selectedNetworkStationId = selected.id;
    }
    const ordered = visible.slice().sort((a, b) => (String(a.id) === String(state.selectedNetworkStationId) ? 1 : 0) - (String(b.id) === String(state.selectedNetworkStationId) ? 1 : 0));
    const points = ordered.map((item) => {
      const xy = project(Number(item.longitude), Number(item.latitude));
      const observed = networkObservation(item);
      const isSelected = String(item.id) === String(state.selectedNetworkStationId);
      const cls = state.networkMode === 'catalog' ? 'is-catalog' : 'is-' + observed.status;
      const title = (item.name || 'Estação') + ' · ' + (item.code || '') + ' · ' + networkStatusLabel(observed.status) + ' · ' + ((item.source_networks || []).join('/') || item.network || 'fonte não informada');
      return '<circle class="network-point ' + cls + (isSelected ? ' is-selected' : '') + '" data-network-id="' + esc(item.id || item.code || '') + '" cx="' + xy[0].toFixed(1) + '" cy="' + xy[1].toFixed(1) + '" r="' + (isSelected ? '5.7' : '3.25') + '" tabindex="0" role="button" aria-label="' + esc(title) + '"><title>' + esc(title) + '</title></circle>';
    }).join('');
    let label = '';
    if (selected) {
      const xy = project(Number(selected.longitude), Number(selected.latitude));
      const anchor = xy[0] > width * .72 ? 'end' : 'start';
      const dx = anchor === 'end' ? -9 : 9;
      label = '<text class="map-label" x="' + (xy[0] + dx).toFixed(1) + '" y="' + (xy[1] - 8).toFixed(1) + '" text-anchor="' + anchor + '">' + esc(selected.name || selected.code) + '</text>';
    }
    host.innerHTML = '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Rede hidrometeorológica da G040 com ' + visible.length + ' estações visíveis de ' + all.length + '">' + paths + points + label + '</svg>' +
      '<div class="basin-map-legend"><span><i class="health-current"></i>≤30 min</span><span><i class="health-attention"></i>30–60 min</span><span><i class="health-delayed"></i>1–3 h</span><span><i class="health-very-delayed"></i>&gt;3 h</span><span><i class="health-no-time"></i>observado sem hora individual</span><span><i class="health-none"></i>sem observado</span></div>';
    host.querySelectorAll('[data-network-id]').forEach((point) => {
      const activate = () => {
        state.selectedNetworkStationId = point.getAttribute('data-network-id');
        renderBasinMap();
      };
      point.addEventListener('click', activate);
      point.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
      });
    });
    renderNetworkStationDetail();
  }
  function renderNowOverview() {
    renderNowStations();
    renderBasinMap();
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
      const directKey = key === 'santa_tereza' ? 'santa' : 'mucum';
      const directSnap = stationSnapshot(directKey, h);
      const currentLevel = directSnap.level != null ? directSnap.level : current.level_cm;
      const currentAt = directSnap.levelAt || current.observed_at_utc;
      const currentState = directSnap.level != null
        ? (directSnap.observedAge == null || directSnap.observedAge <= 1.5 ? 'fresh' : directSnap.observedAge <= 3 ? 'attention' : 'stale')
        : current.state;
      // The integrated research feed is a reproducible snapshot, but the
      // station JSON is the direct owner of the current short-horizon robot.
      // Prefer the direct feed when it exists so this card cannot show an old
      // +2/+4 h value beside a newer observed level.
      const directLiveRows = liveRowsFor(key);
      const liveRows = directLiveRows.length ? directLiveRows : (Array.isArray(item.live_horizons) ? item.live_horizons : []);
      const short = liveRows.length
        ? liveRows.map((f) => {
          const label = f.role === 'comparativo' || f.role === 'sombra_experimental' ? ' (comparativo)' : '';
          const value = f.available ? `${fmt(f.level_forecast_cm, 0)} cm` : 'indisponível';
          const quality = f.quality_status && f.quality_status !== 'NORMAL' ? ` · ${f.quality_status}` : '';
          return `+${f.hours} h${label}: ${value}${quality}`;
        }).join(' · ')
        : 'previsão curta sem valor';
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
          ${researchMetric('Nível observado', currentLevel == null ? '—' : `${fmt(currentLevel, 0)} cm`, `${researchStateLabel(currentState)} · ${when(currentAt)} · feed direto quando disponível`, 'observed')}
          ${researchMetric('Pontos a montante · proxy', headValue, headNote, head.status === 'shared_santa_reference' ? 'proxy' : 'forecast')}
          ${researchMetric('Chuva no ponto', point, `acumulado previsto · +${h} h`, 'forecast')}
          ${researchMetric('Cruzamento da cota', prob, probNote, 'risk')}
        </div>
        <p class="research-context-short"><strong>Robô ao vivo:</strong> ${esc(short)}. <span class="research-context-live-source">${esc(directLiveRows.length ? `feed direto · gerado em ${when(liveGeneratedFor(key))}` : 'snapshot integrado · horário da rodada acima')}</span></p>
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
      const usableScores = [a, b].filter((s) => s.risk != null);
      const riskNote = usableScores.length
        ? ` Scores experimentais atuais utilizáveis: ${usableScores.map((s) => `${s.station.label} ${pct(s.risk)}`).join(' · ')}.`
        : ' Nenhum score experimental atual está utilizável; valores antigos permanecem apenas nos JSONs para auditoria.';
      answerText.textContent = `Santa Tereza: ${fmt(ar.value, 2)} mm (${ar.label}); Muçum: ${fmt(br.value, 2)} mm (${br.label}).${riskNote} Não há probabilidade conjunta publicada.`;
      answerState.textContent = 'COMPARAÇÃO'; answerState.className = 'answer-state warn';
      return;
    }
    const snap = stationSnapshot(state.station, hours); const rain = displayRain(snap);
    const riskStale = snap.riskState === 'stale' || (snap.risk == null && snap.archivedRisk != null);
    const riskText = snap.risk == null
      ? (riskStale ? 'score atrasado ocultado — estado STALE, não “não vai inundar”' : 'UNKNOWN: sem estimativa experimental utilizável')
      : `score experimental ${pct(snap.risk)} de cruzar ${fmt(snap.station.threshold / 100, 2)} m (${fmt(snap.station.threshold, 0)} cm)`;
    answerTitle.textContent = `${snap.station.label}: janela de +${hours} h`;
    const coverageNote = snap.coverage != null && snap.coverage < hours ? ` A cobertura publicada é parcial (${fmt(snap.coverage, 0)}/${hours} h).` : '';
    answerText.textContent = `Previsão principal: ${fmt(rain.value, 2)} mm (${rain.label}). ${riskText}.${coverageNote} O corte 50% (VAI/NÃO VAI) foi retirado da leitura pública.`;
    answerState.textContent = riskStale ? 'STALE' : snap.risk == null ? 'UNKNOWN' : 'PESQUISA';
    answerState.className = `answer-state ${riskStale || snap.risk == null ? 'unknown' : ''}`;
  }

  function renderLayers() {
    const hours = state.horizon;
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    const snaps = keys.map((key) => stationSnapshot(key, hours));
    function setLayer(id, title, note, mode) {
      const el = $(id);
      if (!el) return;
      el.classList.remove('is-unknown', 'is-stale', 'is-blocked');
      if (mode) el.classList.add(mode);
      const strong = el.querySelector('strong');
      const p = el.querySelector('p');
      if (strong) strong.textContent = title;
      if (p) p.textContent = note;
    }
    const hasLevel = snaps.some((s) => s.level != null);
    const staleObs = snaps.some((s) => s.observedAge != null && s.observedAge > 3);
    if (!hasLevel) {
      setLayer('layer-previsao', 'UNKNOWN', 'sem nível observado utilizável · ausência ≠ rio baixo', 'is-unknown');
    } else if (staleObs) {
      setLayer('layer-previsao', 'STALE', snaps.map((s) => `${s.station.label}: ${fmt(s.level, 0)} cm · ${ageLabel(s.observedAge)}`).join(' · '), 'is-stale');
    } else {
      setLayer('layer-previsao', snaps.map((s) => `${fmt(s.level, 0)} cm`).join(' · '), `horizonte +${hours} h · RNA de nível em sombra, não probabilidade de inundação`, '');
    }
    const cota = state.station === 'mucum' ? 'limiar de referência 18,00 m / 1.800 cm' : state.station === 'santa' ? 'limiar de referência 15,00 m / 1.500 cm' : 'limiares de referência · ST 15,00 m · Muçum 18,00 m';
    const usableRisk = snaps.some((s) => s.risk != null);
    const staleRisk = snaps.some((s) => s.riskState === 'stale' || (s.risk == null && s.archivedRisk != null));
    if (staleRisk && !usableRisk) {
      setLayer('layer-perigo', 'STALE', `cota oficial ${cota} · HAND 0 é leito, não inundação · score atrasado ocultado`, 'is-stale');
    } else if (!usableRisk) {
      setLayer('layer-perigo', 'UNKNOWN', `cota oficial ${cota} · HAND 0 (~4–5 m) não é inundação · sem score utilizável`, 'is-unknown');
    } else {
      setLayer('layer-perigo', snaps.map((s) => pct(s.risk)).join(' · ') + ' exp.', `cota oficial ${cota} · score experimental, sem corte 50% · HAND 0 separado`, '');
    }
    setLayer('layer-exposicao', 'UNKNOWN', 'Censo 2022 existe; join mancha validada × grade 200 m ainda não publicado', 'is-unknown');
    if (state.station === 'mucum') {
      setLayer('layer-resposta', 'Bloqueado', 'Muçum ainda sem sala V002. Abrigo canônico e relógio ANA–SACE pendentes.', 'is-blocked');
    } else {
      setLayer('layer-resposta', 'Bloqueado', 'Sala V002: 0/7 confirmações. Ginásio sem capacidade. Não despachar.', 'is-blocked');
    }
  }

  function renderKpis() {
    const hours = state.horizon;
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    const snaps = keys.map((key) => stationSnapshot(key, hours));
    const level = snaps.map((s) => `${s.station.label}: ${fmt(s.level, 0)} cm`).join(' · ');
    const rain = snaps.map((s) => { const r = displayRain(s); return `${s.station.label}: ${fmt(r.value, 2)} mm`; }).join(' · ');
    const risk = snaps.map((s) => `${s.station.label}: ${pct(s.risk)}`).join(' · ');
    const qualities = snaps.map(qualityFor);
    const worst = qualities.some((q) => q.className === 'unknown') ? { label: 'UNKNOWN', className: 'unknown' } : qualities.some((q) => q.className === 'warn') ? { label: 'STALE / PARCIAL', className: 'warn' } : { label: 'FEEDS ATUALIZADOS', className: '' };
    const missingLevel = snaps.every((s) => s.level == null);
    const missingRain = snaps.every((s) => displayRain(s).value == null);
    const missingRisk = snaps.every((s) => s.risk == null);
    $('kpi-level').textContent = missingLevel ? 'UNKNOWN' : (level || 'UNKNOWN');
    $('kpi-level').className = `kpi-value${missingLevel ? ' is-unknown' : ''}`;
    $('kpi-level-note').textContent = missingLevel ? 'ausência ≠ rio baixo' : snaps.length === 1 ? `${liveSourceText(snaps[0])} · ${ageLabel(snaps[0].observedAge)}` : 'duas estações de referência · não é média da bacia';
    $('kpi-rain').textContent = missingRain ? 'UNKNOWN' : (rain || 'UNKNOWN');
    $('kpi-rain').className = `kpi-value${missingRain ? ' is-unknown' : ''}`;
    $('kpi-rain-note').textContent = `horizonte +${hours} h · fonte principal de cada estação`;
    $('kpi-risk').textContent = missingRisk ? 'SEM VALOR ATUAL' : (risk || 'SEM VALOR ATUAL');
    $('kpi-risk').className = `kpi-value${missingRisk ? ' is-unknown' : ''}`;
    $('kpi-risk-note').textContent = snaps.some((s) => s.risk == null && s.archivedRisk != null)
      ? 'probabilidade experimental indisponível; resultado arquivado ocultado da leitura atual'
      : missingRisk
        ? 'nenhuma probabilidade experimental utilizável nesta rodada'
        : 'estimativa experimental; não calibrada; sem VAI/NÃO VAI';
    $('kpi-freshness').textContent = worst.label;
    $('kpi-freshness').className = `kpi-value ${worst.className}${worst.className === 'unknown' ? ' is-unknown' : ''}`;
    $('kpi-freshness-note').textContent = `${qualities.map((q, i) => `${stations[keys[i]].label}: ${q.label.toLowerCase()}`).join(' · ')}`;
  }

  function renderStationComparison() {
    const html = Object.keys(stations).map((key) => {
      const s = stationSnapshot(key, state.horizon); const rain = displayRain(s); const q = qualityFor(s);
      const coverage = s.coverage == null ? 'cobertura não informada' : `${fmt(s.coverage, 0)}/${state.horizon} h de cobertura`;
      const levelValue = s.level == null ? 'Sem dado' : `${fmt(s.level, 0)} cm`;
      const rainValue = rain.value == null ? 'Sem dado' : `${fmt(rain.value, 2)} mm`;
      const riskValue = s.riskUsable && s.risk != null ? pct(s.risk) : 'Sem valor atual';
      const riskNote = s.riskUsable && s.risk != null
        ? 'estimativa experimental de cruzar a cota'
        : s.archivedRisk != null
          ? 'resultado arquivado ocultado; não usar como leitura atual'
          : 'probabilidade experimental indisponível nesta rodada';
      return `<article class="station-card ${state.station === key ? 'selected' : ''}">
        <div class="station-card-head"><div><h3>${esc(s.station.label)}</h3><span class="station-code">ANA/SGB ${esc(s.station.code)} · cota ${fmt(s.station.threshold / 100, 2)} m</span></div><span class="station-decision ${scoreStateClass(s)}">${esc(scoreStateLabel(s))}</span></div>
        <div class="station-card-main"><div class="station-mini ${s.level == null ? 'is-unavailable' : ''}"><strong>${levelValue}</strong><span>nível observado · ${ageLabel(s.observedAge)}</span></div><div class="station-mini ${rain.value == null ? 'is-unavailable' : ''}"><strong>${rainValue}</strong><span>${esc(rain.label)} · +${state.horizon} h</span></div><div class="station-mini ${s.riskUsable && s.risk != null ? '' : 'is-unavailable'}"><strong>${riskValue}</strong><span>${esc(riskNote)}</span></div></div>
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
  function parseSimpleCsv(text) {
    const lines = String(text || '').trim().split(/\r?\n/).filter(Boolean);
    if (!lines.length) return null;
    const headers = lines[0].split(',').map((x) => x.trim());
    const rows = lines.slice(1).map((line) => line.split(','));
    const index = Object.fromEntries(headers.map((h, i) => [h, i]));
    return { headers, rows, index };
  }

  function rainPhaseRows(dataset, mode, hours) {
    if (!dataset || !Array.isArray(dataset.rows)) return [];
    const phaseIndex = dataset.index.phase;
    if (phaseIndex == null) return [];
    const all = dataset.rows.filter((row) => {
      const phase = String(row[phaseIndex] || '');
      return mode === 'observed' ? phase === 'observed' : /ecmwf_ifs/i.test(phase);
    });
    const n = Math.max(1, Number(hours) || 1);
    return mode === 'observed' ? all.slice(-n) : all.slice(0, n);
  }

  function rainComponentAccumulation(mode, hours) {
    const dataset = state.rainSpatial.components;
    const rain = rainSummarySnapshot();
    if (!dataset || !rain) return null;
    const rows = rainPhaseRows(dataset, mode, hours);
    if (rows.length < Number(hours)) return null;
    const areas = rain.component_values || {};
    const ids = dataset.headers.filter((h) => /^BRANCH_|^CORE_INC_/.test(h));
    if (!ids.length) return null;
    let weighted = 0, areaTotal = 0;
    for (const id of ids) {
      const col = dataset.index[id];
      const area = num(areas[id] && areas[id].area);
      if (col == null || area == null || area <= 0) return null;
      let sum = 0;
      for (const row of rows) {
        const raw = row[col];
        if (raw == null || String(raw).trim() === '') return null;
        const v = num(raw);
        if (v == null) return null;
        sum += v;
      }
      weighted += sum * area;
      areaTotal += area;
    }
    return areaTotal > 0 ? weighted / areaTotal : null;
  }

  function rainAccumulationBoard() {
    const hoursList = [1, 3, 6, 12, 24, 48, 72, 120];
    if (!state.rainSpatial.components) {
      return '<div class="rain-accumulation-board is-loading"><div class="rain-board-head"><div><span class="now-eyebrow">Acumulados da bacia</span><h3>1 a 120 horas</h3></div><span>carregando forcing espacial…</span></div></div>';
    }
    return '<div class="rain-accumulation-board"><div class="rain-board-head"><div><span class="now-eyebrow">Acumulados da bacia</span><h3>Observado × ECMWF/IFS</h3></div><span>média ponderada pela área dos 11 componentes hidrológicos</span></div><div class="rain-accumulation-grid">' +
      hoursList.map((h) => {
        const obs = rainComponentAccumulation('observed', h);
        const fc = rainComponentAccumulation('forecast', h);
        return '<article><strong>' + h + ' h</strong><div><span>OBS</span><b>' + (obs == null ? '—' : fmt(obs, 1) + ' mm') + '</b></div><div><span>IFS</span><b>' + (fc == null ? '—' : fmt(fc, 1) + ' mm') + '</b></div></article>';
      }).join('') +
    '</div><p>OBS usa as últimas horas disponíveis antes da transição para previsão; IFS usa as primeiras horas futuras do forcing. Janela incompleta permanece “—”.</p></div>';
  }

  function rainGridAccumulation(mode, hours) {
    const dataset = state.rainSpatial.grid;
    if (!dataset) return null;
    const rows = rainPhaseRows(dataset, mode, hours);
    if (rows.length < Number(hours)) return null;
    const cellIds = dataset.headers.filter((h) => /^G040_R\d{2}_C\d{2}$/.test(h));
    const values = [];
    for (const id of cellIds) {
      const col = dataset.index[id];
      let sum = 0, valid = true;
      for (const row of rows) {
        const raw = row[col];
        if (raw == null || String(raw).trim() === '') { valid = false; break; }
        const v = num(raw);
        if (v == null) { valid = false; break; }
        sum += v;
      }
      const match = id.match(/^G040_R(\d{2})_C(\d{2})$/);
      if (!match) continue;
      values.push({ id, row: Number(match[1]), col: Number(match[2]), mm: valid ? sum : null });
    }
    const timeIndex = dataset.index.time_utc;
    const times = rows.map((row) => row[timeIndex]).filter(Boolean);
    return { values, rows: rows.length, start: times[0] || null, end: times[times.length - 1] || null };
  }

  function rainMapFill(value, maxValue) {
    const v = num(value);
    if (v == null) return 'url(#rain-missing)';
    if (maxValue <= 0) return 'hsl(205 25% 96%)';
    const ratio = Math.max(0, Math.min(1, v / maxValue));
    const light = 96 - ratio * 58;
    const sat = 36 + ratio * 42;
    return 'hsl(205 ' + sat.toFixed(0) + '% ' + light.toFixed(0) + '%)';
  }

  function renderRainSpatialMap() {
    const host = $('rain-spatial-map');
    const status = $('rain-spatial-status');
    const summary = $('rain-spatial-summary');
    if (!host) return;
    if (state.rainSpatial.loading) {
      host.innerHTML = '<div class="loading-block">Carregando a grade de 600 células…</div>';
      if (status) status.textContent = 'carregando forcing espacial…';
      if (summary) summary.innerHTML = '';
      return;
    }
    if (state.rainSpatial.error || !state.rainSpatial.grid) {
      host.innerHTML = '<div class="empty-block">Grade espacial indisponível nesta publicação.</div>';
      if (status) status.textContent = state.rainSpatial.error || 'sem grade publicada';
      if (summary) summary.innerHTML = '';
      return;
    }
    const data = rainGridAccumulation(state.rainMapMode, state.rainMapHours);
    const rings = geoRings(state.basinGeometry);
    if (!data || !rings.length) {
      host.innerHTML = '<div class="empty-block">Não há janela completa para este acumulado.</div>';
      if (status) status.textContent = 'janela incompleta · ausência não vira zero';
      if (summary) summary.innerHTML = '';
      return;
    }

    const gridWest = -52.8, gridEast = -49.8, gridSouth = -30.0, gridNorth = -28.0;
    const cosLat = Math.cos(((gridSouth + gridNorth) / 2) * Math.PI / 180);
    const minX = gridWest * cosLat, maxX = gridEast * cosLat;
    const width = 760, height = 470, pad = 24;
    const project = (lon, lat) => [
      pad + ((lon * cosLat - minX) / Math.max(.000001, maxX - minX)) * (width - pad * 2),
      pad + ((gridNorth - lat) / Math.max(.000001, gridNorth - gridSouth)) * (height - pad * 2)
    ];
    const ringPath = rings.map((ring) => {
      const step = Math.max(1, Math.ceil(ring.length / 1400));
      const pts = ring.filter((_, i) => i % step === 0 || i === ring.length - 1).map((p) => project(Number(p[0]), Number(p[1])));
      return pts.length ? 'M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('L') + 'Z' : '';
    }).filter(Boolean).join('');

    const valid = data.values.map((x) => x.mm).filter((x) => x != null);
    const maxValue = valid.length ? Math.max(...valid) : 0;
    const sorted = valid.slice().sort((a, b) => a - b);
    const p90 = sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * .9))] : null;
    const cellRects = data.values.map((cell) => {
      const west = -52.8 + cell.col * .1;
      const east = west + .1;
      const south = -30 + cell.row * .1;
      const north = south + .1;
      const nw = project(west, north);
      const se = project(east, south);
      const x = Math.min(nw[0], se[0]), y = Math.min(nw[1], se[1]);
      const w = Math.abs(se[0] - nw[0]), h = Math.abs(se[1] - nw[1]);
      const fill = rainMapFill(cell.mm, maxValue);
      const title = cell.id + ' · ' + (cell.mm == null ? 'sem dado' : fmt(cell.mm, 1) + ' mm');
      return '<rect x="' + x.toFixed(2) + '" y="' + y.toFixed(2) + '" width="' + w.toFixed(2) + '" height="' + h.toFixed(2) + '" fill="' + fill + '"><title>' + esc(title) + '</title></rect>';
    }).join('');

    const label = state.rainMapMode === 'observed' ? 'Observado' : 'ECMWF/IFS';
    const timeText = data.start && data.end ? when(data.start) + ' → ' + when(data.end) + ' BRT' : 'horário não publicado';
    host.innerHTML =
      '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Mapa de chuva acumulada da G040, ' + esc(label) + ', ' + state.rainMapHours + ' horas">' +
        '<defs><pattern id="rain-missing" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="#eef1ef"></rect><line x1="0" y1="0" x2="0" y2="8" stroke="#c6cfca" stroke-width="2"></line></pattern><linearGradient id="rain-scale" x1="0%" x2="100%"><stop offset="0%" stop-color="hsl(205 25% 96%)"></stop><stop offset="100%" stop-color="hsl(205 78% 38%)"></stop></linearGradient></defs>' +
        '<g class="rain-grid-field">' + cellRects + '</g>' +
        '<path class="rain-basin-outline" d="' + ringPath + '" fill="rgba(255,255,255,.04)" fill-rule="evenodd"></path>' +
        '<text class="rain-domain-note" x="' + pad + '" y="' + (pad - 7) + '">grade bacia + buffer · contorno = G040</text>' +
        '<g class="rain-map-scale"><rect x="' + (width - 212) + '" y="' + (height - 26) + '" width="150" height="9" rx="4.5" fill="url(#rain-scale)"></rect><text x="' + (width - 218) + '" y="' + (height - 17) + '" text-anchor="end">0</text><text x="' + (width - 56) + '" y="' + (height - 17) + '">' + esc(fmt(maxValue, 0)) + ' mm</text></g>' +
      '</svg>';

    if (status) status.textContent = label + ' · ' + state.rainMapHours + ' h · grade bacia+buffer · ' + timeText;
    if (summary) summary.innerHTML =
      '<div><span>Máximo de célula</span><strong>' + (valid.length ? fmt(maxValue, 1) + ' mm' : '—') + '</strong></div>' +
      '<div><span>P90 das células</span><strong>' + (p90 == null ? '—' : fmt(p90, 1) + ' mm') + '</strong></div>' +
      '<div><span>Células com valor</span><strong>' + fmt(valid.length, 0) + '<small>/600</small></strong></div>' +
      '<div><span>Janela</span><strong>' + state.rainMapHours + ' h</strong></div>';
  }

  async function loadText(url) {
    try {
      const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}cb=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) return null;
      return await response.text();
    } catch (_) { return null; }
  }

  async function loadRainSpatial() {
    if (state.rainSpatial.loading) return;
    state.rainSpatial.loading = true;
    state.rainSpatial.error = null;
    renderRainSpatialMap();
    try {
      const [gridText, componentText] = await Promise.all([loadText(rainGridUrl), loadText(rainComponentsUrl)]);
      const grid = parseSimpleCsv(gridText);
      const components = parseSimpleCsv(componentText);
      if (!grid || !components) throw new Error('forcing espacial não publicado');
      state.rainSpatial.grid = grid;
      state.rainSpatial.components = components;
    } catch (err) {
      state.rainSpatial.error = err && err.message ? err.message : 'falha ao carregar forcing espacial';
    } finally {
      state.rainSpatial.loading = false;
      renderRainBasinOverview();
      renderRainSpatialMap();
    }
  }

  function rainComponentLabel(componentId) {
    const raw = String(componentId || '');
    const stationsByCode = new Map(networkStations().map((row) => [String(row.code || ''), row.name || row.code || 'Estação']));
    if (raw.startsWith('BRANCH_')) {
      const code = raw.replace('BRANCH_', '');
      return stationsByCode.get(code) ? `Afluente · ${stationsByCode.get(code)}` : `Afluente · ${code}`;
    }
    const match = raw.match(/^CORE_INC_(\d+)_(\d+)$/);
    if (match) {
      const from = stationsByCode.get(match[1]) || match[1];
      const to = stationsByCode.get(match[2]) || match[2];
      return `Trecho principal · ${from} → ${to}`;
    }
    return raw || 'Componente hidrológico';
  }

  function rainSummarySnapshot() {
    const fp = state.rainSummary && state.rainSummary.live_fingerprint;
    return fp && fp.rain && typeof fp.rain === 'object' ? fp.rain : null;
  }

  function rainMetricCard(label, value, note, kind = '') {
    const n = num(value);
    return '<article class="rain-metric-card ' + esc(kind) + '">' +
      '<span>' + esc(label) + '</span>' +
      '<strong>' + (n == null ? '—' : fmt(n, 1) + ' mm') + '</strong>' +
      '<small>' + esc(note) + '</small>' +
    '</article>';
  }

  function renderRainBasinOverview() {
    const host = $('rain-basin-overview');
    if (!host) return;
    const rain = rainSummarySnapshot();
    if (!rain) {
      host.innerHTML = '<div class="empty-block">O resumo integrado de chuva da G040 ainda não está disponível nesta publicação.</div>';
      return;
    }

    const freshness = rain.freshness || {};
    const stale = freshness.critical_stale === true;
    const observedAge = num(freshness.observed_rain_age_hours);
    const forcingAge = num(freshness.forcing_age_hours);
    const compactHorizon = state.horizon <= 24 ? 24 : state.horizon <= 48 ? 48 : 72;
    const compactKey = 'fc' + compactHorizon;
    const components = Object.entries(rain.component_values || {}).map(([id, row]) => ({
      id,
      label: rainComponentLabel(id),
      area: num(row && row.area),
      obs24: num(row && row.obs24),
      obs72: num(row && row.obs72),
      fc24: num(row && row.fc24),
      fc48: num(row && row.fc48),
      fc72: num(row && row.fc72),
      selected: num(row && row[compactKey])
    })).sort((a, b) => (b.selected ?? -1) - (a.selected ?? -1));

    const maxSelected = Math.max(1, ...components.map((row) => row.selected == null ? 0 : row.selected));
    const coverage = networkVariableCoverage();
    const sourceCounts = state.networkStatus && state.networkStatus.source_counts && typeof state.networkStatus.source_counts === 'object'
      ? state.networkStatus.source_counts : {};
    const sourceOrder = ['ANA/HidroWeb', 'SGB/SACE', 'CEMADEN', 'INMET'];
    const sourceHtml = sourceOrder.filter((key) => num(sourceCounts[key]) != null).map((key) =>
      '<span><b>' + esc(key) + '</b>' + fmt(sourceCounts[key], 0) + '</span>'
    ).join('');

    const staleText = stale
      ? 'ATENÇÃO: o forcing integrado está defasado' + (observedAge != null ? ' · última chuva observada há ' + fmt(observedAge, 1) + ' h' : '') + (forcingAge != null ? ' · produto há ' + fmt(forcingAge, 1) + ' h' : '') + '.'
      : 'Forcing integrado sem bloqueio crítico de frescor nesta publicação.';
    const cycleText = freshness.exact_ecmwf_cycle_id_available === false
      ? 'O endpoint usado não expõe o identificador exato do ciclo ECMWF; horário de coleta não é relabelado como ciclo.'
      : 'Ciclo meteorológico com proveniência publicada.';

    const barHtml = components.length ? components.map((row) => {
      const width = row.selected == null ? 0 : Math.max(0, Math.min(100, row.selected / maxSelected * 100));
      return '<div class="rain-component-row">' +
        '<div class="rain-component-head"><span><strong>' + esc(row.label) + '</strong><small>' + (row.area == null ? 'área não publicada' : fmt(row.area, 0) + ' km²') + '</small></span><b>' + (row.selected == null ? '—' : fmt(row.selected, 1) + ' mm') + '</b></div>' +
        '<div class="rain-component-track" aria-hidden="true"><i style="width:' + width.toFixed(1) + '%"></i></div>' +
      '</div>';
    }).join('') : '<div class="empty-block">Sem componentes espaciais no resumo integrado.</div>';

    const tableHtml = components.length ? '<div class="table-scroll"><table class="rain-component-table"><thead><tr><th>Componente</th><th>Área</th><th>Obs. 24 h</th><th>Obs. 72 h</th><th>Prev. 24 h</th><th>Prev. 48 h</th><th>Prev. 72 h</th></tr></thead><tbody>' +
      components.map((row) => '<tr><td><strong>' + esc(row.label) + '</strong><small>' + esc(row.id) + '</small></td><td class="num">' + (row.area == null ? '—' : fmt(row.area, 0) + ' km²') + '</td><td class="num">' + (row.obs24 == null ? '—' : fmt(row.obs24, 1) + ' mm') + '</td><td class="num">' + (row.obs72 == null ? '—' : fmt(row.obs72, 1) + ' mm') + '</td><td class="num">' + (row.fc24 == null ? '—' : fmt(row.fc24, 1) + ' mm') + '</td><td class="num">' + (row.fc48 == null ? '—' : fmt(row.fc48, 1) + ' mm') + '</td><td class="num">' + (row.fc72 == null ? '—' : fmt(row.fc72, 1) + ' mm') + '</td></tr>').join('') +
      '</tbody></table></div>' : '';

    const horizonNote = state.horizon > 72
      ? 'O seletor geral está em +' + state.horizon + ' h; o resumo espacial compacto da G040 publicado aqui vai até +72 h. O campo bruto ECMWF/IFS da arquitetura da bacia é mantido separadamente.'
      : 'Barras espaciais ordenadas pela previsão +' + compactHorizon + ' h.';

    host.innerHTML =
      '<div class="rain-freshness ' + (stale ? 'is-stale' : 'is-current') + '"><div><span class="now-eyebrow">Frescor e proveniência</span><strong>' + esc(staleText) + '</strong></div><small>' + esc(cycleText) + '</small></div>' +
      '<div class="rain-metric-grid">' +
        rainMetricCard('Observado · 24 h', rain.observed_24h_basin_mm, 'chuva espacial acumulada na área modelada', 'observed') +
        rainMetricCard('Observado · 72 h', rain.observed_72h_basin_mm, 'memória antecedente da bacia', 'observed') +
        rainMetricCard('Previsto · 24 h', rain.forecast_24h_basin_mm, 'ECMWF/IFS espacial', 'forecast') +
        rainMetricCard('Previsto · 48 h', rain.forecast_48h_basin_mm, 'ECMWF/IFS espacial', 'forecast') +
        rainMetricCard('Previsto · 72 h', rain.forecast_72h_basin_mm, 'ECMWF/IFS espacial', 'forecast') +
      '</div>' +
      rainAccumulationBoard() +
      '<div class="rain-detail-grid">' +
        '<article class="rain-network-card"><div class="rain-card-head"><div><span class="now-eyebrow">Rede observada</span><h3>Cobertura de chuva publicada</h3></div><span>' + fmt(coverage.total, 0) + ' estações no snapshot</span></div>' +
          '<div class="rain-network-stats"><div><span>Série horária</span><strong>' + fmt(coverage.hourlyRain, 0) + '<small>/' + fmt(coverage.total, 0) + '</small></strong></div><div><span>CEMADEN 24 h</span><strong>' + fmt(coverage.cemaden24, 0) + '<small>/' + fmt(coverage.total, 0) + '</small></strong></div></div>' +
          (sourceHtml ? '<div class="rain-source-counts">' + sourceHtml + '</div>' : '') +
          '<p>O painel preserva chuva horária observada e acumulado CEMADEN 24 h como produtos diferentes; ausência de série não vira zero.</p>' +
        '</article>' +
        '<article class="rain-components-card"><div class="rain-card-head"><div><span class="now-eyebrow">Distribuição espacial</span><h3>11 componentes hidrológicos da G040</h3></div><span>' + esc(horizonNote) + '</span></div><div class="rain-component-list">' + barHtml + '</div></article>' +
      '</div>' +
      '<details class="rain-table-fold"><summary><span>Tabela completa dos 11 componentes</span><small>observado 24/72 h + previsto 24/48/72 h</small></summary>' + tableHtml + '</details>' +
      '<div class="rain-method-strip"><p><strong>Como a chuva da bacia é tratada:</strong> os postos válidos de cada hora formam um campo espacial; o forcing preserva os componentes hidrológicos e acumula no tempo. Milímetros de estações diferentes não são simplesmente somados como se fossem uma única lâmina sobre toda a bacia.</p><div><a href="assets/data/hec_hms_g040_full_basin/g040_adaptive_scenario_latest.json">resumo integrado →</a><a href="assets/data/hec_hms_g040_full_basin/whole_basin_rain_forcing_latest.json">forcing observado + previsto →</a><a href="assets/data/hec_hms_g040_full_basin/whole_basin_ifs_forecast_latest.json">campo ECMWF/IFS →</a></div></div>';
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
  function rainSources(key, snap) {
    if (key === 'santa') {
      return [
        { label: 'Cabeceiras · média', value: snap.basinMean, note: 'média das células monitoradas a montante', color: '#c47a10' },
        { label: 'Cabeceiras · máximo', value: snap.basinMax, note: 'maior célula monitorada a montante', color: '#d59a33' },
        { label: 'Ponto da estação', value: snap.pointRain, note: 'célula mais próxima de Santa Tereza', color: '#e2b85c' }
      ];
    }
    return [
      { label: 'Ponto Muçum · IFS', value: snap.directRain, note: 'previsão direta para a estação', color: '#c47a10' },
      { label: 'Célula espacial · IFS', value: snap.ifsProxyRain, note: 'proxy espacial, não medição local', color: '#d59a33' },
      { label: 'Célula · GEFS', value: snap.gefsProxyRain, note: 'proxy de ensemble usado na pesquisa', color: '#e2b85c' }
    ];
  }
  function modelBar(entry, scale, isMax) {
    const value = num(entry.value);
    const width = value == null ? 0 : Math.max(0, Math.min(100, value / scale * 100));
    const label = value == null ? `${entry.label}: sem valor publicado` : `${entry.label}: ${fmt(value, 1)} milímetros`;
    return `<div class="model-bar-row${isMax ? ' is-max' : ''}" role="listitem" aria-label="${esc(label)}"><div class="model-bar-label"><strong>${esc(entry.label)}${isMax ? '<em>maior valor</em>' : ''}</strong><span>${value == null ? '—' : `${fmt(value, 1)} mm`}</span></div><div class="model-bar-track" aria-hidden="true"><i style="width:${width.toFixed(1)}%;--bar-color:${entry.color}"></i></div><small>${esc(entry.note)}</small></div>`;
  }
  function modelComparisonSummary(sources, pointValue) {
    if (!sources.length) return '<div class="model-station-summary is-empty">Nenhuma fonte de chuva foi publicada para este horizonte.</div>';
    const ranked = sources.slice().sort((a, b) => Number(b.value) - Number(a.value));
    const max = ranked[0];
    const point = num(pointValue);
    const delta = point == null ? null : Number(max.value) - point;
    return `<div class="model-station-summary"><div><span>Maior valor comparado</span><strong>${fmt(max.value, 1)} mm</strong><small>${esc(max.label)}</small></div><div><span>Diferença até o ponto</span><strong>${delta == null ? '—' : `${delta >= 0 ? '+' : ''}${fmt(delta, 1)} mm`}</strong><small>maior valor − chuva no ponto</small></div></div>`;
  }
  function modelThresholdVisual(key, snap) {
    const live = liveRowsFor(key).filter((row) => row.available && num(row.level_forecast_cm) != null);
    const liveMax = live.length ? Math.max(...live.map((row) => Number(row.level_forecast_cm))) : null;
    const current = num(snap.level);
    const threshold = num(snap.station.threshold);
    const reference = [current, liveMax].filter((value) => value != null);
    const peak = reference.length ? Math.max(...reference) : null;
    const hasReading = peak != null && threshold != null;
    const ratio = hasReading && threshold ? Math.max(0, Math.min(100, peak / threshold * 100)) : 0;
    const markerRatio = Math.max(4, Math.min(96, ratio));
    const status = !hasReading
      ? 'sem leitura de cota utilizável'
      : peak < threshold ? 'nenhum cenário curto cruza a cota da pesquisa' : 'há cenário curto acima da cota da pesquisa';
    const statusClass = !hasReading ? '' : peak >= threshold ? 'is-alert' : 'is-ok';
    const statusLabel = !hasReading ? 'sem leitura' : peak >= threshold ? 'acima' : 'abaixo';

    if (!hasReading) {
      return `<article class="model-threshold-card is-unavailable"><div class="model-subhead"><div><span class="model-eyebrow">Nível × cota</span><h3>O rio se aproxima da cota?</h3></div><span class="model-status-pill">sem leitura</span></div><div class="model-availability"><strong>Sem comparação atual</strong><span>Nível observado ou cota de pesquisa indisponível nesta rodada.</span></div><p class="model-takeaway">A previsão curta é uma altura do rio; não é uma probabilidade de inundação.</p></article>`;
    }

    return `<article class="model-threshold-card"><div class="model-subhead"><div><span class="model-eyebrow">Nível × cota</span><h3>O rio se aproxima da cota?</h3></div><span class="model-status-pill ${statusClass}">${statusLabel}</span></div><div class="threshold-stats"><div><span>Agora</span><strong>${current == null ? '—' : `${fmt(current, 0)} cm`}</strong></div><div><span>Máx. curto</span><strong>${liveMax == null ? '—' : `${fmt(liveMax, 0)} cm`}</strong></div><div><span>Cota pesquisa</span><strong>${fmt(threshold, 0)} cm</strong></div></div><div class="threshold-scale" aria-label="Maior nível observado ou previsto em relação à cota de pesquisa"><i style="width:${ratio.toFixed(1)}%"></i><b style="left:${markerRatio.toFixed(1)}%">${fmt(peak, 0)} cm</b></div><p class="model-takeaway">${esc(status)}. A previsão curta é uma altura do rio; não é uma probabilidade de inundação.</p></article>`;
  }
  function modelRiskVisual(snap) {
    const usable = snap.riskUsable && snap.risk != null;
    if (!usable) {
      const stateLabel = researchStateLabel(snap.riskState);
      const archiveNote = snap.archivedRisk == null ? '' : '<span class="model-archive-note">Existe resultado arquivado, mas ele foi ocultado da leitura atual por estar desatualizado.</span>';
      return `<article class="model-risk-card is-stale"><div class="model-subhead"><div><span class="model-eyebrow">Risco de pesquisa</span><h3>Probabilidade de cruzar a cota</h3></div><span class="model-status-pill is-stale">indisponível</span></div><div class="model-availability"><strong>Sem valor atual</strong><span>rodada atrasada · ${esc(stateLabel)}</span></div><p>Não há probabilidade atual utilizável. Resultado antigo não é reutilizado como se fosse vigente.</p>${archiveNote}<span class="model-source">PROBABILIDADE · experimental · ${esc(snap.station.label)}</span></article>`;
    }
    return `<article class="model-risk-card"><div class="model-subhead"><div><span class="model-eyebrow">Risco de pesquisa</span><h3>Probabilidade de cruzar a cota</h3></div><span class="model-status-pill is-ok">utilizável</span></div><div class="model-risk-value">${pct(snap.risk)}<span>estimativa experimental</span></div><p>Estimativa experimental de cruzamento; não é alerta oficial.</p><span class="model-source">PROBABILIDADE · experimental · ${esc(snap.station.label)}</span></article>`;
  }
  function modelSoilVisual(snap) {
    const soil = num(snap.soil);
    if (soil == null) {
      return `<article class="model-soil-card is-unavailable"><div class="model-subhead"><div><span class="model-eyebrow">Umidade</span><h3>Solo modelado</h3></div><span class="model-status-pill">indisponível</span></div><div class="model-availability"><strong>Sem valor modelado</strong><span>Nenhuma estimativa válida de umidade nesta rodada.</span></div><p>Ausência de valor não é interpretada como solo seco.</p></article>`;
    }
    return `<article class="model-soil-card"><div class="model-subhead"><div><span class="model-eyebrow">Umidade</span><h3>Solo modelado</h3></div><span class="model-status-pill is-proxy">proxy</span></div><div class="model-soil-value">${fmt(soil, 2)}<span>m³/m³</span></div><div class="soil-meter" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, soil / .6 * 100))}%"></i></div><p>Memória hídrica modelada. Não é sensor local de saturação.</p><span class="model-source">SOLO · modelado · proxy</span></article>`;
  }
  function renderModels() {
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    const prepared = keys.map((key) => {
      const snap = stationSnapshot(key, state.horizon);
      const sources = rainSources(key, snap).filter((entry) => num(entry.value) != null);
      return { key, snap, sources };
    });
    const allValues = prepared.flatMap((item) => item.sources.map((entry) => Number(entry.value)));
    const sharedMaxValue = allValues.length ? Math.max(...allValues) : 0;
    const sharedScale = Math.max(10, Math.ceil((sharedMaxValue * 1.15) / 10) * 10);
    const sections = prepared.map(({ key, snap, sources }) => {
      const rainRows = sources.length ? sources.map((entry) => modelBar(entry, sharedScale, Number(entry.value) === Math.max(...sources.map((item) => Number(item.value))))).join('') : '<div class="empty-block">Sem chuva publicada neste horizonte.</div>';
      const stationLabel = state.station === 'basin' ? `<span class="model-station-kicker">${esc(snap.station.label)}</span>` : '';
      const pointValue = key === 'santa' ? snap.pointRain : snap.directRain;
      return `<section class="model-station-view"><div class="model-station-heading">${stationLabel}<h3>Chuva prevista no horizonte +${state.horizon} h</h3><span>escala comum entre estações · 0–${fmt(sharedScale, 0)} mm</span></div>${modelComparisonSummary(sources, pointValue)}<div class="model-station-layout"><article class="model-rain-chart"><div class="model-subhead"><div><span class="model-eyebrow">Comparação na mesma unidade</span><h3>Onde a chuva aparece?</h3></div><span class="model-unit">mm acumulados</span></div><div class="model-bars" role="list">${rainRows}</div><p class="model-chart-note">As barras comparam chuva prevista. Proxy espacial não é medição local e não equivale a uma média hidrológica da bacia.</p></article><div class="model-status-stack">${modelThresholdVisual(key, snap)}${modelRiskVisual(snap)}${modelSoilVisual(snap)}</div></div></section>`;
    }).join('');
    $('model-cards').innerHTML = sections || '<div class="empty-block">Sem modelos publicados para este recorte.</div>';
    $('model-panel-note').textContent = `Barras de chuva em escala única · nível e probabilidade em leituras separadas · horizonte +${state.horizon} h`;
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
    const summaryByStation = state.station === 'basin'
      ? 'Santa Tereza + Muçum'
      : stations[state.station] ? stations[state.station].label : 'recorte selecionado';
    const cardCount = state.station === 'santa'
      ? ((stationFeed('santa').pattern || {}).summary || {}).model_card_event_count
      : null;
    $('timeline-note').textContent = events.length
      ? `${events.length} eventos no recorte · ${summaryByStation}${cardCount ? ` · ${cardCount} no cartão de validação` : ''}`
      : 'Sem eventos publicados';

    const statusLabel = (value) => {
      const raw = String(value || '').trim();
      if (/requires ANA\/SACE review/i.test(raw)) return 'requer revisão ANA/SACE';
      if (/SACE crossing confirmed for research only/i.test(raw)) return 'cruzamento SACE confirmado · pesquisa';
      if (/pico acima da cota de pesquisa/i.test(raw)) return 'pico acima da cota de pesquisa';
      return raw || 'status não informado';
    };
    const soilLabel = (value) => {
      const raw = String(value || '');
      if (/saturation not demonstrated/i.test(raw)) return 'proxy de umidade; saturação não demonstrada';
      if (/likely very wet/i.test(raw)) return 'proxy indica condição antecedente muito úmida';
      if (/strong antecedent memory/i.test(raw)) return 'proxy indica forte memória antecedente';
      if (/recent rain signal/i.test(raw)) return 'sinal recente de chuva; saturação desconhecida';
      return raw;
    };
    const sourceLabel = (e) => {
      if (e.rain_source_kind === 'local_station') return `chuva local auditada · ANA ${e.rain_station || ''}`;
      if (e.rain_source_kind === 'downstream_proxy') return `proxy jusante · Muçum ${e.rain_station || '86510000'}`;
      if (e.rain_source_kind === 'research_antecedent') return 'chuva antecedente · pacote de pesquisa';
      return 'chuva antecedente não auditada neste feed';
    };
    const safeAssetPath = (value) => {
      const raw = String(value || '').trim();
      return /^(?:assets|pesquisas|docs)\/[A-Za-z0-9_.\/-]+$/.test(raw) ? raw : '';
    };
    const best = (rows, key) => rows.length
      ? rows.reduce((a, b) => Number(b[key]) > Number(a[key]) ? b : a)
      : null;

    const withPeak = events.filter((e) => num(e.peak_cm) != null);
    const withRain24 = events.filter((e) => num(e.rain_24h_mm) != null);
    const withRain72 = events.filter((e) => num(e.rain_72h_mm) != null);
    const withRise = events.filter((e) => num(e.max_hourly_rise_cm_h) != null);
    const withApi = events.filter((e) => num(e.api_72h_mm) != null);
    const peakEvent = best(withPeak, 'peak_cm');
    const rain24Event = best(withRain24, 'rain_24h_mm');
    const rain72Event = best(withRain72, 'rain_72h_mm');
    const riseEvent = best(withRise, 'max_hourly_rise_cm_h');
    const apiEvent = best(withApi, 'api_72h_mm');

    const summaryHost = $('event-summary');
    if (summaryHost) {
      const summaryItems = [
        peakEvent ? ['Maior pico', `${fmt(peakEvent.peak_cm, 0)} cm`, `${peakEvent.sourceLabel} · ${shortDate(peakEvent.date)}`] : null,
        rain24Event ? ['Maior chuva antecedente 24 h', `${fmt(rain24Event.rain_24h_mm, 1)} mm`, `${rain24Event.sourceLabel} · ${shortDate(rain24Event.date)}`] : null,
        rain72Event ? ['Maior chuva antecedente 72 h', `${fmt(rain72Event.rain_72h_mm, 1)} mm`, `${rain72Event.sourceLabel} · ${shortDate(rain72Event.date)}`] : null,
        riseEvent ? ['Subida mais rápida', `${fmt(riseEvent.max_hourly_rise_cm_h, 0)} cm/h`, `${riseEvent.sourceLabel} · ${shortDate(riseEvent.date)}`] : null
      ].filter(Boolean);
      summaryHost.innerHTML = summaryItems.length
        ? summaryItems.map((item) => `<div class="event-summary-item"><span>${esc(item[0])}</span><strong>${esc(item[1])}</strong><small>${esc(item[2])}</small></div>`).join('')
        : '';
    }

    const insightHost = $('event-insight');
    if (insightHost) {
      const insights = [];
      if (peakEvent) insights.push(`O maior pico deste recorte é ${peakEvent.sourceLabel}, em ${shortDate(peakEvent.date)}: ${fmt(peakEvent.peak_cm, 0)} cm.`);
      if (rain72Event) insights.push(`O maior acumulado antecedente de 72 h publicado é ${fmt(rain72Event.rain_72h_mm, 1)} mm em ${rain72Event.sourceLabel} (${shortDate(rain72Event.date)}).`);
      if (riseEvent) insights.push(`A subida horária mais rápida disponível é ${fmt(riseEvent.max_hourly_rise_cm_h, 0)} cm/h em ${riseEvent.sourceLabel} (${shortDate(riseEvent.date)}).`);
      if (apiEvent) insights.push(`A maior memória antecedente API 72 h publicada é ${fmt(apiEvent.api_72h_mm, 1)} mm-eq. em ${apiEvent.sourceLabel} (${shortDate(apiEvent.date)}).`);
      const proxyCount = events.filter((e) => e.rain_source_kind === 'downstream_proxy').length;
      insightHost.innerHTML = insights.length
        ? `<div class="event-insight-head"><div><span class="now-eyebrow">Leitura comparativa</span><h3>O que diferencia esses eventos?</h3></div><span>${events.length} eventos · fontes preservadas</span></div><div class="event-insight-grid">${insights.slice(0, 4).map((item) => `<p>${esc(item)}</p>`).join('')}</div>${proxyCount ? `<p class="event-insight-warning">${proxyCount} evento(s) usa(m) proxy espacial de chuva; esses valores não são tratados como chuva local equivalente.</p>` : ''}`
        : '';
    }

    $('event-timeline').innerHTML = events.length ? events.map((e) => {
      const confirmed = /confirm|cota de pesquisa|acima da cota/i.test(String(e.status || ''));
      const metrics = [];
      const addMetric = (value, label, digits = 1, kind = '') => {
        if (num(value) != null) metrics.push({ value, label, digits, kind });
      };
      if (e.rain_source_kind === 'downstream_proxy') {
        addMetric(e.proxy_rain_24h_mm, 'proxy Muçum 24 h · mm', 1, 'proxy');
        addMetric(e.max_hourly_rise_cm_h, 'subida máx. · cm/h', 0, 'level');
        addMetric(e.total_rise_cm, 'elevação até pico · cm', 0, 'level');
      } else if (num(e.rain_24h_mm) != null) {
        addMetric(e.rain_24h_mm, 'chuva 24 h · mm', 1, 'rain');
        addMetric(e.rain_72h_mm, 'chuva 72 h · mm', 1, 'rain');
        if (num(e.api_72h_mm) != null) addMetric(e.api_72h_mm, 'API 72 h · mm-eq.', 1, 'memory');
        else if (num(e.max_hourly_rise_cm_h) != null) addMetric(e.max_hourly_rise_cm_h, 'subida máx. · cm/h', 0, 'level');
        else addMetric(e.rain_168h_mm, 'chuva 168 h · mm', 1, 'rain');
      } else {
        addMetric(e.max_hourly_rise_cm_h, 'subida máx. · cm/h', 0, 'level');
        addMetric(e.total_rise_cm, 'elevação até pico · cm', 0, 'level');
        addMetric(e.rna_peak_error_cm, 'erro no pico RNA · cm', 1, 'model');
        addMetric(e.model_count, 'modelos avaliados', 0, 'model');
      }
      const threshold = stations[e.sourceKey] ? num(stations[e.sourceKey].threshold) : null;
      const exceed = threshold != null && num(e.peak_cm) != null ? Number(e.peak_cm) - threshold : null;
      const scaleMax = threshold != null ? threshold * 1.55 : num(e.peak_cm);
      const peakWidth = scaleMax && num(e.peak_cm) != null ? Math.max(0, Math.min(100, Number(e.peak_cm) / scaleMax * 100)) : 0;
      const thresholdWidth = scaleMax && threshold != null ? Math.max(0, Math.min(100, threshold / scaleMax * 100)) : 0;
      const sourcePath = safeAssetPath(e.context_source || ((stationFeed(e.sourceKey).pattern || {}).sources || {}).events);
      const sourceLink = sourcePath ? `<a href="${esc(sourcePath)}">abrir fonte →</a>` : '';
      const replayBits = [];
      if (e.replay_role) replayBits.push(`replay: ${String(e.replay_role).toLocaleLowerCase('pt-BR')}`);
      if (num(e.rna_mae_cm) != null) replayBits.push(`MAE ${fmt(e.rna_mae_cm, 1)} cm`);
      if (num(e.rna_peak_error_cm) != null) replayBits.push(`erro pico ${fmt(e.rna_peak_error_cm, 1)} cm`);
      const contextual = e.rain_source_kind === 'downstream_proxy'
        ? `Chuva local de Santa Tereza indisponível neste evento. O acumulado de 24 h é um proxy jusante de Muçum${num(e.rain_coverage_pct) != null ? ` com ${fmt(e.rain_coverage_pct, 1)}% de cobertura` : ''}.`
        : e.rain_source_kind === 'local_station'
          ? `Chuva local auditada na estação ${e.rain_station || ''}${num(e.rain_coverage_pct) != null ? ` · cobertura ${fmt(e.rain_coverage_pct, 1)}% em 72 h` : ''}.`
          : e.rain_source_kind === 'research_antecedent'
            ? `${soilLabel(e.soil_status) || 'Condições antecedentes publicadas no pacote de pesquisa.'}`
            : 'Chuva antecedente auditada ainda não publicada; o cartão usa dinâmica do nível e replay, sem preencher a lacuna com zero.';
      return `<article class="event-card ${confirmed ? 'confirmed' : ''}">
        <div class="event-card-head"><span class="event-date">${esc(e.sourceLabel)} · ${esc(shortDate(e.date))}</span><span class="event-source-kind ${esc(e.rain_source_kind || 'unknown')}">${esc(sourceLabel(e))}</span></div>
        <h3>${esc(e.id || 'Evento catalogado')}</h3>
        <div class="event-peak">${fmt(e.peak_cm, 0)} <span>cm no pico observado</span></div>
        <div class="event-threshold"><div class="event-threshold-track"><i style="width:${peakWidth.toFixed(1)}%"></i><b style="left:${thresholdWidth.toFixed(1)}%"></b></div><span>${exceed == null ? 'cota não informada' : exceed >= 0 ? `+${fmt(exceed, 0)} cm acima da cota de pesquisa` : `${fmt(Math.abs(exceed), 0)} cm abaixo da cota`}</span></div>
        <span class="event-status">${esc(statusLabel(e.status))}</span>
        <div class="event-rain">${metrics.slice(0, 3).map((m) => `<div class="is-${esc(m.kind)}"><b>${fmt(m.value, m.digits)}</b><span>${esc(m.label)}</span></div>`).join('')}</div>
        <p class="event-context-note ${e.rain_source_kind === 'downstream_proxy' ? 'is-proxy' : ''}">${esc(contextual)}</p>
        ${replayBits.length || sourceLink ? `<div class="event-card-foot"><span>${esc(replayBits.join(' · '))}</span>${sourceLink}</div>` : ''}
      </article>`;
    }).join('') : '<div class="empty-block">Os eventos históricos ainda não estão disponíveis neste feed.</div>';

    const comparisonHost = $('event-comparison');
    if (comparisonHost) {
      const rainCell = (e, key, proxyKey = null) => {
        if (num(e[key]) != null) return `${fmt(e[key], 1)}`;
        if (proxyKey && num(e[proxyKey]) != null) return `${fmt(e[proxyKey], 1)}*`;
        return 'não auditada';
      };
      comparisonHost.innerHTML = events.length
        ? `<div class="event-comparison-head"><div><span class="now-eyebrow">Comparação direta</span><h3>Evento por evento</h3></div><span>* proxy espacial, não chuva local equivalente</span></div>
          <div class="table-scroll"><table class="event-comparison-table">
            <thead><tr><th>Local / data</th><th>Pico</th><th>Acima da cota</th><th>Chuva 24 h</th><th>Chuva 72 h</th><th>Chuva 168 h</th><th>API 72 h</th><th>Subida máx.</th><th>Replay</th></tr></thead>
            <tbody>${events.map((e) => {
              const threshold = stations[e.sourceKey] ? num(stations[e.sourceKey].threshold) : null;
              const exceed = threshold != null && num(e.peak_cm) != null ? Number(e.peak_cm) - threshold : null;
              const replay = e.replay_role ? `${e.replay_role}${num(e.rna_mae_cm) != null ? ` · MAE ${fmt(e.rna_mae_cm, 1)} cm` : ''}` : '—';
              return `<tr>
                <td><strong>${esc(e.sourceLabel)}</strong><small>${esc(shortDate(e.date))}</small></td>
                <td class="num">${fmt(e.peak_cm, 0)} cm</td>
                <td class="num">${exceed == null ? '—' : `${exceed >= 0 ? '+' : ''}${fmt(exceed, 0)} cm`}</td>
                <td class="num">${rainCell(e, 'rain_24h_mm', 'proxy_rain_24h_mm')} mm</td>
                <td class="num">${rainCell(e, 'rain_72h_mm')} ${num(e.rain_72h_mm) != null ? 'mm' : ''}</td>
                <td class="num">${rainCell(e, 'rain_168h_mm')} ${num(e.rain_168h_mm) != null ? 'mm' : ''}</td>
                <td class="num">${num(e.api_72h_mm) != null ? `${fmt(e.api_72h_mm, 1)} mm-eq.` : '—'}</td>
                <td class="num">${num(e.max_hourly_rise_cm_h) != null ? `${fmt(e.max_hourly_rise_cm_h, 0)} cm/h` : '—'}</td>
                <td>${esc(replay)}</td>
              </tr>`;
            }).join('')}</tbody>
          </table></div>`
        : '';
    }
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
    if (feedAge > 72 || (observedAge != null && observedAge > 3)) return ['rodada atrasada / parcial', 'proxy'];
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
    renderNowOverview(); renderAnswer(); renderLayers(); renderResearchContext(); renderKpis(); renderStationComparison(); renderRainBasinOverview(); renderRainSpatialMap(); renderZones(); renderModels(); renderEvents(); renderEvaluation(); renderProvenance(); renderStatus();
  }

  async function loadJson(url) {
    try {
      const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}cb=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) return null;
      return await response.json();
    } catch (_) { return null; }
  }
  async function loadLive(url) {
    if (typeof PrevineLiveFeed === 'object' && PrevineLiveFeed.fetchLive) {
      try { return await PrevineLiveFeed.fetchLive(url); } catch (_) { return null; }
    }
    return loadJson(url);
  }
  async function loadFeeds() {
    if (state.loading) return;
    state.loading = true;
    const pairs = Object.entries(stations);
    try {
      await Promise.all(pairs.map(async ([key, cfg]) => {
        const [pattern, weather, live] = await Promise.all([loadJson(cfg.pattern), loadJson(cfg.weather), loadLive(cfg.live)]);
        state.feeds[key] = { pattern, weather, live };
      }));
      const [research, rainSummary, basin, networkStatus] = await Promise.all([
        loadJson(researchUrl),
        loadJson(rainSummaryUrl),
        state.basinGeometry ? Promise.resolve(state.basinGeometry) : loadJson(basinUrl),
        loadJson(basinStatusUrl)
      ]);
      state.research = research;
      state.rainSummary = rainSummary;
      state.basinGeometry = basin;
      state.networkStatus = networkStatus;
      populateNetworkUpgFilter();
      populateNetworkStationSearch();
      if (!state.selectedNetworkStationId && networkStatus && Array.isArray(networkStatus.stations)) {
        const initial = networkStatus.stations.find((row) => String(row.code) === '86472600') || networkStatus.stations[0];
        state.selectedNetworkStationId = initial ? initial.id : null;
      }
      state.lastLoadedAt = new Date().toISOString();
      const available = pairs.filter(([key]) => stationFeed(key).pattern || stationFeed(key).weather || stationFeed(key).live).length;
      $('control-status').textContent = available ? `Feeds carregados às ${when(state.lastLoadedAt)} · atualização automática a cada 5 min` : 'Feeds indisponíveis no momento · tente atualizar a página';
      render();
      void loadRainSpatial();
    } finally {
      state.loading = false;
    }
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
  root.querySelectorAll('[data-rain-map-mode]').forEach((button) => {
    button.addEventListener('click', () => {
      state.rainMapMode = button.dataset.rainMapMode || 'forecast';
      root.querySelectorAll('[data-rain-map-mode]').forEach((b) => {
        const active = b === button;
        b.classList.toggle('is-active', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      renderRainSpatialMap();
    });
  });
  root.querySelectorAll('[data-rain-map-hours]').forEach((button) => {
    button.addEventListener('click', () => {
      state.rainMapHours = Number(button.dataset.rainMapHours) || 72;
      root.querySelectorAll('[data-rain-map-hours]').forEach((b) => {
        const active = b === button;
        b.classList.toggle('is-active', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      renderRainSpatialMap();
    });
  });

  root.querySelectorAll('[data-network-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      state.networkFilter = button.dataset.networkFilter || 'all';
      root.querySelectorAll('[data-network-filter]').forEach((b) => { b.classList.toggle('is-active', b === button); b.setAttribute('aria-pressed', b === button ? 'true' : 'false'); });
      renderBasinMap();
    });
  });
  root.querySelectorAll('[data-network-mode]').forEach((button) => {
    button.addEventListener('click', () => {
      state.networkMode = button.dataset.networkMode || 'health';
      root.querySelectorAll('[data-network-mode]').forEach((b) => { b.classList.toggle('is-active', b === button); b.setAttribute('aria-pressed', b === button ? 'true' : 'false'); });
      renderBasinMap();
    });
  });
  const sourceFilter = $('basin-source-filter');
  if (sourceFilter) sourceFilter.addEventListener('change', () => { state.networkSource = sourceFilter.value || 'all'; renderBasinMap(); });
  const upgFilter = $('basin-upg-filter');
  if (upgFilter) upgFilter.addEventListener('change', () => { state.networkUpg = upgFilter.value || 'all'; renderBasinMap(); });
  const variableFilter = $('basin-variable-filter');
  if (variableFilter) variableFilter.addEventListener('change', () => { state.networkVariable = variableFilter.value || 'all'; renderBasinMap(); });
  const modelFilter = $('basin-model-filter');
  if (modelFilter) modelFilter.addEventListener('change', () => { state.networkModel = modelFilter.value || 'all'; renderBasinMap(); });
  const stationSearch = $('basin-station-search');
  if (stationSearch) {
    const activateSearch = () => {
      const found = findNetworkStation(stationSearch.value);
      const status = $('basin-search-status');
      if (!found) {
        if (status) status.textContent = stationSearch.value.trim() ? 'Estação não encontrada no snapshot atual.' : '';
        return;
      }
      clearNetworkFilters();
      stationSearch.value = (found.code || '') + ' · ' + (found.name || 'Estação');
      state.selectedNetworkStationId = found.id;
      if (status) status.textContent = 'Selecionada: ' + (found.name || found.code) + ' · ' + (found.code || '');
      renderBasinMap();
    };
    stationSearch.addEventListener('change', activateSearch);
    stationSearch.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); activateSearch(); }
    });
  }
  const clearFilters = $('basin-clear-filters');
  if (clearFilters) clearFilters.addEventListener('click', () => { clearNetworkFilters(); renderBasinMap(); });

  loadFeeds();
  window.setInterval(() => {
    if (document.visibilityState === 'visible') loadFeeds();
  }, AUTO_REFRESH_MS);
})();
