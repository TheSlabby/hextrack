/** Pure presentation helpers for the summoner page. */
import type { Division, RankEntry, Tier } from "@/api/types";
import { DIVISION_ORDER, TIER_COLORS, TIER_LABELS, TIER_ORDER, isApexTier } from "@/lib/tiers";

/** Static Tailwind background classes per tier (so the classes survive the build scan). */
export const TIER_BG_CLASS: Readonly<Record<Tier, string>> = {
  IRON: "bg-tier-iron",
  BRONZE: "bg-tier-bronze",
  SILVER: "bg-tier-silver",
  GOLD: "bg-tier-gold",
  PLATINUM: "bg-tier-platinum",
  EMERALD: "bg-tier-emerald",
  DIAMOND: "bg-tier-diamond",
  MASTER: "bg-tier-master",
  GRANDMASTER: "bg-tier-grandmaster",
  CHALLENGER: "bg-tier-challenger",
};

function channel(hex: string, index: number): number {
  return Number.parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16);
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = [0, 1, 2].map((i) => {
    const c = channel(hex, i) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function mixWithWhite(hex: string, amount: number): string {
  const mixed = [0, 1, 2].map((i) => {
    const c = channel(hex, i);
    return Math.round(c + (255 - c) * amount)
      .toString(16)
      .padStart(2, "0");
  });
  return `#${mixed.join("")}`;
}

/**
 * The colour lifted toward white just enough to reach `target` contrast on `surface`
 * (WCAG AA for small text by default). Keeps tier-tinted labels legible: Iron and Bronze
 * are below 4.5:1 on the card surface at their token values.
 */
export function readableOn(hex: string, surface = "#0d111a", target = 4.5): string {
  for (let step = 0; step <= 20; step += 1) {
    const candidate = mixWithWhite(hex, step * 0.05);
    if (contrastRatio(candidate, surface) >= target) return candidate;
  }
  return "#ffffff";
}

const READABLE_TIER_COLORS = Object.fromEntries(
  TIER_ORDER.map((tier) => [tier, readableOn(TIER_COLORS[tier])]),
) as Record<Tier, string>;

/** Tier colour that passes AA as small text on surface-1. */
export function readableTierColor(tier: Tier): string {
  return READABLE_TIER_COLORS[tier];
}

/** Label of the division above this one: Gold II -> "Gold I", Gold I -> "Platinum IV", Diamond I -> "Master". */
export function nextDivisionLabel(tier: Tier, rank: Division | null): string | null {
  if (isApexTier(tier) || rank === null) return null;
  const divisionIndex = DIVISION_ORDER.indexOf(rank);
  const nextDivision = DIVISION_ORDER[divisionIndex + 1];
  if (nextDivision) return `${TIER_LABELS[tier]} ${nextDivision}`;
  const nextTier = TIER_ORDER[TIER_ORDER.indexOf(tier) + 1];
  if (!nextTier) return null;
  return isApexTier(nextTier) ? TIER_LABELS[nextTier] : `${TIER_LABELS[nextTier]} IV`;
}

/** Total games on a rank entry. */
export function rankGames(entry: Pick<RankEntry, "wins" | "losses">): number {
  return entry.wins + entry.losses;
}

/** "na1" -> "NA", "euw1" -> "EUW", "oc1" -> "OCE". */
export function platformLabel(platform: string): string {
  const base = platform.replace(/\d+$/, "").toUpperCase();
  return base === "OC" ? "OCE" : base;
}

/** Parse an ISO timestamp; null for null/invalid input. */
export function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}
