import type { ReactNode } from "react";

import type { ChampionDetail } from "@/api/types";
import { SkeletonCard } from "@/components/common/Skeletons";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatAvgKdaLine, formatDuration, formatInteger, formatKdaRatio } from "@/lib/format";
import { POSITION_LABELS } from "@/lib/positions";

import { pct, winRateTone } from "./detailModel";

const GRID = "grid grid-cols-3 gap-x-3 gap-y-4 sm:grid-cols-5 lg:grid-cols-9";

function Stat({ label, value, caption, className }: { label: string; value: ReactNode; caption?: ReactNode; className?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="label-caps truncate">{label}</dt>
      <dd className={cn("font-display text-xl leading-tight font-semibold tabular-nums text-text", className)}>{value}</dd>
      {caption ? <dd className="truncate text-[11px] text-text-muted tabular-nums">{caption}</dd> : null}
    </div>
  );
}

/**
 * Every headline number for the selected role in one strip: win / pick / ban rate and games,
 * then per-game KDA, damage, CS, gold and game length.
 */
export function ChampionStatStrip({ detail }: { detail: ChampionDetail | undefined }) {
  if (!detail) {
    return (
      <div className={cn(GRID, "rounded-2xl border border-border bg-surface-1/75 p-4")} aria-hidden="true">
        {Array.from({ length: 9 }, (_, i) => (
          <div key={i} className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-14" />
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>
    );
  }
  const stats = detail.detail?.stats;
  const role = detail.role ? POSITION_LABELS[detail.role] : "All roles";
  const winRate = stats?.win_rate ?? detail.win_rate;
  return (
    <dl className={cn(GRID, "rounded-2xl border border-border bg-surface-1/75 p-4 backdrop-blur-sm")}>
      <Stat
        label="Win rate"
        value={winRate === null ? "–" : pct(winRate)}
        caption={role}
        className={winRate === null ? undefined : winRateTone(winRate)}
      />
      <Stat label="Pick rate" value={pct(stats?.pick_rate ?? detail.pick_rate)} caption={role} />
      <Stat label="Ban rate" value={pct(detail.ban_rate)} caption="All roles" />
      <Stat
        label="Games"
        value={formatInteger(stats?.games ?? detail.games)}
        caption={stats && detail.games > stats.games ? `of ${formatInteger(detail.games)}` : "counted"}
      />
      {stats ? (
        <>
          <Stat
            label="KDA"
            value={formatKdaRatio(stats.kda)}
            caption={formatAvgKdaLine(stats.avg_kills, stats.avg_deaths, stats.avg_assists)}
          />
          <Stat label="Damage" value={formatInteger(stats.avg_damage)} caption="to champs / game" />
          <Stat label="CS / min" value={stats.cs_per_min.toFixed(1)} caption={`${formatInteger(stats.avg_cs)} per game`} />
          <Stat label="Gold" value={formatInteger(stats.avg_gold)} caption="per game" />
          <Stat label="Length" value={formatDuration(stats.avg_duration_s)} caption="average game" />
        </>
      ) : null}
    </dl>
  );
}

/** Placeholder for the Build tab, shaped like the real layout. */
export function ChampionBuildSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" role="status" aria-label="Loading champion">
      <div className="flex flex-col gap-4">
        <SkeletonCard lines={8} height={460} />
        <SkeletonCard lines={2} height={130} />
      </div>
      <div className="flex flex-col gap-4">
        <SkeletonCard lines={4} height={260} />
        <SkeletonCard lines={5} height={300} />
      </div>
    </div>
  );
}
