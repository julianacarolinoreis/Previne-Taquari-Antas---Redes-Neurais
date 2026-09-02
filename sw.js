/* PREVINE · cache mínimo para centro de resposta e modo campo (pesquisa offline parcial). */
var CACHE = 'previne-resposta-v2';
var SHELL = [
  '/pesquisas/centro-resposta.html',
  '/pesquisas/modo-campo.html',
  '/pesquisas/estudo-caso-resposta-mucum.html',
  '/pesquisas/exposicao-cruzada.html',
  '/previsao_ao_vivo.json',
  '/previsao_ao_vivo_mucum.json',
  '/assets/data/exposicao_cruzada/exposicao_mucum.json',
  '/assets/data/exposicao_cruzada/indice.json',
  '/assets/data/estudo_caso_resposta_mucum_v002.json',
  '/assets/js/mesa_mucum_v002.js',
  '/assets/js/ficha_jusante.js',
  '/pesquisa_status_encantado.html',
  '/assets/js/resposta_operacional.js',
  '/assets/js/gestor_chrome.js',
  '/assets/css/gestor_chrome.css'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(SHELL.map(function (url) {
        return new Request(url, { cache: 'reload' });
      })).catch(function () { /* partial warm ok */ });
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) {
        return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  var path = url.pathname;
  var isShell = SHELL.indexOf(path) >= 0;
  var isLive = /previsao_ao_vivo/.test(path);
  if (isLive) {
    event.respondWith(
      fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (cache) { cache.put(req, copy); });
        }
        return res;
      }).catch(function () { return caches.match(req); })
    );
    return;
  }
  if (!isShell && !/\.(js|css|html|json)$/.test(path)) return;
  event.respondWith(
    caches.match(req).then(function (cached) {
      var network = fetch(req).then(function (res) {
        if (res && res.ok && (isShell || /\.(js|css)$/.test(path))) {
          var copy = res.clone();
          caches.open(CACHE).then(function (cache) { cache.put(req, copy); });
        }
        return res;
      });
      return cached || network;
    })
  );
});
