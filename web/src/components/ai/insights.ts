/**
 * Pure data helpers behind the AI Score components: trend series, rolling averages,
 * histogram bins, stat-family attributions and the plain-language driver summary.
 * Kept free of React so the maths is easy to read and reuse.
 */
import type { AiTrendPoint, FeatureAttribution, FeatureGroup } from "@/api/types";
import { formatDuration, formatInteger, formatPercent } from "@/lib/format";
import { GRADES, gradeForScore, toScore100, type Grade } from "@/lib/score";

// --- shared query sizes -----------------------------------------------------------------

/** Games shown in the trend chart (shares one cache entry between compact and full). */
export const AI_TREND_LIMIT = 40;
/** Games behind the insights average and histogram (the API maximum). */
export const AI_INSIGHTS_TREND_LIMIT = 200;
/** Games behind the attribution chart. */
export const AI_EXPLAIN_LIMIT = 30;

export const ROLLING_WINDOW = 10;
/** The rolling line starts once this many games are in its window. */
const ROLLING_MIN_GAMES = 3;

// --- trend ------------------------------------------------------------------------------

export interface TrendDatum {
  /** 1-based position in the window, oldest first. */
  index: number;
  matchId: string;
  gameStart: string;
  champion: string;
  win: boolean;
  /** API score 0..1. */
  rate: number;
  /** Integer 0..100. */
  score: number;
  /** Rolling average of the last {@link ROLLING_WINDOW} games (0..100, one decimal). */
  rolling: number | null;
}

function mean(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  let total = 0;
  for (const value of values) total += value;
  return total / values.length;
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/** Trend points (oldest first) -> chart rows with a trailing rolling average. */
export function buildTrendData(points: readonly AiTrendPoint[], window = ROLLING_WINDOW): TrendDatum[] {
  return points.map((point, i) => {
    const start = Math.max(0, i - window + 1);
    const slice = points.slice(start, i + 1).map((p) => p.ai_score);
    const avg = slice.length >= Math.min(ROLLING_MIN_GAMES, window) ? mean(slice) : null;
    return {
      index: i + 1,
      matchId: point.match_id,
      gameStart: point.game_start,
      champion: point.champion_name,
      win: point.win,
      rate: point.ai_score,
      score: toScore100(point.ai_score),
      rolling: avg === null ? null : round1(avg * 100),
    };
  });
}

export interface TrendSummary {
  games: number;
  /** Mean of every game in the window (0..1). */
  average: number | null;
  /** Mean of the latest {@link ROLLING_WINDOW} games (0..1). */
  recent: number | null;
  recentGames: number;
  /** Mean of the {@link ROLLING_WINDOW} games before those (0..1), when there are any. */
  previous: number | null;
  previousGames: number;
  best: TrendDatum | null;
  wins: number;
}

export function summarizeTrend(data: readonly TrendDatum[], window = ROLLING_WINDOW): TrendSummary {
  const rates = data.map((d) => d.rate);
  const recentRates = rates.slice(-window);
  const previousRates = rates.slice(-window * 2, -window);
  let best: TrendDatum | null = null;
  for (const datum of data) {
    if (best === null || datum.rate > best.rate) best = datum;
  }
  return {
    games: data.length,
    average: mean(rates),
    recent: mean(recentRates),
    recentGames: recentRates.length,
    previous: mean(previousRates),
    previousGames: previousRates.length,
    best,
    wins: data.filter((d) => d.win).length,
  };
}

/** Evenly spaced x ticks (game indices) whose date labels don't repeat. */
export function trendTicks(data: readonly TrendDatum[], count: number, label: (d: TrendDatum) => string): number[] {
  if (data.length === 0) return [];
  if (data.length <= count) return dedupeTicks(data, data.map((d) => d.index), label);
  const step = (data.length - 1) / (count - 1);
  const indices = Array.from({ length: count }, (_, i) => Math.round(i * step) + 1);
  return dedupeTicks(data, indices, label);
}

function dedupeTicks(data: readonly TrendDatum[], indices: number[], label: (d: TrendDatum) => string): number[] {
  const out: number[] = [];
  let previous: string | null = null;
  for (const index of indices) {
    const datum = data[index - 1];
    if (!datum) continue;
    const text = label(datum);
    if (text === previous) continue;
    previous = text;
    out.push(index);
  }
  return out;
}

// --- season scope -----------------------------------------------------------------------

export interface ScopedPoints {
  points: AiTrendPoint[];
  /** "season" when the points were filtered to the current season. */
  scope: "season" | "recent";
}

/** Keep points from the current season; fall back to every point when none qualify. */
export function scopeToSeason(points: readonly AiTrendPoint[], seasonStart: string | null | undefined): ScopedPoints {
  const start = seasonStart ? Date.parse(seasonStart) : Number.NaN;
  if (Number.isFinite(start)) {
    const season = points.filter((p) => Date.parse(p.game_start) >= start);
    if (season.length > 0) return { points: season, scope: "season" };
  }
  return { points: [...points], scope: "recent" };
}

export function averageRate(points: readonly AiTrendPoint[]): number | null {
  return mean(points.map((p) => p.ai_score));
}

// --- histogram --------------------------------------------------------------------------

/** Stack order, bottom to top. */
export const GRADE_STACK: readonly Grade[] = ["D", "C", "B", "A", "S"];

export interface HistogramBin {
  /** Inclusive lower bound (0, 10, ..., 90). */
  lo: number;
  /** Inclusive upper bound (9, 19, ..., 100). */
  hi: number;
  /** Bin centre on the 0..100 axis. */
  mid: number;
  total: number;
  /** Share of all games (0..1). */
  share: number;
  D: number;
  C: number;
  B: number;
  A: number;
  S: number;
  /** Highest grade with games in this bin (the segment that gets the rounded cap). */
  top: Grade | null;
}

export interface GradeShare {
  grade: Grade;
  count: number;
  share: number;
}

export interface Histogram {
  bins: HistogramBin[];
  grades: GradeShare[];
  total: number;
  /** Median score 0..100. */
  median: number | null;
}

/** Ten 10-point bins over 0..100 (100 lands in the last bin), split by grade inside each bin. */
export function buildHistogram(points: readonly AiTrendPoint[]): Histogram {
  const bins: HistogramBin[] = Array.from({ length: 10 }, (_, i) => ({
    lo: i * 10,
    hi: i === 9 ? 100 : i * 10 + 9,
    mid: i * 10 + 5,
    total: 0,
    share: 0,
    D: 0,
    C: 0,
    B: 0,
    A: 0,
    S: 0,
    top: null,
  }));
  const gradeCounts: Record<Grade, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
  const scores: number[] = [];

  for (const point of points) {
    const score = toScore100(point.ai_score);
    scores.push(score);
    const bin = bins[Math.min(9, Math.floor(score / 10))];
    if (!bin) continue;
    const grade = gradeForScore(score).grade;
    bin[grade] += 1;
    bin.total += 1;
    gradeCounts[grade] += 1;
  }

  const total = points.length;
  for (const bin of bins) {
    bin.share = total > 0 ? bin.total / total : 0;
    bin.top = [...GRADE_STACK].reverse().find((grade) => bin[grade] > 0) ?? null;
  }

  scores.sort((a, b) => a - b);
  let median: number | null = null;
  if (scores.length > 0) {
    const mid = Math.floor(scores.length / 2);
    median =
      scores.length % 2 === 1 ? (scores[mid] ?? null) : Math.round(((scores[mid - 1] ?? 0) + (scores[mid] ?? 0)) / 2);
  }

  return {
    bins,
    grades: GRADES.map((g) => ({
      grade: g.grade,
      count: gradeCounts[g.grade],
      share: total > 0 ? gradeCounts[g.grade] / total : 0,
    })),
    total,
    median,
  };
}

/** Inclusive 0..100 range of a grade: S "80–100", C "35–49". */
export function gradeRange(grade: Grade): { lo: number; hi: number } {
  const index = GRADES.findIndex((g) => g.grade === grade);
  const info = GRADES[index];
  const above = index > 0 ? GRADES[index - 1] : undefined;
  return { lo: info?.min ?? 0, hi: above ? above.min - 1 : 100 };
}

// --- attributions -----------------------------------------------------------------------

export const FEATURE_GROUP_ORDER: readonly FeatureGroup[] = [
  "combat",
  "economy",
  "vision",
  "objectives",
  "survival",
  "teamplay",
];

export const FEATURE_GROUP_LABELS: Readonly<Record<FeatureGroup, string>> = {
  combat: "Combat",
  economy: "Economy",
  vision: "Vision",
  objectives: "Objectives",
  survival: "Survival",
  teamplay: "Teamplay",
};

export type Direction = "above" | "below" | "even";

/** One model input, formatted for display. */
export interface FeatureDisplay {
  feature: string;
  label: string;
  group: FeatureGroup;
  /** Signed mean attribution in logit units (gradient x input against an all-average stat line). */
  attribution: number;
  you: string;
  avg: string | null;
  /** Unit that follows the you/avg pair when the label doesn't carry one ("per game", "per min"). */
  unit: string;
  /** Player vs population average, when the population value is known. */
  direction: Direction | null;
  /** Relative difference vs the average (e.g. 0.18 = 18% higher), when meaningful. */
  relative: number | null;
}

function trimZeros(text: string): string {
  return text.includes(".") ? text.replace(/\.?0+$/, "") : text;
}

/** Magnitude-aware number formatting for raw feature values (true minus for negatives). */
function formatFeatureNumber(value: number): string {
  if (!Number.isFinite(value)) return "–";
  const abs = Math.abs(value);
  if (abs === 0) return "0";
  const sign = value < 0 ? "−" : "";
  if (abs >= 1000) return sign + formatInteger(abs);
  if (abs >= 100) return sign + abs.toFixed(0);
  if (abs >= 10) return sign + abs.toFixed(1);
  if (abs >= 0.1) return sign + abs.toFixed(2);
  return sign + trimZeros(abs.toPrecision(2));
}

const PER_GOLD_SUFFIX = /\s+per gold earned$/i;
const SECONDS_SUFFIX = /\s*\(seconds\)$/i;
/** Raw per-game counts: their you/avg pair reads "per game". */
const PER_GAME_FEATURES = new Set(["kills", "deaths", "assists", "killingSprees", "largestKillingSpree"]);

interface ValueFormat {
  label: string;
  format: (value: number) => string;
  unit: string;
}

/**
 * Tiny per-gold rates (kills per gold ~0.0005) read better per 1,000 gold; per-gold stats that
 * are already readable (damage per gold ~2) keep their unit. Second counts read as m:ss and
 * participation shares as percentages.
 */
function valueFormat(attr: FeatureAttribution): ValueFormat {
  const magnitude = Math.max(Math.abs(attr.player_value), Math.abs(attr.population_value ?? 0));
  if ((attr.feature.endsWith("PerGold") || PER_GOLD_SUFFIX.test(attr.label)) && magnitude < 0.1) {
    return {
      label: attr.label.replace(PER_GOLD_SUFFIX, " per 1k gold"),
      format: (value) => formatFeatureNumber(value * 1000),
      unit: "per 1k gold",
    };
  }
  if (SECONDS_SUFFIX.test(attr.label)) {
    return { label: attr.label.replace(SECONDS_SUFFIX, ""), format: (value) => formatDuration(value), unit: "" };
  }
  if (attr.feature.endsWith("Participation")) {
    return { label: attr.label, format: (value) => formatPercent(value), unit: "" };
  }
  const unit = attr.feature.endsWith("PerMinute")
    ? "per min"
    : attr.feature.endsWith("PerGold")
      ? "per gold"
      : PER_GAME_FEATURES.has(attr.feature)
        ? "per game"
        : "";
  return { label: attr.label, format: formatFeatureNumber, unit };
}

/** One model input formatted for display; stat families are built from these. */
function displayFeature(attr: FeatureAttribution): FeatureDisplay {
  const { label, format, unit } = valueFormat(attr);
  const population = attr.population_value;
  let direction: Direction | null = null;
  let relative: number | null = null;
  if (population !== null && Number.isFinite(population)) {
    const diff = attr.player_value - population;
    const scale = Math.max(Math.abs(population), Math.abs(attr.player_value), 1e-9);
    direction = Math.abs(diff) / scale < 0.02 ? "even" : diff > 0 ? "above" : "below";
    relative = Math.abs(population) > 1e-9 ? diff / Math.abs(population) : null;
  }
  return {
    feature: attr.feature,
    label,
    group: attr.group,
    attribution: Number.isFinite(attr.mean_attribution) ? attr.mean_attribution : 0,
    you: format(attr.player_value),
    avg: population !== null && Number.isFinite(population) ? format(population) : null,
    unit,
    direction,
    relative,
  };
}

// --- stat families ----------------------------------------------------------------------

interface Phrase {
  /** Noun phrase for the stat. */
  name: string;
  plural: boolean;
  /** Phrase when the player is below average (defaults to "low <name>"). */
  low?: string;
  lowPlural?: boolean;
  /** Phrase when the player is above average (defaults to the name). */
  high?: string;
}

interface StatFamily {
  key: string;
  label: string;
  group: FeatureGroup;
  /** Which way is good in plain League terms; null when it depends on role or champion. */
  better: "higher" | "lower" | null;
  /** Model inputs measuring the same thing; the first one present is shown as "you vs avg". */
  features: readonly string[];
  phrase: Phrase;
}

/**
 * The model sees several correlated views of one stat (deaths per game, per minute, per gold
 * earned, share of team deaths). Their individual attributions often point in opposite
 * directions and largely cancel, so each family is shown as a single net effect.
 */
const STAT_FAMILIES: readonly StatFamily[] = [
  {
    key: "kills",
    label: "Kills",
    group: "combat",
    better: "higher",
    features: ["kills", "killsPerMinute", "killsPerGold"],
    phrase: { name: "kills", plural: true, low: "few kills" },
  },
  {
    key: "deaths",
    label: "Deaths",
    group: "survival",
    better: "lower",
    features: ["deaths", "deathsPerMinute", "deathsPerGold", "deathParticipation"],
    phrase: { name: "deaths", plural: true, low: "few deaths", lowPlural: true, high: "frequent deaths" },
  },
  {
    key: "assists",
    label: "Assists",
    group: "teamplay",
    better: "higher",
    features: ["assists", "assistsPerMinute", "assistsPerGold"],
    phrase: { name: "assists", plural: true, low: "few assists" },
  },
  {
    key: "killParticipation",
    label: "Kill participation",
    group: "teamplay",
    better: "higher",
    features: ["killParticipation"],
    phrase: { name: "kill participation", plural: false },
  },
  {
    key: "gold",
    label: "Gold income",
    group: "economy",
    better: "higher",
    features: ["goldPerMinute"],
    phrase: { name: "gold income", plural: false },
  },
  {
    key: "damage",
    label: "Champion damage",
    group: "combat",
    better: "higher",
    features: ["damagePerMinute", "damagePerGold"],
    phrase: { name: "champion damage", plural: false },
  },
  {
    key: "laneFarming",
    label: "Lane farming",
    group: "economy",
    better: "higher",
    features: ["minionsPerMinute"],
    phrase: { name: "lane farming", plural: false, low: "light lane farming" },
  },
  {
    key: "jungleFarming",
    label: "Jungle farming",
    group: "economy",
    better: null,
    features: ["neutralMinionsPerMinute", "totalAllyJungleMinionsKilledPerMinute"],
    phrase: { name: "jungle farming", plural: false, low: "light jungle farming" },
  },
  {
    key: "objectiveDamage",
    label: "Objective damage",
    group: "objectives",
    better: "higher",
    features: ["objectiveDamagePerMinute"],
    phrase: { name: "objective damage", plural: false },
  },
  {
    key: "turrets",
    label: "Turret takedowns",
    group: "objectives",
    better: "higher",
    features: ["turretsPerMinute"],
    phrase: { name: "turret takedowns", plural: true, low: "few turret takedowns" },
  },
  {
    key: "vision",
    label: "Vision score",
    group: "vision",
    better: "higher",
    features: ["visionPerMinute"],
    phrase: { name: "vision", plural: false, low: "low vision" },
  },
  {
    key: "controlWards",
    label: "Control wards",
    group: "vision",
    better: "higher",
    features: ["controlWardsPerMinute"],
    phrase: { name: "control wards", plural: true, low: "few control wards" },
  },
  {
    key: "wardsKilled",
    label: "Ward clearing",
    group: "vision",
    better: "higher",
    features: ["wardsKilledPerMinute"],
    phrase: { name: "ward clearing", plural: false, low: "little ward clearing" },
  },
  {
    key: "damageTaken",
    label: "Damage taken",
    group: "survival",
    better: null,
    features: ["damageTakenPerMinute"],
    phrase: { name: "damage taken", plural: false },
  },
  {
    key: "timeAlive",
    label: "Longest time alive",
    group: "survival",
    better: "higher",
    features: ["longestTimeSpentLiving"],
    phrase: { name: "staying alive", plural: false, low: "short lifespans", lowPlural: true },
  },
  {
    key: "crowdControl",
    label: "Crowd control",
    group: "teamplay",
    better: "higher",
    features: ["timeCCingOthersPerMinute"],
    phrase: { name: "crowd control", plural: false, low: "little crowd control" },
  },
  {
    key: "healing",
    label: "Healing",
    group: "teamplay",
    better: null,
    features: ["healPerMinute"],
    phrase: { name: "healing", plural: false, low: "little healing" },
  },
  {
    key: "pings",
    label: "Pings",
    group: "teamplay",
    better: null,
    features: ["pingsPerMinute"],
    phrase: { name: "pings", plural: true, low: "few pings" },
  },
  {
    key: "sprees",
    label: "Killing sprees",
    group: "combat",
    better: "higher",
    features: ["killingSprees", "largestKillingSpree"],
    phrase: { name: "killing sprees", plural: true, low: "short killing sprees" },
  },
  {
    key: "multikills",
    label: "Multi-kills",
    group: "combat",
    better: "higher",
    features: ["tripleKillsPerMinute", "quadraKillsPerMinute", "pentaKillsPerMinute"],
    phrase: { name: "multi-kills", plural: true, low: "few multi-kills" },
  },
];

/** Families whose share of the total influence is below this read as neutral. */
const NEUTRAL_SHARE = 0.01;
/** ...as do families whose net attribution is below this many logits (about 0.25 score points). */
const NEUTRAL_LOGITS = 0.01;
/** Smallest share a family needs to be named in the one-line summary. */
const SUMMARY_MIN_SHARE = 0.04;

export interface DriverMember extends FeatureDisplay {
  /** This input's attribution as a signed share of the total influence (-1..1). */
  signedShare: number;
}

/** One stat family's net effect on the AI Score. */
export interface DriverDisplay {
  key: string;
  label: string;
  group: FeatureGroup;
  /** Net attribution of the family in logits (the sum of its inputs). */
  attribution: number;
  /** |attribution| as a share of every family's |attribution| combined (0..1). */
  share: number;
  /** Too small to matter. */
  neutral: boolean;
  /**
   * The model's net push runs against the usual reading of the stat, e.g. more deaths than
   * average lifting the score. Shown, but never used for the plain-language summary.
   */
  mixed: boolean;
  /** The input whose you/avg values represent the family. */
  headline: FeatureDisplay;
  /** Every input in the family, largest effect first. */
  members: DriverMember[];
  better: StatFamily["better"];
  phrase: Phrase;
}

function fallbackPhrase(label: string): Phrase {
  const text = label.charAt(0).toLowerCase() + label.slice(1);
  const head = text.split(/\s+/)[0] ?? "";
  return { name: text, plural: /[^s]s$/.test(head) };
}

/**
 * Model attributions grouped into stat families (one net bar per family), sorted by share of
 * the total influence. Inputs no family knows become a family of their own.
 */
export function buildDrivers(features: readonly FeatureAttribution[]): DriverDisplay[] {
  const displays = new Map(features.map((f) => [f.feature, displayFeature(f)]));
  const claimed = new Set<string>();
  const families: Array<{ family: StatFamily; members: FeatureDisplay[] }> = [];

  for (const family of STAT_FAMILIES) {
    const members = family.features.flatMap((name) => {
      const display = displays.get(name);
      return display ? [display] : [];
    });
    if (members.length === 0) continue;
    for (const member of members) claimed.add(member.feature);
    families.push({ family, members });
  }
  for (const display of displays.values()) {
    if (claimed.has(display.feature)) continue;
    families.push({
      family: {
        key: display.feature,
        label: display.label,
        group: display.group,
        better: null,
        features: [display.feature],
        phrase: fallbackPhrase(display.label),
      },
      members: [display],
    });
  }

  const nets = families.map(({ members }) => members.reduce((sum, m) => sum + m.attribution, 0));
  const total = nets.reduce((sum, net) => sum + Math.abs(net), 0);

  const drivers = families.map(({ family, members }, i): DriverDisplay => {
    const attribution = nets[i] ?? 0;
    const share = total > 0 ? Math.abs(attribution) / total : 0;
    const neutral = share < NEUTRAL_SHARE || Math.abs(attribution) < NEUTRAL_LOGITS;
    const headline = members[0] as FeatureDisplay;
    return {
      key: family.key,
      label: family.label,
      group: family.group,
      attribution,
      share,
      neutral,
      mixed: !neutral && runsAgainst(family.better, headline.direction, attribution),
      headline,
      members: members
        .map((m) => ({ ...m, signedShare: total > 0 ? m.attribution / total : 0 }))
        .sort((a, b) => Math.abs(b.attribution) - Math.abs(a.attribution)),
      better: family.better,
      phrase: family.phrase,
    };
  });

  return drivers.sort((a, b) => b.share - a.share || a.label.localeCompare(b.label));
}

/** True when the effect's sign contradicts the stat's usual meaning for this player. */
function runsAgainst(better: StatFamily["better"], direction: Direction | null, attribution: number): boolean {
  if (better === null || (direction !== "above" && direction !== "below")) return false;
  const expectedUp = (direction === "above") === (better === "higher");
  return expectedUp ? attribution < 0 : attribution > 0;
}

/** Signed share as text: "+34%", "−6%", "+<1%". */
export function formatShare(signedShare: number): string {
  const pct = Math.abs(signedShare) * 100;
  if (pct === 0) return "0%";
  const sign = signedShare > 0 ? "+" : "−";
  return pct < 0.5 ? `${sign}<1%` : `${sign}${Math.round(pct)}%`;
}

/** One-line reading of a family's effect, used in tooltips. */
export function explainDriver(driver: DriverDisplay): string {
  if (driver.neutral) return "Close to average, so it barely moves the score.";
  const helps = driver.attribution > 0;
  const direction = driver.headline.direction;
  if (driver.mixed && (direction === "above" || direction === "below")) {
    const usual = (direction === "above") === (driver.better === "higher") ? "lifts" : "lowers";
    const why =
      driver.members.length > 1
        ? "The model's views of this stat pull in different directions"
        : "The model weighs it against the rest of your stat line";
    return (
      `You're ${direction} average here, which usually ${usual} a score. ${why}, so treat this net ` +
      `${helps ? "lift" : "cost"} as a side effect, not advice.`
    );
  }
  const effect = helps ? "and the model counts that in your favour" : "and the model counts that against you";
  switch (direction) {
    case "above":
      return `You're above average here, ${effect}.`;
    case "below":
      return `You're below average here, ${effect}.`;
    case "even":
      return `You're about average here; the model still ${helps ? "rewards" : "penalises"} your mix of stats.`;
    default:
      return helps ? "This stat lifts your score." : "This stat lowers your score.";
  }
}

// --- plain-language summary -------------------------------------------------------------

function phraseFor(driver: DriverDisplay): { text: string; plural: boolean } {
  const { phrase } = driver;
  switch (driver.headline.direction) {
    case "below":
      return { text: phrase.low ?? `low ${phrase.name}`, plural: phrase.lowPlural ?? phrase.plural };
    case "above":
      return { text: phrase.high ?? phrase.name, plural: phrase.plural };
    default:
      return { text: phrase.name, plural: phrase.plural };
  }
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * "Gold income and champion damage lift your score most; low objective damage costs you the
 * most." Built from the largest stat families that push the score the way their stat
 * suggests; mixed signals (e.g. more deaths lifting the score) are never named. Null when
 * nothing stands out.
 */
export function summarizeDrivers(drivers: readonly DriverDisplay[]): string | null {
  const named = drivers.filter((d) => !d.neutral && !d.mixed && d.share >= SUMMARY_MIN_SHARE);
  const lifts = named
    .filter((d) => d.attribution > 0)
    .sort((a, b) => b.attribution - a.attribution)
    .slice(0, 2)
    .map(phraseFor);
  const [worst] = named.filter((d) => d.attribution < 0).sort((a, b) => a.attribution - b.attribution);

  let lift: string | null = null;
  const [a, b] = lifts;
  if (a && b) lift = `${a.text} and ${b.text} lift your score most`;
  else if (a) lift = `${a.text} ${a.plural ? "lift" : "lifts"} your score most`;

  let cost: string | null = null;
  if (worst) {
    const c = phraseFor(worst);
    cost = `${c.text} ${c.plural ? "cost" : "costs"} you the most`;
  }

  if (lift && cost) return `${capitalize(lift)}; ${cost}.`;
  if (lift) return `${capitalize(lift)}; no single stat stands out as holding it back.`;
  if (cost) return `${capitalize(cost)}; no single stat stands out as lifting it.`;
  return null;
}
