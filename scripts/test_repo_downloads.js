'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const api = require('../assets/js/repo_downloads.js');

const XLSX = 'assets/audit_workbooks/4H_ALT__020_alt_MUC_H04_V30_LJJ_CA_CHUVA_AUDITADO_SEM32_R05_T33_V18-20-21.xlsx';
const MAT = 'assets/mat/001_alt_STZ_2H_R01_T12_V1-5-10-15-17-21.mat';
const PK = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00]);
const HTML_503 = new TextEncoder().encode('<html>Error 503 Backend.max_conn reached</html>');

test('xlsx prefers GitHub Pages over raw.githubusercontent.com', () => {
  const list = api.candidates(XLSX);
  assert.equal(list[0], api.PAGES_BASE + XLSX);
  assert.ok(list.includes(api.RAW_BASE + 'main/' + XLSX));
  assert.ok(!list[0].includes('raw.githubusercontent.com'));
});

test('rewrites pinned raw.githubusercontent.com workbook URLs to Pages', () => {
  const raw = 'https://raw.githubusercontent.com/julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais/a31c12e/' + XLSX;
  const href = api.hrefFor(raw);
  assert.equal(href, api.PAGES_BASE + XLSX);
  const list = api.candidates(raw);
  assert.equal(list[0], api.PAGES_BASE + XLSX);
  assert.ok(list.includes(api.RAW_BASE + 'a31c12e/' + XLSX));
  assert.ok(list.includes(api.RAW_BASE + 'main/' + XLSX));
});

test('mat files stay on raw.githubusercontent.com because Pages omits them', () => {
  const list = api.candidates(MAT);
  assert.equal(list[0], api.RAW_BASE + 'main/' + MAT);
  assert.ok(list.every((url) => !url.includes('github.io')));
});

test('download retries 503 HTML and then uses Pages bytes', async () => {
  const calls = [];
  const fetchMock = async (url) => {
    calls.push(url);
    if (url.includes('github.io') && calls.filter((item) => item === url).length < 2) {
      return {
        status: 503,
        ok: false,
        arrayBuffer: async () => HTML_503
      };
    }
    if (url.includes('github.io')) {
      return { status: 200, ok: true, arrayBuffer: async () => PK };
    }
    throw new Error('should not need raw');
  };
  const result = await api.download(XLSX, { fetch: fetchMock, sleep: 0, filename: 'planilha.xlsx' });
  assert.equal(result.ok, true);
  assert.equal(result.source, api.PAGES_BASE + XLSX);
  assert.ok(calls.length >= 2);
});

test('download falls back to raw when Pages returns 404', async () => {
  const fetchMock = async (url) => {
    if (url.includes('github.io')) {
      return { status: 404, ok: false, arrayBuffer: async () => new Uint8Array() };
    }
    return { status: 200, ok: true, arrayBuffer: async () => PK };
  };
  const result = await api.download(XLSX, { fetch: fetchMock, sleep: 0, filename: 'planilha.xlsx' });
  assert.equal(result.ok, true);
  assert.equal(result.source, api.RAW_BASE + 'main/' + XLSX);
});

test('rejects GitHub 503 HTML so it is not saved as xlsx', async () => {
  const fetchMock = async () => ({
    status: 200,
    ok: true,
    arrayBuffer: async () => HTML_503
  });
  const result = await api.download(XLSX, { fetch: fetchMock, sleep: 0, filename: 'planilha.xlsx' });
  assert.equal(result.ok, false);
});

test('index.html loads the helper and no longer prefixes workbooks with raw main', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  assert.match(html, /assets\/js\/repo_downloads\.js/);
  assert.doesNotMatch(
    html,
    /const WB_RAW='https:\/\/raw\.githubusercontent\.com\/julianacarolinoreis\/Previne-Taquari-Antas---Redes-Neurais\/main\/'/
  );
  assert.match(html, /PREVINE_DOWNLOADS/);
  assert.match(html, /startWorkbookDownload/);
});
