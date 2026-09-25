/**
 * Carry / "ran it down" banter between teammates: the tier from their AI Scores, and the text
 * for each tier. Teammates share the result, so comparing their scores is fair; this is the
 * one place the site talks about carrying (see DESIGN.md).
 *
 * KEEP IN SYNC with api/src/hextrack/stats/verdict.py, which computes the same tiers for the
 * Stacks page and its award counts: the gaps (40 / 20 / 10), the "tried" and "passenger" rules, rounding
 * (toScore100) and "every member scored". VERDICTS is typed against the API's VerdictTier, so
 * a renamed or missing tier breaks the build.
 */
import type { VerdictTier } from "@/api/types";

import type { Outcome } from "./matchUtils";

export const HARD_GAP = 40;
export const CARRY_GAP = 20;
export const EDGE_GAP = 10;
/** On a loss, a bottom gap under this is "close"; then a top gap of CARRY_GAP+ means "tried". */
export const TRIED_CLOSE = 10;

/**
 * Banter lines per tier. `{top}` / `{low}` are the called-out player; `{rest}` is everyone
 * else ("Dantes", or "the squad"); `{All}` is "Both" for a duo and "Everyone" for 3+. One line is
 * picked per match, so a game always reads the same.
 */
export const VERDICTS = {
  hardCarry: [
    "{top} put {rest} on their back",
    "{top} hard carried {rest}",
    "{rest} got a free win from {top}",
    "{top} played 1v9 and won",
  ],
  carry: ["{top} carried", "{top} did the heavy lifting", "{top} had {rest} covered", "{top} brought {rest} along"],
  edge: ["{top} edged it", "{top} pulled a bit more weight", "Slight carry from {top}"],
  passenger: ["{low} got carried", "{low} was along for the ride", "{low} enjoyed the free win", "{rest} carried {low}"],
  winTogether: ["Carried together", "Perfectly balanced", "{All} pulled their weight", "Nobody got carried"],
  soloLost: [
    "{low} solo lost it for {rest}",
    "{rest} had to watch {low} run it down",
    "{low} ran it all the way down",
    "{rest} never stood a chance with {low}",
  ],
  ranDown: ["{low} ran it down", "{low} was the weak link", "{low} had a rough one", "{low} owes {rest} an apology"],
  offDay: ["{low} had an off day", "{low} could've done more", "Slightly more {low}'s fault"],
  tried: ["{top} tried their best", "{top} did everything they could", "{top} deserved better", "Not {top}'s fault"],
  loseTogether: ["Went down together", "Shared the blame equally", "Nobody's fault. Everybody's fault", "{All} ran it down"],
} as const satisfies Record<VerdictTier, readonly string[]>;


export interface Verdict {
  tier: VerdictTier;
  /** Index of the called-out member in the input; null for the "together" tiers. */
  targetIndex: number | null;
  gap: number;
}

/**
 * Tier from teammates' AI Scores (0..100 integers, see toScore100). Null unless every member
 * (2+) is scored and the game isn't a remake.
 */
export function verdictTier(scores: readonly (number | null)[], outcome: Outcome): Verdict | null {
  if (outcome === "remake" || scores.length < 2 || scores.some((s) => s === null)) return null;
  const sorted = scores.map((score, index) => ({ score: score as number, index })).sort((a, b) => b.score - a.score);
  const first = sorted[0]!;
  const second = sorted[1]!;
  const last = sorted[sorted.length - 1]!;
  const secondLast = sorted[sorted.length - 2]!;

  if (outcome === "win") {
    const gap = first.score - second.score;
    if (gap >= EDGE_GAP) {
      const tier: VerdictTier = gap >= HARD_GAP ? "hardCarry" : gap >= CARRY_GAP ? "carry" : "edge";
      return { tier, targetIndex: first.index, gap };
    }
    // No clear carry, but a 3+ stack can still have a clear bottom (duos can't: one gap only).
    const bottom = secondLast.score - last.score;
    if (bottom >= CARRY_GAP) return { tier: "passenger", targetIndex: last.index, gap: bottom };
    return { tier: "winTogether", targetIndex: null, gap };
  }
  if (secondLast.score - last.score < TRIED_CLOSE && first.score - second.score >= CARRY_GAP) {
    return { tier: "tried", targetIndex: first.index, gap: first.score - second.score };
  }
  const gap = secondLast.score - last.score;
  const tier: VerdictTier = gap >= HARD_GAP ? "soloLost" : gap >= CARRY_GAP ? "ranDown" : gap >= EDGE_GAP ? "offDay" : "loseTogether";
  return { tier, targetIndex: tier === "loseTogether" ? null : last.index, gap };
}

/** Stable small hash so a match always gets the same line. */
export function pick<T>(options: readonly T[], seed: string): T {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return options[h % options.length] as T;
}

/**
 * The banter line for a tier; `seed` (the match id) picks the same line every time. `size` is the
 * number of teammates compared ("Both" for 2, "Everyone" for more).
 */
export function verdictText(tier: VerdictTier, target: string, rest: string, seed: string, size: number): string {
  return pick(VERDICTS[tier], seed)
    .replaceAll("{top}", target)
    .replaceAll("{low}", target)
    .replaceAll("{rest}", rest)
    .replaceAll("{All}", size === 2 ? "Both" : "Everyone");
}

export interface VerdictBadge {
  label: string;
  /** "carry": solid gold; "down": red. */
  kind: "carry" | "down";
}

/** Badge for the called-out member; null for the "together" tiers. */
export function verdictBadge(tier: VerdictTier): VerdictBadge | null {
  switch (tier) {
    case "hardCarry":
      return { label: "HARD CARRY", kind: "carry" };
    case "carry":
    case "edge":
      return { label: "CARRIED", kind: "carry" };
    case "soloLost":
    case "ranDown":
      return { label: "RAN IT DOWN", kind: "down" };
    case "offDay":
      return { label: "OFF DAY", kind: "down" };
    case "passenger":
      return { label: "PASSENGER", kind: "down" };
    case "tried":
      return { label: "TRIED", kind: "carry" };
    default:
      return null;
  }
}

/** True when the tier is good news for the called-out player (gold), false for red. */
export function isPraise(tier: VerdictTier): boolean {
  return tier === "hardCarry" || tier === "carry" || tier === "edge" || tier === "tried" || tier === "winTogether";
}
