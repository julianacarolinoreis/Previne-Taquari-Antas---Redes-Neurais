/* Bloco HAND vs hidrodinâmica — mapas geoespaciais PREVINE. */
(function () {
  'use strict';
  if (document.querySelector('.hand-vs-hidro-block')) return;
  var script = document.currentScript;
  var prefix = '';
  if (script && script.getAttribute('src')) {
    var m = script.getAttribute('src').match(/^(.*\/)assets\/js\//);
    prefix = m ? m[1] : '';
  }
  var link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = prefix + 'assets/css/hand_vs_hidro_block.css';
  document.head.appendChild(link);
  var block = document.createElement('aside');
  block.className = 'hand-vs-hidro-block';
  block.setAttribute('role', 'note');
  block.innerHTML =
    '<b>HAND ≠ hidrodinâmica</b>' +
    'A mancha laranja vem de <strong>HAND + MDT</strong> (proxy de terreno relativo ao rio). Não é simulação 2D (HEC-RAS, LISFLOOD-FP) nem produto oficial SGB/SACE.' +
    '<ul><li>HAND 0 ≈ leito — não confundir com “rio baixo” ou “sem risco”.</li>' +
    '<li>Cota oficial ST 15 m · Muçum 18 m — conferir régua e datum em campo.</li>' +
    '<li>Ordem de saída exige DC/bombeiros + ponte + abrigo confirmados.</li></ul>' +
    '<a href="' + prefix + 'pesquisas/centro-resposta.html">Centro de resposta</a>';
  var sel = (script && script.getAttribute('data-target')) || 'aside';
  var mount = document.querySelector(sel);
  if (mount) mount.insertBefore(block, mount.firstChild);
  else document.body.insertBefore(block, document.body.firstChild);
})();
