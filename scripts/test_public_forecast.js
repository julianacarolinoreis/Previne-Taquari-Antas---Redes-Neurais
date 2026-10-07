'use strict';
// Contrato de leitura pública: saídas antigas e comparativas nunca viram previsão atual.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const clock = Date.parse('2026-10-07T15:00:00-03:00');
class FixedDate extends Date { static now() { return clock; } }
const context = vm.createContext({window: {PrevineFmtQuando: require('../assets/js/fmt_quando.js')}, Date: FixedDate});
vm.runInContext(fs.readFileSync(path.join(root, 'assets/js/previsao_publica.js'), 'utf8'), context);
const ready = context.window.PREVINE_PUBLIC.isReady;
const valid = {modo:'ao_vivo', hora_modelo:'2026-10-07T14:00:00-03:00', hora_alvo:'2026-10-07T16:00:00-03:00', nivel_previsto_cm:400};
assert.equal(ready('2h', valid), true);
assert.equal(ready('2h', {...valid, nivel_previsto_cm:0}), true);
for (const overrides of [
  {hora_alvo:'2026-10-07T15:00:00-03:00'}, {hora_alvo:'2026-10-07T14:00:00-03:00'},
  {hora_alvo:null}, {hora_modelo:null}, {disponivel:false}, {shadow_only:true},
  {modo:'replay'}, {status:'inputs incompletos'}, {nivel_previsto_cm:null}, {nivel_previsto_cm:'inválido'}
]) assert.equal(ready('2h', {...valid, ...overrides}), false, JSON.stringify(overrides));
assert.equal(ready('2h_versao_b', valid), false);
assert.equal(ready('8h_v002', valid), false);
for (const city of ['santa_tereza', 'mucum']) {
  const html = fs.readFileSync(path.join(root, city+'_previsao_inundacao.html'), 'utf8');
  const prepare = html.match(/function prepareLiveData\(d\)\{[\s\S]*?\n\}/)[0];
  context.liveHz = '2h';
  context.liveData = null;
  context.liveHorizonReady = ready;
  context.updateLiveHzButtons = () => {};
  context.horizonHasForecast = d => d.nivel_previsto_cm != null;
  vm.runInContext(prepare, context);
  const unavailable = {modo:'ao_vivo',horizonte:'2h',passos:[],...valid,
    nivel_previsto_cm:2500,horizontes:{'2h':{disponivel:false},'4h':{disponivel:false},'8h':{disponivel:false}}};
  context.prepareLiveData(unavailable);
  assert.equal(context.liveHz, null, city+': valor residual na raiz não substitui horizonte indisponível');
  assert.equal(unavailable.horizontes['2h'].disponivel, false);
  const alternative = {...unavailable, horizontes:{'2h':{disponivel:false},'4h':valid,'8h':{disponivel:false},'2h_versao_b':valid}};
  context.prepareLiveData(alternative);
  assert.equal(context.liveHz, '4h', city+': fallback seleciona somente previsão principal disponível');
  console.log('OK público '+city+': indisponibilidade preservada e seleção sem comparativas');
}
console.log('OK público: alvo futuro, zero válido, falta de dados, replay e modelos comparativos');
