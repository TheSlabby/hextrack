import { useCallback, useId, useState, type MouseEvent } from "react";
import { Link } from "@tanstack/react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ChevronDown, ExternalLink } from "lucide-react";

import type { ParticipantSummary, StackGame } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { DdragonPatch } from "@/components/common/DdragonPatch";
import { playerSearchValue } from "@/components/match/focus";
import { KdaLine, PlayerNameLink } from "@/components/match/MatchBits";
import { MatchDetailView } from "@/components/match/MatchDetail";
import { displayName, OUTCOME_LABEL, OUTCOME_STYLES, outcomeOf, rowQueueLabel } from "@/components/match/matchUtils";
import { isPraise, verdictBadge, verdictText, type VerdictBadge } from "@/components/match/verdicts";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { EASE_OUT } from "@/lib/motion";
import { formatDateTime, formatDuration, timeAgo } from "@/lib/format";

/** Elements inside the row that handle their own clicks. */
const INTERACTIVE = "a, button, input, select, textarea, [role='button']";

const VERDICT_NOTE = "From the teammates' AI Scores. They share the same result, so their scores compare fairly.";

const VERDICT_PILL = {
  praise: "border-gold/45 bg-gold/10 text-gold-bright",
  blame: "border-loss/45 bg-loss/10 text-loss",
} as const;

const BADGE_PILL: Readonly<Record<VerdictBadge["kind"], string>> = {
  carry: "border-gold bg-gold text-primary-foreground",
  down: "border-loss/45 bg-loss/10 text-loss",
};

const TARGET_RING = {
  praise: "ring-gold/45",
  blame: "ring-loss/45",
} as const;

interface RowVerdict {
  text: string;
  tone: "praise" | "blame";
  /** The called-out member (null for the "together" tiers). */
  targetPuuid: string | null;
  badge: VerdictBadge | null;
}

/**
 * The server's verdict as text, through the same helpers the match hero and the share card
 * use (same line for the same match id).
 */
function rowVerdict(game: StackGame): RowVerdict | null {
  const verdict = game.verdict;
  const first = game.members[0];
  if (!verdict || !first) return null;
  const target = verdict.target_puuid ? game.members.find((m) => m.puuid === verdict.target_puuid) : undefined;
  const others = game.members.filter((m) => m.puuid !== (target ?? first).puuid);
  const rest = game.members.length === 2 && others[0] ? displayName(others[0]) : "the squad";
  return {
    text: verdictText(verdict.tier, displayName(target ?? first), rest, game.match_id, game.members.length),
    tone: isPraise(verdict.tier) ? "praise" : "blame",
    targetPuuid: target?.puuid ?? null,
    badge: target ? verdictBadge(verdict.tier) : null,
  };
}

function memberSummary(member: ParticipantSummary): string {
  return `${displayName(member)} as ${championDisplayName(member.champion_name)}, ${member.kills} / ${member.deaths} / ${member.assists}`;
}

function VerdictPill({ verdict, className }: { verdict: RowVerdict; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "pointer-events-auto inline-flex h-6 max-w-full min-w-0 items-center rounded-full border px-2.5 text-xs font-semibold",
            VERDICT_PILL[verdict.tone],
            className,
          )}
        >
          <span className="truncate">{verdict.text}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{VERDICT_NOTE}</TooltipContent>
    </Tooltip>
  );
}

function BadgePill({ badge, className }: { badge: VerdictBadge; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-[18px] items-center rounded-full border px-1.5 text-[10px] leading-none font-bold tracking-wide whitespace-nowrap",
        BADGE_PILL[badge.kind],
        className,
      )}
    >
      {badge.label}
    </span>
  );
}

/** Wide layout: one cell per member with champion, name, KDA, AI Score and the verdict badge. */
function MemberCell({ member, verdict }: { member: ParticipantSummary; verdict: RowVerdict | null }) {
  const isTarget = verdict !== null && verdict.targetPuuid === member.puuid;
  return (
    <li
      className={cn(
        "flex min-w-0 flex-col gap-1.5 rounded-lg bg-white/[0.03] px-2 py-1.5 ring-1 ring-white/[0.05]",
        isTarget && verdict && TARGET_RING[verdict.tone],
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <ChampionIcon champion={member.champion_name} size="sm" level={member.champ_level} />
        <div className="flex min-w-0 flex-1 flex-col">
          <PlayerNameLink participant={member} tabIndex={-1} className="pointer-events-auto text-xs leading-4" />
          <KdaLine
            kills={member.kills}
            deaths={member.deaths}
            assists={member.assists}
            className="text-[11px] leading-4 font-medium"
          />
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-1">
        <span className="pointer-events-auto inline-flex">
          <AiScoreBadge score={member.ai_score} size="sm" />
        </span>
        {isTarget && verdict.badge ? <BadgePill badge={verdict.badge} /> : null}
      </div>
    </li>
  );
}

/** Narrow layout: champion icon with the member's AI Score under it. */
function MemberChip({ member, verdict }: { member: ParticipantSummary; verdict: RowVerdict | null }) {
  const isTarget = verdict !== null && verdict.targetPuuid === member.puuid;
  const summary = memberSummary(member);
  return (
    <li className="flex max-w-16 min-w-0 flex-1 flex-col items-center gap-1.5" title={summary}>
      <span className="sr-only">
        {summary}
        {isTarget && verdict.badge ? `, ${verdict.badge.label.toLowerCase()}` : ""}
      </span>
      <ChampionIcon
        champion={member.champion_name}
        size="sm"
        level={member.champ_level}
        className={cn(
          "rounded-md",
          isTarget && verdict && ["ring-2 ring-offset-1 ring-offset-surface-1", TARGET_RING[verdict.tone]],
        )}
      />
      <span className="pointer-events-auto inline-flex">
        <AiScoreBadge score={member.ai_score} size="sm" />
      </span>
    </li>
  );
}

export interface StackGameRowProps {
  game: StackGame;
  className?: string;
}

/**
 * One stack in one game: result, queue, time and team kills; each roster member's champion,
 * KDA and AI Score; and the teammates' verdict ("colton carried"). Click to expand the full
 * match detail, focused on the called-out player.
 */
export function StackGameRow({ game, className }: StackGameRowProps) {
  const [expanded, setExpanded] = useState(false);
  const detailId = useId();
  const reduced = useReducedMotion();
  const toggle = useCallback(() => setExpanded((open) => !open), []);

  // Remakes never reach the Stacks page (the server drops them).
  const outcome = outcomeOf(false, game.win);
  const style = OUTCOME_STYLES[outcome];
  const queue = rowQueueLabel(game.queue_id, game.game_mode, game.queue_label);
  const ago = timeAgo(game.game_start);
  const startedAt = formatDateTime(game.game_start);
  const duration = formatDuration(game.game_duration);
  const verdict = rowVerdict(game);
  const focus = game.members.find((m) => m.puuid === verdict?.targetPuuid) ?? game.members[0];
  const summary = [
    `${OUTCOME_LABEL[outcome]} ${game.team_kills} to ${game.enemy_kills}`,
    queue,
    startedAt,
    verdict?.text,
  ]
    .filter(Boolean)
    .join(", ");

  const onContentClick = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target instanceof Element && event.target.closest(INTERACTIVE)) return;
    if (window.getSelection()?.toString()) return;
    toggle();
  };

  const kills = (
    <span
      className="whitespace-nowrap tabular-nums"
      aria-label={`Team kills ${game.team_kills} to ${game.enemy_kills}`}
      title="Team kills vs enemy kills"
    >
      <span className="font-semibold text-text">{game.team_kills}</span>
      <span className="text-text-muted"> – </span>
      <span className="text-text-secondary">{game.enemy_kills}</span>
    </span>
  );

  return (
    <DdragonPatch patch={game.patch}>
      <article
        className={cn(
          "group/row relative min-w-0 overflow-hidden rounded-xl border bg-surface-1 shadow-card transition-[border-color,box-shadow] duration-200",
          style.border,
          style.hoverBorder,
          expanded && "border-border-strong shadow-raised hover:border-border-strong",
          className,
        )}
      >
        <div className="@container relative">
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
            aria-label={`${summary}. ${expanded ? "Hide" : "Show"} game details`}
            className="absolute inset-0 z-0 w-full cursor-pointer rounded-[inherit] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-gold"
          />

          <div
            onClick={onContentClick}
            className="pointer-events-none relative z-[1] flex flex-col gap-2.5 py-3 pr-3 pl-4 @3xl:flex-row @3xl:items-center @3xl:gap-4 @3xl:py-2.5"
          >
            {/* Narrow: meta line */}
            <div className="flex min-w-0 items-center gap-2 pr-16 text-xs @3xl:hidden">
              <span className={cn("font-bold", style.text)}>{OUTCOME_LABEL[outcome]}</span>
              {kills}
              <span className="min-w-0 truncate text-text-secondary">
                {queue} · <span className="tabular-nums">{duration}</span> ·{" "}
                <time dateTime={game.game_start} title={startedAt}>
                  {ago}
                </time>
              </span>
            </div>

            {/* Wide: meta column */}
            <div className="hidden w-[92px] shrink-0 flex-col items-start text-xs @3xl:flex">
              <span className={cn("font-bold", style.text)}>{OUTCOME_LABEL[outcome]}</span>
              <span className="max-w-full truncate font-semibold text-text" title={game.queue_label}>
                {queue}
              </span>
              <time dateTime={game.game_start} title={startedAt} className="text-[11px] text-text-muted">
                {ago}
              </time>
              <span aria-hidden="true" className="my-1.5 h-px w-8 bg-border-strong" />
              <span className="flex items-baseline gap-1.5 text-[11px]">
                <span className="text-text-secondary tabular-nums">{duration}</span>
                <span aria-hidden="true" className="text-text-muted">
                  ·
                </span>
                {kills}
              </span>
            </div>

            {verdict ? (
              <div className="flex min-w-0 pr-2 @3xl:hidden">
                <VerdictPill verdict={verdict} />
              </div>
            ) : null}

            {/* Narrow: champion strip */}
            <ul className="flex min-w-0 gap-2 @3xl:hidden" aria-label="Stack members">
              {game.members.map((member) => (
                <MemberChip key={member.puuid} member={member} verdict={verdict} />
              ))}
            </ul>

            {/* Wide: verdict and member cells */}
            <div className="hidden min-w-0 flex-1 flex-col items-start gap-2 @3xl:flex">
              {verdict ? <VerdictPill verdict={verdict} /> : null}
              <ul
                className="grid w-full min-w-0 gap-2"
                style={{ gridTemplateColumns: `repeat(${Math.max(game.members.length, 1)}, minmax(0, 1fr))` }}
                aria-label="Stack members"
              >
                {game.members.map((member) => (
                  <MemberCell key={member.puuid} member={member} verdict={verdict} />
                ))}
              </ul>
            </div>

            {/* Actions */}
            <div className="absolute top-2 right-2 flex items-center gap-0.5 @3xl:static @3xl:flex-col @3xl:self-stretch @3xl:justify-between">
              <Link
                to="/match/$matchId"
                params={{ matchId: game.match_id }}
                search={focus ? { player: playerSearchValue(focus) } : {}}
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
                transition={{ duration: reduced ? 0 : 0.34, ease: EASE_OUT }}
                className="overflow-hidden"
              >
                <div className="border-t border-border bg-bg/40 p-2.5 sm:p-3">
                  <MatchDetailView matchId={game.match_id} focusPuuid={focus?.puuid} embedded />
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>
      </article>
    </DdragonPatch>
  );
}

/** Placeholder with the same box model as a collapsed <StackGameRow /> (five members). */
export function StackGameRowSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("relative overflow-hidden rounded-xl border border-border bg-surface-1 shadow-card", className)}
    >
      <div className="@container">
        <span className="absolute inset-y-0 left-0 w-1 bg-surface-3" />
        <div className="flex flex-col gap-2.5 py-3 pr-3 pl-4 @3xl:flex-row @3xl:items-center @3xl:gap-4 @3xl:py-2.5">
          {/* narrow */}
          <div className="flex h-4 items-center gap-2 @3xl:hidden">
            <Skeleton className="h-3.5 w-14" />
            <Skeleton className="h-3 w-44" />
          </div>
          <Skeleton className="h-6 w-40 rounded-full @3xl:hidden" />
          <div className="flex gap-2 @3xl:hidden">
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="flex max-w-16 flex-1 flex-col items-center gap-1.5">
                <Skeleton className="size-7 rounded-md" />
                <Skeleton className="h-5 w-11 rounded-full" />
              </div>
            ))}
          </div>
          {/* wide */}
          <div className="hidden w-[92px] shrink-0 flex-col gap-1.5 @3xl:flex">
            <Skeleton className="h-3.5 w-14" />
            <Skeleton className="h-3.5 w-20" />
            <Skeleton className="h-3 w-12" />
            <span className="my-0.5 h-px w-8 bg-border-strong" />
            <Skeleton className="h-3 w-16" />
          </div>
          <div className="hidden min-w-0 flex-1 flex-col gap-2 @3xl:flex">
            <Skeleton className="h-6 w-40 rounded-full" />
            <div className="grid grid-cols-5 gap-2">
              {Array.from({ length: 5 }, (_, i) => (
                <div key={i} className="flex flex-col gap-1.5 rounded-lg bg-white/[0.03] px-2 py-1.5">
                  <div className="flex items-center gap-2">
                    <Skeleton className="size-7 rounded-md" />
                    <div className="flex flex-1 flex-col gap-1">
                      <Skeleton className="h-3 w-full max-w-16" />
                      <Skeleton className="h-3 w-12" />
                    </div>
                  </div>
                  <Skeleton className="h-5 w-11 rounded-full" />
                </div>
              ))}
            </div>
          </div>
          <div className="hidden w-7 @3xl:block" />
        </div>
      </div>
    </div>
  );
}
