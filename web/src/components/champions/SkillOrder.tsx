import { Fragment } from "react";
import { ChevronRight, ListOrdered } from "lucide-react";

import type { SkillMaxOption, SkillOrder as SkillOrderData } from "@/api/types";
import { GameImage } from "@/components/common/GameImage";
import { cn } from "@/lib/cn";

import { useChampionAbilities, type ChampionAbility } from "./abilities";
import { OptionListHeader, OptionStats } from "./BuildPathRow";
import { DetailCard, EmptyNote } from "./DetailCard";
import { skillKey, timelineNote } from "./detailModel";

const OTHER_ORDERS = 3;
const LEVELS = Array.from({ length: 18 }, (_, i) => i + 1);
const SLOTS = [1, 2, 3, 4] as const;

/** An ability icon with its key letter in the corner, or just the letter when there's no icon. */
function AbilityBadge({
  slot,
  abilities,
  size = 36,
  className,
}: {
  slot: number;
  abilities: readonly ChampionAbility[] | undefined;
  size?: number;
  className?: string;
}) {
  const letter = skillKey(slot);
  const ability = abilities?.[slot - 1];
  const label = ability ? `${letter}: ${ability.name}` : letter;
  const tile = (
    <span
      className="flex size-full items-center justify-center font-display font-bold text-gold-bright"
      style={{ fontSize: Math.round(size * 0.45) }}
    >
      {letter}
    </span>
  );
  return (
    <span className={cn("relative inline-flex shrink-0", className)} style={{ width: size, height: size }} title={label}>
      <span className="block size-full overflow-hidden rounded-md bg-surface-3 ring-1 ring-gold/30">
        {ability?.icon ? (
          <GameImage src={ability.icon} alt={label} width={size} height={size} className="size-full object-cover" fallback={tile} />
        ) : (
          <span role="img" aria-label={label} className="block size-full">
            {tile}
          </span>
        )}
      </span>
      {ability?.icon ? (
        <span
          aria-hidden="true"
          className="absolute -right-1 -bottom-1 flex h-4 min-w-4 items-center justify-center rounded border border-bg bg-surface-3 px-0.5 text-[10px] leading-none font-bold text-text"
        >
          {letter}
        </span>
      ) : null}
    </span>
  );
}

/** "Q > E > W" as letters (compact rows). */
function MaxOrderLetters({ order }: { order: readonly number[] }) {
  return (
    <span role="img" className="flex items-center gap-1" aria-label={`Max ${order.map(skillKey).join(", then ")}`}>
      {order.map((slot, i) => (
        <Fragment key={slot}>
          {i > 0 ? <ChevronRight className="size-3 text-text-muted" aria-hidden="true" /> : null}
          <span
            aria-hidden="true"
            className="flex size-6 items-center justify-center rounded-md border border-border-strong bg-surface-3 font-display text-xs font-bold text-text"
          >
            {skillKey(slot)}
          </span>
        </Fragment>
      ))}
    </span>
  );
}

/** Levels 1-18 as a grid: one row per ability, the level's cell lit where it was skilled. */
function SkillPathGrid({ path, abilities }: { path: readonly number[]; abilities: readonly ChampionAbility[] | undefined }) {
  const summary = path.map((slot, i) => `level ${i + 1} ${skillKey(slot)}`).join(", ");
  return (
    <div className="scrollbar-thin -mx-1 overflow-x-auto px-1 pb-1">
      <div
        role="img"
        aria-label={`Usual skill path: ${summary}.`}
        className="grid min-w-[33rem] grid-cols-[2.25rem_repeat(18,minmax(1.5rem,1fr))] gap-1"
      >
        <span aria-hidden="true" />
        {LEVELS.map((level) => (
          <span key={level} aria-hidden="true" className="text-center text-[11px] text-text-muted tabular-nums">
            {level}
          </span>
        ))}
        {SLOTS.map((slot) => (
          <Fragment key={slot}>
            <span aria-hidden="true" className="flex items-center">
              <AbilityBadge slot={slot} abilities={abilities} size={26} />
            </span>
            {LEVELS.map((level) => {
              const on = path[level - 1] === slot;
              return (
                <span
                  key={level}
                  aria-hidden="true"
                  className={cn(
                    "flex h-7 items-center justify-center rounded-md text-xs font-bold tabular-nums",
                    on
                      ? slot === 4
                        ? "bg-gold text-primary-foreground"
                        : "bg-gold/15 text-gold-bright ring-1 ring-gold/35"
                      : "bg-white/[0.03]",
                  )}
                >
                  {on ? skillKey(slot) : null}
                </span>
              );
            })}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function TopMaxOrder({ option, abilities }: { option: SkillMaxOption; abilities: readonly ChampionAbility[] | undefined }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-gold/20 bg-gold/[0.04] px-3 py-2.5">
      <div role="group" className="flex items-center gap-1.5" aria-label={`Max ${option.order.map(skillKey).join(", then ")}`}>
        {option.order.map((slot, i) => (
          <Fragment key={slot}>
            {i > 0 ? <ChevronRight className="size-4 text-gold/70" aria-hidden="true" /> : null}
            <AbilityBadge slot={slot} abilities={abilities} />
          </Fragment>
        ))}
      </div>
      <OptionStats option={option} />
    </div>
  );
}

/** Skill order: the most common max order, the usual level-by-level path, and other max orders. */
export function SkillOrder({
  skills,
  champion,
  timelineGames,
}: {
  skills: SkillOrderData;
  /** Data Dragon key, for the ability icons. */
  champion: string;
  timelineGames: number;
}) {
  const abilities = useChampionAbilities(champion);
  const [top, ...others] = skills.max_orders;
  const hasData = Boolean(top) || skills.path.length > 0;
  return (
    <DetailCard
      title="Skill order"
      icon={ListOrdered}
      description={
        timelineGames > 0
          ? `Which basic ability gets maxed first, and the usual path. ${timelineNote(timelineGames, "a full timeline")}.`
          : "Which basic ability gets maxed first, and the usual path."
      }
    >
      {hasData ? (
        <div className="flex flex-col gap-4">
          {top ? (
            <div className="flex flex-col gap-1.5">
              <OptionListHeader label="Max order" />
              <TopMaxOrder option={top} abilities={abilities} />
            </div>
          ) : null}
          {skills.path.length > 0 ? <SkillPathGrid path={skills.path} abilities={abilities} /> : null}
          {others.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              <OptionListHeader label="Other max orders" />
              {others.slice(0, OTHER_ORDERS).map((option) => (
                <div
                  key={option.order.join("-")}
                  className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-2/40 px-3 py-2"
                >
                  <MaxOrderLetters order={option.order} />
                  <OptionStats option={option} />
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyNote>
          {timelineGames > 0
            ? "No skill order is common enough to show yet."
            : "Skill order comes from match timelines, and none are in for these games yet."}
        </EmptyNote>
      )}
    </DetailCard>
  );
}
