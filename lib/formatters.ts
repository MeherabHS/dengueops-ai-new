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
