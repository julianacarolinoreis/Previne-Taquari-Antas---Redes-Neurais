'use strict';
const assert = require('node:assert/strict');
const runtime = require('../assets/js/replay-hidrologico-espacial.js');

assert.deepEqual(runtime.zoomWindow(20, 119, 0.25, 0.75, 200), [45, 94]);
assert.deepEqual(runtime.zoomWindow(100, 199, 0.75, 0.25, 300), [125, 174]);
assert.equal(runtime.time('2023-11-19T00:00:00'), Date.parse('2023-11-19T00:00:00-03:00'));
assert.equal(runtime.nearestIndex([
  ['2023-01-01T00:00:00', 1, 1],
  ['2023-01-01T01:00:00', 2, 2],
], Date.parse('2023-01-01T00:40:00-03:00')), 1);
assert.deepEqual(runtime.gaps([
  ['2023-01-01T00:00:00', 1, 1],
  ['2023-01-01T02:00:00', 2, null],
  ['2023-01-01T03:00:00', 3, 3],
]), {missingHours: 1, missingValues: 1, invalidOrder: 0});
assert.equal(runtime.contourAt({contours:[{level: 18}]}, 17), null);
assert.equal(runtime.contourAt({contours:[{level: 18}]}, 18).level, 18);
assert.ok(runtime.aspect({west:-52,east:-51,north:-28,south:-29}) > 0);
assert.equal(runtime.html('<script>&'), '&lt;script&gt;&amp;');
const ranked = runtime.rankEvents([
  {key:'a',metrics:{lag:-1,peak_error:0.10}},
  {key:'b',metrics:{lag:3,peak_error:0.02}},
  {key:'c',metrics:{lag:null,peak_error:0.30}},
], 'lag', 2);
assert.deepEqual(ranked.map(item=>item.event.key), ['b','a']);
assert.deepEqual(ranked.map(item=>item.value), [3,-1]);
console.log('runtime contract: ok');
