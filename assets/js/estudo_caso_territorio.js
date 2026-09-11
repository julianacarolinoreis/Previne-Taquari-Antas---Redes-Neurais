/* Estudo territorial PREVINE: RNA + mancha HAND + grade IBGE 200 m + ruas + pessoas.
   Pesquisa. Não emite alerta, ordem de evacuação nem despacho. */
(function () {
  'use strict';

  var CITIES = {
    santa_tereza: {
      id: 'santa_tereza',
      label: 'Santa Tereza',
      ibge: '4317251',
      station: '86472600',
      rna: '../previsao_ao_vivo.json',
      grade: '../assets/data/estudo_caso_territorio/grade_200m_santa_tereza.geojson',
      ruas: '../assets/data/estudo_caso_territorio/ruas_santa_tereza.json',
      mancha: '../assets/data/estudo_caso_territorio/mancha_santa_tereza.geojson',
      rota: '../assets/data/estudo_caso_territorio/rota_cenario_santa_tereza.json',
      replayKey: 'santa_tereza',
      levels: [15],
      defaultLevel: 15,
      bankfullFallback: 400,
      /* Centro urbano (não o envelope de todas as células HAND). */
      focus: { lat: -29.1701, lon: -51.7355, zoom: 15 },
      floodMap: '../santa_tereza_previsao_inundacao.html',
      ficha: '../pesquisa_status.html',
      painel: 'santa-tereza-painel-evacuacao.html',
      rotaCenario: '../santa_tereza_rota_fuga_ruas_cenario.html',
      mesa: 'estudo-caso-resposta-santa-tereza.html',
      impacto: 'santa-tereza-mapa-impacto.html',
      plan: null
    },
    mucum: {
      id: 'mucum',
      label: 'Muçum',
      ibge: '4312609',
      station: '86510000',
      rna: '../previsao_ao_vivo_mucum.json',
      grade: '../assets/data/estudo_caso_territorio/grade_200m_mucum.geojson',
      ruas: '../assets/data/estudo_caso_territorio/ruas_mucum.json',
      mancha: '../assets/data/estudo_caso_territorio/mancha_mucum.geojson',
      rota: '../assets/data/estudo_caso_territorio/rota_cenario_mucum.json',
      replayKey: 'mucum',
      levels: [18, 20, 25],
      defaultLevel: 18,
      bankfullFallback: 500,
      focus: { lat: -29.1648, lon: -51.8720, zoom: 15 },
      floodMap: '../mucum_previsao_inundacao.html',
      ficha: '../pesquisa_status_mucum.html',
      painel: 'mucum-painel-evacuacao.html',
      rotaCenario: '../mucum_rota_fuga_ruas_cenario.html',
      mesa: null,
      impacto: 'mucum-mapa-impacto.html',
      plan: '../assets/data/mucum_contingencia_202607.json'
    }
  };

  var REPLAY_URL = '../assets/data/research_event_replay_latest.json';
  var CASES_URL = '../assets/data/estudo_caso_territorio/casos_acoplados.json';
  var STORY = ['territorio', 'rna', 'mancha', 'grade', 'ruas', 'pessoas', 'rotas'];
  var STORY_CAPTION = {
    territorio: 'Centro urbano no satélite',
    rna: 'Régua nas próximas 2 horas (cm)',
    mancha: 'Mancha HAND do cenário (m)',
    grade: 'Quadrados IBGE — gente no limite da célula',
    ruas: 'Ruas do estudo',
    pessoas: 'Quem está no quadrado sob a mancha',
    rotas: 'Toque uma rua laranja ou o mapa → caminho até o abrigo seco'
  };
  var STORY_DWELL = {
    territorio: 2500,
    rna: 3500,
    mancha: 3500,
    grade: 2800,
    ruas: 2500,
    pessoas: 3500,
    rotas: 4500
  };

  var state = {
    city: 'santa_tereza',
    level: 15,
    caseId: 'live',
    casesDoc: null,
    selectedId: null,
    selectedStreet: null,
    basemap: 'sat',
    story: 'rotas',
    storyTimer: null,
    presenting: false,
    cache: {},
    loadGen: 0,
    map: null,
    layers: {
      basemap: null,
      labels: null,
      mancha: null,
      grade: null,
      ruas: null,
      flood: null,
      abrigos: null,
      highlight: null,
      rota: null,
      marks: null
    },
    canvas: null,
    streetHits: 0,
    maxScore: 1,
    clickMarker: null,
    lastRota: null,
    streetPriority: []
  };

  function $(id) { return document.getElementById(id); }
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }
  function num(v) {
    if (v == null || String(v).trim() === '') return null;
    var n = Number(String(v).replace(',', '.'));
    return Number.isFinite(n) ? n : null;
  }
  /* RNA sempre em cm — nunca o mesmo formato tipográfico dos botões HAND (m). */
  function fmtCm(v) {
    var n = num(v);
    if (n == null) return '—';
    return Math.round(n).toLocaleString('pt-BR') + ' cm';
  }
  function focusOf() {
    var f = city().focus || { lat: -29.17, lon: -51.80, zoom: 14 };
    return f;
  }
  function focusCenter(opts) {
    opts = opts || {};
    if (!state.map) return;
    var f = focusOf();
    var z = opts.zoom != null ? opts.zoom : f.zoom;
    state.map.setView([f.lat, f.lon], z, { animate: opts.animate !== false });
  }
  function focusOnPoint(lat, lon, opts) {
    opts = opts || {};
    if (!state.map) return;
    var minZ = opts.minZoom != null ? opts.minZoom : 15;
    var target = opts.zoom != null ? opts.zoom : Math.max(state.map.getZoom(), minZ);
    if (target < minZ) target = minZ;
    if (opts.maxZoom != null && target > opts.maxZoom) target = opts.maxZoom;
    state.map.setView([lat, lon], target, { animate: opts.animate !== false });
  }
  function focusLocalPath(pts, anchorLat, anchorLon) {
    if (!state.map || !pts || pts.length < 2) {
      if (anchorLat != null) focusOnPoint(anchorLat, anchorLon, { zoom: 16 });
      return;
    }
    /* Não abrir o município inteiro: enquadra só um trecho local da rota. */
    var maxSpan = 0.012;
    var local = [pts[0]];
    for (var i = 1; i < pts.length; i++) {
      var dlat = Math.abs(pts[i][0] - pts[0][0]);
      var dlon = Math.abs(pts[i][1] - pts[0][1]);
      if (dlat > maxSpan || dlon > maxSpan) break;
      local.push(pts[i]);
    }
    if (local.length < 2) {
      focusOnPoint(anchorLat != null ? anchorLat : pts[0][0], anchorLon != null ? anchorLon : pts[0][1], { zoom: 16 });
      return;
    }
    try {
      var b = L.latLngBounds(local);
      if (b.isValid()) {
        state.map.fitBounds(b, { padding: [48, 48], maxZoom: 17, animate: true });
        if (state.map.getZoom() < 15) state.map.setZoom(15);
      }
    } catch (e) {
      focusOnPoint(pts[0][0], pts[0][1], { zoom: 16 });
    }
  }
  function fmtInt(v) {
    var n = num(v);
    return n == null ? '—' : Math.round(n).toLocaleString('pt-BR');
  }
  function fmtPct(v) {
    var n = num(v);
    return n == null ? '—' : n.toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' %';
  }
  function city() { return CITIES[state.city]; }

  function parseCity(opts) {
    var q = new URLSearchParams(location.search).get('cidade') || '';
    var h = (location.hash || '').replace('#', '');
    var raw = (q || h).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    if (raw.indexOf('muc') >= 0) return 'mucum';
    if (raw.indexOf('santa') >= 0 || raw.indexOf('tereza') >= 0) return 'santa_tereza';
    if (opts && opts.allowDefault) return 'santa_tereza';
    return null;
  }

  function setUrl() {
    var slug = state.city === 'mucum' ? 'mucum' : 'santa-tereza';
    var url = new URL(location.href);
    url.searchParams.set('cidade', slug);
    if (state.caseId && state.caseId !== 'live') url.searchParams.set('caso', state.caseId);
    else url.searchParams.delete('caso');
    url.hash = slug;
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }

  function defaultCaseId(cityId) {
    if (cityId === 'mucum') return 'mucum-e27-mai2024-hotel';
    if (cityId === 'santa_tereza') return 'st-e4-set2023';
    return 'live';
  }

  function parseCaseId() {
    var q = (new URLSearchParams(location.search).get('caso') || '').trim();
    if (q) return q;
    /* Abre no caso mais fácil de ler (Hotel em Muçum; cheia set/2023 em ST). */
    return defaultCaseId(state.city);
  }

  function casesForCity() {
    var doc = state.casesDoc;
    if (!doc || !Array.isArray(doc.cases)) return [];
    return doc.cases.filter(function (c) {
      return !c.city || c.city === state.city || c.mode === 'live';
    });
  }

  function currentCase() {
    var list = casesForCity();
    var found = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === state.caseId) { found = list[i]; break; }
    }
    if (found) return found;
    for (i = 0; i < list.length; i++) {
      if (list[i].mode === 'live') return list[i];
    }
    return { id: 'live', mode: 'live', label: 'Ao vivo', short: 'Régua agora' };
  }

  function loadCasesDoc() {
    if (state.casesDoc) return Promise.resolve(state.casesDoc);
    return fetchJson(CASES_URL).then(function (doc) {
      state.casesDoc = doc;
      return doc;
    }).catch(function (err) {
      console.warn('casos acoplados indisponíveis', err);
      state.casesDoc = {
        cases: [{ id: 'live', mode: 'live', label: 'Ao vivo', short: 'Régua agora', city: null }]
      };
      return state.casesDoc;
    });
  }

  function fetchJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(url + ' · HTTP ' + r.status);
      return r.json();
    });
  }

  function loadCityBundle() {
    var c = city();
    var key = c.id;
    var cached = state.cache[key] || {};
    var needed = {
      rna: c.rna,
      grade: c.grade,
      ruas: c.ruas,
      mancha: c.mancha,
      rota: c.rota,
      replay: REPLAY_URL
    };
    if (c.plan) needed.plan = c.plan;
    var jobs = {};
    Object.keys(needed).forEach(function (k) {
      if (k === 'replay' && state.cache._replay) {
        jobs[k] = Promise.resolve(state.cache._replay);
        return;
      }
      if (k !== 'rna' && cached[k]) {
        jobs[k] = Promise.resolve(cached[k]);
        return;
      }
      jobs[k] = fetchJson(needed[k]);
    });
    return Promise.all(Object.keys(jobs).map(function (k) {
      return jobs[k].then(function (v) { return [k, v, null]; }).catch(function (err) {
        return [k, null, err];
      });
    })).then(function (pairs) {
      var bundle = { errors: [] };
      pairs.forEach(function (p) {
        bundle[p[0]] = p[1];
        if (p[2]) bundle.errors.push(p[0] + ': ' + (p[2].message || p[2]));
      });
      if (bundle.replay) state.cache._replay = bundle.replay;
      state.cache[key] = bundle;
      return bundle;
    });
  }

  function scenario(bundle) {
    var spatial = bundle.replay && bundle.replay.spatial_scenarios
      && bundle.replay.spatial_scenarios[city().replayKey];
    if (!spatial || !Array.isArray(spatial.scenarios)) return null;
    var level = Number(state.level);
    return spatial.scenarios.find(function (s) { return Number(s.level_m) === level; }) || null;
  }

  function hitMap(sc) {
    var map = Object.create(null);
    (sc && sc.intersected_cells_200m || []).forEach(function (cell) {
      map[cell.id_grade] = cell;
    });
    return map;
  }

  function rankedCells(bundle) {
    var sc = scenario(bundle);
    var hits = hitMap(sc);
    var feats = (bundle.grade && bundle.grade.features) || [];
    return feats.map(function (f) {
      var id = f.properties && f.properties.id_grade;
      var hit = hits[id];
      var pop = num(f.properties && f.properties.pop) || 0;
      var overlap = hit ? num(hit.overlap_pct_proxy) || 0 : 0;
      return {
        id: id,
        pop: pop,
        dom: num(f.properties && f.properties.dom) || 0,
        overlap: overlap,
        touched: Boolean(hit),
        score: pop * (overlap / 100),
        feature: f
      };
    }).filter(function (c) { return c.touched; })
      .sort(function (a, b) {
        return (b.score - a.score) || (b.overlap - a.overlap) || (b.pop - a.pop) || String(a.id).localeCompare(String(b.id));
      });
  }

  function colorFor(overlap) {
    if (!(overlap > 0)) return '#c5ccc4';
    if (overlap >= 80) return '#ef7a68';
    if (overlap >= 40) return '#f5c76b';
    return '#8dbf74';
  }

  function setChain(step) {
    document.querySelectorAll('.chain [data-step]').forEach(function (el) {
      el.classList.toggle('is-active', el.getAttribute('data-step') === step);
    });
  }

  function ensureMap() {
    if (state.map) return state.map;
    state.canvas = L.canvas({ padding: 0.5 });
    state.map = L.map('map', {
      zoomControl: true,
      attributionControl: true,
      minZoom: 12,
      maxZoom: 19,
      center: [focusOf().lat, focusOf().lon],
      zoom: focusOf().zoom
    });
    applyBasemap('sat');
    state.layers.mancha = L.layerGroup().addTo(state.map);
    state.layers.grade = L.layerGroup().addTo(state.map);
    state.layers.ruas = L.layerGroup().addTo(state.map);
    state.layers.flood = L.layerGroup().addTo(state.map);
    state.layers.abrigos = L.layerGroup().addTo(state.map);
    state.layers.highlight = L.layerGroup().addTo(state.map);
    state.layers.rota = L.layerGroup().addTo(state.map);
    state.layers.marks = L.layerGroup().addTo(state.map);
    state.map.on('click', onMapClick);
    return state.map;
  }

  function applyBasemap(mode) {
    state.basemap = mode === 'osm' ? 'osm' : 'sat';
    if (!state.map) return;
    if (state.layers.basemap) state.map.removeLayer(state.layers.basemap);
    if (state.layers.labels) state.map.removeLayer(state.layers.labels);
    state.layers.basemap = null;
    state.layers.labels = null;
    if (state.basemap === 'osm') {
      state.layers.basemap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap',
        maxZoom: 19
      }).addTo(state.map);
    } else {
      /* Mesmo satélite das páginas de previsão / impacto / rotas — telhados e quarteirões. */
      state.layers.basemap = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
          attribution: '&copy; Esri, Maxar',
          maxZoom: 19,
          maxNativeZoom: 19
        }
      ).addTo(state.map);
      state.layers.labels = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 19, opacity: 0.75, interactive: false }
      ).addTo(state.map);
    }
    document.querySelectorAll('[data-basemap]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('data-basemap') === state.basemap));
    });
  }

  function manchaFeature(bundle) {
    var feats = (bundle.mancha && bundle.mancha.features) || [];
    var level = Number(state.level);
    return feats.find(function (f) {
      return Number(f.properties && f.properties.nivel_m) === level;
    }) || null;
  }

  function drawMancha(bundle) {
    state.layers.mancha.clearLayers();
    var feat = manchaFeature(bundle);
    if (!feat) return;
    L.geoJSON(feat, {
      style: {
        color: '#7ec8e8',
        weight: 1.6,
        fillColor: '#176ca8',
        fillOpacity: 0.18,
        opacity: 0.95
      },
      interactive: false
    }).addTo(state.layers.mancha);
  }

  function drawMarks() {
    if (!state.layers.marks) return;
    state.layers.marks.clearLayers();
    var caso = currentCase();
    var marks = (caso && caso.marks) || [];
    if (!marks.length) return;
    marks.forEach(function (m) {
      if (num(m.lat) == null || num(m.lon) == null) return;
      var hot = !!m.highlight || (caso.focus_mark && m.name === caso.focus_mark);
      var marker = L.circleMarker([m.lat, m.lon], {
        radius: hot ? 8 : 5,
        color: hot ? '#7a2f28' : '#5c4033',
        weight: hot ? 2.4 : 1.4,
        fillColor: hot ? '#f0c14a' : '#d9c3a0',
        fillOpacity: 0.95
      });
      var elev = m.elevation_m != null
        ? (Number(m.elevation_m).toLocaleString('pt-BR', { maximumFractionDigits: 2 }) + ' m')
        : 'cota não informada';
      marker.bindPopup(
        '<strong>' + esc(m.name) + '</strong><br>' +
        'Marca de onde a água chegou' + (elev !== 'cota não informada' ? ' · ' + esc(elev) : '') + '<br>' +
        '<em>registro histórico · não é alerta de agora</em>'
      );
      marker.addTo(state.layers.marks);
    });
  }

  function drawGrade(bundle) {
    state.layers.grade.clearLayers();
    state._gradeLayer = null;
    if (!bundle.grade || !Array.isArray(bundle.grade.features)) return;
    var ranked = rankedCells(bundle);
    var byId = Object.create(null);
    ranked.forEach(function (c) { byId[c.id] = c; });
    var geo = L.geoJSON(bundle.grade, {
      style: function (feature) {
        var id = feature.properties && feature.properties.id_grade;
        var cell = byId[id];
        var selected = id === state.selectedId;
        return {
          color: selected ? '#f5f3ec' : 'rgba(245,243,236,.55)',
          weight: selected ? 2.4 : 0.7,
          fillColor: colorFor(cell ? cell.overlap : 0),
          fillOpacity: cell ? (selected ? 0.52 : 0.28) : 0.04
        };
      },
      onEachFeature: function (feature, layer) {
        var id = feature.properties && feature.properties.id_grade;
        layer.on('click', function (ev) {
          if (ev && ev.originalEvent) L.DomEvent.stopPropagation(ev.originalEvent);
          selectCell(bundle, id, { zoom: true, story: 'pessoas' });
        });
      }
    });
    geo.addTo(state.layers.grade);
    state._gradeLayer = geo;
  }

  function extendBounds(acc, layer) {
    if (!layer || !layer.getBounds) return acc;
    try {
      var gb = layer.getBounds();
      if (!gb || !gb.isValid()) return acc;
      return acc ? acc.extend(gb) : L.latLngBounds(gb.getSouthWest(), gb.getNorthEast());
    } catch (e) {
      return acc;
    }
  }

  function studyBounds(bundle) {
    var hits = hitMap(scenario(bundle));
    var bounds = null;
    if (state._gradeLayer) {
      state._gradeLayer.eachLayer(function (layer) {
        var id = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
        if (hits[id]) bounds = extendBounds(bounds, layer);
      });
    }
    if ((!bounds || !bounds.isValid()) && state._gradeLayer) bounds = extendBounds(bounds, state._gradeLayer);
    return bounds;
  }

  function drawStreets(bundle) {
    state.layers.ruas.clearLayers();
    if (state.layers.flood) state.layers.flood.clearLayers();
    var rota = bundle.rota;
    var ruas = bundle.ruas;
    var nos = (rota && rota.nos) || (ruas && ruas.nos);
    var edges = (rota && rota.edges) || (ruas && ruas.edges);
    if (!nos || !edges) return;
    var dry = [];
    var wet = [];
    edges.forEach(function (e) {
      var a = nos[e[0]];
      var c = nos[e[1]];
      if (!a || !c) return;
      var seg = [a, c];
      if (e[2] === 1) wet.push(seg);
      else dry.push(seg);
    });
    if (dry.length) {
      L.polyline(dry, {
        color: state.basemap === 'sat' ? '#f5f3ec' : '#0c2a22',
        weight: state.basemap === 'sat' ? 1.05 : 1.2,
        opacity: state.basemap === 'sat' ? 0.55 : 0.4,
        interactive: false,
        renderer: state.canvas
      }).addTo(state.layers.ruas);
    }
    if (wet.length && state.layers.flood) {
      L.polyline(wet, {
        color: '#c45c26',
        weight: 3.4,
        opacity: 0.95,
        lineCap: 'round',
        interactive: false,
        renderer: state.canvas
      }).addTo(state.layers.flood);
    }
  }

  function buildStreetPriority(bundle) {
    var rota = bundle.rota;
    if (!rota || !Array.isArray(rota.edges) || !Array.isArray(rota.nos)) return [];
    var nos = rota.nos;
    var cells = rankedCells(bundle);
    var cellBounds = [];
    if (state._gradeLayer) {
      state._gradeLayer.eachLayer(function (layer) {
        var id = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
        var cell = cells.find(function (c) { return c.id === id; });
        if (!cell || !layer.getBounds) return;
        cellBounds.push({ cell: cell, bounds: layer.getBounds() });
      });
    }
    var seen = Object.create(null);
    var list = [];
    rota.edges.forEach(function (e, idx) {
      if (e[2] !== 1) return;
      var a = nos[e[0]];
      var b = nos[e[1]];
      if (!a || !b) return;
      var midLat = (a[0] + b[0]) / 2;
      var midLon = (a[1] + b[1]) / 2;
      var bucket = midLat.toFixed(3) + ':' + midLon.toFixed(3);
      if (seen[bucket]) return;
      seen[bucket] = true;
      var agua = ((num(rota.agua_m[e[0]]) || 0) + (num(rota.agua_m[e[1]]) || 0)) / 2;
      var dist = ((num(rota.dist_m[e[0]]) || 0) + (num(rota.dist_m[e[1]]) || 0)) / 2;
      var popNear = 0;
      for (var i = 0; i < cellBounds.length; i++) {
        if (cellBounds[i].bounds.contains([midLat, midLon])) {
          popNear = Math.max(popNear, cellBounds[i].cell.pop || 0);
        }
      }
      list.push({
        id: 's' + idx,
        midLat: midLat,
        midLon: midLon,
        agua: agua,
        dist: dist,
        popNear: popNear,
        score: popNear * 2 + agua + Math.max(0, 2500 - dist) * 0.05
      });
    });
    list.sort(function (x, y) {
      return (y.score - x.score) || (y.agua - x.agua) || (x.dist - y.dist);
    });
    return list.slice(0, 10);
  }

  function renderStreetPriority(bundle) {
    var ol = $('street-priority');
    var count = $('street-count');
    state.streetPriority = buildStreetPriority(bundle);
    var nFlood = 0;
    if (bundle.rota && bundle.rota.edges) {
      bundle.rota.edges.forEach(function (e) { if (e[2] === 1) nFlood += 1; });
    }
    if (count) {
      count.textContent = nFlood
        ? ('Laranja no mapa = água na rua. Toque um trecho abaixo (mostro ' +
          state.streetPriority.length + ' dos ' + nFlood + ').')
        : 'Neste momento o mapa não marca rua com água.';
    }
    if (!ol) return;
    if (!state.streetPriority.length) {
      ol.innerHTML = '<li class="empty">Nenhum trecho para toque ainda.</li>';
      return;
    }
    ol.innerHTML = state.streetPriority.map(function (s, i) {
      var km = s.dist != null ? (s.dist / 1000).toFixed(1).replace('.', ',') + ' km até o seco' : '—';
      var titulo = i === 0 ? 'Trecho mais perto do abrigo' : ('Trecho ' + (i + 1));
      return '<li><button type="button" class="street-btn' + (state.selectedStreet === s.id ? ' is-active' : '') +
        '" data-street="' + esc(s.id) + '" aria-pressed="' +
        String(state.selectedStreet === s.id) + '">' +
        '<span class="rank">' + String(i + 1).padStart(2, '0') + '</span>' +
        '<span class="body"><b>' + esc(titulo) + '</b><small>' + esc(km) + '</small></span>' +
        '</button></li>';
    }).join('');
  }

  function selectStreet(bundle, streetId) {
    var s = (state.streetPriority || []).find(function (x) { return x.id === streetId; });
    if (!s || !state.map) return;
    state.selectedStreet = streetId;
    renderStreetPriority(bundle);
    goStory('rotas', { silentPlay: true, keepSelection: true });
    if (state.clickMarker) state.map.removeLayer(state.clickMarker);
    state.clickMarker = L.circleMarker([s.midLat, s.midLon], {
      radius: 7, color: '#c45c26', fillColor: '#fff', fillOpacity: 1, weight: 3
    }).addTo(state.map);
    focusOnPoint(s.midLat, s.midLon, { zoom: 16, maxZoom: 17 });
    var rotaInfo = drawRota(bundle, s.midLat, s.midLon, { fit: true });
    var cell = nearestTouchedCell(bundle, s.midLat, s.midLon);
    if (cell) {
      state.selectedId = cell.id;
      drawGrade(bundle);
    }
    updateLiveCard(bundle, cell, { lat: s.midLat, lng: s.midLon }, rotaInfo);
    var cap = $('story-caption');
    if (cap) {
      var casoStory = currentCase();
      cap.textContent = (casoStory && casoStory.story)
        ? casoStory.story
        : 'Toque a rua laranja → caminho até o abrigo seco';
    }
    pulseMap();
    applyStoryLayers();
  }

  function pointInRing(lat, lng, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1];
      var xj = ring[j][0], yj = ring[j][1];
      var hit = ((yi > lat) !== (yj > lat)) && (lng < (xj - xi) * (lat - yi) / ((yj - yi) || 1e-12) + xi);
      if (hit) inside = !inside;
    }
    return inside;
  }

  function pointInGeometry(lat, lng, geometry) {
    if (!geometry) return false;
    var polys = geometry.type === 'MultiPolygon' ? geometry.coordinates
      : geometry.type === 'Polygon' ? [geometry.coordinates]
      : null;
    if (!polys) return false;
    for (var p = 0; p < polys.length; p++) {
      if (!pointInRing(lat, lng, polys[p][0])) continue;
      var hole = false;
      for (var h = 1; h < polys[p].length; h++) {
        if (pointInRing(lat, lng, polys[p][h])) hole = true;
      }
      if (!hole) return true;
    }
    return false;
  }

  function orient(ax, ay, bx, by, cx, cy) {
    var v = (by - ay) * (cx - bx) - (bx - ax) * (cy - by);
    if (Math.abs(v) < 1e-18) return 0;
    return v > 0 ? 1 : 2;
  }

  function onSeg(ax, ay, bx, by, cx, cy) {
    return Math.min(ax, bx) - 1e-12 <= cx && cx <= Math.max(ax, bx) + 1e-12 &&
      Math.min(ay, by) - 1e-12 <= cy && cy <= Math.max(ay, by) + 1e-12;
  }

  function segsIntersect(a, b, c, d) {
    var ax = a[1], ay = a[0], bx = b[1], by = b[0];
    var cx = c[1], cy = c[0], dx = d[1], dy = d[0];
    var o1 = orient(ax, ay, bx, by, cx, cy);
    var o2 = orient(ax, ay, bx, by, dx, dy);
    var o3 = orient(cx, cy, dx, dy, ax, ay);
    var o4 = orient(cx, cy, dx, dy, bx, by);
    if (o1 !== o2 && o3 !== o4) return true;
    if (o1 === 0 && onSeg(ax, ay, bx, by, cx, cy)) return true;
    if (o2 === 0 && onSeg(ax, ay, bx, by, dx, dy)) return true;
    if (o3 === 0 && onSeg(cx, cy, dx, dy, ax, ay)) return true;
    if (o4 === 0 && onSeg(cx, cy, dx, dy, bx, by)) return true;
    return false;
  }

  function ringEdges(ring) {
    var n = ring && ring.length ? ring.length : 0;
    if (n < 2) return [];
    var closed = n > 2 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1];
    var count = closed ? n - 1 : n;
    var edges = [];
    for (var i = 0; i < count; i++) edges.push([ring[i], ring[(i + 1) % n]]);
    return edges;
  }

  function segmentHitsGeometry(a, c, geometry) {
    if (!a || !c) return false;
    if (pointInGeometry(a[0], a[1], geometry) || pointInGeometry(c[0], c[1], geometry)) return true;
    if (!geometry) return false;
    var polys = geometry.type === 'MultiPolygon' ? geometry.coordinates
      : geometry.type === 'Polygon' ? [geometry.coordinates]
      : null;
    if (!polys) return false;
    for (var p = 0; p < polys.length; p++) {
      var edges = ringEdges(polys[p][0]);
      for (var i = 0; i < edges.length; i++) {
        var p1 = [edges[i][0][1], edges[i][0][0]];
        var p2 = [edges[i][1][1], edges[i][1][0]];
        if (segsIntersect(a, c, p1, p2)) return true;
      }
    }
    return false;
  }

  function highlightStreets(bundle, bounds, geometry) {
    state.layers.highlight.clearLayers();
    state.streetHits = 0;
    if (!bundle.ruas || !Array.isArray(bundle.ruas.nos) || !Array.isArray(bundle.ruas.edges)) return;
    var nos = bundle.ruas.nos;
    var pad = 0.00015;
    var south = bounds ? bounds.getSouth() - pad : null;
    var north = bounds ? bounds.getNorth() + pad : null;
    var west = bounds ? bounds.getWest() - pad : null;
    var east = bounds ? bounds.getEast() + pad : null;
    function inPad(pt) {
      if (!pt || south == null) return true;
      return pt[0] >= south && pt[0] <= north && pt[1] >= west && pt[1] <= east;
    }
    function segMayHit(a, c) {
      if (south == null) return true;
      var minLat = Math.min(a[0], c[0]);
      var maxLat = Math.max(a[0], c[0]);
      var minLng = Math.min(a[1], c[1]);
      var maxLng = Math.max(a[1], c[1]);
      return maxLat >= south && minLat <= north && maxLng >= west && minLng <= east;
    }
    function hits(a, c) {
      if (!a || !c) return false;
      if (!geometry) return inPad(a) || inPad(c);
      if (!segMayHit(a, c)) return false;
      return segmentHitsGeometry(a, c, geometry);
    }
    var segs = [];
    bundle.ruas.edges.forEach(function (e) {
      var a = nos[e[0]];
      var c = nos[e[1]];
      if (hits(a, c)) segs.push([a, c]);
    });
    if (!segs.length) return;
    L.polyline(segs, {
      color: '#0c2a22',
      weight: 3.4,
      opacity: 0.95,
      interactive: false
    }).addTo(state.layers.highlight);
    state.streetHits = segs.length;
    setChain('ruas');
  }

  function abrigosOf(bundle) {
    var list = [];
    if (bundle.rota && Array.isArray(bundle.rota.abrigos)) {
      bundle.rota.abrigos.forEach(function (a) {
        if (num(a.lat) != null && num(a.lon) != null) list.push(a);
      });
    }
    if (!list.length && bundle.plan && Array.isArray(bundle.plan.abrigos)) {
      bundle.plan.abrigos.forEach(function (a) {
        if (num(a.lat) != null && num(a.lon) != null) list.push(a);
      });
    }
    if (!list.length && bundle.ruas && Array.isArray(bundle.ruas.abrigos)) {
      list = bundle.ruas.abrigos.filter(function (a) {
        return num(a.lat) != null && num(a.lon) != null;
      });
    }
    return list;
  }

  function clearRota() {
    state.lastRota = null;
    if (state.layers.rota) state.layers.rota.clearLayers();
    var metrics = $('rota-metrics');
    if (metrics) {
      metrics.hidden = true;
      metrics.innerHTML = '';
    }
  }

  function nearestRotaNode(rota, lat, lon) {
    if (!rota || !Array.isArray(rota.nos) || !rota.nos.length) return -1;
    var best = -1;
    var bd = 1e18;
    for (var i = 0; i < rota.nos.length; i++) {
      var n = rota.nos[i];
      var dy = n[0] - lat;
      var dx = (n[1] - lon) * Math.cos(lat * Math.PI / 180);
      var d = dy * dy + dx * dx;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  function followRotaPath(rota, i0) {
    var pts = [];
    var i = i0;
    var guard = 0;
    while (i >= 0 && guard++ < 8000) {
      pts.push(rota.nos[i]);
      var nx = rota.prox[i];
      if (nx == null || nx === i || nx < 0) break;
      i = nx;
    }
    return pts;
  }

  function resolveRota(bundle, lat, lon) {
    var rota = bundle.rota;
    if (!rota || !Array.isArray(rota.nos) || !Array.isArray(rota.prox)) return null;
    var i0 = nearestRotaNode(rota, lat, lon);
    if (i0 < 0) return null;
    var pts = followRotaPath(rota, i0);
    var destId = rota.dest && rota.dest[i0];
    var abrigo = (rota.abrigos || []).find(function (x) { return x.id === destId; }) ||
      (rota.abrigos && rota.abrigos[0]) || null;
    var distM = rota.dist_m ? num(rota.dist_m[i0]) : null;
    var aguaM = rota.agua_m ? num(rota.agua_m[i0]) : null;
    return {
      i0: i0,
      pts: pts,
      abrigo: abrigo,
      destId: destId,
      distM: distM,
      aguaM: aguaM,
      meta: rota.meta || null
    };
  }

  function renderRotaMetrics(info) {
    var metrics = $('rota-metrics');
    var note = $('rota-note');
    var sheetRota = $('sheet-rota');
    if (!metrics) return;
    if (!info) {
      metrics.hidden = true;
      metrics.innerHTML = '';
      if (sheetRota) { sheetRota.hidden = true; sheetRota.innerHTML = ''; }
      return;
    }
    var km = info.distM != null ? (info.distM / 1000).toFixed(2).replace('.', ',') + ' km' : '—';
    var agua = info.aguaM != null
      ? (info.aguaM >= 1000
        ? (info.aguaM / 1000).toFixed(2).replace('.', ',') + ' km sob a mancha do cenário'
        : Math.round(info.aguaM) + ' m sob a mancha do cenário')
      : 'trecho sob água não informado';
    var nome = info.abrigo && info.abrigo.nome ? info.abrigo.nome : 'abrigo do cenário';
    metrics.hidden = false;
    metrics.innerHTML =
      '<div class="rota-line"><span>Abrigo</span><b>' + esc(nome) + '</b></div>' +
      '<div class="rota-line"><span>A pé</span><b>' + esc(km) + '</b></div>' +
      '<div class="rota-line"><span>Água (cenário de rota)</span><b>' + esc(agua) + '</b></div>' +
      '<p class="rota-caveat">Proxy de esforço no grafo OSM — não é tempo operacional nem ordem de saída. Não acompanha o HAND do mapa.</p>';
    if (sheetRota) {
      sheetRota.hidden = false;
      sheetRota.innerHTML = metrics.innerHTML;
    }
    if (note && info.meta) {
      var rotulo = (info.meta.nivel && info.meta.nivel.rotulo) ||
        (info.meta.nivel_projeto_m != null ? 'cenário de projeto ' + info.meta.nivel_projeto_m + ' m' : null);
      note.textContent = 'Rota do cenário de ruas' +
        (rotulo ? ' (' + rotulo + ')' : '') +
        (info.meta.nivel_projeto_m != null ? ' · HAND projeto ' + info.meta.nivel_projeto_m + ' m' : '') +
        '. Independente do HAND ' + state.level + ' m no mapa; conversão régua ↔ HAND pendente.';
    }
    renderLedger(state.cache[state.city]);
  }

  function renderLedger(bundle) {
    var rnaEl = $('ledger-rna');
    var handEl = $('ledger-hand');
    var rotaEl = $('ledger-rota');
    var convEl = $('ledger-conv');
    if (!rnaEl) return;
    var d = (bundle && bundle.rna) || {};
    var now = d.nivel_rio_agora_cm != null ? d.nivel_rio_agora_cm : d.nivel_atual_cm;
    rnaEl.textContent = fmtCm(now);
    if (handEl) handEl.textContent = 'HAND ' + state.level + ' m';
    var meta = bundle && bundle.rota && bundle.rota.meta;
    if (rotaEl) {
      if (meta && meta.nivel_projeto_m != null) {
        rotaEl.textContent = 'rota @ HAND ' + meta.nivel_projeto_m + ' m';
      } else {
        rotaEl.textContent = 'rota = cenário fixo';
      }
    }
    if (convEl) convEl.textContent = 'sem conversão';
  }

  function drawRota(bundle, lat, lon, opts) {
    opts = opts || {};
    if (state.layers.rota) state.layers.rota.clearLayers();
    var info = resolveRota(bundle, lat, lon);
    state.lastRota = info;
    if (!info || !info.pts || info.pts.length < 2) {
      renderRotaMetrics(null);
      return null;
    }
    L.polyline(info.pts, {
      color: '#0f8b46',
      weight: 5,
      opacity: 0.95,
      lineJoin: 'round',
      lineCap: 'round',
      interactive: false
    }).addTo(state.layers.rota);
    if (info.abrigo && num(info.abrigo.lat) != null && num(info.abrigo.lon) != null) {
      L.circleMarker([info.abrigo.lat, info.abrigo.lon], {
        radius: 8,
        color: '#0c2a22',
        weight: 2,
        fillColor: '#f5c76b',
        fillOpacity: 1,
        interactive: false
      }).addTo(state.layers.rota);
    }
    renderRotaMetrics(info);
    if (opts.fit && state.map) {
      focusLocalPath(info.pts, lat, lon);
    }
    setChain('rotas');
    return info;
  }

  function drawAbrigos(bundle) {
    state.layers.abrigos.clearLayers();
    abrigosOf(bundle).forEach(function (a) {
      var m = L.circleMarker([a.lat, a.lon], {
        radius: 7,
        color: '#0c2a22',
        weight: 1.5,
        fillColor: '#f5c76b',
        fillOpacity: 1
      });
      var cap = a.capacidade_quadro_13 || a.capacidade_ficha_tecnica || a.capacidade_planejada;
      m.bindPopup(
        '<strong>' + esc(a.nome) + '</strong><br>' +
        (a.endereco ? esc(a.endereco) + '<br>' : '') +
        (cap != null ? 'capacidade no plano/estudo: ' + esc(cap) + '<br>' : '') +
        '<em>referência de pesquisa; ocupação e abertura atuais desconhecidas</em>'
      );
      m.addTo(state.layers.abrigos);
    });
  }

  function renderGauge(now, fore, bank) {
    var max = Math.max(bank || 0, now || 0, fore || 0, 1);
    function pct(v) {
      var n = num(v);
      if (n == null) return 0;
      return Math.max(2, Math.min(100, (n / max) * 100));
    }
    var bankEl = $('gauge-bank');
    var nowEl = $('gauge-now');
    var prevEl = $('gauge-prev');
    var deltaEl = $('gauge-delta');
    if (bankEl) bankEl.style.width = pct(bank) + '%';
    if (nowEl) nowEl.style.width = pct(now) + '%';
    if (prevEl) prevEl.style.width = pct(fore) + '%';
    if (deltaEl) {
      if (num(now) == null || num(fore) == null) {
        deltaEl.textContent = 'Δ —';
      } else {
        var d = Math.round(fore - now);
        deltaEl.textContent = 'Δ ' + (d > 0 ? '+' : '') + d + ' cm em +2 h';
      }
    }
    var prevVal = $('rna-prev');
    if (prevVal) prevVal.classList.toggle('is-hot', num(fore) != null && num(now) != null && fore > now);
  }

  function renderRna(bundle) {
    var caso = currentCase();
    var d = bundle.rna || {};
    var now, fore, bank, agoraS, prevS, hz;
    bank = d.bankfull_cm != null ? d.bankfull_cm : city().bankfullFallback;
    hz = '+2 h';
    if (caso && caso.mode === 'coupled' && caso.rna && caso.rna.decision_frame) {
      var fr = caso.rna.decision_frame;
      now = fr.now_obs_cm;
      fore = fr.plus_2h_rna_cm != null ? fr.plus_2h_rna_cm : fr.plus_2h_obs_cm;
      if (caso.bankfull_cm != null) bank = caso.bankfull_cm;
      hz = fr.horizon_label || ('+' + (caso.rna.horizon_h || 2) + ' h');
      agoraS = 'recorte histórico · ' + (fr.t || '');
      prevS = hz + ' no estudo · ' + (caso.rna.event_id || caso.short || '');
    } else {
      now = d.nivel_rio_agora_cm != null ? d.nivel_rio_agora_cm : d.nivel_atual_cm;
      fore = d.nivel_previsto_cm;
      agoraS = d.nivel_rio_agora_em || d.telemetria_ultima_em || 'horário não informado';
      prevS = (d.horizonte || d.rotulo || '+2 h') + (d.modelo ? ' · ' + d.modelo : '');
    }
    function setTxt(id, text) { var el = $(id); if (el) el.textContent = text; }
    setTxt('rna-agora', fmtCm(now));
    setTxt('rna-prev', fmtCm(fore));
    setTxt('rna-bank', fmtCm(bank));
    setTxt('rna-estacao', (d.estacao || city().station));
    setTxt('rna-agora-s', agoraS);
    setTxt('rna-prev-s', prevS);
    setTxt('rna-bank-s', 'cota de pesquisa da régua · não é o nível HAND do mapa');
    setTxt('rna-estacao-s', (d.status_dados || 'status indisponível') +
      (d.consultado_em ? ' · consultado ' + d.consultado_em : ''));
    if (caso && caso.mode === 'coupled') {
      setTxt('rna-note', 'A rede já via o rio mudar neste momento. O azul do mapa é um cenário publicado — não é a régua virando mancha sozinha.');
      setTxt('rna-note-inline', 'Números da régua ≠ azul do mapa (ainda).');
    } else {
      setTxt('rna-note', 'A régua é a altura do rio. O azul do mapa é um cenário já publicado — ainda não viramos um no outro.');
      setTxt('rna-note-inline', 'Números da régua ≠ azul do mapa (ainda).');
    }

    var decide = $('rna-decide');
    if (decide) {
      var n = num(now);
      var f = num(fore);
      var b = num(bank);
      var line;
      if (n == null || f == null) {
        line = 'Sem altura do rio neste momento.';
      } else if (f > n + 5) {
        line = 'O rio sobe ' + Math.round(f - n) + ' cm em ' + hz + '.';
      } else if (f < n - 5) {
        line = 'O rio desce ' + Math.round(n - f) + ' cm em ' + hz + '.';
      } else {
        line = 'O rio fica estável em ' + hz + '.';
      }
      if (b != null && f != null) {
        line += f >= b ? ' Acima da referência.' : ' Ainda abaixo da referência.';
      }
      decide.textContent = line;
    }
    var prevLabel = document.querySelector('.rna-hours > div:nth-child(2) > span');
    if (prevLabel) prevLabel.textContent = (caso && caso.mode === 'coupled') ? hz : '+2 horas';
    renderGauge(now, fore, bank);
    renderLedger(bundle);
    setChain('rna');
  }

  function renderLevels() {
    var row = $('level-row');
    if (!row) return;
    row.innerHTML = city().levels.map(function (lv) {
      return '<button type="button" data-level="' + lv + '" aria-pressed="' +
        (Number(lv) === Number(state.level)) + '">Cenário ' + lv + ' m</button>';
    }).join('');
  }

  function renderCityButtons() {
    document.querySelectorAll('[data-city]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('data-city') === state.city));
    });
  }

  function renderCaseButtons() {
    var row = $('case-row');
    if (!row) return;
    var list = casesForCity();
    if (!list.some(function (c) { return c.id === state.caseId; })) {
      state.caseId = defaultCaseId(state.city);
      if (!list.some(function (c) { return c.id === state.caseId; })) state.caseId = 'live';
    }
    row.innerHTML = list.map(function (c) {
      return '<button type="button" data-case="' + esc(c.id) + '" aria-pressed="' +
        String(c.id === state.caseId) + '" title="' + esc(c.summary || c.one_liner || c.label) + '">' +
        esc(c.short || c.label) + '</button>';
    }).join('');
    var banner = $('case-banner');
    var caso = currentCase();
    if (banner) {
      banner.hidden = false;
      banner.textContent = (caso && (caso.one_liner || caso.summary || caso.story)) ||
        'Escolha um momento acima.';
    }
    var cap = $('story-caption');
    if (cap && caso && caso.story) cap.textContent = caso.story;
    var lead = $('lead-line');
    if (lead) {
      lead.textContent = 'Três passos: 1) o rio · 2) ruas com água · 3) caminho até o seco.';
    }
  }

  function renderSide(bundle) {
    var sc = scenario(bundle);
    var ranked = rankedCells(bundle);
    state.maxScore = Math.max(1, ranked.reduce(function (m, c) { return Math.max(m, c.score); }, 1));
    var status = $('load-status');
    if (status) {
      if (bundle.errors && bundle.errors.length) {
        status.className = 'load-status bad';
        status.textContent = 'leitura parcial · ' + bundle.errors.join(' · ');
      } else {
        status.className = 'load-status good';
        status.textContent = 'fontes carregadas · leitura de pesquisa';
      }
    }
    if ($('meta-line')) $('meta-line').textContent = 'cenário de inundação no mapa: ' + state.level + ' m (publicado)';
    if ($('stat-cells')) $('stat-cells').textContent = sc ? fmtInt(sc.cells_200m_touched) : fmtInt(ranked.length);
    if ($('stat-pop')) $('stat-pop').textContent = sc ? fmtInt(sc.population_upper_bound_whole_touched_cells) : '—';
    if ($('stat-proxy')) {
      $('stat-proxy').textContent = sc && sc.population_area_weighted_proxy != null
        ? Math.round(sc.population_area_weighted_proxy).toLocaleString('pt-BR')
        : '—';
    }
    if ($('stat-ruas')) $('stat-ruas').textContent = bundle.ruas && bundle.ruas.edges ? fmtInt(bundle.ruas.edges.length) : '—';
    if ($('stat-abrigos')) $('stat-abrigos').textContent = fmtInt(abrigosOf(bundle).length);

    var list = $('cell-list');
    if (!list) {
      renderStreetPriority(bundle);
      return;
    }
    if (!ranked.length) {
      list.innerHTML = '<li class="empty">Nenhum quadradinho 200 m intersecta este cenário publicado.</li>';
    } else {
      var shown = ranked.slice(0, 24);
      list.innerHTML = shown.map(function (c, i) {
        var width = Math.max(4, Math.round((c.score / state.maxScore) * 100));
        return '<li><button type="button" class="cell-btn" data-cell="' + esc(c.id) + '" aria-current="' +
          (c.id === state.selectedId) + '">' +
          '<span class="rank">' + String(i + 1).padStart(2, '0') + '</span>' +
          '<span class="id">' + esc(c.id) + '</span>' +
          '<span class="pop">' + fmtInt(c.pop) + ' pess.</span>' +
          '<small>sobreposição ' + fmtPct(c.overlap) + ' · atenção ' +
          Math.round(c.score).toLocaleString('pt-BR') + '</small>' +
          '<span class="bar" aria-hidden="true"><i style="width:' + width + '%"></i></span>' +
          '</button></li>';
      }).join('');
      if (ranked.length > shown.length) {
        list.innerHTML += '<li class="empty">Lista: ' + shown.length + ' de ' +
          ranked.length + ' células tocadas, as de maior atenção espacial. As demais continuam no mapa.</li>';
      }
    }

    var detail = $('cell-detail');
    var selected = ranked.find(function (c) { return c.id === state.selectedId; }) || ranked[0];
    if (selected && !state.selectedId) state.selectedId = selected.id;
    if (!selected) {
      detail.hidden = true;
      return;
    }
    detail.hidden = false;
    var next = ranked.filter(function (c) { return c.id !== selected.id; }).slice(0, 3);
    detail.innerHTML =
      '<h3>' + esc(selected.id) + '</h3>' +
      '<p><strong>' + fmtInt(selected.pop) + ' pessoas</strong> e ' + fmtInt(selected.dom) +
      ' domicílios na célula inteira (Censo 2022). Sobreposição com a mancha HAND ' +
      state.level + ' m: <strong>' + fmtPct(selected.overlap) + '</strong>.</p>' +
      '<p>Isso é limite superior de triagem: a célula inteira entra na conta, não o número de quem sairia.</p>' +
      (state.streetHits
        ? '<p>' + fmtInt(state.streetHits) + ' trechos de rua do grafo OSM tocam este quadradinho — inclusive trechos que só atravessam a célula.</p>'
        : '<p>As ruas OSM do estudo aparecem no mapa; clique no quadradinho para destacar os trechos que o cruzam.</p>') +
      (next.length
        ? '<p>Próximos quadradinhos a observar neste recorte (não é ordem de saída): ' +
          next.map(function (c) { return esc(String(c.id).replace(/^200M/, '')); }).join(', ') + '.</p>'
        : '');
    setChain('pessoas');
  }

  function applyLayersVisible() {
    applyStoryLayers();
  }

  function focusSelected(bundle) {
    if (!state.selectedId || !state._gradeLayer) return;
    state._gradeLayer.eachLayer(function (layer) {
      var id = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
      if (id === state.selectedId) {
        highlightStreets(bundle, layer.getBounds && layer.getBounds(), layer.feature && layer.feature.geometry);
      }
    });
  }

  function pulseMap() {
    var shell = document.body;
    if (!shell) return;
    shell.classList.remove('cell-pulse');
    void shell.offsetWidth;
    shell.classList.add('cell-pulse');
  }

  function updateLiveCard(bundle, cell, latlng, rotaInfo) {
    var card = $('live-card');
    var title = $('live-title');
    var copy = $('live-copy');
    var sheetTitle = $('sheet-title');
    var sheetCopy = $('sheet-copy');
    if (!card || !title || !copy) return;
    card.classList.add('is-hit');
    rotaInfo = rotaInfo || state.lastRota;
    var rotaBit = '';
    if (rotaInfo && rotaInfo.abrigo) {
      var km = rotaInfo.distM != null ? (rotaInfo.distM / 1000).toFixed(2).replace('.', ',') + ' km' : '—';
      rotaBit = ' Rota a pé até <strong>' + esc(rotaInfo.abrigo.nome) + '</strong>: ' + km +
        (rotaInfo.aguaM != null ? ' · ' + Math.round(rotaInfo.aguaM) + ' m sob a mancha do cenário de ruas.' : '.');
    } else if (bundle && !bundle.rota) {
      rotaBit = ' Grafo de rotas indisponível neste carregamento.';
    }
    var titleText;
    var copyHtml;
    if (!cell) {
      titleText = latlng
        ? 'Ponto no mapa'
        : 'Clique no mapa';
      copyHtml = (rotaBit
        ? rotaBit + ' '
        : 'Nenhum quadrado IBGE sob a mancha aqui. ') +
        'Não é ordem de saída.';
    } else {
      titleText = fmtInt(cell.pop) + ' pessoas neste quadrado';
      copyHtml =
        'Sobreposição ' + fmtPct(cell.overlap) + ' com a mancha HAND ' + state.level + ' m' +
        (state.streetHits ? ' · ' + fmtInt(state.streetHits) + ' trechos de rua' : '') +
        '.' + rotaBit +
        ' Limite da célula inteira — não é ordem de saída.';
    }
    title.textContent = titleText;
    copy.innerHTML = copyHtml;
    if (sheetTitle) sheetTitle.textContent = titleText;
    if (sheetCopy) sheetCopy.innerHTML = copyHtml;
  }

  function selectCell(bundle, id, opts) {
    opts = opts || {};
    state.selectedId = id;
    if (opts.story) goStory(opts.story, { silentPlay: true, keepSelection: true });
    setChain(opts.story === 'rotas' ? 'rotas' : 'pessoas');
    var ranked = rankedCells(bundle);
    var cell = ranked.find(function (c) { return c.id === id; }) || null;
    drawGrade(bundle);
    if (!state._gradeLayer) {
      updateLiveCard(bundle, cell, null, null);
      renderSide(bundle);
      return;
    }
    var center = null;
    state._gradeLayer.eachLayer(function (layer) {
      var lid = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
      if (lid !== id) return;
      highlightStreets(bundle, layer.getBounds && layer.getBounds(), layer.feature && layer.feature.geometry);
      if (state.clickMarker) state.map.removeLayer(state.clickMarker);
      var c = layer.getBounds && layer.getBounds().getCenter();
      center = c;
      if (c) {
        state.clickMarker = L.circleMarker(c, {
          radius: 7, color: '#0f8b46', fillColor: '#fff', fillOpacity: 1, weight: 3
        }).addTo(state.map);
      }
      if (opts.zoom && c) {
        focusOnPoint(c.lat, c.lng, { zoom: 16, maxZoom: 17 });
      }
    });
    var rotaInfo = null;
    if (center) {
      rotaInfo = drawRota(bundle, center.lat, center.lng, {
        fit: state.story === 'rotas' || opts.fitRota
      });
    }
    updateLiveCard(bundle, cell, center, rotaInfo);
    renderSide(bundle);
    pulseMap();
  }

  function nearestTouchedCell(bundle, lat, lng) {
    var ranked = rankedCells(bundle);
    if (!ranked.length || !state._gradeLayer) return null;
    var best = null;
    var bestD = 1e18;
    state._gradeLayer.eachLayer(function (layer) {
      var id = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
      var cell = ranked.find(function (c) { return c.id === id; });
      if (!cell) return;
      var geom = layer.feature && layer.feature.geometry;
      if (geom && pointInGeometry(lat, lng, geom)) {
        best = cell;
        bestD = -1;
        return;
      }
      if (bestD < 0) return;
      var c = layer.getBounds && layer.getBounds().getCenter();
      if (!c) return;
      var dy = c.lat - lat;
      var dx = (c.lng - lng) * Math.cos(lat * Math.PI / 180);
      var d = dy * dy + dx * dx;
      if (d < bestD) { bestD = d; best = cell; }
    });
    return best;
  }

  function onMapClick(e) {
    var bundle = state.cache[state.city];
    if (!bundle || !state.map) return;
    if (state.presenting) stopStoryPlay();
    var lat = e.latlng.lat;
    var lng = e.latlng.lng;
    if (state.clickMarker) state.map.removeLayer(state.clickMarker);
    state.clickMarker = L.circleMarker(e.latlng, {
      radius: 6, color: '#0f8b46', fillColor: '#fff', fillOpacity: 1, weight: 3
    }).addTo(state.map);

    /* Sempre manter o olhar no ponto clicado — nunca abrir o município. */
    focusOnPoint(lat, lng, { zoom: Math.max(state.map.getZoom(), 16), maxZoom: 18 });

    var preferRotas = state.story === 'rotas';
    if (preferRotas) {
      goStory('rotas', { silentPlay: true, keepSelection: true });
    }
    var rotaInfo = drawRota(bundle, lat, lng, { fit: false });
    if (preferRotas && rotaInfo && rotaInfo.pts) {
      focusLocalPath(rotaInfo.pts, lat, lng);
    }
    var cell = nearestTouchedCell(bundle, lat, lng);
    if (cell) {
      state.selectedId = cell.id;
      if (!preferRotas) goStory('pessoas', { silentPlay: true, keepSelection: true });
      drawGrade(bundle);
      if (state._gradeLayer) {
        state._gradeLayer.eachLayer(function (layer) {
          var lid = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
          if (lid !== cell.id) return;
          highlightStreets(bundle, layer.getBounds && layer.getBounds(), layer.feature && layer.feature.geometry);
        });
      }
      updateLiveCard(bundle, cell, e.latlng, rotaInfo);
      renderSide(bundle);
      applyStoryLayers();
      pulseMap();
      return;
    }
    updateLiveCard(bundle, null, e.latlng, rotaInfo);
    applyStoryLayers();
    pulseMap();
  }

  function storyIndex() {
    var i = STORY.indexOf(state.story);
    return i < 0 ? 0 : i;
  }

  function applyStoryLayers() {
    var idx = storyIndex();
    var cockpit = document.body.classList.contains('is-cockpit');
    var showMancha = (cockpit || idx >= STORY.indexOf('mancha')) && $('ly-mancha') && $('ly-mancha').checked;
    var showGrade = (cockpit || idx >= STORY.indexOf('grade')) && $('ly-grade') && $('ly-grade').checked;
    var showRuas = (cockpit || idx >= STORY.indexOf('ruas')) && $('ly-ruas') && $('ly-ruas').checked;
    var showFlood = $('ly-flood') ? $('ly-flood').checked : true;
    var showAbrigos = (cockpit || idx >= STORY.indexOf('ruas')) && $('ly-abrigos') && $('ly-abrigos').checked;
    var showRota = $('ly-rota') && $('ly-rota').checked && !!state.lastRota;
    function toggle(group, checked) {
      if (!state.map || !group) return;
      if (checked && !state.map.hasLayer(group)) group.addTo(state.map);
      if (!checked && state.map.hasLayer(group)) state.map.removeLayer(group);
    }
    toggle(state.layers.mancha, showMancha);
    toggle(state.layers.grade, showGrade);
    toggle(state.layers.ruas, showRuas);
    toggle(state.layers.flood, showFlood && showRuas);
    toggle(state.layers.highlight, showRuas && !!state.selectedId && state.story !== 'rotas');
    toggle(state.layers.abrigos, showAbrigos);
    toggle(state.layers.rota, showRota);
    var showMarks = $('ly-marks') ? $('ly-marks').checked : true;
    var casoMarks = currentCase();
    toggle(state.layers.marks, showMarks && !!(casoMarks.marks && casoMarks.marks.length));
  }

  function setPresenting(on) {
    state.presenting = !!on;
    document.body.classList.toggle('is-presenting', state.presenting);
  }

  function updateStoryCaption(step) {
    var el = $('story-caption');
    if (!el) return;
    el.textContent = STORY_CAPTION[step] || '';
    el.setAttribute('data-step', step || '');
  }

  function goStory(step, opts) {
    opts = opts || {};
    if (STORY.indexOf(step) < 0) return;
    state.story = step;
    document.querySelectorAll('[data-story]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('data-story') === step));
    });
    updateStoryCaption(step);
    document.body.classList.toggle('story-rna', step === 'rna');
    /* Abrir números só no passo da régua; senão deixar fechado. */
    var dataWrap = $('panel-data-wrap');
    if (dataWrap) dataWrap.open = step === 'rna';
    var chainMap = {
      territorio: 'rna', rna: 'rna', mancha: 'mancha', grade: 'grade',
      ruas: 'ruas', pessoas: 'pessoas', rotas: 'rotas'
    };
    setChain(chainMap[step] || 'rna');
    applyStoryLayers();
    var bundle = state.cache[state.city];
    if (!bundle) return;
    /* Sempre o centro urbano — nunca o envelope de todas as células do município. */
    if (step === 'territorio' || step === 'mancha' || step === 'grade' || step === 'ruas') {
      focusCenter({ zoom: step === 'territorio' ? focusOf().zoom : Math.max(focusOf().zoom, 15) });
    }
    if (step === 'rna') {
      setChain('rna');
      focusCenter({ zoom: focusOf().zoom });
      pulseMap();
    }
    if (step === 'pessoas') {
      var ranked = rankedCells(bundle);
      if (ranked[0] && !opts.keepSelection) {
        selectCell(bundle, state.selectedId || ranked[0].id, { zoom: true });
      } else {
        focusCenter({ zoom: 15 });
      }
    }
    if (step === 'rotas') {
      var rankedR = rankedCells(bundle);
      var pick = rankedR.find(function (c) { return c.id === state.selectedId; }) || rankedR[0];
      if (pick && !opts.keepSelection) {
        selectCell(bundle, pick.id, { zoom: true, fitRota: true, story: null });
        setChain('rotas');
      } else if (state.lastRota) {
        applyStoryLayers();
        setChain('rotas');
      } else {
        focusCenter({ zoom: 15 });
      }
    }
    if (!opts.silentPlay && state.storyTimer) stopStoryPlay();
  }

  function stopStoryPlay() {
    if (state.storyTimer) {
      window.clearTimeout(state.storyTimer);
      state.storyTimer = null;
    }
    setPresenting(false);
    var play = $('story-play');
    if (play) {
      play.setAttribute('aria-pressed', 'false');
      play.textContent = '▶ Contar a história';
    }
  }

  function startStoryPlay() {
    stopStoryPlay();
    setPresenting(true);
    var play = $('story-play');
    if (play) {
      play.setAttribute('aria-pressed', 'true');
      play.textContent = '❚❚ Pausar história';
    }
    var i = 0;
    function tick() {
      if (!state.presenting) return;
      goStory(STORY[i], { silentPlay: true });
      i += 1;
      if (i >= STORY.length) {
        state.storyTimer = window.setTimeout(function () {
          stopStoryPlay();
          goStory('rotas', { silentPlay: true });
        }, STORY_DWELL.rotas || 4000);
        return;
      }
      var dwell = STORY_DWELL[STORY[i - 1]] || 3200;
      state.storyTimer = window.setTimeout(tick, dwell);
    }
    tick();
  }

  function drawAll(bundle) {
    ensureMap();
    state.streetHits = 0;
    state.selectedStreet = null;
    if (state.layers.highlight) state.layers.highlight.clearLayers();
    clearRota();
    drawMancha(bundle);
    drawMarks();
    drawStreets(bundle);
    drawGrade(bundle);
    drawAbrigos(bundle);
    renderStreetPriority(bundle);
    applyStoryLayers();
    setChain('rotas');
    focusCenter({ animate: false });
    window.setTimeout(function () {
      if (state.map) state.map.invalidateSize();
    }, 80);
    goStory(state.story || 'rotas', { silentPlay: true, keepSelection: true });
    /* No cockpit: já mostra a 1ª rua prioritária com rota até o seco. */
    if (document.body.classList.contains('is-cockpit') && state.streetPriority && state.streetPriority[0]) {
      selectStreet(bundle, state.streetPriority[0].id);
    } else if (state.story === 'pessoas' || state.story === 'rotas') {
      var ranked = rankedCells(bundle);
      if (ranked[0]) {
        selectCell(bundle, state.selectedId || ranked[0].id, {
          zoom: true,
          fitRota: state.story === 'rotas'
        });
      }
    }
  }

  function render(bundle) {
    document.title = 'PREVINE · estudo de caso · ' + city().label;
    $('city-label').textContent = city().label;
    renderCityButtons();
    renderCaseButtons();
    renderLevels();
    renderRna(bundle);
    drawAll(bundle);
    renderSide(bundle);
    var catalogs = (bundle.replay && bundle.replay.municipality_catalogs) || {};
    var catKey = state.city === 'mucum' ? 'mucum' : 'santa_tereza';
    var cat = catalogs[catKey] || catalogs[city().label] || null;
    var eventCount = cat && (cat.event_count_catalog || cat.event_count || cat.events_count || (cat.events && cat.events.length));
    var cases = (bundle.replay && bundle.replay.replay_cases) || [];
    var cityCases = cases.filter(function (c) {
      var m = String((c && c.municipality) || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      return state.city === 'mucum' ? m.indexOf('muc') >= 0 : m.indexOf('santa') >= 0 || m.indexOf('tereza') >= 0;
    });
    var eventNote = $('event-note');
    if (eventNote) {
      if (state.city === 'mucum' && cityCases[0]) {
        eventNote.textContent =
          'Muçum: ' + fmtInt(eventCount || 32) + ' eventos no catálogo · replay publicado ' +
          (cityCases[0].event_id || '') +
          ' (pico ~' + fmtCm(cityCases[0].peak_observed_cm) + '). A mancha no mapa ainda é cenário HAND fixo — não o pico da régua convertido.';
      } else if (eventCount) {
        eventNote.textContent =
          city().label + ': ' + fmtInt(eventCount) +
          ' eventos no catálogo de análise da RNA. A mancha no mapa é cenário HAND publicado; conversão régua ↔ HAND pendente.';
      } else {
        eventNote.textContent =
          'Catálogos de eventos RNA e manchas HAND publicados alimentam o estudo de caso. Conversão régua ↔ HAND continua pendente.';
      }
    }
    var rotaNote = $('rota-note');
    if (rotaNote && bundle.rota && bundle.rota.meta) {
      var rm = bundle.rota.meta;
      var rotulo = (rm.nivel && rm.nivel.rotulo) ||
        (rm.nivel_projeto_m != null ? 'cenário de projeto ' + rm.nivel_projeto_m + ' m' : 'cenário de ruas');
      rotaNote.textContent = 'Grafo de rotas: ' + rotulo + ' · ' +
        fmtInt((bundle.rota.nos || []).length) + ' nós · ' +
        fmtInt((bundle.rota.abrigos || []).length) + ' abrigos. Clique no mapa no passo Rotas.';
    } else if (rotaNote) {
      rotaNote.textContent = bundle.errors && bundle.errors.some(function (e) { return e.indexOf('rota:') === 0; })
        ? 'Grafo de rotas não carregou neste município.'
        : 'Grafo de rotas carrega com o município.';
    }

    var extra = $('city-links');
    extra.innerHTML =
      '<a href="' + city().rotaCenario + '">Página irmã: rota de fuga (mesmo grafo)</a>' +
      '<a href="' + city().floodMap + '">Mapa de inundação (satélite + HAND)</a>' +
      '<a href="' + city().ficha + '">Ficha do município</a>' +
      '<a href="' + city().painel + '">Painel de ruas (protótipo)</a>' +
      (city().mesa ? '<a href="' + city().mesa + '">Mesa V002</a>' : '') +
      '<a href="' + city().impacto + '">Mapa de impacto</a>' +
      '<a href="sala-integrada-eventos.html">Sala de replay histórico</a>';
    renderLedger(bundle);
    var casoCap = currentCase();
    if (casoCap && casoCap.story) {
      var capEl = $('story-caption');
      if (capEl) capEl.textContent = casoCap.story;
    } else {
      updateStoryCaption(state.story || 'territorio');
    }
  }

  function bootCity() {
    var gen = ++state.loadGen;
    $('load-status').textContent = 'carregando ' + city().label + '…';
    $('load-status').className = 'load-status';
    return loadCityBundle().then(function (bundle) {
      if (gen !== state.loadGen) return;
      if (!city().levels.some(function (lv) { return Number(lv) === Number(state.level); })) {
        state.level = city().defaultLevel;
      }
      render(bundle);
    }).catch(function (err) {
      if (gen !== state.loadGen) return;
      $('load-status').className = 'load-status bad';
      $('load-status').textContent = 'falha ao carregar o estudo · ' + (err.message || err);
      console.error(err);
    });
  }

  function onCity(id) {
    if (id === state.city) return;
    state.city = id;
    state.level = city().defaultLevel;
    state.selectedId = null;
    /* Sempre abre a história mais clara da cidade (Muçum → Hotel; ST → set/2023). */
    state.caseId = defaultCaseId(id);
    var caso = currentCase();
    if (caso && caso.mode === 'coupled' && caso.hand_m != null) state.level = caso.hand_m;
    renderCityButtons();
    setUrl();
    bootCity();
  }

  function onCase(id) {
    if (!id || id === state.caseId) return;
    state.caseId = id;
    state.selectedId = null;
    var caso = currentCase();
    if (caso && caso.mode === 'coupled' && caso.hand_m != null) {
      state.level = caso.hand_m;
    } else {
      state.level = city().defaultLevel;
    }
    setUrl();
    var bundle = state.cache[state.city];
    if (!bundle) {
      bootCity();
      return;
    }
    render(bundle);
    if (caso && caso.mode === 'coupled' && caso.focus_mark && caso.marks) {
      var focus = null;
      for (var i = 0; i < caso.marks.length; i++) {
        if (caso.marks[i].name === caso.focus_mark) { focus = caso.marks[i]; break; }
      }
      if (focus && state.map) {
        state.map.setView([focus.lat, focus.lon], Math.max(state.map.getZoom(), 16), { animate: true });
      }
    }
  }

  document.querySelectorAll('[data-city]').forEach(function (btn) {
    btn.addEventListener('click', function () { onCity(btn.getAttribute('data-city')); });
  });
  if ($('btn-recenter')) {
    $('btn-recenter').addEventListener('click', function () {
      stopStoryPlay();
      focusCenter({ zoom: focusOf().zoom });
    });
  }
  document.querySelectorAll('[data-basemap]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var mode = btn.getAttribute('data-basemap');
      if (!mode || mode === state.basemap) return;
      applyBasemap(mode);
      var bundle = state.cache[state.city];
      if (bundle) {
        drawStreets(bundle);
        drawGrade(bundle);
        focusSelected(bundle);
        applyStoryLayers();
      }
    });
  });
  document.querySelectorAll('[data-story]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      stopStoryPlay();
      goStory(btn.getAttribute('data-story'));
    });
  });
  $('story-prev').addEventListener('click', function () {
    stopStoryPlay();
    var i = Math.max(0, storyIndex() - 1);
    goStory(STORY[i]);
  });
  $('story-next').addEventListener('click', function () {
    stopStoryPlay();
    var i = Math.min(STORY.length - 1, storyIndex() + 1);
    goStory(STORY[i]);
  });
  $('story-play').addEventListener('click', function () {
    if (state.storyTimer) stopStoryPlay();
    else startStoryPlay();
  });
  $('level-row').addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-level]');
    if (!btn) return;
    state.level = Number(btn.getAttribute('data-level'));
    state.selectedId = null;
    setChain('mancha');
    goStory('mancha', { silentPlay: true });
    var bundle = state.cache[state.city];
    if (!bundle || (bundle.errors && bundle.errors.length)) {
      bootCity();
      return;
    }
    render(bundle);
  });
  if ($('street-priority')) {
    $('street-priority').addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-street]');
      if (!btn) return;
      ev.preventDefault();
      ev.stopPropagation();
      var bundle = state.cache[state.city];
      if (!bundle) return;
      selectStreet(bundle, btn.getAttribute('data-street'));
    });
  }
  if ($('cell-list')) {
    $('cell-list').addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-cell]');
      if (!btn) return;
      var bundle = state.cache[state.city];
      if (!bundle) return;
      selectCell(bundle, btn.getAttribute('data-cell'), { zoom: true, story: 'pessoas' });
    });
  }
  ['ly-mancha', 'ly-grade', 'ly-ruas', 'ly-flood', 'ly-abrigos', 'ly-rota', 'ly-marks'].forEach(function (id) {
    if ($(id)) $(id).addEventListener('change', applyLayersVisible);
  });
  if ($('btn-recenter')) {
    $('btn-recenter').addEventListener('click', function () {
      stopStoryPlay();
      focusCenter({ zoom: focusOf().zoom });
    });
  }
  if ($('case-row')) {
    $('case-row').addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-case]');
      if (!btn) return;
      onCase(btn.getAttribute('data-case'));
    });
  }
  window.addEventListener('hashchange', function () {
    /* Sem cidade explícita no hash/query, não forçar Santa Tereza
       (hash vazio durante scroll/navegação não pode trocar o município). */
    var next = parseCity({ allowDefault: false });
    if (!next || next === state.city) return;
    onCity(next);
  });

  state.city = parseCity({ allowDefault: true });
  state.caseId = parseCaseId();
  state.level = city().defaultLevel;
  loadCasesDoc().then(function () {
    var caso = currentCase();
    state.caseId = caso.id || 'live';
    if (caso && caso.mode === 'coupled' && caso.hand_m != null) state.level = caso.hand_m;
    setUrl();
    bootCity();
  });
})();
