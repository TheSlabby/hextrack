import { getRouteApi, Link } from "@tanstack/react-router";
import { Home, RadioTower, ScrollText } from "lucide-react";

import { useLiveGames } from "@/api/queries";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { SkeletonRows } from "@/components/common/Skeletons";
import { LiveGameView } from "@/components/live/LiveGameView";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import { queueLabel } from "@/lib/queues";

const route = getRouteApi("/live/$gameId");

function LiveGameSkeleton() {
  return (
    <div className="flex min-w-0 flex-col gap-4 sm:gap-5" role="status" aria-label="Loading live game">
      <GlowCard className="flex flex-col gap-4 p-4 sm:p-5" aria-hidden="true">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex flex-col gap-2">
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-8 w-56" />
            <Skeleton className="h-3 w-72 max-w-full" />
          </div>
          <div className="flex flex-col gap-1.5 sm:items-end">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-9 w-24" />
          </div>
        </div>
        <Skeleton className="h-7 w-64 max-w-full rounded-full" />
      </GlowCard>
      {[0, 1].map((team) => (
        <GlowCard key={team} className="overflow-hidden" aria-hidden="true">
          <div className="flex items-center gap-2.5 border-b border-border px-3 py-3 sm:px-4">
            <Skeleton className="h-5 w-1 rounded-full" />
            <Skeleton className="h-4 w-24" />
          </div>
          <SkeletonRows rows={5} className="px-3 sm:px-4" />
        </GlowCard>
      ))}
    </div>
  );
}

function NotLive({ gameId, checking }: { gameId: string; checking: boolean }) {
  const matchId = /^\d+$/.test(gameId) ? `NA1_${gameId}` : null;
  return (
    <GlowCard className="mx-auto mt-4 w-full max-w-xl">
      <EmptyState
        icon={RadioTower}
        title={checking ? "This game has ended (or isn't live)" : "Live games aren't being checked right now"}
        description={
          checking ? (
            <>
              HexTrack doesn&apos;t see this game in progress anymore. If it just finished, the full match page shows up
              in a few minutes once the worker stores it.
            </>
          ) : (
            <>
              The worker hasn&apos;t looked for live games yet, so there&apos;s nothing to show. If this game already
              finished, its match page shows up in a few minutes once the worker stores it.
            </>
          )
        }
        action={
          <>
            {matchId ? (
              <Button asChild>
                <Link to="/match/$matchId" params={{ matchId }}>
                  <ScrollText aria-hidden="true" />
                  Open the match page
                </Link>
              </Button>
            ) : null}
            <Button variant="ghost" asChild>
              <Link to="/">
                <Home aria-hidden="true" />
                Back to home
              </Link>
            </Button>
          </>
        }
      />
    </GlowCard>
  );
}

/** /live/$gameId: a roster player's game in progress, from the worker's last live check. */
export function LiveGamePage() {
  const { gameId } = route.useParams();
  const query = useLiveGames();
  const game = query.data?.games.find((g) => String(g.game_id) === gameId);

  useDocumentTitle(
    game ? pageTitle(`Live: ${queueLabel(game.queue_id ?? -1, game.game_mode, game.queue_label)}`) : pageTitle("Live game"),
  );

  if (query.isPending) return <LiveGameSkeleton />;

  if (!query.data) {
    return (
      <GlowCard className="mx-auto mt-4 w-full max-w-xl">
        <ErrorState
          error={query.error}
          title="Couldn't load live games"
          onRetry={() => void query.refetch()}
          action={
            <Button variant="ghost" size="sm" asChild>
              <Link to="/">Go home</Link>
            </Button>
          }
        />
      </GlowCard>
    );
  }

  if (!game) return <NotLive gameId={gameId} checking={query.data.checked_at !== null} />;

  return <LiveGameView game={game} intervalSeconds={query.data.interval_seconds} />;
}
