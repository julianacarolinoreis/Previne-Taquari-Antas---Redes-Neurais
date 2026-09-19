#!/usr/bin/env node
'use strict';

const assert = require('assert');
const feed = require('../assets/js/live_feed.js');

function check(actual, expected, label) {
  assert.strictEqual(actual, expected, `${label}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
}

const pages = { consultado_em: '2026-09-15T23:54:34', telemetria_ultima_em: '2026-09-15T22:45:00' };
const github = { consultado_em: '2026-09-16T19:37:50', telemetria_ultima_em: '2026-09-16T18:45:00' };

assert.ok(feed.stampMs(github) > feed.stampMs(pages), 'consulta do GitHub é mais nova que a do Pages');
check(feed.pickNewest([pages, github]), github, 'escolhe o feed com consultado_em mais novo');
check(feed.pickNewest([github, pages, null]), github, 'ignora fonte vazia');
check(feed.pickNewest([pages]), pages, 'uma fonte só');
check(feed.pickNewest([]), null, 'nenhuma fonte');
const staleCached = { consultado_em: '2026-09-16T19:37:50', status: 'ok' };
const failedNewRevision = {
  consultado_em: '2026-09-16T19:37:50',
  ultima_tentativa_em: '2026-09-16T20:10:00',
  ultima_tentativa_status: 'falha',
  status: 'aguardando nova telemetria'
};
check(feed.pickNewest([staleCached, failedNewRevision]), failedNewRevision, 'revisão de falha mais nova vence cache com mesmo consultado_em');
check(
  feed.pickNewest([{ atualizado_em: '2026-09-16T19:37:50' }, { consultado_em: '2026-09-15T23:54:34' }]).atualizado_em,
  '2026-09-16T19:37:50',
  'histórico usa atualizado_em'
);

const sources = feed.sourcesFor('previsao_ao_vivo.json');
check(sources.length, 4, 'quatro fontes');
check(sources[0].url, 'previsao_ao_vivo.json', 'Pages relativo');
assert.ok(sources[1].url.includes('/main/previsao_ao_vivo.json'), 'Raw GitHub');
assert.ok(sources[2].url.includes('jsdelivr.net/gh/'), 'CDN jsDelivr');
assert.ok(sources[3].url.includes('/contents/previsao_ao_vivo.json'), 'API GitHub');
assert.ok(!sources[0].url.includes('22:45'), 'fonte local não é o snapshot velho');
check(feed.primarySources(sources).length, 3, 'API fica de reserva');
check(feed.apiSources(sources).length, 1, 'uma fonte API');

const mucum = feed.sourcesFor('assets/foo/previsao_ao_vivo_mucum.json?cb=1');
check(mucum[0].url, 'previsao_ao_vivo_mucum.json', 'usa só o nome do arquivo');

function jsonOk(data) {
  return {
    ok: true,
    status: 200,
    json: async function () { return data; }
  };
}

function httpErr(status) {
  return {
    ok: false,
    status: status,
    json: async function () { throw new Error('HTTP ' + status); }
  };
}

function sourceOf(url) {
  const s = String(url);
  if (s.includes('api.github.com')) return 'api';
  if (s.includes('raw.githubusercontent.com')) return 'raw';
  if (s.includes('jsdelivr.net')) return 'cdn';
  if (s.includes('previsao_ao_vivo.json')) return 'pages';
  return 'other';
}

async function withFetch(mock, fn) {
  const prev = global.fetch;
  global.fetch = mock;
  try { return await fn(); }
  finally { global.fetch = prev; }
}

(async function () {
  const newest = await withFetch(async function (url) {
    const kind = sourceOf(url);
    if (kind === 'pages') return jsonOk(pages);
    if (kind === 'raw' || kind === 'cdn') return jsonOk(github);
    return httpErr(403);
  }, function () { return feed.fetchLive('previsao_ao_vivo.json'); });
  check(newest, github, 'Pages 22:45 perde para o GitHub 18:45');

  const after404 = await withFetch(async function (url) {
    const kind = sourceOf(url);
    if (kind === 'pages') return httpErr(404);
    if (kind === 'raw') return jsonOk(github);
    if (kind === 'cdn') return jsonOk(pages);
    return httpErr(403);
  }, function () { return feed.fetchLive('previsao_ao_vivo.json'); });
  check(after404, github, 'Pages 404 ainda lê o Raw fresco');

  const viaApi = await withFetch(async function (url) {
    const kind = sourceOf(url);
    if (kind === 'api') {
      const body = Buffer.from(JSON.stringify(github), 'utf8').toString('base64');
      return jsonOk({ content: body, encoding: 'base64' });
    }
    return httpErr(502);
  }, function () { return feed.fetchLive('previsao_ao_vivo.json'); });
  check(viaApi.consultado_em, github.consultado_em, 'API entra só quando Pages/Raw/CDN falham');

  console.log('OK live_feed: Pages velho perde para o GitHub mais novo');
})().catch(function (err) {
  console.error(err);
  process.exit(1);
});
