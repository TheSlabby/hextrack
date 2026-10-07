import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Users } from "lucide-react";

import { useChampionSquad } from "@/api/queries";
import type { ChampionSquadRow, LeaderboardQueue } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { PositionIcon } from "@/components/common/PositionIcon";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SkeletonRows } from "@/components/common/Skeletons";
import { WinRateBar } from "@/components/common/WinRateBar";
import { RiotIdText } from "@/components/leaderboard/parts";
import { playerSearchValue } from "@/components/match/focus";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDateTime, formatKdaRatio, plural, timeAgo } from "@/lib/format";
import { positionLabel } from "@/lib/positions";
import { summonerParams } from "@/lib/riotId";

import { DetailCard } from "./DetailCard";
import { ShareChampionButton } from "./ShareChampionButton";

const QUEUE_PHRASE: Readonly<Record<LeaderboardQueue, string>> = {
  all: "ranked",
  solo: "Solo/Duo",
  flex: "Flex",
};

function LastPlayed({ row, className }: { row: ChampionSquadRow; className?: string }) {
  return (
    <Link
      to="/match/$matchId"
      params={{ matchId: row.last_match_id }}
      search={{ player: playerSearchValue(row) }}
      title={`Last game ${formatDateTime(row.last_played)}`}
      className={cn(
        "rounded-sm text-xs whitespace-nowrap text-text-secondary transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        className,
      )}
    >
      {timeAgo(row.last_played)}
    </Link>
  );
}

function SquadRow({ row, champion, queue }: { row: ChampionSquadRow; champion: string; queue: LeaderboardQueue }) {
  const losses = row.games - row.wins;
  const name =
    row.game_name && row.tag_line ? (
      <Link
        to="/summoner/$region/$riotId"
        params={summonerParams(row.game_name, row.tag_line)}
        className="min-w-0 rounded-sm transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
      >
        <RiotIdText gameName={row.game_name} tagLine={row.tag_line} />
      </Link>
    ) : (
      <span className="truncate font-semibold text-text-secondary">Unknown player</span>
    );

  return (
    <li className="flex flex-col gap-2.5 rounded-xl border border-border bg-surface-2/40 px-3 py-2.5 md:flex-row md:items-center md:gap-4">
      <div className="flex min-w-0 items-center gap-3 md:w-64 md:flex-none">
        <ProfileIcon iconId={row.profile_icon_id} size="sm" alt="" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {name}
          <span className="flex items-center gap-1 text-xs text-text-muted">
            <PositionIcon position={row.main_position} size={12} title="" />
            {positionLabel(row.main_position)} · {plural(row.games, "game")}
          </span>
        </div>
        <LastPlayed row={row} className="shrink-0 md:hidden" />
        <ShareChampionButton champion={champion} puuid={row.puuid} queue={queue} className="-my-1 -mr-1 md:hidden" />
      </div>
      <div className="flex min-w-0 items-center gap-4 md:flex-1">
        <WinRateBar wins={row.wins} losses={losses} size="sm" className="min-w-0 flex-1 md:max-w-56" />
        <div className="flex w-12 shrink-0 flex-col text-right">
          <span className="text-sm font-semibold text-text tabular-nums">{formatKdaRatio(row.kda)}</span>
          <span className="text-[11px] text-text-muted">KDA</span>
        </div>
        <div className="flex w-14 shrink-0 justify-end">
          <AiScoreBadge
            score={row.avg_ai_score}
            kind="average"
            size="sm"
            detail={`Over ${plural(row.games, "game")} on ${championDisplayName(champion)}.`}
          />
        </div>
      </div>
      <LastPlayed row={row} className="hidden w-24 shrink-0 text-right md:block" />
      <ShareChampionButton champion={champion} puuid={row.puuid} queue={queue} className="-my-1 -ml-2 hidden md:inline-flex" />
    </li>
  );
}

/** Roster players who have played this champion in ranked this season (any patch). */
export function ChampionSquad({ champion, queue }: { champion: string; queue: LeaderboardQueue }) {
  const query = useChampionSquad(champion, queue);
  const name = championDisplayName(query.data?.champion_name ?? champion);
  const rows = query.data?.rows ?? [];

  let body: ReactNode;
  if (query.isPending) {
    body = <SkeletonRows rows={3} />;
  } else if (query.isError) {
    body = <ErrorState compact error={query.error} title="Couldn't load the squad" onRetry={() => void query.refetch()} />;
  } else if (rows.length === 0) {
    body = (
      <EmptyState
        compact
        icon={Users}
        title={`Nobody in the squad has played ${name} in ${QUEUE_PHRASE[queue]} this season`}
        description="When a roster player locks it in, they'll show up here."
      />
    );
  } else {
    body = (
      <div className="flex flex-col gap-1.5">
        <div className="hidden items-end gap-4 px-3 md:flex" aria-hidden="true">
          <span className="label-caps w-64">Player</span>
          <span className="flex flex-1 items-center gap-4">
            <span className="label-caps flex-1 md:max-w-56">Record</span>
            <span className="label-caps w-12 text-right">KDA</span>
            <span className="label-caps w-14 text-right">Hex avg</span>
          </span>
          <span className="label-caps w-24 text-right">Last game</span>
          <span className="-ml-2 w-7" />
        </div>
        <ul className="flex flex-col gap-1.5">
          {rows.map((row) => (
            <SquadRow key={row.puuid} row={row} champion={query.data?.champion_name ?? champion} queue={queue} />
          ))}
        </ul>
      </div>
    );
  }

  return (
    <DetailCard
      title={`The squad on ${name}`}
      icon={Users}
      description={`Roster players' ${QUEUE_PHRASE[queue]} games on ${name} this season, on any patch.`}
    >
      {body}
    </DetailCard>
  );
}
