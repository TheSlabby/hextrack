/**
 * Nemesis champions: the player's record against each enemy champion in their lane (the
 * enemy with the same position), as two lists: losing records (nemeses) and winning ones
 * (favourite opponents).
 */
import { useState, type ReactNode } from "react";
import { Crosshair, Skull, Swords } from "lucide-react";

import { useMatchupInsights } from "@/api/queries";
import type { ChampionMatchup, MatchupInsights } from "@/api/types";
import { AiScoreBadge, EmptyState, ErrorState, GlowCard, SectionHeader } from "@/components/common";
import { MatchupRow } from "@/components/common/MatchupRow";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { championDisplayName } from "@/lib/champions";
import { plural } from "@/lib/format";

import { gamesPhrase, type TrendsFilters } from "./model";
import { Refetching } from "./parts";

const MIN_GAMES_OPTIONS = [3, 5, 10] as const;
type MinGames = (typeof MIN_GAMES_OPTIONS)[number];

function isMinGames(value: number): value is MinGames {
  return (MIN_GAMES_OPTIONS as readonly number[]).includes(value);
}

const LIST_ROWS = 8;

export interface MatchupsCardProps {
  puuid: string;
  filters: TrendsFilters;
}

export function MatchupsCard({ puuid, filters }: MatchupsCardProps) {
  const [minGames, setMinGames] = useState<MinGames>(3);
  const query = useMatchupInsights(puuid, { ...filters, minGames });
  const data = query.data;

  let body: ReactNode;
  if (query.isPending) {
    body = <MatchupsSkeleton />;
  } else if (query.isError) {
    body = <ErrorState compact error={query.error} title="Couldn't load matchups" onRetry={() => void query.refetch()} />;
  } else if (!data || data.total_matchups === 0) {
    body = (
      <EmptyState
        compact
        icon={Crosshair}
        title="No lane matchups yet"
        description={`No ${gamesPhrase(filters)} with a known lane opponent for this player.`}
      />
    );
  } else {
    body = (
      <Refetching active={query.isPlaceholderData}>
        <MatchupsBody data={data} />
      </Refetching>
    );
  }

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader
        eyebrow="Lane matchups"
        title="Nemesis champions"
        icon={Crosshair}
        description="Record against the enemy champion in the same position."
        action={
          <ToggleGroup
            type="single"
            size="sm"
            value={String(minGames)}
            onValueChange={(value) => {
              const next = Number(value);
              if (isMinGames(next)) setMinGames(next);
            }}
            aria-label="Fewest games against a champion"
          >
            {MIN_GAMES_OPTIONS.map((option) => (
              <ToggleGroupItem
                key={option}
                value={String(option)}
                aria-label={`${option}+ games`}
                title={`Champions faced at least ${option} times`}
              >
                {option}+
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        }
      />
      {body}
    </GlowCard>
  );
}

function MatchupsBody({ data }: { data: MatchupInsights }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2 md:gap-5">
        <MatchupList
          title="Nemeses"
          icon={Skull}
          items={data.nemeses}
          empty={`No losing record against a champion faced ${data.min_games}+ times.`}
        />
        <MatchupList
          title="Favourite opponents"
          icon={Swords}
          items={data.favorites}
          empty={`No winning record against a champion faced ${data.min_games}+ times.`}
        />
      </div>
      <p className="text-xs text-text-muted">
        Champions faced at least {plural(data.min_games, "time")} in lane, from {plural(data.total_matchups, "game")} with a
        known lane opponent. Even records sit in neither list. Gold is the average difference from the lane opponent at the
        end of the game.
      </p>
    </div>
  );
}

function MatchupList({
  title,
  icon: Icon,
  items,
  empty,
}: {
  title: string;
  icon: typeof Skull;
  items: readonly ChampionMatchup[];
  empty: string;
}) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-2">
      <h3 className="label-caps flex items-center gap-1.5">
        <Icon className="size-3.5" aria-hidden="true" />
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border-strong px-3 py-5 text-center text-sm text-text-secondary">
          {empty}
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.slice(0, LIST_ROWS).map((item) => (
            <li key={item.champion_id}>
              <MatchupItem item={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MatchupItem({ item }: { item: ChampionMatchup }) {
  return (
    <MatchupRow
      champion={item.champion_name}
      wins={item.wins}
      losses={item.losses}
      avgGoldDiff={item.avg_gold_diff}
      detail={
        item.avg_ai_score !== null ? (
          <AiScoreBadge
            score={item.avg_ai_score}
            kind="average"
            size="sm"
            detail={`Over ${plural(item.games, "game")} against ${championDisplayName(item.champion_name)}.`}
          />
        ) : (
          <span>not scored</span>
        )
      }
    />
  );
}

function MatchupsSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 md:gap-5" role="status" aria-label="Loading matchups">
      {Array.from({ length: 2 }, (_, list) => (
        <div key={list} className="flex flex-col gap-2">
          <Skeleton className="h-4 w-28" />
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-[3.25rem] rounded-xl" />
          ))}
        </div>
      ))}
    </div>
  );
}
