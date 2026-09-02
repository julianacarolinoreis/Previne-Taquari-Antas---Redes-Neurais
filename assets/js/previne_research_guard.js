/* Faixa PESQUISA para mapas, rotas PoC, snapshots SACE e relatórios RNA sem gestor_chrome. */
(function () {
  'use strict';
  if (document.querySelector('.gestor-chrome') || document.querySelector('.previne-research-guard')) return;
  var script = document.currentScript;
  var mode = (script && script.getAttribute('data-mode')) || 'research';
  var extra = (script && script.getAttribute('data-extra')) || '';
  var prefix = '';
  if (script && script.getAttribute('src')) {
    var src = script.getAttribute('src');
    var m = src.match(/^(.*\/)assets\/js\//);
    prefix = m ? m[1] : '';
  }
  var link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = prefix + 'assets/css/previne_research_guard.css';
  document.head.appendChild(link);
  var bar = document.createElement('div');
  bar.className = 'previne-research-guard' + (mode === 'snapshot' ? ' snapshot' : '');
  bar.setAttribute('role', 'note');
  var label = mode === 'snapshot'
    ? '<strong>Snapshot histórico</strong> · não é feed ao vivo · SGB/SACE oficial em sace.agenciasreguladoras.gov.br'
    : mode === 'blocked'
      ? '<strong>Exercício bloqueado</strong> · não orientar evacuação · confirmar rua, ponte e abrigo em campo'
      : '<strong>Pesquisa PREVINE</strong> · não substitui alerta SGB/SACE/Defesa Civil · mancha ≠ ordem de saída';
  if (extra) label += ' · ' + extra;
  bar.innerHTML = label + '<a href="' + prefix + 'pesquisas/centro-resposta.html">Centro de resposta</a>';
  document.body.insertBefore(bar, document.body.firstChild);
  document.body.classList.add('has-previne-research-guard');
})();
