import { Fragment, useMemo, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, CalendarDays, Clock3, SearchX, Sparkles } from "lucide-react";

import { isApiError } from "@/api/client";
import { useMatch } from "@/api/queries";
import type { MatchDetail, ParticipantSummary, TeamDetail } from "@/api/types";
import { AiScoreRing } from "@/components/common/AiScoreRing";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { DdragonPatch } from "@/components/common/DdragonPatch";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GameImage } from "@/components/common/GameImage";
import { GlowCard } from "@/components/common/GlowCard";
import { ItemSlots } from "@/components/common/ItemSlots";
import { Stagger, StaggerItem } from "@/components/common/Motion";
import { RolePercentileLabel } from "@/components/common/RolePercentile";
import { SectionHeader } from "@/components/common/SectionHeader";
import { SpellIcons } from "@/components/common/SpellIcons";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { useDdragon } from "@/lib/ddragon";
import { NON_STACK_QUEUES } from "@/components/stacks/model";
import { formatCompact, formatDateTime, formatDecimal, formatDuration, formatDurationLong, formatPercent } from "@/lib/format";
import { championDisplayName } from "@/lib/champions";

import { playerSearchValue } from "./focus";
import { AiRankingChart, DamageShareChart } from "./MatchCharts";
import { MatchDetailSkeleton } from "./MatchSkeletons";
import { InGameRankPill, KdaLine, KdaRatio, PlayerNameLink } from "./MatchBits";
import { ShareRecapButton } from "./ShareRecapButton";
import { buildGroupRecap, groupMembers, highlightsFor } from "./shareRecap";
import { isPraise } from "./verdicts";
import { TeamPanel } from "./TeamPanel";
import {
  allParticipants,
  inGameRank,
  matchMaxima,
  OUTCOME_LABEL,
  OUTCOME_STYLES,
  outcomeOf,
  TEAM_SIDE_LABEL,
  type Outcome,
} from "./matchUtils";

export interface MatchDetailViewProps {
  matchId: string;
  /** puuid of the player to highlight (their team is listed first). */
  focusPuuid?: string;
  /** Rendered inside an expanded match row: compact header, panels instead of cards, no entrance motion. */
  embedded?: boolean;
}

/** Both teams' scoreboards, objectives, bans, damage share and the AI Score ranking for one match. */
export function MatchDetailView({ matchId, focusPuuid, embedded = false }: MatchDetailViewProps) {
  const query = useMatch(matchId);

  if (query.isPending) return <MatchDetailSkeleton embedded={embedded} />;

  if (query.isError) {
    const notFound = isApiError(query.error) && query.error.isNotFound;
    const error = (
      <ErrorState
        error={query.error}
        compact={embedded}
        title={notFound ? "Match not found" : "Couldn't load this match"}
        onRetry={() => void query.refetch()}
      />
    );
    return embedded ? error : <GlowCard>{error}</GlowCard>;
  }

  return <MatchDetailContent match={query.data} focusPuuid={focusPuuid} embedded={embedded} />;
}

function orderTeams(teams: readonly TeamDetail[], focus: ParticipantSummary | undefined): TeamDetail[] {
  return [...teams].sort((a, b) => {
    if (focus) {
      if (a.team_id === focus.team_id) return -1;
      if (b.team_id === focus.team_id) return 1;
    }
    return a.team_id - b.team_id;
  });
}

function MatchDetailContent({ match, focusPuuid, embedded }: { match: MatchDetail; focusPuuid?: string; embedded: boolean }) {
  const maxima = useMemo(() => matchMaxima(match), [match]);
  const focus = useMemo(
    () => (focusPuuid ? allParticipants(match).find((p) => p.puuid === focusPuuid) : undefined),
    [match, focusPuuid],
  );
  const teams = useMemo(() => orderTeams(match.teams, focus), [match.teams, focus]);
  const minutes = match.game_duration / 60;

  if (match.teams.length === 0) {
    const empty = (
      <EmptyState
        icon={SearchX}
        compact={embedded}
        title="No player data for this match"
        description="The stored match has no participants. It may have been imported from an incomplete record."
      />
    );
    return embedded ? empty : <GlowCard>{empty}</GlowCard>;
  }

  const sections: Array<{ key: string; node: ReactNode }> = [
    {
      key: "header",
      node: embedded ? <EmbeddedHeader match={match} focus={focus} /> : <MatchHero match={match} focus={focus} />,
    },
    ...teams.map((team) => ({
      key: `team-${team.team_id}`,
      node: (
        <TeamPanel
          team={team}
          teams={match.teams}
          remake={match.remake}
          maxima={maxima}
          minutes={minutes}
          focusPuuid={focusPuuid}
          embedded={embedded}
        />
      ),
    })),
    {
      key: "charts",
      node: (
        <div className={cn("grid @3xl:grid-cols-2", embedded ? "gap-3" : "gap-6")}>
          <ChartPanel
            embedded={embedded}
            eyebrow="Combat"
            title="Damage share"
            description="Each player's share of their team's damage to champions."
          >
            <DamageShareChart match={match} teams={teams} focusPuuid={focusPuuid} />
          </ChartPanel>
          <ChartPanel
            embedded={embedded}
            ai
            eyebrow="AI Score"
            title="AI Score ranking"
            description="All ten players by how often their stat line wins."
          >
            <AiRankingChart match={match} focusPuuid={focusPuuid} />
          </ChartPanel>
        </div>
      ),
    },
  ];

  // The game's own patch, so items and spells that have since been removed still have icons.
  if (embedded) {
    return (
      <DdragonPatch patch={match.patch}>
        <div className="@container flex min-w-0 flex-col gap-3">
          {sections.map((section) => (
            <Fragment key={section.key}>{section.node}</Fragment>
          ))}
        </div>
      </DdragonPatch>
    );
  }
  return (
    <DdragonPatch patch={match.patch}>
      <Stagger className="@container flex min-w-0 flex-col gap-6">
        {sections.map((section) => (
          <StaggerItem key={section.key} className="min-w-0">
            {section.node}
          </StaggerItem>
        ))}
      </Stagger>
    </DdragonPatch>
  );
}

// --- headers ------------------------------------------------------------------------------

function heroParticipant(match: MatchDetail, focus: ParticipantSummary | undefined): ParticipantSummary | undefined {
  if (focus) return focus;
  const players = allParticipants(match);
  return players.find((p) => p.ai_rank === 1) ?? match.teams.find((t) => t.win)?.participants[0] ?? players[0];
}

function MatchHero({ match, focus }: { match: MatchDetail; focus: ParticipantSummary | undefined }) {
  const dd = useDdragon();
  const hero = heroParticipant(match, focus);
  const winner = match.teams.find((t) => t.win);
  const outcome: Outcome = focus ? outcomeOf(match.remake, focus.win) : match.remake ? "remake" : "win";
  const title = focus || match.remake || !winner ? OUTCOME_LABEL[outcome] : `${TEAM_SIDE_LABEL[winner.team_id]} victory`;

  return (
    <GlowCard className="relative overflow-hidden">
      {hero ? (
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
          <GameImage
            src={dd.championSplash(hero.champion_name)}
            alt=""
            loading="eager"
            className="absolute inset-y-0 right-0 h-full w-full object-cover object-[70%_22%] opacity-50 [mask-image:linear-gradient(to_left,black_30%,transparent_95%)] sm:w-4/5"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-surface-1 via-surface-1/30 to-transparent" />
          <div className="absolute inset-0 bg-gradient-to-r from-surface-1/85 via-surface-1/35 to-transparent" />
        </div>
      ) : null}
      <div className="relative flex flex-col gap-5 p-5 sm:p-6 @3xl:flex-row @3xl:items-end @3xl:justify-between">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex items-start justify-between gap-3">
            <span className="label-caps pt-1.5 text-text-secondary">
              {match.queue_label} · Patch {match.patch}
            </span>
            {hero ? <ShareRecapButton match={match} player={hero} className="@3xl:hidden" /> : null}
          </div>
          {focus ? <HeroPlayerName match={match} player={focus} /> : null}
          <h1 className="font-display text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">
            <span className={OUTCOME_STYLES[outcome].text}>{title}</span>
            {focus ? (
              <span className="text-2xl font-medium text-text-secondary sm:text-3xl"> as {championDisplayName(focus.champion_name)}</span>
            ) : null}
          </h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-text-secondary">
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="size-4 text-text-muted" aria-hidden="true" />
              <time dateTime={match.game_start}>{formatDateTime(match.game_start)}</time>
            </span>
            <span className="inline-flex items-center gap-1.5 tabular-nums">
              <Clock3 className="size-4 text-text-muted" aria-hidden="true" />
              <span aria-hidden="true">{formatDuration(match.game_duration)}</span>
              <span className="sr-only">Duration {formatDurationLong(match.game_duration)}</span>
            </span>
            {match.model_version ? (
              <Badge variant="ai">
                <Sparkles aria-hidden="true" />
                Model {match.model_version}
              </Badge>
            ) : null}
          </div>
          {focus ? <HeroPlayerLine match={match} player={focus} /> : null}
        </div>
        <div className="flex flex-col items-start gap-3 self-start @3xl:items-end @3xl:self-stretch @3xl:justify-between">
          {hero ? <ShareRecapButton match={match} player={hero} className="hidden @3xl:block" /> : null}
          <div className="flex flex-wrap items-end gap-4">
            {focus && !match.remake ? <HeroScore match={match} player={focus} /> : null}
            <Scoreline teams={match.teams} remake={match.remake} />
          </div>
        </div>
      </div>
    </GlowCard>
  );
}

/** The focused player's Riot ID above the result, linking to their profile. */
function HeroPlayerName({ match, player }: { match: MatchDetail; player: ParticipantSummary }) {
  const members = groupMembers(match, player);
  const mates = members.slice(1);
  const group = members.length >= 2 ? buildGroupRecap(match, members, null) : null;
  return (
    <div className="-mb-1 flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="flex min-w-0 items-baseline gap-2 font-display text-2xl leading-tight font-semibold sm:text-3xl">
        <PlayerNameLink participant={player} focused className="min-w-0 text-text" />
        {player.game_name && player.tag_line ? (
          <span className="shrink-0 text-lg font-medium text-text-muted sm:text-xl">#{player.tag_line}</span>
        ) : null}
      </span>
      {mates.length > 0 ? (
        <span className="inline-flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-sm text-text-secondary">
          {mates.length === 1 ? "Duo with" : "Squad with"}
          {mates.map((mate, i) => (
            <Fragment key={mate.puuid}>
              <PlayerNameLink participant={mate} />
              {i < mates.length - 1 ? <span aria-hidden="true">·</span> : null}
            </Fragment>
          ))}
        </span>
      ) : null}
      {members.length >= 3 && !NON_STACK_QUEUES.has(match.queue_id) ? (
        <Link
          to="/stacks"
          search={{ size: members.length >= 5 ? undefined : members.length === 4 ? 4 : 3 }}
          className="inline-flex items-center gap-1 rounded-sm text-sm font-medium text-gold transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
        >
          See stacks
          <ArrowUpRight className="size-3.5" aria-hidden="true" />
        </Link>
      ) : null}
      {group?.verdict ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              tabIndex={0}
              className={cn(
                "inline-flex h-6 items-center rounded-full border px-2.5 text-xs font-semibold focus-visible:outline-2 focus-visible:outline-gold",
                group.verdictTier && isPraise(group.verdictTier)
                  ? "border-gold/45 bg-gold/10 text-gold-bright"
                  : "border-loss/45 bg-loss/10 text-loss",
              )}
            >
              {group.verdict}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-64">
            From the teammates' AI Scores. They share the same result, so their scores compare fairly.
          </TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}

/** The focused player's game at a glance: champion, spells, KDA, key stats, items and highlights. */
function HeroPlayerLine({ match, player }: { match: MatchDetail; player: ParticipantSummary }) {
  const minutes = match.game_duration / 60;
  const highlights = match.remake ? [] : highlightsFor(match, player, { limit: 3, skipAiRank: true });
  const stats = [
    { label: "CS", value: `${player.cs}`, detail: `${formatDecimal(player.cs_per_min)}/min` },
    { label: "Kill part.", value: formatPercent(player.kill_participation) },
    { label: "Damage", value: formatCompact(player.damage_to_champions), detail: minutes > 0 ? `${formatCompact(Math.round(player.damage_per_min))}/min` : undefined },
    { label: "Vision", value: `${player.vision_score}` },
  ];
  return (
    <div className="mt-2 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex items-center gap-2">
          <ChampionIcon champion={player.champion_name} size="lg" level={player.champ_level} />
          <SpellIcons spell1={player.summoner1_id} spell2={player.summoner2_id} patch={match.patch} />
        </div>
        <div className="flex flex-col">
          <KdaLine kills={player.kills} deaths={player.deaths} assists={player.assists} className="font-display text-2xl font-semibold" />
          <KdaRatio kda={player.kda} deaths={player.deaths} className="text-sm" />
        </div>
        <dl className="flex flex-wrap gap-x-5 gap-y-2">
          {stats.map((stat) => (
            <div key={stat.label} className="flex flex-col">
              <dt className="text-[11px] font-semibold tracking-[0.08em] text-text-muted uppercase">{stat.label}</dt>
              <dd className="text-sm font-semibold text-text tabular-nums">
                {stat.value}
                {stat.detail ? <span className="ml-1 font-normal text-text-secondary">{stat.detail}</span> : null}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ItemSlots items={player.items} patch={match.patch} size="sm" />
        {highlights.map((text) => (
          <span key={text} className="inline-flex h-6 items-center rounded-full border border-gold/40 bg-gold/10 px-2.5 text-xs font-semibold text-gold-bright">
            {text}
          </span>
        ))}
        <RolePercentileLabel percentile={player.ai_role_percentile} position={player.team_position} variant="long" />
      </div>
    </div>
  );
}

/** The focused player's AI Score ring with the MVP / ACE / #N pill under it. */
function HeroScore({ match, player }: { match: MatchDetail; player: ParticipantSummary }) {
  if (player.ai_score === null) return null;
  const rank = inGameRank(player, match.teams, match.remake);
  return (
    <div className="flex flex-col items-center gap-1.5 rounded-xl border border-border-strong bg-bg/60 px-3 py-2 backdrop-blur-sm">
      <AiScoreRing score={player.ai_score} size={96} />
      {rank ? <InGameRankPill rank={rank} /> : null}
    </div>
  );
}

function Scoreline({ teams, remake }: { teams: readonly TeamDetail[]; remake: boolean }) {
  const ordered = [...teams].sort((a, b) => a.team_id - b.team_id);
  const label = `Final score: ${ordered.map((t) => `${TEAM_SIDE_LABEL[t.team_id]} ${t.kills}`).join(", ")}`;
  return (
    <div
      role="group"
      aria-label={label}
      className="flex items-center gap-5 self-start rounded-xl border border-border-strong bg-bg/60 px-4 py-3 backdrop-blur-sm @3xl:self-auto"
    >
      {ordered.map((team, index) => {
        const outcome = outcomeOf(remake, team.win);
        return (
          <Fragment key={team.team_id}>
            {index > 0 ? (
              <span aria-hidden="true" className="font-display text-2xl text-text-muted">
                :
              </span>
            ) : null}
            <div className={cn("flex flex-col gap-0.5", index > 0 ? "items-end text-right" : "items-start")} aria-hidden="true">
              <span className="text-[11px] font-semibold tracking-[0.08em] text-text-muted uppercase">
                {TEAM_SIDE_LABEL[team.team_id]} · <span className={OUTCOME_STYLES[outcome].text}>{OUTCOME_LABEL[outcome]}</span>
              </span>
              <span
                className={cn(
                  "font-display text-3xl leading-none font-semibold tabular-nums",
                  team.win && !remake ? "text-text" : "text-text-secondary",
                )}
              >
                {team.kills}
              </span>
              <span className="text-[11px] text-text-muted tabular-nums">{formatCompact(team.gold)} gold</span>
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}

function EmbeddedHeader({ match, focus }: { match: MatchDetail; focus: ParticipantSummary | undefined }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 px-0.5 text-xs text-text-secondary">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold text-text">{match.queue_label}</span>
        <span>Patch {match.patch}</span>
        <time dateTime={match.game_start}>{formatDateTime(match.game_start)}</time>
        <span className="tabular-nums">{formatDurationLong(match.game_duration)}</span>
        {match.model_version ? (
          <span className="inline-flex items-center gap-1 text-cyan">
            <Sparkles className="size-3" aria-hidden="true" />
            Model {match.model_version}
          </span>
        ) : null}
      </div>
      <Link
        to="/match/$matchId"
        params={{ matchId: match.match_id }}
        search={focus ? { player: playerSearchValue(focus) } : {}}
        className="inline-flex items-center gap-1 rounded-sm font-medium text-gold transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
      >
        Full match page
        <ArrowUpRight className="size-3.5" aria-hidden="true" />
      </Link>
    </div>
  );
}

function ChartPanel({
  eyebrow,
  title,
  description,
  embedded,
  ai,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  embedded: boolean;
  ai?: boolean;
  children: ReactNode;
}) {
  const content = (
    <>
      <SectionHeader as="h3" size="sm" eyebrow={eyebrow} title={title} description={description} />
      <div className="mt-4 flex min-w-0 flex-1 flex-col">{children}</div>
    </>
  );
  if (embedded) {
    return <section className="@container flex min-w-0 flex-col rounded-xl border border-border bg-surface-2/40 p-4">{content}</section>;
  }
  return (
    <GlowCard asChild glow={ai ? "cyan" : null} className="@container flex flex-col p-5">
      <section>{content}</section>
    </GlowCard>
  );
}
