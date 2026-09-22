import { useCallback, useMemo } from "react";
import { getRouteApi } from "@tanstack/react-router";
import { CalendarDays, Sparkles, Trophy, Users } from "lucide-react";

import { useLeaderboard } from "@/api/queries";
import type { Leaderboard, LeaderboardQueue } from "@/api/types";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Reveal } from "@/components/common/Motion";
import { SectionHeader } from "@/components/common/SectionHeader";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import { LeaderboardCards, LeaderboardSortMenu } from "@/components/leaderboard/LeaderboardCards";
import { LeaderboardCardsSkeleton, LeaderboardTableSkeleton } from "@/components/leaderboard/LeaderboardSkeleton";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { QueueToggle } from "@/components/leaderboard/QueueToggle";
import { RosterEmptyState } from "@/components/leaderboard/RosterEmptyState";
import {
  computeStandings,
  DEFAULT_SORT,
  defaultDirection,
  nextSort,
  sortEntries,
  type SortState,
} from "@/components/leaderboard/sorting";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatDate, plural } from "@/lib/format";
import { AI_AVERAGE_NOTE, modelVersionDate } from "@/lib/score";

const QUEUE_CAPTION: Readonly<Record<LeaderboardQueue, string>> = {
  all: "Ranked Solo/Duo and Flex",
  solo: "Ranked Solo/Duo",
  flex: "Ranked Flex",
};

function SeasonCaption({
  data,
  queue,
  failed,
}: {
  data: Leaderboard | undefined;
  queue: LeaderboardQueue;
  failed: boolean;
}) {
  if (!data && failed) return null;
  if (!data) {
    return (
      <div className="flex h-5 items-center gap-3" aria-hidden="true">
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="h-3.5 w-32" />
      </div>
    );
  }
  return (
    <p className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
      <span className="inline-flex items-center gap-1.5">
        <CalendarDays className="size-4 text-text-muted" aria-hidden="true" />
        Season since <span className="font-medium text-text">{formatDate(data.season_start)}</span>
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Users className="size-4 text-text-muted" aria-hidden="true" />
        {plural(data.entries.length, "tracked player")} · {QUEUE_CAPTION[queue]}
      </span>
      <span className="inline-flex items-center gap-1.5" title={data.model_version ?? undefined}>
        <Sparkles className="size-4 text-cyan" aria-hidden="true" />
        {data.model_version ? (
          <>
            AI model <span className="font-medium text-text">{modelLabel(data.model_version)}</span>
          </>
        ) : (
          "AI model not trained yet"
        )}
      </span>
    </p>
  );
}

/** Model versions are timestamps ("20260922-170745"); a player only needs the date. */
function modelLabel(version: string): string {
  const trained = modelVersionDate(version);
  return trained ? `trained ${formatDate(trained)}` : version;
}

const route = getRouteApi("/leaderboard");

export function LeaderboardPage() {
  useDocumentTitle(pageTitle("Leaderboard"));
  // Queue and sort live in the URL (?queue=flex&sort=winrate&dir=asc) so views can be shared.
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const queue: LeaderboardQueue = search.queue ?? "all";
  const sort: SortState = useMemo(
    () => ({
      key: search.sort ?? DEFAULT_SORT.key,
      direction: search.dir ?? (search.sort ? defaultDirection(search.sort) : DEFAULT_SORT.direction),
    }),
    [search.sort, search.dir],
  );
  const setQueue = useCallback(
    (next: LeaderboardQueue) =>
      void navigate({ search: (prev) => ({ ...prev, queue: next === "all" ? undefined : next }), replace: true }),
    [navigate],
  );
  const setSort = useCallback(
    (next: SortState) =>
      void navigate({
        search: (prev) => ({
          ...prev,
          sort: next.key === DEFAULT_SORT.key ? undefined : next.key,
          dir: next.direction === (next.key === DEFAULT_SORT.key ? DEFAULT_SORT.direction : defaultDirection(next.key))
            ? undefined
            : next.direction,
        }),
        replace: true,
      }),
    [navigate],
  );
  const query = useLeaderboard(queue);
  const { data } = query;

  const entries = useMemo(() => data?.entries ?? [], [data]);
  const standings = useMemo(() => computeStandings(entries), [entries]);
  const sorted = useMemo(() => sortEntries(entries, sort, queue, standings), [entries, sort, queue, standings]);
  const refetching = query.isPlaceholderData;

  let body;
  if (query.isPending) {
    body = (
      <>
        <div className="hidden md:block">
          <LeaderboardTableSkeleton />
        </div>
        <div className="md:hidden">
          <LeaderboardCardsSkeleton />
        </div>
      </>
    );
  } else if (query.isError && !data) {
    body = (
      <GlowCard>
        <ErrorState error={query.error} title="Couldn't load the leaderboard" onRetry={() => void query.refetch()} />
      </GlowCard>
    );
  } else if (entries.length === 0) {
    body = <RosterEmptyState />;
  } else {
    body = (
      <div
        className={cn("transition-opacity duration-200", refetching && "pointer-events-none opacity-60")}
        aria-busy={refetching || undefined}
      >
        <Reveal className="hidden md:block">
          <GlowCard className="overflow-clip">
            <LeaderboardTable
              entries={sorted}
              standings={standings}
              queue={queue}
              sort={sort}
              onSort={(key) => setSort(nextSort(sort, key))}
            />
          </GlowCard>
        </Reveal>
        <div className="flex flex-col gap-3 md:hidden">
          <LeaderboardSortMenu sort={sort} onChange={setSort} />
          <LeaderboardCards entries={sorted} standings={standings} queue={queue} />
        </div>
        <p className="mt-4 text-xs leading-relaxed text-text-muted">
          # is the overall standing by average AI Score, for players with at least{" "}
          {plural(standings.minGames, "ranked game")} this season; smaller samples count as closer to 50. The AI Score
          is the model's estimate of how often a stat line like this one wins. {AI_AVERAGE_NOTE} Season LP counts
          Ranked Solo/Duo since the season started. Best duo only counts tracked teammates.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Reveal>
        <div className="flex flex-col gap-3">
          <SectionHeader
            as="h1"
            size="lg"
            eyebrow="The Squad"
            icon={Trophy}
            title="Leaderboard"
            description="The tracked roster's season, ranked by average AI Score."
            action={<QueueToggle value={queue} onChange={setQueue} />}
          />
          <SeasonCaption data={data} queue={queue} failed={query.isError} />
        </div>
      </Reveal>
      {body}
    </div>
  );
}
