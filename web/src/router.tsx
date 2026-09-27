/**
 * Code-based route tree. Page components read params/search with `getRouteApi(<path>)` so
 * they never import this module (no import cycles):
 *
 *   const route = getRouteApi("/summoner/$region/$riotId");
 *   const { riotId } = route.useParams();  const { tab } = route.useSearch();
 */
import { createRootRoute, createRoute, createRouter, lazyRouteComponent, Outlet } from "@tanstack/react-router";

import type { ChampionRole, LeaderboardQueue, StackQueue, StackSize, StatsSince } from "@/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { DEFAULT_SORT, SORT_LABELS, type SortDirection, type SortKey } from "@/components/leaderboard/sorting";
import { NotFoundPage, RouteErrorPage, RoutePending } from "@/components/layout/RouteStates";
import { isSummonerTabValue, type SummonerTabValue } from "@/components/summoner/tabs";
import { HomePage } from "@/routes/home";

// The landing page is part of the first paint; every other page (and the chart library it
// pulls in) is fetched on demand, and prefetched on hover by `defaultPreload: "intent"`.
const LeaderboardPage = lazyRouteComponent(() => import("@/routes/leaderboard"), "LeaderboardPage");
const SummonerPage = lazyRouteComponent(() => import("@/routes/summoner"), "SummonerPage");
const MatchPage = lazyRouteComponent(() => import("@/routes/match"), "MatchPage");
const SquadPage = lazyRouteComponent(() => import("@/routes/squad"), "SquadPage");
const RecordsPage = lazyRouteComponent(() => import("@/routes/records"), "RecordsPage");
const StacksPage = lazyRouteComponent(() => import("@/routes/stacks"), "StacksPage");
const LiveGamePage = lazyRouteComponent(() => import("@/routes/live"), "LiveGamePage");
const ChampionsPage = lazyRouteComponent(() => import("@/routes/champions"), "ChampionsPage");
const ChampionPage = lazyRouteComponent(() => import("@/routes/champion"), "ChampionPage");

export interface SummonerSearch {
  tab?: SummonerTabValue;
}

export interface MatchSearch {
  /**
   * Player to highlight: their Riot ID slug ("Name-TAG", preferred: short and readable) or
   * their puuid when the Riot ID is unknown. The match page accepts both.
   */
  player?: string;
}

/** Leaderboard view in the URL; defaults (all queues, AI Score descending) are omitted. */
export interface LeaderboardSearch {
  queue?: Exclude<LeaderboardQueue, "all">;
  sort?: SortKey;
  dir?: SortDirection;
}

/**
 * Period / queue filters in the URL (/squad, /records); defaults (this season, all ranked
 * queues) are omitted: `?since=all&queue=solo`.
 */
export interface StatsFilterSearch {
  since?: Exclude<StatsSince, "season">;
  queue?: Exclude<LeaderboardQueue, "all">;
}

export type SquadSearch = StatsFilterSearch;

export interface RecordsSearch extends StatsFilterSearch {
  /** puuid of one player (player scope); omitted = the whole roster. */
  player?: string;
}

function validateStatsFilterSearch(search: Record<string, unknown>): StatsFilterSearch {
  const result: StatsFilterSearch = {};
  if (search.since === "all") result.since = "all";
  if (search.queue === "solo" || search.queue === "flex") result.queue = search.queue;
  return result;
}

/**
 * /stacks filters; defaults (this season, all queues, full 5-stacks) are omitted:
 * `?since=all&queue=flex&size=4`.
 */
export interface StacksSearch {
  since?: Exclude<StatsSince, "season">;
  queue?: Exclude<StackQueue, "all">;
  size?: Exclude<StackSize, 5>;
}

function validateStacksSearch(search: Record<string, unknown>): StacksSearch {
  const result: StacksSearch = {};
  if (search.since === "all") result.since = "all";
  if (search.queue === "flex") result.queue = "flex";
  // Accept `size=4` whether the router parsed it as a number or left it a string.
  const size = typeof search.size === "string" ? Number(search.size) : search.size;
  if (size === 3 || size === 4) result.size = size;
  return result;
}

/**
 * Champion filters in the URL; defaults (recent patches, all queues, most played role,
 * most games first) are omitted: `/champions?patch=16.18&queue=solo&role=MIDDLE`.
 */
export interface ChampionsSearch {
  /** "season" or one patch ("16.18"); omitted = the two newest patches. */
  patch?: string;
  queue?: Exclude<LeaderboardQueue, "all">;
  role?: ChampionRole;
}

/** The list page also keeps its sort in the URL (omitted = most games first). */
export interface ChampionListSearch extends ChampionsSearch {
  sort?: ChampionListSort;
  dir?: SortDirection;
}

export type ChampionListSort = "games" | "win_rate" | "pick_rate" | "ban_rate" | "kda" | "name";
const CHAMPION_LIST_SORTS: readonly ChampionListSort[] = ["games", "win_rate", "pick_rate", "ban_rate", "kda", "name"];
const CHAMPION_ROLES: readonly ChampionRole[] = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];

function validateChampionsSearch(search: Record<string, unknown>): ChampionsSearch {
  const result: ChampionsSearch = {};
  // Router search parsing turns "16.18" into a number; read it back as the patch string.
  const patch = typeof search.patch === "number" ? String(search.patch) : search.patch;
  if (patch === "season" || (typeof patch === "string" && /^\d{1,2}\.\d{1,2}$/.test(patch))) result.patch = patch;
  if (search.queue === "solo" || search.queue === "flex") result.queue = search.queue;
  if (typeof search.role === "string" && (CHAMPION_ROLES as readonly string[]).includes(search.role)) {
    result.role = search.role as ChampionRole;
  }
  return result;
}

/** Champion page tabs; "build" is the default and omitted from the URL. */
export type ChampionTab = "build" | "matchups" | "squad";

export interface ChampionPageSearch extends ChampionsSearch {
  tab?: Exclude<ChampionTab, "build">;
}

function validateChampionPageSearch(search: Record<string, unknown>): ChampionPageSearch {
  const result: ChampionPageSearch = validateChampionsSearch(search);
  if (search.tab === "matchups" || search.tab === "squad") result.tab = search.tab;
  return result;
}

function validateChampionListSearch(search: Record<string, unknown>): ChampionListSearch {
  const result: ChampionListSearch = validateChampionsSearch(search);
  if (typeof search.sort === "string" && (CHAMPION_LIST_SORTS as readonly string[]).includes(search.sort)) {
    if (search.sort !== "games") result.sort = search.sort as ChampionListSort;
  }
  if (search.dir === "asc" || search.dir === "desc") result.dir = search.dir;
  return result;
}

function validateRecordsSearch(search: Record<string, unknown>): RecordsSearch {
  const result: RecordsSearch = validateStatsFilterSearch(search);
  if (typeof search.player === "string" && search.player.length > 0 && search.player.length <= 100) {
    result.player = search.player;
  }
  return result;
}

function isSortKey(value: unknown): value is SortKey {
  return typeof value === "string" && Object.hasOwn(SORT_LABELS, value);
}

function validateLeaderboardSearch(search: Record<string, unknown>): LeaderboardSearch {
  const result: LeaderboardSearch = {};
  if (search.queue === "solo" || search.queue === "flex") result.queue = search.queue;
  if (isSortKey(search.sort) && search.sort !== DEFAULT_SORT.key) result.sort = search.sort;
  if ((search.dir === "asc" || search.dir === "desc") && (result.sort || search.dir !== DEFAULT_SORT.direction)) {
    result.dir = search.dir;
  }
  return result;
}

const rootRoute = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
  notFoundComponent: NotFoundPage,
  errorComponent: RouteErrorPage,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

const leaderboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/leaderboard",
  validateSearch: validateLeaderboardSearch,
  component: LeaderboardPage,
});

const summonerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/summoner/$region/$riotId",
  validateSearch: (search: Record<string, unknown>): SummonerSearch =>
    typeof search.tab === "string" && isSummonerTabValue(search.tab) ? { tab: search.tab } : {},
  component: SummonerPage,
});

const matchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/match/$matchId",
  validateSearch: (search: Record<string, unknown>): MatchSearch =>
    typeof search.player === "string" && search.player.length > 0 ? { player: search.player } : {},
  component: MatchPage,
});

const liveRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/live/$gameId",
  component: LiveGamePage,
});

const squadRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/squad",
  validateSearch: validateStatsFilterSearch,
  component: SquadPage,
});

const stacksRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/stacks",
  validateSearch: validateStacksSearch,
  component: StacksPage,
});

const recordsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/records",
  validateSearch: validateRecordsSearch,
  component: RecordsPage,
});

const championsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/champions",
  validateSearch: validateChampionListSearch,
  component: ChampionsPage,
});

const championRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/champions/$champion",
  validateSearch: validateChampionPageSearch,
  component: ChampionPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  leaderboardRoute,
  squadRoute,
  stacksRoute,
  recordsRoute,
  championsRoute,
  championRoute,
  summonerRoute,
  matchRoute,
  liveRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0,
  defaultPendingComponent: RoutePending,
  defaultPendingMs: 150,
  defaultErrorComponent: RouteErrorPage,
  defaultNotFoundComponent: NotFoundPage,
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
