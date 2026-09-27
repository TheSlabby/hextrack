import type { ReactNode } from "react";
import { Flame, Layers } from "lucide-react";

import type { BuildOption, ChampionBuilds } from "@/api/types";
import { cn } from "@/lib/cn";
import { formatCompact } from "@/lib/format";

import { ItemPath, OptionListHeader, OptionRow } from "./BuildPathRow";
import { DetailCard, EmptyNote } from "./DetailCard";
import { NO_TIMELINE, pct, timelineCount, winRateTone } from "./detailModel";
import { ItemIcon, ItemName } from "./ItemIcon";

const START_ROWS = 3;
const BOOT_ROWS = 3;
const SLOT_ROWS = 3;
const POPULAR_ITEMS = 10;

/** A single item with its name (the name hides when the column is narrow; it's on hover too). */
function ItemOptionRow({ option, highlight }: { option: BuildOption; highlight?: boolean }) {
  const id = option.items[0] ?? 0;
  return (
    <OptionRow option={option} highlight={highlight}>
      <ItemIcon id={id} size={26} />
      <ItemName id={id} className="hidden text-xs font-medium text-text @[15rem]:inline" />
    </OptionRow>
  );
}

/** One column of the item build: a heading and up to `rows` options (the first highlighted). */
function OptionColumn({
  label,
  options,
  rows,
  render,
  empty,
  footer,
}: {
  label: string;
  options: readonly BuildOption[];
  rows: number;
  render: (option: BuildOption, first: boolean) => ReactNode;
  empty: string;
  footer?: ReactNode;
}) {
  return (
    <section aria-label={label} className="@container flex min-w-0 flex-col gap-1">
      <OptionListHeader label={label} />
      {options.length > 0 ? (
        options.slice(0, rows).map((option, i) => (
          <div key={option.items.join("-")} className="min-w-0">
            {render(option, i === 0)}
          </div>
        ))
      ) : (
        <EmptyNote className="py-3">{empty}</EmptyNote>
      )}
      {footer}
    </section>
  );
}

/**
 * The item build in one card: starting items and boots, then what comes 4th, 5th and 6th.
 * Starting items and items 4-6 need a timeline; boots come from every game.
 */
export function ItemBuild({ builds, timelineGames }: { builds: ChampionBuilds; timelineGames: number }) {
  const slots = [...builds.slots].sort((a, b) => a.slot - b.slot);
  const noTimeline = timelineGames === 0;
  const noBoots = builds.no_boots_rate;
  return (
    <DetailCard
      title="Item build"
      icon={Layers}
      description="Starting items, boots, and what comes after the core."
      action={timelineGames > 0 ? timelineCount(timelineGames) : null}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <OptionColumn
          label="Starting items"
          options={builds.starting}
          rows={START_ROWS}
          empty={noTimeline ? "Needs match timelines; none are in yet." : "No starting set is common enough yet."}
          render={(option, first) => (
            <OptionRow option={option} highlight={first}>
              <ItemPath items={option.items} size={26} arrows={false} />
            </OptionRow>
          )}
        />
        <OptionColumn
          label="Boots"
          options={builds.boots}
          rows={BOOT_ROWS}
          empty="No boots are common enough to show."
          render={(option, first) => <ItemOptionRow option={option} highlight={first} />}
          footer={
            noBoots >= 0.005 ? (
              <p className="px-2.5 pt-0.5 text-[11px] text-text-muted">
                <span className="font-semibold text-text-secondary tabular-nums">{pct(noBoots)}</span> of games ended
                without boots.
              </p>
            ) : null
          }
        />
      </div>
      <div className="border-t border-border pt-3">
        {noTimeline ? (
          <EmptyNote>{NO_TIMELINE}</EmptyNote>
        ) : (
          <div className="grid gap-4 sm:grid-cols-3 sm:gap-3">
            {slots.map((slot) => (
              <OptionColumn
                key={slot.slot}
                label={`Item ${slot.slot}`}
                options={slot.options}
                rows={SLOT_ROWS}
                empty="Not enough games."
                render={(option, first) => <ItemOptionRow option={option} highlight={first} />}
              />
            ))}
          </div>
        )}
      </div>
    </DetailCard>
  );
}

/** The finished items most often in the final inventory (any order, every game), as an icon grid. */
export function BuildPopular({ builds, className }: { builds: ChampionBuilds; className?: string }) {
  const items = builds.popular_items.slice(0, POPULAR_ITEMS);
  return (
    <DetailCard
      title="Popular items"
      icon={Flame}
      description="Finished items most often in the final inventory."
      className={className}
    >
      {items.length > 0 ? (
        <ul className="grid grid-cols-5 gap-x-2 gap-y-3">
          {items.map((option) => {
            const id = option.items[0] ?? 0;
            return (
              <li key={id} className="flex min-w-0 flex-col items-center gap-1 text-center tabular-nums">
                <ItemIcon id={id} size={36} />
                <span className="text-xs leading-none font-semibold text-text">{pct(option.pick_rate)}</span>
                <span className={cn("text-[10px] leading-none", winRateTone(option.win_rate))}>
                  {pct(option.win_rate)} win
                </span>
                <span className="sr-only">
                  <ItemName id={id} />, {formatCompact(option.games)} games
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <EmptyNote>No finished items yet.</EmptyNote>
      )}
    </DetailCard>
  );
}

