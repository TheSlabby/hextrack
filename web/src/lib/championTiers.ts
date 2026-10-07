/**
 * Champion tiers (S..D): how strong a champion is in one role for the patch window, relative to
 * the other champions in that role. The API blends an adjusted win rate, pick rate and ban rate;
 * roughly the top 10% are S, then 20% A, 35% B, 20% C and 15% D. null = too few games to rank.
 * Not a rank tier (`lib/tiers.ts`) and not the AI Score (`lib/score.ts`).
 */
import type { ChampionRole, ChampionTier } from "@/api/types";
import { POSITION_LABELS } from "@/lib/positions";

export const CHAMPION_TIER_ORDER: readonly ChampionTier[] = ["S", "A", "B", "C", "D"];

/** Higher is stronger; unranked (null) sorts below D. */
export function championTierValue(tier: ChampionTier | null | undefined): number {
  return tier ? CHAMPION_TIER_ORDER.length - CHAMPION_TIER_ORDER.indexOf(tier) : 0;
}

/** Badge classes per tier: letter colour, tinted fill and border (static strings so Tailwind sees them). */
export const CHAMPION_TIER_CLASS: Readonly<Record<ChampionTier, string>> = {
  S: "text-champ-tier-s bg-champ-tier-s/15 border-champ-tier-s/50 shadow-glow-champ-tier-s",
  A: "text-champ-tier-a bg-champ-tier-a/12 border-champ-tier-a/40",
  B: "text-champ-tier-b bg-champ-tier-b/10 border-champ-tier-b/30",
  C: "text-champ-tier-c bg-champ-tier-c/8 border-champ-tier-c/20",
  D: "text-champ-tier-d bg-champ-tier-d/10 border-champ-tier-d/30",
};

/** One-line reading of each tier, used in tooltips. */
export const CHAMPION_TIER_SUMMARY: Readonly<Record<ChampionTier, string>> = {
  S: "One of the strongest picks",
  A: "A strong pick",
  B: "A solid, middle-of-the-pack pick",
  C: "A below-average pick",
  D: "One of the weakest picks",
};

/** How tiers are made, for tooltips and footnotes. */
export const CHAMPION_TIER_NOTE =
  "Tiers compare champions in the same role for these patches, from win rate (adjusted for sample size), pick rate and ban rate. They are not the Hex Score.";

/** "S tier in Mid" / "S tier". */
export function championTierLabel(tier: ChampionTier, role?: ChampionRole | null): string {
  return role ? `${tier} tier in ${POSITION_LABELS[role]}` : `${tier} tier`;
}
