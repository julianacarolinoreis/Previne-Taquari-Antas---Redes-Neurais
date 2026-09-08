/* Barra de decisão compartilhada. Não emite alerta e não promove modelo. */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script || document.querySelector('.gestor-chrome')) return;
  var src = script.getAttribute('src') || '';
  var prefix = src.replace(/assets\/js\/gestor_chrome\.js(?:\?.*)?$/, '');
  var page = script.getAttribute('data-page') || 'arquivo';
  var place = script.getAttribute('data-place') || 'bacia';

  var respostaByPlace = {
    mucum: prefix + 'pesquisas/estudo-caso-resposta-mucum.html',
    santa: prefix + 'pesquisas/estudo-caso-resposta-santa-tereza.html',
    bacia: prefix + 'pesquisas/centro-resposta.html'
  };
  var fichaByPlace = {
    santa: prefix + 'pesquisa_status.html',
    mucum: prefix + 'pesquisa_status_mucum.html',
    encantado: prefix + 'pesquisa_status_encantado.html',
    roca_sales: prefix + 'pesquisa_status_roca_sales.html',
    lajeado: prefix + 'pesquisa_status_lajeado.html'
  };
  var centro = prefix + 'pesquisas/centro-resposta.html';
  var campo = prefix + 'pesquisas/modo-campo.html';

  function mapaFor(p) {
    return p === 'mucum'
      ? prefix + 'mucum_previsao_inundacao.html'
      : prefix + 'santa_tereza_previsao_inundacao.html';
  }
  function respostaFor(p) {
    return respostaByPlace[p] || respostaByPlace.santa;
  }
  function fichaFor(p) {
    return fichaByPlace[p] || prefix + 'pesquisa_status.html';
  }

  function current(id) {
    return page === id ? ' aria-current="page"' : '';
  }
  function fichaCurrent() {
    return (page === 'ficha' || page === 'ficha-jusante') ? ' aria-current="page"' : '';
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
      '<a href="' + prefix + 'dashboard_bacia.html"' + placeCurrent('bacia') + ' data-chrome-place="bacia">Bacia</a>' +
      '<a href="' + prefix + 'pesquisa_status.html"' + placeCurrent('santa') + ' data-chrome-place="santa">Santa Tereza</a>' +
      '<a href="' + prefix + 'pesquisa_status_mucum.html"' + placeCurrent('mucum') + ' data-chrome-place="mucum">Muçum</a>' +
    '</div>' +
    '<div class="gestor-chrome-vale" role="group" aria-label="Vale abaixo">' +
      '<span class="gestor-chrome-vale-label">Vale</span>' +
      '<a href="' + prefix + 'pesquisa_status_encantado.html"' + placeCurrent('encantado') + '>Encantado</a>' +
      '<a href="' + prefix + 'pesquisa_status_roca_sales.html"' + placeCurrent('roca_sales') + '>Roca Sales</a>' +
      '<a href="' + prefix + 'pesquisa_status_lajeado.html"' + placeCurrent('lajeado') + '>Lajeado</a>' +
    '</div>' +
    '<div class="gestor-chrome-tabs" role="group" aria-label="Camadas">' +
      '<a href="' + centro + '"' + current('centro') + '>Centro</a>' +
      '<a href="' + prefix + 'dashboard_bacia.html"' + current('agora') + '>Agora</a>' +
      '<a href="' + mapaFor(place) + '"' + current('mapa') + ' data-chrome-tab="mapa">Mapa</a>' +
      '<a href="' + prefix + 'vulnerabilidade.html"' + current('pessoas') + '>Pessoas</a>' +
      '<a href="' + respostaFor(place) + '"' + current('resposta') + ' data-chrome-tab="resposta">Resposta</a>' +
      '<a href="' + campo + '"' + current('campo') + '>Campo</a>' +
      '<a href="' + fichaFor(place) + '"' + fichaCurrent() + ' data-chrome-tab="ficha">Ficha</a>' +
      '<a href="' + prefix + 'pesquisas/briefing-gestores.html"' + current('briefing') + '>Briefing</a>' +
      '<a href="' + prefix + 'pesquisas.html"' + current('arquivo') + '>Arquivo</a>' +
    '</div>' +
    '<div class="gestor-chrome-seal" title="Não libera alerta, rota ou despacho">Pesquisa · não é alerta oficial</div>';
  document.body.insertBefore(nav, document.body.firstChild);
  document.body.classList.add('has-gestor-chrome');
  if (page === 'mapa' || page === 'pessoas') document.body.classList.add('gestor-fill-layout');

  function updatePlace(nextPlace) {
    if (!nextPlace || (nextPlace !== 'santa' && nextPlace !== 'mucum' && nextPlace !== 'bacia')) return place;
    place = nextPlace;
    if (script) script.setAttribute('data-place', place);
    nav.querySelectorAll('[data-chrome-place]').forEach(function (a) {
      if (a.getAttribute('data-chrome-place') === place) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
    var mapaLink = nav.querySelector('[data-chrome-tab="mapa"]');
    var respostaLink = nav.querySelector('[data-chrome-tab="resposta"]');
    var fichaLink = nav.querySelector('[data-chrome-tab="ficha"]');
    if (mapaLink) mapaLink.setAttribute('href', mapaFor(place));
    if (respostaLink) respostaLink.setAttribute('href', respostaFor(place));
    if (fichaLink) fichaLink.setAttribute('href', fichaFor(place));
    return place;
  }

  window.PREVINE_GESTOR_CHROME = {
    updatePlace: updatePlace,
    getPlace: function () { return place; },
    getPage: function () { return page; }
  };
})();
