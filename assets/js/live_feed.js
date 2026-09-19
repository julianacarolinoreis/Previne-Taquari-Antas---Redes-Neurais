(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.PrevineLiveFeed = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const REPO = 'julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais';

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

  async function fetchLive(path) {
    const sources = sourcesFor(path);
    try {
      return await fetchNewest(primarySources(sources));
    } catch (primaryError) {
      const fallback = apiSources(sources);
      if (!fallback.length) throw primaryError;
      return fetchNewest(fallback);
    }
  }

  return {
    stampMs: stampMs,
    pickNewest: pickNewest,
    sourcesFor: sourcesFor,
    primarySources: primarySources,
    apiSources: apiSources,
    withCacheBust: withCacheBust,
    fetchNewest: fetchNewest,
    fetchLive: fetchLive
  };
});
