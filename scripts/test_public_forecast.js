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


// Seleção de +4 h apenas na interface pública de Muçum.
// Dados do robô e interface _usuario continuam com as chaves originais.
const selectPublic4h = require('../assets/js/live_feed.js').selectPublicMucum4h;
const verifiedRows = Array.from({length: 12}, (_, i) => ({erro_abs_cm: i + 1}));
const make4h = (id, mae, level, status = 'NORMAL') => ({
  modelo: id, horizonte: id === '006' ? '4h' : '4h_versao_b',
  disponivel: true, status: 'ok', nivel_previsto_cm: level,
  hora_modelo: '2035-10-09T09:00:00', hora_alvo: '2035-10-09T13:00:00',
  auditoria: {n_conferidas: 289, ultimas_conferidas: verifiedRows},
  qualidade_ao_vivo: {status, mae_24h_cm: mae}
});
const example = {local:'Muçum', horizontes:{
  '2h': {modelo:'2h'},
  '4h': make4h('006', 40.7, 472, 'ATENCAO'),
  '4h_versao_b': make4h('015', 23.5, 423)
}};
const chosen = selectPublic4h(example, true);
assert.equal(chosen.horizontes['4h'].modelo, '015');
assert.equal(chosen.horizontes['4h'].nivel_previsto_cm, 423);
assert.equal(chosen.horizontes['4h'].horizonte, '4h');
assert.equal(chosen.horizontes['4h_versao_b'].modelo, '015');
assert.equal(chosen.selecao_publica_4h.mae_cm, 23.5);
assert.equal(example.horizontes['4h'].modelo, '006', 'feed original não pode ser alterado');
assert.strictEqual(selectPublic4h(example, false), example, 'interface do usuário não seleciona');
const worse = {horizontes:{'4h':make4h('006', 10, 472), '4h_versao_b':make4h('015', 23.5, 423)}};
assert.strictEqual(selectPublic4h(worse, true), worse, 'não escolher RNA com MAE maior');
const stale = {horizontes:{'4h':make4h('006', 40.7, 472), '4h_versao_b':{...make4h('015', 23.5, 423), hora_modelo:'2035-10-09T08:00:00'}}};
assert.strictEqual(selectPublic4h(stale, true), stale, 'não misturar horas-base diferentes');
const noAudit = {horizontes:{'4h':make4h('006', 40.7, 472), '4h_versao_b':{...make4h('015', 23.5, 423), auditoria:{n_conferidas:2,ultimas_conferidas:[]}}}};
assert.strictEqual(selectPublic4h(noAudit, true), noAudit, 'sem histórico suficiente não promover');
const warning = {horizontes:{'4h':make4h('006', 40.7, 472), '4h_versao_b':make4h('015', 23.5, 423, 'ATENCAO')}};
assert.strictEqual(selectPublic4h(warning, true), warning, 'RNA alternativa em atenção não promove');
console.log('OK público Muçum: menor MAE +4h e proteções sem modificar o feed bruto ou página _usuario');
