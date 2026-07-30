/**
 * Format a large number with locale commas.
 */
export function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

/**
 * Format a percentage value to one decimal place.
 */
export function formatPercent(n: number, decimals = 1): string {
  return `${n.toFixed(decimals)}%`;
}

/**
 * Format a growth factor to one decimal place with "×" suffix.
 */
export function formatGrowthFactor(n: number): string {
  return `${n.toFixed(1)}×`;
}

/**
 * Format a decimal as a 0-100 score rounded to one decimal.
 */
export function formatScore(n: number): string {
  return n.toFixed(1);
}

/**
 * Format a date string to a human-readable format.
 */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const DHAKA_DATE_TIME_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Dhaka",
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/**
 * Format a runtime ISO timestamp deterministically for server and browser
 * rendering. Runtime contracts retain the original ISO timestamp.
 */
export function formatDhakaDateTime(iso: string | null | undefined): string {
  if (!iso) return "Not available";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "Not available";
  return `${DHAKA_DATE_TIME_FORMATTER.format(value)} — Dhaka time`;
}

/**
 * Format epi week label.
 */
export function formatEpiWeek(year: number, week: number): string {
  return `Epi W${week}, ${year}`;
}

/**
 * Format a days value with unit.
 */
export function formatDays(days: number): string {
  return `${days}d`;
}

/**
 * Truncate a string with ellipsis.
 */
export function truncate(str: string, maxLen = 40): string {
  return str.length > maxLen ? str.slice(0, maxLen) + "…" : str;
}
