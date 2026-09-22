/**
 * Queue ids and labels, the single source for queue names in the UI.
 *
 * Riot adds queue ids faster than anyone maps them (queue 710 arrived in August 2026 and is in
 * no static list), so every label falls back to the game mode before it falls back to the raw
 * id: an unmapped Summoner's Rift queue reads "Summoner's Rift", never "Queue 710".
 */
import type { QueueType } from "@/api/types";

export const QUEUE_SOLO = 420;
export const QUEUE_FLEX = 440;
export const RANKED_QUEUES: readonly number[] = [QUEUE_SOLO, QUEUE_FLEX];

export const QUEUE_LABELS: Readonly<Record<number, string>> = {
  0: "Custom",
  400: "Normal Draft",
  420: "Ranked Solo/Duo",
  430: "Normal Blind",
  440: "Ranked Flex",
  450: "ARAM",
  480: "Swiftplay",
  490: "Quickplay",
  700: "Clash",
  720: "ARAM Clash",
  830: "Co-op vs AI",
  840: "Co-op vs AI",
  850: "Co-op vs AI",
  900: "ARURF",
  1700: "Arena",
  1710: "Arena",
  1900: "URF",
};

/** Compact names for dense rows ("Solo/Duo"). */
const SHORT_LABELS: Readonly<Record<number, string>> = {
  400: "Draft",
  420: "Solo/Duo",
  430: "Blind",
  440: "Flex",
  450: "ARAM",
  480: "Swiftplay",
  490: "Quickplay",
  700: "Clash",
  900: "ARURF",
  1700: "Arena",
  1710: "Arena",
  1900: "URF",
};

/** Names for match rows, where "Ranked Solo" reads better than "Ranked Solo/Duo". */
const ROW_LABELS: Readonly<Record<number, string>> = {
  ...QUEUE_LABELS,
  420: "Ranked Solo",
};

/** `game_mode` from match-v5 -> what a player calls it. */
const GAME_MODE_LABELS: Readonly<Record<string, string>> = {
  CLASSIC: "Summoner's Rift",
  ARAM: "ARAM",
  CHERRY: "Arena",
  URF: "URF",
  ARURF: "ARURF",
  ONEFORALL: "One for All",
  NEXUSBLITZ: "Nexus Blitz",
  ULTBOOK: "Ultimate Spellbook",
  STRAWBERRY: "Swarm",
  BRAWL: "Brawl",
  TUTORIAL: "Tutorial",
  PRACTICETOOL: "Practice Tool",
};

/** Compact game-mode names, for the same narrow columns as SHORT_LABELS. */
const GAME_MODE_SHORT: Readonly<Record<string, string>> = {
  CLASSIC: "Rift",
  NEXUSBLITZ: "Blitz",
  ULTBOOK: "Spellbook",
  PRACTICETOOL: "Practice",
};

/** Name of a game mode ("CLASSIC" -> "Summoner's Rift"); null when the mode is unknown too. */
function gameModeLabel(gameMode: string | null | undefined, short = false): string | null {
  const mode = gameMode?.trim().toUpperCase();
  if (!mode) return null;
  return (short ? GAME_MODE_SHORT[mode] : undefined) ?? GAME_MODE_LABELS[mode] ?? null;
}

/** A server label the backend made up for an id it doesn't know ("Queue 710"). */
function isPlaceholderLabel(label: string | null | undefined): boolean {
  return !label || /^queue \d+$/i.test(label.trim());
}

function fallbackLabel(queueId: number, gameMode: string | null | undefined, short = false): string {
  return gameModeLabel(gameMode, short) ?? `Queue ${queueId}`;
}

/**
 * Full queue name. Prefers the API's own label (`MatchSummary.queue_label`, which follows
 * Riot's list) and falls back to the local table, then the game mode.
 */
export function queueLabel(queueId: number, gameMode?: string | null, serverLabel?: string | null): string {
  if (serverLabel && !isPlaceholderLabel(serverLabel)) return serverLabel;
  return QUEUE_LABELS[queueId] ?? fallbackLabel(queueId, gameMode);
}

/** Queue name for a dense match row ("Ranked Solo"). Used by components/match/matchUtils. */
export function queueRowLabel(queueId: number, gameMode?: string | null, serverLabel?: string | null): string {
  return ROW_LABELS[queueId] ?? queueLabel(queueId, gameMode, serverLabel);
}

/** Shortest queue name, for chips and narrow columns ("Solo/Duo"). */
export function queueShortLabel(queueId: number, gameMode?: string | null): string {
  return SHORT_LABELS[queueId] ?? QUEUE_LABELS[queueId] ?? fallbackLabel(queueId, gameMode, true);
}

export function isRankedQueue(queueId: number): boolean {
  return RANKED_QUEUES.includes(queueId);
}

export const QUEUE_TYPE_LABELS: Readonly<Record<QueueType, string>> = {
  RANKED_SOLO_5x5: "Ranked Solo/Duo",
  RANKED_FLEX_SR: "Ranked Flex",
};
