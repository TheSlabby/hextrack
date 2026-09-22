/** Number, time and stat formatting. All output is plain text; wrap numbers in `tabular-nums`. */

const MINUS = "−";

const compactFormatter = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const integerFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const relativeFormatter = new Intl.RelativeTimeFormat("en-US", { numeric: "auto", style: "long" });
const dateFormatter = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
const shortDateFormatter = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

type DateInput = string | number | Date;

function toDate(value: DateInput): Date {
  return value instanceof Date ? value : new Date(value);
}

const RELATIVE_STEPS: ReadonlyArray<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** "just now", "5 minutes ago", "yesterday", "3 weeks ago", "in 2 minutes". */
export function timeAgo(value: DateInput, now: number = Date.now()): string {
  const seconds = Math.round((toDate(value).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return seconds <= 0 ? "just now" : "in a few seconds";
  for (const [unit, size] of RELATIVE_STEPS) {
    if (abs >= size) return relativeFormatter.format(Math.round(seconds / size), unit);
  }
  return relativeFormatter.format(Math.round(seconds / 60), "minute");
}

/** Compact relative time for dense rows: "now", "12m", "5h", "3d", "2w", "4mo", "1y". */
export function timeAgoShort(value: DateInput, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - toDate(value).getTime()) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.floor(days / 7)}w`;
  if (days < 365) return `${Math.floor(days / 30)}mo`;
  return `${Math.floor(days / 365)}y`;
}

/** Game duration in seconds -> "27:05" (or "1:02:13" past an hour). */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const ss = String(seconds).padStart(2, "0");
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${ss}`;
  return `${minutes}:${ss}`;
}

/** Seconds -> "27m 5s" (for prose / aria labels). */
export function formatDurationLong(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(s / 60);
  const seconds = s % 60;
  return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
}

/** 1284 -> "1.3K", 12900 -> "12.9K". */
export function formatCompact(value: number): string {
  return compactFormatter.format(value);
}

/** 12345 -> "12,345". */
export function formatInteger(value: number): string {
  return integerFormatter.format(value);
}

/** Fixed decimals without trailing noise: formatDecimal(6.0) -> "6.0", formatDecimal(6.25, 2) -> "6.25". */
export function formatDecimal(value: number, digits = 1): string {
  return value.toFixed(digits);
}

/** Ratio 0..1 -> "54%" (digits controls decimals). */
export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return "–";
  return `${(ratio * 100).toFixed(digits)}%`;
}

/** Pre-computed KDA ratio (API `kda` field). Pass `deaths` to render "Perfect" when 0. */
export function formatKdaRatio(kda: number, deaths?: number, digits = 2): string {
  if (deaths === 0 && kda > 0) return "Perfect";
  return kda.toFixed(digits);
}

/** Averages: "6.2 / 4.1 / 8.7". */
export function formatAvgKdaLine(kills: number, deaths: number, assists: number): string {
  return `${kills.toFixed(1)} / ${deaths.toFixed(1)} / ${assists.toFixed(1)}`;
}

/** Signed number with a true minus sign: +24, −12, 0. */
export function formatSigned(value: number, digits = 0): string {
  const fixed = Math.abs(value).toFixed(digits);
  if (value > 0) return `+${fixed}`;
  if (value < 0) return `${MINUS}${fixed}`;
  return fixed;
}

/** Signed LP delta: "+24 LP", "−12 LP", "±0 LP". */
export function formatLpDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "–";
  if (delta === 0) return "±0 LP";
  return `${formatSigned(delta)} LP`;
}

/** "Sep 21, 2026". */
export function formatDate(value: DateInput): string {
  return dateFormatter.format(toDate(value));
}

/** "Sep 21". */
export function formatShortDate(value: DateInput): string {
  return shortDateFormatter.format(toDate(value));
}

/** "Sep 21, 2026, 7:42 PM". */
export function formatDateTime(value: DateInput): string {
  return dateTimeFormatter.format(toDate(value));
}

/** "12 W 8 L". */
export function formatRecord(wins: number, losses: number): string {
  return `${wins}W ${losses}L`;
}

/** Pluralise: plural(3, "game") -> "3 games". */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${formatInteger(count)} ${count === 1 ? singular : pluralForm}`;
}
