import { Link } from "@tanstack/react-router";
import { TrendingDown, TrendingUp } from "lucide-react";

import type { SquadPlayer } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { cn } from "@/lib/cn";
import { formatPercent, formatSigned, plural } from "@/lib/format";
import { formatRiotId, summonerParams } from "@/lib/riotId";

import { WinLoss } from "./DetailParts";
import { DUO_LIST_MIN_GAMES, type DuoEntry } from "./model";

const COPY = {
  best: {
    title: "Best duos",
    icon: TrendingUp,
    eyebrow: "Beat their usual win rates",
    empty: "No duo is beating their usual win rates yet.",
  },
  worst: {
    title: "Worst duos",
    icon: TrendingDown,
    eyebrow: "Fell short of their usual win rates",
    empty: "No duo is falling short of their usual win rates.",
  },
} as const;

function PlayerLink({ player, label }: { player: SquadPlayer; label: string }) {
  return (
    <Link
      to="/summoner/$region/$riotId"
      params={summonerParams(player.game_name, player.tag_line)}
      title={formatRiotId(player.game_name, player.tag_line)}
      className="focus-ring max-w-full truncate rounded-sm font-semibold text-text transition-colors hover:text-gold-bright"
    >
      {label}
    </Link>
  );
}

/** Top duos by win rate together minus expected (at least {@link DUO_LIST_MIN_GAMES} games). */
export function DuoListCard({
  kind,
  entries,
  labels,
  className,
}: {
  kind: "best" | "worst";
  entries: readonly DuoEntry[];
  labels: ReadonlyMap<string, string>;
  className?: string;
}) {
  const copy = COPY[kind];
  const name = (player: SquadPlayer) => labels.get(player.puuid) ?? player.game_name;
  return (
    <GlowCard className={cn("flex flex-col gap-3 p-4 sm:p-5", className)}>
      <SectionHeader size="sm" icon={copy.icon} eyebrow={copy.eyebrow} title={copy.title} />
      {entries.length === 0 ? (
        <EmptyState
          compact
          icon={copy.icon}
          title={copy.empty}
          description={`Duos need at least ${DUO_LIST_MIN_GAMES} games together to be listed.`}
        />
      ) : (
        <ol className="flex flex-col divide-y divide-border">
          {entries.map(({ a, b, pair }) => (
            <li key={`${pair.a_puuid}-${pair.b_puuid}`} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <span className="flex shrink-0 -space-x-2" aria-hidden="true">
                <ProfileIcon iconId={a.profile_icon_id} size="sm" alt="" />
                <ProfileIcon iconId={b.profile_icon_id} size="sm" alt="" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-sm">
                  <PlayerLink player={a} label={name(a)} />
                  <span className="shrink-0 text-text-muted" aria-hidden="true">
                    +
                  </span>
                  <span className="sr-only">and</span>
                  <PlayerLink player={b} label={name(b)} />
                </div>
                <span className="text-xs text-text-secondary tabular-nums">
                  {plural(pair.games, "game")} · <WinLoss wins={pair.wins} losses={pair.games - pair.wins} />
                </span>
              </div>
              <div className="flex shrink-0 flex-col items-end leading-tight">
                <span className="font-display text-base font-semibold text-text tabular-nums">
                  {formatPercent(pair.winrate)}
                </span>
                <span
                  className="text-[11px] text-text-secondary tabular-nums"
                  title={`Expected ${formatPercent(pair.expected_winrate)} from their usual win rates`}
                >
                  {formatSigned(Math.round(pair.winrate_delta * 100))} vs usual
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </GlowCard>
  );
}
