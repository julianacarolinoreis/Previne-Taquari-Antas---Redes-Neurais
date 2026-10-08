'use strict';
// Regressao: uma base vencida de 2 h nao pode fazer a area do grafico desaparecer.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('assets/js/stz_shadow.js', 'utf8');
async function panel(feed) {
  const listeners = {};
  const el = {dataset: {}, innerHTML: '', querySelector: id => ({addEventListener: (_, fn) => {listeners[id] = fn;}})};
  vm.runInNewContext(source, {
    document: {getElementById: id => id === 'stz-shadow-user' ? el : null},
    location: {hostname: 'localhost', hash: ''},
    fetch: async () => ({ok: true, json: async () => feed}),
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
  console.log('8 cenarios de interface aprovados: 2/4/8/12 h com dados e aguardando dados.');
})().catch(error => {console.error(error); process.exitCode = 1;});
