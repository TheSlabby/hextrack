/**
 * Shared helpers for the Stacks page (no React here, so component files stay
 * react-refresh clean).
 */
import type { StackPlayer, StackQueue, StackSize, StackSummary, StatsSince } from "@/api/types";
import { toSlug } from "@/lib/riotId";

/** "5-stack", "4+ stack", "3+ stack". */
export function stackLabel(size: StackSize): string {
  return size === 5 ? "5-stack" : `${size}+ stack`;
}

/** Plural for headings: "5-stacks", "4+ stacks". */
export function stackLabelPlural(size: StackSize): string {
  return `${stackLabel(size)}s`;
}

/** Queues that never count as stacks (Arena pairs, customs). Mirrors ARENA_QUEUES | CUSTOM_QUEUES in api/src/hextrack/queues.py. */
export const NON_STACK_QUEUES: ReadonlySet<number> = new Set([0, 1700, 1710, 3100]);

export const STACK_SIZES: readonly StackSize[] = [5, 4, 3];

export const STACK_QUEUE_LABEL: Readonly<Record<StackQueue, string>> = {
  all: "All queues",
  flex: "Ranked Flex",
};

export const STACK_PERIOD_LABEL: Readonly<Record<StatsSince, string>> = {
  season: "This season",
  all: "All time",
};

export type PlayerLookup = ReadonlyMap<string, StackPlayer>;

/** puuid -> player, for lineups, awards and highlights (which only carry puuids). */
export function playerLookup(data: Pick<StackSummary, "players">): PlayerLookup {
  return new Map(data.players.map((p) => [p.puuid, p]));
}

/** Display name for a puuid ("Unknown player" if they left the roster). */
export function playerName(lookup: PlayerLookup, puuid: string): string {
  return lookup.get(puuid)?.game_name ?? "Unknown player";
}

/** `?player=` value for match links (Name-TAG, or the raw puuid). */
export function playerParam(lookup: PlayerLookup, puuid: string): string {
  const p = lookup.get(puuid);
  return p ? toSlug(p.game_name, p.tag_line) : puuid;
}
