import type { ReactNode } from "react";

import type { MatchSummary } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { WinRateBar } from "@/components/common/WinRateBar";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatAvgKdaLine, formatDecimal, formatPercent, formatSigned, plural } from "@/lib/format";
import { averageOffset } from "@/lib/score";
import { championDisplayName } from "@/lib/champions";

import { KdaRatio } from "./MatchBits";
import { kdaToneClass, recordKda, summarizeHistory } from "./matchUtils";

const GRID = "grid grid-cols-2 gap-x-4 gap-y-5 @3xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.5fr)] @3xl:gap-x-6";

function Block({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <span className="label-caps">{label}</span>
      {children}
    </div>
  );
}

/** W-L, win rate, average KDA, average AI Score and top champions over the loaded games. */
export function MatchHistorySummary({ matches, className }: { matches: readonly MatchSummary[]; className?: string }) {
  const s = summarizeHistory(matches);
  const scope = plural(s.loaded, "game");

  return (
    <GlowCard className={cn("p-4 sm:p-5", className)}>
      <h3 className="sr-only">Summary of the {scope} shown</h3>
      <div className={GRID}>
        <Block label={`Last ${scope}`}>
          <div className="flex items-baseline gap-2">
            <span className="font-display text-2xl leading-none font-semibold tabular-nums text-text">
              {s.winrate !== null ? formatPercent(s.winrate) : "–"}
            </span>
            <span className="text-xs text-text-secondary tabular-nums">
              <span className="text-win">{s.wins}W</span> <span className="text-loss">{s.losses}L</span>
              {s.remakes > 0 ? <span className="text-text-muted"> · {plural(s.remakes, "remake")}</span> : null}
            </span>
          </div>
          <WinRateBar wins={s.wins} losses={s.losses} showLabels={false} size="sm" className="max-w-48" />
        </Block>

        <Block label="Avg KDA">
          <span className="text-sm font-semibold whitespace-nowrap text-text tabular-nums">
            {s.games > 0 ? formatAvgKdaLine(s.avgKills, s.avgDeaths, s.avgAssists) : "–"}
          </span>
          <span className="text-xs text-text-secondary">
            {s.games > 0 ? <KdaRatio kda={s.kda} deaths={s.totalDeaths} /> : null}
            {s.avgKillParticipation !== null ? (
              <span className="tabular-nums"> · {formatPercent(s.avgKillParticipation)} KP</span>
            ) : null}
          </span>
        </Block>

        <Block label="Avg AI Score">
          <div className="flex items-center gap-2">
            <AiScoreBadge score={s.avgAiScore} kind="average" size="lg" />
            {s.avgAiScore !== null ? (
              <span className="text-xs font-medium text-text-secondary tabular-nums">
                {formatSigned(averageOffset(s.avgAiScore))} vs 50
              </span>
            ) : null}
          </div>
          <span className="text-xs text-text-muted">
            {s.scoredGames > 0 ? `Across ${plural(s.scoredGames, "scored game")}` : "No scored games yet"}
          </span>
        </Block>

        <Block label="Most played" className="col-span-2 @3xl:col-span-1">
          {s.topChampions.length === 0 ? (
            <span className="text-xs text-text-muted">No completed games</span>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {s.topChampions.map((record) => {
                const kda = recordKda(record);
                return (
                  <li key={record.champion} className="flex min-w-0 items-center gap-2 text-xs tabular-nums">
                    <ChampionIcon champion={record.champion} size="xs" />
                    <span className="min-w-0 flex-1 truncate font-medium text-text">{championDisplayName(record.champion)}</span>
                    <span className="text-text-secondary">
                      {formatPercent(record.wins / record.games)}{" "}
                      <span className="text-text-muted">({record.wins}W {record.games - record.wins}L)</span>
                    </span>
                    <span className={cn("w-16 text-right font-semibold", kdaToneClass(kda, record.deaths))}>
                      {record.deaths === 0 && kda > 0 ? "Perfect" : `${formatDecimal(kda, 2)} KDA`}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </Block>
      </div>
    </GlowCard>
  );
}

/** Placeholder with the summary card's exact layout. */
export function MatchHistorySummarySkeleton({ className }: { className?: string }) {
  return (
    <GlowCard className={cn("p-4 sm:p-5", className)} aria-hidden="true">
      <div className={GRID}>
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-6 w-28" />
          <Skeleton className="h-1.5 w-40 rounded-full" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-4 w-24" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-8 w-20 rounded-full" />
          <Skeleton className="h-4 w-28" />
        </div>
        <div className="col-span-2 flex flex-col gap-1.5 @3xl:col-span-1">
          <Skeleton className="h-4 w-20" />
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="flex items-center gap-2">
              <Skeleton className="size-5 rounded-md" />
              <Skeleton className="h-3 flex-1" />
            </div>
          ))}
        </div>
      </div>
    </GlowCard>
  );
}
