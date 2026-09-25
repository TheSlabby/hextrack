import { useId } from "react";
import { Hexagon } from "lucide-react";

import type { LiveBan, LiveGame, LiveParticipant, RankEntry, TeamId } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { Stagger, StaggerItem } from "@/components/common/Motion";
import { SpellIcons } from "@/components/common/SpellIcons";
import { TierBadge } from "@/components/common/TierBadge";
import { WinRateBar } from "@/components/common/WinRateBar";
import { PlayerNameLink } from "@/components/match/MatchBits";
import { TEAM_SIDE_LABEL } from "@/components/match/matchUtils";
import { useNow } from "@/components/summoner/hooks";
import { Badge } from "@/components/ui/badge";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatPercent, formatRecord, plural, timeAgo } from "@/lib/format";
import { QUEUE_FLEX, queueLabel } from "@/lib/queues";

import { formatLiveClock, liveElapsedSeconds, partyLabel, rosterByTeam } from "./model";
import { RuneIcons } from "./RuneIcons";

export interface LiveGameViewProps {
  game: LiveGame;
  /** Seconds between the worker's live checks (`LiveGames.interval_seconds`). */
  intervalSeconds: number;
}

const TEAMS: readonly TeamId[] = [100, 200];

const SIDE_STRIPE: Readonly<Record<TeamId, string>> = { 100: "bg-win", 200: "bg-loss" };

const MAP_NAMES: Readonly<Record<number, string>> = {
  11: "Summoner's Rift",
  12: "Howling Abyss",
  21: "Nexus Blitz",
  30: "Rings of Wrath",
};

/** Wide rows: Player | Rank | HexTrack season | This champion | Avg AI. */
const WIDE_COLUMNS =
  "@3xl:grid-cols-[minmax(0,1.7fr)_minmax(0,1.25fr)_minmax(0,1fr)_minmax(0,1fr)_4.5rem] @3xl:items-center @3xl:gap-x-4";

function refreshCopy(intervalSeconds: number): string {
  if (intervalSeconds <= 90) return "refreshes about every minute";
  if (intervalSeconds <= 180) return "refreshes every couple of minutes";
  return `refreshes about every ${Math.round(intervalSeconds / 60)} minutes`;
}

function championOf(p: Pick<LiveParticipant, "champion_name">): string {
  return p.champion_name ? championDisplayName(p.champion_name) : "Unknown champion";
}

function nameOf(p: LiveParticipant): string {
  return p.game_name?.trim() || championOf(p);
}

/** The rank that matters for this queue: flex in flex games, solo otherwise, then the other one. */
function rankFor(p: LiveParticipant, queueId: number | null): { entry: RankEntry | null; label: string | null } {
  const preferFlex = queueId === QUEUE_FLEX;
  const [first, second] = preferFlex ? [p.flex, p.solo] : [p.solo, p.flex];
  const [firstLabel, secondLabel] = preferFlex ? ["Flex", "Solo/Duo"] : ["Solo/Duo", "Flex"];
  if (first) return { entry: first, label: firstLabel };
  if (second) return { entry: second, label: secondLabel };
  return { entry: null, label: null };
}

// --- header -------------------------------------------------------------------------------

function LivePill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-loss/35 bg-loss/12 px-2 py-0.5 text-[11px] leading-4 font-bold tracking-[0.12em] text-loss">
      <span className="relative flex size-2" aria-hidden="true">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-loss opacity-70" />
        <span className="relative inline-flex size-2 rounded-full bg-loss" />
      </span>
      LIVE
    </span>
  );
}

function RosterParties({ game }: { game: LiveGame }) {
  const teams = rosterByTeam(game);
  if (teams.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Roster players in this game">
      {teams.map(({ teamId, players }) => (
        <li
          key={teamId}
          className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-full border border-gold/25 bg-gold/[0.07] py-1 pr-3 pl-2 text-xs"
        >
          <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", SIDE_STRIPE[teamId])} />
          <span className="shrink-0 font-semibold text-text">
            {TEAM_SIDE_LABEL[teamId]} · {partyLabel(players.length)}
          </span>
          <span className="truncate text-gold">{players.map(nameOf).join(", ")}</span>
        </li>
      ))}
    </ul>
  );
}

function LiveHeader({ game, intervalSeconds }: LiveGameViewProps) {
  const now = useNow(1000);
  const elapsed = liveElapsedSeconds(game, now);
  const label = queueLabel(game.queue_id ?? -1, game.game_mode, game.queue_label);
  const map = game.map_id !== null ? MAP_NAMES[game.map_id] : undefined;

  return (
    <GlowCard glow="gold" className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <LivePill />
            {map ? <span className="text-xs text-text-muted">{map}</span> : null}
          </div>
          <h1 className="font-display text-2xl font-semibold text-text sm:text-3xl">{label}</h1>
          <p className="text-xs leading-relaxed text-text-muted">
            Updated {timeAgo(game.seen_at, now)} · {refreshCopy(intervalSeconds)}. Riot doesn&apos;t share kills or gold
            until the game ends.
          </p>
        </div>
        <div className="flex shrink-0 flex-col gap-0.5 sm:items-end">
          <span className="label-caps">Game time</span>
          {elapsed === null ? (
            <span className="animate-pulse-soft font-display text-lg font-semibold text-text-secondary">
              Loading into game
            </span>
          ) : (
            <span
              role="timer"
              aria-label={`Game time ${formatLiveClock(elapsed)}`}
              className="font-display text-3xl leading-none font-bold text-text tabular-nums sm:text-4xl"
            >
              {formatLiveClock(elapsed)}
            </span>
          )}
        </div>
      </div>
      <RosterParties game={game} />
    </GlowCard>
  );
}

// --- bans ---------------------------------------------------------------------------------

function BanIcon({ ban }: { ban: LiveBan }) {
  if (ban.champion_id <= 0) {
    return (
      <span
        className="block size-5 rounded-md border border-dashed border-border-strong"
        role="img"
        aria-label="No ban"
        title="No ban"
      />
    );
  }
  if (!ban.champion_name) {
    return (
      <span
        className="flex size-5 items-center justify-center rounded-md bg-surface-3 text-[10px] font-semibold text-text-muted ring-1 ring-white/10"
        role="img"
        aria-label={`Banned champion ${ban.champion_id}`}
        title={`Champion ${ban.champion_id}`}
      >
        ?
      </span>
    );
  }
  const name = championDisplayName(ban.champion_name);
  return (
    <span className="relative block size-5" role="img" aria-label={`Banned ${name}`} title={`Banned ${name}`}>
      <ChampionIcon champion={ban.champion_name} size="xs" className="opacity-70 grayscale-[0.85]" />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-md bg-[linear-gradient(135deg,transparent_45%,var(--color-loss)_46%,var(--color-loss)_54%,transparent_55%)] opacity-75"
      />
    </span>
  );
}

function LiveBans({ bans, className }: { bans: readonly LiveBan[]; className?: string }) {
  if (bans.length === 0) return null;
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="label-caps">Bans</span>
      <ul className="flex items-center gap-1" aria-label="Bans">
        {bans.map((ban, index) => (
          <li key={`${index}-${ban.champion_id}`}>
            <BanIcon ban={ban} />
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- participants -------------------------------------------------------------------------

function RankBlock({ entry, label }: { entry: RankEntry | null; label: string | null }) {
  if (!entry) return <span className="text-xs font-semibold text-text-muted">Unranked</span>;
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <TierBadge entry={entry} size="sm" />
      <span className="truncate text-[11px] text-text-muted tabular-nums">
        {label} · {formatRecord(entry.wins, entry.losses)} · {formatPercent(entry.winrate)}
      </span>
    </div>
  );
}

function ChampionLine({ p }: { p: LiveParticipant }) {
  if (p.season_games === 0) return null;
  const champ = championOf(p);
  if (p.champion_games === 0) {
    return <span className="text-text-muted">First time on {champ} this season</span>;
  }
  return (
    <span className="text-text-secondary tabular-nums">
      <span className="text-text-muted">{champ}: </span>
      {plural(p.champion_games, "game")} · {formatPercent(p.champion_wins / p.champion_games)}
    </span>
  );
}

function AvgAi({ p, className }: { p: LiveParticipant; className?: string }) {
  if (p.avg_ai_score === null) return null;
  return (
    <AiScoreBadge
      score={p.avg_ai_score}
      kind="average"
      size="sm"
      detail={`Season average over HexTrack's stored ranked games (${p.season_games}).`}
      className={className}
    />
  );
}

function LiveParticipantRow({ p, queueId }: { p: LiveParticipant; queueId: number | null }) {
  const rank = rankFor(p, queueId);
  const known = p.season_games > 0;
  const nameParticipant = {
    game_name: p.bot ? null : p.game_name,
    tag_line: p.bot ? null : p.tag_line,
    champion_name: p.champion_name ?? "",
    is_tracked: p.is_tracked,
  };

  return (
    <li
      className={cn(
        "flex flex-col gap-2 px-3 py-2.5 @3xl:grid @3xl:py-2 sm:px-4",
        WIDE_COLUMNS,
        p.is_tracked && "bg-gold/[0.05] shadow-[inset_2px_0_0_var(--color-gold)]",
      )}
    >
      {/* Player: champion, spells, runes, name (+ rank and avg AI on narrow rows). */}
      <div className="flex min-w-0 items-center gap-2">
        <ChampionIcon champion={p.champion_name ?? ""} size="md" highlight={p.is_tracked} />
        <SpellIcons spell1={p.spell1_id} spell2={p.spell2_id} size="sm" />
        <RuneIcons
          keystoneId={p.keystone_id}
          primaryStyleId={p.primary_style_id}
          secondaryStyleId={p.secondary_style_id}
        />
        <div className="ml-0.5 flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex min-w-0 items-center gap-1.5">
            {p.game_name || p.champion_name ? (
              <PlayerNameLink participant={nameParticipant} showTrackedMark className="text-[13px]" />
            ) : (
              <span className="text-[13px] font-medium text-text-secondary">Unknown player</span>
            )}
            {p.bot ? (
              <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
                Bot
              </Badge>
            ) : null}
          </div>
          <span className="truncate text-[11px] text-text-muted">{championOf(p)}</span>
          <div className="@3xl:hidden">
            {rank.entry ? (
              <TierBadge entry={rank.entry} size="sm" emblem={false} />
            ) : (
              <span className="text-xs font-semibold text-text-muted">Unranked</span>
            )}
          </div>
        </div>
        <AvgAi p={p} className="shrink-0 @3xl:hidden" />
      </div>

      {/* Rank (wide rows only; narrow rows show it under the name). */}
      <div className="hidden min-w-0 @3xl:block">
        <span className="sr-only">Rank: </span>
        <RankBlock entry={rank.entry} label={rank.label} />
      </div>

      {/* Narrow: one wrapped caption line. Wide: `contents`, so each part is its own column. */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] @3xl:contents",
          !known && !rank.entry && "hidden",
        )}
      >
        {rank.entry ? (
          <span className="text-text-muted tabular-nums @3xl:hidden">
            {rank.label} {formatRecord(rank.entry.wins, rank.entry.losses)} · {formatPercent(rank.entry.winrate)}
          </span>
        ) : null}
        <div className={cn("min-w-0", !known && "hidden @3xl:block")}>
          <span className="sr-only">HexTrack season: </span>
          {known ? (
            <>
              <span className="text-text-secondary tabular-nums @3xl:hidden">
                <span className="text-text-muted">HexTrack </span>
                {formatRecord(p.season_wins, p.season_games - p.season_wins)} ·{" "}
                {formatPercent(p.season_wins / p.season_games)}
              </span>
              <WinRateBar
                wins={p.season_wins}
                losses={p.season_games - p.season_wins}
                size="sm"
                className="hidden @3xl:flex"
              />
            </>
          ) : (
            <span className="text-xs text-text-muted">No games on HexTrack</span>
          )}
        </div>
        <div className={cn("min-w-0 @3xl:text-xs", !known && "hidden @3xl:block")}>
          <span className="sr-only">On this champion: </span>
          {known ? <ChampionLine p={p} /> : <span className="text-text-muted">–</span>}
        </div>
        <div className="hidden justify-end @3xl:flex">
          <span className="sr-only">Average AI Score: </span>
          {p.avg_ai_score !== null ? <AvgAi p={p} /> : <span className="text-xs text-text-muted">–</span>}
        </div>
      </div>
    </li>
  );
}

// --- team panel ---------------------------------------------------------------------------

function LiveTeamPanel({ game, teamId }: { game: LiveGame; teamId: TeamId }) {
  const headingId = useId();
  const players = game.participants.filter((p) => p.team_id === teamId);
  const roster = players.filter((p) => p.is_tracked).length;
  const bans = game.bans.filter((b) => b.team_id === teamId);
  if (players.length === 0) return null;

  return (
    <GlowCard asChild className="overflow-hidden">
      <section aria-labelledby={headingId}>
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-3 py-3 sm:px-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <span aria-hidden="true" className={cn("h-5 w-1 rounded-full", SIDE_STRIPE[teamId])} />
            <h2 id={headingId} className="font-display text-base font-semibold whitespace-nowrap text-text">
              {TEAM_SIDE_LABEL[teamId]}
            </h2>
            {roster > 0 ? (
              <Badge variant="default">
                <Hexagon aria-hidden="true" className="fill-gold/25" />
                Roster {partyLabel(roster).toLowerCase()}
              </Badge>
            ) : null}
          </div>
          <LiveBans bans={bans} className="ml-auto" />
        </header>
        <div className="@container">
          <div
            aria-hidden="true"
            className={cn("hidden border-b border-border px-3 py-1.5 sm:px-4 @3xl:grid", WIDE_COLUMNS)}
          >
            <span className="label-caps">Player</span>
            <span className="label-caps">Rank</span>
            <span className="label-caps">HexTrack season</span>
            <span className="label-caps">This champion</span>
            <span className="label-caps text-right">Avg AI</span>
          </div>
          <ul className="divide-y divide-border">
            {players.map((p, index) => (
              <LiveParticipantRow key={p.puuid ?? `bot-${index}`} p={p} queueId={game.queue_id} />
            ))}
          </ul>
        </div>
      </section>
    </GlowCard>
  );
}

/** Live game: header (queue, timer, roster parties) and both teams, blue side first. */
export function LiveGameView({ game, intervalSeconds }: LiveGameViewProps) {
  return (
    <Stagger className="flex min-w-0 flex-col gap-4 sm:gap-5">
      <StaggerItem>
        <LiveHeader game={game} intervalSeconds={intervalSeconds} />
      </StaggerItem>
      {TEAMS.map((teamId) => (
        <StaggerItem key={teamId}>
          <LiveTeamPanel game={game} teamId={teamId} />
        </StaggerItem>
      ))}
    </Stagger>
  );
}
