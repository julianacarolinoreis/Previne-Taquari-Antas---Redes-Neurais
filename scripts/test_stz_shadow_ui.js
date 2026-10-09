'use strict';
// Regressao: uma base vencida de 2 h nao pode fazer a area do grafico desaparecer.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('assets/js/stz_shadow.js', 'utf8');
async function panel(feed, alternate=null, n5=null) {
  const listeners = {};
  const el = {dataset: {}, innerHTML: '', querySelector: id => ({addEventListener: (_, fn) => {listeners[id] = fn;}})};
  vm.runInNewContext(source, {
    document: {getElementById: id => id === 'stz-shadow-user' ? el : null},
    location: {hostname: alternate ? 'example.org' : 'localhost', hash: ''},
    fetch: async url => ({ok: true, json: async () => n5 && url.includes('stz_n5') ? n5 : alternate && !url.startsWith('https://') ? alternate : feed}),
    Intl, Date, setInterval: () => {}, setTimeout: () => {}
  });
  await new Promise(resolve => setImmediate(resolve));
  return {el, listeners};
}
(async () => {
  const models = [2, 4, 8, 12].flatMap(h => Array.from({length: 13}, (_, i) => ({
    modelo_id: `h${h}_${i}`, nome: `Modelo ${i}`, horizonte_h: h,
    disponivel: false, status: 'ALVO_JA_PASSOU', hora_alvo: '2020-01-01T02:00:00', avaliacao: {}
  })));
  const feed = {gerado_em: new Date().toISOString(), modelos: models, serie_recente: [], historico_registros_n: 0};
  const {el, listeners} = await panel(feed);
  for (const h of [2, 4, 8, 12]) {
    listeners['#shadow-horizon']({target: {value: String(h)}});
    assert.match(el.innerHTML, new RegExp(`Nível previsto e observado · ${h} h`));
    assert.match(el.innerHTML, /<svg class="shadow-chart"/);
    assert.match(el.innerHTML, /Aguardando previsões registradas/);
    assert.match(el.innerHTML, /horário-alvo já passou/);
    assert.equal((el.innerHTML.match(/<tr class=/g) || []).length, 13);
    assert.doesNotMatch(el.innerHTML, /<circle /);
  }
  for (const p of models) {
    p.disponivel = true; p.status = 'OK_SOMBRA'; p.hora_modelo = new Date().toISOString();
    p.hora_alvo = new Date(Date.now() + p.horizonte_h * 3600000).toISOString();
    p.nivel_base_cm = 400; p.nivel_previsto_cm = 450;
  }
  const live = await panel(feed);
  for (const h of [2, 4, 8, 12]) {
    live.listeners['#shadow-horizon']({target: {value: String(h)}});
    assert.match(live.el.innerHTML, /13\/13 modelos com previsão futura disponível/);
    assert.match(live.el.innerHTML, /<circle /);
    assert.equal((live.el.innerHTML.match(/<tr class=/g) || []).length, 13);
  }
  const stale = {...feed, gerado_em: '2020-01-01T02:00:00', modelos: []};
  const newerPage = await panel(stale, feed);
  assert.match(newerPage.el.innerHTML, /13\/13 modelos com previsão futura disponível/);
  const newerRaw = await panel(feed, stale);
  assert.match(newerRaw.el.innerHTML, /13\/13 modelos com previsão futura disponível/);
  for (const p of models) p.teste_historico = {mae_cm: 22.8, persistencia_mae_cm: 55.8};
  const n5 = {gerado_em: new Date().toISOString(), avaliacao: {'168': {n: 3, mae_cm: 12}},
    previsao: {disponivel: true, status: 'OK_SOMBRA', hora_modelo: new Date().toISOString(),
      hora_alvo: new Date(Date.now() + 4 * 3600000).toISOString(), nivel_base_cm: 400, nivel_previsto_cm: 452}};
  const withN5 = await panel({...feed, referencia_n5_teste: {mae_cm: 26.8},
    historico_arquivos: ['assets/data/stz_shadow_history/usuario/2026-10.json']}, null, n5);
  assert.match(withN5.el.innerHTML, /MAE teste histórico/);
  assert.match(withN5.el.innerHTML, /22,8 cm/);
  assert.match(withN5.el.innerHTML, /N5 · MATLAB[\s\S]*4,52 m[\s\S]*26,8 cm/);
  assert.match(withN5.el.innerHTML, /stz_shadow_history\/usuario\/2026-10\.json/);
  assert.equal((withN5.el.innerHTML.match(/<tr class=/g) || []).length, 14);
  withN5.listeners['#shadow-horizon']({target: {value: '8'}});
  assert.doesNotMatch(withN5.el.innerHTML, /N5 · MATLAB/);
  console.log('14 cenarios de interface aprovados: quatro horizontes com dados e espera; fonte mais recente entre Raw e Pages; N5 e erro historico de teste.');
})().catch(error => {console.error(error); process.exitCode = 1;});
