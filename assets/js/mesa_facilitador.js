/* Modo facilitador — oculta jargão RNA nas mesas V002. */
(function (global) {
  'use strict';
  var KEY = 'previne:mesa-facilitador';

  function isOn() {
    return document.body.classList.contains('mesa-facilitador');
  }

  function setOn(on) {
    document.body.classList.toggle('mesa-facilitador', !!on);
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) { /* ignore */ }
    document.querySelectorAll('[data-facilitador-toggle]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(!!on));
      btn.textContent = on ? 'Modo técnico (RNA)' : 'Modo facilitador';
    });
  }

  function injectToggle(mount) {
    if (!mount || document.querySelector('[data-facilitador-toggle]')) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'facilitador-toggle';
    btn.setAttribute('data-facilitador-toggle', '');
    btn.setAttribute('aria-pressed', 'false');
    btn.textContent = 'Modo facilitador';
    btn.addEventListener('click', function () { setOn(!isOn()); });
    mount.appendChild(btn);
  }

  function init(opts) {
    opts = opts || {};
    var prefix = opts.prefix || '';
    if (!document.querySelector('link[href*="mesa_facilitador.css"]')) {
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = prefix + 'assets/css/mesa_facilitador.css';
      document.head.appendChild(link);
    }
    injectToggle(opts.mount || document.querySelector('.mode-switch') || document.querySelector('.mode-switch'));
    var saved = false;
    try { saved = localStorage.getItem(KEY) === '1'; } catch (e) { /* ignore */ }
    if (saved) setOn(true);
  }

  global.PREVINE_MESA_FACILITADOR = { init: init, setOn: setOn, isOn: isOn };
})(typeof window !== 'undefined' ? window : globalThis);
