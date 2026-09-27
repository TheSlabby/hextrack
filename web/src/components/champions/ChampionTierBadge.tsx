import type { ChampionRole, ChampionTier } from "@/api/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  CHAMPION_TIER_CLASS,
  CHAMPION_TIER_NOTE,
  CHAMPION_TIER_SUMMARY,
  championTierLabel,
} from "@/lib/championTiers";
import { cn } from "@/lib/cn";
import { POSITION_LONG_LABELS } from "@/lib/positions";

export interface ChampionTierBadgeProps {
  /** S..D; null = too few games in the role to rank (shows a dash). */
  tier: ChampionTier | null | undefined;
  /** The role the tier is for, named in the tooltip and label. */
  role?: ChampionRole | null;
  size?: "sm" | "md";
  /** Explain the tier on hover. Off inside links and buttons (no nested interactive content). */
  tooltip?: boolean;
  /** Make the badge a tab stop so keyboard users can open the tooltip. */
  focusable?: boolean;
  className?: string;
}

const SIZE = {
  sm: "size-5 rounded-[5px] text-[11px]",
  md: "size-7 rounded-md text-sm",
} as const;

/** Champion strength in a role as a letter tile: S gold, A teal, B blue, C grey, D red. */
export function ChampionTierBadge({
  tier,
  role,
  size = "sm",
  tooltip = true,
  focusable = false,
  className,
}: ChampionTierBadgeProps) {
  const label = tier ? championTierLabel(tier, role) : "Not ranked: too few games";
  const badge = (
    <span
      role="img"
      aria-label={label}
      tabIndex={tooltip && focusable ? 0 : undefined}
      className={cn(
        "inline-flex shrink-0 items-center justify-center border font-display leading-none font-bold select-none",
        SIZE[size],
        tier ? CHAMPION_TIER_CLASS[tier] : "border-border bg-white/[0.03] text-text-muted",
        tooltip && "cursor-help",
        tooltip && focusable && "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        className,
      )}
    >
      {tier ?? "–"}
    </span>
  );
  if (!tooltip) return badge;

  const where = role ? ` in ${POSITION_LONG_LABELS[role].toLowerCase()}` : "";
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent className="tracking-normal normal-case">
        <span className="flex flex-col gap-1">
          <span className="font-semibold text-text">
            {tier ? `${championTierLabel(tier, role)}: ${CHAMPION_TIER_SUMMARY[tier].toLowerCase()}${where}.` : `Not ranked${where}.`}
          </span>
          <span className="text-text-secondary">
            {tier ? CHAMPION_TIER_NOTE : "Too few games in this role for these patches to rank it against the others."}
          </span>
        </span>
      </TooltipContent>
    </Tooltip>
  );
}
