import { useMemo } from "react";
import { Link } from "@tanstack/react-router";
import { Flame, Hourglass, Skull, Swords, Trophy, Zap, type LucideIcon } from "lucide-react";

import type { StackHighlight, StackSummary } from "@/api/types";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { OUTCOME_LABEL, OUTCOME_STYLES, outcomeOf } from "@/components/match/matchUtils";
import { cn } from "@/lib/cn";
import { queueRowLabel } from "@/lib/queues";
import { formatDate, formatDuration, formatDurationLong, formatShortDate } from "@/lib/format";

import { playerLookup, playerName, playerParam, type PlayerLookup } from "./model";

type HighlightKey = StackHighlight["key"];

interface HighlightMeta {
  title: string;
  /** What the card is the record for. */
  caption: string;
  icon: LucideIcon;
  /** The big figure: the kill score line, or the game clock. */
  hero: "kills" | "duration";
  tone: "gold" | "loss";
}

const HIGHLIGHTS: Readonly<Record<HighlightKey, HighlightMeta>> = {
  biggest_stomp: { title: "Biggest stomp", caption: "Largest kill lead", icon: Swords, hero: "kills", tone: "gold" },
  worst_loss: { title: "Worst loss", caption: "Largest kill deficit", icon: Skull, hero: "kills", tone: "loss" },
  longest_game: { title: "Marathon", caption: "Longest game", icon: Hourglass, hero: "duration", tone: "gold" },
  fastest_win: { title: "Speedrun", caption: "Fastest win", icon: Zap, hero: "duration", tone: "gold" },
  most_team_kills: { title: "Kill fest", caption: "Most team kills", icon: Flame, hero: "kills", tone: "gold" },
};

const TONE: Readonly<Record<HighlightMeta["tone"], string>> = {
  gold: "border-gold/25 bg-gold/10 text-gold",
  loss: "border-loss/30 bg-loss/10 text-loss",
};

/** Overlapping member avatars, capped so a 5-stack still fits a narrow card. */
function MemberIcons({ puuids, lookup }: { puuids: readonly string[]; lookup: PlayerLookup }) {
  return (
    <span className="flex shrink-0 items-center" aria-hidden="true">
      {puuids.map((puuid, index) => (
        <span
          key={puuid}
          className={cn("rounded-full ring-2 ring-surface-1", index > 0 && "-ml-2")}
          style={{ zIndex: puuids.length - index }}
        >
          <ProfileIcon iconId={lookup.get(puuid)?.profile_icon_id} size="sm" alt="" />
        </span>
      ))}
    </span>
  );
}

function HighlightCard({ highlight, lookup }: { highlight: StackHighlight; lookup: PlayerLookup }) {
  const meta = HIGHLIGHTS[highlight.key];
  const outcome = outcomeOf(false, highlight.win);
  const style = OUTCOME_STYLES[outcome];
  const Icon = meta.icon;
  const names = highlight.member_puuids.map((puuid) => playerName(lookup, puuid));
  const first = highlight.member_puuids[0];
  const duration = formatDuration(highlight.game_duration);
  const date = formatShortDate(highlight.game_start);

  const label = [
    `${meta.title}: ${meta.caption.toLowerCase()}`,
    `${OUTCOME_LABEL[outcome]}, ${highlight.team_kills} kills to ${highlight.enemy_kills}`,
    formatDurationLong(highlight.game_duration),
    formatDate(highlight.game_start),
    queueRowLabel(highlight.queue_id, highlight.game_mode, highlight.queue_label),
    `with ${names.join(", ")}`,
  ].join(". ");

  const scoreLine = (
    <span className="inline-flex items-baseline gap-1.5 tabular-nums">
      <span className="text-text">{highlight.team_kills}</span>
      <span className="text-text-muted">–</span>
      <span className="text-text-secondary">{highlight.enemy_kills}</span>
    </span>
  );

  return (
    <GlowCard interactive asChild>
      <Link
        to="/match/$matchId"
        params={{ matchId: highlight.match_id }}
        search={{ player: first ? playerParam(lookup, first) : undefined }}
        aria-label={label}
        className="flex w-full min-w-0 flex-col gap-3 p-4 outline-offset-2"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg border", TONE[meta.tone])}
              aria-hidden="true"
            >
              <Icon className="size-4" />
            </span>
            <span className="flex min-w-0 flex-col leading-tight">
              <span className="truncate font-display font-semibold text-text">{meta.title}</span>
              <span className="truncate text-xs text-text-muted">{meta.caption}</span>
            </span>
          </div>
          <span
            className={cn(
              "inline-flex h-6 shrink-0 items-center rounded-full border px-2 text-xs font-semibold",
              style.chip,
            )}
          >
            {OUTCOME_LABEL[outcome]}
          </span>
        </div>

        <div className="flex items-baseline gap-2">
          {meta.hero === "kills" ? (
            <>
              <span className="font-display text-3xl font-bold">{scoreLine}</span>
              <span className="text-xs text-text-muted">kills</span>
            </>
          ) : (
            <>
              <span className="font-display text-3xl font-bold text-text tabular-nums">{duration}</span>
              <span className="text-sm font-semibold">
                {scoreLine}
                <span className="ml-1 text-xs font-normal text-text-muted">kills</span>
              </span>
            </>
          )}
        </div>

        <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-text-secondary tabular-nums">
          {meta.hero === "kills" ? (
            <>
              <span>{duration}</span>
              <span aria-hidden="true" className="text-text-muted">
                ·
              </span>
            </>
          ) : null}
          <span>{date}</span>
          <span aria-hidden="true" className="text-text-muted">
            ·
          </span>
          <span className="truncate">{queueRowLabel(highlight.queue_id, highlight.game_mode, highlight.queue_label)}</span>
        </p>

        <div className="mt-auto flex min-w-0 items-center gap-2.5 border-t border-border pt-3">
          <MemberIcons puuids={highlight.member_puuids} lookup={lookup} />
          <span className="min-w-0 truncate text-xs text-text-muted">{names.join(", ")}</span>
        </div>
      </Link>
    </GlowCard>
  );
}

/** Record games for the stack: biggest stomp, worst loss, longest, fastest win, most kills. */
export function StackHighlights({ data }: { data: StackSummary }) {
  const lookup = useMemo(() => playerLookup(data), [data]);
  if (data.highlights.length === 0) return null;

  return (
    <section className="flex flex-col gap-3" aria-labelledby="stack-highlights-title">
      <SectionHeader title={<span id="stack-highlights-title">Highlights</span>} icon={Trophy} />
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.highlights.map((highlight) => (
          <li key={`${highlight.key}-${highlight.match_id}`} className="flex min-w-0">
            <HighlightCard highlight={highlight} lookup={lookup} />
          </li>
        ))}
      </ul>
    </section>
  );
}
