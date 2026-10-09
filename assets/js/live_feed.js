(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.PrevineLiveFeed = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const REPO = 'previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais';

  function withCacheBust(url) {
    return url + (String(url).includes('?') ? '&' : '?') + 'cb=' + Date.now();
  }

  function stampMs(data) {
    const value = data && (data.ultima_tentativa_em || data.consultado_em || data.gerado_em || data.atualizado_em || data.hora_modelo);
    if (!value) return NaN;
    const raw = String(value);
    return Date.parse(/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw + '-03:00');
  }

  function pickNewest(feeds) {
    const ok = (feeds || []).filter(Boolean);
    if (!ok.length) return null;
    ok.sort(function (a, b) { return (stampMs(b) || 0) - (stampMs(a) || 0); });
    return ok[0];
  }

  function fileName(path) {
    return String(path || '').split('?')[0].replace(/^.*\//, '');
  }

  function sourcesFor(path) {
    const file = fileName(path);
    if (!file) return [];
    return [
      { label: 'arquivo publicado', url: file },
      { label: 'arquivo Raw', url: 'https://raw.githubusercontent.com/' + REPO + '/main/' + file },
      { label: 'CDN jsDelivr', url: 'https://cdn.jsdelivr.net/gh/' + REPO + '@main/' + file },
      { label: 'API GitHub', url: 'https://api.github.com/repos/' + REPO + '/contents/' + file + '?ref=main', kind: 'github-api' }
    ];
  }

  function primarySources(sources) {
    return (sources || []).filter(function (src) { return src.kind !== 'github-api'; });
  }

  function apiSources(sources) {
    return (sources || []).filter(function (src) { return src.kind === 'github-api'; });
  }

  async function fetchJson(url, timeoutMs) {
    const ctl = new AbortController();
    const timer = setTimeout(function () { ctl.abort(); }, timeoutMs || 8000);
    try {
      const response = await fetch(withCacheBust(url), { cache: 'no-store', signal: ctl.signal });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function fetchGithubContents(apiUrl) {
    const meta = await fetchJson(apiUrl);
    const b64 = String(meta.content || '').replace(/\s/g, '');
    if (!b64) throw new Error('conteúdo vazio');
    return JSON.parse(decodeURIComponent(escape(atob(b64))));
  }

  async function fetchNewest(sources) {
    const list = sources || [];
    const settled = await Promise.allSettled(list.map(function (src) {
      return src.kind === 'github-api' ? fetchGithubContents(src.url) : fetchJson(src.url);
    }));
    const ok = [];
    const failures = [];
    settled.forEach(function (result, i) {
      const label = list[i].label || list[i].url;
      if (result.status === 'fulfilled' && result.value) ok.push(result.value);
      else failures.push(label + ': ' + (result.reason && result.reason.message || 'erro de rede'));
    });
    const newest = pickNewest(ok);
    if (!newest) throw new Error(failures.join(' · ') || 'fontes indisponíveis');
    return newest;
  }

  // A interface pública de Muçum escolhe a RNA +4 h pelo erro observado recente.
  // O feed original permanece intacto, assim como a página _usuario e os dados de pesquisa.
  function selectPublicMucum4h(feed, isPublicMucum) {
    if (!isPublicMucum || !feed || !feed.horizontes) return feed;
    const primary = feed.horizontes['4h'];
    const alternative = feed.horizontes['4h_versao_b'];
    if (!alternative || !primary) return feed;

    const parseLocal = function (value) {
      if (!value) return NaN;
      const raw = String(value);
      return Date.parse(/[zZ]|[+-]\\d{2}:?\\d{2}$/.test(raw) ? raw : raw + '-03:00');
    };
    const usable = function (model) {
      if (!model || model.disponivel === false || model.shadow_only ||
          !Number.isFinite(Number(model.nivel_previsto_cm)) ||
          model.nivel_previsto_cm === null ||
          !/^ok\\b/i.test(String(model.status || '')) ||
          !Number.isFinite(parseLocal(model.hora_modelo)) ||
          !(parseLocal(model.hora_alvo) > Date.now())) return false;
      const audit = model.auditoria || {};
      return (Number(audit.n_conferidas) >= 8 &&
        Array.isArray(audit.ultimas_conferidas) &&
        audit.ultimas_conferidas.filter(function (r) { return Number.isFinite(Number(r.erro_abs_cm)); }).length >= 8);
    };
    if (!usable(alternative)) return feed;
    const altMae = Number(alternative.qualidade_ao_vivo && alternative.qualidade_ao_vivo.mae_24h_cm);
    const priMae = Number(primary.qualidade_ao_vivo && primary.qualidade_ao_vivo.mae_24h_cm);
    // Mesmo ciclo, mesmo alvo e mesma base: nunca comparar rodadas de horas diferentes.
    if (primary.hora_modelo !== alternative.hora_modelo ||
        primary.hora_alvo !== alternative.hora_alvo ||
        !Number.isFinite(altMae) || altMae < 0) return feed;
    const primaryUsable = usable(primary);
    const alternativeWarning = alternative.qualidade_ao_vivo && alternative.qualidade_ao_vivo.status;
    // Não promover modelo classificado em atenção ou desatualizado.
    if (alternativeWarning !== 'NORMAL') return feed;
    if (primaryUsable && (!Number.isFinite(priMae) || priMae < 0 || altMae + 2 >= priMae)) return feed;

    const public4h = Object.assign({}, alternative, {
      horizonte: '4h',
      rotulo: '4h · RNA selecionada por desempenho recente',
      modelo_papel: 'principal_publico',
      origem_horizonte: '4h_versao_b'
    });
    return Object.assign({}, feed, {
      horizontes: Object.assign({}, feed.horizontes, { '4h': public4h }),
      selecao_publica_4h: {
        criterio: 'menor MAE observado nas ultimas 24h, ambas RNAs com ao menos 8 confrontos',
        modelo: public4h.modelo,
        mae_cm: altMae,
        modelo_anterior: primary.modelo,
        mae_anterior_cm: primaryUsable ? priMae : null
      }
    });
  }

  function isPublicMucumPage(path) {
    return fileName(path) === 'previsao_ao_vivo_mucum.json' &&
      typeof document !== 'undefined' && document.body &&
      document.body.classList && document.body.classList.contains('public-forecast') &&
      document.body.dataset && document.body.dataset.cityName === 'Muçum';
  }

  async function fetchLive(path) {
    const sources = sourcesFor(path);
    let feed;
    try {
      feed = await fetchNewest(primarySources(sources));
    } catch (primaryError) {
      const fallback = apiSources(sources);
      if (!fallback.length) throw primaryError;
      feed = await fetchNewest(fallback);
    }
    return selectPublicMucum4h(feed, isPublicMucumPage(path));
  }

  return {
    stampMs: stampMs,
    pickNewest: pickNewest,
    sourcesFor: sourcesFor,
    primarySources: primarySources,
    apiSources: apiSources,
    withCacheBust: withCacheBust,
    fetchNewest: fetchNewest,
    fetchLive: fetchLive,
    selectPublicMucum4h: selectPublicMucum4h
  };
});
