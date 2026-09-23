/**
 * Binned diverging colour scales for the squad grids.
 *
 * Both grids colour a polarity around a baseline, so each uses two opposite hues with a
 * neutral grey midpoint and three equal steps per arm (7 classes, each named in a legend):
 *
 * - Duo synergy: win rate together minus the pair's expected win rate. Blue arm (the app's
 *   win colour) = better together, red arm (loss) = worse together.
 * - Who carries whom: share of shared games where the row player had the higher AI Score,
 *   around 50%. Teal arm (the AI colour) = outscored more often, red arm = less often.
 *
 * The steps hold each pole's OKLCH hue and chroma ratio and step lightness evenly
 * (L 0.39 / 0.46 / 0.52, ΔL >= 0.06), checked with the dataviz ramp validator against the
 * card surface #0d111a: lightness monotone, single hue, adjacent ΔL >= 0.06. The palest step
 * sits at ~1.9-2.0:1 against the surface on purpose (it means "barely different"), and every
 * cell prints its value, which is the required relief channel. Cell text (#e8ecf4) keeps
 * >= 4.6:1 on every step.
 */

export type Bin = -3 | -2 | -1 | 0 | 1 | 2 | 3;
export type Arm = "win" | "ai";

export const SCALE_COLORS = {
  neutral: "#242932",
  win: ["#2a4577", "#30559a", "#3765bc"],
  ai: ["#184e48", "#0e625a", "#00776d"],
  loss: ["#712d32", "#91323c", "#b13946"],
} as const;

/** Background colour for a bin on the given positive arm. */
export function binColor(bin: Bin, arm: Arm): string {
  if (bin === 0) return SCALE_COLORS.neutral;
  const steps = bin > 0 ? SCALE_COLORS[arm] : SCALE_COLORS.loss;
  return steps[Math.abs(bin) - 1] ?? SCALE_COLORS.neutral;
}

function binFromPoints(points: number, edges: readonly [number, number, number]): Bin {
  const magnitude = Math.abs(points);
  const step = magnitude >= edges[2] ? 3 : magnitude >= edges[1] ? 2 : magnitude >= edges[0] ? 1 : 0;
  return (points < 0 ? -step : step) as Bin;
}

/** Synergy edges in win-rate points: |delta| < 2 neutral, 2-5, 5-10, 10+. */
export const SYNERGY_EDGES = [2, 5, 10] as const;
/** Carry edges in points away from 50%: |share - 50| < 5 neutral, 5-10, 10-20, 20+. */
export const CARRY_EDGES = [5, 10, 20] as const;

/** winrate_delta (0..1 scale) -> bin. */
export function synergyBin(delta: number): Bin {
  return binFromPoints(Math.round(delta * 1000) / 10, SYNERGY_EDGES);
}

/** Share of games the row player outscored the column player (0..1) -> bin. */
export function carryBin(share: number): Bin {
  return binFromPoints(Math.round((share - 0.5) * 1000) / 10, CARRY_EDGES);
}

export const BINS: readonly Bin[] = [-3, -2, -1, 0, 1, 2, 3];
