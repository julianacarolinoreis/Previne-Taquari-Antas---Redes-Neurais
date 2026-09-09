/**
 * Downloads of audit workbooks (.xlsx) go through GitHub Pages first.
 * raw.githubusercontent.com often returns 503 Backend.max_conn from
 * Brazilian CDN nodes (Varnish error 54113), which turned the "Baixar
 * planilha" click into an error page. .mat files are not published on
 * Pages, so they still use raw.githubusercontent.com with retries.
 */
(function (root) {
  const REPO = 'julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais';
  const PAGES_BASE = 'https://julianacarolinoreis.github.io/Previne-Taquari-Antas---Redes-Neurais/';
  const RAW_BASE = 'https://raw.githubusercontent.com/' + REPO + '/';
  const RETRY_STATUSES = { 429: true, 502: true, 503: true, 504: true };

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function filenameFromUrl(url) {
    try {
      const path = String(url || '').split('?')[0].split('#')[0];
      const name = decodeURIComponent(path.split('/').pop() || '');
      return name || 'arquivo';
    } catch (err) {
      return 'arquivo';
    }
  }

  function looksLikeHtml(bytes) {
    if (!bytes || !bytes.length) return false;
    let i = 0;
    if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) i = 3;
    while (i < bytes.length && (bytes[i] === 0x20 || bytes[i] === 0x09 || bytes[i] === 0x0a || bytes[i] === 0x0d)) i++;
    return bytes[i] === 0x3c;
  }

  function looksLikeXlsx(bytes) {
    return !!(bytes && bytes.length >= 2 && bytes[0] === 0x50 && bytes[1] === 0x4b);
  }

  function isSpreadsheet(path) {
    return /\.xlsx?$/i.test(path || '');
  }

  function isMat(path) {
    return /\.mat$/i.test(path || '');
  }

  function onGithubPages() {
    return typeof location !== 'undefined' && /github\.io$/i.test(location.hostname || '');
  }

  function onLocalSite() {
    if (typeof location === 'undefined') return false;
    const host = location.hostname || '';
    return host === 'localhost' || host === '127.0.0.1' || host === '::1';
  }

  function parseRepoAsset(url) {
    if (!url) return null;
    const value = String(url).trim();
    if (!value) return null;
    if (!/^https?:\/\//i.test(value)) {
      return { path: value.replace(/^\.?\//, ''), ref: 'main', relative: true };
    }
    const raw = value.match(
      /^https?:\/\/raw\.githubusercontent\.com\/julianacarolinoreis\/Previne-Taquari-Antas---Redes-Neurais\/([^/]+)\/(.+)$/i
    );
    if (raw) return { path: raw[2].split('?')[0], ref: raw[1], relative: false };
    const githubRaw = value.match(
      /^https?:\/\/github\.com\/julianacarolinoreis\/Previne-Taquari-Antas---Redes-Neurais\/(?:raw|blob)\/([^/]+)\/(.+)$/i
    );
    if (githubRaw) {
      return { path: githubRaw[2].split('?')[0], ref: githubRaw[1], relative: false };
    }
    const pages = value.match(
      /^https?:\/\/julianacarolinoreis\.github\.io\/Previne-Taquari-Antas---Redes-Neurais\/(.+)$/i
    );
    if (pages) return { path: pages[1].split('?')[0], ref: 'main', relative: false, pages: true };
    return { external: value };
  }

  function candidates(url) {
    const parsed = parseRepoAsset(url);
    if (!parsed) return [];
    if (parsed.external) return [parsed.external];
    const path = String(parsed.path || '').replace(/^\/+/, '');
    if (!path) return [];
    const ref = parsed.ref || 'main';
    const out = [];
    function push(item) {
      if (item && out.indexOf(item) === -1) out.push(item);
    }
    if (isSpreadsheet(path) && !isMat(path)) {
      if (onGithubPages() || onLocalSite()) push(path);
      push(PAGES_BASE + path);
    }
    push(RAW_BASE + ref + '/' + path);
    if (ref !== 'main') {
      if (isSpreadsheet(path)) push(PAGES_BASE + path);
      push(RAW_BASE + 'main/' + path);
    }
    return out;
  }

  function hrefFor(url) {
    const list = candidates(url);
    return list.length ? list[0] : (url || '');
  }

  function saveBlob(blob, filename) {
    if (typeof document === 'undefined') return;
    const a = document.createElement('a');
    const objectUrl = URL.createObjectURL(blob);
    a.href = objectUrl;
    a.download = filename || 'arquivo';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 4000);
  }

  function navigateFallback(url, filename) {
    if (typeof document === 'undefined' || !url) return;
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || filenameFromUrl(url);
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function makeError(message, extra) {
    const err = new Error(message);
    if (extra) Object.keys(extra).forEach(function (key) { err[key] = extra[key]; });
    return err;
  }

  async function fetchBinary(url, fetchFn) {
    const res = await fetchFn(url, { cache: 'no-store' });
    const status = res.status;
    if (RETRY_STATUSES[status]) {
      throw makeError('retryable ' + status, { retryable: true, status: status });
    }
    if (!res.ok) {
      throw makeError('http ' + status, { status: status });
    }
    const bytes = new Uint8Array(await res.arrayBuffer());
    if (looksLikeHtml(bytes)) {
      throw makeError('html error page', { retryable: true, status: status });
    }
    return bytes;
  }

  async function download(url, opts) {
    opts = opts || {};
    const filename = opts.filename || filenameFromUrl(url);
    const expectXlsx = isSpreadsheet(filename) || isSpreadsheet(url);
    const fetchFn = opts.fetch || (typeof fetch !== 'undefined' ? fetch.bind(root) : null);
    const list = candidates(url);
    let lastErr = null;

    if (fetchFn) {
      for (let i = 0; i < list.length; i++) {
        const candidate = list[i];
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            const bytes = await fetchBinary(candidate, fetchFn);
            if (expectXlsx && !looksLikeXlsx(bytes)) {
              lastErr = makeError('not xlsx', { status: 200 });
              break;
            }
            if (typeof document !== 'undefined') {
              saveBlob(new Blob([bytes]), filename);
            }
            return { ok: true, source: candidate, bytes: bytes };
          } catch (err) {
            lastErr = err;
            if (err && err.retryable && attempt < 2) {
              await sleep(opts.sleep === 0 ? 0 : (opts.sleep || (400 * Math.pow(2, attempt))));
              continue;
            }
            break;
          }
        }
      }
    }

    if (typeof document !== 'undefined' && list.length) {
      navigateFallback(list[list.length - 1], filename);
      return { ok: true, source: list[list.length - 1], fallback: true };
    }
    return { ok: false, error: lastErr, source: list[0] || '' };
  }

  function bindLink(anchor, url) {
    if (!anchor) return;
    const href = hrefFor(url);
    const name = filenameFromUrl(url || href);
    anchor.href = href;
    if (isSpreadsheet(name) || isMat(name) || isSpreadsheet(url) || isMat(url)) {
      anchor.setAttribute('download', name);
    }
    anchor.addEventListener('click', function (ev) {
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button) return;
      ev.preventDefault();
      download(url || href, { filename: name }).then(function (result) {
        if (result && result.ok) return;
        if (typeof window !== 'undefined') {
          window.alert('Não foi possível baixar o arquivo agora. O GitHub está congestionado; tente de novo em alguns segundos.');
        }
      });
    });
  }

  const api = {
    REPO: REPO,
    PAGES_BASE: PAGES_BASE,
    RAW_BASE: RAW_BASE,
    parseRepoAsset: parseRepoAsset,
    candidates: candidates,
    hrefFor: hrefFor,
    download: download,
    bindLink: bindLink,
    filenameFromUrl: filenameFromUrl
  };

  root.PREVINE_DOWNLOADS = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
