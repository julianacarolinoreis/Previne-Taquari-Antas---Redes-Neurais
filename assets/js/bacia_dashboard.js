/* PREVINE · dashboard integrado da bacia
 * Os valores são lidos dos artefatos publicados; este arquivo não inventa uma
 * probabilidade conjunta nem transforma score em probabilidade calibrada.
 */
(function () {
  'use strict';

  const root = document.querySelector('[data-bacia-dashboard]');
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const state = { station: 'basin', horizon: 72, feeds: {} };
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
    ['Cabeceira', 'montante da bacia', 'A chuva nesta zona precisa de uma máscara espacial e de tempo de propagação validados.', 'var(--blue)', '20%'],
    ['Meio da bacia', 'células dos modelos', 'A média e o máximo publicados não permitem dizer, sozinhos, em qual município a chuva caiu.', 'var(--green)', '48%'],
    ['Perto da estação', 'ponto de leitura', 'A chuva no ponto e o nível ANA/SGB são mostrados quando a fonte os publica.', 'var(--amber)', '72%'],
    ['Jusante / foz', 'propagação', 'Ainda não há série zonal independente e tempo de propagação validados neste painel.', 'var(--purple)', '33%']
  ];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[c]));
  }
  function num(value) {
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
    const meanRain = first(w.basin_mean_mm, p.ifs_mean_mm, w.rain_ecmwf_direct_mm, p.ifs_direct_mm);
    const maxRain = first(w.basin_max_mm, p.ifs_max_mm, w.rain_ifs_proxy_mm, p.ifs_proxy_mm);
    const directRain = first(w.rain_ecmwf_direct_mm, p.ifs_direct_mm);
    const ifsProxyRain = first(w.rain_ifs_proxy_mm, p.ifs_proxy_mm);
    const gefsProxyRain = first(w.rain_gefs_proxy_mm, p.gefs_proxy_mm);
    const soil = first(w.soil_moisture_model_mean_m3m3, p.soil_moisture_m3m3);
    const risk = first(p.probability_percent, w.flood_probability_percent, num(w.flood_probability) == null ? null : w.flood_probability * 100);
    const score = first(p.rna_score_percent, w.rna_score_percent);
    const decision = p.decision || w.flood_decision || (w.flood_answer && /VAI/.test(w.flood_answer) ? 'VAI' : null);
    const generated = f.pattern && f.pattern.generated_at_utc || f.weather && f.weather.generated_at_utc;
    const forecastAge = ageHours(generated);
    const observedAge = ageHours(levelAt);
    const coverage = num(w.rain_hours_available);
    return { key, horizon: hours, station: s, pattern: f.pattern, weather: f.weather, live, p, w, obs, level, levelAt, pointRain, meanRain, maxRain, directRain, ifsProxyRain, gefsProxyRain, soil, risk, score, decision, generated, forecastAge, observedAge, coverage };
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
    return { value: snap.meanRain, label: 'média do recorte da bacia', source: 'ECMWF IFS' };
  }
  function sourceGenerated(snap) {
    const values = [snap.weather && snap.weather.generated_at_utc, snap.pattern && snap.pattern.generated_at_utc].filter(Boolean);
    return values.sort((a, b) => (parseDate(b)?.getTime() || 0) - (parseDate(a)?.getTime() || 0))[0] || null;
  }
  function liveSourceText(snap) {
    const src = snap.live && snap.live.estacao ? snap.live.estacao : snap.obs && snap.obs.source ? snap.obs.source : `ANA/SGB ${snap.station.code}`;
    return src;
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
      answerText.textContent = `Santa Tereza: ${fmt(ar.value, 2)} mm (${ar.label}); Muçum: ${fmt(br.value, 2)} mm (${br.label}). As estimativas experimentais de cruzar a cota são ${pct(a.risk)} e ${pct(b.risk)}, respectivamente. Não há probabilidade conjunta publicada.`;
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
    $('kpi-risk-note').textContent = 'estimativa experimental; não calibrada como alerta';
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
    if (!snap && state.station === 'basin' && zoneIndex === 1) {
      const a = stationSnapshot('santa', state.horizon); const b = stationSnapshot('mucum', state.horizon);
      return { value: `S ${fmt(a.meanRain, 1)} · M ${fmt(b.meanRain, 1)} mm`, note: 'médias do recorte · Santa / Muçum' };
    }
    if (!snap && state.station === 'basin' && zoneIndex === 2) {
      const a = stationSnapshot('santa', state.horizon); const b = stationSnapshot('mucum', state.horizon);
      return { value: `S ${fmt(a.pointRain, 1)} · M ${fmt(b.pointRain, 1)} mm`, note: 'ponto/célula próxima · Santa / Muçum' };
    }
    if (!snap) return { value: '—', note: 'sem estação selecionada' };
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
      return `<article class="zone-card" style="--zone-color:${z[3]};--zone-width:${z[4]}"><h3>${esc(z[0])}</h3><span class="zone-role">${esc(z[1])}</span><p><strong>${esc(v.value)}</strong><br>${esc(v.note)}</p><span class="zone-state">${i === 2 && v.value !== '—' ? 'valor publicado' : 'integração pendente'}</span></article>`;
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
        cards.push(modelCard(`${prefix}IFS · média do recorte`, 'PREVISÃO · chuva acumulada', s.meanRain, 'mm', 'Média das células do recorte usado pela rodada. Não é uma probabilidade.', 'ECMWF IFS', '#c47a10'));
        cards.push(modelCard(`${prefix}IFS · máximo espacial`, 'PREVISÃO · chuva acumulada', s.maxRain, 'mm', 'Maior célula disponível no recorte; não representa a bacia inteira.', 'ECMWF IFS', '#d59a33'));
        cards.push(modelCard(`${prefix}IFS · ponto`, 'PREVISÃO · chuva acumulada', s.pointRain, 'mm', 'Valor do ponto/célula mais próxima da estação.', 'ECMWF IFS', '#e2b85c'));
        cards.push(modelCard(`${prefix}RNA do feed`, 'SCORE · não calibrado', s.score, '%', 'Score do modelo de pesquisa. Não é frequência nem chance real.', 'RNA / feed visual', '#7650b4', 'experimental-card'));
        cards.push(modelCard(`${prefix}GEFS`, 'PROBABILIDADE · experimental', s.risk, '%', 'Estimativa experimental de cruzar a cota; não é alerta oficial.', 'NOAA GEFS · proxy/rodada', '#6541a7', 'experimental-card'));
      } else {
        cards.push(modelCard(`${prefix}IFS direto`, 'PREVISÃO · ponto Muçum', s.directRain, 'mm', 'Chuva acumulada direta no ponto/rodada IFS.', 'ECMWF IFS', '#c47a10'));
        cards.push(modelCard(`${prefix}IFS proxy`, 'PROXY · célula espacial', s.ifsProxyRain, 'mm', 'Proxy espacial usado na conferência; não é medição local.', 'ECMWF IFS / célula', '#d59a33'));
        cards.push(modelCard(`${prefix}GEFS proxy`, 'PROXY · ensemble', s.gefsProxyRain, 'mm', 'Proxy da célula GEFS que alimenta o ajuste de pesquisa.', 'NOAA GEFS / célula', '#e2b85c'));
        cards.push(modelCard(`${prefix}Cruzamento da cota`, 'PROBABILIDADE · experimental', s.risk, '%', 'Score logístico de pesquisa; não calibrado operacionalmente.', 'Modelo logístico · cota 1.800 cm', '#6541a7', 'experimental-card'));
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
      return `<section class="provenance-station"><h3>${esc(s.station.label)} <span>· rodada ${esc(when(sourceGenerated(s)))}</span></h3>${provenanceRow('Nível ANA/SGB', `${liveSourceText(s)} · ${when(s.levelAt)} · ${ageLabel(s.observedAge)}`, s.level == null ? 'UNKNOWN' : s.observedAge != null && s.observedAge > 3 ? 'atrasado' : 'observado', s.level == null || (s.observedAge != null && s.observedAge > 3) ? 'pending' : '')}${provenanceRow('Chuva prevista', `${displayRain(s).label} · fonte principal · +${state.horizon} h`, s.meanRain == null ? 'UNKNOWN' : feedState, feedClass)}${provenanceRow('Risco de pesquisa', `estimativa experimental · ${s.pattern && s.pattern.sources && s.pattern.sources.probability || 'JSON de probabilidade'}`, s.risk == null ? 'UNKNOWN' : 'experimental', s.risk == null ? 'pending' : 'proxy')}${provenanceRow('Solo / saturação', key === 'mucum' ? 'umidade modelada; não é medição local' : 'medição local não publicada', soilState, 'proxy')}${provenanceRow('Zonas e propagação', 'polígonos, radar/QPE e tempos de viagem', 'integração pendente', 'pending')}</section>`;
    }).join('');
    $('provenance-content').innerHTML = html;
  }

  function renderStatus() {
    const keys = state.station === 'basin' ? ['santa', 'mucum'] : [state.station];
    $('control-status').textContent = `${keys.map((key) => { const s = stationSnapshot(key, state.horizon); return `${stations[key].label}: feed ${ageLabel(s.forecastAge)} · observação ${ageLabel(s.observedAge)}`; }).join(' · ')} · horário em BRT`;
  }
  function render() {
    renderAnswer(); renderKpis(); renderStationComparison(); renderZones(); renderModels(); renderEvents(); renderEvaluation(); renderProvenance(); renderStatus();
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
    const available = pairs.filter(([key]) => stationFeed(key).pattern || stationFeed(key).weather).length;
    $('control-status').textContent = available ? 'Feeds publicados carregados · escolha local e horizonte' : 'Feeds indisponíveis no momento · tente atualizar a página';
    render();
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
