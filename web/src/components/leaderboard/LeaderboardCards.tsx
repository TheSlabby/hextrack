import type { MouseEvent, ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDownWideNarrow, ArrowUpNarrowWide } from "lucide-react";

import type { LeaderboardEntry, LeaderboardQueue } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { RolePercentileAverage } from "@/components/common/RolePercentile";
import { FormDots } from "@/components/common/FormDots";
import { GlowCard } from "@/components/common/GlowCard";
import { Stagger, StaggerItem } from "@/components/common/Motion";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { StreakBadge } from "@/components/common/StreakBadge";
import { WinRateBar } from "@/components/common/WinRateBar";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import { LEADERBOARD_FORM_LIMIT } from "@/lib/streaks";
import { formatAvgKdaLine, formatInteger, formatKdaRatio, plural } from "@/lib/format";
import { summonerParams } from "@/lib/riotId";

import { BestAllyLink, LpDelta, RankCell, RiotIdText, StandingBadge, TopChampions } from "./parts";
import {
  displayedRank,
  SORT_LABELS,
  SORT_MENU_KEYS,
  defaultDirection,
  type SortKey,
  type SortState,
  type Standings,
} from "./sorting";

export interface LeaderboardCardsProps {
  entries: readonly LeaderboardEntry[];
  standings: Standings;
  queue: LeaderboardQueue;
  className?: string;
}

function Stat({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      <dt className="label-caps">{label}</dt>
      <dd className="text-sm font-semibold text-text tabular-nums">{children}</dd>
    </div>
  );
}

/** Mobile leaderboard: one card per player, the same data as the table rows. */
export function LeaderboardCards({ entries, standings, queue, className }: LeaderboardCardsProps) {
  const navigate = useNavigate();

  const openPlayer = (event: MouseEvent, entry: LeaderboardEntry) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest("a, button")) return;
    if (window.getSelection()?.toString()) return;
    void navigate({ to: "/summoner/$region/$riotId", params: summonerParams(entry.game_name, entry.tag_line) });
  };

  return (
    <Stagger className={cn("flex flex-col gap-3", className)}>
      {entries.map((entry) => {
        const standing = standings.rank.get(entry.puuid) ?? null;
        const needed = standings.gamesNeeded(entry);
        const hasGames = entry.games > 0;
        return (
          <StaggerItem key={entry.puuid}>
            <GlowCard
              interactive
              className="cursor-pointer p-4"
              onClick={(event) => openPlayer(event, entry)}
              glow={standing === 1 ? "gold" : null}
            >
              <div className="flex items-center gap-3">
                <StandingBadge standing={standing} />
                <Link
                  to="/summoner/$region/$riotId"
                  params={summonerParams(entry.game_name, entry.tag_line)}
                  className="flex min-w-0 flex-1 items-center gap-3 rounded-lg"
                >
                  <ProfileIcon iconId={entry.profile_icon_id} size="sm" alt="" />
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <RiotIdText gameName={entry.game_name} tagLine={entry.tag_line} />
                    <RankCell rank={displayedRank(entry, queue)} size="sm" />
                  </span>
                </Link>
                <AiScoreBadge
                  score={entry.avg_ai_score}
                  kind="average"
                  size="lg"
                  className="shrink-0"
                  detail={hasGames ? `Over ${plural(entry.games, "ranked game")} this season.` : undefined}
                />
              </div>

              {needed > 0 ? (
                <p className="mt-3 text-xs text-text-muted">
                  No standing yet · needs {plural(needed, "more game")}
                </p>
              ) : null}

              <dl className="mt-4 grid grid-cols-3 gap-3">
                <Stat label="Games">{formatInteger(entry.games)}</Stat>
                <Stat label="KDA">
                  {hasGames ? (
                    <span className="flex flex-col">
                      <span>{formatKdaRatio(entry.kda, entry.avg_deaths === 0 ? 0 : undefined)}</span>
                      <span className="truncate text-[11px] font-normal text-text-muted">
                        {formatAvgKdaLine(entry.avg_kills, entry.avg_deaths, entry.avg_assists)}
                      </span>
                    </span>
                  ) : (
                    "–"
                  )}
                </Stat>
                <Stat label="Season LP">
                  <LpDelta value={entry.lp_delta} />
                </Stat>
              </dl>

              {hasGames ? <WinRateBar wins={entry.wins} losses={entry.losses} size="sm" className="mt-3" /> : null}

              <div className="mt-3 flex items-center justify-between gap-3 border-t border-border pt-3">
                <BestAllyLink ally={entry.best_ally} className="max-w-[45%]" />
                <TopChampions champions={entry.top_champions} />
              </div>
              <div className="mt-3 flex items-center justify-between gap-3">
                <span className="label-caps">Form</span>
                <span className="flex items-center gap-1.5">
                  <FormDots results={entry.recent_form} limit={10} size="sm" className="flex-nowrap" />
                  <StreakBadge results={entry.recent_form} limit={LEADERBOARD_FORM_LIMIT} size="sm" />
                </span>
              </div>
              {needed === 0 && entry.avg_ai_role_percentile !== null ? (
                <div className="mt-2 flex items-center justify-between gap-3">
                  <span className="label-caps">AI Score in role</span>
                  <RolePercentileAverage
                    percentile={entry.avg_ai_role_percentile}
                    games={entry.games}
                    minGames={standings.minGames}
                    bare
                    size="sm"
                  />
                </div>
              ) : null}
            </GlowCard>
          </StaggerItem>
        );
      })}
    </Stagger>
  );
}

/** Mobile sort controls: a "Sort by" menu plus a direction toggle. */
export function LeaderboardSortMenu({
  sort,
  onChange,
  className,
}: {
  sort: SortState;
  onChange: (sort: SortState) => void;
  className?: string;
}) {
  const ascending = sort.direction === "asc";
  const menuKeys = SORT_MENU_KEYS.includes(sort.key) ? SORT_MENU_KEYS : [sort.key, ...SORT_MENU_KEYS];
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="label-caps shrink-0">Sort by</span>
      <Select
        value={sort.key}
        onValueChange={(key) => onChange({ key: key as SortKey, direction: defaultDirection(key as SortKey) })}
      >
        <SelectTrigger size="sm" className="min-w-36" aria-label="Sort by">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper" align="start">
          {menuKeys.map((key) => (
            <SelectItem key={key} value={key}>
              {SORT_LABELS[key]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        size="icon-sm"
        onClick={() => onChange({ key: sort.key, direction: ascending ? "desc" : "asc" })}
        aria-label={ascending ? "Sorted ascending. Switch to descending" : "Sorted descending. Switch to ascending"}
      >
        {ascending ? <ArrowUpNarrowWide aria-hidden="true" /> : <ArrowDownWideNarrow aria-hidden="true" />}
      </Button>
    </div>
  );
}
