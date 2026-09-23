/**
 * Summoner "Trends" tab: the tilt detector (sessions), best time to play (schedule heatmap),
 * nemesis champions (lane matchups) and unlucky losses / lucky wins, under one period and
 * queue filter row. Each card owns its query, loading, empty and error states.
 */
import { Activity, CalendarRange } from "lucide-react";

import { useSessionInsights } from "@/api/queries";
import { EmptyState, GlowCard, Stagger, StaggerItem } from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

import { useTrendsFilters } from "./hooks";
import { LuckCard } from "./LuckCard";
import { MatchupsCard } from "./MatchupsCard";
import { gamesPhrase, type TrendsFilters } from "./model";
import { TrendsFilterBar } from "./parts";
import { ScheduleCard } from "./ScheduleCard";
import { SessionsCard } from "./SessionsCard";

export interface TrendsTabProps {
  puuid: string;
}

export function TrendsTab({ puuid }: TrendsTabProps) {
  const [filters, setFilters] = useTrendsFilters();
  // The session query is the cheapest one and counts every game in scope, so it decides
  // whether there is anything to show at all (the cards share its cache entry).
  const sessions = useSessionInsights(puuid, filters);
  const games = sessions.data?.games;
  const nothing = sessions.isSuccess && !sessions.isPlaceholderData && games === 0;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <TrendsFilterBar filters={filters} onChange={setFilters}>
        {sessions.isPending ? (
          <Skeleton className="h-4 w-48" aria-hidden="true" />
        ) : games !== undefined ? (
          <span className={cn("tabular-nums transition-opacity duration-200", sessions.isPlaceholderData && "opacity-60")}>
            Patterns from {gamesPhrase(filters, games)}
          </span>
        ) : null}
      </TrendsFilterBar>

      {nothing ? (
        <NothingInScope filters={filters} onChange={setFilters} />
      ) : (
        <Stagger className="flex flex-col gap-6">
          <StaggerItem className="min-w-0">
            <SessionsCard puuid={puuid} filters={filters} />
          </StaggerItem>
          <StaggerItem className="min-w-0">
            <ScheduleCard puuid={puuid} filters={filters} />
          </StaggerItem>
          <StaggerItem className="min-w-0">
            <MatchupsCard puuid={puuid} filters={filters} />
          </StaggerItem>
          <StaggerItem className="min-w-0">
            <LuckCard puuid={puuid} filters={filters} />
          </StaggerItem>
        </Stagger>
      )}
    </div>
  );
}

/** No ranked game in the chosen period and queue: one message and a way to widen the filter. */
function NothingInScope({ filters, onChange }: { filters: TrendsFilters; onChange: (next: TrendsFilters) => void }) {
  const widen: { label: string; next: TrendsFilters } | null =
    filters.queue !== "all"
      ? { label: "Show both queues", next: { ...filters, queue: "all" } }
      : filters.since === "season"
        ? { label: "Show all time", next: { ...filters, since: "all" } }
        : null;
  return (
    <GlowCard>
      <EmptyState
        icon={widen ? CalendarRange : Activity}
        title={`No ${gamesPhrase(filters)}`}
        description="Trends need stored ranked games: sessions, the best time to play, lane matchups and games where the AI Score and the result disagreed."
        action={
          widen ? (
            <Button variant="outline" size="sm" onClick={() => onChange(widen.next)}>
              {widen.label}
            </Button>
          ) : null
        }
      />
    </GlowCard>
  );
}
