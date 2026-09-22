import type { QueueType, RankEntry } from "@/api/types";
import { GlowCard, RankEmblem, WinRateBar } from "@/components/common";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/cn";
import { formatPercent, plural } from "@/lib/format";
import { QUEUE_TYPE_LABELS } from "@/lib/queues";
import { TIER_COLORS, TIER_TEXT_CLASS, formatTier, isApexTier } from "@/lib/tiers";

import { TIER_BG_CLASS, nextDivisionLabel, rankGames } from "./summonerFormat";

export interface RankCardProps {
  queue: QueueType;
  entry: RankEntry | null;
  /** Smaller emblem and type for the secondary queue. */
  compact?: boolean;
  className?: string;
}

/** One ranked queue: emblem, tier/division, LP with progress to the next division, W/L. */
export function RankCard({ queue, entry, compact, className }: RankCardProps) {
  const emblemSize = compact ? 60 : 76;
  const label = QUEUE_TYPE_LABELS[queue];

  if (!entry) {
    return (
      <GlowCard className={cn("flex flex-col gap-3 p-4 sm:p-5", className)}>
        <span className="label-caps">{label}</span>
        <div className="flex items-center gap-4">
          <RankEmblem tier={null} size={emblemSize} className="opacity-80" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className={cn("font-display font-semibold text-text-secondary", compact ? "text-lg" : "text-xl")}>
              Unranked
            </span>
            <span className="text-xs leading-relaxed text-text-muted">No {label} games on record this season.</span>
          </div>
        </div>
      </GlowCard>
    );
  }

  const apex = isApexTier(entry.tier);
  const games = rankGames(entry);
  const next = nextDivisionLabel(entry.tier, entry.rank);
  const lpInDivision = Math.max(0, Math.min(100, entry.lp));
  const tierColor = TIER_COLORS[entry.tier];

  return (
    <GlowCard className={cn("relative flex flex-col gap-3 overflow-hidden p-4 sm:p-5", className)}>
      {/* Faint tier-coloured glow behind the emblem. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-10 -left-10 size-44 rounded-full"
        style={{ background: `radial-gradient(closest-side, ${tierColor}22, transparent)` }}
      />
      <div className="relative flex items-center justify-between gap-2">
        <span className="label-caps">{label}</span>
        <span className="text-xs text-text-muted tabular-nums">{plural(games, "game")}</span>
      </div>

      <div className="relative flex items-center gap-4">
        <RankEmblem tier={entry.tier} size={emblemSize} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span
            className={cn(
              "font-display leading-tight font-bold",
              compact ? "text-lg" : "text-[22px]",
              TIER_TEXT_CLASS[entry.tier],
              entry.tier === "IRON" && "text-[#9a9ea6]",
            )}
          >
            {formatTier(entry.tier, entry.rank)}
          </span>
          <span className="text-sm text-text-secondary tabular-nums">
            <span className="font-semibold text-text">{entry.lp}</span> LP
          </span>
          {!apex ? (
            <div className="mt-1 flex flex-col gap-1">
              <Progress
                value={lpInDivision}
                aria-label={`${entry.lp} of 100 LP in ${formatTier(entry.tier, entry.rank)}`}
                className="h-1"
                indicatorClassName={TIER_BG_CLASS[entry.tier]}
              />
              {next ? (
                <span className="text-[11px] text-text-muted tabular-nums">
                  {entry.lp >= 100 ? `Next win promotes to ${next}` : `${100 - entry.lp} LP to ${next}`}
                </span>
              ) : null}
            </div>
          ) : (
            <span className="text-[11px] text-text-muted">Apex tier · LP ladder</span>
          )}
        </div>
      </div>

      <div className="relative flex flex-col gap-1.5 border-t border-border pt-3">
        <div className="flex items-baseline justify-between text-xs tabular-nums">
          <span className="text-text-secondary">
            <span className="text-win">{entry.wins}W</span> <span className="text-loss">{entry.losses}L</span>
          </span>
          <span className="text-text-secondary">
            <span className={cn("font-semibold", entry.winrate >= 0.5 ? "text-text" : "text-text-secondary")}>
              {formatPercent(entry.winrate)}
            </span>{" "}
            win rate
          </span>
        </div>
        <WinRateBar wins={entry.wins} losses={entry.losses} showLabels={false} size="sm" />
      </div>
    </GlowCard>
  );
}
