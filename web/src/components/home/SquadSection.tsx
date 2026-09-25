import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowRight, ChevronRight, Crown, Users } from "lucide-react";

import type { Leaderboard, LeaderboardEntry } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { AiScoreRing } from "@/components/common/AiScoreRing";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Stagger, StaggerItem } from "@/components/common/Motion";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { StreakBadge } from "@/components/common/StreakBadge";
import { TierBadge } from "@/components/common/TierBadge";
import { WinRateBar } from "@/components/common/WinRateBar";
import { LpDelta, RankCell, RiotIdText, StandingBadge } from "@/components/leaderboard/parts";
import { RosterEmptyState } from "@/components/leaderboard/RosterEmptyState";
import { displayedRank, type Standings } from "@/components/leaderboard/sorting";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { LEADERBOARD_FORM_LIMIT } from "@/lib/streaks";
import { formatPercent, formatRecord, formatShortDate, plural } from "@/lib/format";
import { summonerParams } from "@/lib/riotId";

import { useMediaQuery } from "@/lib/hooks";

type Place = 1 | 2 | 3;

const PLACE_LABEL: Readonly<Record<Place, string>> = { 1: "1st", 2: "2nd", 3: "3rd" };

const MEDAL_CLASS: Readonly<Record<Place, string>> = {
  1: "border-gold/60 bg-gradient-to-b from-gold-bright to-gold text-primary-foreground shadow-[0_0_16px_-4px_rgba(200,170,110,0.8)]",
  2: "border-tier-silver/60 bg-surface-3 text-tier-silver",
  3: "border-tier-bronze/60 bg-surface-3 text-tier-bronze",
};

/** Desktop podium order: 2nd, 1st, 3rd. */
const PODIUM_ORDER: Readonly<Record<Place, string>> = { 1: "md:order-2", 2: "md:order-1", 3: "md:order-3" };

const PODIUM_GRID: Readonly<Record<number, string>> = {
  1: "md:mx-auto md:max-w-sm md:grid-cols-1",
  2: "md:mx-auto md:max-w-3xl md:grid-cols-2",
  3: "md:grid-cols-3",
};

const CARD_LAYOUT =
  "relative grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-3 p-4 md:flex md:flex-col md:items-center md:gap-4 md:p-6 md:text-center";

const DESKTOP = "(min-width: 768px)";

function ringSize(place: Place, desktop: boolean): number {
  if (!desktop) return 68;
  return place === 1 ? 124 : 100;
}

function PlaceMedal({ place }: { place: Place }) {
  return (
    <span
      className={cn(
        "absolute -top-1.5 -left-1.5 z-10 flex size-6 items-center justify-center rounded-full border font-display text-[11px] font-bold md:size-7 md:text-xs",
        MEDAL_CLASS[place],
      )}
    >
      {place === 1 ? <Crown className="size-3.5" aria-hidden="true" /> : <span aria-hidden="true">{place}</span>}
      <span className="sr-only">{PLACE_LABEL[place]} place</span>
    </span>
  );
}

function PodiumStat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-0.5 text-center">
      <dt className="label-caps">{label}</dt>
      <dd className="text-sm font-semibold text-text tabular-nums">{children}</dd>
    </div>
  );
}

function PodiumCard({ entry, place, desktop }: { entry: LeaderboardEntry; place: Place; desktop: boolean }) {
  const rank = displayedRank(entry, "all");
  return (
    <GlowCard
      asChild
      interactive
      glow={place === 1 ? "gold" : null}
      className={cn(CARD_LAYOUT, "group", place === 1 && "md:pt-8")}
    >
      <Link to="/summoner/$region/$riotId" params={summonerParams(entry.game_name, entry.tag_line)}>
        <span className="relative inline-flex w-fit shrink-0">
          <ProfileIcon
            iconId={entry.profile_icon_id}
            level={desktop ? entry.summoner_level : null}
            size={desktop && place === 1 ? "xl" : "lg"}
            alt=""
          />
          <PlaceMedal place={place} />
        </span>

        <span className="flex min-w-0 flex-col gap-1 md:items-center">
          <RiotIdText
            gameName={entry.game_name}
            tagLine={entry.tag_line}
            className="md:justify-center"
            nameClassName={cn(
              "font-display transition-colors group-hover:text-gold-bright",
              place === 1 ? "text-lg md:text-xl" : "text-base md:text-lg",
            )}
          />
          <span className="flex flex-wrap items-center gap-1.5 md:justify-center">
            {rank ? <TierBadge entry={rank.entry} size="sm" /> : <TierBadge tier={null} size="sm" />}
            {/* Inside the card's link, so no tooltip (a nested tab stop isn't allowed). */}
            <StreakBadge results={entry.recent_form} limit={LEADERBOARD_FORM_LIMIT} size="sm" tooltip={false} />
          </span>
        </span>

        {/* One gauge sweeps per view (DESIGN.md → Motion): the other two places are static. */}
        <AiScoreRing
          score={entry.avg_ai_score}
          kind="average"
          size={ringSize(place, desktop)}
          label="Avg AI Score"
          animate={place === 1}
        />

        <dl className="col-span-3 grid grid-cols-3 gap-2 border-t border-border pt-3 md:w-full md:pt-4">
          <PodiumStat label="Win rate">
            {entry.games > 0 ? formatPercent(entry.winrate) : "–"}
            {entry.games > 0 ? (
              <span className="block text-[11px] font-normal text-text-muted">
                {formatRecord(entry.wins, entry.losses)}
              </span>
            ) : null}
          </PodiumStat>
          <PodiumStat label="Games">{entry.games}</PodiumStat>
          <PodiumStat label="Season LP">
            <LpDelta value={entry.lp_delta} suffix />
          </PodiumStat>
        </dl>
      </Link>
    </GlowCard>
  );
}

function PodiumCardSkeleton({ place, desktop }: { place: Place; desktop: boolean }) {
  const icon = desktop && place === 1 ? 80 : 56;
  const ring = ringSize(place, desktop);
  return (
    <GlowCard className={cn(CARD_LAYOUT, place === 1 && "md:pt-8", PODIUM_ORDER[place])} aria-hidden="true">
      <Skeleton className={cn("rounded-full", desktop && "mb-2")} style={{ width: icon, height: icon }} />
      <span className="flex min-w-0 flex-col gap-2 md:items-center">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-28" />
      </span>
      <Skeleton className="rounded-full" style={{ width: ring, height: ring }} />
      <div className="col-span-3 grid grid-cols-3 gap-2 border-t border-border pt-3 md:w-full md:pt-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex flex-col items-center gap-1.5">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-4 w-10" />
          </div>
        ))}
      </div>
    </GlowCard>
  );
}

function SquadRow({ entry, standing, gamesNeeded }: { entry: LeaderboardEntry; standing: number | null; gamesNeeded: number }) {
  return (
    <Link
      to="/summoner/$region/$riotId"
      params={summonerParams(entry.game_name, entry.tag_line)}
      className="group flex min-h-16 items-center gap-3 px-4 py-2.5 transition-colors outline-offset-[-2px] hover:bg-white/[0.03] sm:gap-4"
    >
      <StandingBadge standing={standing} />
      <ProfileIcon iconId={entry.profile_icon_id} size="sm" alt="" />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex min-w-0 items-center gap-1.5">
          <RiotIdText
            gameName={entry.game_name}
            tagLine={entry.tag_line}
            nameClassName="transition-colors group-hover:text-gold-bright"
          />
          <StreakBadge results={entry.recent_form} limit={LEADERBOARD_FORM_LIMIT} size="sm" tooltip={false} />
        </span>
        <span className="truncate text-xs text-text-muted sm:hidden">
          {entry.games > 0
            ? `${formatPercent(entry.winrate)} win rate · ${plural(entry.games, "game")}`
            : "No games yet"}
        </span>
        {gamesNeeded > 0 ? (
          <span className="truncate text-xs text-text-muted">{needsGamesText(gamesNeeded)}</span>
        ) : null}
      </span>
      <RankCell rank={displayedRank(entry, "all")} className="hidden w-40 shrink-0 sm:flex" />
      <span className="hidden w-32 shrink-0 md:block">
        {entry.games > 0 ? (
          <WinRateBar wins={entry.wins} losses={entry.losses} size="sm" />
        ) : (
          <span className="text-xs text-text-muted">No games yet</span>
        )}
      </span>
      <span className="hidden w-16 shrink-0 text-right text-sm lg:block">
        <LpDelta value={entry.lp_delta} suffix />
      </span>
      <AiScoreBadge score={entry.avg_ai_score} kind="average" className="shrink-0" />
      <ChevronRight
        className="hidden size-4 shrink-0 text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-text-secondary sm:block"
        aria-hidden="true"
      />
    </Link>
  );
}

function SquadRowSkeleton() {
  return (
    <div className="flex min-h-16 items-center gap-3 px-4 py-2.5 sm:gap-4" aria-hidden="true">
      <Skeleton className="size-7 rounded-lg" />
      <Skeleton className="size-7 rounded-full" />
      <span className="flex flex-1 flex-col gap-1.5">
        <Skeleton className="h-3.5 w-32" />
        <Skeleton className="h-3 w-24 sm:hidden" />
      </span>
      <Skeleton className="hidden h-[30px] w-40 sm:block" />
      <Skeleton className="hidden h-6 w-32 md:block" />
      <Skeleton className="hidden h-3.5 w-16 lg:block" />
      <Skeleton className="h-6 w-14 rounded-full" />
      <span className="hidden w-4 sm:block" />
    </div>
  );
}

export interface SquadSectionProps {
  data: Leaderboard | undefined;
  /** The roster's standing (who is ranked, in what order). */
  standings: Standings;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
}

/** "Needs 8 more games" for a player who hasn't earned a standing yet. */
function needsGamesText(needed: number): string {
  return `Needs ${plural(needed, "more game")}`;
}

const MAX_ROWS = 7;

/** "The Squad": a podium for the top three by average AI Score and compact rows for the rest. */
export function SquadSection({ data, standings, isPending, error, onRetry }: SquadSectionProps) {
  const desktop = useMediaQuery(DESKTOP);
  const entries = standings.ordered;
  const scored = entries.some((entry) => entry.avg_ai_score !== null);
  const podium = standings.ranked.slice(0, 3);
  const rest = entries.filter((entry) => !podium.includes(entry)).slice(0, MAX_ROWS);
  const hidden = entries.length - podium.length - rest.length;

  const description =
    data && entries.length > 0
      ? `${scored ? "Ranked by average AI Score" : "Ranked by win rate until an AI model is trained"} · ${plural(standings.minGames, "game")} minimum · season since ${formatShortDate(data.season_start)}`
      : "The tracked roster, ranked by average AI Score";

  let body;
  if (isPending) {
    body = (
      <div className="flex flex-col gap-4" role="status" aria-label="Loading the roster">
        <div className={cn("grid grid-cols-1 gap-3 md:items-end md:gap-4", PODIUM_GRID[3])}>
          {([1, 2, 3] as const).map((place) => (
            <PodiumCardSkeleton key={place} place={place} desktop={desktop} />
          ))}
        </div>
        <GlowCard className="divide-y divide-border overflow-clip">
          {Array.from({ length: 5 }, (_, i) => (
            <SquadRowSkeleton key={i} />
          ))}
        </GlowCard>
      </div>
    );
  } else if (error && !data) {
    body = (
      <GlowCard>
        <ErrorState error={error} title="Couldn't load the roster" onRetry={onRetry} />
      </GlowCard>
    );
  } else if (entries.length === 0) {
    body = <RosterEmptyState />;
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {podium.length > 0 ? (
          <Stagger className={cn("grid grid-cols-1 gap-3 md:items-end md:gap-4", PODIUM_GRID[podium.length])}>
            {podium.map((entry, index) => {
              const place = (index + 1) as Place;
              return (
                <StaggerItem key={entry.puuid} className={cn("min-w-0", podium.length === 3 && PODIUM_ORDER[place])}>
                  <PodiumCard entry={entry} place={place} desktop={desktop} />
                </StaggerItem>
              );
            })}
          </Stagger>
        ) : null}

        {rest.length > 0 ? (
          <GlowCard className="overflow-clip">
            <ol className="divide-y divide-border" start={podium.length + 1}>
              {rest.map((entry) => (
                <li key={entry.puuid}>
                  <SquadRow
                    entry={entry}
                    standing={standings.rank.get(entry.puuid) ?? null}
                    gamesNeeded={standings.gamesNeeded(entry)}
                  />
                </li>
              ))}
            </ol>
            {hidden > 0 ? (
              <Link
                to="/leaderboard"
                className="flex items-center justify-center gap-1.5 border-t border-border px-4 py-3 text-sm font-medium text-text-secondary outline-offset-[-2px] transition-colors hover:bg-white/[0.03] hover:text-gold-bright"
              >
                {plural(hidden, "more player")} on the leaderboard
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            ) : null}
          </GlowCard>
        ) : null}
      </div>
    );
  }

  return (
    <section aria-labelledby="home-squad-title" className="flex flex-col gap-5">
      <SectionHeader
        eyebrow="The Squad"
        icon={Users}
        title={<span id="home-squad-title">Season standings</span>}
        description={description}
        action={
          <Button variant="outline" size="sm" asChild>
            <Link to="/leaderboard">
              Full leaderboard
              <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        }
      />
      {body}
    </section>
  );
}
