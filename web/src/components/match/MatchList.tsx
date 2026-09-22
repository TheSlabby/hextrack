import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { ChevronsDown, History, ListFilter, LoaderCircle } from "lucide-react";

import { useMatchHistory } from "@/api/queries";
import type { MatchSummary } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { EASE_OUT, MOTION, staggerStep, useEntranceMotion } from "@/lib/motion";
import { plural } from "@/lib/format";

import { MatchHistorySummary, MatchHistorySummarySkeleton } from "./MatchHistorySummary";
import { MatchRow } from "./MatchRow";
import { MatchRowSkeleton } from "./MatchSkeletons";
import { QueueFilter } from "./QueueFilter";
import { groupByDay, historyQueueFilter, type HistoryQueueFilterId } from "./matchUtils";

const PAGE_SIZE = 20;
const SKELETON_ROWS = 6;


export interface MatchListProps {
  puuid: string;
  className?: string;
}

/**
 * Infinite match history for one player: queue filter chips, a summary of the loaded games,
 * rows grouped by day, and "Load more" with automatic loading as the end scrolls into view.
 */
export function MatchList({ puuid, className }: MatchListProps) {
  const [queue, setQueue] = useState<HistoryQueueFilterId>("all");
  const filter = historyQueueFilter(queue);
  const history = useMatchHistory(puuid, filter.queues, PAGE_SIZE);
  const { data, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = history;
  const entrance = useEntranceMotion();

  const { matches, pagePosition } = useMemo(() => {
    const seen = new Set<string>();
    const flat: MatchSummary[] = [];
    const position = new Map<string, number>();
    for (const page of data?.pages ?? []) {
      page.items.forEach((match, index) => {
        if (seen.has(match.match_id)) return;
        seen.add(match.match_id);
        flat.push(match);
        position.set(match.match_id, index);
      });
    }
    return { matches: flat, pagePosition: position };
  }, [data]);

  const groups = useMemo(() => groupByDay(matches), [matches]);

  // Auto-load the next page when the end of the list approaches.
  const sentinelRef = useRef<HTMLDivElement>(null);
  const canAutoLoad = Boolean(hasNextPage) && !isFetchingNextPage && !isFetchNextPageError;
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !canAutoLoad || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void fetchNextPage();
      },
      { rootMargin: "0px 0px 480px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [canAutoLoad, fetchNextPage]);

  const backgroundRefetch = history.isFetching && !history.isPending && !isFetchingNextPage;

  let body: ReactNode;
  if (history.isPending) {
    body = (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading match history">
        <MatchHistorySummarySkeleton />
        <div className="flex flex-col gap-2">
          {Array.from({ length: SKELETON_ROWS }, (_, i) => (
            <MatchRowSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  } else if (!data) {
    body = (
      <GlowCard>
        <ErrorState error={history.error} title="Couldn't load match history" onRetry={() => void history.refetch()} />
      </GlowCard>
    );
  } else if (matches.length === 0) {
    body = (
      <GlowCard>
        {filter.queues === null ? (
          <EmptyState
            icon={History}
            title="No games stored yet"
            description="Games show up here once this player has been updated. Use Update on the profile to pull their recent ranked games from Riot."
          />
        ) : (
          <EmptyState
            icon={ListFilter}
            title={`No ${filter.description} games`}
            description="None of this player's stored games are in this queue. HexTrack stores ranked games by default."
            action={
              <Button variant="outline" size="sm" onClick={() => setQueue("all")}>
                Show all queues
              </Button>
            }
          />
        )}
      </GlowCard>
    );
  } else {
    body = (
      <div className={cn("flex flex-col gap-3 transition-opacity duration-200", backgroundRefetch && "opacity-70")}>
        <MatchHistorySummary matches={matches} />
        <div className="flex flex-col gap-5">
          {groups.map((group) => (
            <section key={group.key} aria-label={`${group.label}: ${group.wins} wins, ${group.losses} losses`}>
              <div className="mb-2 flex items-center gap-3 px-1">
                <h3 className="text-[11px] leading-4 font-semibold tracking-[0.08em] text-text-secondary uppercase">
                  {group.label}
                </h3>
                <span className="text-[11px] font-semibold tabular-nums" aria-hidden="true">
                  <span className="text-win">{group.wins}W</span> <span className="text-loss">{group.losses}L</span>
                </span>
                <span aria-hidden="true" className="h-px flex-1 bg-border" />
              </div>
              <ol className="flex flex-col gap-2">
                {group.matches.map((match) => (
                  <motion.li
                    key={match.match_id}
                    initial={entrance ? { opacity: 0, y: 8 } : false}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: MOTION.duration,
                      ease: EASE_OUT,
                      delay: entrance ? Math.min(pagePosition.get(match.match_id) ?? 0, 12) * staggerStep(13) : 0,
                    }}
                    className="min-w-0"
                  >
                    <MatchRow match={match} puuid={puuid} />
                  </motion.li>
                ))}
              </ol>
            </section>
          ))}
        </div>

        <div ref={sentinelRef} className="flex flex-col items-center gap-2 pt-2">
          {isFetchingNextPage ? (
            <div className="flex w-full flex-col gap-2" role="status" aria-label="Loading more games">
              {Array.from({ length: 2 }, (_, i) => (
                <MatchRowSkeleton key={i} />
              ))}
            </div>
          ) : null}
          {isFetchNextPageError ? (
            <GlowCard className="w-full">
              <ErrorState
                compact
                error={history.error}
                title="Couldn't load more games"
                onRetry={() => void fetchNextPage()}
              />
            </GlowCard>
          ) : hasNextPage ? (
            <Button
              variant="outline"
              onClick={() => void fetchNextPage()}
              disabled={isFetchingNextPage}
              aria-busy={isFetchingNextPage}
            >
              {isFetchingNextPage ? (
                <LoaderCircle className="animate-spin" aria-hidden="true" />
              ) : (
                <ChevronsDown aria-hidden="true" />
              )}
              {isFetchingNextPage ? "Loading…" : "Load more"}
            </Button>
          ) : (
            <p className="py-2 text-xs text-text-muted">
              That's all {plural(matches.length, "stored game")}
              {filter.queues !== null ? ` in ${filter.description}` : ""}.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <section className={cn("@container flex min-w-0 flex-col gap-3", className)} aria-label="Match history">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <QueueFilter value={queue} onChange={setQueue} />
        <span className="flex items-center gap-1.5 text-xs text-text-muted" aria-live="polite">
          {backgroundRefetch || isFetchingNextPage ? (
            <LoaderCircle className="size-3.5 animate-spin text-gold" aria-hidden="true" />
          ) : null}
          {history.isSuccess && matches.length > 0 ? `${plural(matches.length, "game")} loaded` : null}
        </span>
      </div>
      {body}
    </section>
  );
}
