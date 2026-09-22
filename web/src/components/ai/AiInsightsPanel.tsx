import { useMemo, type ReactNode } from "react";
import { BarChart3, Cpu, Gamepad2, Scale, Sparkles, Wand2 } from "lucide-react";

import { useAiExplain, useAiTrend, useMeta } from "@/api/queries";
import type { AiExplain } from "@/api/types";
import {
  AiScoreRing,
  EmptyState,
  ErrorState,
  GlowCard,
  SectionHeader,
  SkeletonChart,
  SkeletonCircle,
  Stagger,
  StaggerItem,
} from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatSigned, plural } from "@/lib/format";
import { AI_AVERAGE_NOTE, averageOffset, toScore100 } from "@/lib/score";

import { AiScoreExplainer } from "./AiScoreExplainer";
import { AttributionChart } from "./AttributionChart";
import {
  AI_EXPLAIN_LIMIT,
  AI_INSIGHTS_TREND_LIMIT,
  averageRate,
  buildDrivers,
  buildHistogram,
  scopeToSeason,
  summarizeDrivers,
  type ScopedPoints,
} from "./insights";
import { CommandChip, ModelMissingState } from "./parts";
import { ScoreHistogram } from "./ScoreHistogram";

/** Season figures from the profile (ranked queues, remakes excluded), as the header shows them. */
export interface AiSeasonSummary {
  /** Season average AI Score (0..1), null when no ranked game is scored. */
  average: number | null;
  /** Scored ranked games this season. */
  games: number;
}

export interface AiInsightsPanelProps {
  puuid: string;
  /**
   * The profile's season average. When given, the headline shows it (so it matches the profile
   * header); the distribution still covers the latest scored games the trend query returns.
   * Without it the headline averages those trend games and says so.
   */
  season?: AiSeasonSummary;
  /**
   * Draw the season-average AiScoreRing in the headline card (default true). Pass false where
   * the page already shows a ring for this player (the summoner header), so each view has one;
   * the average is then shown as a compact number with its offset from a coin flip instead.
   */
  showRing?: boolean;
  className?: string;
}

const HISTOGRAM_HEIGHT = 188;
const RING_SIZE = 144;

/**
 * The AI Insights tab: headline average ring with a plain-language summary, the score
 * distribution, and the per-stat attributions behind the score. Renders its own cards.
 */
export function AiInsightsPanel({ puuid, season, showRing = true, className }: AiInsightsPanelProps) {
  const explain = useAiExplain(puuid, AI_EXPLAIN_LIMIT);
  const trend = useAiTrend(puuid, AI_INSIGHTS_TREND_LIMIT);
  const meta = useMeta();

  const scoped = useMemo<ScopedPoints | null>(
    () => (trend.data ? scopeToSeason(trend.data.points, meta.data?.season_start) : null),
    [trend.data, meta.data?.season_start],
  );

  // 503 model_missing resolves to null: a designed "not trained yet" state, not an error.
  if (explain.data === null) {
    return <ModelMissingState className={className} />;
  }

  // Nothing scored at all: one tab-level message instead of three empty cards.
  const nothingScored =
    trend.isSuccess &&
    trend.data.points.length === 0 &&
    explain.isSuccess &&
    explain.data.n_matches === 0 &&
    (season?.average ?? null) === null;
  if (nothingScored) {
    return <NothingScoredState className={className} />;
  }

  return (
    <Stagger className={cn("grid min-w-0 gap-6 lg:grid-cols-2", className)}>
      <StaggerItem className="min-w-0">
        <HeadlineCard explain={explain} trend={trend} scoped={scoped} season={season} showRing={showRing} />
      </StaggerItem>
      <StaggerItem className="min-w-0">
        <DistributionCard trend={trend} scoped={scoped} hasRankedGames={(explain.data?.n_matches ?? 0) > 0} />
      </StaggerItem>
      <StaggerItem className="min-w-0 lg:col-span-2">
        <DriversCard explain={explain} />
      </StaggerItem>
    </Stagger>
  );
}

type ExplainQuery = ReturnType<typeof useAiExplain>;
type TrendQuery = ReturnType<typeof useAiTrend>;

/** True when the trend query hit its cap, so the points are the latest N rather than a whole season. */
function isCapped(trend: TrendQuery, scoped: ScopedPoints | null): boolean {
  const fetched = trend.data?.points.length ?? 0;
  return fetched >= AI_INSIGHTS_TREND_LIMIT && (scoped?.points.length ?? 0) === fetched;
}

/** What the trend-derived numbers cover: "Last 200 scored games", "84 scored games this season". */
function trendCoverage(trend: TrendQuery, scoped: ScopedPoints | null): string {
  const games = scoped?.points.length ?? 0;
  if (isCapped(trend, scoped)) return `Last ${plural(games, "scored game")}`;
  if (scoped?.scope === "season") return `${plural(games, "scored game")} this season`;
  return plural(games, "recent scored game");
}

function NothingScoredState({ className }: { className?: string }) {
  return (
    <GlowCard glow="cyan" className={cn("overflow-hidden", className)}>
      <EmptyState
        tone="ai"
        icon={Sparkles}
        title="No scored games yet"
        description="The AI Score rates each stored ranked game from its end-of-game stats. The season average, how the scores spread and the stats behind them show up here after this player's first scored game."
        action={<AiScoreExplainer />}
      />
    </GlowCard>
  );
}

// --- headline ---------------------------------------------------------------------------

interface HeadlineCardProps {
  explain: ExplainQuery;
  trend: TrendQuery;
  scoped: ScopedPoints | null;
  season: AiSeasonSummary | undefined;
  showRing: boolean;
}

function HeadlineCard({ explain, trend, scoped, season, showRing }: HeadlineCardProps) {
  // The profile's season average when there is one (so this matches the header); otherwise the
  // average of the games the trend query returned, labelled with what they actually cover.
  const fromSeason = season !== undefined && season.average !== null;
  const average = fromSeason ? season.average : (scoped ? averageRate(scoped.points) : null);
  const games = fromSeason ? season.games : (scoped?.points.length ?? 0);
  const loadingScore = !fromSeason && trend.isPending;
  // Never call a trend-derived number a season average next to a header that scopes differently.
  const seasonWide = fromSeason || (season === undefined && scoped?.scope === "season" && !isCapped(trend, scoped));
  const heading = games === 0 ? "AI Score" : seasonWide ? "Season average" : "Recent average";
  const ringLabel = games === 0 ? "Not scored" : seasonWide ? "Season avg" : "Recent avg";
  const coverage = fromSeason ? `${plural(games, "scored ranked game")} this season` : trendCoverage(trend, scoped);
  // Centred under the ring on phones; left-aligned when there is no ring.
  const align = showRing ? "justify-center sm:justify-start" : "justify-start";

  return (
    <GlowCard glow="cyan" className="flex h-full flex-col overflow-hidden p-5 sm:p-6">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 -left-16 size-64 rounded-full bg-cyan/10 blur-3xl"
      />
      <div
        className={cn(
          "relative flex flex-1 flex-col gap-5",
          showRing ? "items-center sm:flex-row sm:items-center sm:gap-6" : "items-stretch",
        )}
      >
        {!showRing ? null : loadingScore ? (
          <SkeletonCircle size={RING_SIZE} className="shrink-0" />
        ) : (
          <AiScoreRing score={average} kind="average" size={RING_SIZE} label={ringLabel} />
        )}
        <div className={cn("flex min-w-0 flex-1 flex-col gap-3", showRing ? "text-center sm:text-left" : "text-left")}>
          <div className="flex flex-col gap-1">
            <span className={cn("label-caps flex items-center gap-1.5", align)}>
              <Sparkles className="size-3.5 text-cyan" aria-hidden="true" />
              {heading}
            </span>
            {showRing ? null : loadingScore ? (
              <Skeleton className="h-9 w-24" />
            ) : (
              <p className="flex items-baseline gap-2">
                <span
                  className={cn(
                    "font-display text-4xl font-bold tabular-nums",
                    average !== null ? "text-cyan" : "text-text-muted",
                  )}
                >
                  {average !== null ? toScore100(average) : "–"}
                </span>
                {average !== null ? (
                  <span className="rounded-full border border-cyan/25 bg-cyan/8 px-2 py-0.5 text-xs font-semibold text-cyan tabular-nums">
                    {formatSigned(averageOffset(average))} vs 50
                  </span>
                ) : null}
              </p>
            )}
            {loadingScore ? (
              <Skeleton className={cn("h-4 w-48", showRing && "mx-auto sm:mx-0")} />
            ) : average !== null ? (
              <p className="text-sm text-text-secondary">{AI_AVERAGE_NOTE}</p>
            ) : trend.isError ? (
              <p className="text-sm text-text-secondary">Couldn't load stored scores.</p>
            ) : (
              <p className="text-sm text-text-secondary">No scored games yet.</p>
            )}
          </div>

          <DriverSummary explain={explain} />

          {explain.isPending || loadingScore ? (
            <div className={cn("flex flex-wrap gap-1.5", align)} aria-hidden="true">
              <Skeleton className="h-6 w-44 rounded-full" />
              <Skeleton className="h-6 w-36 rounded-full" />
            </div>
          ) : null}
          <ul
            className={cn(
              "flex flex-wrap items-center gap-1.5",
              align,
              (explain.isPending || loadingScore) && "hidden",
            )}
            aria-label="Details"
          >
            {games > 0 ? <MetaChip icon={Gamepad2}>{coverage}</MetaChip> : null}
            {explain.data ? (
              <MetaChip icon={Cpu}>
                Model <span className="font-mono text-[11px]">{explain.data.model_version}</span>
              </MetaChip>
            ) : null}
            {games > 0 && explain.data?.base_score !== null && explain.data?.base_score !== undefined ? (
              <MetaChip icon={Scale}>Average stat line scores {toScore100(explain.data.base_score)}</MetaChip>
            ) : null}
          </ul>
        </div>
      </div>
      <div className="relative mt-4 flex justify-center border-t border-border pt-3 sm:justify-end">
        <AiScoreExplainer />
      </div>
    </GlowCard>
  );
}

function DriverSummary({ explain }: { explain: ExplainQuery }) {
  const sentence = useMemo(() => {
    const data = explain.data;
    if (!data || data.features.length === 0) return null;
    return summarizeDrivers(buildDrivers(data.features));
  }, [explain.data]);

  if (explain.isPending) {
    return (
      <div className="flex flex-col gap-2" aria-hidden="true">
        <Skeleton className="mx-auto h-5 w-full max-w-sm sm:mx-0" />
        <Skeleton className="mx-auto h-5 w-2/3 sm:mx-0" />
      </div>
    );
  }
  if (explain.isError) return null;
  if (!sentence) {
    return (
      <p className="font-display text-base leading-snug text-text-secondary">
        Play a few ranked games to see what drives the score.
      </p>
    );
  }
  return <p className="font-display text-[17px] leading-snug font-medium text-balance text-text">{sentence}</p>;
}

function MetaChip({ icon: Icon, children }: { icon: typeof Cpu; children: ReactNode }) {
  return (
    <li className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2/70 px-2.5 py-1 text-[11px] font-medium tabular-nums text-text-secondary">
      <Icon className="size-3 text-text-muted" aria-hidden="true" />
      {children}
    </li>
  );
}

// --- distribution -----------------------------------------------------------------------

function DistributionCard({
  trend,
  scoped,
  hasRankedGames,
}: {
  trend: TrendQuery;
  scoped: ScopedPoints | null;
  hasRankedGames: boolean;
}) {
  const histogram = useMemo(() => (scoped ? buildHistogram(scoped.points) : null), [scoped]);
  const average = scoped ? averageRate(scoped.points) : null;
  const coverage = trendCoverage(trend, scoped);

  let body: ReactNode;
  if (trend.isPending) {
    body = <DistributionSkeleton />;
  } else if (trend.isError) {
    body = (
      <div className="flex items-center justify-center" style={{ minHeight: HISTOGRAM_HEIGHT + 56 }}>
        <ErrorState compact error={trend.error} onRetry={() => void trend.refetch()} title="Couldn't load scores" />
      </div>
    );
  } else if (!histogram || histogram.total === 0) {
    body = (
      <div className="flex items-center justify-center" style={{ minHeight: HISTOGRAM_HEIGHT + 56 }}>
        <EmptyState
          compact
          tone="ai"
          icon={BarChart3}
          title="No scored games yet"
          description={
            hasRankedGames ? (
              <span className="flex flex-col items-center gap-2">
                This player's stored games haven't been scored by the current model yet:
                <CommandChip command="hextrack model rescore" />
              </span>
            ) : (
              "Scores appear here once this player's ranked games are stored and scored."
            )
          }
        />
      </div>
    );
  } else {
    body = (
      <div className={cn("transition-opacity duration-200", trend.isFetching && "opacity-60")}>
        <ScoreHistogram histogram={histogram} average={average !== null ? average * 100 : null} height={HISTOGRAM_HEIGHT} />
      </div>
    );
  }

  return (
    <GlowCard className="flex h-full flex-col gap-4 p-5">
      <SectionHeader
        size="sm"
        eyebrow="Distribution"
        title="How the scores spread"
        description={
          histogram && histogram.total > 0
            ? `${coverage}${histogram.median !== null ? ` · median ${histogram.median}` : ""}`
            : "AI Scores in 10-point bins, coloured by grade."
        }
      />
      {body}
    </GlowCard>
  );
}

function DistributionSkeleton() {
  return (
    <div className="flex flex-col gap-3" role="status" aria-label="Loading score distribution">
      <div className="grid grid-cols-5 gap-1.5" aria-hidden="true">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-[64px] rounded-lg" />
        ))}
      </div>
      <SkeletonChart height={HISTOGRAM_HEIGHT} />
    </div>
  );
}

// --- drivers ----------------------------------------------------------------------------

function DriversCard({ explain }: { explain: ExplainQuery }) {
  const data: AiExplain | null | undefined = explain.data;

  let body: ReactNode;
  if (explain.isPending) {
    body = <DriversSkeleton />;
  } else if (explain.isError) {
    body = <ErrorState error={explain.error} onRetry={() => void explain.refetch()} title="Couldn't explain the score" />;
  } else if (!data || data.n_matches === 0 || data.features.length === 0) {
    body = (
      <EmptyState
        tone="ai"
        icon={Wand2}
        title="No ranked games to analyse yet"
        description="Once this player has ranked games stored, you'll see which stats lift or lower their AI Score."
      />
    );
  } else {
    body = (
      <div className={cn("transition-opacity duration-200", explain.isFetching && "opacity-60")}>
        <AttributionChart features={data.features} />
        <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-text-muted">
          Each bar is a stat's average effect across {plural(data.n_matches, "ranked game")}, measured by moving that
          stat from an all-average line to this player's (integrated gradients). The model sees some stats several
          ways (deaths per game, per minute and per gold earned), so those are combined into one net bar. The
          percentage is that stat's share of the model's total influence here, not AI Score points. Grey bars are
          mixed signals that run against the usual reading of a stat, such as more deaths lifting the score.
        </p>
      </div>
    );
  }

  return (
    <GlowCard className="flex flex-col gap-5 p-5">
      <SectionHeader
        eyebrow="Attributions"
        title="What drives the score"
        description={
          data && data.n_matches > 0
            ? `The stats that lift or lower the AI Score most, over the last ${plural(data.n_matches, "ranked game")}.`
            : "The stats that lift or lower the AI Score most."
        }
      />
      {body}
    </GlowCard>
  );
}

function DriversSkeleton() {
  return (
    <div className="flex flex-col gap-4" role="status" aria-label="Loading attributions">
      <div className="flex flex-wrap gap-1.5" aria-hidden="true">
        {[44, 88, 92, 72, 96, 84, 90].map((w, i) => (
          <Skeleton key={i} className="h-7 rounded-full" style={{ width: w }} />
        ))}
      </div>
      <div className="flex flex-col" aria-hidden="true">
        <div className="h-6" />
        {Array.from({ length: 10 }, (_, i) => (
          <div
            key={i}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_3.5rem] lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)_3.75rem]"
          >
            <div className="flex flex-col gap-1.5 py-0.5">
              <Skeleton className="h-3.5" style={{ width: `${55 + ((i * 29) % 40)}%` }} />
              <Skeleton className="h-3 w-24" />
            </div>
            <div className="relative order-last col-span-2 h-3 sm:order-none sm:col-span-1 sm:h-5">
              <Skeleton
                className={cn("absolute top-1/2 h-2.5 -translate-y-1/2", i % 3 === 1 ? "right-1/2" : "left-1/2")}
                style={{ width: `${Math.max(6, 46 - i * 3.4)}%` }}
              />
            </div>
            <Skeleton className="ml-auto h-4 w-9" />
          </div>
        ))}
        <div className="h-5.5" />
      </div>
    </div>
  );
}

