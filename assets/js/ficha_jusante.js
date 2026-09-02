/* PREVINE · ficha municipal a jusante (sem estação própria). */
(function () {
  'use strict';
  var script = document.currentScript;
  var key = script && script.getAttribute('data-municipio');
  var R = window.PREVINE_RESPOSTA;
  if (!key) return;
  if (!R || !R.JUSANTE[key]) {
    var sub = document.getElementById('mun-sub');
    if (sub) sub.textContent = 'Erro ao carregar configuração do município.';
    return;
  }
  var cfg = R.JUSANTE[key];

  function fmt(n) {
    return Number.isFinite(Number(n)) ? Math.round(Number(n)).toLocaleString('pt-BR') : '—';
  }
  function fmtSigilo(value, sigilo) {
    return sigilo ? 'parcial/sigilo IBGE' : fmt(value);
  }

  Promise.all([
    fetch('assets/data/vulnerabilidade/indicadores_municipios.json').then(function (r) { return r.ok ? r.json() : null; }),
    fetch('assets/data/icm_municipios.json').then(function (r) { return r.ok ? r.json() : null; })
  ]).then(function (parts) {
    var ind = parts[0], icmData = parts[1];
    if (!ind) throw new Error('indicadores indisponíveis');
    var mun = (ind.municipios || []).find(function (m) { return m.cod_mun === cfg.codIbge || m.nome === cfg.label; });
    var icm = (icmData && icmData.municipios || []).find(function (m) { return m.cod_ibge === cfg.codIbge; });
    document.getElementById('mun-title').textContent = cfg.label;
    document.getElementById('mun-sub').textContent = 'IBGE ' + cfg.codIbge + ' · bacia Taquari-Antas · sem estação PREVINE dedicada';
    document.getElementById('k-pop').textContent = fmt(mun && mun.pop_bacia);
    document.getElementById('k-dom').textContent = fmtSigilo(mun && mun.dom_ocupados_bacia, mun && mun.sigilo_dom_ocupados_bacia);
    document.getElementById('k-i70').textContent = fmtSigilo(mun && mun.i70m_bacia, mun && mun.sigilo_i70m_bacia);
    document.getElementById('k-set').textContent = fmt(mun && mun.n_setores_bacia);
    document.getElementById('k-zenodo').textContent = fmt(cfg.zenodoPoints);
    document.getElementById('k-icm').textContent = icm ? ('Faixa ' + icm.faixa + ' · ' + icm.pontuacao_total + ' pts') : '—';
    document.getElementById('k-perfil').textContent = icm ? ('Capacidade DC · ' + icm.perfil_risco) : '—';
    document.getElementById('k-renda').textContent = mun && mun.renda_resp_bacia ? ('R$ ' + fmt(mun.renda_resp_bacia)) : '—';
    document.title = 'PREVINE · Estado da pesquisa — ' + cfg.label;
  }).catch(function () {
    document.getElementById('mun-sub').textContent = 'Não foi possível carregar indicadores IBGE/ICM. Tente atualizar a página.';
  });
})();
