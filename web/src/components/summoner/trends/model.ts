/**
 * Pure helpers for the Trends tab: labels, the tilt verdict, the win-rate colour scale of the
 * schedule heatmap. No React in here.
 */
import type {
  LeaderboardQueue,
  ScheduleWindow,
  SessionGameBucket,
  SessionState,
  StatsSince,
} from "@/api/types";
import { CHART_COLORS } from "@/lib/chartTheme";
import { formatPercent, plural } from "@/lib/format";

// --- filters ----------------------------------------------------------------------------

export interface TrendsFilters {
  since: StatsSince;
  queue: LeaderboardQueue;
}

export const DEFAULT_TRENDS_FILTERS: TrendsFilters = { since: "season", queue: "all" };

export function isStatsSince(value: unknown): value is StatsSince {
  return value === "season" || value === "all";
}

export function isLeaderboardQueue(value: unknown): value is LeaderboardQueue {
  return value === "all" || value === "solo" || value === "flex";
}

/**
 * "ranked games this season", "Flex games (all time)"; with a count, "578 ranked games this
 * season", "1 Solo/Duo game (all time)".
 */
export function gamesPhrase({ since, queue }: TrendsFilters, count?: number): string {
  const kind = queue === "solo" ? "Solo/Duo game" : queue === "flex" ? "Flex game" : "ranked game";
  const noun = count === undefined ? `${kind}s` : plural(count, kind);
  return since === "season" ? `${noun} this season` : `${noun} (all time)`;
}

// --- percentages / numbers ----------------------------------------------------------------

/** 0..1 -> integer percent. */
export function pct(ratio: number): number {
  return Math.round(ratio * 100);
}

/** AI average 0..1 -> "46", or null. */
export function aiPoints(rate: number | null | undefined): number | null {
  return rate === null || rate === undefined ? null : Math.round(rate * 100);
}

/** "−1.3K", "+820": a signed compact number with a true minus sign. */
export function formatSignedCompact(value: number): string {
  const abs = Math.abs(value);
  const text = abs >= 1000 ? `${(abs / 1000).toFixed(1).replace(/\.0$/, "")}K` : String(Math.round(abs));
  if (Math.round(value) === 0) return "0";
  return `${value > 0 ? "+" : "−"}${text}`;
}

// --- sessions (tilt detector) ---------------------------------------------------------------

/** Buckets need this many games (in the first game and a later one) before a verdict is shown. */
export const VERDICT_MIN_GAMES = 10;

/** Win-rate changes smaller than this many (whole, as printed) points read as "steady". */
const VERDICT_MIN_POINTS = 5;

export function gameNumberLabel(n: number): string {
  return n >= 6 ? "6+" : String(n);
}

export const SESSION_STATE_LABELS: Readonly<Record<SessionState, { label: string; description: string }>> = {
  first_game: { label: "First game", description: "The first game of a session." },
  after_win: { label: "After a win", description: "The previous game in the session was a win." },
  after_one_loss: { label: "After a loss", description: "One loss just before, after a win or the session start." },
  after_two_plus_losses: { label: "After 2+ losses", description: "Two or more losses in a row just before." },
};

export type VerdictKind = "drop" | "rise" | "steady" | "unclear";

export interface SessionVerdict {
  kind: VerdictKind;
  text: string;
  first: SessionGameBucket;
  later: SessionGameBucket;
}

/**
 * One-line reading of the win rate by game number. Compares the first game with the latest
 * game number that still has `VERDICT_MIN_GAMES` games; a change only counts when it is at
 * least 5 points and at least one standard error (so a handful of games can't shout "tilt").
 * Under 5 points reads "steady" (and names the gap when there is one); 5+ points inside the
 * noise reads "unclear". Points are measured on the rounded percentages the sentence prints, so
 * "50% ... 45%" is never called steady. Null when the samples are too small.
 */
export function sessionVerdict(buckets: readonly SessionGameBucket[]): SessionVerdict | null {
  const first = buckets.find((bucket) => bucket.n === 1);
  if (!first || first.games < VERDICT_MIN_GAMES) return null;
  const later = [...buckets]
    .filter((bucket) => bucket.n > 1 && bucket.games >= VERDICT_MIN_GAMES)
    .sort((a, b) => b.n - a.n)[0];
  if (!later) return null;

  // Same rounding as formatPercent, so the points match the two printed percentages.
  const printed = (rate: number) => Number((rate * 100).toFixed(0));
  const points = printed(later.winrate) - printed(first.winrate);
  const delta = points / 100;
  const pooled = (first.wins + later.wins) / (first.games + later.games);
  const se = Math.sqrt(pooled * (1 - pooled) * (1 / first.games + 1 / later.games));
  const firstText = formatPercent(first.winrate);
  const laterText = formatPercent(later.winrate);
  const laterPhrase = later.n >= 6 ? "from game 6 on" : `by game ${later.n}`;

  if (Math.abs(points) >= VERDICT_MIN_POINTS && Math.abs(delta) >= se) {
    const kind: VerdictKind = delta < 0 ? "drop" : "rise";
    const verb = kind === "drop" ? "drops" : "climbs";
    return { kind, first, later, text: `Win rate ${verb} from ${firstText} in the first game to ${laterText} ${laterPhrase}.` };
  }
  if (Math.abs(points) < VERDICT_MIN_POINTS) {
    const gap = points === 0 ? "" : ` (${formatSignedCompact(points)} pts, within noise)`;
    const lead = points === 0 ? "Win rate holds steady through a session" : "Win rate barely moves through a session";
    return {
      kind: "steady",
      first,
      later,
      text: `${lead}${gap}: ${firstText} in the first game, ${laterText} ${laterPhrase}.`,
    };
  }
  return {
    kind: "unclear",
    first,
    later,
    text: `No clear pattern yet: ${firstText} in the first game and ${laterText} ${laterPhrase}, a gap these sample sizes can't separate from luck.`,
  };
}

// --- schedule (best time to play) ----------------------------------------------------------

export const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
export const DAY_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

export function dayShort(dow: number): string {
  return DAY_SHORT[dow] ?? "";
}

export function dayLong(dow: number): string {
  return DAY_LONG[dow] ?? "";
}

const meridiem = (hour: number) => (hour % 24 < 12 ? "AM" : "PM");
const clock = (hour: number) => hour % 12 || 12;

/** Axis label: "12a", "3p". */
export function hourTick(hour: number): string {
  return `${clock(hour)}${meridiem(hour) === "AM" ? "a" : "p"}`;
}

/** "8 PM". */
export function hourLabel(hour: number): string {
  return `${clock(hour)} ${meridiem(hour)}`;
}

/** Hour range, end exclusive: (20, 23) -> "8–11 PM", (9, 12) -> "9 AM–12 PM", (21, 24) -> "9 PM–12 AM". */
export function hourRange(start: number, end: number): string {
  if (meridiem(start) === meridiem(end)) {
    return `${clock(start)}–${clock(end)} ${meridiem(end)}`;
  }
  return `${hourLabel(start)}–${hourLabel(end)}`;
}

/** "Wed 2–5 PM". */
export function windowLabel(window: Pick<ScheduleWindow, "dow" | "start_hour" | "end_hour">): string {
  return `${dayShort(window.dow)} ${hourRange(window.start_hour, window.end_hour)}`;
}

/** Short zone name for the viewer ("CDT"), or the IANA key when the browser can't name it. */
export function timeZoneAbbreviation(tz: string, at: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }).formatToParts(at);
    return parts.find((part) => part.type === "timeZoneName")?.value ?? tz;
  } catch {
    return tz;
  }
}

/** Neutral midpoint of the diverging scale: low salience, but still >= 2:1 on surface-1. */
const HEAT_NEUTRAL = "#404859";

export interface WinrateBin {
  /** Legend label. */
  label: string;
  color: string;
  /** Short description for screen readers and the legend title. */
  description: string;
}

/**
 * Diverging win-rate scale: loss red <- neutral grey -> win blue, five steps with equal
 * lightness gaps per arm (midpoints are OKLab mixes, checked with the dataviz validator:
 * monotone lightness, >= 2:1 light end on surface-1).
 */
export const WINRATE_BINS: readonly WinrateBin[] = [
  { label: "≤35%", color: CHART_COLORS.loss, description: "35% or lower" },
  { label: "36–44%", color: "#944f5c", description: "36 to 44%" },
  { label: "45–55%", color: HEAT_NEUTRAL, description: "45 to 55%" },
  { label: "56–64%", color: "#496aa9", description: "56 to 64%" },
  { label: "≥65%", color: CHART_COLORS.win, description: "65% or higher" },
];

/** Index into WINRATE_BINS for a 0..1 win rate (bins are on whole percents). */
export function winrateBinIndex(winrate: number): number {
  const p = pct(winrate);
  if (p <= 35) return 0;
  if (p < 45) return 1;
  if (p <= 55) return 2;
  if (p < 65) return 3;
  return 4;
}

export function winrateColor(winrate: number): string {
  return (WINRATE_BINS[winrateBinIndex(winrate)] as WinrateBin).color;
}

/** Side of a heatmap mark as a fraction of its cell: area grows with games (sqrt), 0.4..1. */
export function markScale(games: number, maxGames: number): number {
  if (games <= 0 || maxGames <= 0) return 0;
  return 0.4 + 0.6 * Math.sqrt(Math.min(1, games / maxGames));
}
