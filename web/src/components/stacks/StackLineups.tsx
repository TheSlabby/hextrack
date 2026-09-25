/**
 * Lineups: the best lineup (highest win rate with enough games) and the most played one, then a
 * compact list of the other lineups. A lineup is an exact set of roster players, so with a 3+ or
 * 4+ stack it can hold three to five players.
 */
import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Crown, Repeat, Users } from "lucide-react";

import type { StackLineup, StackPlayer, StackSummary } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { WinRateBar } from "@/components/common/WinRateBar";
import { WinLoss } from "@/components/squad/DetailParts";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatDate, formatPercent, plural, timeAgo } from "@/lib/format";
import { formatRiotId, summonerParams } from "@/lib/riotId";

interface Member {
  puuid: string;
  player: StackPlayer | undefined;
}

function lineupKey(lineup: StackLineup): string {
  return lineup.puuids.join("|");
}

/** Lineup members in roster order (most stack games first) rather than puuid order. */
function membersOf(lineup: StackLineup, players: readonly StackPlayer[]): Member[] {
  const order = new Map(players.map((p, i) => [p.puuid, { player: p, index: i }]));
  return lineup.puuids
    .map((puuid) => ({ puuid, entry: order.get(puuid) }))
    .sort((a, b) => (a.entry?.index ?? Infinity) - (b.entry?.index ?? Infinity))
    .map(({ puuid, entry }) => ({ puuid, player: entry?.player }));
}

function memberName(member: Member): string {
  return member.player?.game_name ?? "Unknown player";
}

/** Overlapping profile icons (decorative: the names follow as text). */
function Faces({ members, size }: { members: readonly Member[]; size: "xs" | "sm" }) {
  return (
    <span className={cn("flex shrink-0", size === "xs" ? "-space-x-1.5" : "-space-x-2")} aria-hidden="true">
      {members.map((m) => (
        <ProfileIcon key={m.puuid} iconId={m.player?.profile_icon_id} size={size} alt="" />
      ))}
    </span>
  );
}

function MemberLink({ member }: { member: Member }) {
  const { player } = member;
  if (!player) return <span className="font-semibold text-text-secondary">Unknown player</span>;
  return (
    <Link
      to="/summoner/$region/$riotId"
      params={summonerParams(player.game_name, player.tag_line)}
      title={formatRiotId(player.game_name, player.tag_line)}
      className="focus-ring max-w-full truncate rounded-sm font-semibold text-text transition-colors hover:text-gold-bright"
    >
      {player.game_name}
    </Link>
  );
}

function LastPlayed({ value }: { value: string }) {
  return (
    <time dateTime={value} title={formatDate(value)} className="text-xs whitespace-nowrap text-text-secondary">
      Last played {timeAgo(value)}
    </time>
  );
}

function FeaturedLineup({
  label,
  icon: Icon,
  lineup,
  players,
}: {
  label: string;
  icon: LucideIcon;
  lineup: StackLineup;
  players: readonly StackPlayer[];
}) {
  const members = membersOf(lineup, players);
  const losses = lineup.games - lineup.wins;
  return (
    <section
      aria-label={label}
      className="flex min-w-0 flex-col gap-3 rounded-xl border border-gold/20 bg-surface-2/60 p-3 sm:p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex items-center gap-1.5">
          <Icon className="size-4 shrink-0 text-gold" aria-hidden="true" />
          <h3 className="label-caps text-gold">{label}</h3>
        </div>
        <LastPlayed value={lineup.last_played} />
      </div>
      <div className="flex min-w-0 items-center gap-3">
        <Faces members={members} size="sm" />
        <p className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-sm">
          {members.map((m, i) => (
            <span key={m.puuid} className="inline-flex min-w-0 items-baseline gap-x-1.5">
              <MemberLink member={m} />
              {i < members.length - 1 ? (
                <span className="text-text-muted" aria-hidden="true">
                  ·
                </span>
              ) : null}
            </span>
          ))}
        </p>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex shrink-0 flex-col leading-tight">
          <span className="font-display text-2xl font-semibold text-text tabular-nums">
            {formatPercent(lineup.winrate)}
          </span>
          <span className="text-[11px] text-text-secondary">win rate</span>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <WinRateBar wins={lineup.wins} losses={losses} showLabels={false} />
          <span className="text-xs text-text-secondary tabular-nums">
            <WinLoss wins={lineup.wins} losses={losses} /> · {plural(lineup.games, "game")}
          </span>
        </div>
      </div>
    </section>
  );
}

function NoBestLineup({ minGames }: { minGames: number }) {
  return (
    <div className="flex min-w-0 items-start gap-3 rounded-xl border border-dashed border-border-strong bg-surface-2/40 p-3 sm:p-4">
      <Crown className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <h3 className="label-caps">Best lineup</h3>
        <p className="text-sm text-text-secondary">
          Play {plural(minGames, "game")} with the same lineup to crown one.
        </p>
      </div>
    </div>
  );
}

function LineupRow({ lineup, players }: { lineup: StackLineup; players: readonly StackPlayer[] }) {
  const members = membersOf(lineup, players);
  const losses = lineup.games - lineup.wins;
  const names = members.map(memberName).join(" · ");
  return (
    <li className="flex min-w-0 items-center gap-3 py-2.5 first:pt-0 last:pb-0">
      <Faces members={members} size="xs" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm leading-snug text-text">{names}</span>
        <LastPlayed value={lineup.last_played} />
      </div>
      <div className="flex shrink-0 flex-col items-end leading-tight">
        <span className="font-display text-base font-semibold text-text tabular-nums">
          {formatPercent(lineup.winrate)}
        </span>
        <span className="text-[11px] tabular-nums">
          <WinLoss wins={lineup.wins} losses={losses} />
        </span>
      </div>
    </li>
  );
}

/** "Other lineups" rows shown before "Show all", so the card stays close to the awards' height. */
const OTHERS_PREVIEW = 3;

export function StackLineups({ data }: { data: StackSummary }) {
  const [showAll, setShowAll] = useState(false);
  const best = data.best_lineup;
  const most = data.most_played_lineup;
  const sameLineup = best !== null && most !== null && lineupKey(best) === lineupKey(most);
  const shown = new Set([best, most].filter((l): l is StackLineup => l !== null).map(lineupKey));
  const others = data.lineups.filter((lineup) => !shown.has(lineupKey(lineup)));

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader
        size="sm"
        icon={Users}
        eyebrow="Who plays best together"
        title="Lineups"
        description="Exact sets of roster players on the same team."
      />
      {most === null && best === null && data.lineups.length === 0 ? (
        <EmptyState compact icon={Users} title="No lineups yet" description="Queue up together to start a record." />
      ) : (
        <>
          <div className="flex flex-col gap-3">
            {sameLineup ? (
              <FeaturedLineup label="Best and most played" icon={Crown} lineup={best} players={data.players} />
            ) : (
              <>
                {best ? (
                  <FeaturedLineup label="Best lineup" icon={Crown} lineup={best} players={data.players} />
                ) : (
                  <NoBestLineup minGames={data.min_lineup_games} />
                )}
                {most ? (
                  <FeaturedLineup label="Most played" icon={Repeat} lineup={most} players={data.players} />
                ) : null}
              </>
            )}
          </div>
          {others.length > 0 ? (
            <div className="flex flex-col gap-2 border-t border-border pt-3">
              <h3 className="label-caps">Other lineups</h3>
              <ol className="flex flex-col divide-y divide-border">
                {(showAll ? others : others.slice(0, OTHERS_PREVIEW)).map((lineup) => (
                  <LineupRow key={lineupKey(lineup)} lineup={lineup} players={data.players} />
                ))}
              </ol>
              {others.length > OTHERS_PREVIEW ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="self-start text-text-secondary"
                  aria-expanded={showAll}
                  onClick={() => setShowAll((v) => !v)}
                >
                  {showAll ? "Show fewer" : `Show all ${others.length}`}
                </Button>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </GlowCard>
  );
}
