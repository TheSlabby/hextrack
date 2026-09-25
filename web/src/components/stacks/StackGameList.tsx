import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { motion } from "motion/react";
import { ChevronsDown, LoaderCircle, Users } from "lucide-react";

import { useStackGames } from "@/api/queries";
import type { StackGame, StackQueue, StackSize, StatsSince } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { dayKey, dayLabel } from "@/components/match/matchUtils";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { EASE_OUT, MOTION, staggerStep, useEntranceMotion } from "@/lib/motion";

import { STACK_QUEUE_LABEL, stackLabelPlural } from "./model";
import { StackGameRow, StackGameRowSkeleton } from "./StackGameRow";

const SKELETON_ROWS = 4;

/** One stack per team per match: two opposing roster stacks in one game are two rows. */
function stackKey(game: StackGame): string {
  return `${game.match_id}-${game.team_id}`;
}

interface StackDay {
  key: string;
  label: string;
  games: StackGame[];
  wins: number;
  losses: number;
}

/** Group newest-first stack games into consecutive local days (remakes never reach this list). */
function groupStackGames(games: readonly StackGame[], now: Date = new Date()): StackDay[] {
  const groups: StackDay[] = [];
  for (const game of games) {
    const date = new Date(game.game_start);
    const key = dayKey(date);
    let group = groups[groups.length - 1];
    if (!group || group.key !== key) {
      group = { key, label: dayLabel(date, now), games: [], wins: 0, losses: 0 };
      groups.push(group);
    }
    group.games.push(game);
    if (game.win) group.wins += 1;
    else group.losses += 1;
  }
  return groups;
}

export interface StackGameListProps {
  since: StatsSince;
  queue: StackQueue;
  size: StackSize;
  className?: string;
}

/**
 * Every game the roster played as a stack, newest first and grouped by day, with "Load more"
 * and automatic loading as the end scrolls into view.
 */
export function StackGameList({ since, queue, size, className }: StackGameListProps) {
  const query = useStackGames({ since, queue, size });
  const { data, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = query;
  const entrance = useEntranceMotion();

  const { games, pagePosition } = useMemo(() => {
    const seen = new Set<string>();
    const flat: StackGame[] = [];
    const position = new Map<string, number>();
    for (const page of data?.pages ?? []) {
      page.items.forEach((game, index) => {
        const key = stackKey(game);
        if (seen.has(key)) return;
        seen.add(key);
        flat.push(game);
        position.set(key, index);
      });
    }
    return { games: flat, pagePosition: position };
  }, [data]);

  const groups = useMemo(() => groupStackGames(games), [games]);

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

  const backgroundRefetch = query.isFetching && !query.isPending && !isFetchingNextPage;

  let body: ReactNode;
  if (query.isPending) {
    body = (
      <div className="flex flex-col gap-2" role="status" aria-label="Loading stack games">
        {Array.from({ length: SKELETON_ROWS }, (_, i) => (
          <StackGameRowSkeleton key={i} />
        ))}
      </div>
    );
  } else if (!data) {
    body = (
      <GlowCard>
        <ErrorState compact error={query.error} title="Couldn't load stack games" onRetry={() => void query.refetch()} />
      </GlowCard>
    );
  } else if (games.length === 0) {
    const scope = [queue === "flex" ? `in ${STACK_QUEUE_LABEL.flex}` : null, since === "season" ? "this season" : "yet"]
      .filter(Boolean)
      .join(" ");
    body = (
      <GlowCard>
        <EmptyState
          compact
          icon={Users}
          title={`No ${stackLabelPlural(size)} ${scope}`}
          description="Games show up here once enough of the roster queues up together."
        />
      </GlowCard>
    );
  } else {
    body = (
      <div className={cn("flex flex-col gap-3 transition-opacity duration-200", backgroundRefetch && "opacity-70")}>
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
                {group.games.map((game) => {
                  const key = stackKey(game);
                  return (
                    <motion.li
                      key={key}
                      initial={entrance ? { opacity: 0, y: 8 } : false}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: MOTION.duration,
                        ease: EASE_OUT,
                        delay: entrance ? Math.min(pagePosition.get(key) ?? 0, 12) * staggerStep(13) : 0,
                      }}
                      className="min-w-0"
                    >
                      <StackGameRow game={game} />
                    </motion.li>
                  );
                })}
              </ol>
            </section>
          ))}
        </div>

        <div ref={sentinelRef} className="flex flex-col items-center gap-2 pt-2">
          {isFetchingNextPage ? (
            <div className="flex w-full flex-col gap-2" role="status" aria-label="Loading more games">
              {Array.from({ length: 2 }, (_, i) => (
                <StackGameRowSkeleton key={i} />
              ))}
            </div>
          ) : null}
          {isFetchNextPageError ? (
            <GlowCard className="w-full">
              <ErrorState
                compact
                error={query.error}
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
            <p className="py-2 text-xs text-text-muted">That's all {plural(games.length, "game")}.</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <section className={cn("flex min-w-0 flex-col gap-3", className)} aria-label="Stack games">
      {body}
    </section>
  );
}
