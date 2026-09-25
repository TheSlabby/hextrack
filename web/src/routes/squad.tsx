/**
 * /squad: duo synergy grid and who carries whom, for the tracked roster.
 * Filters live in the URL (`?since=all&queue=solo`; defaults omitted, like the leaderboard).
 */
import { useCallback, useMemo, type ReactNode } from "react";
import { getRouteApi } from "@tanstack/react-router";
import { CalendarDays, Sparkles, Swords, Users, UsersRound } from "lucide-react";

import { useSquadPairs } from "@/api/queries";
import type { LeaderboardQueue, SquadPairs, StatsSince } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Reveal } from "@/components/common/Motion";
import { SectionHeader } from "@/components/common/SectionHeader";
import { LiveNowStrip } from "@/components/home/LiveNowStrip";
import { QueueToggle } from "@/components/leaderboard/QueueToggle";
import { RosterEmptyState } from "@/components/leaderboard/RosterEmptyState";
import { CarryCard } from "@/components/squad/CarryCard";
import { CarryRankingCard } from "@/components/squad/CarryRankingCard";
import { DuoListCard } from "@/components/squad/DuoListCard";
import { buildSquadModel, carryStandings, rankDuos, type SquadModel } from "@/components/squad/model";
import { SinceToggle } from "@/components/squad/SinceToggle";
import { SquadSkeleton } from "@/components/squad/SquadSkeleton";
import { SynergyCard } from "@/components/squad/SynergyCard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatDate, plural } from "@/lib/format";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import { modelVersionDate } from "@/lib/score";

const QUEUE_CAPTION: Readonly<Record<LeaderboardQueue, string>> = {
  all: "Ranked Solo/Duo and Flex",
  solo: "Ranked Solo/Duo",
  flex: "Ranked Flex",
};

const route = getRouteApi("/squad");

function modelLabel(version: string): string {
  const trained = modelVersionDate(version);
  return trained ? `trained ${formatDate(trained)}` : version;
}

function FilterCaption({
  data,
  model,
  since,
  queue,
  failed,
}: {
  data: SquadPairs | undefined;
  model: SquadModel | null;
  since: StatsSince;
  queue: LeaderboardQueue;
  failed: boolean;
}) {
  if (!data && failed) return null;
  if (!data || !model) {
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
        {since === "season" ? (
          <>
            Season since <span className="font-medium text-text">{formatDate(data.season_start)}</span>
          </>
        ) : (
          "All stored games"
        )}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Users className="size-4 text-text-muted" aria-hidden="true" />
        {model.players.length} of {plural(data.players.length, "tracked player")} with duo games · {QUEUE_CAPTION[queue]}
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

/** Who isn't in the grids, so a missing friend isn't a mystery. */
function BenchNote({ model, since }: { model: SquadModel; since: StatsSince }) {
  if (model.benched.length === 0) return null;
  const played = model.benched.filter((player) => player.games > 0);
  const idle = model.benched.length - played.length;
  const period = since === "season" ? "this season" : "in the stored games";
  const parts: ReactNode[] = [];
  if (played.length > 0) {
    parts.push(
      <span key="played">
        {played.map((player, index) => (
          <span key={player.puuid}>
            {index > 0 ? (index === played.length - 1 ? " and " : ", ") : null}
            <span className="text-text-secondary">
              {player.game_name}#{player.tag_line}
            </span>
          </span>
        ))}{" "}
        played ranked {period} but never on a team with another tracked player
      </span>,
    );
  }
  if (idle > 0) {
    parts.push(
      <span key="idle">
        {plural(idle, "tracked player")} {idle === 1 ? "has" : "have"} no ranked games {period} with these filters
      </span>,
    );
  }
  return (
    <p className="text-xs leading-relaxed text-text-muted">
      Not in the grids:{" "}
      {parts.map((part, index) => (
        <span key={index}>
          {index > 0 ? "; " : null}
          {part}
        </span>
      ))}
      .
    </p>
  );
}

export function SquadPage() {
  useDocumentTitle(pageTitle("Squad"));
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const since: StatsSince = search.since ?? "season";
  const queue: LeaderboardQueue = search.queue ?? "all";
  const setSince = useCallback(
    (next: StatsSince) =>
      void navigate({ search: (prev) => ({ ...prev, since: next === "season" ? undefined : next }), replace: true }),
    [navigate],
  );
  const setQueue = useCallback(
    (next: LeaderboardQueue) =>
      void navigate({ search: (prev) => ({ ...prev, queue: next === "all" ? undefined : next }), replace: true }),
    [navigate],
  );

  const query = useSquadPairs(since, queue);
  const { data } = query;
  const model = useMemo(() => (data ? buildSquadModel(data) : null), [data]);
  const duos = useMemo(() => (model ? rankDuos(model) : null), [model]);
  const standings = useMemo(() => (model ? carryStandings(model) : []), [model]);
  const refetching = query.isPlaceholderData;

  let body: ReactNode;
  if (query.isPending) {
    body = <SquadSkeleton />;
  } else if (!data || !model || !duos) {
    body = (
      <GlowCard>
        <ErrorState error={query.error} title="Couldn't load the squad" onRetry={() => void query.refetch()} />
      </GlowCard>
    );
  } else if (data.players.length === 0) {
    body = <RosterEmptyState />;
  } else if (data.players.length < 2) {
    body = (
      <GlowCard>
        <EmptyState
          icon={UsersRound}
          title="The squad needs two tracked players"
          description="Duo stats compare tracked friends who queued together. Add another player to the roster with hextrack roster add."
        />
      </GlowCard>
    );
  } else if (model.players.length < 2) {
    const widen = since === "season" || queue !== "all";
    body = (
      <GlowCard>
        <EmptyState
          icon={UsersRound}
          title="No duo games yet"
          description={
            widen
              ? "No two tracked players were on the same team in a ranked game with these filters."
              : "No two tracked players have been on the same team in a stored ranked game yet."
          }
          action={
            widen ? (
              <>
                {since === "season" ? (
                  <Button variant="outline" size="sm" onClick={() => setSince("all")}>
                    Show all time
                  </Button>
                ) : null}
                {queue !== "all" ? (
                  <Button variant="outline" size="sm" onClick={() => setQueue("all")}>
                    Show both queues
                  </Button>
                ) : null}
              </>
            ) : null
          }
        />
      </GlowCard>
    );
  } else {
    body = (
      <div
        className={cn("flex flex-col gap-6 transition-opacity duration-200", refetching && "pointer-events-none opacity-60")}
        aria-busy={refetching || undefined}
      >
        <Reveal>
          {/* The matrix card keeps its natural width beside the lists (they take the free space,
              grow 100 vs 1) and stretches to the page edge once the lists wrap below it. */}
          <section aria-label="Duo synergy" className="flex flex-wrap items-start gap-6">
            <SynergyCard model={model} className="max-w-full shrink-0 grow" />
            <div className="@container flex min-w-[min(100%,20rem)] shrink grow-[100] basis-80">
              <div className="grid w-full gap-6 @2xl:grid-cols-2">
                <DuoListCard kind="best" entries={duos.best} labels={model.labels} />
                <DuoListCard kind="worst" entries={duos.worst} labels={model.labels} />
              </div>
            </div>
          </section>
        </Reveal>
        <Reveal delay={0.06}>
          {model.scoredPairs > 0 ? (
            <section aria-label="Who carries whom" className="flex flex-wrap items-start gap-6">
              <CarryCard model={model} standings={standings} className="max-w-full shrink-0 grow" />
              <CarryRankingCard
                standings={standings}
                labels={model.labels}
                className="min-w-[min(100%,20rem)] shrink grow-[100] basis-80"
              />
            </section>
          ) : (
            <GlowCard glow="cyan">
              <EmptyState
                tone="ai"
                icon={Swords}
                title="Who carries whom needs AI Scores"
                description={
                  data.model_version
                    ? "None of these duo games have AI Scores from the current model yet. They appear once the games are scored."
                    : "No AI model is trained yet. Once one is, this compares who had the higher AI Score in your duo games."
                }
              />
            </GlowCard>
          )}
        </Reveal>
        <BenchNote model={model} since={since} />
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
            icon={UsersRound}
            title="Squad"
            description="Who wins together, and who had the higher AI Score when you queued together."
            action={
              <>
                <SinceToggle value={since} onChange={setSince} />
                <QueueToggle value={queue} onChange={setQueue} />
              </>
            }
          />
          <FilterCaption data={data} model={model} since={since} queue={queue} failed={query.isError} />
        </div>
      </Reveal>
      <LiveNowStrip />
      {body}
    </div>
  );
}
