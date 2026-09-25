import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";

import type { StackGame } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { DdragonPatch } from "@/components/common/DdragonPatch";
import { playerSearchValue } from "@/components/match/focus";
import { KdaLine } from "@/components/match/MatchBits";
import { OUTCOME_LABEL, OUTCOME_STYLES, outcomeOf } from "@/components/match/matchUtils";
import { isPraise, verdictText } from "@/components/match/verdicts";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDuration, timeAgoShort } from "@/lib/format";
import { queueShortLabel } from "@/lib/queues";

/** "Duo", "3-stack", "5-stack". */
function groupLabel(size: number): string {
  return size === 2 ? "Duo" : `${size}-stack`;
}

/**
 * One game in the home page feed, on one compact card that links to the match. A solo game shows
 * the player's champion, KDA and AI Score; friends who queued together show their champions,
 * names and the carry / "ran it down" line.
 */
export function RecentGameItem({ game }: { game: StackGame }) {
  const outcome = outcomeOf(false, game.win);
  const styles = OUTCOME_STYLES[outcome];
  const members = game.members;
  const solo = members.length === 1;
  const lead = members.find((m) => m.puuid === game.verdict?.target_puuid) ?? members[0];
  if (!lead) return null;

  const verdict = game.verdict;
  const rest = members.length === 2 ? (members.find((m) => m !== lead)?.game_name ?? "the squad") : "the squad";
  const line = verdict ? verdictText(verdict.tier, lead.game_name ?? "", rest, game.match_id) : null;
  const names = members.map((m) => m.game_name ?? championDisplayName(m.champion_name)).join(", ");
  const queue = queueShortLabel(game.queue_id, game.game_mode);
  const when = timeAgoShort(game.game_start);
  const label = [
    `${OUTCOME_LABEL[outcome]}, ${queue}, ${when}`,
    solo
      ? `${names} as ${championDisplayName(lead.champion_name)}, ${lead.kills} ${lead.deaths} ${lead.assists}`
      : `${groupLabel(members.length)}: ${names}`,
    line,
  ]
    .filter(Boolean)
    .join(". ");

  return (
    <DdragonPatch patch={game.patch}>
      <Link
        to="/match/$matchId"
        params={{ matchId: game.match_id }}
        search={{ player: playerSearchValue(lead) }}
        aria-label={label}
        className={cn(
          "group relative flex min-w-0 items-center gap-3 overflow-hidden rounded-xl border bg-gradient-to-r py-2.5 pr-2 pl-4",
          "bg-surface-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
          styles.wash,
          styles.border,
          styles.hoverBorder,
        )}
      >
        <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-1", styles.stripe)} />

        {/* Champions: one with its level when solo, an overlapping row for a group. */}
        <span aria-hidden="true" className="flex shrink-0 items-center">
          {solo ? (
            <ChampionIcon champion={lead.champion_name} size="md" level={lead.champ_level} />
          ) : (
            <span className="flex -space-x-2">
              {members.map((m) => (
                <ChampionIcon key={m.puuid} champion={m.champion_name} size="sm" shape="circle" className="ring-2 ring-surface-1" />
              ))}
            </span>
          )}
        </span>

        {/* Who, and how it went. */}
        <span aria-hidden="true" className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex min-w-0 items-baseline gap-1.5 text-sm">
            {solo ? (
              <>
                <span className="truncate font-semibold text-text">{names}</span>
                <span className="shrink-0 truncate text-xs text-text-muted">{championDisplayName(lead.champion_name)}</span>
              </>
            ) : (
              <>
                <span className="shrink-0 rounded-full border border-gold/35 bg-gold/10 px-1.5 text-[10px] font-bold tracking-wide text-gold uppercase">
                  {groupLabel(members.length)}
                </span>
                <span className="truncate font-medium text-text">{names}</span>
              </>
            )}
          </span>
          <span className="flex min-w-0 items-center gap-2 text-xs">
            {solo ? (
              <KdaLine kills={lead.kills} deaths={lead.deaths} assists={lead.assists} className="font-semibold" />
            ) : line && verdict ? (
              <span className={cn("truncate font-semibold", isPraise(verdict.tier) ? "text-gold-bright" : "text-loss")}>{line}</span>
            ) : (
              <span className="truncate text-text-secondary">Queued together</span>
            )}
          </span>
        </span>

        {/* Result, score and when. */}
        <span aria-hidden="true" className="flex shrink-0 flex-col items-end gap-1 text-right">
          <span className="flex items-center gap-2">
            {solo ? <AiScoreBadge score={lead.ai_score} size="sm" tooltip={false} /> : null}
            <span className={cn("text-xs font-semibold", styles.text)}>{OUTCOME_LABEL[outcome]}</span>
          </span>
          <span className="text-[11px] whitespace-nowrap text-text-muted tabular-nums">
            {queue} · {formatDuration(game.game_duration)} · {when}
          </span>
        </span>

        <ChevronRight
          aria-hidden="true"
          className="size-4 shrink-0 text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-text-secondary"
        />
      </Link>
    </DdragonPatch>
  );
}
