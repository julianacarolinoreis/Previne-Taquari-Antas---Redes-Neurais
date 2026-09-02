/* Formulário exportável de capacidade de abrigo (reunião gestor / campo). */
(function (global) {
  'use strict';
  var KEY = 'previne:abrigo-capacidade:v1';

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
    return String(s == null ? '' : s).replace(/"/g, '""');
  }

  function exportCsv(rows) {
    var header = ['registrado_em', 'municipio', 'abrigo', 'capacidade_declarada', 'vagas_livres', 'aberto', 'responsavel', 'observacao'];
    var lines = [header.join(',')].concat(rows.map(function (r) {
      return header.map(function (k) { return '"' + esc(r[k]) + '"'; }).join(',');
    }));
    var blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'previne-abrigos-capacidade.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function renderList(container, rows) {
    if (!rows.length) {
      container.innerHTML = '<p class="abrigo-empty">Nenhum registro ainda.</p>';
      return;
    }
    container.innerHTML = rows.slice().reverse().map(function (r, i) {
      return '<div class="abrigo-row"><strong>' + esc(r.abrigo) + '</strong> · ' + esc(r.municipio) +
        '<br>Cap. ' + esc(r.capacidade_declarada || '—') + ' · livres ' + esc(r.vagas_livres || '—') +
        ' · ' + esc(r.aberto || '—') + '<br><small>' + esc(r.registrado_em) + '</small></div>';
    }).join('');
  }

  function mount(root) {
    if (!root || root.dataset.abrigoMounted) return;
    root.dataset.abrigoMounted = '1';
    root.innerHTML =
      '<p class="abrigo-intro">Registre o que a mesa ou a equipe de campo confirmou sobre abrigos. Exportável — não libera despacho.</p>' +
      '<form class="abrigo-form" id="abrigo-cap-form">' +
      '<label>Município<select name="municipio" required><option value="Santa Tereza">Santa Tereza</option><option value="Muçum">Muçum</option><option value="Outro">Outro</option></select></label>' +
      '<label>Abrigo / ponto<input name="abrigo" required placeholder="Ex.: Ginásio de Esportes" maxlength="120"></label>' +
      '<label>Capacidade declarada<input name="capacidade_declarada" inputmode="numeric" placeholder="Ex.: 200"></label>' +
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
      '.abrigo-empty{color:#5b6b76;font-size:12px;margin:0}' +
      '@media(max-width:640px){.abrigo-form{grid-template-columns:1fr}}';
    root.appendChild(style);
    var listEl = root.querySelector('#abrigo-list');
    function refresh() { renderList(listEl, readRows()); }
    root.querySelector('#abrigo-cap-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var fd = new FormData(ev.target);
      var row = {
        registrado_em: new Date().toISOString(),
        municipio: fd.get('municipio'),
        abrigo: fd.get('abrigo'),
        capacidade_declarada: fd.get('capacidade_declarada'),
        vagas_livres: fd.get('vagas_livres'),
        aberto: fd.get('aberto'),
        responsavel: fd.get('responsavel'),
        observacao: fd.get('observacao')
      };
      var rows = readRows();
      rows.push(row);
      writeRows(rows);
      ev.target.reset();
      refresh();
    });
    root.querySelector('#abrigo-export').addEventListener('click', function () { exportCsv(readRows()); });
    root.querySelector('#abrigo-clear').addEventListener('click', function () {
      if (global.confirm('Apagar todos os registros de abrigo neste aparelho?')) {
        writeRows([]);
        refresh();
      }
    });
    refresh();
  }

  global.PREVINE_ABRIGO_FORM = { mount: mount, readRows: readRows, exportCsv: exportCsv };
})(typeof window !== 'undefined' ? window : globalThis);
