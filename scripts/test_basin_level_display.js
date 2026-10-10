// Unit regression for the actual home-page level consumers, without a browser.
// Rejected vertical measurements stay missing; they must never become zero.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const names = ['basinFinite', 'basinNumber', 'basinLevelNumber', 'basinSourceObservationUsable'];
const declarations = names.map(name => {
  const match = html.match(new RegExp('  const ' + name + '=([^\\n]+)'));
  assert.ok(match, 'missing actual helper ' + name);
  return 'const ' + name + '=' + match[1];
});
declarations.push(html.slice(html.indexOf('  const basinMedian='), html.indexOf('  const basinModelSpecs=')));
declarations.push(html.slice(html.indexOf('  const basinLevelTrend='), html.indexOf('  const basinSourceObservationUsable=')));
const observed = html.slice(html.indexOf('  const basinTimelineObservedRows='), html.indexOf('  const basinObservedRowTime='));
const forecast = html.slice(html.indexOf('  const basinTimelineForecastRows='), html.indexOf('  const basinTimelineDetail='));
const source = html.slice(html.indexOf('  const basinHasAnyObserved='), html.indexOf('  const basinObservedWindowNote='));
const context = vm.createContext({});
vm.runInContext(declarations.join('\n') + observed + forecast + source + '\nthis.levelNumber=basinLevelNumber;this.levelTrend=basinLevelTrend;this.observed=basinTimelineObservedRows;this.forecast=basinTimelineForecastRows;this.anyObserved=basinHasAnyObserved;this.sourceValue=basinSourceObservationValue;', context);
for (const invalid of [null, '', undefined, NaN, Infinity, -1, 5001, 24907]) {
  assert.equal(context.levelNumber(invalid), null);
}
for (const valid of [0, 350, 5000]) assert.equal(context.levelNumber(valid), valid);
const station = {level: {
  state: 'available', // legacy producer can incorrectly leave this available
  current_cm: 24907,
  series: [{time: '2026-10-02T12:00Z', cm: 350}, {time: '2026-10-02T13:00Z', cm: 24907}],
  forecasts: [{time: '2099-01-01T12:00Z', cm: 24908}, {time: '2099-01-01T13:00Z', cm: 360}],
}};
const observedRows = context.observed(station, 'level_cm');
assert.equal(observedRows.length, 1);
assert.equal(observedRows[0].value, 350);
const forecastRows = context.forecast(station, 'level_cm', 6);
assert.equal(forecastRows.length, 1);
assert.equal(forecastRows[0].value, 360);
station.level.series = [{time: '2026-10-02T13:00Z', cm: 24907}];
station.level.forecasts = [{time: '2099-01-01T12:00Z', cm: 24908}];
assert.equal(context.observed(station, 'level_cm').length, 0);
assert.equal(context.forecast(station, 'level_cm', 6).length, 0);
assert.equal(context.anyObserved(station), false);
station.source_observations = [{value: 250, source_status: 1, unit: 'm'}];
assert.equal(context.anyObserved(station), false);
assert.match(context.sourceValue(station.source_observations[0]), /indisponível.*valor bruto.*não utilizável/);
station.source_observations[0].source_status = 0;
assert.equal(context.anyObserved(station), true);
assert.equal(context.sourceValue(station.source_observations[0]), '250 m');
station.source_observations[0].metric = 'chuva_acumulada_24h_mm';
station.source_observations[0].value = -1;
assert.equal(context.anyObserved(station), false);
assert.ok(html.includes('value:basinLevelNumber(row&&row.cm)'));
assert.ok(html.includes('value:basinLevelNumber(item&&item.cm)'));
assert.ok(html.includes("observedLevelUsable?'complete':'unavailable'"));
const legacyMixed = {
  state: 'available', current_cm: 350, observed_at_utc: '2026-10-02T13:00Z',
  series: [{time: '2026-10-02T12:00Z', cm: 25000}, {time: '2026-10-02T13:00Z', cm: 350}],
  trend_cm_per_hour: -24650, trend_label: 'descendo',
};
const original = JSON.stringify(legacyMixed);
const rejectedTrend = context.levelTrend(legacyMixed);
assert.equal(rejectedTrend.value, null);
assert.equal(rejectedTrend.label, null);
assert.equal(rejectedTrend.raw_value, -24650);
assert.equal(JSON.stringify(legacyMixed), original, 'do not mutate raw snapshot');
assert.ok(html.includes('const trend=basinLevelTrend(level);'));
assert.ok(html.includes('const levelNote=basinLevelObservedNote(level);'));
assert.ok(html.includes("levelNote,observedLevelUsable?'complete':'unavailable','level'"));
assert.ok(!html.includes('observedLevelUsable&&level.trend_label'));
const validTrend = {...legacyMixed, series: [
  {time:'2026-10-02T13:00Z',cm:350}, // deliberately unsorted
  {time:'2026-10-02T12:00Z',cm:360},
  {time:'2026-10-02T11:00Z',cm:25000},
]};
assert.equal(context.levelTrend(validTrend).value, -10, 'legitimate negative rate remains valid');
assert.equal(context.levelTrend(validTrend).label, 'descendo');
assert.equal(context.levelTrend({...validTrend, current_cm:5001}).value, null);
assert.equal(context.levelTrend({...validTrend, observed_at_utc:'2026-10-02T14:00Z'}).value, null);
assert.equal(context.levelTrend({...validTrend, current_cm:400}).value, null);
const fromZero={...validTrend,current_cm:0,series:[{time:'2026-10-02T12:00Z',cm:1},{time:'2026-10-02T13:00Z',cm:0}]};
assert.equal(context.levelTrend(fromZero).value, -1);
assert.equal(context.levelTrend({...fromZero,series:[...fromZero.series,fromZero.series[1]]}).value, -1);
assert.equal(context.levelTrend({...fromZero,series:[...fromZero.series,{time:'2026-10-02T13:00Z',cm:1}]}).value, null);
assert.equal(context.levelTrend({...fromZero,series:[{time:'bad',cm:350},fromZero.series[1]]}).value, null);
assert.equal(context.levelTrend({...fromZero,series:[{time:'2026-10-02T12:00Z',cm:0},fromZero.series[1]]}).label, 'estável');
console.log('OK basin_level_display: suspect scale and unsupported legacy trends cannot leak into level cards, timeline or chart points');
