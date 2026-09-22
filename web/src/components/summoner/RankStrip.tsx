import type { QueueType, RankEntry } from "@/api/types";
import { GlowCard, RankEmblem } from "@/components/common";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { QUEUE_TYPE_LABELS } from "@/lib/queues";
import { TIER_TEXT_CLASS, formatTier, isApexTier } from "@/lib/tiers";

import { TIER_BG_CLASS } from "./summonerFormat";

export interface RankStripProps {
  solo: RankEntry | null;
  flex: RankEntry | null;
  className?: string;
}

/**
 * Both ranked queues in one short card. Below `lg` this stands in for the full rank cards so
 * the tabs and match history stay near the top of the page; the sidebar takes over at `lg`.
 */
export function RankStrip({ solo, flex, className }: RankStripProps) {
  return (
    <GlowCard className={cn("grid grid-cols-2 gap-px overflow-hidden bg-border p-0", className)}>
      <RankCell queue="RANKED_SOLO_5x5" entry={solo} />
      <RankCell queue="RANKED_FLEX_SR" entry={flex} />
    </GlowCard>
  );
}

function RankCell({ queue, entry }: { queue: QueueType; entry: RankEntry | null }) {
  const label = QUEUE_TYPE_LABELS[queue];
  const apex = entry ? isApexTier(entry.tier) : false;

  return (
    <section aria-label={label} className="flex min-w-0 flex-col gap-2 bg-surface-1 p-3 sm:p-4">
      <span className="label-caps truncate">{label}</span>
      <div className="flex min-w-0 items-center gap-2.5 sm:gap-3">
        <RankEmblem tier={entry?.tier ?? null} size={44} className={cn("shrink-0", !entry && "opacity-80")} />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span
            className={cn(
              "truncate font-display text-sm leading-tight font-bold sm:text-base",
              entry ? TIER_TEXT_CLASS[entry.tier] : "text-text-secondary",
              entry?.tier === "IRON" && "text-[#9a9ea6]",
            )}
          >
            {entry ? formatTier(entry.tier, entry.rank) : "Unranked"}
          </span>
          {entry ? (
            <span className="text-xs text-text-secondary tabular-nums">
              <span className="font-semibold text-text">{entry.lp}</span> LP
            </span>
          ) : (
            <span className="text-[11px] leading-snug text-text-muted">No games this season</span>
          )}
        </div>
      </div>
      {entry ? (
        <div className="flex flex-col gap-1.5">
          {apex ? null : (
            <Progress
              value={Math.max(0, Math.min(100, entry.lp))}
              aria-label={`${entry.lp} of 100 LP in ${formatTier(entry.tier, entry.rank)}`}
              className="h-1"
              indicatorClassName={TIER_BG_CLASS[entry.tier]}
            />
          )}
          <span className="flex items-baseline justify-between gap-2 text-[11px] text-text-secondary tabular-nums">
            <span>
              <span className="text-win">{entry.wins}W</span> <span className="text-loss">{entry.losses}L</span>
            </span>
            <span className="font-semibold text-text">{formatPercent(entry.winrate)}</span>
          </span>
        </div>
      ) : null}
    </section>
  );
}
