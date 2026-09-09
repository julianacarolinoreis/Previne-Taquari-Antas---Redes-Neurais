/* Estudo de caso territorial: RNA + mancha HAND + grade IBGE 200 m + ruas + pessoas.
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
      replayKey: 'santa_tereza',
      levels: [15],
      defaultLevel: 15,
      bankfullFallback: 400,
      floodMap: '../santa_tereza_previsao_inundacao.html',
      ficha: '../pesquisa_status.html',
      painel: 'santa-tereza-painel-evacuacao.html',
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
      replayKey: 'mucum',
      levels: [18, 20, 25],
      defaultLevel: 18,
      bankfullFallback: 500,
      floodMap: '../mucum_previsao_inundacao.html',
      ficha: '../pesquisa_status_mucum.html',
      painel: 'mucum-painel-evacuacao.html',
      mesa: null,
      impacto: 'mucum-mapa-impacto.html',
      plan: '../assets/data/mucum_contingencia_202607.json'
    }
  };

  var REPLAY_URL = '../assets/data/research_event_replay_latest.json';

  var state = {
    city: 'santa_tereza',
    level: 15,
    selectedId: null,
    cache: {},
    map: null,
    layers: {
      mancha: null,
      grade: null,
      ruas: null,
      abrigos: null,
      highlight: null
    },
    canvas: null
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
  function fmtCm(v) {
    var n = num(v);
    if (n == null) return '—';
    if (Math.abs(n) >= 100) return (n / 100).toFixed(2).replace('.', ',') + ' m';
    return Math.round(n) + ' cm';
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

  function parseCity() {
    var q = new URLSearchParams(location.search).get('cidade') || '';
    var h = (location.hash || '').replace('#', '');
    var raw = (q || h).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    if (raw.indexOf('muc') >= 0) return 'mucum';
    if (raw.indexOf('santa') >= 0 || raw.indexOf('tereza') >= 0) return 'santa_tereza';
    return 'santa_tereza';
  }

  function setUrl() {
    var slug = state.city === 'mucum' ? 'mucum' : 'santa-tereza';
    var url = new URL(location.href);
    url.searchParams.set('cidade', slug);
    url.hash = slug;
    history.replaceState(null, '', url.pathname + url.search + url.hash);
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
    if (state.cache[key] && state.cache[key].ready) return Promise.resolve(state.cache[key]);
    var jobs = {
      rna: fetchJson(c.rna),
      grade: fetchJson(c.grade),
      ruas: fetchJson(c.ruas),
      mancha: fetchJson(c.mancha),
      replay: state.cache._replay
        ? Promise.resolve(state.cache._replay)
        : fetchJson(REPLAY_URL)
    };
    if (c.plan) jobs.plan = fetchJson(c.plan);
    return Promise.all(Object.keys(jobs).map(function (k) {
      return jobs[k].then(function (v) { return [k, v, null]; }).catch(function (err) {
        return [k, null, err];
      });
    })).then(function (pairs) {
      var bundle = { ready: true, errors: [] };
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

  function colorFor(overlap, selected) {
    if (selected) return '#155c47';
    if (!(overlap > 0)) return '#c5ccc4';
    if (overlap >= 80) return '#ef7a68';
    if (overlap >= 40) return '#f5c76b';
    return '#8dbf74';
  }

  function ensureMap() {
    if (state.map) return state.map;
    state.canvas = L.canvas({ padding: 0.5 });
    state.map = L.map('map', {
      zoomControl: true,
      attributionControl: true,
      minZoom: 11,
      maxZoom: 18
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap',
      maxZoom: 19
    }).addTo(state.map);
    state.layers.mancha = L.layerGroup().addTo(state.map);
    state.layers.grade = L.layerGroup().addTo(state.map);
    state.layers.ruas = L.layerGroup().addTo(state.map);
    state.layers.abrigos = L.layerGroup().addTo(state.map);
    state.layers.highlight = L.layerGroup().addTo(state.map);
    return state.map;
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
        color: '#176ca8',
        weight: 1.4,
        fillColor: '#176ca8',
        fillOpacity: 0.28,
        opacity: 0.9
      },
      interactive: false
    }).addTo(state.layers.mancha);
  }

  function drawGrade(bundle) {
    state.layers.grade.clearLayers();
    var ranked = rankedCells(bundle);
    var byId = Object.create(null);
    ranked.forEach(function (c) { byId[c.id] = c; });
    var geo = L.geoJSON(bundle.grade, {
      style: function (feature) {
        var id = feature.properties && feature.properties.id_grade;
        var cell = byId[id];
        var selected = id === state.selectedId;
        return {
          color: selected ? '#0c2a22' : '#5d6b62',
          weight: selected ? 2.4 : 0.8,
          fillColor: colorFor(cell ? cell.overlap : 0, selected),
          fillOpacity: cell ? 0.55 : 0.12
        };
      },
      onEachFeature: function (feature, layer) {
        var id = feature.properties && feature.properties.id_grade;
        layer.on('click', function () {
          state.selectedId = id;
          var bounds = layer.getBounds && layer.getBounds();
          drawGrade(bundle);
          if (bounds) {
            highlightStreets(bundle, bounds);
            state.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 16 });
          }
          renderSide(bundle);
        });
      }
    });
    geo.addTo(state.layers.grade);
    state._gradeLayer = geo;
    if (!state._fitted) {
      try {
        state.map.fitBounds(geo.getBounds(), { padding: [24, 24] });
        state._fitted = true;
      } catch (e) { /* bounds vazios */ }
    }
  }

  function drawStreets(bundle) {
    state.layers.ruas.clearLayers();
    var ruas = bundle.ruas;
    if (!ruas || !Array.isArray(ruas.nos) || !Array.isArray(ruas.edges)) return;
    var nos = ruas.nos;
    var coords = [];
    ruas.edges.forEach(function (e) {
      var a = nos[e[0]];
      var c = nos[e[1]];
      if (!a || !c) return;
      coords.push([[a[1], a[0]], [c[1], c[0]]]);
    });
    L.geoJSON({
      type: 'Feature',
      geometry: { type: 'MultiLineString', coordinates: coords }
    }, {
      style: { color: '#0c2a22', weight: 1.35, opacity: 0.55 },
      interactive: false,
      renderer: state.canvas
    }).addTo(state.layers.ruas);
  }

  function highlightStreets(bundle, bounds) {
    state.layers.highlight.clearLayers();
    if (!bounds || !bundle.ruas) return;
    var nos = bundle.ruas.nos;
    var pad = 0.00015;
    var south = bounds.getSouth() - pad;
    var north = bounds.getNorth() + pad;
    var west = bounds.getWest() - pad;
    var east = bounds.getEast() + pad;
    function inside(pt) {
      return pt && pt[0] >= south && pt[0] <= north && pt[1] >= west && pt[1] <= east;
    }
    var segs = [];
    bundle.ruas.edges.forEach(function (e) {
      var a = nos[e[0]];
      var c = nos[e[1]];
      if (inside(a) || inside(c)) segs.push([a, c]);
    });
    if (!segs.length) return;
    L.polyline(segs, {
      color: '#0c2a22',
      weight: 3.2,
      opacity: 0.95,
      interactive: false
    }).addTo(state.layers.highlight);
    state._streetHits = segs.length;
  }

  function abrigosOf(bundle) {
    var list = [];
    if (bundle.plan && Array.isArray(bundle.plan.abrigos)) {
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

  function renderRna(bundle) {
    var d = bundle.rna || {};
    var now = d.nivel_rio_agora_cm != null ? d.nivel_rio_agora_cm : d.nivel_atual_cm;
    var fore = d.nivel_previsto_cm;
    var bank = d.bankfull_cm != null ? d.bankfull_cm : city().bankfullFallback;
    $('rna-agora').textContent = fmtCm(now);
    $('rna-prev').textContent = fmtCm(fore);
    $('rna-bank').textContent = fmtCm(bank);
    $('rna-estacao').textContent = (d.estacao || city().station) + ' · ' + (d.status_dados || 'status indisponível');
    $('rna-agora-s').textContent = d.nivel_rio_agora_em || d.telemetria_ultima_em || 'horário não informado';
    $('rna-prev-s').textContent = (d.horizonte || d.rotulo || '+2 h') + (d.modelo ? ' · ' + d.modelo : '');
    $('rna-bank-s').textContent = 'cota de pesquisa da régua · não é o nível HAND do mapa';
    $('rna-estacao-s').textContent = d.consultado_em ? 'consultado ' + d.consultado_em : (d.gerado_em || '');
    var note = $('rna-note');
    note.textContent = 'A RNA lê a régua em centímetros. O mapa mostra um cenário HAND publicado (' +
      state.level + ' m). A conversão régua ↔ HAND/MDT continua pendente — o nível previsto não escolhe sozinho o quadradinho.';
  }

  function renderLevels() {
    var row = $('level-row');
    row.innerHTML = city().levels.map(function (lv) {
      return '<button type="button" data-level="' + lv + '" aria-pressed="' + (Number(lv) === Number(state.level)) + '">HAND ' + lv + ' m</button>';
    }).join('');
  }

  function renderCityButtons() {
    document.querySelectorAll('[data-city]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('data-city') === state.city));
    });
  }

  function renderSide(bundle) {
    var sc = scenario(bundle);
    var ranked = rankedCells(bundle);
    var status = $('load-status');
    if (bundle.errors && bundle.errors.length) {
      status.className = 'load-status bad';
      status.textContent = 'leitura parcial · ' + bundle.errors.join(' · ');
    } else {
      status.className = 'load-status good';
      status.textContent = 'fontes carregadas · leitura de pesquisa';
    }
    $('meta-line').textContent = city().label + ' · IBGE ' + city().ibge +
      ' · cenário HAND ' + state.level + ' m · grade 200 m';
    $('stat-cells').textContent = sc ? fmtInt(sc.cells_200m_touched) : fmtInt(ranked.length);
    $('stat-pop').textContent = sc ? fmtInt(sc.population_upper_bound_whole_touched_cells) : '—';
    $('stat-proxy').textContent = sc && sc.population_area_weighted_proxy != null
      ? Math.round(sc.population_area_weighted_proxy).toLocaleString('pt-BR')
      : '—';
    $('stat-ruas').textContent = bundle.ruas && bundle.ruas.edges ? fmtInt(bundle.ruas.edges.length) : '—';
    $('stat-abrigos').textContent = fmtInt(abrigosOf(bundle).length);

    var list = $('cell-list');
    if (!ranked.length) {
      list.innerHTML = '<li class="empty">Nenhum quadradinho 200 m intersecta este cenário publicado.</li>';
    } else {
      list.innerHTML = ranked.slice(0, 24).map(function (c, i) {
        return '<li><button type="button" class="cell-btn" data-cell="' + esc(c.id) + '" aria-current="' +
          (c.id === state.selectedId) + '">' +
          '<span class="rank">' + String(i + 1).padStart(2, '0') + '</span>' +
          '<span class="id">' + esc(c.id) + '</span>' +
          '<span class="pop">' + fmtInt(c.pop) + ' pess.</span>' +
          '<small>sobreposição ' + fmtPct(c.overlap) + ' · atenção de pesquisa ' +
          Math.round(c.score).toLocaleString('pt-BR') + '</small></button></li>';
      }).join('');
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
      (state._streetHits
        ? '<p>' + fmtInt(state._streetHits) + ' trechos de rua do grafo OSM tocam este quadradinho.</p>'
        : '<p>As ruas OSM do estudo aparecem no mapa; clique no quadradinho para destacar os trechos que o cruzam.</p>') +
      (next.length
        ? '<p>Próximos quadradinhos a observar neste recorte (não é ordem de saída): ' +
          next.map(function (c) { return esc(c.id.replace(/^200M/, '')); }).join(', ') + '.</p>'
        : '');
  }

  function applyLayersVisible() {
    function toggle(group, checked) {
      if (!state.map || !group) return;
      if (checked && !state.map.hasLayer(group)) group.addTo(state.map);
      if (!checked && state.map.hasLayer(group)) state.map.removeLayer(group);
    }
    toggle(state.layers.mancha, $('ly-mancha').checked);
    toggle(state.layers.grade, $('ly-grade').checked);
    toggle(state.layers.ruas, $('ly-ruas').checked);
    toggle(state.layers.abrigos, $('ly-abrigos').checked);
  }

  function focusSelected(bundle) {
    if (!state.selectedId || !state._gradeLayer) return;
    state._gradeLayer.eachLayer(function (layer) {
      var id = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
      if (id === state.selectedId && layer.getBounds) highlightStreets(bundle, layer.getBounds());
    });
  }

  function drawAll(bundle) {
    ensureMap();
    var ranked = rankedCells(bundle);
    if (!state.selectedId && ranked[0]) state.selectedId = ranked[0].id;
    state._fitted = false;
    state._streetHits = 0;
    if (state.layers.highlight) state.layers.highlight.clearLayers();
    drawMancha(bundle);
    drawStreets(bundle);
    drawGrade(bundle);
    drawAbrigos(bundle);
    focusSelected(bundle);
    applyLayersVisible();
    window.setTimeout(function () { state.map.invalidateSize(); }, 60);
  }

  function render(bundle) {
    document.title = 'PREVINE · estudo de caso · ' + city().label;
    $('city-label').textContent = city().label;
    renderCityButtons();
    renderLevels();
    renderRna(bundle);
    drawAll(bundle);
    renderSide(bundle);
    var extra = $('city-links');
    extra.innerHTML =
      '<a href="' + city().floodMap + '">Mapa de inundação (HAND ao vivo)</a>' +
      '<a href="' + city().ficha + '">Ficha do município</a>' +
      '<a href="' + city().painel + '">Painel de ruas (protótipo)</a>' +
      (city().mesa ? '<a href="' + city().mesa + '">Mesa V002</a>' : '') +
      '<a href="' + city().impacto + '">Mapa de impacto</a>' +
      '<a href="sala-integrada-eventos.html">Sala de replay histórico</a>';
  }

  function bootCity() {
    $('load-status').textContent = 'carregando ' + city().label + '…';
    $('load-status').className = 'load-status';
    return loadCityBundle().then(function (bundle) {
      if (!city().levels.some(function (lv) { return Number(lv) === Number(state.level); })) {
        state.level = city().defaultLevel;
      }
      render(bundle);
    }).catch(function (err) {
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
    setUrl();
    bootCity();
  }

  document.querySelectorAll('[data-city]').forEach(function (btn) {
    btn.addEventListener('click', function () { onCity(btn.getAttribute('data-city')); });
  });
  $('level-row').addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-level]');
    if (!btn) return;
    state.level = Number(btn.getAttribute('data-level'));
    state.selectedId = null;
    var bundle = state.cache[state.city];
    if (bundle) render(bundle);
  });
  $('cell-list').addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-cell]');
    if (!btn) return;
    state.selectedId = btn.getAttribute('data-cell');
    var bundle = state.cache[state.city];
    if (!bundle || !state._gradeLayer) return;
    renderSide(bundle);
    drawGrade(bundle);
    state._gradeLayer.eachLayer(function (layer) {
      var id = layer.feature && layer.feature.properties && layer.feature.properties.id_grade;
      if (id === state.selectedId && layer.getBounds) {
        highlightStreets(bundle, layer.getBounds());
        state.map.fitBounds(layer.getBounds(), { padding: [28, 28], maxZoom: 16 });
      }
    });
    renderSide(bundle);
  });
  ['ly-mancha', 'ly-grade', 'ly-ruas', 'ly-abrigos'].forEach(function (id) {
    $(id).addEventListener('change', applyLayersVisible);
  });
  window.addEventListener('hashchange', function () {
    var next = parseCity();
    if (next !== state.city) onCity(next);
  });

  state.city = parseCity();
  state.level = city().defaultLevel;
  setUrl();
  bootCity();
})();
