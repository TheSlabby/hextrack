import { useCallback, useId, useState, type MouseEvent } from "react";
import { Link } from "@tanstack/react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ChevronDown, ExternalLink } from "lucide-react";

import type { MatchSummary } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { DdragonPatch } from "@/components/common/DdragonPatch";
import { RolePercentileLabel } from "@/components/common/RolePercentile";
import { ItemSlots } from "@/components/common/ItemSlots";
import { SpellIcons } from "@/components/common/SpellIcons";
import { cn } from "@/lib/cn";
import { formatCompact, formatDateTime, formatDecimal, formatDuration, formatPercent, timeAgo } from "@/lib/format";
import { championDisplayName } from "@/lib/champions";

import { playerSearchValue } from "./focus";
import { AiScoreWithRank, KdaLine, KdaRatio, PlayerNameLink, TinyChampion } from "./MatchBits";
import { MatchDetailView } from "./MatchDetail";
import {
  multikillLabel,
  OUTCOME_LABEL,
  OUTCOME_STYLES,
  outcomeOf,
  rowQueueLabel,
  sortByPosition,
  TEAM_SIDE_LABEL,
} from "./matchUtils";

export interface MatchRowProps {
  match: MatchSummary;
  /** The player whose history this row belongs to (`match.me`). */
  puuid: string;
  /** Start expanded (e.g. a deep link). */
  defaultExpanded?: boolean;
  className?: string;
}

const EASE = [0.16, 1, 0.3, 1] as const;

/** Elements inside the row that handle their own clicks. */
const INTERACTIVE = "a, button, input, select, textarea, [role='button']";

/**
 * op.gg-style match row: result stripe + tint, game info, champion / spells / KDA / AI score,
 * items, key stats and both teams. Click (or Enter on the focused row) expands the full
 * match detail inline; the link icon opens the match page.
 */
export function MatchRow({ match, puuid, defaultExpanded = false, className }: MatchRowProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const detailId = useId();
  const reduced = useReducedMotion();
  const toggle = useCallback(() => setExpanded((open) => !open), []);

  const me = match.me;
  const outcome = outcomeOf(match.remake, me.win);
  const style = OUTCOME_STYLES[outcome];
  const queue = rowQueueLabel(match.queue_id, match.game_mode, match.queue_label);
  const champion = championDisplayName(me.champion_name);
  const multikill = multikillLabel(me.largest_multikill);
  const ago = timeAgo(match.game_start);
  const startedAt = formatDateTime(match.game_start);
  const summary = `${OUTCOME_LABEL[outcome]} as ${champion}, ${me.kills} / ${me.deaths} / ${me.assists}, ${queue}, ${ago}`;

  // Clicks on pointer-enabled content (tooltips) bubble here; links and buttons act on their own.
  const onContentClick = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target instanceof Element && event.target.closest(INTERACTIVE)) return;
    if (window.getSelection()?.toString()) return;
    toggle();
  };

  return (
    // The game's own patch, so items and spells that have since been removed still have icons.
    <DdragonPatch patch={match.patch}>
    <article
      className={cn(
        "group/row relative min-w-0 overflow-hidden rounded-xl border bg-surface-1 shadow-card transition-[border-color,box-shadow] duration-200",
        style.border,
        style.hoverBorder,
        expanded && "border-border-strong shadow-raised hover:border-border-strong",
        className,
      )}
    >
      <div className="relative">
        <span aria-hidden="true" className={cn("pointer-events-none absolute inset-0 bg-gradient-to-r", style.wash)} />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-white/0 transition-colors duration-200 group-hover/row:bg-white/[0.018]"
        />
        <span aria-hidden="true" className={cn("pointer-events-none absolute inset-y-0 left-0 w-1", style.stripe)} />

        {/* The whole row is one toggle button; content sits above it with pointer events off. */}
        <button
          type="button"
          onClick={toggle}
          aria-expanded={expanded}
          aria-controls={detailId}
          aria-label={`${summary}. ${expanded ? "Hide" : "Show"} match details`}
          className="absolute inset-0 z-0 w-full cursor-pointer rounded-[inherit] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-gold"
        />

        <div
          onClick={onContentClick}
          className="pointer-events-none relative z-[1] flex flex-col gap-2.5 py-3 pr-3 pl-4 @2xl:flex-row @2xl:items-center @2xl:gap-3 @2xl:py-2.5"
        >
          {/* Mobile header line */}
          <div className="flex min-w-0 items-center gap-2 pr-16 text-xs @2xl:hidden">
            <span className={cn("font-bold", style.text)}>{OUTCOME_LABEL[outcome]}</span>
            <span className="truncate text-text-secondary">
              {queue} · <span className="tabular-nums">{formatDuration(match.game_duration)}</span> ·{" "}
              <time dateTime={match.game_start} title={startedAt}>
                {ago}
              </time>
            </span>
          </div>

          {/* Desktop game info column */}
          <div className="hidden w-[84px] shrink-0 flex-col items-start text-xs @2xl:flex @4xl:w-[92px]">
            <span className="max-w-full truncate font-semibold text-text" title={match.queue_label}>
              {queue}
            </span>
            <time dateTime={match.game_start} title={startedAt} className="text-[11px] text-text-muted">
              {ago}
            </time>
            <span aria-hidden="true" className="my-1.5 h-px w-8 bg-border-strong" />
            <span className={cn("font-bold", style.text)}>{OUTCOME_LABEL[outcome]}</span>
            <span className="text-[11px] text-text-secondary tabular-nums">{formatDuration(match.game_duration)}</span>
          </div>

          {/* Champion, spells, KDA, AI score + items */}
          <div className="flex min-w-0 flex-col gap-2 @2xl:w-[256px] @2xl:shrink-0 @4xl:w-[276px]">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex shrink-0 items-center gap-1">
                <ChampionIcon champion={me.champion_name} size="lg" level={me.champ_level} />
                <SpellIcons spell1={me.summoner1_id} spell2={me.summoner2_id} size="md" />
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <KdaLine
                  kills={me.kills}
                  deaths={me.deaths}
                  assists={me.assists}
                  className="font-display text-[15px] font-semibold"
                />
                <KdaRatio kda={me.kda} deaths={me.deaths} className="text-xs" />
              </div>
              <div className="pointer-events-auto flex w-[76px] shrink-0 flex-col items-center gap-1">
                <AiScoreWithRank participant={me} teams={match.teams} remake={match.remake} layout="stack" />
                <RolePercentileLabel percentile={me.ai_role_percentile} position={me.team_position} />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2">
              <ItemSlots items={me.items} size="sm" />
              {multikill ? (
                <span className="rounded-full border border-gold/30 bg-gold/10 px-1.5 text-[10px] leading-4 font-bold whitespace-nowrap text-gold">
                  {multikill}
                </span>
              ) : null}
            </div>
          </div>

          {/* Key stats */}
          <dl className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] leading-4 tabular-nums @2xl:w-[84px] @2xl:shrink-0 @2xl:flex-col @4xl:w-[104px]">
            <div className="flex gap-1">
              <dt className="text-text-muted">KP</dt>
              <dd className="font-medium text-text">{formatPercent(me.kill_participation)}</dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-text-muted">CS</dt>
              <dd className="text-text">
                {me.cs} <span className="text-text-muted">({formatDecimal(me.cs_per_min)})</span>
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-text-muted">Dmg</dt>
              <dd className="text-text">{formatCompact(me.damage_to_champions)}</dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-text-muted">Vision</dt>
              <dd className="text-text">{me.vision_score}</dd>
            </div>
          </dl>

          {/* Both teams */}
          <div className="hidden min-w-0 flex-1 grid-cols-2 gap-x-2.5 @2xl:grid @3xl:gap-x-3">
            {match.teams.map((team) => (
              <ul key={team.team_id} className="flex min-w-0 flex-col gap-0.5" aria-label={TEAM_SIDE_LABEL[team.team_id]}>
                {sortByPosition(team.participants).map((p) => {
                  const focused = p.puuid === puuid;
                  return (
                    <li key={p.puuid} className="flex h-4 min-w-0 items-center gap-1.5">
                      <TinyChampion champion={p.champion_name} className={cn(focused && "ring-gold")} />
                      <PlayerNameLink
                        participant={p}
                        focused={focused}
                        tabIndex={-1}
                        className="pointer-events-auto text-[11px] leading-4"
                      />
                    </li>
                  );
                })}
              </ul>
            ))}
          </div>

          {/* Actions */}
          <div className="absolute top-2 right-2 flex items-center gap-0.5 @2xl:static @2xl:ml-auto @2xl:flex-col @2xl:self-stretch @2xl:justify-between">
            <Link
              to="/match/$matchId"
              params={{ matchId: match.match_id }}
              search={{ player: playerSearchValue(me) }}
              aria-label={`Open match page (${summary})`}
              title="Open match page"
              className="pointer-events-auto inline-flex size-7 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-white/8 hover:text-text focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-gold"
            >
              <ExternalLink className="size-3.5" aria-hidden="true" />
            </Link>
            <span
              aria-hidden="true"
              className={cn(
                "inline-flex size-7 items-center justify-center rounded-md text-text-muted transition-colors group-hover/row:text-text-secondary",
                expanded && "bg-white/6 text-text",
              )}
            >
              <ChevronDown
                className={cn("size-4 transition-transform duration-300 ease-out", expanded && "rotate-180")}
              />
            </span>
          </div>
        </div>
      </div>

      <div id={detailId}>
        <AnimatePresence initial={false}>
          {expanded ? (
            <motion.div
              key="detail"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: reduced ? 0 : 0.34, ease: EASE }}
              className="overflow-hidden"
            >
              <div className="border-t border-border bg-bg/40 p-2.5 sm:p-3">
                <MatchDetailView matchId={match.match_id} focusPuuid={puuid} embedded />
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </article>
    </DdragonPatch>
  );
}
