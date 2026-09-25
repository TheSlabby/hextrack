import { useMemo } from "react";
import { ArrowDownRight, ArrowUpRight, CircleHelp, Clock, Minus, Skull, Users } from "lucide-react";

import { useHealth, useMatchHistory, useMatchupInsights } from "@/api/queries";
import type { MatchSummary, SummonerProfile } from "@/api/types";
import { AiScoreExplainer } from "@/components/ai/AiScoreExplainer";
import { AiScoreRing, ChampionIcon, ProfileIcon, StreakBadge } from "@/components/common";
import { RolePercentileAverage } from "@/components/common/RolePercentile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { PROFILE_FORM_LIMIT } from "@/lib/streaks";
import { championDisplayName } from "@/lib/champions";
import { formatDate, formatDateTime, formatRecord, formatSigned, plural, timeAgo } from "@/lib/format";
import { isRankedQueue } from "@/lib/queues";
import { toScore100 } from "@/lib/score";

import { CopyLinkButton } from "./CopyLinkButton";
import { useMediaQuery } from "@/lib/hooks";

import { useNow } from "./hooks";
import { ProfileBanner } from "./ProfileBanner";
import { AI_PANEL } from "./layout";
import { platformLabel } from "./summonerFormat";
import { UpdateButton } from "./UpdateButton";

export interface ProfileHeaderProps {
  profile: SummonerProfile;
  region: string;
  /** Switches to the Trends tab (where the full nemesis list lives). */
  onOpenTrends?: () => void;
}

/** Summoner hero: splash banner, identity, Update / copy-link actions and the season AI Score. */
export function ProfileHeader({ profile, region, onOpenTrends }: ProfileHeaderProps) {
  const now = useNow(30_000);
  const updated = profile.last_refreshed_at;

  return (
    <header className="relative isolate pt-2 sm:pt-8">
      <ProfileBanner champion={profile.main_champion} />

      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex min-w-0 items-start gap-4 sm:items-center sm:gap-5">
          <ProfileIcon
            iconId={profile.profile_icon_id}
            level={profile.summoner_level}
            size="xl"
            alt={`${profile.game_name}'s profile icon`}
          />

          <div className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              {profile.is_tracked ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge tabIndex={0} className="cursor-default">
                      <Users aria-hidden="true" />
                      On the roster
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>
                    {profile.tracked_since ? `Tracked since ${formatDate(profile.tracked_since)}. ` : ""}
                    New games are pulled in automatically.
                  </TooltipContent>
                </Tooltip>
              ) : null}
              <Badge variant="secondary">{platformLabel(profile.platform)}</Badge>
              <StreakBadge results={profile.recent_form} limit={PROFILE_FORM_LIMIT} />
              <NemesisBadge puuid={profile.puuid} onOpenTrends={onOpenTrends} />
            </div>

            <h1 className="font-display text-[28px] leading-[1.1] font-bold tracking-tight [overflow-wrap:anywhere] text-text sm:text-4xl">
              {profile.game_name}
              <span className="ml-1.5 text-xl font-medium text-text-muted sm:text-2xl">#{profile.tag_line}</span>
            </h1>

            <p className="flex items-center gap-1.5 text-sm text-text-secondary">
              <Clock className="size-3.5 text-text-muted" aria-hidden="true" />
              {updated ? (
                <time dateTime={updated} title={formatDateTime(updated)}>
                  {/* The clock ticks every 30s, so a fresh refresh can be "ahead" of it: never say "in …". */}
                  Updated {timeAgo(updated, Math.max(now, Date.parse(updated)))}
                </time>
              ) : (
                <span>Never updated</span>
              )}
            </p>

            <div className="mt-1 flex flex-wrap items-center gap-2">
              <UpdateButton profile={profile} />
              <CopyLinkButton gameName={profile.game_name} tagLine={profile.tag_line} region={region} />
            </div>
          </div>
        </div>

        <AiSummary profile={profile} />
      </div>
    </header>
  );
}

/**
 * The lane opponent's champion this player has the worst record against this season (3+
 * games, losing record), from the Trends tab's matchup insights. Nothing when there isn't one.
 */
function NemesisBadge({ puuid, onOpenTrends }: { puuid: string; onOpenTrends?: () => void }) {
  const { data } = useMatchupInsights(puuid);
  const nemesis = data?.nemeses[0];
  if (!nemesis) return null;
  const champion = championDisplayName(nemesis.champion_name);
  const record = formatRecord(nemesis.wins, nemesis.losses);
  const pill = (
    <>
      <Skull className="size-3.5 text-loss" aria-hidden="true" />
      <span className="text-text-secondary">Nemesis</span>
      <ChampionIcon champion={nemesis.champion_name} size="xs" />
      <span className="text-text">{champion}</span>
      <span className="text-loss tabular-nums">{record}</span>
    </>
  );
  const classes =
    "inline-flex h-6 items-center gap-1.5 rounded-full border border-loss/35 bg-loss/[0.08] px-2.5 text-xs font-semibold whitespace-nowrap focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold";
  const label = `Nemesis: ${champion}, ${record} in lane this season`;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {onOpenTrends ? (
          <button type="button" onClick={onOpenTrends} aria-label={`${label}. Open Trends`} className={cn(classes, "cursor-pointer transition-colors hover:border-loss/60")}>
            {pill}
          </button>
        ) : (
          <span tabIndex={0} aria-label={label} className={classes}>
            {pill}
          </span>
        )}
      </TooltipTrigger>
      <TooltipContent className="max-w-64">
        The lane opponent this player has the worst record against this season ({nemesis.games} games).
        {onOpenTrends ? " Click for every matchup in Trends." : ""}
      </TooltipContent>
    </Tooltip>
  );
}

/** Average AI Score of this player's ranked games on the first match-history page. */
function recentRankedAverage(matches: readonly MatchSummary[]): { average: number; games: number } | null {
  const scores = matches
    .filter((m) => !m.remake && isRankedQueue(m.queue_id) && m.me.ai_score !== null)
    .map((m) => m.me.ai_score as number);
  if (scores.length === 0) return null;
  return { average: scores.reduce((sum, s) => sum + s, 0) / scores.length, games: scores.length };
}

function AiSummary({ profile }: { profile: SummonerProfile }) {
  const wide = useMediaQuery("(min-width: 640px)");
  const health = useHealth();
  const history = useMatchHistory(profile.puuid);
  const { avg_ai_score: season, ai_scored_games: scored } = profile.stats;
  const recent = useMemo(() => recentRankedAverage(history.data?.pages[0]?.items ?? []), [history.data]);
  const modelMissing = health.data?.model.loaded === false;
  const trend = season !== null && recent !== null ? toScore100(recent.average) - toScore100(season) : null;

  return (
    <section
      aria-label="Season AI Score"
      className={AI_PANEL}
    >
      <AiScoreRing score={season} kind="average" size={wide ? 124 : 100} label="AI Score" />
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-[11px] leading-4 font-semibold tracking-[0.08em] text-cyan uppercase">Season average</span>
        <p className="line-clamp-3 max-w-60 text-sm leading-snug font-medium text-balance text-text sm:line-clamp-2">
          {season !== null
            ? `A stat line like yours wins about ${toScore100(season)}% of the time.`
            : modelMissing
              ? "No AI model is trained yet."
              : "No scored ranked games yet."}
        </p>
        <p className="line-clamp-2 max-w-60 text-xs leading-relaxed text-text-secondary">
          {season !== null
            ? `${plural(scored, "scored ranked game")} this season`
            : modelMissing
              ? "Scores appear once a model is trained."
              : "Every ranked game gets a score."}
        </p>
        {season !== null ? (
          <RolePercentileAverage
            percentile={profile.stats.avg_ai_role_percentile}
            games={scored}
            size="md"
            className="w-fit"
          />
        ) : null}
        {recent && trend !== null ? (
          <p className="flex items-center gap-1 text-xs text-text-secondary tabular-nums">
            <TrendIcon delta={trend} />
            <span>
              Last {recent.games}: <span className="font-semibold text-text">{toScore100(recent.average)}</span>
              <span className="text-text-muted"> ({formatSigned(trend)} vs season)</span>
            </span>
          </p>
        ) : null}
        <AiScoreExplainer
          trigger={
            <Button variant="ghost" size="xs" className="-ml-1.5 w-fit text-cyan hover:bg-cyan/10 hover:text-cyan">
              <CircleHelp aria-hidden="true" />
              What is this?
            </Button>
          }
        />
      </div>
    </section>
  );
}

function TrendIcon({ delta }: { delta: number }) {
  const Icon = delta > 0 ? ArrowUpRight : delta < 0 ? ArrowDownRight : Minus;
  return (
    <Icon
      aria-hidden="true"
      className={cn("size-3.5", delta > 0 ? "text-score-a" : delta < 0 ? "text-loss" : "text-text-muted")}
    />
  );
}
