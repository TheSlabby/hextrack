import { useId, useMemo, useState } from "react";
import { useReducedMotion } from "motion/react";
import { ArrowDownRight, ArrowUpRight, Crown, LineChart } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type XAxisTickContentProps,
  type YAxisTickContentProps,
} from "recharts";

import { useMeta, useRankHistory } from "@/api/queries";
import type { QueueType, SummonerProfile } from "@/api/types";
import { EmptyState, ErrorState, GlowCard, SectionHeader, SkeletonChart, TierBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  CHART_COLORS,
  ChartTooltip,
  areaGradientStops,
  areaProps,
  chartAnimation,
  gridProps,
  tooltipProps,
  xAxisProps,
  yAxisProps,
} from "@/lib/chartTheme";
import { cn } from "@/lib/cn";
import { formatDate, formatDateTime, formatLpDelta, formatRecord, plural } from "@/lib/format";
import { QUEUE_TYPE_LABELS } from "@/lib/queues";
import { TIER_COLORS, formatRank } from "@/lib/tiers";

import { useMediaQuery } from "@/lib/hooks";
import {
  gapDays,
  lpScale,
  lpSummary,
  lpTickLabel,
  pointLabel,
  sinceLabel,
  sinceSeason,
  timeTicks,
  toLpData,
  toLpRows,
  type LpDatum,
  type LpRow,
} from "./lpChartModel";

const CHART_HEIGHT = 240;
const LINE_COLOR = CHART_COLORS.goldBright;

type RangeId = "season" | "all";

const RANGE_OPTIONS: ReadonlyArray<{ value: RangeId; label: string; title: string }> = [
  { value: "season", label: "Season", title: "This season" },
  { value: "all", label: "All", title: "All recorded history" },
];

function isRangeId(value: string): value is RangeId {
  return value === "season" || value === "all";
}

const QUEUE_OPTIONS: ReadonlyArray<{ value: QueueType; label: string }> = [
  { value: "RANKED_SOLO_5x5", label: "Solo/Duo" },
  { value: "RANKED_FLEX_SR", label: "Flex" },
];

function isQueueType(value: string): value is QueueType {
  return value === "RANKED_SOLO_5x5" || value === "RANKED_FLEX_SR";
}

export interface LpJourneyCardProps {
  profile: SummonerProfile;
}

/** Overview card: rank_value over time for Solo/Duo or Flex, with tier bands and boundaries. */
export function LpJourneyCard({ profile }: LpJourneyCardProps) {
  const [queue, setQueue] = useState<QueueType>(
    profile.solo || !profile.flex ? "RANKED_SOLO_5x5" : "RANKED_FLEX_SR",
  );
  const [range, setRange] = useState<RangeId>("season");
  const history = useRankHistory(profile.puuid, queue);
  const meta = useMeta();
  const all = useMemo(() => toLpData(history.data?.points ?? []), [history.data]);
  const season = useMemo(() => sinceSeason(all, meta.data?.season_start), [all, meta.data?.season_start]);
  // Seasons reset LP, so the default view starts at the season; older runs stay behind "All".
  const hasOlder = season.length < all.length;
  const data = range === "season" && hasOlder ? season : all;
  const summary = lpSummary(data);
  const current = queue === "RANKED_SOLO_5x5" ? profile.solo : profile.flex;
  const scopedToSeason = data === season && hasOlder;

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader
        title="LP journey"
        eyebrow={QUEUE_TYPE_LABELS[queue]}
        icon={LineChart}
        action={
          <>
            {hasOlder ? (
              <ToggleGroup
                type="single"
                size="sm"
                value={range}
                onValueChange={(value) => {
                  if (isRangeId(value)) setRange(value);
                }}
                aria-label="Time range"
              >
                {RANGE_OPTIONS.map((option) => (
                  <ToggleGroupItem key={option.value} value={option.value} aria-label={option.title}>
                    {option.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            ) : null}
            <ToggleGroup
              type="single"
              size="sm"
              value={queue}
              onValueChange={(value) => {
                if (isQueueType(value)) setQueue(value);
              }}
              aria-label="Ranked queue"
            >
              {QUEUE_OPTIONS.map((option) => (
                <ToggleGroupItem key={option.value} value={option.value} aria-label={QUEUE_TYPE_LABELS[option.value]}>
                  {option.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </>
        }
      />

      <div className="flex min-h-6 flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-text-secondary">
        {current ? <TierBadge entry={current} size="sm" /> : <TierBadge tier={null} size="sm" />}
        {summary && data.length > 1 ? (
          <>
            <span className="inline-flex items-center gap-1 tabular-nums">
              {summary.net >= 0 ? (
                <ArrowUpRight className="size-3.5 text-score-a" aria-hidden="true" />
              ) : (
                <ArrowDownRight className="size-3.5 text-loss" aria-hidden="true" />
              )}
              <span className="font-semibold text-text">{formatLpDelta(summary.net)}</span>
              <span>{scopedToSeason ? "this season" : `since ${sinceLabel(summary.first.t)}`}</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <Crown className="size-3.5 text-gold" aria-hidden="true" />
              <span>
                Peak <span className="font-semibold text-text">{pointLabel(summary.peak.point)}</span>
              </span>
            </span>
          </>
        ) : null}
      </div>

      <div style={{ minHeight: CHART_HEIGHT }} className="flex flex-col justify-center">
        {history.isPending ? (
          <SkeletonChart height={CHART_HEIGHT} />
        ) : history.isError ? (
          <ErrorState compact error={history.error} title="Couldn't load rank history" onRetry={() => void history.refetch()} />
        ) : data.length < 2 ? (
          <EmptyState
            compact
            icon={LineChart}
            title={
              data.length === 0
                ? scopedToSeason
                  ? "No LP history this season"
                  : "No LP history yet"
                : "The journey starts here"
            }
            description={
              data.length === 0
                ? scopedToSeason
                  ? `No ${QUEUE_TYPE_LABELS[queue]} snapshot since the season started. Earlier seasons are under "All".`
                  : `HexTrack records a rank snapshot whenever ${QUEUE_TYPE_LABELS[queue]} LP changes. Play a few ranked games and hit Update.`
                : `One snapshot so far (${pointLabel(data[0]!.point)} on ${formatDate(data[0]!.t)}). The chart fills in as LP changes.`
            }
            action={
              scopedToSeason && all.length > 1 ? (
                <Button variant="outline" size="sm" onClick={() => setRange("all")}>
                  Show all history
                </Button>
              ) : null
            }
          />
        ) : (
          <LpChart data={data} queue={queue} />
        )}
      </div>
    </GlowCard>
  );
}

function LpChart({ data, queue }: { data: LpDatum[]; queue: QueueType }) {
  const gradientId = `lp-wash-${useId().replace(/:/g, "")}`;
  const reduced = useReducedMotion();
  const wide = useMediaQuery("(min-width: 640px)");
  const scale = useMemo(() => lpScale(data, wide ? 6 : 5), [data, wide]);
  // Weeks without a snapshot break the line, so sparse histories don't draw invented climbs.
  const rows = useMemo(() => toLpRows(data), [data]);
  const first = data[0]!;
  const last = data[data.length - 1]!;
  const x = useMemo(() => timeTicks(first.t, last.t, wide ? 6 : 3), [first.t, last.t, wide]);
  const summary = lpSummary(data)!;

  const description =
    `${QUEUE_TYPE_LABELS[queue]} LP journey: from ${pointLabel(first.point)} on ${formatDate(first.t)} ` +
    `to ${pointLabel(last.point)} on ${formatDate(last.t)}, peak ${pointLabel(summary.peak.point)}.`;

  return (
    <figure className="m-0">
      <div role="img" aria-label={description} style={{ height: CHART_HEIGHT }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                {areaGradientStops(LINE_COLOR, 0.16).map((stop) => (
                  <stop key={stop.offset} offset={stop.offset} stopColor={stop.color} stopOpacity={stop.opacity} />
                ))}
              </linearGradient>
            </defs>

            {scale.bands.map((band) => (
              <ReferenceArea
                key={`${band.tier}-${band.from}`}
                y1={band.from}
                y2={band.to}
                fill={band.color}
                fillOpacity={0.035}
                stroke="none"
                ifOverflow="hidden"
              />
            ))}

            <CartesianGrid {...gridProps} />

            {scale.boundaries.map((boundary) => (
              <ReferenceLine
                key={boundary.value}
                y={boundary.value}
                stroke={boundary.color}
                strokeOpacity={0.45}
                strokeWidth={1}
                ifOverflow="hidden"
                label={{
                  value: boundary.label,
                  position: labelSide(boundary.value, first.value, last.value, scale.domain),
                  fill: boundary.labelColor,
                  fontSize: 11,
                  fontWeight: 600,
                  offset: 6,
                }}
              />
            ))}

            <XAxis
              {...xAxisProps}
              dataKey="t"
              type="number"
              scale="time"
              domain={[first.t, last.t]}
              ticks={x.ticks}
              interval={0}
              minTickGap={8}
              tick={(props: XAxisTickContentProps) => (
                <EdgeTick {...props} label={x.format(Number(props.payload.value))} min={first.t} max={last.t} />
              )}
            />
            <YAxis
              {...yAxisProps}
              type="number"
              domain={scale.domain}
              ticks={scale.ticks}
              interval={0}
              allowDataOverflow
              width={wide ? 92 : 36}
              tick={(props: YAxisTickContentProps) => (
                <YTick {...props} label={lpTickLabel(Number(props.payload.value), !wide)} />
              )}
            />

            <Tooltip
              {...tooltipProps}
              content={
                <ChartTooltip
                  labelFormatter={(label, entries) => {
                    const row = entries[0]?.payload as LpRow | undefined;
                    if (row?.gap) return "No snapshots";
                    return typeof label === "number" ? formatDateTime(label) : null;
                  }}
                  renderBody={(datum) => <LpTooltipBody row={datum as LpRow} />}
                />
              }
            />

            {/* The dashed hint spans each gap; it sits under the solid line, which breaks there. */}
            <Line
              type="monotone"
              dataKey="bridge"
              name="No snapshots"
              stroke={LINE_COLOR}
              strokeOpacity={0.45}
              strokeWidth={1.5}
              strokeDasharray="3 4"
              dot={false}
              activeDot={false}
              legendType="none"
              {...chartAnimation(reduced)}
            />

            <Area
              {...areaProps}
              dataKey="value"
              name="Rank"
              stroke={LINE_COLOR}
              fill={`url(#${gradientId})`}
              baseValue={scale.domain[0]}
              dot={(props: LpDotProps) => <IsolatedDot {...props} />}
              {...chartAnimation(reduced)}
            />

            <ReferenceDot
              x={last.t}
              y={last.value}
              r={4}
              fill={LINE_COLOR}
              stroke={CHART_COLORS.surface}
              strokeWidth={2}
              ifOverflow="visible"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <LpTable data={data} queue={queue} />
    </figure>
  );
}

/**
 * Boundary labels sit at the right end of their line unless the latest point is right there
 * (then the line would run through the text), in which case they move to the left end.
 */
function labelSide(boundary: number, firstValue: number, lastValue: number, domain: [number, number]) {
  const near = (value: number) => Math.abs(value - boundary) < (domain[1] - domain[0]) * 0.18;
  return near(lastValue) && !near(firstValue) ? ("insideBottomLeft" as const) : ("insideBottomRight" as const);
}

const TICK_TEXT = {
  fill: CHART_COLORS.axis,
  fontSize: 11,
  fontFamily: "Inter Variable, ui-sans-serif, system-ui, sans-serif",
  style: { fontVariantNumeric: "tabular-nums" },
} as const;

/** X tick whose first/last labels anchor inward so they are never clipped at the plot edges. */
function EdgeTick({ x, y, payload, label, min, max }: XAxisTickContentProps & { label: string; min: number; max: number }) {
  const value = Number(payload.value);
  const position = max > min ? (value - min) / (max - min) : 0.5;
  const anchor = position <= 0.06 ? "start" : position >= 0.94 ? "end" : "middle";
  return (
    <text x={Number(x)} y={Number(y)} dy={12} textAnchor={anchor} {...TICK_TEXT}>
      {label}
    </text>
  );
}

/** Single-line y tick (Recharts' default <Text> wraps long labels like "Platinum III"). */
function YTick({ x, y, label }: YAxisTickContentProps & { label: string }) {
  return (
    <text x={Number(x)} y={Number(y)} dy={4} textAnchor="end" {...TICK_TEXT}>
      {label}
    </text>
  );
}

/** Recharts only draws a line between neighbouring points, so a lone snapshot needs its own dot. */
interface LpDotProps {
  cx?: number;
  cy?: number;
  index?: number;
  payload?: LpRow;
}

function IsolatedDot({ cx, cy, payload, index }: LpDotProps) {
  if (!payload?.isolated || cx === undefined || cy === undefined) return <g key={`dot-${index ?? 0}`} />;
  return (
    <circle
      key={`dot-${index ?? 0}`}
      cx={cx}
      cy={cy}
      r={3}
      fill={LINE_COLOR}
      stroke={CHART_COLORS.surface}
      strokeWidth={2}
    />
  );
}

function LpTooltipBody({ row }: { row: LpRow }) {
  if (row.gap) {
    return (
      <div className="flex flex-col gap-1 text-text-secondary">
        <span className="font-medium text-text">{plural(gapDays(row.gap), "day")} without a snapshot</span>
        <span className="tabular-nums">
          {formatDate(row.gap.from)} – {formatDate(row.gap.to)}
        </span>
      </div>
    );
  }
  const point = row.point;
  if (!point) return null;
  const delta = row.delta;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="h-0.5 w-3 shrink-0 rounded-full" style={{ backgroundColor: TIER_COLORS[point.tier] }} />
        <span className="font-display text-sm font-semibold tabular-nums text-text">{formatRank(point)}</span>
      </div>
      <div className="flex items-center gap-3 pl-5 text-text-secondary tabular-nums">
        {delta !== null ? (
          <span className={cn("font-semibold", delta > 0 ? "text-score-a" : delta < 0 ? "text-loss" : "text-text-muted")}>
            {formatLpDelta(delta)}
          </span>
        ) : null}
        <span>{formatRecord(point.wins, point.losses)}</span>
      </div>
    </div>
  );
}

/** Screen-reader table twin of the chart (latest snapshots first). */
function LpTable({ data, queue }: { data: LpDatum[]; queue: QueueType }) {
  const rows = data.slice(-30).reverse();
  return (
    <div className="sr-only">
      <table>
        <caption>
          {QUEUE_TYPE_LABELS[queue]} rank snapshots, newest first ({plural(rows.length, "snapshot")} of {data.length})
        </caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Rank</th>
            <th scope="col">Change</th>
            <th scope="col">Record</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={`${d.t}-${d.value}`}>
              <td>{formatDateTime(d.t)}</td>
              <td>{formatRank(d.point)}</td>
              <td>{d.delta === null ? "–" : formatLpDelta(d.delta)}</td>
              <td>{formatRecord(d.point.wins, d.point.losses)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
