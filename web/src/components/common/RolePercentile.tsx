/**
 * Score within role: a quiet "Top 12% SUP" label for one game's AI Score, and a plain
 * "47th pct in role" for a player's average. Both explain themselves in a tooltip ("Better than 88% of scored
 * support games"). They render nothing when there is no percentile (unscored, remake, another
 * model version or an UNKNOWN position).
 */
import type { ReactNode } from "react";

import type { Position } from "@/api/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import {
  averagePercentileLabel,
  isKnownRole,
  ROLE_AVERAGE_MIN_GAMES,
  ROLE_GAMES,
  ROLE_PERCENTILE_AVERAGE_NOTE,
  ROLE_PERCENTILE_NOTE,
  ROLE_PLAYERS,
  ROLE_SHORT,
  roleStanding,
  type RoleStanding,
} from "@/lib/rolePercentile";

const SIZE = {
  xs: "text-[10px] leading-3",
  sm: "text-[11px] leading-4",
  md: "text-xs leading-4",
} as const;

/** The top tenth gets the AI accent; everything else stays neutral (the text carries the meaning). */
function toneClass(standing: RoleStanding): string {
  return standing.side === "top" && standing.share <= 10 ? "text-cyan" : "text-text-secondary";
}

function withTooltip(trigger: ReactNode, content: ReactNode, enabled: boolean) {
  if (!enabled) return trigger;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{trigger}</TooltipTrigger>
      <TooltipContent className="max-w-64">{content}</TooltipContent>
    </Tooltip>
  );
}

export interface RolePercentileLabelProps {
  /** `ai_role_percentile` (0..100); null / undefined renders nothing. */
  percentile: number | null | undefined;
  position: Position | null | undefined;
  /**
   * "short" (default): "Top 12% SUP" for dense rows. "long": "Top 12% of supports" where there
   * is room. "bare": "Top 12%" when the role is already shown next to it.
   */
  variant?: "short" | "long" | "bare";
  size?: keyof typeof SIZE;
  tooltip?: boolean;
  className?: string;
}

/** One game's AI Score against every scored game in the same role. */
export function RolePercentileLabel({
  percentile,
  position,
  variant = "short",
  size = "xs",
  tooltip = true,
  className,
}: RolePercentileLabelProps) {
  if (percentile === null || percentile === undefined || !isKnownRole(position)) return null;
  const standing = roleStanding(percentile);
  const games = ROLE_GAMES[position];
  const description = `Better than ${standing.betterThan}% of scored ${games}`;
  const label = (
    <span
      className={cn(
        "inline-flex items-baseline gap-1 font-semibold whitespace-nowrap tabular-nums",
        SIZE[size],
        toneClass(standing),
        className,
      )}
      aria-label={`${standing.label} in role: ${description.toLowerCase()}`}
    >
      <span>{standing.label}</span>
      {variant === "short" ? <span className="font-medium tracking-wide opacity-80">{ROLE_SHORT[position]}</span> : null}
      {variant === "long" ? <span className="font-medium">of {ROLE_PLAYERS[position]}</span> : null}
    </span>
  );
  return withTooltip(
    label,
    <>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-sm font-bold text-text tabular-nums">{standing.label}</span>
        <span className="font-medium text-text">of {games}</span>
      </div>
      <p className="mt-0.5 text-text-secondary">{description}.</p>
      <p className="mt-1 text-text-muted">{ROLE_PERCENTILE_NOTE}</p>
    </>,
    tooltip,
  );
}

export interface RolePercentileAverageProps {
  /** `avg_ai_role_percentile` (0..100); null / undefined renders nothing. */
  percentile: number | null | undefined;
  /** Scored games behind the average: the tooltip names them, and fewer than `minGames` marks
   * the label "small sample". */
  games?: number | null;
  /** Below this many games the average is a small sample (default: the leaderboard's 20). */
  minGames?: number;
  /** Tooltip line saying which games, e.g. "this season". */
  period?: string;
  /** Drop the trailing "in role" where a label next to it already says so. */
  bare?: boolean;
  size?: keyof typeof SIZE;
  tooltip?: boolean;
  className?: string;
}

/**
 * A player's mean role percentile as a plain number: "47th pct in role". Averages are not graded
 * (DESIGN.md), so there is no Top/Bottom wording and no accent colour.
 */
export function RolePercentileAverage({
  percentile,
  games,
  minGames = ROLE_AVERAGE_MIN_GAMES,
  period = "this season",
  bare = false,
  size = "sm",
  tooltip = true,
  className,
}: RolePercentileAverageProps) {
  if (percentile === null || percentile === undefined) return null;
  const value = averagePercentileLabel(percentile);
  const smallSample = games !== null && games !== undefined && games < minGames;
  const over = games ? `Over ${plural(games, "scored ranked game")} ${period}.` : null;
  const label = (
    <span
      className={cn(
        "inline-flex items-baseline gap-1 font-semibold whitespace-nowrap text-text-secondary tabular-nums",
        SIZE[size],
        smallSample && "text-text-muted",
        className,
      )}
      aria-label={`Average ${value.replace(" pct", " percentile")} in role${smallSample ? ", small sample" : ""}`}
    >
      {value}
      {bare ? null : <span className="font-medium opacity-80">in role</span>}
      {smallSample ? <span className="font-medium">· small sample</span> : null}
    </span>
  );
  return withTooltip(
    label,
    <>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-sm font-bold text-text tabular-nums">{value}</span>
        <span className="font-medium text-text">in role, on average</span>
      </div>
      <p className="mt-0.5 text-text-secondary">
        The average of this player&apos;s per-game role percentiles (50 is the middle).
        {over ? <> {over}</> : null}
        {smallSample ? <> Too few games to read much into it.</> : null}
      </p>
      <p className="mt-1 text-text-muted">{ROLE_PERCENTILE_AVERAGE_NOTE}</p>
    </>,
    tooltip,
  );
}
