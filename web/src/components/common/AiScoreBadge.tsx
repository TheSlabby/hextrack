import type { ReactNode } from "react";
import { Sparkles } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatSigned } from "@/lib/format";
import { AI_AVERAGE_NOTE, averageOffset, gradeForRate, toScore100 } from "@/lib/score";

export interface AiScoreBadgeProps {
  /** API score 0..1, or null when unscored. */
  score: number | null | undefined;
  /**
   * "game" (default): one game's score, with its letter grade. "average": a mean over many
   * games (season, roster, champion). Averages follow win rate closely, so they are shown as a
   * plain number in the AI accent, never graded.
   */
  kind?: "game" | "average";
  /**
   * @deprecated Match-wide AI rank. Rendered as a neutral "#N" only; MVP / ACE need both teams,
   * so rows that know the match use `AiScoreWithRank` (components/match/MatchBits) instead.
   */
  rank?: number | null;
  size?: "sm" | "md" | "lg";
  /** Show the letter grade next to the number (single games only). */
  showGrade?: boolean;
  /** Wrap in a tooltip explaining the score. */
  tooltip?: boolean;
  /** Extra tooltip line for averages, e.g. "Over 42 ranked games this season". */
  detail?: ReactNode;
  className?: string;
}

const SIZE = {
  sm: "h-5 gap-1 px-1.5 text-[11px]",
  md: "h-6 gap-1.5 px-2 text-xs",
  lg: "h-8 gap-2 px-3 text-sm",
} as const;

const ICON = { sm: "size-3", md: "size-3", lg: "size-3.5" } as const;

function withTooltip(pill: ReactNode, content: ReactNode, enabled: boolean) {
  if (!enabled) return pill;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{pill}</TooltipTrigger>
      <TooltipContent>{content}</TooltipContent>
    </Tooltip>
  );
}

/** AI Score pill: grade letter + 0-100 number for a game, or a plain number for an average. */
export function AiScoreBadge({
  score,
  kind = "game",
  rank,
  size = "md",
  showGrade = true,
  tooltip = true,
  detail,
  className,
}: AiScoreBadgeProps) {
  if (score === null || score === undefined) {
    const pill = (
      <span
        className={cn(
          "inline-flex items-center rounded-full border border-border bg-white/[0.03] font-semibold text-text-muted",
          SIZE[size],
          className,
        )}
        aria-label="AI Score not available"
      >
        <Sparkles className={ICON[size]} aria-hidden="true" />
        <span>–</span>
      </span>
    );
    return withTooltip(pill, "Not scored yet. Scores appear once an AI model is trained.", tooltip);
  }

  const value = toScore100(score);

  if (kind === "average") {
    const offset = averageOffset(score);
    const pill = (
      <span
        className={cn(
          "inline-flex items-center rounded-full border border-cyan/25 bg-cyan/[0.06] font-semibold text-text tabular-nums",
          SIZE[size],
          className,
        )}
        aria-label={`Average AI Score ${value}, ${formatSigned(offset)} versus a coin flip`}
      >
        <Sparkles className={cn(ICON[size], "text-cyan")} aria-hidden="true" />
        <span>{value}</span>
      </span>
    );
    return withTooltip(
      pill,
      <>
        <div className="flex items-baseline gap-2">
          <span className="font-display text-sm font-bold text-text tabular-nums">{value}</span>
          <span className="font-medium text-text">Average AI Score</span>
        </div>
        <p className="mt-0.5 text-text-secondary tabular-nums">
          {offset === 0 ? "Even with a coin flip (50)." : `${formatSigned(offset)} vs a coin flip (50).`}
          {detail ? <> {detail}</> : null}
        </p>
        <p className="mt-1 text-text-muted">{AI_AVERAGE_NOTE}</p>
      </>,
      tooltip,
    );
  }

  const grade = gradeForRate(score);
  const rankText = rank ? `#${rank}` : null;
  const pill = (
    <span
      className={cn(
        "inline-flex items-center rounded-full border font-semibold tabular-nums",
        grade.pillClass,
        SIZE[size],
        className,
      )}
      aria-label={`AI Score ${value}, grade ${grade.grade}${rankText ? `, ${rankText} of 10 in the match` : ""}`}
    >
      {showGrade ? <span className="font-display font-bold">{grade.grade}</span> : null}
      <span className={cn(showGrade && "text-text")}>{value}</span>
      {rankText ? (
        <span className="rounded-full bg-white/10 px-1 text-[10px] leading-3.5 font-bold text-text-secondary">
          {rankText}
        </span>
      ) : null}
    </span>
  );
  return withTooltip(
    pill,
    <>
      <div className="flex items-baseline gap-2">
        <span className={cn("font-display text-sm font-bold", grade.textClass)}>
          {grade.grade} · {value}
        </span>
        <span className="font-medium text-text">{grade.label}</span>
      </div>
      <p className="mt-0.5 text-text-secondary">{grade.description}</p>
    </>,
    tooltip,
  );
}
