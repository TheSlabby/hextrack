import type { Division, RankEntry, Tier } from "@/api/types";
import { cn } from "@/lib/cn";
import { formatTier, TIER_TEXT_CLASS } from "@/lib/tiers";

import { RankEmblem } from "./RankEmblem";

export interface TierBadgeProps {
  /** A rank entry from the API; or pass tier/rank/lp directly. null = unranked. */
  entry?: Pick<RankEntry, "tier" | "rank" | "lp"> | null;
  tier?: Tier | null;
  rank?: Division | null;
  lp?: number | null;
  /** Show the emblem before the label. */
  emblem?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const EMBLEM_PX = { sm: 18, md: 24, lg: 36 } as const;
const TEXT = { sm: "text-xs", md: "text-sm", lg: "text-base" } as const;

/** "Diamond II · 54 LP", with the tier name tinted and an optional emblem. */
export function TierBadge({ entry, tier, rank, lp, emblem = true, size = "md", className }: TierBadgeProps) {
  const t = entry?.tier ?? tier ?? null;
  const r = entry?.rank ?? rank ?? null;
  const points = entry?.lp ?? lp ?? null;

  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap", TEXT[size], className)}>
      {emblem ? <RankEmblem tier={t} size={EMBLEM_PX[size]} title="" /> : null}
      <span className={cn("font-semibold", t ? TIER_TEXT_CLASS[t] : "text-text-muted", t === "IRON" && "text-[#9a9ea6]")}>
        {formatTier(t, r)}
      </span>
      {t && points !== null ? (
        <>
          <span aria-hidden="true" className="text-text-muted">
            ·
          </span>
          <span className="tabular-nums text-text-secondary">{points} LP</span>
        </>
      ) : null}
    </span>
  );
}
