/** Cells shared by the champion list table (desktop) and cards (phones). */
import type { ChampionRole, ChampionTier } from "@/api/types";
import { PositionIcon } from "@/components/common/PositionIcon";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatInteger, formatPercent } from "@/lib/format";
import { POSITION_LONG_LABELS } from "@/lib/positions";

import { SMALL_SAMPLE_GAMES, winRateClass } from "./ChampionListModel";
import { ChampionTierBadge } from "./ChampionTierBadge";

/** Win rate points either side of 50% that fill half the meter. */
const METER_SPAN = 0.08;

/** "52.4%" coloured against a coin flip, over a small meter centred on 50%. */
export function ChampionWinRate({ rate, className }: { rate: number; className?: string }) {
  const offset = Math.max(-1, Math.min(1, (rate - 0.5) / METER_SPAN));
  return (
    <span className={cn("inline-flex flex-col gap-1", className)}>
      <span className={cn("text-sm font-semibold tabular-nums", winRateClass(rate))}>{formatPercent(rate, 1)}</span>
      <span aria-hidden="true" className="relative h-1 w-14 overflow-hidden rounded-full bg-white/6">
        <span className="absolute inset-y-0 left-1/2 w-px bg-white/20" />
        <span
          className={cn("absolute inset-y-0 rounded-full", offset >= 0 ? "left-1/2 bg-win" : "right-1/2 bg-loss/85")}
          style={{ width: `${Math.abs(offset) * 50}%` }}
        />
      </span>
    </span>
  );
}

/** The champion's main roles, most played first; the filtered role is highlighted. */
export function ChampionRoleIcons({
  roles,
  active,
  className,
}: {
  roles: readonly ChampionRole[];
  active?: ChampionRole | null;
  className?: string;
}) {
  if (roles.length === 0) return <span className="text-xs text-text-muted">–</span>;
  return (
    <span className={cn("inline-flex items-center gap-1", className)} aria-label={`Main roles: ${roles.map((r) => POSITION_LONG_LABELS[r]).join(", ")}`}>
      {roles.map((role) => (
        <PositionIcon
          key={role}
          position={role}
          size={16}
          title=""
          className={role === active ? "text-gold-bright" : "text-text-secondary"}
        />
      ))}
    </span>
  );
}

/** The row's tier badge; with every role shown, the role it's for follows as a small icon. */
export function ChampionTierCell({
  tier,
  role,
  showRole,
  tooltip = true,
  className,
}: {
  tier: ChampionTier | null;
  role: ChampionRole | null;
  showRole: boolean;
  tooltip?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <ChampionTierBadge tier={tier} role={role} tooltip={tooltip} />
      {showRole && role ? (
        <PositionIcon position={role} size={14} title="" className="text-text-muted" />
      ) : null}
    </span>
  );
}

/** Games in the window; a small sample says so in a tooltip. */
export function ChampionGames({ games, smallSample, className }: { games: number; smallSample: boolean; className?: string }) {
  if (!smallSample) return <span className={cn("tabular-nums", className)}>{formatInteger(games)}</span>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn(
            "cursor-help rounded-sm tabular-nums underline decoration-dotted underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
            className,
          )}
        >
          {formatInteger(games)}
          <span className="sr-only"> (small sample)</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        Small sample: fewer than {SMALL_SAMPLE_GAMES} games in this window, so these rates can swing a lot.
      </TooltipContent>
    </Tooltip>
  );
}
