import { useMemo, type ReactElement } from "react";
import { useReducedMotion } from "motion/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type BarShapeProps,
} from "recharts";

import {
  CHART_COLORS,
  ChartTooltip,
  barTooltipProps,
  chartAnimation,
  gridProps,
  referenceLineProps,
  xAxisProps,
  yAxisProps,
} from "@/lib/chartTheme";
import { formatPercent, plural } from "@/lib/format";
import { GRADES, type Grade } from "@/lib/score";

import { GRADE_STACK, gradeRange, type Histogram, type HistogramBin } from "./insights";
import { LegendKey } from "./parts";

const GRADE_INFO = new Map(GRADES.map((g) => [g.grade, g]));
const X_TICKS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
/** Surface gap between stacked segments (px). */
const SEGMENT_GAP = 2;

export interface ScoreHistogramProps {
  histogram: Histogram;
  /** Mean score 0..100, marked with a reference line. */
  average?: number | null;
  height?: number;
}

function gradeColor(grade: Grade): string {
  return GRADE_INFO.get(grade)?.color ?? CHART_COLORS.neutral;
}

/**
 * One grade's share of a 10-point bin. The topmost segment of each bin gets the 4px rounded
 * cap; lower segments stay square and leave a 2px surface gap above them.
 */
function GradeSegment({ grade, ...props }: BarShapeProps & { grade: Grade }) {
  const { x, y, width, height, isActive } = props;
  const bin = props.payload as HistogramBin | undefined;
  if (!bin || bin[grade] === 0 || !Number.isFinite(x) || !Number.isFinite(y) || width <= 0 || height <= 0) {
    return <g />;
  }
  const isTop = bin.top === grade;
  const top = isTop ? y : y + Math.min(SEGMENT_GAP, height - 1);
  const h = y + height - top;
  const r = isTop ? Math.min(4, width / 2, h) : 0;
  const d =
    r > 0
      ? `M${x},${top + h}V${top + r}Q${x},${top} ${x + r},${top}H${x + width - r}Q${x + width},${top} ${x + width},${top + r}V${top + h}Z`
      : `M${x},${top + h}V${top}H${x + width}V${top + h}Z`;
  return <path d={d} fill={gradeColor(grade)} fillOpacity={isActive ? 1 : 0.85} />;
}

/** Scores in 10-point bins (0–100), each bin split by grade so the colours stay exact. */
export function ScoreHistogram({ histogram, average, height = 188 }: ScoreHistogramProps) {
  const reduced = useReducedMotion();
  const shapes = useMemo(
    () =>
      Object.fromEntries(
        GRADE_STACK.map((grade) => [grade, (props: BarShapeProps) => <GradeSegment {...props} grade={grade} />]),
      ) as Record<Grade, (props: BarShapeProps) => ReactElement>,
    [],
  );
  const maxCount = Math.max(1, ...histogram.bins.map((b) => b.total));
  const yTicks = maxCount <= 4 ? Array.from({ length: maxCount + 1 }, (_, i) => i) : undefined;

  const description = `Distribution of ${plural(histogram.total, "scored game")} by AI Score: ${histogram.grades
    .map((g) => `${g.grade} ${formatPercent(g.share)}`)
    .join(", ")}.`;

  return (
    <figure className="m-0 flex flex-col gap-3">
      <figcaption className="sr-only">{description}</figcaption>
      <GradeShares histogram={histogram} />
      <div style={{ height }} className="w-full min-w-0 [&_.recharts-surface]:outline-none">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={histogram.bins}
            margin={{ top: average !== null && average !== undefined ? 18 : 8, right: 12, bottom: 0, left: 0 }}
            barCategoryGap="14%"
            accessibilityLayer
          >
            <CartesianGrid {...gridProps} />
            <XAxis
              dataKey="mid"
              type="number"
              domain={[0, 100]}
              ticks={X_TICKS}
              interval="preserveStartEnd"
              {...xAxisProps}
              minTickGap={6}
            />
            <YAxis {...yAxisProps} allowDecimals={false} ticks={yTicks} width={28} />
            <Tooltip
              {...barTooltipProps}
              content={
                <ChartTooltip
                  labelFormatter={() => null}
                  renderBody={(datum) => <BinTooltipBody bin={datum as HistogramBin} total={histogram.total} />}
                />
              }
            />
            {GRADE_STACK.map((grade) => (
              <Bar
                key={grade}
                dataKey={grade}
                name={grade}
                stackId="grades"
                shape={shapes[grade]}
                activeBar={shapes[grade]}
                {...chartAnimation(reduced)}
              />
            ))}
            {average !== null && average !== undefined ? (
              <ReferenceLine
                x={average}
                {...referenceLineProps}
                stroke={CHART_COLORS.textSecondary}
                strokeOpacity={0.55}
                label={{
                  value: `avg ${Math.round(average)}`,
                  position: "top",
                  fill: CHART_COLORS.textSecondary,
                  fontSize: 11,
                  fontWeight: 600,
                }}
              />
            ) : null}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/** Compact score range for a grade chip: "80+", "65–79", "<35". */
function shortRange(grade: Grade): string {
  const { lo, hi } = gradeRange(grade);
  if (hi >= 100) return `${lo}+`;
  if (lo <= 0) return `<${hi + 1}`;
  return `${lo}–${hi}`;
}

/** Legend that doubles as the headline numbers: each grade's share of games and its score range. */
function GradeShares({ histogram }: { histogram: Histogram }) {
  return (
    <ul className="grid grid-cols-5 gap-1.5" aria-label="Share of games by grade">
      {histogram.grades.map((g) => {
        const range = gradeRange(g.grade);
        return (
          <li
            key={g.grade}
            className="flex min-w-0 flex-col gap-0.5 rounded-lg border border-border bg-surface-2/60 px-2 py-1.5"
            title={`${g.grade}: ${range.lo}–${range.hi}, ${plural(g.count, "game")}`}
          >
            <span className="flex items-center gap-1.5">
              <LegendKey color={gradeColor(g.grade)} mark="bar" />
              <span className="font-display text-xs font-bold text-text">{g.grade}</span>
            </span>
            <span className="font-display text-sm font-semibold tabular-nums text-text">{formatPercent(g.share)}</span>
            <span className="text-[11px] leading-4 whitespace-nowrap text-text-muted tabular-nums">
              <span className="sr-only">Scores </span>
              {shortRange(g.grade)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function BinTooltipBody({ bin, total }: { bin: HistogramBin; total: number }) {
  const rows = [...GRADE_STACK].reverse().filter((grade) => bin[grade] > 0);
  return (
    <div className="flex min-w-40 flex-col gap-1.5">
      <div className="font-medium text-text-secondary">
        Score {bin.lo}–{bin.hi}
      </div>
      {rows.length === 0 ? (
        <span className="text-text-muted">No games</span>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((grade) => (
            <li key={grade} className="flex items-center gap-2">
              <LegendKey color={gradeColor(grade)} mark="line" />
              <span className="font-display text-sm font-semibold tabular-nums text-text">{bin[grade]}</span>
              <span className="text-text-secondary">
                {grade} · {GRADE_INFO.get(grade)?.label}
              </span>
            </li>
          ))}
        </ul>
      )}
      {total > 0 ? (
        <div className="mt-0.5 border-t border-border pt-1.5 text-[11px] text-text-muted">
          {formatPercent(bin.total / total)} of {plural(total, "game")}
        </div>
      ) : null}
    </div>
  );
}
