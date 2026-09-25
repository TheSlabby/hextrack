import { Flame, Snowflake } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { streakInfo } from "@/lib/streaks";

export interface StreakBadgeProps {
  /** Results, newest first (true = win). */
  results: readonly boolean[];
  /** How many results the source can hold (see `PROFILE_FORM_LIMIT`), so a full list reads "10+". */
  limit: number;
  /** "md" shows the mood ("5W streak · On fire"); "sm" only the count, for dense rows. */
  size?: "sm" | "md";
  /**
   * Focusable pill with a tooltip. Turn off inside a link or other interactive element, where a
   * nested tab stop isn't allowed (the badge still reads as text there).
   */
  tooltip?: boolean;
  className?: string;
}

/** Flame / snowflake pill for a current streak of 3+; renders nothing for shorter runs. */
export function StreakBadge({ results, limit, size = "md", tooltip = true, className }: StreakBadgeProps) {
  const streak = streakInfo(results, limit);
  if (!streak) return null;
  const Icon = streak.win ? Flame : Snowflake;
  const text = size === "md" ? `${streak.short} · ${streak.mood}` : streak.short.replace(" streak", "");

  const pill = (
    <span
      tabIndex={tooltip ? 0 : undefined}
      aria-label={`${streak.description}: ${streak.mood}`}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border font-semibold whitespace-nowrap tabular-nums",
        tooltip && "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        size === "md" ? "h-6 px-2.5 text-xs" : "h-5 px-1.5 text-[11px]",
        streak.win ? "border-gold/45 bg-gold/10 text-gold-bright" : "border-loss/40 bg-loss/10 text-loss",
        className,
      )}
    >
      <Icon aria-hidden="true" className={cn(size === "md" ? "size-3.5" : "size-3", streak.win ? "text-gold" : "text-loss")} />
      {text}
    </span>
  );
  if (!tooltip) return pill;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{pill}</TooltipTrigger>
      <TooltipContent>
        {streak.description}. {streak.mood}
      </TooltipContent>
    </Tooltip>
  );
}
