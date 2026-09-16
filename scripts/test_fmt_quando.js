#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fmt = require('../assets/js/fmt_quando.js');

function check(actual, expected, label) {
  assert.strictEqual(actual, expected, `${label}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
}

check(fmt.fmtWhen('2026-09-16T00:00:00'), '16/09 0h', 'meia-noite BRT ingênua');
check(fmt.fmtClock('2026-09-16T00:00:00'), '0h', 'relógio da meia-noite');
check(fmt.fmtWhen('2026-09-16T00:00:00-03:00'), '16/09 0h', 'meia-noite com offset BRT');
check(fmt.fmtWhen('2026-09-16T03:00:00Z'), '16/09 0h', '03:00 UTC vira 0h BRT');
check(fmt.fmtWhen('2026-09-16T00:00:00Z'), '15/09 21h', '00:00 UTC vira 21h do dia anterior');
check(fmt.fmtWhen('2026-09-15T22:00:00'), '15/09 22h', 'hora-base 22h');
check(fmt.fmtWhen('2026-09-16T09:00:00'), '16/09 9h', 'hora cheia sem zero à esquerda');
check(fmt.fmtWhen('2026-09-16T09:45:00'), '16/09 9h45', 'minutos diferentes de zero');
check(fmt.fmtClock('2026-09-16T09:45:00'), '9h45', 'relógio com minutos');
check(fmt.fmtClockDate('2026-09-16T00:00:00'), '16/09 0h BRT', 'data com fuso');
check(fmt.fmtWhen(new Date('2026-09-16T00:00:00-03:00')), '16/09 0h', 'Date object');
check(fmt.fmtWhen(null), '—', 'vazio');
check(fmt.fmtWhen(''), '—', 'string vazia');
check(fmt.fmtWhen('2026-09-16T11:00:00'), '16/09 11h', 'horário atual do feed');

const alvo = fmt.fmtWhen('2026-09-16T00:00:00');
assert.ok(!alvo.includes(':'), 'rótulo da meia-noite não usa 00:00');
assert.ok(!alvo.includes('00h'), 'rótulo da meia-noite não usa 00h');
check(`+2h · para ${alvo}`, '+2h · para 16/09 0h', 'título do cartão simples');

console.log('OK fmt_quando: meia-noite em 0h, sem 00:00');
