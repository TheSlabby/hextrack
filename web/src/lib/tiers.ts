/** Ranked tier order, labels and colours (Hextech night palette). */
import type { Division, RankEntry, Tier } from "@/api/types";

export const TIER_ORDER: readonly Tier[] = [
  "IRON",
  "BRONZE",
  "SILVER",
  "GOLD",
  "PLATINUM",
  "EMERALD",
  "DIAMOND",
  "MASTER",
  "GRANDMASTER",
  "CHALLENGER",
];

export const DIVISION_ORDER: readonly Division[] = ["IV", "III", "II", "I"];

export const APEX_TIERS: ReadonlySet<Tier> = new Set<Tier>(["MASTER", "GRANDMASTER", "CHALLENGER"]);

export const TIER_LABELS: Readonly<Record<Tier, string>> = {
  IRON: "Iron",
  BRONZE: "Bronze",
  SILVER: "Silver",
  GOLD: "Gold",
  PLATINUM: "Platinum",
  EMERALD: "Emerald",
  DIAMOND: "Diamond",
  MASTER: "Master",
  GRANDMASTER: "Grandmaster",
  CHALLENGER: "Challenger",
};

/** Hex colours (mirrors the --color-tier-* tokens in index.css; use for SVG/charts). */
export const TIER_COLORS: Readonly<Record<Tier, string>> = {
  IRON: "#6b6f76",
  BRONZE: "#a86b4a",
  SILVER: "#9fb1c2",
  GOLD: "#d4af37",
  PLATINUM: "#3fb6a8",
  EMERALD: "#2ecc71",
  DIAMOND: "#5b8def",
  MASTER: "#b05bd9",
  GRANDMASTER: "#e0474c",
  CHALLENGER: "#f4c874",
};

/** Tailwind text-colour class per tier (static strings so Tailwind can see them). */
export const TIER_TEXT_CLASS: Readonly<Record<Tier, string>> = {
  IRON: "text-tier-iron",
  BRONZE: "text-tier-bronze",
  SILVER: "text-tier-silver",
  GOLD: "text-tier-gold",
  PLATINUM: "text-tier-platinum",
  EMERALD: "text-tier-emerald",
  DIAMOND: "text-tier-diamond",
  MASTER: "text-tier-master",
  GRANDMASTER: "text-tier-grandmaster",
  CHALLENGER: "text-tier-challenger",
};

/** Colour for "unranked" states. */
export const UNRANKED_COLOR = "#5f6b82";

export function isApexTier(tier: Tier): boolean {
  return APEX_TIERS.has(tier);
}

export function tierIndex(tier: Tier): number {
  return TIER_ORDER.indexOf(tier);
}

export function tierColor(tier: Tier | null | undefined): string {
  return tier ? TIER_COLORS[tier] : UNRANKED_COLOR;
}

/** "Diamond II", "Master", "Unranked". */
export function formatTier(tier: Tier | null | undefined, rank?: Division | null): string {
  if (!tier) return "Unranked";
  if (isApexTier(tier) || !rank) return TIER_LABELS[tier];
  return `${TIER_LABELS[tier]} ${rank}`;
}

/** "Diamond II · 54 LP". */
export function formatRank(entry: Pick<RankEntry, "tier" | "rank" | "lp"> | null | undefined): string {
  if (!entry) return "Unranked";
  return `${formatTier(entry.tier, entry.rank)} · ${entry.lp} LP`;
}

/** Short form for tight spaces: "D2", "M", "GM", "C". */
export function shortTier(tier: Tier | null | undefined, rank?: Division | null): string {
  if (!tier) return "UR";
  const short: Record<Tier, string> = {
    IRON: "I",
    BRONZE: "B",
    SILVER: "S",
    GOLD: "G",
    PLATINUM: "P",
    EMERALD: "E",
    DIAMOND: "D",
    MASTER: "M",
    GRANDMASTER: "GM",
    CHALLENGER: "C",
  };
  if (isApexTier(tier) || !rank) return short[tier];
  return `${short[tier]}${DIVISION_ORDER.length - DIVISION_ORDER.indexOf(rank)}`;
}

/** Mirrors backend rank_value: tier*400 + division*100 + lp; apex tiers share MASTER_BASE + lp. */
export const MASTER_BASE = 2800;

