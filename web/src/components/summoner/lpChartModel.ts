/**
 * Data model for the LP journey chart: rank snapshots -> points, a y-domain snapped to
 * division boundaries, axis ticks labelled with tier/division names and the tier bands that
 * the domain crosses. `rank_value` mirrors api/src/hextrack/rank.py (400 per tier, 100 per
 * division, apex tiers share MASTER_BASE + LP).
 */
import type { RankPoint, Tier } from "@/api/types";
import { formatDate, formatShortDate } from "@/lib/format";
import { DIVISION_ORDER, MASTER_BASE, TIER_COLORS, TIER_LABELS, TIER_ORDER, formatRank, shortTier } from "@/lib/tiers";

import { readableTierColor } from "./summonerFormat";

const DIVISION_SIZE = 100;
const TIER_SIZE = 400;

export interface LpDatum {
  /** Snapshot time (ms since epoch), the x value. */
  t: number;
  /** rank_value, the y value. */
  value: number;
  point: RankPoint;
  /** Change in rank_value since the previous snapshot (null for the first). */
  delta: number | null;
}

export interface TierBand {
  tier: Tier;
  /** Lower edge (inclusive) clipped to the domain. */
  from: number;
  /** Upper edge clipped to the domain. */
  to: number;
  color: string;
}

export interface TierBoundary {
  value: number;
  /** Tier that starts at this boundary. */
  tier: Tier;
  label: string;
  color: string;
  labelColor: string;
}

export interface LpScale {
  domain: [number, number];
  ticks: number[];
  bands: TierBand[];
  boundaries: TierBoundary[];
}

export function toLpData(points: readonly RankPoint[]): LpDatum[] {
  const sorted = [...points]
    .map((point) => ({ point, t: Date.parse(point.taken_at) }))
    .filter((entry) => Number.isFinite(entry.t))
    .sort((a, b) => a.t - b.t);
  return sorted.map((entry, index) => {
    const previous = sorted[index - 1];
    return {
      t: entry.t,
      value: entry.point.rank_value,
      point: entry.point,
      delta: previous ? entry.point.rank_value - previous.point.rank_value : null,
    };
  });
}

/** Tier whose band contains `value` (apex values report Master: the ladder is shared). */
export function tierAt(value: number): Tier {
  if (value >= MASTER_BASE) return "MASTER";
  return TIER_ORDER[Math.max(0, Math.min(6, Math.floor(value / TIER_SIZE)))] ?? "IRON";
}

const TICK_STEPS = [100, 200, 400, 800, 1_600] as const;

export function lpScale(data: readonly LpDatum[], maxTicks = 6): LpScale {
  const values = data.map((d) => d.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // Snap to division boundaries with a little air so the line never rides the frame.
  let min = Math.max(0, Math.floor((lo - 12) / DIVISION_SIZE) * DIVISION_SIZE);
  let max = Math.ceil((hi + 12) / DIVISION_SIZE) * DIVISION_SIZE;
  if (max - min < 2 * DIVISION_SIZE) {
    if (min >= DIVISION_SIZE) min -= DIVISION_SIZE;
    else max += DIVISION_SIZE;
    if (max - min < 2 * DIVISION_SIZE) max = min + 2 * DIVISION_SIZE;
  }

  const span = max - min;
  const step: number = TICK_STEPS.find((s) => span / s <= maxTicks) ?? Math.ceil(span / maxTicks / TIER_SIZE) * TIER_SIZE;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) ticks.push(v);

  const bands: TierBand[] = [];
  const boundaries: TierBoundary[] = [];
  const divisionedTop = Math.min(max, MASTER_BASE);
  for (let start = Math.floor(min / TIER_SIZE) * TIER_SIZE; start < divisionedTop; start += TIER_SIZE) {
    const tier = tierAt(start);
    bands.push({ tier, from: Math.max(start, min), to: Math.min(start + TIER_SIZE, max), color: TIER_COLORS[tier] });
    if (start > min) {
      boundaries.push({
        value: start,
        tier,
        label: TIER_LABELS[tier],
        color: TIER_COLORS[tier],
        labelColor: readableTierColor(tier),
      });
    }
  }
  if (max > MASTER_BASE) {
    bands.push({ tier: "MASTER", from: Math.max(MASTER_BASE, min), to: max, color: TIER_COLORS.MASTER });
    if (MASTER_BASE > min) {
      boundaries.push({
        value: MASTER_BASE,
        tier: "MASTER",
        label: "Master",
        color: TIER_COLORS.MASTER,
        labelColor: readableTierColor("MASTER"),
      });
    }
  }

  return { domain: [min, max], ticks, bands, boundaries };
}

/** Y tick label: "Gold II" (or "G2" when `short`); apex ticks read "Master" / "+200 LP". */
export function lpTickLabel(value: number, short: boolean): string {
  if (value >= MASTER_BASE) {
    const lp = value - MASTER_BASE;
    if (lp === 0) return short ? "M" : "Master";
    return short ? `+${lp}` : `+${lp} LP`;
  }
  const tier = tierAt(value);
  const division = DIVISION_ORDER[Math.min(3, Math.floor((value % TIER_SIZE) / DIVISION_SIZE))] ?? "IV";
  return short ? shortTier(tier, division) : `${TIER_LABELS[tier]} ${division}`;
}

/** "Gold II · 45 LP" for a snapshot. */
export function pointLabel(point: RankPoint): string {
  return formatRank(point);
}

const DAY = 24 * 60 * 60 * 1_000;
const HOUR = 60 * 60 * 1_000;
/** Ranges longer than this label their ticks by month and year ("Aug 2025"). */
const LONG_RANGE = 300 * DAY;

const hourFormatter = new Intl.DateTimeFormat("en-US", { hour: "numeric" });
const monthYearFormatter = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" });

/** Tick labels drop the year only while the range stays inside one calendar year. */
function tickFormat(min: number, max: number, unit: number): (t: number) => string {
  if (unit === HOUR) return (t) => hourFormatter.format(t);
  if (max - min > LONG_RANGE) return (t) => monthYearFormatter.format(t);
  if (new Date(min).getFullYear() !== new Date(max).getFullYear()) return (t) => formatDate(t);
  return (t) => formatShortDate(t);
}

/** Evenly spaced x ticks snapped to whole days (or hours for short ranges). */
export function timeTicks(min: number, max: number, count: number): { ticks: number[]; format: (t: number) => string } {
  const span = max - min;
  if (span <= 0) return { ticks: [min], format: tickFormat(min, max, DAY) };
  const unit = span < 2 * DAY ? HOUR : DAY;
  const format = tickFormat(min, max, unit);
  const ticks: number[] = [];
  const segments = Math.max(1, count - 1);
  for (let i = 0; i <= segments; i += 1) {
    const raw = min + (span * i) / segments;
    const snapped = unit === DAY ? startOfLocalDay(raw + DAY / 2) : Math.round(raw / HOUR) * HOUR;
    const clamped = Math.min(max, Math.max(min, snapped));
    const last = ticks[ticks.length - 1];
    if (last === undefined || clamped - last >= unit) ticks.push(clamped);
  }
  return { ticks, format };
}

function startOfLocalDay(t: number): number {
  const date = new Date(t);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/** Snapshots taken on or after the season start (the whole history when it is unknown). */
export function sinceSeason(data: readonly LpDatum[], seasonStart: string | null | undefined): LpDatum[] {
  const start = seasonStart ? Date.parse(seasonStart) : Number.NaN;
  if (!Number.isFinite(start)) return [...data];
  return data.filter((d) => d.t >= start);
}

/** "since Aug 19" in the current year, "since Aug 19, 2025" before it. */
export function sinceLabel(t: number, now: number = Date.now()): string {
  return new Date(t).getFullYear() === new Date(now).getFullYear() ? formatShortDate(t) : formatDate(t);
}

/** Longer than this without a snapshot and the line breaks instead of inventing a climb. */
export const LP_GAP_MS = 7 * DAY;

/** One row of the chart series: a snapshot, or the placeholder that opens a gap. */
export interface LpRow {
  /** x value (ms since epoch). */
  t: number;
  /** rank_value; null inside a gap, which breaks the line and the area. */
  value: number | null;
  /** Dashed "no snapshots" segment: set at both ends of a gap and at its midpoint. */
  bridge: number | null;
  point: RankPoint | null;
  delta: number | null;
  /** Set on the placeholder row: the stretch of time with no snapshots. */
  gap: { from: number; to: number } | null;
  /** A snapshot with a gap on both sides: nothing connects to it, so it draws its own dot. */
  isolated: boolean;
}

/**
 * Chart rows for `data`, with a null placeholder wherever more than {@link LP_GAP_MS} passes
 * between snapshots. Sparse histories then read as separate runs joined by a dashed hint,
 * instead of one smooth climb through months without a single game.
 */
export function toLpRows(data: readonly LpDatum[], gapMs = LP_GAP_MS): LpRow[] {
  const rows: LpRow[] = [];
  data.forEach((d, index) => {
    const previous = data[index - 1];
    const next = data[index + 1];
    const gapBefore = previous !== undefined && d.t - previous.t > gapMs;
    const gapAfter = next !== undefined && next.t - d.t > gapMs;
    rows.push({
      t: d.t,
      value: d.value,
      bridge: gapBefore || gapAfter ? d.value : null,
      point: d.point,
      delta: d.delta,
      gap: null,
      isolated: gapBefore && gapAfter,
    });
    if (gapAfter && next) {
      rows.push({
        t: Math.round((d.t + next.t) / 2),
        value: null,
        bridge: (d.value + next.value) / 2,
        point: null,
        delta: null,
        gap: { from: d.t, to: next.t },
        isolated: false,
      });
    }
  });
  return rows;
}

/** Whole days without a snapshot across a gap. */
export function gapDays(gap: { from: number; to: number }): number {
  return Math.max(1, Math.round((gap.to - gap.from) / DAY));
}

export interface LpSummary {
  first: LpDatum;
  last: LpDatum;
  peak: LpDatum;
  net: number;
}

export function lpSummary(data: readonly LpDatum[]): LpSummary | null {
  const first = data[0];
  const last = data[data.length - 1];
  if (!first || !last) return null;
  const peak = data.reduce((best, d) => (d.value > best.value ? d : best), first);
  return { first, last, peak, net: last.value - first.value };
}
