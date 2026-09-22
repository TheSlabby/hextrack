/**
 * AI Score presentation. The API returns scores as probabilities 0..1 (the model's estimate of
 * how often a stat line like this one wins); the UI shows them as 0..100.
 *
 * What the number is, and isn't: the result is not a model input, but the stats that weigh the
 * most (gold, towers, objectives, deaths per gold earned) mostly come with winning. So a single
 * game's score largely follows its result: wins typically score around 90 and losses around 10.
 * Grades therefore describe how much a line looks like a winning one, never "a carry", and they
 * are for single games only. Averages over many games collapse onto win rate, so they are shown
 * as a plain number (`AiScoreBadge kind="average"`, `AiScoreRing kind="average"`), never graded.
 */

export type Grade = "S" | "A" | "B" | "C" | "D";

export interface GradeInfo {
  grade: Grade;
  /** Lower bound on the 0..100 scale (inclusive). */
  min: number;
  /** Hex colour (mirrors --color-score-*). */
  color: string;
  /** Tailwind text class. */
  textClass: string;
  /** Tailwind classes for a tinted pill (bg + border + text). */
  pillClass: string;
  label: string;
  description: string;
}

export const GRADES: readonly GradeInfo[] = [
  {
    grade: "S",
    min: 80,
    color: "#0ac8b9",
    textClass: "text-score-s",
    pillClass: "bg-score-s/12 border-score-s/35 text-score-s",
    label: "Winning line",
    description: "Stats that look like a win: lines like this win the vast majority of games. Most wins land here.",
  },
  {
    grade: "A",
    min: 65,
    color: "#3ddc97",
    textClass: "text-score-a",
    pillClass: "bg-score-a/12 border-score-a/35 text-score-a",
    label: "Leaning win",
    description: "Stats that show up more often on the winning side than the losing one.",
  },
  {
    grade: "B",
    min: 50,
    color: "#f5d547",
    textClass: "text-score-b",
    pillClass: "bg-score-b/12 border-score-b/35 text-score-b",
    label: "Toss-up",
    description: "Close to the line between a winning and a losing stat line.",
  },
  {
    grade: "C",
    min: 35,
    color: "#ff9f43",
    textClass: "text-score-c",
    pillClass: "bg-score-c/12 border-score-c/35 text-score-c",
    label: "Leaning loss",
    description: "Stats that show up more often on the losing side than the winning one.",
  },
  {
    grade: "D",
    min: 0,
    color: "#ff5d6c",
    textClass: "text-score-d",
    pillClass: "bg-score-d/12 border-score-d/35 text-score-d",
    label: "Losing line",
    description: "Stats that look like a loss: lines like this rarely win. Most losses land here.",
  },
];

const FALLBACK: GradeInfo = GRADES[GRADES.length - 1] as GradeInfo;

/** Probability 0..1 -> integer 0..100. */
export function toScore100(rate: number): number {
  return Math.round(Math.max(0, Math.min(1, rate)) * 100);
}

/** Grade info for a 0..100 score. */
export function gradeForScore(score100: number): GradeInfo {
  return GRADES.find((g) => score100 >= g.min) ?? FALLBACK;
}

/** Grade info for an API score (0..1). */
export function gradeForRate(rate: number): GradeInfo {
  return gradeForScore(toScore100(rate));
}

/** How far an average sits from a coin flip, in 0..100 points: 0.53 -> 3, 0.47 -> -3. */
export function averageOffset(rate: number): number {
  return toScore100(rate) - 50;
}

/** One-paragraph explanation for teasers and summaries. */
export const AI_SCORE_SUMMARY =
  "The AI Score is a neural network's estimate, from 0 to 100, of how often a stat line like yours wins. " +
  "The result isn't an input, but gold, towers and objectives mostly come with winning, so the score " +
  "largely follows it: wins usually score 65+ and losses under 35.";

/** How to read a single game's score. */
export const AI_SCORE_RESULT_NOTE =
  "Won games usually score 65+ and lost games under 35, so compare scores between games with the same result.";

/** How to read an average over many games (season, roster, champion). */
export const AI_AVERAGE_NOTE =
  "Averages over many games follow win rate closely (50 is a coin flip), so they aren't graded like single games.";

const MODEL_VERSION_RE = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/;

/** Training time encoded in a model version id ("20260922-170745", UTC); null for other ids. */
export function modelVersionDate(version: string | null | undefined): Date | null {
  const match = version ? MODEL_VERSION_RE.exec(version) : null;
  if (!match) return null;
  const [, y, mo, d, h, mi, s] = match.map(Number) as [number, number, number, number, number, number, number];
  const date = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  return Number.isNaN(date.getTime()) ? null : date;
}
