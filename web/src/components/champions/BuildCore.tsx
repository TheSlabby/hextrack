import { Fragment } from "react";
import { ChevronRight, Hammer, Trophy } from "lucide-react";

import type { BuildOption, ChampionBuilds } from "@/api/types";
import { cn } from "@/lib/cn";
import { formatInteger } from "@/lib/format";

import { BuildPathRow, OptionListHeader } from "./BuildPathRow";
import { DetailCard, EmptyNote } from "./DetailCard";
import { buildTime, pct, timelineNote, winRateTone } from "./detailModel";
import { ItemIcon, ItemName } from "./ItemIcon";

const OTHER_CORE_ROWS = 4;

/** Core build: the most common first three completed items, the runners-up and the best-performing one. */
export function BuildCore({ builds, timelineGames }: { builds: ChampionBuilds; timelineGames: number }) {
  const [top, ...others] = builds.core;
  return (
    <DetailCard
      eyebrow="Build"
      title="Core items"
      icon={Hammer}
      description={
        timelineGames > 0
          ? `The first three completed items, in the order they were bought. ${timelineNote(timelineGames)}.`
          : "The first three completed items, in the order they were bought."
      }
    >
      {top ? (
        <>
          <CoreShowcase option={top} />
          {others.length > 0 || builds.core_best ? (
            <div className="flex flex-col gap-1.5">
              <OptionListHeader label="Other paths" />
              {others.slice(0, OTHER_CORE_ROWS).map((option) => (
                <BuildPathRow key={option.items.join("-")} option={option} showTime />
              ))}
              {builds.core_best ? (
                <BuildPathRow
                  option={builds.core_best}
                  showTime
                  className="border-gold/20 bg-gold/[0.04]"
                  badge={
                    <span className="inline-flex items-center gap-1 font-semibold text-gold">
                      <Trophy className="size-3" aria-hidden="true" />
                      Highest win rate
                    </span>
                  }
                />
              ) : null}
            </div>
          ) : null}
        </>
      ) : (
        <EmptyNote>
          {timelineGames > 0
            ? "No core build is common enough to show yet."
            : "Item order comes from match timelines, and none are in for these games yet. Check back soon."}
        </EmptyNote>
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

/** The most common core build, large, with item names and its numbers. */
function CoreShowcase({ option }: { option: BuildOption }) {
  const time = buildTime(option.avg_time_s);
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-gold/20 bg-gold/[0.04] p-3 sm:p-4 xl:flex-row xl:items-center xl:justify-between">
      <ol className="flex items-start gap-1 sm:gap-2" aria-label="Most common core build">
        {option.items.map((id, i) => (
          <Fragment key={`${id}-${i}`}>
            {i > 0 ? (
              <li aria-hidden="true" className="flex h-11 items-center">
                <ChevronRight className="size-4 text-gold/70" />
              </li>
            ) : null}
            <li className="flex w-[4.75rem] flex-col items-center gap-1.5 text-center">
              <ItemIcon id={id} size={44} className="ring-gold/30" />
              <ItemName id={id} lines={2} className="text-[11px] leading-tight text-text-secondary" />
            </li>
          </Fragment>
        ))}
      </ol>
      <dl className="grid grid-cols-4 gap-3 sm:flex sm:gap-6">
        <ShowcaseStat label="Win rate" value={pct(option.win_rate)} className={winRateTone(option.win_rate)} />
        <ShowcaseStat label="Pick rate" value={pct(option.pick_rate)} className="text-text" />
        <ShowcaseStat label="Games" value={formatInteger(option.games)} className="text-text" />
        {time ? <ShowcaseStat label="Done at" value={time} className="text-text" /> : null}
      </dl>
    </div>
  );
}
