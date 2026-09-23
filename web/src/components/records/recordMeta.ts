/**
 * Presentation for the records API (no React here, so component files stay react-refresh
 * clean): icons, value formatting per unit, the page's card order and the personal-bests pick.
 */
import {
  Coins,
  Crosshair,
  Eye,
  Flame,
  Gauge,
  HandHelping,
  Handshake,
  HeartPulse,
  Hourglass,
  ShieldHalf,
  Skull,
  Sparkles,
  Swords,
  Target,
  Timer,
  Wheat,
  Zap,
  type LucideIcon,
} from "lucide-react";

import type { LeaderboardQueue, RecordCategory, RecordEntry, RecordKey, RecordUnit, StatsSince } from "@/api/types";
import { formatDate, formatDuration, formatInteger, formatPercent } from "@/lib/format";
import { formatRiotId } from "@/lib/riotId";
import { toScore100 } from "@/lib/score";

export interface RecordMeta {
  icon: LucideIcon;
  /** Word after the big number ("35 kills"); empty when the value speaks for itself (26:14). */
  suffix: string;
  /** Short title for compact tiles (personal bests). */
  short: string;
  /** Qualifier shown under the card, when the record has one. */
  note?: string;
}

export const RECORD_META: Readonly<Record<RecordKey, RecordMeta>> = {
  most_kills: { icon: Crosshair, suffix: "kills", short: "Kills" },
  most_assists: { icon: HandHelping, suffix: "assists", short: "Assists" },
  most_deaths: { icon: Skull, suffix: "deaths", short: "Deaths", note: "The one record nobody wants." },
  best_kda: {
    icon: Target,
    suffix: "KDA",
    short: "KDA",
    note: "(Kills + assists) / deaths, at least 5 takedowns.",
  },
  most_damage: { icon: Flame, suffix: "damage", short: "Damage" },
  highest_damage_per_min: { icon: Zap, suffix: "/ min", short: "Damage / min" },
  most_cs: { icon: Wheat, suffix: "CS", short: "CS" },
  highest_cs_per_min: { icon: Gauge, suffix: "CS / min", short: "CS / min" },
  most_gold: { icon: Coins, suffix: "gold", short: "Gold" },
  highest_vision: { icon: Eye, suffix: "vision", short: "Vision score" },
  highest_kill_participation: {
    icon: Handshake,
    suffix: "KP",
    short: "Kill participation",
    note: "Only games where the team got 10+ kills.",
  },
  longest_game: { icon: Hourglass, suffix: "", short: "Longest game" },
  fastest_win: {
    icon: Timer,
    suffix: "",
    short: "Fastest win",
    note: "Wins this short usually mean the other team surrendered.",
  },
  highest_ai_score: { icon: Sparkles, suffix: "", short: "AI Score" },
  largest_killing_spree: { icon: Swords, suffix: "in a row", short: "Killing spree" },
  most_damage_taken: { icon: ShieldHalf, suffix: "taken", short: "Damage taken" },
  most_healing: { icon: HeartPulse, suffix: "healed", short: "Healing" },
};

/**
 * Card order on /records: rows of four on wide screens (fights, damage, farm and vision, the
 * game itself). highest_ai_score is left out: it gets its own wide card after the grid.
 */
export const RECORD_GRID_ORDER: readonly RecordKey[] = [
  "most_kills",
  "most_assists",
  "best_kda",
  "largest_killing_spree",
  "most_damage",
  "highest_damage_per_min",
  "most_damage_taken",
  "most_healing",
  "most_cs",
  "highest_cs_per_min",
  "most_gold",
  "highest_vision",
  "highest_kill_participation",
  "most_deaths",
  "longest_game",
  "fastest_win",
];

/** The eight categories on the Overview tab's personal-bests card. */
export const PERSONAL_BEST_KEYS: readonly RecordKey[] = [
  "most_kills",
  "most_assists",
  "best_kda",
  "largest_killing_spree",
  "most_damage",
  "highest_cs_per_min",
  "highest_vision",
  "longest_game",
];

const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const perMinuteFormatter = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** A record value in its unit: 35, 7.33, 3,093.5, 93%, 57:06, 100 (AI Score). */
export function formatRecordValue(unit: RecordUnit, value: number): string {
  switch (unit) {
    case "count":
      return formatInteger(value);
    case "number":
      return numberFormatter.format(value);
    case "per_min":
      return perMinuteFormatter.format(value);
    case "percent":
      return formatPercent(value);
    case "duration":
      return formatDuration(value);
    case "score":
      return String(toScore100(value));
  }
}

/** "35 kills", "57:06", "93% KP" (for aria labels and titles). */
export function recordValueText(category: Pick<RecordCategory, "key" | "unit">, value: number): string {
  const suffix = RECORD_META[category.key].suffix;
  const formatted = formatRecordValue(category.unit, value);
  if (category.unit === "score") return `AI Score ${formatted}`;
  return suffix ? `${formatted} ${suffix}` : formatted;
}

/** Categories by key (the API returns every key, in RecordKey order). */
export function categoriesByKey(categories: readonly RecordCategory[]): Map<RecordKey, RecordCategory> {
  return new Map(categories.map((category) => [category.key, category]));
}

/** "Victory" / "Defeat" for a record game (remakes never hold records). */
export function resultLabel(entry: Pick<RecordEntry, "win">): string {
  return entry.win ? "Victory" : "Defeat";
}

export const PERIOD_LABEL: Readonly<Record<StatsSince, string>> = {
  season: "this season",
  all: "in every stored game",
};

export const QUEUE_CAPTION: Readonly<Record<LeaderboardQueue, string>> = {
  all: "Ranked Solo/Duo and Flex",
  solo: "Ranked Solo/Duo",
  flex: "Ranked Flex",
};

// --- players ------------------------------------------------------------------------------

export interface PlayerInfo {
  iconId: number | null;
  /** Game name, plus the tag when two roster players share the name ("sam #gjoat"). */
  label: string;
}

/** puuid -> icon and display name, from the roster (untracked players fall back to the entry). */
export type PlayerLookup = ReadonlyMap<string, PlayerInfo>;

export function buildPlayerLookup(
  roster: ReadonlyArray<{ puuid: string; game_name: string; tag_line: string; profile_icon_id: number | null }>,
): PlayerLookup {
  const counts = new Map<string, number>();
  for (const player of roster) {
    const key = player.game_name.toLowerCase();
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return new Map(
    roster.map((player) => [
      player.puuid,
      {
        iconId: player.profile_icon_id,
        label:
          (counts.get(player.game_name.toLowerCase()) ?? 0) > 1
            ? formatRiotId(player.game_name, player.tag_line)
            : player.game_name,
      },
    ]),
  );
}

/** Display name of a record holder. */
export function playerLabel(players: PlayerLookup, entry: { puuid: string; game_name: string }): string {
  return players.get(entry.puuid)?.label ?? entry.game_name;
}

const shortDateFormatter = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });

/** "Sep 8" this year, "Sep 8, 2025" before it (tight tiles). */
export function formatCompactDate(value: string, now: Date = new Date()): string {
  const date = new Date(value);
  return date.getFullYear() === now.getFullYear() ? shortDateFormatter.format(date) : formatDate(date);
}
