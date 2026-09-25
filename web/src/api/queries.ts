/**
 * TanStack Query hooks for every HexTrack API endpoint.
 *
 * Components use these hooks (never `api` directly) so caching, keys and error handling stay
 * consistent. All hooks throw `ApiError` (see ./client) on failure.
 */
import {
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, isApiError, request, type ApiError } from "./client";
import type {
  AiExplain,
  LeaderboardQueue,
  MatchPage,
  QueueType,
  RefreshResult,
  RiotIdParts,
  StackGamePage,
  StackQueue,
  StackSize,
  StackSummary,
  StatsSince,
} from "./types";

const SECOND = 1_000;
const MINUTE = 60 * SECOND;

// --- query keys -----------------------------------------------------------------------------

const lower = (value: string) => value.trim().toLowerCase();

/** A match-history queue filter: one queue id, any of several, or null/empty for all. */
export type MatchQueueFilter = number | readonly number[] | null | undefined;

/** Sorted, de-duplicated queue ids of a filter (empty = all queues). */
export function matchQueueIds(queue: MatchQueueFilter): number[] {
  if (queue === null || queue === undefined) return [];
  const ids = typeof queue === "number" ? [queue] : queue;
  return [...new Set(ids)].sort((a, b) => a - b);
}

const queueKey = (queue: MatchQueueFilter) => {
  const ids = matchQueueIds(queue);
  return ids.length ? ids.join(",") : "all";
};

/**
 * Query key factory. Everything about one player lives under `["summoner", puuid, ...]`
 * so a single invalidation refreshes matches, ranks and AI data together.
 */
export const queryKeys = {
  health: () => ["health"] as const,
  meta: () => ["meta"] as const,
  search: (q: string) => ["search", lower(q)] as const,
  profile: (gameName: string, tagLine: string) => ["profile", lower(gameName), lower(tagLine)] as const,
  summoner: (puuid: string) => ["summoner", puuid] as const,
  matches: (puuid: string, queue?: MatchQueueFilter) => ["summoner", puuid, "matches", queueKey(queue)] as const,
  ranks: (puuid: string, queue: QueueType) => ["summoner", puuid, "ranks", queue] as const,
  aiTrend: (puuid: string) => ["summoner", puuid, "ai-trend"] as const,
  aiExplain: (puuid: string) => ["summoner", puuid, "ai-explain"] as const,
  match: (matchId: string) => ["match", matchId] as const,
  leaderboard: (queue: LeaderboardQueue) => ["leaderboard", queue] as const,
  leaderboardAll: () => ["leaderboard"] as const,
  roster: () => ["roster"] as const,
  // Personal insights live under the player's key, so `invalidatePlayer` refreshes them too.
  sessionInsights: (puuid: string, since: StatsSince, queue: LeaderboardQueue, gapMinutes: number) =>
    ["summoner", puuid, "insights", "sessions", since, queue, gapMinutes] as const,
  scheduleInsights: (puuid: string, since: StatsSince, queue: LeaderboardQueue, tz: string) =>
    ["summoner", puuid, "insights", "schedule", since, queue, tz] as const,
  matchupInsights: (puuid: string, since: StatsSince, queue: LeaderboardQueue, minGames: number) =>
    ["summoner", puuid, "insights", "matchups", since, queue, minGames] as const,
  luckInsights: (puuid: string, since: StatsSince, queue: LeaderboardQueue, limit: number) =>
    ["summoner", puuid, "insights", "luck", since, queue, limit] as const,
  squadPairs: (since: StatsSince, queue: LeaderboardQueue) => ["squad", "pairs", since, queue] as const,
  squadAll: () => ["squad"] as const,
  stacks: (since: StatsSince, queue: StackQueue, size: StackSize) => ["squad", "stacks", since, queue, size] as const,
  stackGames: (since: StatsSince, queue: StackQueue, size: StackSize) =>
    ["squad", "stacks", "games", since, queue, size] as const,
  records: (since: StatsSince, queue: LeaderboardQueue, puuid: string | null, limit: number) =>
    ["records", since, queue, puuid ?? "roster", limit] as const,
  recordsAll: () => ["records"] as const,
};

/** Period and queue filters shared by the squad, insights and records endpoints. */
export interface StatsFilters {
  /** Default "season". */
  since?: StatsSince;
  /** Default "all" (Solo/Duo and Flex). */
  queue?: LeaderboardQueue;
}

/** Fallback when the browser does not expose its IANA zone (the group plays on US Central). */
export const DEFAULT_TIME_ZONE = "America/Chicago";

/** The browser's IANA time zone (e.g. "America/New_York"), for the schedule heatmap. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_TIME_ZONE;
  } catch {
    return DEFAULT_TIME_ZONE;
  }
}

// --- meta / health --------------------------------------------------------------------------

/** Service health: DB, model, Riot key and poller. Polled every minute for the nav status pill. */
export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: ({ signal }) => request(api.GET("/api/v1/health", { signal })),
    staleTime: 30 * SECOND,
    refetchInterval: MINUTE,
  });
}

/** Data Dragon version, region, season start, model version and queue labels. */
export function useMeta() {
  return useQuery({
    queryKey: queryKeys.meta(),
    queryFn: ({ signal }) => request(api.GET("/api/v1/meta", { signal })),
    staleTime: 60 * MINUTE,
    gcTime: 24 * 60 * MINUTE,
  });
}

// --- search ---------------------------------------------------------------------------------

/** Prefix search over known summoners. Disabled until the trimmed query has 2+ characters. */
export function useSearch(q: string, limit = 8) {
  const query = q.trim();
  return useQuery({
    queryKey: [...queryKeys.search(query), limit] as const,
    queryFn: ({ signal }) => request(api.GET("/api/v1/search", { params: { query: { q: query, limit } }, signal })),
    enabled: query.length >= 2,
    staleTime: 30 * SECOND,
    placeholderData: keepPreviousData,
  });
}

// --- summoner -------------------------------------------------------------------------------

/** Profile by Riot ID. Unknown players are resolved through Riot on first view (may be slow). */
export function useSummonerProfile(gameName: string, tagLine: string) {
  return useQuery({
    queryKey: queryKeys.profile(gameName, tagLine),
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/summoners/by-riot-id/{game_name}/{tag_line}", {
          params: { path: { game_name: gameName, tag_line: tagLine } },
          signal,
        }),
      ),
    enabled: gameName.length > 0 && tagLine.length > 0,
    staleTime: MINUTE,
  });
}

function toastRefreshOutcome(result: RefreshResult): void {
  const name = `${result.profile.game_name}#${result.profile.tag_line}`;
  const games = (n: number) => `${n} new game${n === 1 ? "" : "s"}`;
  switch (result.status) {
    case "ok":
      toast.success(`${name} updated`, {
        description: result.new_matches > 0 ? `${games(result.new_matches)} added.` : "Already up to date.",
      });
      break;
    case "partial":
      toast.info(`${name} partially updated`, {
        description: `${games(result.new_matches)} added, ${result.pending} still queued. ${result.message}`.trim(),
      });
      break;
    case "cooldown":
      toast.info("Recently updated", { description: result.message });
      break;
    case "unavailable":
      toast.warning("Live updates unavailable", { description: result.message });
      break;
  }
}

function toastRefreshError(error: unknown): void {
  if (isApiError(error)) {
    if (error.code === "riot_key") {
      toast.error("Riot API key not configured", {
        description: "Live updates are unavailable. Stored data is still shown.",
      });
      return;
    }
    if (error.code === "riot_rate_limited") {
      toast.warning("Riot rate limit reached", {
        description: error.retryAfter ? `Try again in ${error.retryAfter}s.` : error.detail,
      });
      return;
    }
  }
  toast.error("Update failed", { description: errorMessage(error) });
}

/** Invalidate every cached query that belongs to one player (plus the leaderboard). */
export async function invalidatePlayer(client: QueryClient, puuid: string): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.summoner(puuid) }),
    client.invalidateQueries({ queryKey: queryKeys.leaderboardAll() }),
    client.invalidateQueries({ queryKey: queryKeys.squadAll() }),
    client.invalidateQueries({ queryKey: queryKeys.recordsAll() }),
  ]);
}

/**
 * The op.gg "Update" button. Stores the fresh profile, invalidates the player's matches,
 * ranks and AI queries, and toasts the ok / partial / cooldown / unavailable / riot_key outcome.
 */
export function useRefreshSummoner() {
  const client = useQueryClient();
  return useMutation<RefreshResult, ApiError | Error, RiotIdParts>({
    mutationKey: ["refresh"],
    mutationFn: ({ gameName, tagLine }) =>
      request(
        api.POST("/api/v1/summoners/by-riot-id/{game_name}/{tag_line}/refresh", {
          params: { path: { game_name: gameName, tag_line: tagLine } },
        }),
      ),
    onSuccess: async (result, { gameName, tagLine }) => {
      client.setQueryData(queryKeys.profile(gameName, tagLine), result.profile);
      client.setQueryData(queryKeys.profile(result.profile.game_name, result.profile.tag_line), result.profile);
      toastRefreshOutcome(result);
      const changed = result.status === "ok" || result.status === "partial";
      if (changed || result.new_matches > 0) {
        await invalidatePlayer(client, result.profile.puuid);
      }
    },
    onError: toastRefreshError,
  });
}

/** Match history, newest first, paginated on `next_cursor`. `queue` filters by queue id. */
export function useMatchHistory(puuid: string | undefined, queue?: MatchQueueFilter, pageSize = 20) {
  const queues = matchQueueIds(queue);
  return useInfiniteQuery({
    queryKey: [...queryKeys.matches(puuid ?? "", queue), pageSize] as const,
    queryFn: ({ pageParam, signal }): Promise<MatchPage> =>
      request(
        api.GET("/api/v1/summoners/{puuid}/matches", {
          params: {
            path: { puuid: puuid ?? "" },
            query: { limit: pageSize, cursor: pageParam ?? undefined, queue: queues.length ? queues : undefined },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(puuid),
    staleTime: MINUTE,
  });
}

/** Rank snapshots for one queue, oldest first (LP chart). */
export function useRankHistory(puuid: string | undefined, queue: QueueType = "RANKED_SOLO_5x5") {
  return useQuery({
    queryKey: queryKeys.ranks(puuid ?? "", queue),
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/summoners/{puuid}/ranks", {
          params: { path: { puuid: puuid ?? "" }, query: { queue } },
          signal,
        }),
      ),
    enabled: Boolean(puuid),
    staleTime: 5 * MINUTE,
  });
}

/** Stored AI scores over recent games, oldest first. Works without a loaded model. */
export function useAiTrend(puuid: string | undefined, limit = 40) {
  return useQuery({
    queryKey: [...queryKeys.aiTrend(puuid ?? ""), limit] as const,
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/summoners/{puuid}/ai-trend", {
          params: { path: { puuid: puuid ?? "" }, query: { limit } },
          signal,
        }),
      ),
    enabled: Boolean(puuid),
    staleTime: 5 * MINUTE,
  });
}

/**
 * Feature attributions behind a player's AI Score.
 *
 * Resolves to `null` when no model is trained (503 `model_missing`): that is a normal
 * "not trained yet" state, not an error. Render an EmptyState for it.
 */
export function useAiExplain(puuid: string | undefined, limit = 30) {
  return useQuery({
    queryKey: [...queryKeys.aiExplain(puuid ?? ""), limit] as const,
    queryFn: async ({ signal }): Promise<AiExplain | null> => {
      try {
        return await request(
          api.GET("/api/v1/summoners/{puuid}/ai-explain", {
            params: { path: { puuid: puuid ?? "" }, query: { limit } },
            signal,
          }),
        );
      } catch (error) {
        if (isApiError(error) && error.isModelMissing) return null;
        throw error;
      }
    },
    enabled: Boolean(puuid),
    staleTime: 5 * MINUTE,
  });
}

// --- matches --------------------------------------------------------------------------------

/** Full match detail (both teams, objectives, bans). Matches never change, so cache long. */
export function useMatch(matchId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.match(matchId ?? ""),
    queryFn: ({ signal }) =>
      request(api.GET("/api/v1/matches/{match_id}", { params: { path: { match_id: matchId ?? "" } }, signal })),
    enabled: Boolean(matchId),
    staleTime: 60 * MINUTE,
  });
}

// --- leaderboard / roster -------------------------------------------------------------------

/** Season leaderboard of the tracked roster. */
export function useLeaderboard(queue: LeaderboardQueue = "all") {
  return useQuery({
    queryKey: queryKeys.leaderboard(queue),
    queryFn: ({ signal }) => request(api.GET("/api/v1/leaderboard", { params: { query: { queue } }, signal })),
    staleTime: 2 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

/** Tracked players. */
export function useRoster() {
  return useQuery({
    queryKey: queryKeys.roster(),
    queryFn: ({ signal }) => request(api.GET("/api/v1/roster", { signal })),
    staleTime: 5 * MINUTE,
  });
}

// --- squad (friend group) -------------------------------------------------------------------

/** Duo synergy and who-carries-whom for every pair of tracked players. */
/** Query options for squad pairs, shared by the hook and imperative `fetchQuery` callers. */
export function squadPairsQuery(since: StatsSince = "season", queue: LeaderboardQueue = "all") {
  return queryOptions({
    queryKey: queryKeys.squadPairs(since, queue),
    queryFn: ({ signal }) =>
      request(api.GET("/api/v1/squad/pairs", { params: { query: { since, queue } }, signal })),
    staleTime: 5 * MINUTE,
  });
}

export function useSquadPairs(since: StatsSince = "season", queue: LeaderboardQueue = "all") {
  return useQuery({ ...squadPairsQuery(since, queue), placeholderData: keepPreviousData });
}

// --- stacks (games the squad played together) ------------------------------------------------

export interface StackFilters {
  since?: StatsSince;
  queue?: StackQueue;
  size?: StackSize;
}

/** Record, awards, lineups, players and highlights for the Stacks page. */
export function useStackSummary({ since = "season", queue = "all", size = 5 }: StackFilters = {}) {
  return useQuery({
    queryKey: queryKeys.stacks(since, queue, size),
    queryFn: ({ signal }): Promise<StackSummary> =>
      request(api.GET("/api/v1/squad/stacks", { params: { query: { since, queue, size } }, signal })),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

/** Stacked games, newest first, cursor paginated (both teams of a match share a page). */
export function useStackGames({ since = "season", queue = "all", size = 5 }: StackFilters = {}, pageSize = 20) {
  return useInfiniteQuery({
    queryKey: [...queryKeys.stackGames(since, queue, size), pageSize] as const,
    queryFn: ({ pageParam, signal }): Promise<StackGamePage> =>
      request(
        api.GET("/api/v1/squad/stacks/games", {
          params: { query: { since, queue, size, limit: pageSize, cursor: pageParam ?? undefined } },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    staleTime: MINUTE,
  });
}

// --- personal insights (Trends tab) ---------------------------------------------------------

export interface SessionInsightsOptions extends StatsFilters {
  /** Break (minutes, 10..180) that still counts as the same session. Default 45. */
  gapMinutes?: number;
}

/** Tilt detector: win rate and AI Score by game number within a play session. */
export function useSessionInsights(puuid: string | undefined, opts: SessionInsightsOptions = {}) {
  const { since = "season", queue = "all", gapMinutes = 45 } = opts;
  return useQuery({
    queryKey: queryKeys.sessionInsights(puuid ?? "", since, queue, gapMinutes),
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/summoners/{puuid}/insights/sessions", {
          params: { path: { puuid: puuid ?? "" }, query: { since, queue, gap_minutes: gapMinutes } },
          signal,
        }),
      ),
    enabled: Boolean(puuid),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

export interface ScheduleInsightsOptions extends StatsFilters {
  /** IANA zone; defaults to the browser's (`browserTimeZone()`). */
  tz?: string;
}

/** Best time to play: win rate by local day of week and hour. */
export function useScheduleInsights(puuid: string | undefined, opts: ScheduleInsightsOptions = {}) {
  const { since = "season", queue = "all", tz = browserTimeZone() } = opts;
  return useQuery({
    queryKey: queryKeys.scheduleInsights(puuid ?? "", since, queue, tz),
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/summoners/{puuid}/insights/schedule", {
          params: { path: { puuid: puuid ?? "" }, query: { since, queue, tz } },
          signal,
        }),
      ),
    enabled: Boolean(puuid),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

export interface MatchupInsightsOptions extends StatsFilters {
  /** Fewest games against a champion to list it (1..20). Default 3. */
  minGames?: number;
}

/** Nemesis champions: record against each enemy champion in the player's lane. */
export function useMatchupInsights(puuid: string | undefined, opts: MatchupInsightsOptions = {}) {
  const { since = "season", queue = "all", minGames = 3 } = opts;
  return useQuery({
    queryKey: queryKeys.matchupInsights(puuid ?? "", since, queue, minGames),
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/summoners/{puuid}/insights/matchups", {
          params: { path: { puuid: puuid ?? "" }, query: { since, queue, min_games: minGames } },
          signal,
        }),
      ),
    enabled: Boolean(puuid),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

export interface LuckInsightsOptions extends StatsFilters {
  /** Games per list (1..20). Default 5. */
  limit?: number;
}

/** Unlucky losses (scored high, lost) and lucky wins (scored low, won). */
export function useLuckInsights(puuid: string | undefined, opts: LuckInsightsOptions = {}) {
  const { since = "season", queue = "all", limit = 5 } = opts;
  return useQuery({
    queryKey: queryKeys.luckInsights(puuid ?? "", since, queue, limit),
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/summoners/{puuid}/insights/luck", {
          params: { path: { puuid: puuid ?? "" }, query: { since, queue, limit } },
          signal,
        }),
      ),
    enabled: Boolean(puuid),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}

// --- records --------------------------------------------------------------------------------

export interface RecordsOptions extends StatsFilters {
  /** Only this player's games (scope "player"); omit / null for the whole roster. */
  puuid?: string | null;
  /** Entries per category (1..10). Default 3. */
  limit?: number;
}

/** Single-game records (roster or one player) and the pentakill hall of fame. */
export function useRecords(opts: RecordsOptions = {}) {
  const { since = "season", queue = "all", puuid = null, limit = 3 } = opts;
  return useQuery({
    queryKey: queryKeys.records(since, queue, puuid, limit),
    queryFn: ({ signal }) =>
      request(
        api.GET("/api/v1/records", {
          params: { query: { since, queue, limit, puuid: puuid ?? undefined } },
          signal,
        }),
      ),
    staleTime: 5 * MINUTE,
    placeholderData: keepPreviousData,
  });
}
