/**
 * Leaderboard ordering. "Standing" is the roster's overall order; the table can be re-sorted by
 * any column but the # column keeps the standing.
 *
 * A standing needs a season worth playing: 20 ranked games (less on a young roster, where nobody
 * has that many yet), and the average AI Score it sorts on is pulled towards a coin flip by 20
 * games of prior. Without both, a 10-game player on a hot streak outranks someone with 900 games,
 * and their podium ring says nothing about a season.
 */
import type { LeaderboardEntry, LeaderboardQueue, RankEntry } from "@/api/types";

export type SortKey = "standing" | "player" | "rank" | "games" | "winrate" | "kda" | "ai" | "lp";
export type SortDirection = "asc" | "desc";

export interface SortState {
  key: SortKey;
  direction: SortDirection;
}

/** The roster's own order, so the first view of the table matches the # column. */
export const DEFAULT_SORT: SortState = { key: "standing", direction: "asc" };

export const SORT_LABELS: Readonly<Record<SortKey, string>> = {
  standing: "Standing",
  player: "Name",
  rank: "Rank",
  games: "Games",
  winrate: "Win rate",
  kda: "KDA",
  ai: "AI Score",
  lp: "Season LP",
};

/** Keys offered in the mobile "Sort by" menu, in display order. */
export const SORT_MENU_KEYS: readonly SortKey[] = ["standing", "ai", "winrate", "games", "kda", "lp", "rank", "player"];

/** Ranked games needed for a standing (capped at the roster's best when nobody is there yet). */
const STANDING_MIN_GAMES = 20;

/** Games of "coin flip" prior mixed into an average AI Score before it is ranked. */
const PRIOR_GAMES = 20;
const PRIOR_MEAN = 0.5;

/** Names read naturally A to Z; every numeric column starts with the best value. */
export function defaultDirection(key: SortKey): SortDirection {
  return key === "player" || key === "standing" ? "asc" : "desc";
}

/** Clicking a header: flip the direction on the active column, else start at its default. */
export function nextSort(current: SortState, key: SortKey): SortState {
  if (current.key === key) return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  return { key, direction: defaultDirection(key) };
}

export interface DisplayedRank {
  entry: RankEntry;
  /** True when the solo rank was missing and the flex rank is shown instead. */
  isFallback: boolean;
}

/** The rank to show for a queue filter: flex for "flex", otherwise solo with a flex fallback. */
export function displayedRank(entry: LeaderboardEntry, queue: LeaderboardQueue): DisplayedRank | null {
  if (queue === "flex") return entry.flex ? { entry: entry.flex, isFallback: false } : null;
  if (entry.solo) return { entry: entry.solo, isFallback: false };
  if (queue === "all" && entry.flex) return { entry: entry.flex, isFallback: true };
  return null;
}

const collator = new Intl.Collator("en", { sensitivity: "base", numeric: true });

function compareNullableDesc(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return b - a;
}

/**
 * Average AI Score pulled towards a coin flip by 20 games of prior, so a handful of good games
 * can't top the roster. Null when the player has no scored games.
 */
function shrunkAiScore(entry: LeaderboardEntry): number | null {
  if (entry.avg_ai_score === null) return null;
  const games = Math.max(0, entry.games);
  return (entry.avg_ai_score * games + PRIOR_MEAN * PRIOR_GAMES) / (games + PRIOR_GAMES);
}

export interface Standings {
  /** Ranked games a player needs this season to hold a standing. */
  minGames: number;
  /** Everyone, best first: players with a standing, then the rest. */
  ordered: LeaderboardEntry[];
  /** Players with enough games to hold a standing, best first. */
  ranked: LeaderboardEntry[];
  /** puuid -> 1-based standing; absent for players below `minGames`. */
  rank: ReadonlyMap<string, number>;
  /** Games still needed for a standing (0 once a player has one). */
  gamesNeeded: (entry: LeaderboardEntry) => number;
}

/** Overall roster order for a threshold: qualified first, then shrunk AI Score, games, name. */
function compareFor(minGames: number) {
  return (a: LeaderboardEntry, b: LeaderboardEntry): number => {
    const qualified = Number(b.games >= minGames) - Number(a.games >= minGames);
    return (
      qualified ||
      compareNullableDesc(shrunkAiScore(a), shrunkAiScore(b)) ||
      Number(b.games > 0) - Number(a.games > 0) ||
      b.winrate - a.winrate ||
      b.games - a.games ||
      collator.compare(a.game_name, b.game_name)
    );
  };
}

/** The roster's standing: who is ranked, in what order, and who still needs games. */
export function computeStandings(entries: readonly LeaderboardEntry[]): Standings {
  const mostGames = entries.reduce((max, entry) => Math.max(max, entry.games), 0);
  const minGames = Math.max(1, Math.min(STANDING_MIN_GAMES, mostGames));
  const ordered = [...entries].sort(compareFor(minGames));
  const ranked = ordered.filter((entry) => entry.games >= minGames);
  const rank = new Map(ranked.map((entry, index) => [entry.puuid, index + 1]));
  return {
    minGames,
    ordered,
    ranked,
    rank,
    gamesNeeded: (entry) => Math.max(0, minGames - entry.games),
  };
}

function numericValue(entry: LeaderboardEntry, key: SortKey, queue: LeaderboardQueue): number | null {
  switch (key) {
    case "rank":
      return displayedRank(entry, queue)?.entry.rank_value ?? null;
    case "games":
      return entry.games;
    case "winrate":
      return entry.games > 0 ? entry.winrate : null;
    case "kda":
      return entry.games > 0 ? entry.kda : null;
    case "ai":
      return entry.avg_ai_score;
    case "lp":
      return entry.lp_delta;
    default:
      return null;
  }
}

/**
 * Sort by a column. Missing values (unranked, no games, unscored) always sink to the
 * bottom whichever way the column is sorted; ties fall back to the overall standing.
 */
export function sortEntries(
  entries: readonly LeaderboardEntry[],
  sort: SortState,
  queue: LeaderboardQueue,
  standings: Standings,
): LeaderboardEntry[] {
  const sign = sort.direction === "asc" ? 1 : -1;
  const byStanding = compareFor(standings.minGames);
  return [...entries].sort((a, b) => {
    if (sort.key === "standing") return sign * byStanding(a, b);
    if (sort.key === "player") {
      return (
        sign * (collator.compare(a.game_name, b.game_name) || collator.compare(a.tag_line, b.tag_line)) ||
        byStanding(a, b)
      );
    }
    const va = numericValue(a, sort.key, queue);
    const vb = numericValue(b, sort.key, queue);
    if (va === null && vb === null) return byStanding(a, b);
    if (va === null) return 1;
    if (vb === null) return -1;
    return sign * (va - vb) || byStanding(a, b);
  });
}
