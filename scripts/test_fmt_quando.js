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
check(fmt.fmtWhen('2026-09-15T22:45:00'), '15/09 22h45', 'leitura 22h45 sem dois-pontos');
check(fmt.fmtClock('2026-09-15T22:45:00'), '22h45', 'relógio 22h45');
check(fmt.fmtClockDate('2026-09-16T00:00:00'), '16/09 0h BRT', 'data com fuso');
check(fmt.fmtWhen(new Date('2026-09-16T00:00:00-03:00')), '16/09 0h', 'Date object');
check(fmt.fmtWhen(null), '—', 'vazio');
check(fmt.fmtWhen(''), '—', 'string vazia');
check(fmt.fmtWhen('2026-09-16T11:00:00'), '16/09 11h', 'horário atual do feed');

const alvo = fmt.fmtWhen('2026-09-16T00:00:00');
assert.ok(!alvo.includes(':'), 'rótulo da meia-noite não usa 00:00');
assert.ok(!alvo.includes('00h'), 'rótulo da meia-noite não usa 00h');
check(`+2h · para ${alvo}`, '+2h · para 16/09 0h', 'título do cartão simples');
check(fmt.fmtWhen(new Date('2026-09-16T00:00:00-03:00')), '16/09 0h', 'eixo 24h na meia-noite');
check(fmt.fmtClock(new Date('2026-09-16T03:48:00-03:00')), '3h48', 'tick curto do eixo');

check(fmt.fmtDuration(800), '13 h 20 min', '800 min não parece horário');
check(fmt.fmtDuration(870), '14 h 30 min', '870 min');
check(fmt.fmtDuration(13), '13 min', 'só minutos');
check(fmt.fmtDuration(60), '1 h', 'hora cheia');
check(fmt.fmtDuration(61), '1 h 1 min', 'hora e minuto');
check(fmt.fmtDuration(0), '0 min', 'zero minutos');
check(fmt.fmtDuration(null), '—', 'duração vazia');
check(fmt.fmtAge(800), 'há 13 h 20 min', 'idade do robô');
check(fmt.fmtAge(45), 'há 45 min', 'idade em minutos');
check(fmt.fmtAge(0), 'agora', 'idade zero');
check(fmt.fmtAge(null), 'idade indisponível', 'idade nula');

const clock = fmt.fmtWhen('2026-09-15T22:45:00');
const liveBar = clock + '\n⚠ robô sem publicar ' + fmt.fmtAge(800) + '\nANA sem hora nova ' + fmt.fmtAge(870);
check(liveBar, '15/09 22h45\n⚠ robô sem publicar há 13 h 20 min\nANA sem hora nova há 14 h 30 min', 'banner ao vivo');
assert.ok(!liveBar.includes(':'), 'banner ao vivo não mistura relógio com dois-pontos');
assert.ok(!/\d+h\d+/.test(fmt.fmtDuration(800)), 'duração não cola hora e minuto como relógio');
assert.ok(!/\d+h\d+/.test(fmt.fmtAge(870)), 'idade não cola hora e minuto como relógio');
assert.ok(!fmt.fmtWhen('2026-09-15T22:45:00').includes('22:45'), 'leitura não usa 22:45');

console.log('OK fmt_quando: meia-noite em 0h, 22h45 e duração 13 h 20 min');
