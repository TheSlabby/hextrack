import { useMemo } from "react";

import { useLeaderboard } from "@/api/queries";
import { AiScoreTeaser } from "@/components/home/AiScoreTeaser";
import { HomeHero } from "@/components/home/HomeHero";
import { RecentGames } from "@/components/home/RecentGames";
import { SITE_NAME, useDocumentTitle } from "@/lib/hooks";
import { RosterHighlights } from "@/components/home/RosterHighlights";
import { SquadSection } from "@/components/home/SquadSection";
import { computeStandings } from "@/components/leaderboard/sorting";

export function HomePage() {
  useDocumentTitle(`${SITE_NAME} · League stats with an AI Score`);
  const leaderboard = useLeaderboard("all");
  const { data, isPending, error, refetch } = leaderboard;

  const entries = useMemo(() => data?.entries ?? [], [data]);
  const standings = useMemo(() => computeStandings(entries), [entries]);
  // The hero's example players are the ones with the most games: their profiles have the most
  // to show, whatever their standing.
  const examples = useMemo(
    () => [...entries].sort((a, b) => b.games - a.games || b.winrate - a.winrate).slice(0, 3),
    [entries],
  );
  const hasRoster = isPending || entries.length > 0;
  const failed = Boolean(error) && !data;

  return (
    <div className="flex flex-col gap-14 sm:gap-20">
      <HomeHero examples={examples} loading={isPending} />

      {hasRoster && !failed ? <RecentGames /> : null}

      <SquadSection
        data={data}
        standings={standings}
        isPending={isPending}
        error={error}
        onRetry={() => void refetch()}
      />

      {hasRoster && !failed ? (
        <div className="grid grid-cols-1 items-stretch gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)]">
          <RosterHighlights entries={standings.ordered} isPending={isPending} />
          <AiScoreTeaser />
        </div>
      ) : (
        <AiScoreTeaser className="lg:max-w-xl" />
      )}
    </div>
  );
}
