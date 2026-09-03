/* Roteiro cronometrado 90 min — reunião gestor PREVINE. */
(function (global) {
  'use strict';
  var KEY = 'previne:roteiro90:v1';
  var STEPS = [
    { min: 0, dur: 5, title: 'Abertura', text: 'Regra de ouro: PREVINE ≠ alerta SGB/SACE/DC. UNKNOWN/STALE ≠ rio baixo. Mancha ≠ ordem de saída.', link: 'centro-resposta.html' },
    { min: 5, dur: 15, title: 'Agora na bacia', text: 'Dashboard + fichas ST/Muçum: telemetria, score experimental, frescor dos dados.', link: '../dashboard_bacia.html' },
    { min: 20, dur: 15, title: 'Perigo e exposição', text: 'Mapa HAND + exposição cruzada v1/v2. Números agregados — não lista nominal.', link: 'exposicao-cruzada.html' },
    { min: 35, dur: 15, title: 'Mesa V002', text: 'Exercício Santa Tereza: checklist 7 itens, ginásio sem capacidade, plantão ao vivo.', link: 'estudo-caso-resposta-santa-tereza.html' },
    { min: 50, dur: 15, title: 'Rotas e pontes', text: 'Corredor Etapa 2 ST/Muçum: pontes UNKNOWN, abrigos plano Muçum, validação em campo.', link: 'santa-tereza-rota-fuga-ruas.html' },
    { min: 65, dur: 10, title: 'Capacidade abrigo', text: 'Registrar Ginásio ST e alojamentos Muçum — exportar CSV antes de encerrar.', link: '#abrigo-capacidade-mount' },
    { min: 75, dur: 10, title: 'Benchmark HAND', text: 'HAND vs hidrodinâmica: agenda HEC-RAS/LISFLOOD — subárea drone.', link: 'benchmark-hand-hidrodinamica.html' },
    { min: 85, dur: 5, title: 'Encerramento', text: 'Recapitular lacunas abertas, responsáveis e data do próximo exercício.', link: 'agenda-avanco.html' }
  ];

  function fmt(sec) {
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  }

  function loadState() {
    try {
      var s = JSON.parse(localStorage.getItem(KEY) || '{}');
      return { startedAt: s.startedAt || null, pausedAt: s.pausedAt || null, elapsed: s.elapsed || 0, done: s.done || {} };
    } catch (e) { return { startedAt: null, pausedAt: null, elapsed: 0, done: {} }; }
  }

  function saveState(st) {
    try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) { /* ignore */ }
  }

  function mount(root, prefix) {
    if (!root || root.dataset.roteiroMounted) return;
    root.dataset.roteiroMounted = '1';
    prefix = prefix || '';
    var css = document.createElement('style');
    css.textContent =
      '.roteiro90{margin:12px 0;padding:14px;border:1px solid #d7e1e8;border-radius:12px;background:#f9fbfd}' +
      '.roteiro-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}' +
      '.roteiro-clock{font:850 28px/1 ui-monospace,monospace;color:#102334;min-width:72px}' +
      '.roteiro-btns{display:flex;gap:6px;flex-wrap:wrap}' +
      '.roteiro-btns button{min-height:36px;padding:0 12px;border-radius:8px;border:1px solid #102334;background:#102334;color:#fff;font:inherit;font-size:12px;font-weight:750;cursor:pointer}' +
      '.roteiro-btns .secondary{background:#fff;color:#102334}' +
      '.roteiro-steps{display:grid;gap:6px}' +
      '.roteiro-step{display:grid;grid-template-columns:52px 1fr auto;gap:8px;align-items:start;padding:8px 10px;border:1px solid #e0e6ea;border-radius:10px;background:#fff;font-size:12px}' +
      '.roteiro-step.active{border-color:#0f6b62;background:#f2faf5}' +
      '.roteiro-step.done{opacity:.85;background:#eef9f4}' +
      '.roteiro-step .when{font-weight:850;color:#5b6b76;font-variant-numeric:tabular-nums}' +
      '.roteiro-step b{display:block;color:#102334;margin-bottom:2px}' +
      '.roteiro-step a{font-size:11px;font-weight:750;color:#0f6b62;text-decoration:none}' +
      '@media(max-width:640px){.roteiro-step{grid-template-columns:1fr}}';
    root.appendChild(css);

    root.innerHTML += '<div class="roteiro90">' +
      '<div class="roteiro-head"><span class="roteiro-clock" id="roteiro-clock">00:00</span>' +
      '<span id="roteiro-phase">Pronto para iniciar · 90 min</span>' +
      '<div class="roteiro-btns"><button type="button" id="roteiro-start">Iniciar</button>' +
      '<button type="button" class="secondary" id="roteiro-pause">Pausar</button>' +
      '<button type="button" class="secondary" id="roteiro-reset">Reiniciar</button></div></div>' +
      '<div class="roteiro-steps" id="roteiro-steps"></div></div>';

    var stepsEl = root.querySelector('#roteiro-steps');
    stepsEl.innerHTML = STEPS.map(function (s, i) {
      var link = s.link.indexOf('#') === 0 ? s.link : (prefix + s.link);
      return '<div class="roteiro-step" data-step="' + i + '"><span class="when">' + s.min + '–' + (s.min + s.dur) + ' min</span>' +
        '<div><b>' + s.title + '</b>' + s.text + '</div>' +
        '<a href="' + link + '">abrir →</a></div>';
    }).join('');

    var st = loadState();
    var timer = null;

    function elapsedSec() {
      if (!st.startedAt) return st.elapsed;
      if (st.pausedAt) return st.elapsed;
      return st.elapsed + Math.floor((Date.now() - st.startedAt) / 1000);
    }

    function currentStepIndex(sec) {
      for (var i = STEPS.length - 1; i >= 0; i--) {
        if (sec >= STEPS[i].min * 60) return i;
      }
      return 0;
    }

    function tick() {
      var sec = elapsedSec();
      root.querySelector('#roteiro-clock').textContent = fmt(sec);
      var idx = currentStepIndex(sec);
      var phase = STEPS[idx];
      root.querySelector('#roteiro-phase').textContent = sec >= 90 * 60
        ? 'Tempo esgotado · encerrar reunião'
        : 'Fase: ' + phase.title + ' · restam ~' + Math.max(0, 90 - Math.floor(sec / 60)) + ' min';
      root.querySelectorAll('.roteiro-step').forEach(function (el, i) {
        el.classList.toggle('active', i === idx && sec < 90 * 60);
        el.classList.toggle('done', !!st.done[i]);
      });
    }

    function startTimer() {
      if (timer) return;
      timer = setInterval(tick, 1000);
      tick();
    }

    root.querySelector('#roteiro-start').addEventListener('click', function () {
      if (!st.startedAt || st.pausedAt) {
        if (st.pausedAt) {
          st.startedAt = Date.now();
          st.pausedAt = null;
        } else {
          st.startedAt = Date.now();
          st.elapsed = 0;
        }
        saveState(st);
        startTimer();
      }
    });
    root.querySelector('#roteiro-pause').addEventListener('click', function () {
      if (st.startedAt && !st.pausedAt) {
        st.elapsed = elapsedSec();
        st.pausedAt = Date.now();
        st.startedAt = null;
        saveState(st);
      }
    });
    root.querySelector('#roteiro-reset').addEventListener('click', function () {
      if (!global.confirm('Reiniciar cronômetro do roteiro?')) return;
      st = { startedAt: null, pausedAt: null, elapsed: 0, done: {} };
      saveState(st);
      tick();
    });
    stepsEl.addEventListener('click', function (ev) {
      var step = ev.target.closest('.roteiro-step');
      if (!step) return;
      var i = Number(step.getAttribute('data-step'));
      st.done[i] = !st.done[i];
      saveState(st);
      tick();
    });
    tick();
    if (st.startedAt && !st.pausedAt) startTimer();
  }

  global.PREVINE_ROTEIRO_90 = { mount: mount, STEPS: STEPS };
})(typeof window !== 'undefined' ? window : globalThis);
