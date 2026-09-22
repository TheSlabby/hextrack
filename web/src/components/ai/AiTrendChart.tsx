import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDownRight, ArrowUpRight, ChartColumn, Minus, Sparkles, Table2 } from "lucide-react";
import { useReducedMotion } from "motion/react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  useActiveTooltipLabel,
  type BarShapeProps,
  type MouseHandlerDataParam,
} from "recharts";

import { useAiTrend } from "@/api/queries";
import {
  AiScoreBadge,
  ChampionIcon,
  EmptyState,
  ErrorState,
  GlowCard,
  SectionHeader,
} from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";
import {
  CHART_COLORS,
  ChartTooltip,
  chartAnimation,
  chartMargin,
  chartMarginCompact,
  gridProps,
  lineProps,
  referenceLineProps,
  tooltipProps,
  xAxisProps,
  yAxisProps,
} from "@/lib/chartTheme";
import { formatDate, formatShortDate, formatSigned, plural, timeAgo } from "@/lib/format";
import { gradeForScore, toScore100 } from "@/lib/score";
import { championDisplayName } from "@/lib/champions";

import { AiScoreExplainer } from "./AiScoreExplainer";
import {
  AI_TREND_LIMIT,
  ROLLING_WINDOW,
  buildTrendData,
  summarizeTrend,
  trendTicks,
  type TrendDatum,
  type TrendSummary,
} from "./insights";
import { ChartLegend, InlineStat, LegendKey, type LegendItem } from "./parts";

export interface AiTrendChartProps {
  puuid: string;
  /** Small variant for the profile overview: ~160px plot, minimal axes, no table view. */
  compact?: boolean;
  /**
   * Render without the card surface and title (legend, stats and chart only), for embedding
   * inside a card the page already owns. When the chart sits inside another GlowCard its own
   * card chrome also collapses automatically, so cards never nest.
   */
  bare?: boolean;
  className?: string;
}

const CHART_HEIGHT = { full: 248, compact: 160 } as const;
const ROLLING_LABEL = `${ROLLING_WINDOW}-game avg`;

const LEGEND: readonly LegendItem[] = [
  { label: "Win", color: CHART_COLORS.win, mark: "bar" },
  { label: "Loss", color: CHART_COLORS.loss, mark: "bar" },
  { label: ROLLING_LABEL, color: CHART_COLORS.ai, mark: "line" },
  { label: "50 = coin flip", color: CHART_COLORS.reference, mark: "reference" },
];

/** Card chrome that collapses when nested inside another GlowCard. */
const NESTED_RESET =
  "in-data-[slot=glow-card]:border-0 in-data-[slot=glow-card]:bg-none in-data-[slot=glow-card]:bg-transparent in-data-[slot=glow-card]:p-0 sm:in-data-[slot=glow-card]:p-0 in-data-[slot=glow-card]:shadow-none";

/**
 * Per-game AI Scores (oldest to newest) as win/loss-coloured columns, with a rolling
 * 10-game average and the 50 "coin flip" reference line. Click a column to open the match.
 */
export function AiTrendChart({ puuid, compact = false, bare = false, className }: AiTrendChartProps) {
  const query = useAiTrend(puuid, AI_TREND_LIMIT);
  const [view, setView] = useState<"chart" | "table">("chart");
  const points = query.data?.points;
  const data = useMemo(() => buildTrendData(points ?? []), [points]);
  const summary = useMemo(() => summarizeTrend(data), [data]);
  const height = compact ? CHART_HEIGHT.compact : CHART_HEIGHT.full;
  const hasData = data.length > 0;
  const showTable = !compact && view === "table" && hasData;

  let body: ReactNode;
  if (query.isPending) {
    body = <TrendSkeleton height={height} compact={compact} />;
  } else if (query.isError) {
    body = (
      <div className="flex items-center justify-center" style={{ minHeight: height }}>
        <ErrorState compact error={query.error} onRetry={() => void query.refetch()} title="Couldn't load AI Scores" />
      </div>
    );
  } else if (!hasData) {
    body = (
      <div className="flex items-center justify-center" style={{ minHeight: height }}>
        <EmptyState
          compact
          tone="ai"
          icon={Sparkles}
          title="No scored games yet"
          description={
            compact
              ? "AI Scores appear here once ranked games are scored."
              : "AI Scores appear here once this player's ranked games are scored by the model."
          }
        />
      </div>
    );
  } else {
    body = (
      <div
        className={cn("transition-opacity duration-200", query.isFetching && !query.isPending && "opacity-60")}
        aria-busy={query.isFetching}
      >
        {showTable ? (
          <TrendTable data={data} puuid={puuid} height={height} />
        ) : (
          <TrendPlot data={data} puuid={puuid} compact={compact} height={height} summary={summary} />
        )}
      </div>
    );
  }

  const header = compact ? (
    <CompactHeader summary={hasData ? summary : null} bare={bare} loading={query.isPending} />
  ) : (
    <FullHeader
      summary={hasData ? summary : null}
      bare={bare}
      loading={query.isPending}
      view={view}
      onViewChange={setView}
      canToggle={hasData}
    />
  );

  const content = (
    <div className={cn("flex min-w-0 flex-col", compact ? "gap-3" : "gap-4")}>
      {header}
      {body}
    </div>
  );

  if (bare) return <div className={cn("min-w-0", className)}>{content}</div>;
  return <GlowCard className={cn(compact ? "p-4 sm:p-5" : "p-5", NESTED_RESET, className)}>{content}</GlowCard>;
}

// --- headers ----------------------------------------------------------------------------

function CompactHeader({ summary, bare, loading }: { summary: TrendSummary | null; bare: boolean; loading: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {bare ? null : (
            <>
              <Sparkles className="size-4 shrink-0 text-cyan" aria-hidden="true" />
              <h3 className="truncate text-sm font-semibold text-text">AI Score trend</h3>
            </>
          )}
          {loading ? (
            <Skeleton className="h-5 w-16 rounded-full" aria-hidden="true" />
          ) : summary?.average !== null && summary?.average !== undefined ? (
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="hidden min-[400px]:inline">avg</span>
              <AiScoreBadge score={summary.average} kind="average" size="sm" />
            </span>
          ) : null}
        </div>
        <AiScoreExplainer />
      </div>
      {loading ? (
        <Skeleton className="h-4 w-44" aria-hidden="true" />
      ) : summary ? (
        <ChartLegend items={LEGEND.slice(0, 3)} className="gap-x-3 text-[11px]" />
      ) : null}
    </div>
  );
}

function FullHeader({
  summary,
  bare,
  loading,
  view,
  onViewChange,
  canToggle,
}: {
  summary: TrendSummary | null;
  bare: boolean;
  loading: boolean;
  view: "chart" | "table";
  onViewChange: (view: "chart" | "table") => void;
  canToggle: boolean;
}) {
  const actions = (
    <>
      <AiScoreExplainer />
      {canToggle ? (
        <ToggleGroup
          type="single"
          size="sm"
          value={view}
          onValueChange={(next) => {
            if (next === "chart" || next === "table") onViewChange(next);
          }}
          aria-label="Trend view"
          className="p-0.5"
        >
          <ToggleGroupItem value="chart" aria-label="Chart view" className="h-7 min-w-7 px-2">
            <ChartColumn aria-hidden="true" />
          </ToggleGroupItem>
          <ToggleGroupItem value="table" aria-label="Table view" className="h-7 min-w-7 px-2">
            <Table2 aria-hidden="true" />
          </ToggleGroupItem>
        </ToggleGroup>
      ) : null}
    </>
  );

  return (
    <div className="flex flex-col gap-4">
      {bare ? (
        <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div>
      ) : (
        <SectionHeader
          eyebrow="AI Score"
          title="Performance trend"
          description={
            summary
              ? `Last ${plural(summary.games, "scored game")}, oldest to newest.`
              : "Per-game AI Scores, oldest to newest."
          }
          action={actions}
        />
      )}
      {loading ? (
        <>
          <div
            className="grid grid-cols-3 gap-3 rounded-xl border border-border bg-surface-2/50 p-3 sm:gap-4 sm:px-4"
            aria-hidden="true"
          >
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="flex flex-col gap-1">
                <Skeleton className="my-0.5 h-3 w-16" />
                <Skeleton className="h-7 w-14" />
                <Skeleton className="my-0.5 h-3 w-20" />
              </div>
            ))}
          </div>
          <Skeleton className="h-4 w-64 max-w-full" aria-hidden="true" />
        </>
      ) : summary ? (
        <>
          <TrendStats summary={summary} />
          <ChartLegend items={LEGEND} />
        </>
      ) : null}
    </div>
  );
}

function TrendStats({ summary }: { summary: TrendSummary }) {
  const delta =
    summary.recent !== null && summary.previous !== null
      ? toScore100(summary.recent) - toScore100(summary.previous)
      : null;
  const DeltaIcon = delta === null || delta === 0 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
  const best = summary.best;

  return (
    <div className="grid grid-cols-3 gap-3 rounded-xl border border-border bg-surface-2/50 p-3 sm:gap-4 sm:px-4">
      <InlineStat label="Average" caption={`${summary.wins}W ${summary.games - summary.wins}L`}>
        <ScoreFigure rate={summary.average} />
      </InlineStat>
      <InlineStat
        label={`Last ${summary.recentGames}`}
        caption={
          delta !== null ? (
            <span className="inline-flex items-center gap-0.5">
              <DeltaIcon
                className={cn("size-3.5", delta > 0 ? "text-score-a" : delta < 0 ? "text-loss" : "text-text-muted")}
                aria-hidden="true"
              />
              <span className="tabular-nums text-text-secondary">{formatSigned(delta)}</span>
              <span className="hidden sm:inline">&nbsp;vs previous {summary.previousGames}</span>
            </span>
          ) : (
            "Not enough games to compare"
          )
        }
      >
        <ScoreFigure rate={summary.recent} />
      </InlineStat>
      <InlineStat label="Best game" caption={best ? championDisplayName(best.champion) : undefined}>
        {best ? (
          <>
            <ScoreFigure rate={best.rate} />
            <ChampionIcon champion={best.champion} size="xs" className="ml-0.5" />
          </>
        ) : (
          <span className="text-text-muted">–</span>
        )}
      </InlineStat>
    </div>
  );
}

/** Number + grade letter, the way scores read everywhere in the AI views. */
function ScoreFigure({ rate }: { rate: number | null }) {
  if (rate === null) return <span className="font-display text-xl leading-7 font-semibold text-text-muted">–</span>;
  const score = toScore100(rate);
  const grade = gradeForScore(score);
  return (
    <span className="flex items-baseline gap-1" aria-label={`${score}, grade ${grade.grade}`}>
      <span className="font-display text-xl leading-7 font-semibold tabular-nums text-text">{score}</span>
      <span className={cn("font-display text-sm font-bold", grade.textClass)}>{grade.grade}</span>
    </span>
  );
}

// --- plot -------------------------------------------------------------------------------

const COARSE_QUERY = "(pointer: coarse)";

function subscribeCoarse(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => undefined;
  const media = window.matchMedia(COARSE_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/** True on touch-first devices (drives the tooltip hint copy). */
function useCoarsePointer(): boolean {
  return useSyncExternalStore(
    subscribeCoarse,
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(COARSE_QUERY).matches : false),
    () => false,
  );
}

/** Column with a 4px rounded data end and a square baseline, coloured by result. */
function TrendBar(props: BarShapeProps) {
  const { x, y, width, height, isActive } = props;
  const datum = props.payload as TrendDatum | undefined;
  if (!datum || !Number.isFinite(x) || !Number.isFinite(y) || width <= 0 || height <= 0) return <g />;
  const r = Math.min(4, width / 2, height);
  const fill = datum.win ? CHART_COLORS.win : CHART_COLORS.loss;
  const d = `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
  return <path d={d} fill={fill} fillOpacity={isActive ? 1 : 0.78} className="transition-[fill-opacity] duration-150" />;
}

interface EndLabelProps {
  x?: number | string;
  y?: number | string;
  index?: number;
  value?: unknown;
}

function TrendPlot({
  data,
  puuid,
  compact,
  height,
  summary,
}: {
  data: TrendDatum[];
  puuid: string;
  compact: boolean;
  height: number;
  summary: TrendSummary;
}) {
  const reduced = useReducedMotion();
  const navigate = useNavigate();
  const lastIndex = data.length - 1;

  const tickLabel = useCallback((d: TrendDatum) => formatShortDate(d.gameStart), []);
  const ticks = useMemo(() => (compact ? [] : trendTicks(data, 5, tickLabel)), [compact, data, tickLabel]);

  // On touch, the first tap on a column shows its tooltip; a second tap on it opens the match.
  const pointerType = useRef<string>("mouse");
  const armedIndex = useRef<number | null>(null);
  const coarse = useCoarsePointer();
  // Game under the keyboard cursor (Recharts' accessibility layer moves it with the arrow keys).
  const activeGame = useRef<number | null>(null);
  const onActiveLabel = useCallback((label: unknown) => {
    const value = typeof label === "number" ? label : typeof label === "string" ? Number(label) : Number.NaN;
    activeGame.current = Number.isInteger(value) ? value : null;
  }, []);

  const goTo = useCallback(
    (datum: TrendDatum) => {
      void navigate({ to: "/match/$matchId", params: { matchId: datum.matchId }, search: { player: puuid } });
    },
    [navigate, puuid],
  );

  const openMatch = useCallback(
    (state: MouseHandlerDataParam) => {
      const index = Number(state.activeTooltipIndex);
      const datum = Number.isInteger(index) ? data[index] : undefined;
      if (!datum) return;
      if (pointerType.current === "touch" && armedIndex.current !== index) {
        armedIndex.current = index;
        return;
      }
      armedIndex.current = null;
      goTo(datum);
    },
    [data, goTo],
  );

  const renderEndLabel = useCallback(
    ({ x, y, index, value }: EndLabelProps) => {
      if (index !== lastIndex || typeof value !== "number") return <g />;
      return (
        <text
          x={Number(x) + 8}
          y={Number(y)}
          dy={4}
          fill={CHART_COLORS.text}
          fontSize={11}
          fontWeight={600}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {Math.round(value)}
        </text>
      );
    },
    [lastIndex],
  );

  const latest = data[lastIndex];
  const description = [
    `AI Score over the last ${plural(data.length, "scored game")}, oldest to newest.`,
    summary.average !== null ? `Average ${toScore100(summary.average)}.` : "",
    latest ? `Latest game: ${latest.score} on ${championDisplayName(latest.champion)}, ${latest.win ? "a win" : "a loss"}.` : "",
    latest?.rolling !== null && latest?.rolling !== undefined ? `Current ${ROLLING_LABEL}: ${Math.round(latest.rolling)}.` : "",
    "Focus the chart and use the arrow keys to step through games; press Enter to open one.",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <figure className="m-0 flex flex-col gap-1.5">
      <figcaption className="sr-only">{description}</figcaption>
      <div
        style={{ height }}
        className="w-full min-w-0 [&_.recharts-surface]:rounded-md [&_.recharts-surface:focus:not(:focus-visible)]:outline-none"
        onPointerDown={(event) => {
          pointerType.current = event.pointerType;
        }}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          const datum = activeGame.current !== null ? data[activeGame.current - 1] : undefined;
          if (!datum) return;
          event.preventDefault();
          goTo(datum);
        }}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={data}
            margin={compact ? { ...chartMarginCompact, top: 6, right: 6 } : { ...chartMargin, right: 30 }}
            barCategoryGap={compact ? "16%" : "22%"}
            onClick={openMatch}
            style={{ cursor: "pointer" }}
            accessibilityLayer
          >
            <CartesianGrid {...gridProps} />
            <XAxis
              dataKey="index"
              {...xAxisProps}
              hide={compact}
              ticks={ticks}
              interval={0}
              tickFormatter={(value: number) => {
                const datum = data[value - 1];
                return datum ? formatShortDate(datum.gameStart) : "";
              }}
            />
            <YAxis
              {...yAxisProps}
              domain={[0, 100]}
              ticks={compact ? [0, 50, 100] : [0, 25, 50, 75, 100]}
              width={compact ? 26 : 34}
            />
            <Tooltip
              {...tooltipProps}
              content={
                <ChartTooltip
                  labelFormatter={() => null}
                  renderBody={(datum) => <TrendTooltipBody datum={datum as TrendDatum} />}
                  footer={coarse ? "Tap again to open the match" : "Click to open the match"}
                />
              }
            />
            <ActiveLabelBridge onChange={onActiveLabel} />
            <ReferenceLine y={50} {...referenceLineProps} />
            <Bar
              dataKey="score"
              name="AI Score"
              shape={TrendBar}
              activeBar={TrendBar}
              maxBarSize={compact ? 14 : 18}
              minPointSize={2}
              {...chartAnimation(reduced)}
            />
            {/* Surface-coloured halo keeps the average legible where it crosses columns. */}
            <Line
              dataKey="rolling"
              {...lineProps}
              stroke={CHART_COLORS.surface}
              strokeWidth={5}
              strokeOpacity={0.85}
              activeDot={false}
              tooltipType="none"
              legendType="none"
              connectNulls={false}
              {...chartAnimation(reduced)}
            />
            <Line
              dataKey="rolling"
              name={ROLLING_LABEL}
              {...lineProps}
              stroke={CHART_COLORS.ai}
              activeDot={{ ...lineProps.activeDot, fill: CHART_COLORS.ai }}
              connectNulls={false}
              label={compact ? false : renderEndLabel}
              {...chartAnimation(reduced)}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {compact ? (
        <div className="flex justify-between pl-[30px] text-[11px] text-text-muted">
          <span>{plural(data.length, "game")} ago</span>
          <span>Latest</span>
        </div>
      ) : null}
    </figure>
  );
}

/** Reports the chart's active x label (hover or keyboard) to the parent. Renders nothing. */
function ActiveLabelBridge({ onChange }: { onChange: (label: unknown) => void }) {
  const label = useActiveTooltipLabel();
  useEffect(() => {
    onChange(label);
  }, [label, onChange]);
  return null;
}

function TrendTooltipBody({ datum }: { datum: TrendDatum }) {
  const grade = gradeForScore(datum.score);
  return (
    <div className="flex w-56 flex-col gap-2.5">
      <div className="flex items-center gap-2.5">
        <ChampionIcon champion={datum.champion} size="sm" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[13px] font-semibold text-text">{championDisplayName(datum.champion)}</span>
          <span className="truncate text-[11px] text-text-muted">
            {formatShortDate(datum.gameStart)} · {timeAgo(datum.gameStart)}
          </span>
        </div>
        <Badge variant={datum.win ? "win" : "loss"}>{datum.win ? "Victory" : "Defeat"}</Badge>
      </div>
      <div className="flex items-end justify-between gap-3 border-t border-border pt-2">
        <div className="flex items-baseline gap-1.5">
          <span className="font-display text-2xl leading-none font-semibold tabular-nums text-text">{datum.score}</span>
          <span className={cn("font-display text-sm font-bold", grade.textClass)}>{grade.grade}</span>
          <span className="text-text-secondary">{grade.label}</span>
        </div>
      </div>
      {datum.rolling !== null ? (
        <div className="flex items-center gap-2">
          <LegendKey color={CHART_COLORS.ai} mark="line" />
          <span className="font-display text-sm font-semibold tabular-nums text-text">{Math.round(datum.rolling)}</span>
          <span className="text-text-secondary">{ROLLING_LABEL}</span>
        </div>
      ) : null}
    </div>
  );
}

// --- table view -------------------------------------------------------------------------

function TrendTable({ data, puuid, height }: { data: TrendDatum[]; puuid: string; height: number }) {
  const rows = useMemo(() => [...data].reverse(), [data]);
  return (
    <div className="overflow-auto rounded-xl border border-border scrollbar-thin" style={{ height }}>
      <table className="w-full text-sm tabular-nums">
        <caption className="sr-only">AI Score per game, newest first</caption>
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr className="border-b border-border text-left">
            {["Game", "Champion", "Result", "AI Score", ROLLING_LABEL].map((heading, i) => (
              <th
                key={heading}
                scope="col"
                className={cn(
                  "h-9 px-3 text-[11px] font-semibold tracking-[0.08em] whitespace-nowrap text-text-muted uppercase",
                  i >= 3 && "text-right",
                )}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((datum) => (
            <tr key={datum.matchId} className="transition-colors hover:bg-white/[0.025]">
              <td className="px-3 py-2 whitespace-nowrap text-text-secondary">
                <span title={formatDate(datum.gameStart)}>{timeAgo(datum.gameStart)}</span>
              </td>
              <td className="px-3 py-2">
                <Link
                  to="/match/$matchId"
                  params={{ matchId: datum.matchId }}
                  search={{ player: puuid }}
                  className="inline-flex items-center gap-2 rounded-md font-medium whitespace-nowrap text-text hover:text-gold-bright"
                >
                  <ChampionIcon champion={datum.champion} size="xs" />
                  {championDisplayName(datum.champion)}
                </Link>
              </td>
              <td className="px-3 py-2">
                <Badge variant={datum.win ? "win" : "loss"}>{datum.win ? "Win" : "Loss"}</Badge>
              </td>
              <td className="px-3 py-2 text-right">
                <AiScoreBadge score={datum.rate} size="sm" tooltip={false} />
              </td>
              <td className="px-3 py-2 text-right text-text-secondary">
                {datum.rolling !== null ? Math.round(datum.rolling) : "–"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- loading ----------------------------------------------------------------------------

/** Column skeleton at the final plot height, so nothing shifts when data arrives. */
function TrendSkeleton({ height, compact }: { height: number; compact: boolean }) {
  const bars = compact ? 24 : 32;
  const plot = compact ? height : height - 24;
  return (
    <div role="status" aria-label="Loading AI Scores" className="flex flex-col gap-1.5">
      <div className="relative w-full" style={{ height }}>
        <div className="absolute inset-0 flex flex-col justify-between" style={{ height: plot }} aria-hidden="true">
          {Array.from({ length: compact ? 3 : 5 }, (_, i) => (
            <div key={i} className="h-px w-full bg-white/[0.04]" />
          ))}
        </div>
        <div
          className={cn("absolute right-0 bottom-0 flex items-end gap-[3px]", compact ? "left-7" : "left-9")}
          style={{ height: plot, bottom: compact ? 0 : 24 }}
          aria-hidden="true"
        >
          {Array.from({ length: bars }, (_, i) => (
            <Skeleton
              key={i}
              className="flex-1 rounded-t-[4px] rounded-b-none opacity-70"
              style={{ height: `${30 + ((i * 37) % 55)}%` }}
            />
          ))}
        </div>
      </div>
      {compact ? <div className="h-4" aria-hidden="true" /> : null}
    </div>
  );
}
