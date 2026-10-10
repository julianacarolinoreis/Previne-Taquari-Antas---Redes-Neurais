// Test the actual home-page consumers with an explicit synthetic clock and
// station fixture. These are not new measurements or a production snapshot.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const declaration = name => {
  const match = html.match(new RegExp('^  (?:const |(?:async )?function )' + name + '(?:=|\\()[\\s\\S]*?(?=^  (?:const |(?:async )?function |\\(function ))', 'm'));
  assert.ok(match, 'missing actual declaration ' + name);
  return match[0];
};
const names = [
  'basinFinite', 'basinNumber', 'basinLevelNumber', 'basinMedian',
  'basinLevelTrend', 'basinEscape', 'basinStationId', 'basinDate',
  'basinDateTime', 'basinRelativeAge', 'basinNextCycle', 'basinFeedAgeHours',
  'basinObservedAgeMinutes', 'basinObservedAge', 'basinObservedRainAge',
  'basinObservedWindow', 'basinObservedWindowNote', 'basinMinutesNote',
  'basinFormat', 'basinSourceObservationUsable', 'basinSourceObservation',
  'basinCemadenRain24', 'basinSourceObservationLabel', 'basinSourceObservationValue',
  'basinStationAgeNote', 'basinLevelObservedNote', 'basinObservationFreshness',
  'basinFreshnessClass', 'basinStateSummary', 'basinById',
  'basinUpdateStatus', 'basinRefreshFreshness', 'basinMetricStatusLabel',
  'basinMetricCard', 'basinTimelinePeriod', 'basinTimelineObservationNote',
];
const source = names.map(declaration).join('\n');
let now = Date.parse('2026-10-08T17:00:00Z');
class FixtureDate extends Date { static now() { return now; } }
const freshContext = () => {
  now = Date.parse('2026-10-08T17:00:00Z');
  const document = {getElementById: () => null, querySelectorAll: () => []};
  const context = vm.createContext({
    Date: FixtureDate, document,
    BASIN_FEED: {generated_at_utc:'2026-10-07T20:00:00Z'},
    BASIN_FEED_SOURCE:'raw', BASIN_STATIONS:[], BASIN_SELECTED:null,
    BASIN_METRIC_DEFAULTS:[{id:'level_cm',unit:'cm'}, {id:'precipitation',unit:'mm'}],
  });
  vm.runInContext(source + '\nthis.api={' + names.join(',') + '};', context);
  return context;
};
const level = overrides => ({
  state:'available', current_cm:350, observed_at_utc:'2026-10-07T19:06:00Z',
  observed_age_minutes:54, series:[], ...overrides,
});
const rain = overrides => ({
  state:'available', timestamp_role:'interval_start',
  last_closed_interval_end_utc:'2026-10-07T19:00:00Z',
  closed_interval_age_minutes:60, ...overrides,
});
const station = (overrides = {}) => ({id:'ANA:86472600',name:'Fixture',
  level:level(), observed_rain:rain(), ...overrides});

test('a real observation timestamp overrides the saved 54 minutes', () => {
  const {api} = freshContext();
  assert.equal(api.basinObservedAgeMinutes('2026-10-07T19:06:00Z',54),1314);
  assert.equal(api.basinMinutesNote('2026-10-07T19:06:00Z',54),'tempo desde a leitura: 21,9 h');
});
test('saved age advances from generation when the individual timestamp is missing', () => {
  const {api} = freshContext();
  assert.equal(api.basinObservedAgeMinutes(null,54),1314);
  assert.equal(api.basinObservedAgeMinutes('bad',54),1314);
});
test('missing generation cannot turn saved minutes into current freshness', () => {
  const context = freshContext();
  for(const generated of [null,undefined,'bad','2026-10-08T18:00:00Z']){
    context.BASIN_FEED={generated_at_utc:generated};
    assert.equal(context.api.basinObservedAgeMinutes(null,54),null);
  }
});
test('missing, invalid or negative saved minutes remain unknown', () => {
  const {api} = freshContext();
  for(const minutes of [null,undefined,'',NaN,Infinity,-1])
    assert.equal(api.basinObservedAgeMinutes(null,minutes),null);
});
test('a real measured zero age is valid and advances with the clock', () => {
  const context = freshContext();
  context.BASIN_FEED.generated_at_utc='2026-10-08T17:00:00Z';
  assert.equal(context.api.basinObservedAgeMinutes(null,0),0);
  now+=5*60000;
  assert.equal(context.api.basinObservedAgeMinutes(null,0),5);
});
test('future individual timestamps are flagged rather than called recent', () => {
  const {api} = freshContext();
  assert.equal(api.basinMinutesNote('2026-10-08T18:00:00Z',0),'carimbo posterior ao relógio local');
});
test('rain age uses interval end, not panel time or interval start', () => {
  const {api} = freshContext();
  assert.equal(api.basinObservedRainAge(rain({last_observed_at_utc:'2026-10-08T16:59:00Z'})),
    'último intervalo encerrado no calendário há 22,0 h');
});
test('rain without an interval role discloses the individual timestamp instead', () => {
  const {api} = freshContext();
  assert.equal(api.basinObservedRainAge(rain({timestamp_role:null,last_observed_at_utc:'2026-10-08T16:30:00Z'})),
    'último carimbo disponível há 30 min');
});
test('CEMADEN panel time is never substituted for sensor time', () => {
  const {api} = freshContext();
  assert.equal(api.basinObservedAgeMinutes(null,null),null);
  const note=api.basinStationAgeNote(station({level:null,observed_rain:{state:'unavailable'},
    source_observations:[{metric:'chuva_acumulada_24h_mm',value:0,source_status:0,updated_at_utc:'2026-10-08T17:00:00Z'}]}));
  assert.match(note,/série horária de chuva indisponível.*nível indisponível/);
});
test('window dates, partial coverage and unconfirmed points are retained', () => {
  const {api} = freshContext();
  const note=api.basinObservedWindowNote({start_utc:'2026-10-06T19:00:00Z',end_utc:'2026-10-07T19:00:00Z',
    coverage_ratio:0.5,valid_points:12,expected_points:24,complete:false,unconfirmed_points:2},rain());
  assert.match(note,/12\/24 pontos válidos · cobertura 50% · janela parcial/);
  assert.match(note,/2 pontos sem consulta confirmada/);
  assert.match(note,/período 06\/10.*16:00.*07\/10.*16:00/);
  assert.match(note,/22,0 h/);
});
test('the level note keeps the absolute BRT time and dynamically computed age', () => {
  const {api} = freshContext();
  assert.match(api.basinLevelObservedNote(level()),/observado em 07\/10, 16:06 · tempo desde a leitura: 21,9 h/);
  assert.match(api.basinLevelObservedNote(level({observed_at_utc:null})),/horário individual não informado.*21,9 h/);
});

test('timeline rain age advances without changing published timestamps or coverage', () => {
  const {api}=freshContext();
  const selected=station({observed_rain:rain({rows:[{time:'2026-10-07T18:00:00Z',mm:0},{time:'2026-10-07T19:00:00Z',mm:null}]})});
  const before=api.basinTimelineObservationNote(selected,'precipitation');
  assert.match(before,/07\/10\/2026, 15:00 BRT → 07\/10\/2026, 16:00 BRT · 1\/2 horários válidos.*22,0 h/);
  now+=60*60000;
  assert.equal(api.basinTimelineObservationNote(selected,'precipitation'),before.replace('22,0 h','23,0 h'));
  assert.equal(api.basinTimelineObservationNote(selected,'temperature_2m'),'observação direta não publicada para esta estação');
});
test('unavailable or rejected levels cannot appear as usable freshness', () => {
  const {api} = freshContext();
  for(const item of [null,level({state:'unavailable'}),level({current_cm:24907}),level({current_cm:null})])
    assert.equal(api.basinLevelObservedNote(item),'telemetria indisponível');
});
test('valid level trends, zero levels and units are preserved', () => {
  const {api} = freshContext();
  const item=level({current_cm:0,series:[{time:'2026-10-07T18:06:00Z',cm:1},{time:'2026-10-07T19:06:00Z',cm:0}]});
  assert.match(api.basinLevelObservedNote(item),/descendo · -1 cm\/h/);
  assert.match(api.basinStationAgeNote(station({level:item})),/tempo desde a leitura: 21,9 h/);
});
test('global maximum and old-count use all usable individual timestamps', () => {
  const context=freshContext();
  context.BASIN_STATIONS=[station(),station({id:'recent',level:level({observed_at_utc:'2026-10-08T16:30:00Z'})})];
  const summary=context.api.basinObservationFreshness('level');
  assert.equal(summary.max,1314);
  assert.equal(summary.old,1);
  assert.equal(context.api.basinFreshnessClass(summary),'stale');
});
test('unknown and future timestamps never produce a green fresh chip', () => {
  const context=freshContext();
  context.BASIN_STATIONS=[station({level:level({observed_at_utc:null,observed_age_minutes:null})}),
    station({id:'future',level:level({observed_at_utc:'2026-10-08T18:00:00Z'})})];
  const summary=context.api.basinObservationFreshness('level');
  assert.equal(summary.max,null);
  assert.equal(summary.unknown,1);
  assert.equal(summary.future,1);
  assert.equal(context.api.basinFreshnessClass(summary),'muted');
  assert.equal(context.api.basinFreshnessClass(context.api.basinObservationFreshness('rain')),'stale');
});
test('empty and rejected-only observations have unknown, not fresh, age', () => {
  const context=freshContext();
  for(const stations of [[],[station({level:level({current_cm:24907}),observed_rain:{state:'unavailable'}})]]){
    context.BASIN_STATIONS=stations;
    for(const metric of ['rain','level']){
      const summary=context.api.basinObservationFreshness(metric);
      assert.equal(summary.max,null);
      assert.equal(context.api.basinFreshnessClass(summary),'muted');
    }
  }
});
test('the one-hour boundary changes counts as the clock advances, without a new feed', () => {
  const context=freshContext();
  context.BASIN_STATIONS=[station({level:level({observed_at_utc:'2026-10-08T16:00:00Z'})})];
  assert.equal(context.api.basinObservationFreshness('level').old,0);
  now+=60000;
  assert.equal(context.api.basinObservationFreshness('level').old,1);
});
test('partial level observations contribute to aggregate age but rejected scales do not', () => {
  const context=freshContext();
  context.BASIN_STATIONS=[station({level:level({state:'partial'})}),station({id:'bad',level:level({current_cm:24907})})];
  assert.equal(context.api.basinObservationFreshness('level').old,1);
});
test('status recomputes actual age instead of using frozen aggregate metadata', () => {
  const context=freshContext();
  const status={innerHTML:''};
  context.document.getElementById=id=>id==='map-status'?status:null;
  context.BASIN_FEED.scope={station_count:1,level_station_count:1,observed_rain_hourly_station_count:1};
  context.BASIN_FEED.freshness={level_max_age_minutes:54,level_over_60min_count:0};
  context.BASIN_STATIONS=[station()];
  context.api.basinUpdateStatus();
  assert.match(status.innerHTML,/map-status-chip stale.*níveis: máx 21,9 h · 1 &gt;1h/);
  assert.match(status.innerHTML,/chuva · último intervalo encerrado: máx 22 h/);
  assert.ok(!status.innerHTML.includes('níveis: máx 54 min'));
});
test('refresh updates observation text, preserves controls, chart and raw data', () => {
  const context=freshContext();
  const selected=station({observed_rain:rain({rows:[{time:'2026-10-07T18:00:00Z',mm:0}]})});
  const original=JSON.stringify(selected);
  context.BASIN_SELECTED=selected;
  context.BASIN_STATIONS=[selected];
  const state={dataset:{basinAgeStation:selected.id},classList:{contains:()=>true}};
  const quality={dataset:{basinAgeStation:selected.id},classList:{contains:()=>false}};
  const levelNote={dataset:{basinObservedNote:'level'}};
  const rainNote={dataset:{basinObservedNote:'rain24'}};
  const timelineNote={dataset:{basinObservedTimeline:'precipitation'}};
  const popupLevel={},popupRain={};
  const popup={dataset:{basinAgeStation:selected.id},querySelector:selector=>selector==='[data-basin-popup-level]'?popupLevel:popupRain};
  const focusedButton={id:'keyboard-focus'};
  context.document.activeElement=focusedButton;
  context.document.querySelectorAll=selector=>selector.startsWith('.st-state')?[state,quality]
    :selector==='[data-basin-observed-note]'?[levelNote,rainNote]:selector==='[data-basin-observed-timeline]'?[timelineNote]:selector.startsWith('.basin-popup')?[popup]:[];
  context.api.basinRefreshFreshness();
  assert.match(quality.textContent,/21,9 h/);
  assert.match(levelNote.textContent,/21,9 h/);
  assert.match(popupLevel.textContent,/21,9 h/);
  assert.match(popupRain.textContent,/22,0 h/);
  assert.match(timelineNote.textContent,/22,0 h/);
  now+=60*60000;
  context.api.basinRefreshFreshness();
  assert.match(quality.textContent,/22,9 h/);
  assert.match(levelNote.textContent,/22,9 h/);
  assert.match(popupLevel.textContent,/22,9 h/);
  assert.match(popupRain.textContent,/23,0 h/);
  assert.match(timelineNote.textContent,/23,0 h/);
  assert.equal(context.document.activeElement,focusedButton);
  assert.equal(context.BASIN_SELECTED,selected);
  assert.equal(JSON.stringify(selected),original);
  const refresh=declaration('basinRefreshFreshness');
  for(const prohibited of ['basinRenderDetail(', 'basinRenderChart(', 'basinRenderMarkers(', 'basinRenderStationList(', '.focus(', '.innerHTML=', 'fetch('])
    assert.ok(!refresh.includes(prohibited),'clock refresh must not '+prohibited);
});
test('same, older and failed fetches refresh ages without replacing selection', () => {
  const load=declaration('basinLoadFeed');
  assert.match(load,/Date\.parse\(data\.generated_at_utc\)<[\s\S]*?basinRefreshFreshness\(\);\s*return;/);
  assert.match(load,/data\.generated_at_utc===BASIN_FEED\.generated_at_utc[\s\S]*?basinRefreshFreshness\(\);\s*return;/);
  assert.match(load,/catch\(error\)\{\s*basinRefreshFreshness\(\);/);
});
test('clock updates have a separate one-minute timer and do not accelerate network polling', () => {
  assert.ok(html.includes('setInterval(basinRefreshFreshness,60*1000);'));
  assert.ok(html.includes('setInterval(basinLoadFeed,5*60*1000);'));
  assert.ok(html.includes("BASIN_MAP.on('popupopen',basinRefreshFreshness);"));
  assert.ok(html.includes('if(!document.hidden){basinRefreshFreshness();basinLoadFeed();}'));
});
test('observation note bindings are explicit and escaped', () => {
  const {api}=freshContext();
  assert.match(api.basinMetricCard('Fixture','0 cm','<note>','complete','level'),/data-basin-observed-note="level"[^>]*>&lt;note&gt;/);
  assert.ok(!api.basinMetricCard('Fixture','0 mm','note','complete').includes('data-basin-observed-note'));
});
test('all inline scripts remain syntactically valid', () => {
  let count=0;
  for(const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)){
    if(/\bsrc\s*=/.test(match[1]))continue;
    if(/\btype\s*=\s*["']application\/(?:ld\+)?json["']/.test(match[1])){
      JSON.parse(match[2]);
      continue;
    }
    try{ new vm.Script(match[2],{filename:'inline-script-'+count,displayErrors:false}); }
    catch(error){ assert.fail('inline-script-'+count+': '+error.message); }
    count++;
  }
  assert.ok(count>=4,'expected actual page scripts');
});
