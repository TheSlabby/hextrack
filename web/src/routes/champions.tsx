/**
 * /champions: every champion's win / pick / ban rate in a patch window, filterable by role
 * and sortable. Filters and sort live in the URL (defaults omitted); the text search is local.
 */
import { useCallback, useMemo, useState } from "react";
import { getRouteApi } from "@tanstack/react-router";
import { Gamepad2, Hourglass, Layers, Search, SearchX, Swords, X } from "lucide-react";

import { useChampionList, useChampionPatches } from "@/api/queries";
import type { ChampionList, ChampionPatchParam, ChampionRole, LeaderboardQueue } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Reveal } from "@/components/common/Motion";
import { SectionHeader } from "@/components/common/SectionHeader";
import { ChampionListCards, ChampionListSortMenu } from "@/components/champions/ChampionListCards";
import {
  buildChampionItems,
  defaultChampionDirection,
  defaultChampionSortKey,
  filterChampionItems,
  nextChampionSort,
  SMALL_SAMPLE_GAMES,
  type ChampionListSortState,
} from "@/components/champions/ChampionListModel";
import { ChampionListCardsSkeleton, ChampionListTableSkeleton } from "@/components/champions/ChampionListSkeleton";
import { ChampionListTable } from "@/components/champions/ChampionListTable";
import { ChampionRoleFilter } from "@/components/champions/ChampionRoleFilter";
import { PatchSelect } from "@/components/champions/PatchSelect";
import { QueueToggle } from "@/components/leaderboard/QueueToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { patchWindowLabel } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatInteger, plural } from "@/lib/format";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import type { ChampionsSearch } from "@/router";

const QUEUE_CAPTION: Readonly<Record<LeaderboardQueue, string>> = {
  all: "Ranked Solo/Duo and Flex",
  solo: "Ranked Solo/Duo",
  flex: "Ranked Flex",
};

/** "No champions played in the jungle". */
const ROLE_PHRASE: Readonly<Record<ChampionRole, string>> = {
  TOP: "in top lane",
  JUNGLE: "in the jungle",
  MIDDLE: "in mid lane",
  BOTTOM: "in bot lane",
  UTILITY: "as support",
};

const route = getRouteApi("/champions");

function WindowCaption({
  data,
  queue,
  pending,
  failed,
}: {
  data: ChampionList | undefined;
  queue: LeaderboardQueue;
  pending: number;
  failed: boolean;
}) {
  if (!data && failed) return null;
  if (!data) {
    return (
      <div className="flex h-5 items-center gap-3" aria-hidden="true">
        <Skeleton className="h-3.5 w-32" />
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="h-3.5 w-28" />
      </div>
    );
  }
  return (
    <p className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
      <span className="inline-flex items-center gap-1.5">
        <Gamepad2 className="size-4 text-text-muted" aria-hidden="true" />
        <span className="font-medium text-text tabular-nums">{formatInteger(data.total_matches)}</span>
        {data.total_matches === 1 ? "game" : "games"} · {QUEUE_CAPTION[queue]}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Layers className="size-4 text-text-muted" aria-hidden="true" />
        {patchWindowLabel(data.patch, data.patches)} · {plural(data.rows.length, "champion")}
      </span>
      {pending > 0 ? (
        <span className="inline-flex items-center gap-1.5">
          <Hourglass className="size-4 text-text-muted" aria-hidden="true" />
          {plural(pending, "stored game")} still being counted
        </span>
      ) : null}
    </p>
  );
}

function ChampionSearchBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-muted"
        aria-hidden="true"
      />
      <Input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && value) {
            event.stopPropagation();
            onChange("");
          }
        }}
        placeholder="Search champions"
        aria-label="Search champions"
        autoComplete="off"
        spellCheck={false}
        maxLength={40}
        className="h-9 pr-9 pl-9 [&::-webkit-search-cancel-button]:hidden"
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute top-1/2 right-1.5 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-white/5 hover:text-text focus-visible:outline-2 focus-visible:outline-gold"
          aria-label="Clear search"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}

export function ChampionsPage() {
  useDocumentTitle(pageTitle("Champions"));
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const patch: ChampionPatchParam = search.patch ?? "recent";
  const queue: LeaderboardQueue = search.queue ?? "all";
  const role: ChampionRole | null = search.role ?? null;
  const sort: ChampionListSortState = useMemo(() => {
    const key = search.sort ?? defaultChampionSortKey(search.role);
    return { key, direction: search.dir ?? defaultChampionDirection(key) };
  }, [search.sort, search.dir, search.role]);
  const [text, setText] = useState("");

  const setFilters = useCallback(
    (next: { patch?: ChampionPatchParam; queue?: LeaderboardQueue; role?: ChampionRole | null }) =>
      void navigate({
        search: (prev) => {
          const result = { ...prev };
          if (next.patch !== undefined) result.patch = next.patch === "recent" ? undefined : next.patch;
          if (next.queue !== undefined) result.queue = next.queue === "all" ? undefined : next.queue;
          if (next.role !== undefined) {
            const before = prev.sort ?? defaultChampionSortKey(prev.role);
            result.role = next.role ?? undefined;
            // A sort that is the new role's default drops out of the URL; a direction only
            // survives while it still applies to the same column.
            if (result.sort === defaultChampionSortKey(result.role)) result.sort = undefined;
            if ((result.sort ?? defaultChampionSortKey(result.role)) !== before) result.dir = undefined;
          }
          return result;
        },
        replace: true,
      }),
    [navigate],
  );
  const setSort = useCallback(
    (next: ChampionListSortState) =>
      void navigate({
        search: (prev) => ({
          ...prev,
          sort: next.key === defaultChampionSortKey(prev.role) ? undefined : next.key,
          dir: next.direction === defaultChampionDirection(next.key) ? undefined : next.direction,
        }),
        replace: true,
      }),
    [navigate],
  );

  const query = useChampionList({ patch, queue });
  const patches = useChampionPatches();
  const { data } = query;
  const pending = patches.data?.pending_matches ?? 0;

  const items = useMemo(
    () => (data ? buildChampionItems(data.rows, role, data.total_matches, sort) : []),
    [data, role, sort],
  );
  const shown = useMemo(() => filterChampionItems(items, text), [items, text]);
  // The champion page opens on the same window, queue and role.
  const linkSearch: ChampionsSearch = useMemo(
    () => ({ patch: search.patch, queue: search.queue, role: search.role }),
    [search.patch, search.queue, search.role],
  );
  const refetching = query.isPlaceholderData;

  let body;
  if (query.isPending) {
    body = (
      <>
        <div className="hidden md:block">
          <ChampionListTableSkeleton />
        </div>
        <div className="md:hidden">
          <ChampionListCardsSkeleton />
        </div>
      </>
    );
  } else if (query.isError && !data) {
    body = (
      <GlowCard>
        <ErrorState error={query.error} title="Couldn't load champions" onRetry={() => void query.refetch()} />
      </GlowCard>
    );
  } else if (!data || data.rows.length === 0) {
    body = (
      <GlowCard>
        {pending > 0 ? (
          <EmptyState
            icon={Hourglass}
            title="No champion data yet"
            description={`The worker is still counting stored games (${formatInteger(pending)} to go). Champion stats fill in as it works through them, so check back in a few minutes.`}
          />
        ) : (
          <EmptyState
            icon={Swords}
            title="No champion games in this window"
            description="No ranked games are counted for these patches and queue yet."
            action={
              patch !== "season" || queue !== "all" ? (
                <Button variant="outline" size="sm" onClick={() => setFilters({ patch: "season", queue: "all" })}>
                  Show the whole season
                </Button>
              ) : null
            }
          />
        )}
      </GlowCard>
    );
  } else if (shown.length === 0) {
    body = (
      <GlowCard>
        {items.length === 0 && role ? (
          <EmptyState
            icon={Swords}
            title={`No champions played ${ROLE_PHRASE[role]}`}
            description="Nobody has played this role in the window yet."
            action={
              <Button variant="outline" size="sm" onClick={() => setFilters({ role: null })}>
                Show every role
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={SearchX}
            title={`No champions match “${text.trim()}”`}
            description={
              role
                ? `Only champions played ${ROLE_PHRASE[role]} are listed. Check the spelling or try every role.`
                : "Check the spelling, or search by part of the name."
            }
            action={
              <>
                <Button variant="outline" size="sm" onClick={() => setText("")}>
                  Clear search
                </Button>
                {role ? (
                  <Button variant="ghost" size="sm" onClick={() => setFilters({ role: null })}>
                    Every role
                  </Button>
                ) : null}
              </>
            }
          />
        )}
      </GlowCard>
    );
  } else {
    body = (
      <div
        className={cn("transition-opacity duration-200", refetching && "pointer-events-none opacity-60")}
        aria-busy={refetching || undefined}
      >
        <Reveal className="hidden md:block">
          <GlowCard className="overflow-clip">
            <ChampionListTable
              items={shown}
              role={role}
              sort={sort}
              onSort={(key) => setSort(nextChampionSort(sort, key))}
              linkSearch={linkSearch}
            />
          </GlowCard>
        </Reveal>
        <Reveal className="flex flex-col gap-3 md:hidden">
          <ChampionListSortMenu sort={sort} onChange={setSort} />
          <ChampionListCards items={shown} role={role} linkSearch={linkSearch} />
        </Reveal>
        <p className="mt-4 text-xs leading-relaxed text-text-muted">
          Pick rate is the share of games with the champion in them; ban rate is the share where it was banned.
          {role
            ? " With a role selected, games, win rate and pick rate count that role only; ban rate and KDA cover every role."
            : ""}{" "}
          Rows under {SMALL_SAMPLE_GAMES} games are dimmed: their rates can swing a lot. Win rates are coloured against
          50%. Tiers (S to D) compare champions in the same role from win rate (adjusted for sample size), pick rate and
          ban rate
          {role ? "" : "; with every role shown, the tier is for the champion's most played role"}. A dash means too few
          games to rank.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Reveal>
        <div className="flex flex-col gap-4">
          <SectionHeader
            as="h1"
            size="lg"
            eyebrow="Every ranked game"
            icon={Swords}
            title="Champions"
            description="Ranked Solo/Duo and Flex games tracked by HexTrack, including games from outside the squad."
            action={
              <>
                <PatchSelect value={patch} onChange={(next) => setFilters({ patch: next })} />
                <QueueToggle value={queue} onChange={(next) => setFilters({ queue: next })} />
              </>
            }
          />
          <WindowCaption data={data} queue={queue} pending={pending} failed={query.isError} />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <ChampionRoleFilter value={role} onChange={(next) => setFilters({ role: next })} />
            <ChampionSearchBox value={text} onChange={setText} />
          </div>
        </div>
      </Reveal>
      {body}
    </div>
  );
}
