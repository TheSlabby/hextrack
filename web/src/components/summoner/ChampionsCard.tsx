import { Swords } from "lucide-react";

import type { ChampionStat } from "@/api/types";
import { AiScoreBadge, ChampionIcon, EmptyState, GlowCard, SectionHeader, WinRateBar } from "@/components/common";
import { cn } from "@/lib/cn";
import { formatDecimal, formatPercent, plural } from "@/lib/format";
import { championDisplayName } from "@/lib/champions";


export interface ChampionsCardProps {
  champions: readonly ChampionStat[];
  className?: string;
}

const GRID = "grid grid-cols-[32px_minmax(0,1fr)_52px_38px_48px] items-center gap-x-3";

/** Most played champions this season: games, win rate bar, KDA and average AI Score. */
export function ChampionsCard({ champions, className }: ChampionsCardProps) {
  return (
    <GlowCard className={cn("flex flex-col gap-3 p-4 sm:p-5", className)}>
      <SectionHeader title="Champions" eyebrow="Most played · ranked" size="sm" />
      {champions.length === 0 ? (
        <EmptyState compact icon={Swords} title="No champions yet" description="Play a ranked game to see champion stats." />
      ) : (
        <div role="table" aria-label="Most played champions" className="flex flex-col">
          <div role="row" className={cn(GRID, "pb-1.5")}>
            <span role="columnheader">
              <span className="sr-only">Icon</span>
            </span>
            <span role="columnheader" className="label-caps">
              Champion
            </span>
            <span role="columnheader" className="label-caps">
              WR
            </span>
            <span role="columnheader" className="label-caps text-right">
              KDA
            </span>
            <span role="columnheader" className="label-caps text-right">
              AI
            </span>
          </div>
          <div role="rowgroup" className="flex flex-col divide-y divide-border">
            {champions.map((champion) => (
              <ChampionRow key={champion.champion_id} champion={champion} />
            ))}
          </div>
        </div>
      )}
    </GlowCard>
  );
}

function ChampionRow({ champion }: { champion: ChampionStat }) {
  const name = championDisplayName(champion.champion_name);
  const losses = champion.games - champion.wins;
  return (
    <div role="row" className={cn(GRID, "py-2")}>
      <span role="cell">
        <ChampionIcon champion={champion.champion_name} size="sm" />
      </span>
      <span role="cell" className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium text-text" title={name}>
          {name}
        </span>
        <span className="text-[11px] text-text-muted tabular-nums">{plural(champion.games, "game")}</span>
      </span>
      <span role="cell" className="flex flex-col gap-1">
        <span
          className={cn(
            "text-xs font-semibold tabular-nums",
            champion.winrate >= 0.5 ? "text-text" : "text-text-secondary",
          )}
        >
          {formatPercent(champion.winrate)}
        </span>
        <WinRateBar wins={champion.wins} losses={losses} showLabels={false} size="sm" className="[&>div]:h-1" />
      </span>
      <span
        role="cell"
        className={cn(
          "text-right text-xs font-semibold tabular-nums",
          champion.kda >= 4 ? "text-gold-bright" : champion.kda >= 2.5 ? "text-text" : "text-text-secondary",
        )}
      >
        {formatDecimal(champion.kda, 2)}
      </span>
      <span role="cell" className="flex justify-end">
        <AiScoreBadge score={champion.avg_ai_score} kind="average" size="sm" />
      </span>
    </div>
  );
}
