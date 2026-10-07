/**
 * Hex Score presentation. The API returns scores as 0..1; the UI shows them as 0..100.
 *
 * What the number is: how much a player's own stat line pushed their team toward winning,
 * as a percentile among ranked games in the same role (50 = a typical game, 80 = better than
 * 80% of games in that role). The model is trained on whole games, where the ten players'
 * impacts add up to which team won, so a stomp or a teammate's big game doesn't inflate
 * everyone's score, and a strong game in a loss still scores well. Wins still score higher
 * on average (playing well is how games are won), so it's never called a "carry" rating
 * outside the duo/squad verdicts. Averages are shown as plain numbers
 * (`AiScoreBadge kind="average"`, `AiScoreRing kind="average"`), never graded.
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
    label: "Standout",
    description: "Better than 80% of games in this role: a line that clearly pushed the team toward winning.",
  },
  {
    grade: "A",
    min: 65,
    color: "#3ddc97",
    textClass: "text-score-a",
    pillClass: "bg-score-a/12 border-score-a/35 text-score-a",
    label: "Strong",
    description: "Clearly above a typical game for this role.",
  },
  {
    grade: "B",
    min: 50,
    color: "#f5d547",
    textClass: "text-score-b",
    pillClass: "bg-score-b/12 border-score-b/35 text-score-b",
    label: "Solid",
    description: "Around a typical game for this role, or a bit better.",
  },
  {
    grade: "C",
    min: 35,
    color: "#ff9f43",
    textClass: "text-score-c",
    pillClass: "bg-score-c/12 border-score-c/35 text-score-c",
    label: "Below par",
    description: "A bit under a typical game for this role.",
  },
  {
    grade: "D",
    min: 0,
    color: "#ff5d6c",
    textClass: "text-score-d",
    pillClass: "bg-score-d/12 border-score-d/35 text-score-d",
    label: "Rough",
    description: "Among the weaker games for this role: the line held the team back more than it helped.",
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

/** How far an average sits from a typical game (50), in 0..100 points: 0.53 -> 3, 0.47 -> -3. */
export function averageOffset(rate: number): number {
  return toScore100(rate) - 50;
}

/** One-paragraph explanation for teasers and summaries. */
export const AI_SCORE_SUMMARY =
  "The Hex Score rates how much your own stat line pushed your team toward winning, from 0 to 100, " +
  "compared with ranked games in the same role: 50 is a typical game. A neural network learns it from " +
  "whole games, where the ten players' lines add up to who won, so a strong game in a loss still scores well.";

/** How to read a single game's score. */
export const AI_SCORE_RESULT_NOTE =
  "50 is a typical game for the role. Wins score higher on average, but a strong game in a loss still scores well.";

/** How to read an average over many games (season, roster, champion). */
export const AI_AVERAGE_NOTE =
  "Over many games, 50 is a typical player for their roles; averages are shown as plain numbers, not graded.";

const MODEL_VERSION_RE = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/;

/** Training time encoded in a model version id ("20260922-170745", UTC); null for other ids. */
export function modelVersionDate(version: string | null | undefined): Date | null {
  const match = version ? MODEL_VERSION_RE.exec(version) : null;
  if (!match) return null;
  const [, y, mo, d, h, mi, s] = match.map(Number) as [number, number, number, number, number, number, number];
  const date = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  return Number.isNaN(date.getTime()) ? null : date;
}
