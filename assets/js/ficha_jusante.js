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
    fetch('assets/data/icm_municipios.json').then(function (r) { return r.ok ? r.json() : null; }),
    fetch('assets/data/validacao_zenodo_2020/relatorio_cruzamento.json').then(function (r) { return r.ok ? r.json() : null; }),
    R.fetchLive('mucum').catch(function () { return null; }),
    R.fetchLive('santa').catch(function () { return null; })
  ]).then(function (parts) {
    var ind = parts[0], icmData = parts[1], zenodo = parts[2], feedMuc = parts[3], feedSt = parts[4];
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

    var note = document.getElementById('exposure-note');
    if (note) {
      var zenodoPts = zenodo && zenodo.fonte_zenodo && zenodo.fonte_zenodo.cidades
        ? zenodo.fonte_zenodo.cidades[cfg.label] : cfg.zenodoPoints;
      var mucLevel = feedMuc && R.fmtLevel(feedMuc.nivel_rio_agora_cm || feedMuc.telemetria_ultima_nivel_cm);
      var stLevel = feedSt && R.fmtLevel(feedSt.nivel_rio_agora_cm || feedSt.telemetria_ultima_nivel_cm);
      note.innerHTML = '<strong>Exposição espacial local:</strong> sem HAND municipal publicado — ' +
        zenodoPts + ' pontos fotográficos Zenodo jul/2020 neste município. ' +
        'Proxy montante: Muçum ' + (mucLevel || '—') + ' · ST ' + (stLevel || '—') + '. ' +
        'Exposição cruzada HAND×IBGE disponível para <a href="pesquisas/exposicao-cruzada.html">Muçum e Santa Tereza</a>.';
    }

    var proxy = document.getElementById('proxy-levels');
    if (proxy && feedMuc && feedSt) {
      proxy.textContent = 'Muçum ' + R.fmtLevel(feedMuc.nivel_rio_agora_cm) + ' · ST ' + R.fmtLevel(feedSt.nivel_rio_agora_cm);
    }
  }).catch(function () {
    document.getElementById('mun-sub').textContent = 'Não foi possível carregar indicadores IBGE/ICM. Tente atualizar a página.';
  });
})();
