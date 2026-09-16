(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.PrevineFmtQuando = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const TZ = 'America/Sao_Paulo';

  function parseWhen(value) {
    if (!value && value !== 0) return null;
    if (value instanceof Date) return Number.isFinite(value.getTime()) ? value : null;
    const raw = String(value).trim().replace(' ', 'T');
    if (!raw) return null;
    const zoned = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw + '-03:00';
    const date = new Date(zoned);
    return Number.isFinite(date.getTime()) ? date : null;
  }

  function part(parts, type) {
    const found = parts.find(function (item) { return item.type === type; });
    return found ? found.value : null;
  }

  function clockLabel(date) {
    const parts = new Intl.DateTimeFormat('pt-BR', {
      timeZone: TZ,
      hour: 'numeric',
      minute: '2-digit',
      hourCycle: 'h23'
    }).formatToParts(date);
    const hourRaw = part(parts, 'hour');
    const minute = part(parts, 'minute') || '00';
    const hour = hourRaw == null ? NaN : Number(hourRaw);
    if (!Number.isFinite(hour)) return '—';
    return minute === '00' ? hour + 'h' : hour + 'h' + minute;
  }

  function fmtClock(value) {
    const date = parseWhen(value);
    return date ? clockLabel(date) : '—';
  }

  function fmtWhen(value) {
    const date = parseWhen(value);
    if (!date) return '—';
    const parts = new Intl.DateTimeFormat('pt-BR', {
      timeZone: TZ,
      day: '2-digit',
      month: '2-digit',
      hourCycle: 'h23'
    }).formatToParts(date);
    const day = part(parts, 'day');
    const month = part(parts, 'month');
    if (!day || !month) return '—';
    return day + '/' + month + ' ' + clockLabel(date);
  }

  function fmtClockDate(value) {
    const date = parseWhen(value);
    return date ? fmtWhen(date) + ' BRT' : '—';
  }

  // Duração (13 h 20 min) fica diferente do relógio (13h20 / 22h45).
  function fmtDuration(minutes) {
    if (minutes === null || minutes === undefined || minutes === '') return '—';
    const mins = Math.round(Number(minutes));
    if (!Number.isFinite(mins) || mins < 0) return '—';
    const hours = Math.floor(mins / 60);
    const rest = mins % 60;
    if (hours > 0 && rest) return hours + ' h ' + rest + ' min';
    if (hours > 0) return hours + ' h';
    return rest + ' min';
  }

  function fmtAge(minutes) {
    if (minutes === null || minutes === undefined) return 'idade indisponível';
    const mins = Math.round(Number(minutes));
    if (!Number.isFinite(mins) || mins < 0) return 'idade indisponível';
    if (mins < 1) return 'agora';
    return 'há ' + fmtDuration(mins);
  }

  return {
    parseWhen: parseWhen,
    fmtClock: fmtClock,
    fmtWhen: fmtWhen,
    fmtWhenDate: fmtWhen,
    fmtClockDate: fmtClockDate,
    fmtDuration: fmtDuration,
    fmtAge: fmtAge
  };
});
