/**
 * Unlucky losses and lucky wins: games where the AI Score and the result disagreed. An
 * unlucky loss scored high (the stat line looked like a winning one) but was lost; a lucky
 * win scored low but was won. Rows open the match with this player highlighted.
 */
import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Dices, Sparkles } from "lucide-react";

import { useLuckInsights } from "@/api/queries";
import type { LuckGame, LuckInsights } from "@/api/types";
import { AiScoreExplainer } from "@/components/ai/AiScoreExplainer";
import { AiScoreBadge, ChampionIcon, EmptyState, ErrorState, GlowCard, PositionIcon, SectionHeader } from "@/components/common";
import { RolePercentileLabel } from "@/components/common/RolePercentile";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDurationLong, formatPercent, formatShortDate, plural } from "@/lib/format";
import { ROLE_GAMES, isKnownRole, roleStanding } from "@/lib/rolePercentile";
import { queueShortLabel } from "@/lib/queues";
import { toScore100 } from "@/lib/score";

import { usePlayerSearchValue } from "./hooks";
import { gamesPhrase, type TrendsFilters } from "./model";
import { Refetching } from "./parts";

const LIST_LIMIT = 5;
/** The API's maximum `limit`. */
const EXPANDED_LIMIT = 20;

type LuckKind = "unlucky" | "lucky";

export interface LuckCardProps {
  puuid: string;
  filters: TrendsFilters;
}

export function LuckCard({ puuid, filters }: LuckCardProps) {
  const [expanded, setExpanded] = useState(false);
  const query = useLuckInsights(puuid, { ...filters, limit: expanded ? EXPANDED_LIMIT : LIST_LIMIT });
  const data = query.data;
  const high = data ? toScore100(data.high_threshold) : 60;
  const low = data ? toScore100(data.low_threshold) : 40;

  let body: ReactNode;
  if (query.isPending) {
    body = <LuckSkeleton />;
  } else if (query.isError) {
    body = <ErrorState compact error={query.error} title="Couldn't load these games" onRetry={() => void query.refetch()} />;
  } else if (!data || data.model_version === null) {
    body = (
      <EmptyState
        compact
        tone="ai"
        icon={Sparkles}
        title="No AI model yet"
        description="These lists compare each game's AI Score with its result, so they appear once a model has scored the games."
      />
    );
  } else if (data.losses_scored + data.wins_scored === 0) {
    body = (
      <EmptyState
        compact
        tone="ai"
        icon={Sparkles}
        title="No scored games yet"
        description={`No ${gamesPhrase(filters)} with an AI Score for this player.`}
      />
    );
  } else {
    body = (
      <Refetching active={query.isPlaceholderData}>
        <LuckBody data={data} puuid={puuid} high={high} low={low} expanded={expanded} onExpand={() => setExpanded(true)} />
      </Refetching>
    );
  }

  return (
    <GlowCard glow="cyan" className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader
        eyebrow="AI Score vs result"
        title={
          <span className="inline-flex items-center gap-2">
            <Dices className="size-5 text-cyan" aria-hidden="true" />
            Unlucky losses and lucky wins
          </span>
        }
        description={`Games where the stats and the result disagreed: losses that scored ${high} or more, and wins that scored ${low} or less.`}
        action={<AiScoreExplainer />}
      />
      {body}
    </GlowCard>
  );
}

interface LuckBodyProps {
  data: LuckInsights;
  puuid: string;
  high: number;
  low: number;
  expanded: boolean;
  onExpand: () => void;
}

function LuckBody({ data, puuid, high, low, expanded, onExpand }: LuckBodyProps) {
  const player = usePlayerSearchValue(puuid);
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2 md:gap-5">
        <LuckColumn
          kind="unlucky"
          title="Unlucky losses"
          count={data.unlucky_count}
          of={data.losses_scored}
          ofLabel="scored loss"
          ofPlural="scored losses"
          games={data.unlucky_losses}
          player={player}
          expanded={expanded}
          onExpand={onExpand}
          empty={`No loss scored ${high} or more.`}
        />
        <LuckColumn
          kind="lucky"
          title="Lucky wins"
          count={data.lucky_count}
          of={data.wins_scored}
          ofLabel="scored win"
          ofPlural="scored wins"
          games={data.lucky_wins}
          player={player}
          expanded={expanded}
          onExpand={onExpand}
          empty={`No win scored ${low} or less.`}
        />
      </div>
      <p className="text-xs leading-relaxed text-text-muted">
        The AI Score estimates how often a stat line like this one wins, so an unlucky loss is a game that looked won on
        paper, and a lucky win one that didn&apos;t. Unlucky losses show the highest scores first, lucky wins the lowest.
        &ldquo;Top 27% TOP&rdquo; means the score beat 73% of scored games in that position.
      </p>
    </div>
  );
}

function LuckColumn({
  kind,
  title,
  count,
  of,
  ofLabel,
  ofPlural,
  games,
  player,
  expanded,
  onExpand,
  empty,
}: {
  kind: LuckKind;
  title: string;
  count: number;
  of: number;
  ofLabel: string;
  ofPlural: string;
  games: readonly LuckGame[];
  /** `?player=` value for the match links. */
  player: string;
  expanded: boolean;
  onExpand: () => void;
  empty: string;
}) {
  const share = of > 0 ? count / of : null;
  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-2">
      <div className="flex items-end justify-between gap-3 rounded-xl border border-border bg-surface-2/50 px-3 py-2.5">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="label-caps flex items-center gap-1.5">
            <span aria-hidden="true" className={cn("h-3 w-[3px] rounded-full", kind === "unlucky" ? "bg-loss" : "bg-win")} />
            {title}
          </span>
          <span className="text-xs text-text-muted tabular-nums">
            of {plural(of, ofLabel, ofPlural)}
          </span>
        </div>
        <div className="flex items-baseline gap-2 tabular-nums">
          <span className="font-display text-2xl leading-none font-semibold text-text">{count}</span>
          <span className="text-sm font-semibold text-text-secondary">{share !== null ? formatPercent(share) : "–"}</span>
        </div>
      </div>
      {games.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border-strong px-3 py-5 text-center text-sm text-text-secondary">
          {empty}
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {games.map((game) => (
            <li key={game.match_id}>
              <LuckRow game={game} kind={kind} player={player} />
            </li>
          ))}
        </ul>
      )}
      {count > games.length ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-muted">
          <span className="tabular-nums">
            {expanded ? "Top" : "Showing"} {games.length} of {count}
          </span>
          {expanded ? null : (
            <Button variant="ghost" size="xs" onClick={onExpand} className="text-text-secondary hover:text-text">
              Show up to {EXPANDED_LIMIT}
            </Button>
          )}
        </div>
      ) : null}
    </section>
  );
}

function LuckRow({ game, kind, player }: { game: LuckGame; kind: LuckKind; player: string }) {
  const champion = championDisplayName(game.champion_name);
  const queue = queueShortLabel(game.queue_id);
  const result = kind === "unlucky" ? "Loss" : "Win";
  const percentile =
    game.ai_role_percentile !== null && isKnownRole(game.team_position)
      ? `, ${roleStanding(game.ai_role_percentile).label} of ${ROLE_GAMES[game.team_position]}`
      : "";
  const label = `${result} as ${champion}, ${game.kills} kills, ${game.deaths} deaths, ${game.assists} assists, AI Score ${toScore100(game.ai_score)}${percentile}, ${queue}, ${formatDurationLong(game.duration)}, ${formatDateTime(game.game_start)}`;

  return (
    <Link
      to="/match/$matchId"
      params={{ matchId: game.match_id }}
      search={{ player }}
      aria-label={label}
      className={cn(
        "group relative flex items-center gap-3 overflow-hidden rounded-xl border border-border py-2 pr-2.5 pl-3.5",
        "transition-[border-color,background-color,transform] duration-150 ease-out hover:-translate-y-px hover:border-border-strong hover:bg-surface-2",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        kind === "unlucky" ? "bg-loss-tint" : "bg-win-tint",
      )}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", kind === "unlucky" ? "bg-loss" : "bg-win")} />
      <ChampionIcon champion={game.champion_name} size="sm" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-sm font-semibold text-text">{champion}</span>
          {game.team_position !== "UNKNOWN" ? (
            <PositionIcon position={game.team_position} size={14} className="text-text-muted" title="" />
          ) : null}
        </span>
        <span className="truncate text-xs text-text-muted tabular-nums">
          <span className="font-semibold text-text-secondary">
            {game.kills}/{game.deaths}/{game.assists}
          </span>{" "}
          <span className="hidden min-[420px]:inline">· {queue} </span>·{" "}
          <span title={formatDateTime(game.game_start)}>{formatShortDate(game.game_start)}</span>
        </span>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-0.5">
        <AiScoreBadge score={game.ai_score} size="sm" tooltip={false} />
        <RolePercentileLabel percentile={game.ai_role_percentile} position={game.team_position} size="sm" />
      </div>
    </Link>
  );
}

function LuckSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 md:gap-5" role="status" aria-label="Loading games">
      {Array.from({ length: 2 }, (_, column) => (
        <div key={column} className="flex flex-col gap-2">
          <Skeleton className="h-[3.75rem] rounded-xl" />
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-[3.25rem] rounded-xl" />
          ))}
        </div>
      ))}
    </div>
  );
}
