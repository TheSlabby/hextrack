/**
 * /stacks: games where several tracked players queued on the same team, with awards, lineups,
 * per-player stats, highlights and the game list. Filters live in the URL
 * (`?size=4&since=all&queue=flex`; defaults omitted, like /squad).
 */
import { useCallback, type ReactNode } from "react";
import { getRouteApi } from "@tanstack/react-router";
import { CalendarDays, Gamepad2, Layers } from "lucide-react";

import { useStackSummary } from "@/api/queries";
import type { StackQueue, StackSize, StackSummary, StatsSince } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Reveal } from "@/components/common/Motion";
import { SectionHeader } from "@/components/common/SectionHeader";
import { SinceToggle } from "@/components/squad/SinceToggle";
import { StackAwards } from "@/components/stacks/StackAwards";
import { StackGameList } from "@/components/stacks/StackGameList";
import { StackHighlights } from "@/components/stacks/StackHighlights";
import { StackLineups } from "@/components/stacks/StackLineups";
import { StackPlayerTable } from "@/components/stacks/StackPlayerTable";
import { StackQueueToggle } from "@/components/stacks/StackQueueToggle";
import { StackSizeToggle } from "@/components/stacks/StackSizeToggle";
import { StackSummaryHeader } from "@/components/stacks/StackSummaryHeader";
import { STACK_PERIOD_LABEL, STACK_QUEUE_LABEL, stackLabel, stackLabelPlural } from "@/components/stacks/model";
import { StacksSkeleton } from "@/components/stacks/StacksSkeleton";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatDate, plural } from "@/lib/format";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";

const route = getRouteApi("/stacks");

/** "five tracked players", "four or more tracked players". */
const SIZE_PHRASE: Readonly<Record<StackSize, string>> = {
  5: "five tracked players",
  4: "four or more tracked players",
  3: "three or more tracked players",
};

/** The active filters in words: "5-stacks · Season since Jan 8 · All queues · 42 games". */
function FilterCaption({
  data,
  since,
  queue,
  size,
  stale,
}: {
  data: StackSummary | undefined;
  since: StatsSince;
  queue: StackQueue;
  size: StackSize;
  /** The data is still the previous filters' (placeholder while refetching). */
  stale: boolean;
}) {
  return (
    <p className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
      <span className="inline-flex items-center gap-1.5">
        <Layers className="size-4 text-text-muted" aria-hidden="true" />
        <span className="font-medium text-text">{stackLabelPlural(size)}</span>
      </span>
      <span className="inline-flex items-center gap-1.5">
        <CalendarDays className="size-4 text-text-muted" aria-hidden="true" />
        {since === "season" && data ? (
          <>
            Season since <span className="font-medium text-text">{formatDate(data.season_start)}</span>
          </>
        ) : (
          STACK_PERIOD_LABEL[since]
        )}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Gamepad2 className="size-4 text-text-muted" aria-hidden="true" />
        {STACK_QUEUE_LABEL[queue]}
        {data && !stale ? <span className="tabular-nums"> · {plural(data.games, "game")}</span> : null}
      </span>
    </p>
  );
}

export function StacksPage() {
  useDocumentTitle(pageTitle("Stacks"));
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const since: StatsSince = search.since ?? "season";
  const queue: StackQueue = search.queue ?? "all";
  const size: StackSize = search.size ?? 5;
  const setSince = useCallback(
    (next: StatsSince) =>
      void navigate({ search: (prev) => ({ ...prev, since: next === "season" ? undefined : next }), replace: true }),
    [navigate],
  );
  const setQueue = useCallback(
    (next: StackQueue) =>
      void navigate({ search: (prev) => ({ ...prev, queue: next === "all" ? undefined : next }), replace: true }),
    [navigate],
  );
  const setSize = useCallback(
    (next: StackSize) =>
      void navigate({ search: (prev) => ({ ...prev, size: next === 5 ? undefined : next }), replace: true }),
    [navigate],
  );

  const query = useStackSummary({ since, queue, size });
  const { data } = query;
  const refetching = query.isPlaceholderData;

  let body: ReactNode;
  if (query.isPending) {
    body = <StacksSkeleton />;
  } else if (!data) {
    body = (
      <GlowCard>
        <ErrorState error={query.error} title="Couldn't load stacks" onRetry={() => void query.refetch()} />
      </GlowCard>
    );
  } else if (data.games === 0) {
    const widen = since === "season" || size !== 3 || queue !== "all";
    body = (
      <GlowCard className={cn("transition-opacity duration-200", refetching && "pointer-events-none opacity-60")}>
        <EmptyState
          icon={Layers}
          title={`No ${stackLabelPlural(size)} yet`}
          description={
            widen
              ? `No game had ${SIZE_PHRASE[size]} on the same team with these filters.`
              : `No stored game has ${SIZE_PHRASE[size]} on the same team yet.`
          }
          action={
            widen ? (
              <>
                {since === "season" ? (
                  <Button variant="outline" size="sm" onClick={() => setSince("all")}>
                    Show all time
                  </Button>
                ) : null}
                {size === 5 ? (
                  <Button variant="outline" size="sm" onClick={() => setSize(4)}>
                    Try 4+
                  </Button>
                ) : size === 4 ? (
                  <Button variant="outline" size="sm" onClick={() => setSize(3)}>
                    Try 3+
                  </Button>
                ) : null}
                {queue !== "all" ? (
                  <Button variant="outline" size="sm" onClick={() => setQueue("all")}>
                    All queues
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
          <StackSummaryHeader data={data} />
        </Reveal>
        <Reveal delay={0.03}>
          <div className="grid items-start gap-6 lg:grid-cols-2">
            <div className="min-w-0">
              <StackAwards data={data} />
            </div>
            <div className="min-w-0">
              <StackLineups data={data} />
            </div>
          </div>
        </Reveal>
        <Reveal delay={0.06}>
          <StackPlayerTable data={data} />
        </Reveal>
        <Reveal delay={0.09}>
          <StackHighlights data={data} />
        </Reveal>
        <Reveal delay={0.12}>
          <section aria-label="Games" className="flex flex-col gap-3">
            <SectionHeader title="Games" description={`Every ${stackLabel(size)}, newest first.`} />
            <StackGameList since={since} queue={queue} size={size} />
          </section>
        </Reveal>
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
            icon={Layers}
            title="Stacks"
            description="Games where the squad queued together: the record, the lineups and who showed up."
            action={
              <>
                <StackSizeToggle value={size} onChange={setSize} />
                <SinceToggle value={since} onChange={setSince} />
                <StackQueueToggle value={queue} onChange={setQueue} />
              </>
            }
          />
          <FilterCaption data={data} since={since} queue={queue} size={size} stale={refetching} />
        </div>
      </Reveal>
      {body}
    </div>
  );
}
