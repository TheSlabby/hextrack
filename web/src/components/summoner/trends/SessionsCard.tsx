/**
 * Tilt detector: win rate and average AI Score by game number within a play session, plus
 * the record after a win / a loss / a losing streak, with a one-line verdict.
 */
import { useMemo, useState, type ReactNode } from "react";
import { ChartColumn, Gauge, Info, Minus, Table2, TrendingDown, TrendingUp } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type DotItemDotProps,
  type XAxisTickContentProps,
} from "recharts";

import { useSessionInsights } from "@/api/queries";
import type { SessionGameBucket, SessionInsights, SessionStateBucket } from "@/api/types";
import { ChartLegend, LegendKey, type LegendItem } from "@/components/ai/parts";
import { EmptyState, ErrorState, GlowCard, SectionHeader, SkeletonChart } from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";
import {
  CHART_COLORS,
  CHART_FONT_SIZE,
  ChartTooltip,
  chartMargin,
  gridProps,
  lineProps,
  referenceLineProps,
  tooltipProps,
  useChartAnimation,
  yAxisProps,
} from "@/lib/chartTheme";
import { formatDecimal, formatPercent, formatRecord, formatSigned, plural } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";

import {
  SESSION_STATE_LABELS,
  VERDICT_MIN_GAMES,
  aiPoints,
  gameNumberLabel,
  gamesPhrase,
  pct,
  sessionVerdict,
  type SessionVerdict,
  type TrendsFilters,
} from "./model";
import { FigurePanel, Refetching } from "./parts";

const CHART_HEIGHT = 232;

const LEGEND: readonly LegendItem[] = [
  { label: "Win rate", color: CHART_COLORS.win, mark: "line" },
  { label: "Avg AI Score", color: CHART_COLORS.ai, mark: "line" },
  { label: "50 = coin flip", color: CHART_COLORS.reference, mark: "reference" },
];

export interface SessionsCardProps {
  puuid: string;
  filters: TrendsFilters;
}

export function SessionsCard({ puuid, filters }: SessionsCardProps) {
  const query = useSessionInsights(puuid, filters);
  const [view, setView] = useState<"chart" | "table">("chart");
  const data = query.data;
  const hasGames = (data?.games ?? 0) > 0;

  let body: ReactNode;
  if (query.isPending) {
    body = <SessionsSkeleton />;
  } else if (query.isError) {
    body = <ErrorState compact error={query.error} title="Couldn't load sessions" onRetry={() => void query.refetch()} />;
  } else if (!data || !hasGames) {
    body = (
      <EmptyState
        compact
        icon={Gauge}
        title="No sessions to read yet"
        description={`No ${gamesPhrase(filters)} stored for this player.`}
      />
    );
  } else {
    body = (
      <Refetching active={query.isPlaceholderData}>
        <SessionsBody data={data} view={view} />
      </Refetching>
    );
  }

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader
        eyebrow="Tilt detector"
        title="Win rate through a session"
        icon={Gauge}
        description={
          data && hasGames
            ? `Sessions split after ${data.gap_minutes} minutes idle. ${plural(data.sessions, "session")}, ${formatDecimal(data.avg_session_games)} games on average, longest ${data.longest_session_games}.`
            : `Sessions split after ${data?.gap_minutes ?? 45} minutes idle.`
        }
        action={
          hasGames ? (
            <ToggleGroup
              type="single"
              size="sm"
              value={view}
              onValueChange={(next) => {
                if (next === "chart" || next === "table") setView(next);
              }}
              aria-label="Session view"
              className="p-0.5"
            >
              <ToggleGroupItem value="chart" aria-label="Chart view" className="h-7 min-w-7 px-2">
                <ChartColumn aria-hidden="true" />
              </ToggleGroupItem>
              <ToggleGroupItem value="table" aria-label="Table view" className="h-7 min-w-7 px-2">
                <Table2 aria-hidden="true" />
              </ToggleGroupItem>
            </ToggleGroup>
          ) : null
        }
      />
      {body}
    </GlowCard>
  );
}

// --- body -------------------------------------------------------------------------------

function SessionsBody({ data, view }: { data: SessionInsights; view: "chart" | "table" }) {
  const verdict = useMemo(() => sessionVerdict(data.by_game_number), [data.by_game_number]);
  const minGames = data.min_games;

  return (
    <div className="flex flex-col gap-4">
      <VerdictLine verdict={verdict} />
      {view === "chart" ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <ChartLegend items={LEGEND} />
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span aria-hidden="true" className="size-2 rounded-full border-2 border-text-muted" />
              Faint, hollow: under {minGames} games
            </span>
          </div>
          <SessionChart buckets={data.by_game_number} minGames={minGames} />
        </div>
      ) : (
        <SessionTable buckets={data.by_game_number} minGames={minGames} />
      )}
      <StateTiles states={data.by_state} minGames={minGames} />
    </div>
  );
}

function VerdictLine({ verdict }: { verdict: SessionVerdict | null }) {
  const Icon = !verdict ? Info : verdict.kind === "drop" ? TrendingDown : verdict.kind === "rise" ? TrendingUp : Minus;
  const tone = !verdict
    ? "text-text-muted"
    : verdict.kind === "drop"
      ? "text-loss"
      : verdict.kind === "rise"
        ? "text-win"
        : "text-text-secondary";
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-border bg-surface-2/50 px-3 py-2.5">
      <Icon className={cn("mt-0.5 size-4 shrink-0", tone)} aria-hidden="true" />
      <p className="text-sm text-text">
        {verdict ? (
          <>
            {verdict.text}{" "}
            <span className="text-text-muted tabular-nums">
              ({verdict.first.games} vs {plural(verdict.later.games, "game")})
            </span>
          </>
        ) : (
          <span className="text-text-secondary">
            Not enough games for a verdict yet: it needs {VERDICT_MIN_GAMES} first games of a session and{" "}
            {VERDICT_MIN_GAMES} at a later game number.
          </span>
        )}
      </p>
    </div>
  );
}

// --- chart ------------------------------------------------------------------------------

interface SessionDatum {
  n: number;
  label: string;
  games: number;
  wins: number;
  winrate: number | null;
  ai: number | null;
  /** The same values, but null for small samples: drawn as the solid line on top. */
  winrateSolid: number | null;
  aiSolid: number | null;
  small: boolean;
}

function toDatum(bucket: SessionGameBucket, minGames: number): SessionDatum {
  const winrate = bucket.games > 0 ? bucket.winrate * 100 : null;
  const ai = bucket.avg_ai_score !== null ? bucket.avg_ai_score * 100 : null;
  const small = bucket.games < minGames;
  return {
    n: bucket.n,
    label: gameNumberLabel(bucket.n),
    games: bucket.games,
    wins: bucket.wins,
    winrate,
    ai,
    winrateSolid: small ? null : winrate,
    aiSolid: small ? null : ai,
    small,
  };
}

/** Fixed 30..70 window (the interesting band around a coin flip), widened to fit the data. */
function yScale(values: number[]): { domain: [number, number]; ticks: number[] } {
  const lo = Math.max(0, Math.floor(Math.min(30, ...values) / 10) * 10);
  const hi = Math.min(100, Math.ceil(Math.max(70, ...values) / 10) * 10);
  if (hi - lo > 60) return { domain: [0, 100], ticks: [0, 25, 50, 75, 100] };
  const ticks: number[] = [];
  for (let t = lo; t <= hi; t += 10) ticks.push(t);
  return { domain: [lo, hi], ticks };
}

/**
 * Point markers: the faint full-range line draws hollow dots for small samples, the solid
 * line filled dots for the rest, so every point is marked exactly once.
 */
function dotRenderer(color: string, key: "winrate" | "ai", layer: "faint" | "solid") {
  return function SessionDot(props: DotItemDotProps) {
    const { cx, cy, index } = props;
    const datum = props.payload as SessionDatum | undefined;
    const id = `${key}-${layer}-${index}`;
    if (typeof cx !== "number" || typeof cy !== "number" || !datum || datum[key] === null) return <g key={id} />;
    if (layer === "faint") {
      return datum.small ? (
        <circle key={id} cx={cx} cy={cy} r={3.5} fill={CHART_COLORS.surface} stroke={color} strokeWidth={2} />
      ) : (
        <g key={id} />
      );
    }
    if (datum.small) return <g key={id} />;
    return <circle key={id} cx={cx} cy={cy} r={4} fill={color} stroke={CHART_COLORS.surface} strokeWidth={2} />;
  };
}

function SessionChart({ buckets, minGames }: { buckets: readonly SessionGameBucket[]; minGames: number }) {
  const animation = useChartAnimation();
  const wide = useMediaQuery("(min-width: 640px)");
  const data = useMemo(() => buckets.map((bucket) => toDatum(bucket, minGames)), [buckets, minGames]);
  const { domain, ticks } = useMemo(
    () =>
      yScale(
        data.flatMap((datum) => [datum.winrate, datum.ai]).filter((value): value is number => value !== null),
      ),
    [data],
  );

  const description = data
    .filter((datum) => datum.games > 0)
    .map(
      (datum) =>
        `Game ${datum.label}: ${Math.round(datum.winrate ?? 0)}% win rate over ${plural(datum.games, "game")}${datum.ai !== null ? `, average AI Score ${Math.round(datum.ai)}` : ""}.`,
    )
    .join(" ");

  const renderTick = (props: XAxisTickContentProps) => {
    const datum = data[props.payload.index];
    if (!datum) return <g />;
    return (
      <g transform={`translate(${Number(props.x)},${Number(props.y)})`}>
        <text
          dy={12}
          textAnchor="middle"
          fill={CHART_COLORS.textSecondary}
          fontSize={CHART_FONT_SIZE}
          fontWeight={600}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {wide ? `Game ${datum.label}` : datum.label}
        </text>
        <text dy={27} textAnchor="middle" fill={CHART_COLORS.axis} fontSize={CHART_FONT_SIZE} style={{ fontVariantNumeric: "tabular-nums" }}>
          {wide ? plural(datum.games, "game") : datum.games}
        </text>
      </g>
    );
  };

  return (
    <figure className="m-0 flex flex-col gap-1">
      <figcaption className="sr-only">Win rate and average AI Score by game number in a session. {description}</figcaption>
      <div style={{ height: CHART_HEIGHT }} className="w-full min-w-0" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ ...chartMargin, top: 12, right: 16, left: 4 }}>
            <CartesianGrid {...gridProps} />
            <XAxis
              dataKey="label"
              tick={renderTick}
              tickLine={false}
              axisLine={{ stroke: CHART_COLORS.axisLine }}
              interval={0}
              height={40}
              padding={{ left: 18, right: 18 }}
            />
            <YAxis {...yAxisProps} width={34} domain={domain} ticks={ticks} allowDataOverflow={false} />
            <ReferenceLine y={50} {...referenceLineProps} />
            <Tooltip
              {...tooltipProps}
              content={<ChartTooltip labelFormatter={() => null} renderBody={(datum) => <SessionTooltip datum={datum as SessionDatum} minGames={minGames} />} />}
            />
            {/* Faint lines through every point; small samples only get these and a hollow dot. */}
            <Line
              dataKey="winrate"
              name="Win rate"
              {...lineProps}
              type="linear"
              stroke={CHART_COLORS.win}
              strokeOpacity={0.35}
              dot={dotRenderer(CHART_COLORS.win, "winrate", "faint")}
              activeDot={{ ...lineProps.activeDot, fill: CHART_COLORS.win }}
              connectNulls={false}
              {...animation}
            />
            <Line
              dataKey="ai"
              name="Avg AI Score"
              {...lineProps}
              type="linear"
              stroke={CHART_COLORS.ai}
              strokeOpacity={0.35}
              dot={dotRenderer(CHART_COLORS.ai, "ai", "faint")}
              activeDot={{ ...lineProps.activeDot, fill: CHART_COLORS.ai }}
              connectNulls={false}
              {...animation}
            />
            <Line
              dataKey="winrateSolid"
              {...lineProps}
              type="linear"
              stroke={CHART_COLORS.win}
              dot={dotRenderer(CHART_COLORS.win, "winrate", "solid")}
              activeDot={false}
              tooltipType="none"
              legendType="none"
              connectNulls={false}
              {...animation}
            />
            <Line
              dataKey="aiSolid"
              {...lineProps}
              type="linear"
              stroke={CHART_COLORS.ai}
              dot={dotRenderer(CHART_COLORS.ai, "ai", "solid")}
              activeDot={false}
              tooltipType="none"
              legendType="none"
              connectNulls={false}
              {...animation}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {wide ? null : <p className="text-[11px] text-text-muted">Game number in a session, with games played below.</p>}
    </figure>
  );
}

function SessionTooltip({ datum, minGames }: { datum: SessionDatum; minGames: number }) {
  return (
    <div className="flex w-48 flex-col gap-1.5">
      <span className="font-medium text-text-secondary">
        {datum.n >= 6 ? "Game 6 or later" : `Game ${datum.n}`} in a session
      </span>
      {datum.games === 0 ? (
        <span className="text-text-muted">No games</span>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <LegendKey color={CHART_COLORS.win} mark="line" />
            <span className="font-display text-sm font-semibold tabular-nums text-text">{Math.round(datum.winrate ?? 0)}%</span>
            <span className="text-text-secondary">win rate</span>
          </div>
          <div className="flex items-center gap-2">
            <LegendKey color={CHART_COLORS.ai} mark="line" />
            <span className="font-display text-sm font-semibold tabular-nums text-text">
              {datum.ai !== null ? Math.round(datum.ai) : "–"}
            </span>
            <span className="text-text-secondary">{datum.ai !== null ? "avg AI Score" : "not scored"}</span>
          </div>
          <span className="border-t border-border pt-1.5 text-[11px] text-text-muted tabular-nums">
            {plural(datum.games, "game")} · {formatRecord(datum.wins, datum.games - datum.wins)}
            {datum.small ? ` · small sample (under ${minGames})` : ""}
          </span>
        </>
      )}
    </div>
  );
}

// --- table ------------------------------------------------------------------------------

function SessionTable({ buckets, minGames }: { buckets: readonly SessionGameBucket[]; minGames: number }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border scrollbar-thin">
      <table className="w-full text-sm tabular-nums">
        <caption className="sr-only">Win rate and average AI Score by game number in a session</caption>
        <thead className="bg-surface-2">
          <tr className="border-b border-border text-left">
            {["Game", "Games", "Record", "Win rate", "Avg AI"].map((heading, i) => (
              <th
                key={heading}
                scope="col"
                className={cn(
                  "h-9 px-3 text-[11px] font-semibold tracking-[0.08em] whitespace-nowrap text-text-muted uppercase",
                  i >= 1 && "text-right",
                )}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {buckets.map((bucket) => {
            const small = bucket.games < minGames;
            return (
              <tr key={bucket.n} className={cn(small && "text-text-muted")}>
                <th scope="row" className="px-3 py-2 text-left font-medium whitespace-nowrap">
                  Game {gameNumberLabel(bucket.n)}
                </th>
                <td className="px-3 py-2 text-right">{bucket.games}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">{formatRecord(bucket.wins, bucket.games - bucket.wins)}</td>
                <td className={cn("px-3 py-2 text-right font-semibold", small ? "text-text-muted" : "text-text")}>
                  {bucket.games > 0 ? formatPercent(bucket.winrate) : "–"}
                </td>
                <td className="px-3 py-2 text-right">{aiPoints(bucket.avg_ai_score) ?? "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// --- streak states ----------------------------------------------------------------------

function StateTiles({ states, minGames }: { states: readonly SessionStateBucket[]; minGames: number }) {
  const totals = states.reduce((acc, state) => ({ games: acc.games + state.games, wins: acc.wins + state.wins }), {
    games: 0,
    wins: 0,
  });
  const overall = totals.games > 0 ? totals.wins / totals.games : null;

  return (
    <section aria-label="Record by what happened just before" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="label-caps">Just before the game</h3>
        {overall !== null ? (
          <span className="text-xs text-text-muted tabular-nums">Overall {formatPercent(overall)}</span>
        ) : null}
      </div>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {states.map((state) => {
          const small = state.games < minGames;
          const delta = !small && overall !== null ? pct(state.winrate) - pct(overall) : null;
          const ai = aiPoints(state.avg_ai_score);
          return (
            <li key={state.state} title={SESSION_STATE_LABELS[state.state].description}>
              <FigurePanel
                label={SESSION_STATE_LABELS[state.state].label}
                muted={small}
                value={
                  <span className="flex items-baseline gap-1.5">
                    {state.games > 0 ? formatPercent(state.winrate) : "–"}
                    {delta !== null && delta !== 0 ? (
                      <span className={cn("font-sans text-xs font-semibold", delta > 0 ? "text-score-a" : "text-loss")}>
                        {formatSigned(delta)}
                      </span>
                    ) : null}
                  </span>
                }
                caption={
                  <>
                    {plural(state.games, "game")}
                    {state.games > 0 ? ` · ${ai !== null ? `AI ${ai}` : "not scored"}` : ""}
                    {small && state.games > 0 ? " · small sample" : ""}
                  </>
                }
                className={cn("h-full", small && "opacity-70")}
              />
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-text-muted">
        Win rate in each situation, with the difference from the overall rate in points. Streaks only count earlier games of
        the same session.
      </p>
    </section>
  );
}

// --- loading ----------------------------------------------------------------------------

function SessionsSkeleton() {
  return (
    <div className="flex flex-col gap-4" role="status" aria-label="Loading sessions">
      <Skeleton className="h-10 w-full rounded-xl" />
      <Skeleton className="h-4 w-64 max-w-full" />
      <SkeletonChart height={CHART_HEIGHT} />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-[5.5rem] rounded-xl" />
        ))}
      </div>
    </div>
  );
}
