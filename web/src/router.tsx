/**
 * Code-based route tree. Page components read params/search with `getRouteApi(<path>)` so
 * they never import this module (no import cycles):
 *
 *   const route = getRouteApi("/summoner/$region/$riotId");
 *   const { riotId } = route.useParams();  const { tab } = route.useSearch();
 */
import { createRootRoute, createRoute, createRouter, lazyRouteComponent, Outlet } from "@tanstack/react-router";

import type { LeaderboardQueue } from "@/api/types";
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

const routeTree = rootRoute.addChildren([indexRoute, leaderboardRoute, summonerRoute, matchRoute]);

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
