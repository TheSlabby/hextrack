/** Small helpers shared by the champion detail page's sections. */
import type { ChampionLaneMatchup } from "@/api/types";
import { useItemCatalog, type ItemInfo } from "@/lib/ddragonItems";
import { formatDuration, formatInteger, formatPercent } from "@/lib/format";

/** Win rate text colour: blue when clearly winning, red when clearly losing, plain in between. */
export function winRateTone(rate: number): string {
  if (rate >= 0.53) return "text-win";
  if (rate <= 0.47) return "text-loss";
  return "text-text";
}

/** Rates on this page carry one decimal ("52.4%"): differences between options are small. */
export function pct(rate: number | null | undefined): string {
  return formatPercent(rate, 1);
}

/** Average completion time of a build: "24:31". */
export function buildTime(seconds: number | null | undefined): string | null {
  return seconds === null || seconds === undefined || seconds <= 0 ? null : formatDuration(seconds);
}

/** Short count for a card's corner: "1,234 games with item order". */
export function timelineCount(timelineGames: number, what = "item order"): string {
  return `${formatInteger(timelineGames)} ${timelineGames === 1 ? "game" : "games"} with ${what}`;
}

/** Empty-state text of order-based sections before any timeline is in. */
export const NO_TIMELINE = "Item order comes from match timelines, and none are in for these games yet. Check back soon.";

/** Skill slot number from the API (1 Q, 2 W, 3 E, 4 R) -> key letter. */
export const SKILL_KEYS: Readonly<Record<number, "Q" | "W" | "E" | "R">> = { 1: "Q", 2: "W", 3: "E", 4: "R" };

export function skillKey(slot: number): string {
  return SKILL_KEYS[slot] ?? "?";
}

export interface MatchupLists {
  best: ChampionLaneMatchup[];
  worst: ChampionLaneMatchup[];
  common: ChampionLaneMatchup[];
}

/**
 * Best / worst by the shrunk win rate (so a 5-0 doesn't top the list), most common by games. A
 * champion appears in best or worst, never both; with few opponents the lists stay short.
 */
export function matchupLists(rows: readonly ChampionLaneMatchup[], size = 5): MatchupLists {
  const byAdjusted = [...rows].sort((a, b) => b.adjusted_win_rate - a.adjusted_win_rate || b.games - a.games);
  const best = byAdjusted.slice(0, Math.min(size, Math.ceil(rows.length / 2)));
  const taken = new Set(best.map((row) => row.champion_id));
  const worst = byAdjusted
    .slice()
    .reverse()
    .filter((row) => !taken.has(row.champion_id))
    .slice(0, size);
  const common = [...rows].sort((a, b) => b.games - a.games).slice(0, size);
  return { best, worst, common };
}

/** One item from Data Dragon (at the nearest `<DdragonPatch>`); undefined while loading or when unknown. */
export function useItemInfo(id: number): ItemInfo | undefined {
  return useItemCatalog([id]).info(id);
}

/** The item's name, "Item 1234" until the catalogue answers or when it is unknown. */
export function itemLabel(id: number, info: ItemInfo | undefined): string {
  return info?.name ?? `Item ${id}`;
}
