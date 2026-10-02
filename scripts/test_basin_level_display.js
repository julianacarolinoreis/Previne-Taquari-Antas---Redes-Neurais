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
const observed = html.slice(html.indexOf('  const basinTimelineObservedRows='), html.indexOf('  const basinObservedRowTime='));
const forecast = html.slice(html.indexOf('  const basinTimelineForecastRows='), html.indexOf('  const basinTimelineDetail='));
const source = html.slice(html.indexOf('  const basinHasAnyObserved='), html.indexOf('  const basinObservedWindowNote='));
const context = vm.createContext({});
vm.runInContext(declarations.join('\n') + observed + forecast + source + '\nthis.levelNumber=basinLevelNumber;this.observed=basinTimelineObservedRows;this.forecast=basinTimelineForecastRows;this.anyObserved=basinHasAnyObserved;this.sourceValue=basinSourceObservationValue;', context);
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
console.log('OK basin_level_display: suspect scale cannot leak into level cards, timeline or chart points');
