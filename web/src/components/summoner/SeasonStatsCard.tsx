import type { ReactNode } from "react";
import { BarChart3 } from "lucide-react";

import type { ProfileStats } from "@/api/types";
import { EmptyState, GlowCard, SectionHeader, StatTile, WinRateBar } from "@/components/common";
import { cn } from "@/lib/cn";
import { formatAvgKdaLine, formatDecimal, formatInteger, formatRecord, formatShortDate } from "@/lib/format";

export interface SeasonStatsCardProps {
  stats: ProfileStats;
  /** Season start (ISO), from /meta. */
  seasonStart?: string | null;
  className?: string;
}

function Cell({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("min-w-0 rounded-xl border border-border bg-white/[0.02] px-3 py-2.5", className)}>{children}</div>;
}

const percent = (value: number) => `${Math.round(value)}%`;

/** Season aggregates over ranked queues: games, win rate, KDA and per-minute averages. */
export function SeasonStatsCard({ stats, seasonStart, className }: SeasonStatsCardProps) {
  const eyebrow = seasonStart ? `Ranked · since ${formatShortDate(seasonStart)}` : "Ranked this season";

  if (stats.games === 0) {
    return (
      <GlowCard className={cn("flex flex-col gap-2 p-4 sm:p-5", className)}>
        <SectionHeader title="Season stats" eyebrow={eyebrow} size="sm" />
        <EmptyState
          compact
          icon={BarChart3}
          title="No ranked games this season"
          description="Season stats cover Ranked Solo/Duo and Flex. They appear after the first ranked game."
        />
      </GlowCard>
    );
  }

  const perfect = stats.avg_deaths === 0;

  return (
    <GlowCard className={cn("flex flex-col gap-3 p-4 sm:p-5", className)}>
      <SectionHeader title="Season stats" eyebrow={eyebrow} size="sm" />

      <div className="grid grid-cols-3 gap-2">
        <Cell>
          <StatTile bare label="Games" value={stats.games} format={(v) => formatInteger(v)} caption={formatRecord(stats.wins, stats.losses)} />
        </Cell>
        <Cell>
          <StatTile bare label="Win rate" value={stats.winrate * 100} format={percent} />
        </Cell>
        <Cell>
          <StatTile
            bare
            label="KDA"
            value={perfect ? <span className="text-xl">Perfect</span> : stats.kda}
            format={(v) => formatDecimal(v, 2)}
          />
        </Cell>
      </div>

      <WinRateBar wins={stats.wins} losses={stats.losses} showLabels={false} size="sm" />

      <div className="grid grid-cols-2 gap-2">
        <Cell>
          <StatTile bare label="Kill part." value={stats.avg_kill_participation * 100} format={percent} />
        </Cell>
        <Cell>
          <StatTile bare label="CS / min" value={stats.avg_cs_per_min} format={(v) => formatDecimal(v, 1)} />
        </Cell>
        <Cell>
          <StatTile bare label="Damage / min" value={stats.avg_damage_per_min} format={(v) => formatInteger(v)} />
        </Cell>
        <Cell>
          <StatTile bare label="Vision / min" value={stats.avg_vision_per_min} format={(v) => formatDecimal(v, 2)} />
        </Cell>
      </div>

      <p className="flex items-center justify-between gap-2 text-xs text-text-secondary">
        <span className="label-caps">Avg K / D / A</span>
        <span className="font-medium tabular-nums text-text">
          {formatAvgKdaLine(stats.avg_kills, stats.avg_deaths, stats.avg_assists)}
        </span>
      </p>
    </GlowCard>
  );
}
