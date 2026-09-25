import { useMemo } from "react";
import { History } from "lucide-react";

import { useRecentGames } from "@/api/queries";
import type { StackGame } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { SectionHeader } from "@/components/common/SectionHeader";
import { StackGameRow, StackGameRowSkeleton } from "@/components/stacks/StackGameRow";
import { Button } from "@/components/ui/button";

/** Stop offering "Show more" after this many games; the profiles and Stacks page go further. */
const MAX_GAMES = 40;

/**
 * Home page feed: the roster's latest games. Each row is one team: a solo game shows one
 * player, friends who queued together share a row with the carry / "ran it down" line.
 */
export function RecentGames() {
  const query = useRecentGames();
  const { data, hasNextPage, isFetchingNextPage, fetchNextPage } = query;

  const games = useMemo(() => {
    const seen = new Set<string>();
    const flat: StackGame[] = [];
    for (const page of data?.pages ?? []) {
      for (const game of page.items) {
        const key = `${game.match_id}-${game.team_id}`;
        if (!seen.has(key)) {
          seen.add(key);
          flat.push(game);
        }
      }
    }
    return flat;
  }, [data]);

  let body;
  if (query.isPending) {
    body = (
      <div className="flex flex-col gap-2" role="status" aria-label="Loading recent games">
        {Array.from({ length: 4 }, (_, i) => (
          <StackGameRowSkeleton key={i} />
        ))}
      </div>
    );
  } else if (!data) {
    body = (
      <GlowCard>
        <ErrorState compact error={query.error} title="Couldn't load recent games" onRetry={() => void query.refetch()} />
      </GlowCard>
    );
  } else if (games.length === 0) {
    body = (
      <GlowCard>
        <EmptyState
          compact
          icon={History}
          title="No games yet"
          description="The roster's games show up here as soon as they're played."
        />
      </GlowCard>
    );
  } else {
    body = (
      <div className="flex flex-col gap-2">
        {games.map((game) => (
          <StackGameRow key={`${game.match_id}-${game.team_id}`} game={game} />
        ))}
        {hasNextPage && games.length < MAX_GAMES ? (
          <Button
            variant="outline"
            className="mt-1 self-center"
            disabled={isFetchingNextPage}
            onClick={() => void fetchNextPage()}
          >
            {isFetchingNextPage ? "Loading…" : "Show more"}
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <section aria-labelledby="recent-games" className="flex flex-col gap-4">
      <SectionHeader
        eyebrow="Latest"
        icon={History}
        title={<span id="recent-games">Recent games</span>}
        description="What the squad has been playing. Friends who queued together share a row."
      />
      {body}
    </section>
  );
}
