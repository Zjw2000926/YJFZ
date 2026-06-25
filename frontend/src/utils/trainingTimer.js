export function getPositiveInt(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function calculateTimeLeftSeconds(startedAt, limitMinutes, nowMs = Date.now()) {
  const limitSeconds = (getPositiveInt(limitMinutes) || 8) * 60;
  const startedMs = Date.parse(startedAt || "");
  if (!Number.isFinite(startedMs)) return limitSeconds;
  return Math.max(0, Math.ceil((startedMs + limitSeconds * 1000 - nowMs) / 1000));
}

export function getTrainingTimerEndMs(record, fallbackLimitMinutes) {
  const limitMinutes = getPositiveInt(record?.time_limit_minutes) || getPositiveInt(fallbackLimitMinutes) || 8;
  const startedMs = Date.parse(record?.started_at || "");
  return Number.isFinite(startedMs) ? startedMs + limitMinutes * 60 * 1000 : Date.now() + limitMinutes * 60 * 1000;
}

export function isTrainingRecordExpired(record, fallbackLimitMinutes, nowMs = Date.now()) {
  if (!record || record.status !== "in_progress") return false;
  return calculateTimeLeftSeconds(record.started_at, record.time_limit_minutes || fallbackLimitMinutes, nowMs) <= 0;
}

export function formatCountdownTime(seconds) {
  const safeSeconds = Math.max(0, Number(seconds) || 0);
  return `${String(Math.floor(safeSeconds / 60)).padStart(2, "0")}:${String(safeSeconds % 60).padStart(2, "0")}`;
}
