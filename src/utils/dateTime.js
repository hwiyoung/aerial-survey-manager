const APP_TIME_ZONE = 'Asia/Seoul';

export function parseBackendDate(value) {
  if (!value) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value !== 'string') {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  const trimmed = value.trim();
  if (!trimmed) return null;

  // Backend datetimes are stored with datetime.utcnow() and serialized without TZ.
  // Treat timezone-less ISO strings as UTC before rendering them in KST.
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const normalized = hasTimezone ? trimmed : `${trimmed}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatKstDate(value) {
  const date = parseBackendDate(value);
  if (!date) return '';
  return date.toLocaleDateString('ko-KR', {
    timeZone: APP_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

export function formatKstDateTime(value, { withYear = true, withSeconds = false } = {}) {
  const date = parseBackendDate(value);
  if (!date) return '';
  return date.toLocaleString('ko-KR', {
    timeZone: APP_TIME_ZONE,
    hour12: false,
    ...(withYear ? { year: 'numeric' } : {}),
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  });
}

export function formatKstTime(value) {
  const date = parseBackendDate(value);
  if (!date) return '-';
  return date.toLocaleTimeString('ko-KR', {
    timeZone: APP_TIME_ZONE,
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatDuration(startedAt, completedAt) {
  const start = parseBackendDate(startedAt);
  const end = parseBackendDate(completedAt);
  if (!start || !end || end < start) return '';

  const totalMinutes = Math.round((end.getTime() - start.getTime()) / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `${hours}시간 ${minutes}분`;
  return `${minutes}분`;
}
