/**
 * Nemesis champions: the player's record against each enemy champion in their lane (the
 * enemy with the same position), as two lists: losing records (nemeses) and winning ones
 * (favourite opponents).
 */
import { useState, type ReactNode } from "react";
import { Crosshair, Skull, Swords } from "lucide-react";

import { useMatchupInsights } from "@/api/queries";
import type { ChampionMatchup, MatchupInsights } from "@/api/types";
import { AiScoreBadge, ChampionIcon, EmptyState, ErrorState, GlowCard, SectionHeader, WinRateBar } from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { championDisplayName } from "@/lib/champions";
import { formatPercent, plural } from "@/lib/format";

import { formatSignedCompact, gamesPhrase, type TrendsFilters } from "./model";
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
              <MatchupRow item={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MatchupRow({ item }: { item: ChampionMatchup }) {
  const name = championDisplayName(item.champion_name);
  const gold = Math.round(item.avg_gold_diff);
  return (
    <div
      className="flex items-center gap-3 rounded-xl border border-border bg-surface-2/40 px-2.5 py-2"
      aria-label={`${name}: ${item.wins} wins, ${item.losses} losses, ${formatPercent(item.winrate)} win rate, ${formatSignedCompact(gold)} gold on average`}
    >
      <ChampionIcon champion={item.champion_name} size="sm" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm font-semibold text-text">{name}</span>
        <span className="flex items-center gap-2 text-xs text-text-muted tabular-nums">
          <span className="text-text-secondary">{formatSignedCompact(gold)} gold</span>
          {item.avg_ai_score !== null ? (
            <AiScoreBadge
              score={item.avg_ai_score}
              kind="average"
              size="sm"
              detail={`Over ${plural(item.games, "game")} against ${name}.`}
            />
          ) : (
            <span>not scored</span>
          )}
        </span>
      </div>
      <WinRateBar wins={item.wins} losses={item.losses} size="sm" className="w-24 shrink-0 sm:w-28" />
    </div>
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
