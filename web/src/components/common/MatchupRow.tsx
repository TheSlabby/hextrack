import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";

import { formatSignedCompact } from "@/components/summoner/trends/model";
import { championDisplayName, championSlug } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import type { ChampionsSearch } from "@/router";

import { ChampionIcon } from "./ChampionIcon";
import { WinRateBar } from "./WinRateBar";

export interface MatchupRowProps {
  /** Data Dragon key of the opposing champion, e.g. "MonkeyKing". */
  champion: string;
  wins: number;
  losses: number;
  /** Average gold difference against the lane opponent at the end of the game; null/undefined hides it. */
  avgGoldDiff?: number | null;
  /** More caption after the gold (e.g. an average AI Score badge or "not scored"). */
  detail?: ReactNode;
  /**
   * Link the champion (name and portrait) to its page. Default true; pass false when the row
   * sits inside another link or clickable row.
   */
  linked?: boolean;
  /** Patch / queue / role carried to the champion page (the champion page's own filters). */
  linkSearch?: ChampionsSearch;
  className?: string;
}

const NAME_LINK =
  "truncate rounded-sm transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold";

/**
 * One lane matchup: the opposing champion, a caption (average gold difference plus `detail`)
 * and a win / loss bar. Used by the profile's Trends tab and the champion page's matchups.
 */
export function MatchupRow({
  champion,
  wins,
  losses,
  avgGoldDiff,
  detail,
  linked = true,
  linkSearch,
  className,
}: MatchupRowProps) {
  const name = championDisplayName(champion);
  const gold = avgGoldDiff === null || avgGoldDiff === undefined ? null : Math.round(avgGoldDiff);
  const games = wins + losses;
  const params = { champion: championSlug(champion) };
  const label = [
    `${name}: ${wins} wins, ${losses} losses`,
    `${formatPercent(games > 0 ? wins / games : null)} win rate`,
    gold !== null ? `${formatSignedCompact(gold)} gold on average` : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div
      className={cn("flex items-center gap-3 rounded-xl border border-border bg-surface-2/40 px-2.5 py-2", className)}
      aria-label={label}
    >
      {linked ? (
        // The name below is the accessible link; the portrait is a mouse shortcut to the same page.
        <Link to="/champions/$champion" params={params} search={linkSearch} tabIndex={-1} aria-hidden="true" className="shrink-0 rounded-md">
          <ChampionIcon champion={champion} size="sm" />
        </Link>
      ) : (
        <ChampionIcon champion={champion} size="sm" />
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {linked ? (
          <Link
            to="/champions/$champion"
            params={params}
            search={linkSearch}
            className={cn(NAME_LINK, "max-w-full self-start text-sm font-semibold text-text")}
          >
            {name}
          </Link>
        ) : (
          <span className="truncate text-sm font-semibold text-text">{name}</span>
        )}
        {gold !== null || detail ? (
          <span className="flex items-center gap-2 text-xs text-text-muted tabular-nums">
            {gold !== null ? <span className="text-text-secondary">{formatSignedCompact(gold)} gold</span> : null}
            {detail}
          </span>
        ) : null}
      </div>
      <WinRateBar wins={wins} losses={losses} size="sm" className="w-24 shrink-0 sm:w-28" />
    </div>
  );
}
