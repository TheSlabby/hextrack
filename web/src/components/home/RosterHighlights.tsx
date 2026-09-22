import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import { Flame, Handshake, Swords, TrendingUp } from "lucide-react";

import type { LeaderboardEntry } from "@/api/types";
import { GlowCard } from "@/components/common/GlowCard";
import { Stagger, StaggerItem } from "@/components/common/Motion";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { RiotIdText } from "@/components/leaderboard/parts";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatInteger, formatLpDelta, formatPercent, formatRecord, plural } from "@/lib/format";
import { summonerParams } from "@/lib/riotId";

import { computeHighlights } from "./highlights";

const VALUE_CLASS = "font-display text-[26px] leading-none font-semibold tabular-nums sm:text-[32px]";

/**
 * Mobile: heading and player on the left, the big value on the right (compact rows).
 * sm and up: a stacked tile (heading, value, player, caption).
 */
const LAYOUT =
  "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 sm:flex sm:h-full sm:flex-col sm:items-stretch";

function CardHeading({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border-strong bg-surface-2 text-gold">
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <span className="label-caps truncate">{label}</span>
    </div>
  );
}

interface HighlightBodyProps {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  valueClassName?: string;
  player: ReactNode;
  caption: ReactNode;
}

function HighlightBody({ icon, label, value, valueClassName, player, caption }: HighlightBodyProps) {
  return (
    <div className={LAYOUT}>
      <CardHeading icon={icon} label={label} />
      <div className={cn(VALUE_CLASS, "row-span-2 text-right sm:mt-4 sm:text-left", valueClassName)}>{value}</div>
      <div className="mt-3 flex min-h-7 min-w-0 items-center gap-2 sm:mt-4">{player}</div>
      <p className="col-span-2 mt-1 min-h-4 truncate text-xs text-text-muted">{caption}</p>
    </div>
  );
}

const CARD_PAD = "h-full p-4 sm:p-5";

interface PlayerCardProps {
  icon: LucideIcon;
  label: string;
  entry: LeaderboardEntry | null;
  value: ReactNode;
  caption: ReactNode;
  valueClassName?: string;
}

/** A highlight about one player; the whole card links to their profile. */
function PlayerHighlightCard({ icon, label, entry, value, caption, valueClassName }: PlayerCardProps) {
  const body = (
    <HighlightBody
      icon={icon}
      label={label}
      value={value}
      valueClassName={valueClassName}
      caption={caption}
      player={
        entry ? (
          <>
            <ProfileIcon iconId={entry.profile_icon_id} size="xs" alt="" />
            <RiotIdText
              gameName={entry.game_name}
              tagLine={entry.tag_line}
              className="text-sm"
              nameClassName="transition-colors group-hover:text-gold-bright"
            />
          </>
        ) : (
          <span className="text-sm text-text-muted">Not enough games yet</span>
        )
      }
    />
  );
  if (!entry) return <GlowCard className={CARD_PAD}>{body}</GlowCard>;
  return (
    <GlowCard asChild interactive className={cn("group block", CARD_PAD)}>
      <Link to="/summoner/$region/$riotId" params={summonerParams(entry.game_name, entry.tag_line)}>
        {body}
      </Link>
    </GlowCard>
  );
}

function PlayerLink({ gameName, tagLine }: { gameName: string; tagLine: string }) {
  return (
    <Link
      to="/summoner/$region/$riotId"
      params={summonerParams(gameName, tagLine)}
      className="min-w-0 truncate rounded-sm font-semibold text-text transition-colors hover:text-gold-bright"
    >
      {gameName}
    </Link>
  );
}

function HighlightSkeleton() {
  return (
    <GlowCard className={CARD_PAD} aria-hidden="true">
      <div className={LAYOUT}>
        <div className="flex items-center gap-2">
          <Skeleton className="size-8 rounded-lg" />
          <Skeleton className="h-3 w-24" />
        </div>
        <Skeleton className="row-span-2 h-[26px] w-16 sm:mt-4 sm:h-8 sm:w-20" />
        <div className="mt-3 flex min-h-7 items-center gap-2 sm:mt-4">
          <Skeleton className="size-5 rounded-full" />
          <Skeleton className="h-3.5 w-28" />
        </div>
        <Skeleton className="col-span-2 mt-1 h-3 w-32" />
      </div>
    </GlowCard>
  );
}

export interface RosterHighlightsProps {
  entries: readonly LeaderboardEntry[];
  isPending: boolean;
  className?: string;
}

/** Small stat cards computed from the leaderboard: best win rate, most games, top climber, best duo. */
export function RosterHighlights({ entries, isPending, className }: RosterHighlightsProps) {
  const header = <SectionHeader eyebrow="Roster highlights" icon={Flame} title="Who's hot this season" />;

  if (isPending) {
    return (
      <section className={cn("flex flex-col gap-5", className)} aria-label="Roster highlights">
        {header}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="status" aria-label="Loading highlights">
          {Array.from({ length: 4 }, (_, i) => (
            <HighlightSkeleton key={i} />
          ))}
        </div>
      </section>
    );
  }

  const h = computeHighlights(entries);
  const duo = h.duo;

  return (
    <section className={cn("flex flex-col gap-5", className)} aria-label="Roster highlights">
      {header}
      <Stagger className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <StaggerItem className="min-w-0">
          <PlayerHighlightCard
            icon={Flame}
            label="Best win rate"
            entry={h.bestWinrate?.entry ?? null}
            value={h.bestWinrate ? formatPercent(h.bestWinrate.value) : "–"}
            caption={
              h.bestWinrate
                ? `${formatRecord(h.bestWinrate.entry.wins, h.bestWinrate.entry.losses)} · min. ${plural(h.winrateMinGames, "game")}`
                : null
            }
            valueClassName={h.bestWinrate && h.bestWinrate.value >= 0.5 ? "text-win" : "text-text"}
          />
        </StaggerItem>
        <StaggerItem className="min-w-0">
          <PlayerHighlightCard
            icon={Swords}
            label="Most games"
            entry={h.mostGames?.entry ?? null}
            value={h.mostGames ? formatInteger(h.mostGames.value) : "–"}
            caption={h.mostGames ? `${formatPercent(h.mostGames.entry.winrate)} win rate this season` : null}
            valueClassName="text-gold-bright"
          />
        </StaggerItem>
        <StaggerItem className="min-w-0">
          <PlayerHighlightCard
            icon={TrendingUp}
            label={h.climber && h.climber.value < 0 ? "Smallest LP drop" : "Biggest LP climb"}
            entry={h.climber?.entry ?? null}
            value={h.climber ? formatLpDelta(h.climber.value) : "–"}
            caption={h.climber ? "Solo/Duo LP since the season started" : null}
            valueClassName={
              h.climber
                ? h.climber.value > 0
                  ? "text-score-a"
                  : h.climber.value < 0
                    ? "text-loss"
                    : "text-text"
                : "text-text"
            }
          />
        </StaggerItem>
        <StaggerItem className="min-w-0">
          <GlowCard className={CARD_PAD}>
            <HighlightBody
              icon={Handshake}
              label="Best duo"
              value={duo ? formatPercent(duo.ally.winrate) : "–"}
              valueClassName={duo ? "text-win" : "text-text"}
              caption={duo ? `${duo.ally.wins}W in ${plural(duo.ally.games, "game")} on the same team` : null}
              player={
                duo ? (
                  <>
                    <span className="flex shrink-0 items-center">
                      <ProfileIcon iconId={duo.entry.profile_icon_id} size="xs" alt="" />
                      <ProfileIcon
                        iconId={duo.allyEntry?.profile_icon_id ?? null}
                        size="xs"
                        alt=""
                        className="-ml-1.5"
                      />
                    </span>
                    <span className="flex min-w-0 items-center gap-1 text-sm">
                      <PlayerLink gameName={duo.entry.game_name} tagLine={duo.entry.tag_line} />
                      <span className="shrink-0 text-text-muted">&amp;</span>
                      <PlayerLink gameName={duo.ally.game_name} tagLine={duo.ally.tag_line} />
                    </span>
                  </>
                ) : (
                  <span className="text-sm text-text-muted">No shared games yet</span>
                )
              }
            />
          </GlowCard>
        </StaggerItem>
      </Stagger>
    </section>
  );
}
