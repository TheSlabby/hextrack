import { Compass } from "lucide-react";

import type { RoleStat } from "@/api/types";
import { EmptyState, GlowCard, PositionIcon, SectionHeader } from "@/components/common";
import { cn } from "@/lib/cn";
import { formatPercent, plural } from "@/lib/format";
import { POSITION_LONG_LABELS, positionLabel } from "@/lib/positions";

export interface RolesCardProps {
  roles: readonly RoleStat[];
  className?: string;
}

/** Position split this season: share of games per role and the win rate on it. */
export function RolesCard({ roles, className }: RolesCardProps) {
  const played = roles.filter((role) => role.games > 0).sort((a, b) => b.games - a.games);
  const total = played.reduce((sum, role) => sum + role.games, 0);

  return (
    <GlowCard className={cn("flex flex-col gap-3 p-4 sm:p-5", className)}>
      <SectionHeader title="Roles" eyebrow="Share of ranked games" size="sm" />
      {played.length === 0 ? (
        <EmptyState compact icon={Compass} title="No roles yet" description="Roles appear after the first ranked game." />
      ) : (
        <ul className="flex flex-col gap-2.5" aria-label="Roles played">
          {played.map((role, index) => {
            const share = total > 0 ? role.games / total : 0;
            const main = index === 0;
            return (
              <li
                key={role.position}
                className="grid grid-cols-[28px_minmax(0,1fr)_44px] items-center gap-x-3"
              >
                <span className="sr-only">
                  {`${POSITION_LONG_LABELS[role.position]}: ${plural(role.games, "game")}, ${formatPercent(share)} of games, ${formatPercent(role.winrate)} win rate`}
                </span>
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex size-7 items-center justify-center rounded-lg border",
                    main ? "border-gold/30 bg-gold/10 text-gold" : "border-border bg-surface-2 text-text-secondary",
                  )}
                >
                  <PositionIcon position={role.position} size={16} title="" />
                </span>
                <span aria-hidden="true" className="flex min-w-0 flex-col gap-1">
                  <span className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="font-medium text-text">{positionLabel(role.position)}</span>
                    <span className="text-text-muted tabular-nums">
                      {formatPercent(share)} · {plural(role.games, "game")}
                    </span>
                  </span>
                  <span className="h-1.5 w-full overflow-hidden rounded-full bg-white/6">
                    <span
                      className={cn("block h-full rounded-full", main ? "bg-gold" : "bg-gold/45")}
                      style={{ width: `${Math.max(share * 100, 3)}%` }}
                    />
                  </span>
                </span>
                <span aria-hidden="true" className="flex flex-col items-end leading-tight">
                  <span
                    className={cn(
                      "text-xs font-semibold tabular-nums",
                      role.winrate >= 0.5 ? "text-text" : "text-text-secondary",
                    )}
                  >
                    {formatPercent(role.winrate)}
                  </span>
                  <span className="label-caps">WR</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </GlowCard>
  );
}
