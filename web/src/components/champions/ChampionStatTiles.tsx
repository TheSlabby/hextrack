import { Coins, Crosshair, Hourglass, Swords, Wheat } from "lucide-react";

import type { ChampionRoleStats } from "@/api/types";
import { SkeletonCard, SkeletonStatTile } from "@/components/common/Skeletons";
import { StatTile } from "@/components/common/StatTile";
import { formatAvgKdaLine, formatDuration, formatInteger, formatKdaRatio } from "@/lib/format";

const GRID = "grid grid-cols-2 gap-3 md:grid-cols-5 [&>*:last-child]:col-span-2 md:[&>*:last-child]:col-span-1";

/** Per-game averages for the champion in the selected role. */
export function ChampionStatTiles({ stats }: { stats: ChampionRoleStats }) {
  return (
    <div className={GRID}>
      <StatTile
        label="KDA"
        icon={Swords}
        value={formatKdaRatio(stats.kda)}
        caption={formatAvgKdaLine(stats.avg_kills, stats.avg_deaths, stats.avg_assists)}
      />
      <StatTile label="Damage" icon={Crosshair} value={formatInteger(stats.avg_damage)} caption="To champions, per game" />
      <StatTile
        label="CS / min"
        icon={Wheat}
        value={stats.cs_per_min.toFixed(1)}
        caption={`${formatInteger(stats.avg_cs)} CS per game`}
      />
      <StatTile label="Gold" icon={Coins} value={formatInteger(stats.avg_gold)} caption="Earned per game" />
      <StatTile label="Game length" icon={Hourglass} value={formatDuration(stats.avg_duration_s)} caption="Average" />
    </div>
  );
}

/** Placeholder for the page body under the header, sized like the real sections. */
export function ChampionDetailSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading champion">
      <div className={GRID}>
        {Array.from({ length: 5 }, (_, i) => (
          <SkeletonStatTile key={i} />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <SkeletonCard lines={6} height={420} />
        <SkeletonCard lines={6} height={420} />
      </div>
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        <SkeletonCard lines={3} />
        <SkeletonCard lines={3} />
        <SkeletonCard lines={3} className="md:col-span-2 xl:col-span-1" />
      </div>
    </div>
  );
}
