import { Link } from "@tanstack/react-router";
import { ArrowRight, ChevronRight, Swords } from "lucide-react";

import { useMatchHistory } from "@/api/queries";
import type { MatchSummary } from "@/api/types";
import { ChampionIcon, DdragonPatch, EmptyState, ErrorState, GlowCard, ItemSlots, SectionHeader, SpellIcons } from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import {
  formatDateTime,
  formatDecimal,
  formatDuration,
  formatDurationLong,
  formatKdaRatio,
  formatPercent,
  timeAgoShort,
} from "@/lib/format";
import { queueShortLabel } from "@/lib/queues";
import { toScore100 } from "@/lib/score";
import { championDisplayName } from "@/lib/champions";
import { playerSearchValue } from "@/components/match/focus";
import { AiScoreWithRank } from "@/components/match/MatchBits";
import { RolePercentileLabel } from "@/components/common/RolePercentile";

import { useNow } from "./hooks";

const ROWS = 5;

export interface RecentGamesCardProps {
  puuid: string;
  onSeeAll: () => void;
}

/** First five games of the match history as compact rows, with a jump to the Matches tab. */
export function RecentGamesCard({ puuid, onSeeAll }: RecentGamesCardProps) {
  const history = useMatchHistory(puuid);
  const now = useNow(60_000);
  const games = history.data?.pages[0]?.items.slice(0, ROWS) ?? [];

  return (
    <GlowCard className="flex flex-col gap-3 p-4 sm:p-5">
      <SectionHeader
        title="Recent games"
        eyebrow="Latest matches"
        icon={Swords}
        action={
          <Button variant="ghost" size="sm" onClick={onSeeAll} className="text-gold hover:text-gold-bright">
            See all matches
            <ArrowRight aria-hidden="true" />
          </Button>
        }
      />
      {history.isPending ? (
        <div className="flex flex-col gap-2" role="status" aria-label="Loading recent games">
          {Array.from({ length: ROWS }, (_, i) => (
            <RecentGameSkeleton key={i} />
          ))}
        </div>
      ) : history.isError ? (
        <ErrorState compact error={history.error} title="Couldn't load recent games" onRetry={() => void history.refetch()} />
      ) : games.length === 0 ? (
        <EmptyState
          compact
          icon={Swords}
          title="No games stored yet"
          description="Hit Update to pull this player's latest matches from Riot."
        />
      ) : (
        <ul className="flex flex-col gap-2" aria-label="Recent games">
          {games.map((game) => (
            <li key={game.match_id}>
              <RecentGameRow game={game} now={now} />
            </li>
          ))}
        </ul>
      )}
    </GlowCard>
  );
}

type Outcome = "win" | "loss" | "remake";

const OUTCOME: Record<Outcome, { label: string; text: string; bar: string; row: string }> = {
  win: { label: "Victory", text: "text-win", bar: "bg-win", row: "bg-win-tint" },
  loss: { label: "Defeat", text: "text-loss", bar: "bg-loss", row: "bg-loss-tint" },
  remake: { label: "Remake", text: "text-remake", bar: "bg-remake", row: "bg-remake-tint" },
};

function RecentGameRow({ game, now }: { game: MatchSummary; now: number }) {
  const me = game.me;
  const outcome: Outcome = game.remake ? "remake" : me.win ? "win" : "loss";
  const style = OUTCOME[outcome];
  const champion = championDisplayName(me.champion_name);
  const queue = queueShortLabel(game.queue_id, game.game_mode);
  const summary = `${style.label} as ${champion}, ${me.kills} kills, ${me.deaths} deaths, ${me.assists} assists, ${queue}, ${formatDurationLong(game.game_duration)}, ${formatDateTime(game.game_start)}${me.ai_score !== null ? `, AI Score ${toScore100(me.ai_score)}` : ""}`;

  return (
    <DdragonPatch patch={game.patch}>
    <Link
      to="/match/$matchId"
      params={{ matchId: game.match_id }}
      search={{ player: playerSearchValue(me) }}
      aria-label={summary}
      className={cn(
        "group relative flex items-center gap-3 overflow-hidden rounded-xl border border-border py-2 pr-2 pl-4 sm:gap-4 sm:pr-3",
        "transition-[border-color,background-color,transform] duration-150 ease-out hover:-translate-y-px hover:border-border-strong hover:bg-surface-2",
        style.row,
      )}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", style.bar)} />

      <div className="flex w-[4.25rem] shrink-0 flex-col leading-tight">
        <span className={cn("text-sm font-semibold", style.text)}>{style.label}</span>
        <span className="truncate text-[11px] text-text-muted">{queue}</span>
        <span className="text-[11px] text-text-muted tabular-nums">{formatDuration(game.game_duration)}</span>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <ChampionIcon champion={me.champion_name} size="md" level={me.champ_level} />
        <SpellIcons spell1={me.summoner1_id} spell2={me.summoner2_id} size="sm" className="hidden sm:flex" />
      </div>

      <div className="flex min-w-0 flex-1 flex-col leading-tight">
        <span className="font-display text-[14px] font-semibold whitespace-nowrap tabular-nums text-text sm:text-[15px]">
          {me.kills}
          <span className="mx-0.5 text-text-muted sm:mx-1">/</span>
          <span className="text-loss">{me.deaths}</span>
          <span className="mx-0.5 text-text-muted sm:mx-1">/</span>
          {me.assists}
        </span>
        <span className="truncate text-xs text-text-secondary tabular-nums">
          {formatKdaRatio(me.kda, me.deaths)} KDA
          <span className="hidden sm:inline"> · {formatPercent(me.kill_participation)} KP</span>
        </span>
      </div>

      <ItemSlots items={me.items} size="sm" className="hidden xl:flex" />

      <div className="hidden w-14 shrink-0 flex-col text-right text-xs leading-tight text-text-secondary tabular-nums sm:flex">
        <span className="text-text">{me.cs} CS</span>
        <span>{formatDecimal(me.cs_per_min, 1)}/m</span>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1">
        <AiScoreWithRank participant={me} teams={game.teams} remake={game.remake} size="sm" />
        <span className="flex items-baseline gap-1.5">
          <RolePercentileLabel
            percentile={me.ai_role_percentile}
            position={me.team_position}
            tooltip={false}
            className="hidden sm:inline-flex"
          />
          <time dateTime={game.game_start} title={formatDateTime(game.game_start)} className="text-[11px] text-text-muted tabular-nums">
            {timeAgoShort(game.game_start, now)}
          </time>
        </span>
      </div>

      <ChevronRight
        aria-hidden="true"
        className="hidden size-4 shrink-0 text-text-muted transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-text-secondary sm:block"
      />
    </Link>
    </DdragonPatch>
  );
}

function RecentGameSkeleton() {
  return (
    <div className="flex h-[62px] items-center gap-3 rounded-xl border border-border py-2 pr-3 pl-4 sm:gap-4" aria-hidden="true">
      <div className="flex w-[4.25rem] shrink-0 flex-col gap-1.5">
        <Skeleton className="h-3.5 w-14" />
        <Skeleton className="h-2.5 w-10" />
      </div>
      <Skeleton className="size-10 shrink-0 rounded-lg" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="h-2.5 w-16" />
      </div>
      <Skeleton className="h-5 w-12 shrink-0 rounded-full" />
    </div>
  );
}
