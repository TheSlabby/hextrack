/**
 * Small presentational pieces shared by MatchRow and MatchDetailView.
 */
import { Link } from "@tanstack/react-router";
import { Hexagon } from "lucide-react";

import type { ParticipantSummary } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { GameImage } from "@/components/common/GameImage";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { useDdragon } from "@/lib/ddragon";
import { formatKdaRatio } from "@/lib/format";
import { formatRiotId, summonerParams } from "@/lib/riotId";
import { championDisplayName } from "@/lib/champions";

import { displayName, inGameRank, kdaToneClass, riotIdOf, type InGameRank } from "./matchUtils";

// --- in-game rank -------------------------------------------------------------------------

const RANK_PILL = {
  mvp: "border-gold bg-gold text-primary-foreground",
  ace: "border-gold/45 bg-gold/10 text-gold-bright",
  rank: "border-border-strong bg-white/[0.04] text-text-secondary",
} as const;

export function InGameRankPill({ rank, className }: { rank: InGameRank; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex h-[18px] min-w-8 items-center justify-center rounded-full border px-1.5 text-[10px] leading-none font-bold tracking-wide tabular-nums",
            RANK_PILL[rank.kind],
            className,
          )}
          aria-label={rank.description}
        >
          {rank.label}
        </span>
      </TooltipTrigger>
      <TooltipContent>{rank.description}</TooltipContent>
    </Tooltip>
  );
}

interface TeamLike {
  team_id: ParticipantSummary["team_id"];
  win: boolean;
  participants: readonly ParticipantSummary[];
}

/** AI Score pill plus the MVP / ACE / #N pill. */
export function AiScoreWithRank({
  participant,
  teams,
  remake,
  layout = "row",
  size = "md",
  className,
}: {
  participant: ParticipantSummary;
  teams: readonly TeamLike[];
  remake: boolean;
  layout?: "row" | "stack";
  size?: "sm" | "md";
  className?: string;
}) {
  const rank = inGameRank(participant, teams, remake);
  return (
    <div
      className={cn(
        "inline-flex items-center",
        layout === "stack" ? "flex-col gap-1" : "gap-1.5",
        className,
      )}
    >
      <AiScoreBadge score={participant.ai_score} size={size} />
      {rank ? <InGameRankPill rank={rank} /> : null}
    </div>
  );
}

// --- KDA ----------------------------------------------------------------------------------

/** "7 / 2 / 11" with deaths tinted. */
export function KdaLine({
  kills,
  deaths,
  assists,
  className,
}: {
  kills: number;
  deaths: number;
  assists: number;
  className?: string;
}) {
  return (
    <span
      className={cn("inline-flex items-baseline gap-1 whitespace-nowrap tabular-nums", className)}
      aria-label={`${kills} kills, ${deaths} deaths, ${assists} assists`}
    >
      <span className="text-text">{kills}</span>
      <span aria-hidden="true" className="text-text-muted">
        /
      </span>
      <span className="text-loss">{deaths}</span>
      <span aria-hidden="true" className="text-text-muted">
        /
      </span>
      <span className="text-text">{assists}</span>
    </span>
  );
}

/** "3.50 KDA" / "Perfect KDA", coloured by tier (>= 5 gold, >= 3 cyan). */
export function KdaRatio({
  kda,
  deaths,
  suffix = " KDA",
  className,
}: {
  kda: number;
  deaths: number;
  suffix?: string;
  className?: string;
}) {
  return (
    <span className={cn("font-semibold whitespace-nowrap tabular-nums", kdaToneClass(kda, deaths), className)}>
      {formatKdaRatio(kda, deaths)}
      {suffix ? <span className="font-medium">{suffix}</span> : null}
    </span>
  );
}

// --- players ------------------------------------------------------------------------------

/** Gold hex marking a tracked (roster) player. */
export function TrackedMark({ className }: { className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn("inline-flex shrink-0 text-gold", className)} role="img" aria-label="Tracked player">
          <Hexagon className="size-3 fill-gold/25" aria-hidden="true" />
        </span>
      </TooltipTrigger>
      <TooltipContent>Tracked by HexTrack</TooltipContent>
    </Tooltip>
  );
}

export interface PlayerNameLinkProps {
  participant: Pick<ParticipantSummary, "game_name" | "tag_line" | "champion_name" | "is_tracked">;
  /** The player whose page / history this is: rendered bold. */
  focused?: boolean;
  /** Append the tracked hex marker. */
  showTrackedMark?: boolean;
  /** -1 keeps the link out of the tab order (dense rows whose details repeat the links). */
  tabIndex?: number;
  className?: string;
}

/**
 * Riot ID link to the summoner page. Tracked players are gold, the focused player is bold;
 * players without a stored Riot ID render as plain text.
 */
export function PlayerNameLink({ participant, focused, showTrackedMark, tabIndex, className }: PlayerNameLinkProps) {
  const riotId = riotIdOf(participant);
  const name = displayName(participant);
  const tone = participant.is_tracked ? "text-gold" : focused ? "text-text" : "text-text-secondary";
  const classes = cn(
    "inline-flex min-w-0 max-w-full items-center gap-1 rounded-sm",
    tone,
    focused ? "font-semibold" : "font-medium",
    className,
  );
  const body = (
    <>
      <span className="truncate">{name}</span>
      {showTrackedMark && participant.is_tracked ? <TrackedMark /> : null}
    </>
  );

  if (!riotId) {
    return <span className={classes}>{body}</span>;
  }
  return (
    <Link
      to="/summoner/$region/$riotId"
      params={summonerParams(riotId.gameName, riotId.tagLine)}
      title={formatRiotId(riotId.gameName, riotId.tagLine)}
      tabIndex={tabIndex}
      className={cn(
        classes,
        "transition-colors hover:text-gold-bright hover:underline hover:decoration-gold/40 hover:underline-offset-2",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
      )}
    >
      {body}
    </Link>
  );
}

/**
 * 16px champion portrait for dense participant lists (the shared ChampionIcon starts at
 * 20px, which makes a 5-player column taller than an op.gg-style row).
 */
export function TinyChampion({ champion, className }: { champion: string; className?: string }) {
  const dd = useDdragon();
  const name = championDisplayName(champion);
  return (
    <span
      className={cn("block size-4 shrink-0 overflow-hidden rounded-[4px] bg-surface-3 ring-1 ring-white/10", className)}
      title={name}
    >
      <GameImage
        src={champion ? dd.championIcon(champion) : ""}
        alt={name}
        width={16}
        height={16}
        className="size-full scale-[1.08] object-cover"
        fallback={
          <span
            role="img"
            aria-label={name}
            className="flex size-full items-center justify-center text-[8px] font-semibold text-text-secondary"
          >
            {name.slice(0, 1)}
          </span>
        }
      />
    </span>
  );
}

// --- bars ---------------------------------------------------------------------------------

/** Value over a thin bar scaled to `max` (e.g. damage relative to the match's top damage). */
export function StatBar({
  value,
  max,
  label,
  barClassName,
  className,
}: {
  value: number;
  max: number;
  /** Formatted value shown above the bar. */
  label: string;
  barClassName: string;
  className?: string;
}) {
  const pct = max > 0 ? Math.max(2, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-xs font-medium tabular-nums text-text">{label}</span>
      <span aria-hidden="true" className="block h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <span className={cn("block h-full rounded-full", barClassName)} style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}
