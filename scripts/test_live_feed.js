#!/usr/bin/env node
'use strict';

const assert = require('assert');
const feed = require('../assets/js/live_feed.js');

function check(actual, expected, label) {
  assert.strictEqual(actual, expected, `${label}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
}

const pages = { consultado_em: '2026-09-15T23:54:34', telemetria_ultima_em: '2026-09-15T22:45:00' };
const github = { consultado_em: '2026-09-16T15:32:50', telemetria_ultima_em: '2026-09-16T14:45:00' };

assert.ok(feed.stampMs(github) > feed.stampMs(pages), 'consulta do GitHub é mais nova que a do Pages');
check(feed.pickNewest([pages, github]), github, 'escolhe o feed com consultado_em mais novo');
check(feed.pickNewest([github, pages, null]), github, 'ignora fonte vazia');
check(feed.pickNewest([pages]), pages, 'uma fonte só');
check(feed.pickNewest([]), null, 'nenhuma fonte');

const sources = feed.sourcesFor('previsao_ao_vivo.json');
check(sources.length, 3, 'três fontes');
check(sources[0].url, 'previsao_ao_vivo.json', 'Pages relativo');
assert.ok(sources[1].url.includes('/contents/previsao_ao_vivo.json'), 'API GitHub');
assert.ok(sources[2].url.includes('/main/previsao_ao_vivo.json'), 'Raw GitHub');
assert.ok(!sources[0].url.includes('22:45'), 'fonte local não é o snapshot velho');

const mucum = feed.sourcesFor('assets/foo/previsao_ao_vivo_mucum.json?cb=1');
check(mucum[0].url, 'previsao_ao_vivo_mucum.json', 'usa só o nome do arquivo');

console.log('OK live_feed: Pages velho perde para o GitHub mais novo');
