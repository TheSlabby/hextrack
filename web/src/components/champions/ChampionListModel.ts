/**
 * The /champions list: role filter, text search and sorting, all client-side over the rows of
 * `useChampionList` (the API returns every champion in the patch window, most games first).
 */
import type { ChampionListRow, ChampionRole, ChampionTier } from "@/api/types";
import type { ChampionListSort } from "@/router";
import { championTierValue } from "@/lib/championTiers";
import { championDisplayName } from "@/lib/champions";

export type { ChampionListSort };
export type ChampionListDirection = "asc" | "desc";

export interface ChampionListSortState {
  key: ChampionListSort;
  direction: ChampionListDirection;
}

/**
 * The sort when the URL names none: a role reads as a tier list (S first, like u.gg); every role
 * mixes lanes, so it starts with the most played champions.
 */
export function defaultChampionSortKey(role: ChampionRole | null | undefined): ChampionListSort {
  return role ? "tier" : "games";
}

export const CHAMPION_SORT_LABELS: Readonly<Record<ChampionListSort, string>> = {
  tier: "Tier",
  games: "Games",
  win_rate: "Win rate",
  pick_rate: "Pick rate",
  ban_rate: "Ban rate",
  kda: "KDA",
  name: "Name",
};

/** Keys offered in the mobile "Sort by" menu, in display order. */
export const CHAMPION_SORT_MENU: readonly ChampionListSort[] = [
  "tier",
  "games",
  "win_rate",
  "pick_rate",
  "ban_rate",
  "kda",
  "name",
];

/** Fewer games than this in the shown row: dimmed and flagged as a small sample. */
export const SMALL_SAMPLE_GAMES = 100;

/** A role counts for the role filter at this share of the champion's games, or this many games. */
const ROLE_MIN_SHARE = 0.01;
const ROLE_MIN_GAMES = 20;

/** Roles shown as the champion's main roles (icons in the list), most played first. */
const MAIN_ROLE_SHARE = 0.1;
const MAIN_ROLES_MAX = 3;

/** One row as displayed: the champion-wide numbers, or one role's when the role filter is on. */
export interface ChampionListItem {
  row: ChampionListRow;
  /** 1-based place in the sorted list before the text search (so a search keeps the place). */
  rank: number;
  name: string;
  games: number;
  wins: number;
  winRate: number;
  pickRate: number;
  /** Champion-wide: bans happen before roles are picked. */
  banRate: number;
  /** Champion-wide (the list has no per-role KDA). */
  kda: number;
  mainRoles: ChampionRole[];
  /** Tier in the filtered role, or (every role) in the champion's most played role. */
  tier: ChampionTier | null;
  /** The role `tier` is for. */
  tierRole: ChampionRole | null;
  smallSample: boolean;
}

/** Names read naturally A to Z; tiers start at S; every numeric column starts with the highest value. */
export function defaultChampionDirection(key: ChampionListSort): ChampionListDirection {
  return key === "name" ? "asc" : "desc";
}

/** Clicking a header: flip the direction on the active column, else start at its default. */
export function nextChampionSort(current: ChampionListSortState, key: ChampionListSort): ChampionListSortState {
  if (current.key === key) return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  return { key, direction: defaultChampionDirection(key) };
}

export function mainRoles(row: ChampionListRow): ChampionRole[] {
  const roles = row.roles.filter((role) => role.share >= MAIN_ROLE_SHARE).slice(0, MAIN_ROLES_MAX);
  // A champion spread thin still shows its most played role.
  if (roles.length === 0 && row.roles[0]) return [row.roles[0].position];
  return roles.map((role) => role.position);
}

/** The role with the most games (the API lists them most played first, but don't rely on it). */
function mostPlayedRole(row: ChampionListRow): ChampionListRow["roles"][number] | null {
  return row.roles.reduce<ChampionListRow["roles"][number] | null>(
    (best, role) => (!best || role.games > best.games ? role : best),
    null,
  );
}

function toItem(row: ChampionListRow, role: ChampionRole | null, totalMatches: number): ChampionListItem | null {
  const base = {
    row,
    rank: 0,
    name: championDisplayName(row.champion_name),
    banRate: row.ban_rate,
    kda: row.kda,
    mainRoles: mainRoles(row),
  };
  if (!role) {
    const main = mostPlayedRole(row);
    return {
      ...base,
      tier: main?.tier ?? null,
      tierRole: main?.position ?? null,
      games: row.games,
      wins: row.wins,
      winRate: row.win_rate,
      pickRate: row.pick_rate,
      smallSample: row.games < SMALL_SAMPLE_GAMES,
    };
  }
  const stats = row.roles.find((r) => r.position === role);
  if (!stats || (stats.share < ROLE_MIN_SHARE && stats.games < ROLE_MIN_GAMES)) return null;
  return {
    ...base,
    games: stats.games,
    wins: stats.wins,
    winRate: stats.win_rate,
    pickRate: totalMatches > 0 ? stats.games / totalMatches : 0,
    tier: stats.tier,
    tierRole: role,
    smallSample: stats.games < SMALL_SAMPLE_GAMES,
  };
}

function sortValue(item: ChampionListItem, key: ChampionListSort): number {
  switch (key) {
    case "tier":
      return championTierValue(item.tier);
    case "games":
      return item.games;
    case "win_rate":
      return item.winRate;
    case "pick_rate":
      return item.pickRate;
    case "ban_rate":
      return item.banRate;
    case "kda":
      return item.kda;
    case "name":
      return 0;
  }
}

const byName = (a: ChampionListItem, b: ChampionListItem) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" });

/** Rows for the role (null = every role), sorted and numbered. */
export function buildChampionItems(
  rows: readonly ChampionListRow[],
  role: ChampionRole | null,
  totalMatches: number,
  sort: ChampionListSortState,
): ChampionListItem[] {
  const items = rows.flatMap((row) => toItem(row, role, totalMatches) ?? []);
  const sign = sort.direction === "asc" ? 1 : -1;
  items.sort((a, b) => {
    if (sort.key === "name") return sign * byName(a, b);
    // Unranked rows stay at the bottom in either direction.
    if (sort.key === "tier" && !a.tier !== !b.tier) return a.tier ? -1 : 1;
    // Ties (and equal rates) fall back to games, then name, so the order is stable.
    return sign * (sortValue(a, sort.key) - sortValue(b, sort.key)) || b.games - a.games || byName(a, b);
  });
  items.forEach((item, index) => {
    item.rank = index + 1;
  });
  return items;
}

/** Lower case with punctuation and spaces removed: "Kai'Sa" and "kaisa", "Dr. Mundo" and "drmundo". */
export function normalizeChampionQuery(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

/** Display name or Data Dragon key contains the query ("wukong" and "monkeyking" both work). */
export function matchesChampionQuery(query: string, key: string, name: string = championDisplayName(key)): boolean {
  const q = normalizeChampionQuery(query);
  if (!q) return true;
  return normalizeChampionQuery(name).includes(q) || normalizeChampionQuery(key).includes(q);
}

export function filterChampionItems(items: readonly ChampionListItem[], query: string): ChampionListItem[] {
  if (!normalizeChampionQuery(query)) return [...items];
  return items.filter((item) => matchesChampionQuery(query, item.row.champion_name, item.name));
}

export interface ChampionListColumn {
  id: string;
  label: string;
  sortKey?: ChampionListSort;
  align?: "left" | "right" | "center";
  hint?: string;
  className?: string;
}

/** Desktop table columns, shared with the loading skeleton so both render the same widths. */
export function championListColumns(role: ChampionRole | null): readonly ChampionListColumn[] {
  return [
    { id: "rank", label: "#", align: "center", className: "w-12 pl-4" },
    { id: "champion", label: "Champion", sortKey: "name", className: "min-w-40" },
    {
      id: "tier",
      label: "Tier",
      sortKey: "tier",
      align: "center",
      className: "w-18",
      hint: role
        ? "Strength against the other champions in this role, from win, pick and ban rates. Not the Hex Score."
        : "Strength in the champion's most played role (icon), from win, pick and ban rates. Not the Hex Score.",
    },
    { id: "roles", label: "Roles", className: "w-24", hint: "Main roles: at least 10% of the champion's games" },
    {
      id: "win_rate",
      label: "Win rate",
      sortKey: "win_rate",
      className: "w-28",
      hint: role ? "Win rate in this role" : undefined,
    },
    {
      id: "pick_rate",
      label: "Pick rate",
      sortKey: "pick_rate",
      align: "right",
      className: "w-24",
      hint: role ? "Share of games with the champion in this role" : "Share of games with the champion in them",
    },
    {
      id: "ban_rate",
      label: "Ban rate",
      sortKey: "ban_rate",
      align: "right",
      className: "w-24",
      hint: "Share of games where the champion was banned (every role)",
    },
    { id: "games", label: "Games", sortKey: "games", align: "right", className: "w-24" },
    {
      id: "kda",
      label: "KDA",
      sortKey: "kda",
      align: "right",
      className: "w-20 pr-4",
      hint: role ? "(Kills + assists) / deaths over every role" : "(Kills + assists) / deaths",
    },
  ];
}

/** Win rate text colour against a coin flip (the number itself is always shown too). */
export function winRateClass(rate: number): string {
  if (rate >= 0.53) return "text-win";
  if (rate >= 0.505) return "text-win/80";
  if (rate <= 0.47) return "text-loss";
  if (rate <= 0.495) return "text-loss/80";
  return "text-text";
}
