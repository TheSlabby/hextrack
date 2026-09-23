/**
 * Score within role: where an AI Score sits among every ranked game the active model scored in
 * the same position (the API's `ai_role_percentile`, 0..100 = "better than X% of those games").
 *
 * One game's label reads like a ladder: "Top 12%" from the 50th percentile up, "Bottom 30%" below
 * it. A player's AVERAGE is a plain number instead ("47th pct in role"): a mean of percentiles is
 * not itself a percentile, every roster average sits near the middle, and a Top/Bottom ladder
 * would make 49 and 51 sound like opposites. The copy for the label's tooltip lives here (next to the AI Score copy in `lib/score.ts`), so every
 * place that shows the percentile explains it the same way.
 */
import type { Position } from "@/api/types";

/** Three-letter role tags for dense rows ("Top 12% SUP"). */
export const ROLE_SHORT: Readonly<Record<Position, string>> = {
  TOP: "TOP",
  JUNGLE: "JGL",
  MIDDLE: "MID",
  BOTTOM: "BOT",
  UTILITY: "SUP",
  UNKNOWN: "",
};

/** "Top 12% of supports" (where there is room). */
export const ROLE_PLAYERS: Readonly<Record<Position, string>> = {
  TOP: "top laners",
  JUNGLE: "junglers",
  MIDDLE: "mid laners",
  BOTTOM: "bot laners",
  UTILITY: "supports",
  UNKNOWN: "players",
};

/** "Better than 88% of scored support games". */
export const ROLE_GAMES: Readonly<Record<Position, string>> = {
  TOP: "top lane games",
  JUNGLE: "jungle games",
  MIDDLE: "mid lane games",
  BOTTOM: "bot lane games",
  UTILITY: "support games",
  UNKNOWN: "games",
};

/** Who the percentile is measured against (tooltip footnote). */
export const ROLE_PERCENTILE_NOTE =
  "Compared with every ranked game the current AI model scored in the same role, not just the roster's.";

/** Averages of the percentile follow win rate, like average AI Scores. */
export const ROLE_PERCENTILE_AVERAGE_NOTE =
  "An average over this player's scored games. Scores mostly follow the result, so this tracks win rate too.";

export interface RoleStanding {
  /** "Top" from the 50th percentile up, "Bottom" below it. */
  side: "top" | "bottom";
  /** Whole percent shown after the side, at least 1: "Top 12%", "Bottom 3%". */
  share: number;
  /** "Top 12%". */
  label: string;
  /** Rounded "better than" share, 0..100. */
  betterThan: number;
}

/** Percentile (0..100, share of same-role games with a lower score) -> ladder-style standing. */
export function roleStanding(percentile: number): RoleStanding {
  const p = Math.max(0, Math.min(100, percentile));
  const side = p >= 50 ? "top" : "bottom";
  const share = Math.max(1, Math.round(side === "top" ? 100 - p : p));
  const label = `${side === "top" ? "Top" : "Bottom"} ${share}%`;
  return { side, share, label, betterThan: Math.round(p) };
}

/** Below this many scored games a player's average is marked "small sample" (the leaderboard's
 * standing minimum). */
export const ROLE_AVERAGE_MIN_GAMES = 20;

/** 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 11 -> "11th", 47 -> "47th". */
export function ordinal(value: number): string {
  const n = Math.round(value);
  const mod100 = Math.abs(n) % 100;
  const mod10 = Math.abs(n) % 10;
  const suffix = mod100 >= 11 && mod100 <= 13 ? "th" : mod10 === 1 ? "st" : mod10 === 2 ? "nd" : mod10 === 3 ? "rd" : "th";
  return `${n}${suffix}`;
}

/** A player's average role percentile as a neutral number: "47th pct". */
export function averagePercentileLabel(percentile: number): string {
  return `${ordinal(Math.max(0, Math.min(100, percentile)))} pct`;
}

/** A known role (the percentile is null for UNKNOWN anyway). */
export function isKnownRole(position: Position | null | undefined): position is Exclude<Position, "UNKNOWN"> {
  return Boolean(position) && position !== "UNKNOWN";
}
