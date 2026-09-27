import { Fragment } from "react";
import { ChevronRight, Hammer, Trophy } from "lucide-react";

import type { BuildOption, ChampionBuilds } from "@/api/types";
import { cn } from "@/lib/cn";
import { formatInteger } from "@/lib/format";

import { BuildPathRow, OptionListHeader } from "./BuildPathRow";
import { DetailCard, EmptyNote } from "./DetailCard";
import { buildTime, NO_TIMELINE, pct, timelineCount, winRateTone } from "./detailModel";
import { ItemIcon, ItemName } from "./ItemIcon";

const OTHER_CORE_ROWS = 3;

/** Core build: the most common first three completed items, the runners-up and the best-performing one. */
export function BuildCore({ builds, timelineGames }: { builds: ChampionBuilds; timelineGames: number }) {
  const [top, ...others] = builds.core;
  const best = builds.core_best;
  return (
    <DetailCard
      title="Core build"
      icon={Hammer}
      description="The first three finished items, in the order they were bought."
      action={timelineGames > 0 ? timelineCount(timelineGames) : null}
    >
      {top ? (
        <>
          <CoreShowcase option={top} />
          {others.length > 0 || best ? (
            <div className="flex flex-col gap-1">
              <OptionListHeader label="Other paths" />
              {others.slice(0, OTHER_CORE_ROWS).map((option) => (
                <BuildPathRow key={option.items.join("-")} option={option} showTime />
              ))}
              {best ? (
                <BuildPathRow
                  option={best}
                  showTime
                  highlight
                  badge={
                    <span className="inline-flex items-center gap-1 font-semibold text-gold">
                      <Trophy className="size-3" aria-hidden="true" />
                      Best win rate
                    </span>
                  }
                />
              ) : null}
            </div>
          ) : null}
        </>
      ) : (
        <EmptyNote>{timelineGames > 0 ? "No core build is common enough to show yet." : NO_TIMELINE}</EmptyNote>
      )}
    </DetailCard>
  );
}

function ShowcaseStat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="label-caps truncate">{label}</dt>
      <dd className={cn("font-display text-lg leading-tight font-semibold tabular-nums", className)}>{value}</dd>
    </div>
  );
}

/**
 * The most common core build, large, with item names and its numbers. Items and numbers sit
 * side by side only when the card itself is wide enough (container query), else stacked.
 */
function CoreShowcase({ option }: { option: BuildOption }) {
  const time = buildTime(option.avg_time_s);
  return (
    <div className="@container rounded-xl border border-gold/25 bg-gold/[0.05] p-3">
      <div className="flex flex-col gap-3 @xl:flex-row @xl:items-center @xl:justify-between">
        <ol className="flex items-start justify-center gap-1 @xl:justify-start" aria-label="Most common core build">
          {option.items.map((id, i) => (
            <Fragment key={`${id}-${i}`}>
              {i > 0 ? (
                <li aria-hidden="true" className="flex h-11 items-center">
                  <ChevronRight className="size-4 text-gold/70" />
                </li>
              ) : null}
              <li className="flex w-[4.5rem] flex-col items-center gap-1 text-center">
                <ItemIcon id={id} size={44} className="ring-gold/30" />
                <ItemName id={id} lines={2} className="text-[11px] leading-tight text-text-secondary" />
              </li>
            </Fragment>
          ))}
        </ol>
        <dl className="grid grid-cols-4 gap-2 border-t border-gold/15 pt-3 @xl:gap-4 @xl:border-t-0 @xl:pt-0">
          <ShowcaseStat label="Win" value={pct(option.win_rate)} className={winRateTone(option.win_rate)} />
          <ShowcaseStat label="Pick" value={pct(option.pick_rate)} className="text-text" />
          <ShowcaseStat label="Games" value={formatInteger(option.games)} className="text-text" />
          <ShowcaseStat label="Done at" value={time ?? "–"} className="text-text" />
        </dl>
      </div>
    </div>
  );
}
