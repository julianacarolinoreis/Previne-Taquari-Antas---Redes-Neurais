/* Formulário exportável de capacidade de abrigo (reunião gestor / campo).
   Seeds locais = cadastro planejado; capacidade real / abertura exigem confirmação. */
(function (global) {
  'use strict';
  var KEY = 'previne:abrigo-capacidade:v1';
  var SEEDS = {
    'Santa Tereza': [
      {
        id: 'santa_tereza_ginasio_esportes',
        nome: 'Ginásio de Esportes',
        capacidade_planejada: '',
        hint: 'Cadastro DC · capacidade não publicada · abertura UNKNOWN'
      }
    ],
    'Muçum': []
  };

  function readRows() {
    try {
      var raw = localStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }

  function writeRows(rows) {
    try { localStorage.setItem(KEY, JSON.stringify(rows)); } catch (e) { /* ignore */ }
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function escCsv(s) {
    return String(s == null ? '' : s).replace(/"/g, '""');
  }

  function exportCsv(rows) {
    var header = ['registrado_em', 'municipio', 'abrigo', 'capacidade_declarada', 'vagas_livres', 'aberto', 'responsavel', 'observacao', 'fonte_planejada'];
    var lines = [header.join(',')].concat(rows.map(function (r) {
      return header.map(function (k) { return '"' + escCsv(r[k]) + '"'; }).join(',');
    }));
    var blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'previne-abrigos-capacidade.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function renderList(container, rows, municipioFilter) {
    var filtered = rows;
    if (municipioFilter && municipioFilter !== 'Outro') {
      filtered = rows.filter(function (r) { return r.municipio === municipioFilter; });
    }
    if (!filtered.length) {
      container.innerHTML = '<p class="abrigo-empty">Nenhum registro' +
        (municipioFilter && municipioFilter !== 'Outro' ? ' para ' + esc(municipioFilter) : '') +
        ' ainda.</p>';
      return;
    }
    container.innerHTML = filtered.slice().reverse().map(function (r) {
      return '<div class="abrigo-row"><strong>' + esc(r.abrigo) + '</strong> · ' + esc(r.municipio) +
        '<br>Cap. ' + esc(r.capacidade_declarada || '—') + ' · livres ' + esc(r.vagas_livres || '—') +
        ' · ' + esc(r.aberto || '—') +
        (r.fonte_planejada ? '<br><em>planejado: ' + esc(r.fonte_planejada) + '</em>' : '') +
        '<br><small>' + esc(r.registrado_em) + '</small></div>';
    }).join('');
  }

  function seedsFor(municipio) {
    return SEEDS[municipio] || [];
  }

  function fillDatalist(root, municipio) {
    var list = root.querySelector('#abrigo-seed-list');
    if (!list) return;
    var seeds = seedsFor(municipio);
    list.innerHTML = seeds.map(function (s) {
      return '<option value="' + esc(s.nome) + '" data-id="' + esc(s.id) + '" data-cap="' + esc(s.capacidade_planejada || '') + '" data-hint="' + esc(s.hint || '') + '"></option>';
    }).join('');
  }

  function applySeedHints(root, municipio, abrigoNome) {
    var hintEl = root.querySelector('#abrigo-seed-hint');
    var capInput = root.querySelector('[name="capacidade_declarada"]');
    var seeds = seedsFor(municipio);
    var hit = seeds.find(function (s) { return s.nome === abrigoNome; });
    if (!hit) {
      if (hintEl) hintEl.textContent = 'Sem seed local para este nome — preencha só o que foi confirmado.';
      return;
    }
    if (hintEl) {
      hintEl.textContent = hit.hint ||
        (hit.capacidade_planejada
          ? 'Capacidade planejada no cadastro: ' + hit.capacidade_planejada + ' · abertura ainda UNKNOWN'
          : 'Nome do cadastro · capacidade/abertura UNKNOWN até confirmação');
    }
    if (capInput && !capInput.value && hit.capacidade_planejada) {
      capInput.placeholder = 'planejada: ' + hit.capacidade_planejada;
    }
  }

  function loadMucumSeeds(cb) {
    if (SEEDS['Muçum'].length) {
      cb();
      return;
    }
    var urls = [
      '../assets/data/mucum_contingencia_202607.json',
      '/assets/data/mucum_contingencia_202607.json',
      'assets/data/mucum_contingencia_202607.json'
    ];
    function tryFetch(i) {
      if (i >= urls.length) { cb(); return; }
      fetch(urls[i], { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data || !Array.isArray(data.abrigos)) {
            tryFetch(i + 1);
            return;
          }
          SEEDS['Muçum'] = data.abrigos.map(function (a) {
            var cap = a.capacidade_quadro_13 != null ? String(a.capacidade_quadro_13) : '';
            return {
              id: a.id || a.nome,
              nome: a.nome,
              capacidade_planejada: cap,
              hint: cap
                ? 'Quadro 13 planejado: ' + cap + ' pessoas · abertura/ocupação UNKNOWN até campo'
                : 'Cadastro plano jul/2026 · capacidade/abertura UNKNOWN'
            };
          });
          cb();
        })
        .catch(function () { tryFetch(i + 1); });
    }
    tryFetch(0);
  }

  function setMunicipio(root, municipio) {
    if (!root) return;
    var select = root.querySelector('[name="municipio"]');
    if (!select) return;
    var value = municipio === 'mucum' || municipio === 'Muçum' ? 'Muçum'
      : (municipio === 'santa' || municipio === 'Santa Tereza' ? 'Santa Tereza' : municipio);
    if ([].some.call(select.options, function (o) { return o.value === value; })) {
      select.value = value;
    }
    fillDatalist(root, select.value);
    var listEl = root.querySelector('#abrigo-list');
    if (listEl) renderList(listEl, readRows(), select.value);
    applySeedHints(root, select.value, (root.querySelector('[name="abrigo"]') || {}).value || '');
  }

  function mount(root, options) {
    if (!root || root.dataset.abrigoMounted) return root;
    options = options || {};
    root.dataset.abrigoMounted = '1';
    root.innerHTML =
      '<p class="abrigo-intro">Registre o que a mesa ou a equipe de campo confirmou sobre abrigos. Seeds locais sugerem nomes do cadastro — <strong>não</strong> marcam abertura nem liberam despacho.</p>' +
      '<form class="abrigo-form" id="abrigo-cap-form">' +
      '<label>Município<select name="municipio" required><option value="Santa Tereza">Santa Tereza</option><option value="Muçum">Muçum</option><option value="Outro">Outro</option></select></label>' +
      '<label>Abrigo / ponto<input name="abrigo" list="abrigo-seed-list" required placeholder="Ex.: Ginásio de Esportes" maxlength="120" autocomplete="off"></label>' +
      '<datalist id="abrigo-seed-list"></datalist>' +
      '<p id="abrigo-seed-hint" class="abrigo-seed-hint">Escolha um município para ver sugestões do cadastro.</p>' +
      '<label>Capacidade declarada<input name="capacidade_declarada" inputmode="numeric" placeholder="confirmada em campo"></label>' +
      '<label>Vagas livres agora<input name="vagas_livres" inputmode="numeric" placeholder="Ex.: 45"></label>' +
      '<label>Aberto<select name="aberto"><option value="desconhecido">desconhecido</option><option value="sim">sim</option><option value="nao">não</option><option value="lotado">lotado</option></select></label>' +
      '<label>Responsável<input name="responsavel" placeholder="função ou nome" maxlength="80"></label>' +
      '<label class="wide">Observação<textarea name="observacao" rows="2" maxlength="300"></textarea></label>' +
      '<button type="submit">Salvar registro</button></form>' +
      '<div class="abrigo-toolbar"><button type="button" id="abrigo-export">Exportar CSV</button><button type="button" id="abrigo-clear" class="secondary">Limpar todos</button></div>' +
      '<div id="abrigo-list" class="abrigo-list"></div>';
    var style = document.createElement('style');
    style.textContent =
      '.abrigo-intro{margin:0 0 10px;color:var(--muted,#5b6b76);font-size:13px}' +
      '.abrigo-seed-hint{grid-column:1/-1;margin:0;font-size:11px;color:#0f6b62;line-height:1.35}' +
      '.abrigo-form{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}' +
      '.abrigo-form label{display:flex;flex-direction:column;gap:4px;font-size:12px;font-weight:650}' +
      '.abrigo-form label.wide{grid-column:1/-1}' +
      '.abrigo-form input,.abrigo-form select,.abrigo-form textarea{padding:8px 10px;border:1px solid #d7e1e8;border-radius:8px;font:inherit}' +
      '.abrigo-form button{grid-column:1/-1;min-height:40px;border:0;border-radius:10px;background:#102334;color:#fff;font:inherit;font-weight:750;cursor:pointer}' +
      '.abrigo-toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}' +
      '.abrigo-toolbar button{min-height:38px;padding:0 12px;border-radius:9px;border:1px solid #102334;background:#102334;color:#fff;font:inherit;font-size:12px;font-weight:750;cursor:pointer}' +
      '.abrigo-toolbar .secondary{background:#fff;color:#102334}' +
      '.abrigo-list{display:grid;gap:8px}' +
      '.abrigo-row{padding:10px;border:1px solid #d7e1e8;border-radius:10px;font-size:12px;background:#f9fbfd}' +
      '.abrigo-row em{font-style:normal;color:#5b6b76}' +
      '.abrigo-empty{color:#5b6b76;font-size:12px;margin:0}' +
      '@media(max-width:640px){.abrigo-form{grid-template-columns:1fr}}';
    root.appendChild(style);

    var listEl = root.querySelector('#abrigo-list');
    var munSelect = root.querySelector('[name="municipio"]');
    var abrigoInput = root.querySelector('[name="abrigo"]');

    function refresh() {
      renderList(listEl, readRows(), munSelect.value);
    }

    function syncSeeds() {
      fillDatalist(root, munSelect.value);
      applySeedHints(root, munSelect.value, abrigoInput.value.trim());
      refresh();
    }

    munSelect.addEventListener('change', syncSeeds);
    abrigoInput.addEventListener('change', function () {
      applySeedHints(root, munSelect.value, abrigoInput.value.trim());
    });
    abrigoInput.addEventListener('input', function () {
      applySeedHints(root, munSelect.value, abrigoInput.value.trim());
    });

    root.querySelector('#abrigo-cap-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var fd = new FormData(ev.target);
      var mun = String(fd.get('municipio') || '');
      var nome = String(fd.get('abrigo') || '');
      var seed = seedsFor(mun).find(function (s) { return s.nome === nome; });
      var row = {
        registrado_em: new Date().toISOString(),
        municipio: mun,
        abrigo: nome,
        capacidade_declarada: fd.get('capacidade_declarada'),
        vagas_livres: fd.get('vagas_livres'),
        aberto: fd.get('aberto'),
        responsavel: fd.get('responsavel'),
        observacao: fd.get('observacao'),
        fonte_planejada: seed
          ? (seed.capacidade_planejada
            ? 'planejada ' + seed.capacidade_planejada
            : (seed.hint || 'cadastro local'))
          : ''
      };
      var rows = readRows();
      rows.push(row);
      writeRows(rows);
      ev.target.reset();
      munSelect.value = mun;
      syncSeeds();
    });
    root.querySelector('#abrigo-export').addEventListener('click', function () { exportCsv(readRows()); });
    root.querySelector('#abrigo-clear').addEventListener('click', function () {
      if (global.confirm('Apagar todos os registros de abrigo neste aparelho?')) {
        writeRows([]);
        refresh();
      }
    });

    loadMucumSeeds(function () {
      if (options.municipio) setMunicipio(root, options.municipio);
      else syncSeeds();
    });

    root._previneSetMunicipio = function (m) { setMunicipio(root, m); };
    return root;
  }

  global.PREVINE_ABRIGO_FORM = {
    mount: mount,
    setMunicipio: function (root, municipio) {
      if (root && root._previneSetMunicipio) root._previneSetMunicipio(municipio);
      else setMunicipio(root, municipio);
    },
    readRows: readRows,
    exportCsv: exportCsv,
    SEEDS: SEEDS
  };
})(typeof window !== 'undefined' ? window : globalThis);
