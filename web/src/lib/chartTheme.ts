/**
 * Shared Recharts theme. Every chart imports its colours, grid/axis props and tooltip from
 * here so charts read as one system. Rules (see web/DESIGN.md → Charts):
 *   - one y-axis per chart, never dual-axis; recessive solid hairline grid, horizontal only
 *   - 2px lines, >= 8px active dots with a 2px surface ring, 10% area washes
 *   - bars <= 24px thick with 4px rounded data-ends, square at the baseline
 *   - text wears text tokens, never the series colour; always use <ChartTooltip />
 *
 * Categorical order is fixed (ai, lp, win, loss) and never cycles. The colours were stepped
 * from the brand accents and validated with the dataviz palette checker against surface-1
 * (#0d111a): lightness band, chroma floor, CVD separation (worst adjacent ΔE 12.1) and >= 3:1
 * contrast all pass.
 */
import type { CSSProperties } from "react";

import { MOTION, useEntranceMotion } from "@/lib/motion";

export { ChartTooltip, type ChartTooltipProps } from "@/components/charts/ChartTooltip";

export const CHART_COLORS = {
  surface: "#0d111a",
  grid: "rgba(255, 255, 255, 0.05)",
  axis: "#76829b",
  axisLine: "rgba(255, 255, 255, 0.08)",
  cursor: "rgba(255, 255, 255, 0.18)",
  cursorFill: "rgba(255, 255, 255, 0.03)",
  reference: "rgba(255, 255, 255, 0.16)",
  text: "#e8ecf4",
  textSecondary: "#9aa4b8",

  /** Named series (use these, in this order, for multi-series charts). */
  ai: "#0aa699",
  lp: "#b08a3a",
  win: "#4f8cff",
  loss: "#e5475a",

  /** Single-series accent lines may use the brand colours directly. */
  aiBright: "#0ac8b9",
  goldBright: "#c8aa6e",

  /** Diverging (attributions): helps win / neutral / hurts win. */
  positive: "#0aa699",
  neutral: "#5f6b82",
  negative: "#e5475a",
} as const;

export const CHART_FONT_SIZE = 11;

export const chartMargin = { top: 8, right: 12, bottom: 4, left: 0 } as const;
export const chartMarginCompact = { top: 4, right: 4, bottom: 0, left: 4 } as const;

/** <CartesianGrid {...gridProps} /> */
export const gridProps = {
  stroke: CHART_COLORS.grid,
  strokeWidth: 1,
  vertical: false,
} as const;

const tickStyle = {
  fill: CHART_COLORS.axis,
  fontSize: CHART_FONT_SIZE,
  fontFamily: "Inter Variable, ui-sans-serif, system-ui, sans-serif",
  fontVariantNumeric: "tabular-nums",
} as const;

/** <XAxis {...xAxisProps} dataKey="..." /> */
export const xAxisProps = {
  tick: tickStyle,
  tickLine: false,
  axisLine: { stroke: CHART_COLORS.axisLine },
  tickMargin: 8,
  minTickGap: 24,
} as const;

/** <YAxis {...yAxisProps} /> */
export const yAxisProps = {
  tick: tickStyle,
  tickLine: false,
  axisLine: false,
  tickMargin: 6,
  width: 40,
} as const;

/** <Tooltip {...tooltipProps} content={<ChartTooltip ... />} /> for line/area charts. */
export const tooltipProps = {
  cursor: { stroke: CHART_COLORS.cursor, strokeWidth: 1 },
  wrapperStyle: { outline: "none", zIndex: 20 } satisfies CSSProperties,
  isAnimationActive: false,
  offset: 12,
} as const;

/** Tooltip props for bar charts: a faint band highlights the hovered category. */
export const barTooltipProps = {
  ...tooltipProps,
  cursor: { fill: CHART_COLORS.cursorFill },
} as const;

/** <Line {...lineProps} stroke={...} /> */
export const lineProps = {
  type: "monotone",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  dot: false,
  activeDot: { r: 5, strokeWidth: 2, stroke: CHART_COLORS.surface },
} as const;

/** <Area {...areaProps} stroke={c} fill={`url(#id)`} />, pair with <AreaGradient />-style stops. */
export const areaProps = {
  ...lineProps,
  fillOpacity: 1,
} as const;

/** <Bar {...barProps} /> for vertical columns. */
export const barProps = {
  radius: [4, 4, 0, 0] as [number, number, number, number],
  maxBarSize: 24,
} as const;

/** <Bar {...horizontalBarProps} /> for horizontal bars (data end on the right). */
export const horizontalBarProps = {
  radius: [0, 4, 4, 0] as [number, number, number, number],
  maxBarSize: 20,
} as const;

/** <ReferenceLine {...referenceLineProps} y={50} /> */
export const referenceLineProps = {
  stroke: CHART_COLORS.reference,
  strokeWidth: 1,
  ifOverflow: "extendDomain",
} as const;

/** Gradient stops for a ~10% area wash fading to transparent. */
export function areaGradientStops(color: string, opacity = 0.14): ReadonlyArray<{ offset: string; color: string; opacity: number }> {
  return [
    { offset: "0%", color, opacity },
    { offset: "100%", color, opacity: 0 },
  ];
}

/** Animation props: pass `useReducedMotion()` from "motion/react", or use `useChartAnimation()`. */
export function chartAnimation(reducedMotion: boolean | null) {
  return reducedMotion
    ? ({ isAnimationActive: false } as const)
    : ({ isAnimationActive: true, animationDuration: MOTION.chartMs, animationEasing: "ease-out" } as const);
}

/**
 * Animation props for a chart: draws once on first paint, and renders finished under reduced
 * motion or when its section has already played its entrance (see lib/motion.ts).
 */
export function useChartAnimation() {
  return chartAnimation(!useEntranceMotion());
}

/** Colour for a diverging value (e.g. a feature attribution). */
export function divergingColor(value: number): string {
  if (value > 0) return CHART_COLORS.positive;
  if (value < 0) return CHART_COLORS.negative;
  return CHART_COLORS.neutral;
}
