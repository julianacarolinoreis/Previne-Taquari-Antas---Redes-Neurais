/* Fila de evacuação na previsão ao vivo — grade IBGE + rotas-exemplo. */
(function (global) {
  const CORES = {
    seguro: '#1b7a5a', atencao: '#e3b100', urgente: '#e8730c',
    alagada: '#1e5fbf', alto: '#7a8a84', isolada: '#7a1f1f', fuga: '#c0392b'
  };
  const LAB = {
    seguro: 'ainda seguro', atencao: 'sair — RNA alcança', urgente: 'SAIR AGORA',
    alagada: 'já alagou', alto: 'ponto alto', isolada: 'ROTA CORTADA', fuga: 'só pela água'
  };
  const NF = new Intl.NumberFormat('pt-BR');

  let cfg = null, data = null, layers = null, cellRoute = null;

  function $(id) { return document.getElementById(id); }

  function handCm(cm) {
    const z = (data && data.meta && data.meta.zero_regua_m != null)
      ? data.meta.zero_regua_m
      : (cfg && cfg.bankfullM ? cfg.bankfullM() : 5);
    if (cm == null || !Number.isFinite(Number(cm))) return 0;
    return Math.max(0, Number(cm) / 100 - z);
  }

  function clsCota(cota, hNow, hRna) {
    if (cota == null) return 'alto';
    if (cota <= hNow + 0.05) return 'alagada';
    if (cota > hRna + 0.05) return 'seguro';
    return (cota - hNow) < 1.2 ? 'urgente' : 'atencao';
  }

  function rotaEm(arr, h) {
    if (!arr || !arr.length) return null;
    let b = arr[0];
    for (const r of arr) if (r.hand <= h + 0.05) b = r;
    return b;
  }

  function pegaRota(c, hRna) {
    const seca = rotaEm(c.rotas_seca, hRna), fuga = rotaEm(c.rotas_fuga, hRna);
    if (seca && !seca.isolada) return Object.assign({ kind: 'seca' }, seca);
    if (fuga && !fuga.isolada) return Object.assign({ kind: 'fuga' }, fuga);
    if (c.rota && c.rota.length > 1) return { kind: 'seca', pts: c.rota, dist_m: c.dist_m, abrigo: c.abrigo, agua_m: 0, isolada: false };
    return { kind: 'isolada', isolada: true, pts: [[c.lat, c.lon]], dist_m: null, abrigo: c.abrigo, agua_m: 0 };
  }

  function txtCasa(c, k, rr, vel) {
    if (k === 'seguro' || k === 'alto') return 'rota ainda não necessária';
    if (rr.kind === 'isolada') return 'rota cortada — não chega a pé ao abrigo';
    const min = Math.round((rr.dist_m || 0) / vel / 60);
    const dest = (rr.abrigo || c.abrigo || '').split(' ').slice(0, 3).join(' ');
    if (rr.kind === 'fuga') {
      return 'último corredor · ' + min + ' min → ' + dest + (rr.agua_m > 20 ? (' · ' + Math.round(rr.agua_m) + ' m na água') : '');
    }
    const extra = (c.dist_m && rr.dist_m > c.dist_m * 1.15)
      ? (' · desvio +' + Math.round((rr.dist_m - c.dist_m) / vel / 60) + ' min') : '';
    return min + ' min → ' + dest + extra;
  }

  function load() {
    if (!cfg || !cfg.url) return Promise.resolve();
    return fetch(cfg.url + '?cb=' + Date.now()).then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(d => { data = d; }).catch(e => {
      console.error('fila de evacuação', e);
      data = null;
    });
  }

  function ensureLayers() {
    const map = cfg && cfg.getMap && cfg.getMap();
    if (!map || !data || layers) return map;
    if (!map.getPane('evacCellPane')) {
      map.createPane('evacCellPane').style.zIndex = 450;
      map.createPane('evacRoutePane').style.zIndex = 455;
      map.createPane('evacDotPane').style.zIndex = 460;
    }
    layers = { cells: [], orig: {}, rotas: {}, dots: {} };
    layers.abrigos = L.layerGroup();
    (data.abrigos || []).forEach(a => {
      L.circleMarker([a.lat, a.lon], {
        pane: 'evacDotPane', radius: 6, color: '#fff', weight: 2,
        fillColor: '#0f6b4a', fillOpacity: 1
      }).addTo(layers.abrigos).bindTooltip((a.nome || '').split(' ').slice(0, 3).join(' '), { direction: 'top' });
    });
    layers.cellGroup = L.layerGroup().addTo(map);
    (data.cells || []).forEach((c, idx) => {
      const r = Math.max(4, Math.min(14, 3 + Math.sqrt(c.pop || 1)));
      const mk = L.circleMarker([c.lat, c.lon], {
        pane: 'evacCellPane', radius: r, color: '#fff', weight: 1,
        fillColor: CORES.alto, fillOpacity: 0.85, opacity: 0
      }).addTo(layers.cellGroup);
      mk.on('click', () => showCellRoute(c));
      mk.bindTooltip(NF.format(c.pop) + ' pessoas' + (c.cota != null ? (' · alaga em HAND ' + c.cota + ' m') : ' · ponto alto'), { direction: 'top' });
      layers.cells[idx] = mk;
    });
    (data.casas || []).forEach(c => {
      layers.orig[c.id] = L.polyline(c.rota || [[c.lat, c.lon]], {
        pane: 'evacRoutePane', color: '#ffffff', weight: 3, opacity: 0, dashArray: '7 8'
      }).addTo(map);
      layers.rotas[c.id] = L.polyline(c.rota || [[c.lat, c.lon]], {
        pane: 'evacRoutePane', color: '#0f8b46', weight: 5, opacity: 0
      }).addTo(map);
      const ic = L.divIcon({ className: '', html: '<div class="ev-dot" style="background:#1b7a5a"></div>', iconSize: [16, 16], iconAnchor: [8, 8] });
      layers.dots[c.id] = L.marker([c.lat, c.lon], { pane: 'evacDotPane', icon: ic, zIndexOffset: 800 })
        .addTo(map).bindTooltip(c.nome, { direction: 'right', offset: [10, 0] });
    });
    return map;
  }

  function showCellRoute(c) {
    const map = cfg.getMap();
    if (!map || !c.rota || c.rota.length < 2) return;
    if (cellRoute) map.removeLayer(cellRoute);
    cellRoute = L.polyline(c.rota, {
      pane: 'evacRoutePane', color: '#0f8b46', weight: 5, opacity: 0.95
    }).addTo(map);
    const dest = (c.abrigo || 'abrigo').split(' ').slice(0, 3).join(' ');
    cellRoute.bindPopup(NF.format(c.pop) + ' pessoas · ' + (c.min_idoso || '?') + ' min → ' + dest).openPopup();
  }

  function hideOverlays(map) {
    if (!layers) return;
    layers.cells.forEach(mk => mk.setStyle({ opacity: 0, fillOpacity: 0 }));
    Object.keys(layers.orig).forEach(id => layers.orig[id].setStyle({ opacity: 0 }));
    Object.keys(layers.rotas).forEach(id => layers.rotas[id].setStyle({ opacity: 0 }));
    Object.keys(layers.dots).forEach(id => layers.dots[id].setOpacity(0));
    if (layers.abrigos && map.hasLayer(layers.abrigos)) map.removeLayer(layers.abrigos);
    if (cellRoute) { map.removeLayer(cellRoute); cellRoute = null; }
  }

  function render(nowCm, foreCm) {
    const box = $('fila-list');
    const sub = $('fila-sub');
    const tot = $('fila-totais');
    if (!box) return;
    if (!data || !data.cells || !data.cells.length) {
      box.innerHTML = '<div class="fila-bl">Fila de evacuação ainda não carregou.</div>';
      if (tot) tot.innerHTML = '';
      return;
    }
    const vel = (data.meta && data.meta.vel_idoso_ms) || 0.9;
    const hNow = handCm(nowCm), hRna = handCm(foreCm);
    const semMancha = hRna <= 0.05;
    const popTot = data.meta.pop_total || 0;
    const cnt = { alagada: 0, urgente: 0, atencao: 0, seguro: 0, alto: 0 };
    (data.cells || []).forEach(c => { cnt[clsCota(c.cota, hNow, hRna)] += c.pop; });
    const sair = cnt.alagada + cnt.urgente + cnt.atencao;

    if (sub) {
      sub.textContent = semMancha
        ? ('Rio abaixo da cota de atenção (' + (data.meta.zero_regua_m) + ' m) — sem mancha, sem fila de evacuação.')
        : ('A mancha prevista (RNA) alcança a grade IBGE — ' + NF.format(sair) + ' de ' + NF.format(popTot) + ' pessoas.');
    }
    if (tot) {
      tot.innerHTML = semMancha
        ? '<div class="fila-hero">Ninguém precisa sair agora</div>'
        : ('<div class="fila-hero"><b>' + NF.format(sair) + '</b> pessoas precisam sair <span>de ' + NF.format(popTot) + '</span></div>' +
          '<div class="fila-tot-row"><i style="background:' + CORES.alagada + '"></i>já na água<b>' + NF.format(cnt.alagada) + '</b></div>' +
          '<div class="fila-tot-row"><i style="background:' + CORES.urgente + '"></i>sair agora<b>' + NF.format(cnt.urgente) + '</b></div>' +
          '<div class="fila-tot-row"><i style="background:' + CORES.atencao + '"></i>a RNA alcança<b>' + NF.format(cnt.atencao) + '</b></div>');
    }

    const ranked = (data.casas || []).slice().sort((a, b) => a.cota_hand_m - b.cota_hand_m);
    let nFila = 0;
    box.innerHTML = ranked.map(c => {
      const k = clsCota(c.cota_hand_m, hNow, hRna);
      const rr = pegaRota(c, hRna);
      const rotaFecha = rr.kind === 'fuga' || rr.kind === 'isolada';
      const naFila = !semMancha && ((k !== 'seguro' && k !== 'alto') || rotaFecha);
      if (naFila) nFila += 1;
      const vis = semMancha ? 'seguro' : (rr.kind === 'isolada' && naFila ? 'isolada' : (rr.kind === 'fuga' && naFila ? 'fuga' : k));
      return '<div class="fila-item ' + (naFila ? vis : 'seguro') + '">' +
        '<div class="fila-ord">' + (naFila ? nFila + 'º' : '—') + '</div>' +
        '<div><span class="fila-tag" style="background:' + (CORES[vis] || CORES[k]) + '">' + (LAB[vis] || vis) + '</span>' +
        '<div class="fila-nm">' + c.nome + '</div>' +
        '<div class="fila-bl">alaga em HAND ' + c.cota_hand_m + ' m · rota-exemplo</div>' +
        '<div class="fila-bl">' + (semMancha ? '—' : txtCasa(c, naFila ? k : 'seguro', rr, vel)) + '</div></div></div>';
    }).join('');
    if (!ranked.length && !semMancha) {
      box.innerHTML = '<div class="fila-bl">Clique num ponto da grade no mapa para ver a rota a pé até o abrigo.</div>';
    }

    const map = cfg && cfg.getMap && cfg.getMap();
    if (semMancha) {
      if (map) hideOverlays(map);
      return;
    }
    if (!map) return;
    ensureLayers();
    if (!layers) return;
    if (layers.abrigos && !map.hasLayer(layers.abrigos)) layers.abrigos.addTo(map);

    (data.cells || []).forEach((c, i) => {
      const k = clsCota(c.cota, hNow, hRna);
      const show = k !== 'alto';
      const mk = layers.cells[i];
      if (!mk) return;
      mk.setStyle({
        fillColor: CORES[k],
        opacity: show ? 1 : 0,
        fillOpacity: show ? (k === 'seguro' ? 0.35 : 0.88) : 0
      });
    });

    ranked.forEach(c => {
      const k = clsCota(c.cota_hand_m, hNow, hRna);
      const rr = pegaRota(c, hRna);
      const show = k === 'atencao' || k === 'urgente' || k === 'alagada' || rr.kind === 'fuga' || rr.kind === 'isolada';
      const desvia = show && rr.kind !== 'seca' && (c.rota || []).length > 1;
      if (layers.orig[c.id]) {
        layers.orig[c.id].setLatLngs(c.rota || [[c.lat, c.lon]]);
        layers.orig[c.id].setStyle({ opacity: desvia ? 0.55 : 0 });
      }
      if (layers.rotas[c.id]) {
        layers.rotas[c.id].setLatLngs(rr.pts && rr.pts.length ? rr.pts : [[c.lat, c.lon]]);
        const corLinha = rr.kind === 'isolada' ? '#7a1f1f' : rr.kind === 'fuga' ? '#c0392b' : k === 'urgente' ? '#c0392b' : '#0f8b46';
        layers.rotas[c.id].setStyle({ opacity: show ? 0.95 : 0, color: corLinha, dashArray: rr.kind === 'isolada' ? '5 7' : '' });
      }
      if (layers.dots[c.id]) {
        const corDot = rr.kind === 'isolada' ? CORES.isolada : (rr.kind === 'fuga' ? CORES.fuga : CORES[k]);
        layers.dots[c.id].setIcon(L.divIcon({
          className: '', html: '<div class="ev-dot" style="background:' + corDot + '"></div>',
          iconSize: [16, 16], iconAnchor: [8, 8]
        }));
        layers.dots[c.id].setOpacity(1);
      }
    });
  }

  function wireReplay() {
    const btn = $('fila-replay');
    if (!btn || !cfg) return;
    if (cfg.replayLabel) btn.textContent = cfg.replayLabel;
    btn.onclick = function () {
      if (typeof cfg.exitLive === 'function') cfg.exitLive();
      const key = cfg.replayKey;
      if (key && typeof cfg.setEvent === 'function') cfg.setEvent(key);
      if (typeof cfg.play === 'function') cfg.play();
    };
  }

  function init(options) {
    cfg = options || {};
    wireReplay();
    return load();
  }

  global.PREVINE_FILA = { init: init, load: load, render: render };
})(window);
