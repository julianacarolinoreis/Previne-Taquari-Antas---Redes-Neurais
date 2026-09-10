/* Barra institucional. Não emite alerta. */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script || document.querySelector('.site-nav')) return;
  var src = script.getAttribute('src') || '';
  var prefix = src.replace(/assets\/js\/site_chrome\.js(?:\?.*)?$/, '');
  var page = script.getAttribute('data-page') || '';
  function cur(id) {
    return page === id ? ' aria-current="page"' : '';
  }
  var bar = document.createElement('div');
  bar.className = 'site-brandbar';
  bar.setAttribute('aria-hidden', 'true');
  var nav = document.createElement('nav');
  nav.className = 'site-nav';
  nav.setAttribute('aria-label', 'PREVINE');
  nav.innerHTML =
    '<a class="site-wordmark" href="' + prefix + 'projeto.html">PREVINE</a>' +
    '<div class="site-nav-links">' +
      '<a href="' + prefix + 'projeto.html"' + cur('projeto') + '>Projeto</a>' +
      '<a href="' + prefix + 'pesquisas.html"' + cur('acervo') + '>Acervo</a>' +
      '<a href="' + prefix + 'dashboard_bacia.html"' + cur('bacia') + '>Bacia</a>' +
      '<a href="' + prefix + 'index.html"' + cur('rna') + '>RNA</a>' +
    '</div>';
  document.body.insertBefore(nav, document.body.firstChild);
  document.body.insertBefore(bar, nav);
  document.body.classList.add('has-site-chrome');
})();
