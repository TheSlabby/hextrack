import type { ReactNode } from "react";

import type { Division, Tier } from "@/api/types";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { TierBadge } from "@/components/common/TierBadge";
import { cn } from "@/lib/cn";

export interface SummonerOptionProps {
  gameName: string;
  tagLine: string;
  profileIconId: number | null;
  tier?: Tier | null;
  rank?: Division | null;
  /** Secondary line under the name (e.g. "Tracked", "Visited 2h ago"). */
  caption?: ReactNode;
  /** Trailing content after the rank (badges, shortcuts). */
  trailing?: ReactNode;
  className?: string;
}

/** One summoner row inside a search list: icon, Riot ID, optional caption and solo rank. */
export function SummonerOption({
  gameName,
  tagLine,
  profileIconId,
  tier,
  rank,
  caption,
  trailing,
  className,
}: SummonerOptionProps) {
  return (
    <span className={cn("flex min-w-0 flex-1 items-center gap-3", className)}>
      <ProfileIcon iconId={profileIconId} size="sm" alt="" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-baseline gap-1">
          <span className="truncate font-medium text-text">{gameName}</span>
          <span className="shrink-0 text-text-muted">#{tagLine}</span>
        </span>
        {caption ? <span className="truncate text-xs text-text-muted">{caption}</span> : null}
      </span>
      {tier ? (
        <TierBadge tier={tier} rank={rank ?? null} size="sm" className="hidden shrink-0 min-[420px]:inline-flex" />
      ) : null}
      {trailing}
    </span>
  );
}
