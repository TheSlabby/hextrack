/** Small presentational pieces shared by the leaderboard table, its mobile cards and the home page. */
import { Link } from "@tanstack/react-router";
import { Handshake } from "lucide-react";

import type { BestAlly } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { RankEmblem } from "@/components/common/RankEmblem";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatPercent, formatSigned, plural } from "@/lib/format";
import { summonerParams } from "@/lib/riotId";
import { formatTier, TIER_TEXT_CLASS } from "@/lib/tiers";

import type { DisplayedRank } from "./sorting";

/** "Name" + muted "#TAG"; the name truncates, the tag never does. */
export function RiotIdText({
  gameName,
  tagLine,
  className,
  nameClassName,
}: {
  gameName: string;
  tagLine: string;
  className?: string;
  nameClassName?: string;
}) {
  return (
    <span className={cn("flex min-w-0 items-baseline gap-1", className)}>
      <span className={cn("truncate font-semibold text-text", nameClassName)}>{gameName}</span>
      <span className="shrink-0 text-[0.85em] font-medium text-text-muted">#{tagLine}</span>
    </span>
  );
}

/** Signed season LP change: green up, red down, muted when flat or unknown. */
export function LpDelta({
  value,
  suffix = false,
  className,
}: {
  value: number | null;
  suffix?: boolean;
  className?: string;
}) {
  if (value === null) {
    return (
      <span className={cn("text-text-muted tabular-nums", className)}>
        <span aria-hidden="true">–</span>
        <span className="sr-only">No LP data this season</span>
      </span>
    );
  }
  const tone = value > 0 ? "text-score-a" : value < 0 ? "text-loss" : "text-text-muted";
  const text = value === 0 ? "±0" : formatSigned(value);
  return (
    <span className={cn("font-semibold tabular-nums", tone, className)}>
      <span aria-hidden="true">
        {text}
        {suffix ? <span className="ml-0.5 text-[0.85em] font-medium">LP</span> : null}
      </span>
      <span className="sr-only">
        {value > 0 ? `Gained ${value}` : value < 0 ? `Lost ${-value}` : "No change,"} LP this season
      </span>
    </span>
  );
}

const MEDAL: Readonly<Record<1 | 2 | 3, string>> = {
  1: "border-gold/45 bg-gold/12 text-gold",
  2: "border-tier-silver/40 bg-tier-silver/10 text-tier-silver",
  3: "border-tier-bronze/45 bg-tier-bronze/12 text-tier-bronze",
};

/**
 * Overall standing number; the top three get gold, silver and bronze medallions. `null` (not
 * enough ranked games for a standing) shows a dash.
 */
export function StandingBadge({ standing, className }: { standing: number | null; className?: string }) {
  const medal = standing === 1 || standing === 2 || standing === 3 ? MEDAL[standing] : null;
  return (
    <span
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-lg font-display text-sm font-bold tabular-nums",
        medal ? cn("border", medal) : "text-text-muted",
        className,
      )}
    >
      {standing === null ? (
        <>
          <span aria-hidden="true">–</span>
          <span className="sr-only">No standing yet</span>
        </>
      ) : (
        standing
      )}
    </span>
  );
}

/**
 * A rank: emblem + tier name, LP underneath (`md`) or inline (`sm`, for tight rows).
 * "Unranked" when there is no rank for the queue.
 */
export function RankCell({
  rank,
  size = "md",
  className,
}: {
  rank: DisplayedRank | null;
  size?: "sm" | "md";
  className?: string;
}) {
  const tier = rank?.entry.tier ?? null;
  const tierText = (
    <span
      className={cn(
        "truncate font-semibold",
        size === "sm" ? "text-xs" : "text-[13px]",
        tier ? TIER_TEXT_CLASS[tier] : "text-text-muted",
      )}
    >
      {rank ? formatTier(rank.entry.tier, rank.entry.rank) : "Unranked"}
    </span>
  );
  const lpText = rank ? (
    <span className="flex shrink-0 items-center gap-1 text-xs text-text-secondary tabular-nums">
      {size === "sm" ? (
        <span aria-hidden="true" className="text-text-muted">
          ·
        </span>
      ) : null}
      {rank.entry.lp} LP
      {rank.isFallback ? <span className="text-[11px] text-text-muted">· Flex</span> : null}
    </span>
  ) : null;

  if (size === "sm") {
    return (
      <span className={cn("flex min-w-0 items-center gap-1.5", className)}>
        <RankEmblem tier={tier} size={18} title="" />
        {tierText}
        {lpText}
      </span>
    );
  }
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      <RankEmblem tier={tier} size={30} title="" />
      <span className="flex min-w-0 flex-col leading-tight">
        {tierText}
        {lpText}
      </span>
    </span>
  );
}

/** Up to three overlapping champion portraits. */
export function TopChampions({ champions, className }: { champions: readonly string[]; className?: string }) {
  if (champions.length === 0) return <span className={cn("text-xs text-text-muted", className)}>–</span>;
  return (
    <span className={cn("flex items-center", className)} aria-label={`Most played: ${champions.join(", ")}`} role="img">
      {champions.map((champion, index) => (
        <span
          key={champion}
          className={cn("rounded-[7px] ring-2 ring-surface-1", index > 0 && "-ml-1.5")}
          style={{ zIndex: champions.length - index }}
        >
          <ChampionIcon champion={champion} size="sm" />
        </span>
      ))}
    </span>
  );
}

/** Best duo partner: linked name + "9 games · 67%" with a tooltip explaining the stat. */
export function BestAllyLink({
  ally,
  showIcon = true,
  className,
}: {
  ally: BestAlly | null;
  /** Hide the handshake where a column header already says "Best duo" (names need the room). */
  showIcon?: boolean;
  className?: string;
}) {
  if (!ally) return <span className={cn("text-xs text-text-muted", className)}>–</span>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to="/summoner/$region/$riotId"
          params={summonerParams(ally.game_name, ally.tag_line)}
          className={cn(
            "group/ally flex min-w-0 flex-col rounded-md leading-tight outline-offset-2 hover:text-gold-bright",
            className,
          )}
          onClick={(event) => event.stopPropagation()}
        >
          <span className="flex min-w-0 items-center gap-1.5">
            {showIcon ? (
              <Handshake className="size-3.5 shrink-0 text-text-muted group-hover/ally:text-gold" aria-hidden="true" />
            ) : null}
            <span className="truncate text-[13px] font-medium text-text group-hover/ally:text-gold-bright">
              {ally.game_name}
            </span>
          </span>
          <span className={cn("text-xs text-text-muted tabular-nums", showIcon && "pl-5")}>
            {plural(ally.games, "game")} · {formatPercent(ally.winrate)}
          </span>
        </Link>
      </TooltipTrigger>
      <TooltipContent>
        Best duo: {ally.wins} wins in {plural(ally.games, "game")} together on the same team (
        {formatPercent(ally.winrate)}).
      </TooltipContent>
    </Tooltip>
  );
}
