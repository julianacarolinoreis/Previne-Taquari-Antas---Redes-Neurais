/* Barra de decisão compartilhada. Não emite alerta e não promove modelo. */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script || document.querySelector('.gestor-chrome')) return;
  var src = script.getAttribute('src') || '';
  var prefix = src.replace(/assets\/js\/gestor_chrome\.js(?:\?.*)?$/, '');
  var page = script.getAttribute('data-page') || 'arquivo';
  var place = script.getAttribute('data-place') || 'bacia';
  var mapa = place === 'mucum'
    ? prefix + 'mucum_previsao_inundacao.html'
    : prefix + 'santa_tereza_previsao_inundacao.html';
  var resposta = place === 'mucum'
    ? prefix + 'pesquisas/mucum-rota-fuga-ruas.html'
    : prefix + 'pesquisas/estudo-caso-resposta-santa-tereza.html';
  var ficha = place === 'mucum'
    ? prefix + 'pesquisa_status_mucum.html'
    : prefix + 'pesquisa_status.html';

  function current(id) {
    return page === id ? ' aria-current="page"' : '';
  }
  function placeCurrent(id) {
    return place === id ? ' aria-current="true"' : '';
  }

  var nav = document.createElement('nav');
  nav.className = 'gestor-chrome';
  nav.setAttribute('aria-label', 'Navegação de briefing para gestores');
  nav.innerHTML =
    '<div class="gestor-chrome-brand">PREVINE <span>pesquisa</span></div>' +
    '<div class="gestor-chrome-places" role="group" aria-label="Município">' +
      '<a href="' + prefix + 'dashboard_bacia.html"' + placeCurrent('bacia') + '>Bacia</a>' +
      '<a href="' + prefix + 'pesquisa_status.html"' + placeCurrent('santa') + '>Santa Tereza</a>' +
      '<a href="' + prefix + 'pesquisa_status_mucum.html"' + placeCurrent('mucum') + '>Muçum</a>' +
    '</div>' +
    '<div class="gestor-chrome-tabs" role="group" aria-label="Camadas">' +
      '<a href="' + prefix + 'dashboard_bacia.html"' + current('agora') + '>Agora</a>' +
      '<a href="' + mapa + '"' + current('mapa') + '>Mapa</a>' +
      '<a href="' + prefix + 'vulnerabilidade.html"' + current('pessoas') + '>Pessoas</a>' +
      '<a href="' + resposta + '"' + current('resposta') + '>Resposta</a>' +
      '<a href="' + ficha + '"' + current('ficha') + '>Ficha</a>' +
      '<a href="' + prefix + 'pesquisas/briefing-gestores.html"' + current('briefing') + '>Briefing</a>' +
      '<a href="' + prefix + 'pesquisas.html"' + current('arquivo') + '>Arquivo</a>' +
    '</div>' +
    '<div class="gestor-chrome-seal">Pesquisa · não é alerta oficial</div>';
  document.body.insertBefore(nav, document.body.firstChild);
  document.body.classList.add('has-gestor-chrome');
  if (page === 'mapa' || page === 'pessoas') document.body.classList.add('gestor-fill-layout');
})();
