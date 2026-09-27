import { Flame, Footprints, Layers, PackageOpen } from "lucide-react";

import type { BuildOption, ChampionBuilds } from "@/api/types";
import { cn } from "@/lib/cn";

import { BuildPathRow, OptionListHeader, OptionStats } from "./BuildPathRow";
import { DetailCard, EmptyNote } from "./DetailCard";
import { pct, timelineNote } from "./detailModel";
import { ItemIcon, ItemName } from "./ItemIcon";

const SLOT_ROWS = 4;
const START_ROWS = 4;
const BOOT_ROWS = 4;
const POPULAR_ROWS = 10;

const NO_TIMELINE = "Item order comes from match timelines, and none are in for these games yet.";

/** A single item: icon + name on the left, win and pick rate on the right. */
function ItemOptionRow({
  option,
  compact,
  className,
}: {
  option: BuildOption;
  /** Name hidden between md and lg, where three lists share a row (still on hover). */
  compact?: boolean;
  className?: string;
}) {
  const id = option.items[0] ?? 0;
  return (
    <div
      className={cn(
        "flex min-w-0 items-center justify-between gap-3 rounded-xl border border-border bg-surface-2/40 px-3 py-2",
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <ItemIcon id={id} size={28} />
        <ItemName id={id} className={cn("text-sm font-medium text-text", compact && "md:max-lg:hidden")} />
      </div>
      <OptionStats option={option} />
    </div>
  );
}

/** Items bought in the first 90 seconds. */
export function BuildStarting({ builds, timelineGames }: { builds: ChampionBuilds; timelineGames: number }) {
  return (
    <DetailCard
      title="Starting items"
      icon={PackageOpen}
      description={timelineGames > 0 ? `Bought in the first 90 seconds. ${timelineNote(timelineGames)}.` : "Bought in the first 90 seconds."}
    >
      {builds.starting.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <OptionListHeader label="Items" />
          {builds.starting.slice(0, START_ROWS).map((option) => (
            <BuildPathRow key={option.items.join("-")} option={option} arrows={false} />
          ))}
        </div>
      ) : (
        <EmptyNote>{timelineGames > 0 ? "No starting set is common enough to show yet." : NO_TIMELINE}</EmptyNote>
      )}
    </DetailCard>
  );
}

/** Boots in the final inventory, plus how often games ended without any. */
export function BuildBoots({ builds }: { builds: ChampionBuilds }) {
  const noBoots = builds.no_boots_rate;
  return (
    <DetailCard title="Boots" icon={Footprints} description="Boots in the final inventory, over every game.">
      {builds.boots.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <OptionListHeader label="Boots" />
          {builds.boots.slice(0, BOOT_ROWS).map((option) => (
            <ItemOptionRow key={option.items.join("-")} option={option} />
          ))}
        </div>
      ) : (
        <EmptyNote>No boots are common enough to show.</EmptyNote>
      )}
      {noBoots >= 0.005 ? (
        <p className="text-xs text-text-secondary">
          <span className="font-semibold text-text tabular-nums">{pct(noBoots)}</span> of games ended without boots.
        </p>
      ) : null}
    </DetailCard>
  );
}

/** Items 4, 5 and 6: the options for each later slot, side by side. */
export function BuildSlots({ builds, timelineGames }: { builds: ChampionBuilds; timelineGames: number }) {
  const slots = [...builds.slots].sort((a, b) => a.slot - b.slot);
  const any = slots.some((slot) => slot.options.length > 0);
  return (
    <DetailCard
      eyebrow="Build"
      title="Later items"
      icon={Layers}
      description={
        timelineGames > 0
          ? `What comes 4th, 5th and 6th once the core is done. ${timelineNote(timelineGames)}.`
          : "What comes 4th, 5th and 6th once the core is done."
      }
    >
      {any ? (
        <div className="grid gap-4 md:grid-cols-3 md:gap-3">
          {slots.map((slot) => (
            <section key={slot.slot} aria-label={`Item ${slot.slot}`} className="flex min-w-0 flex-col gap-1.5">
              <OptionListHeader label={`Item ${slot.slot}`} />
              {slot.options.length > 0 ? (
                slot.options
                  .slice(0, SLOT_ROWS)
                  .map((option) => <ItemOptionRow key={option.items.join("-")} option={option} compact />)
              ) : (
                <EmptyNote className="py-3">Not enough games.</EmptyNote>
              )}
            </section>
          ))}
        </div>
      ) : (
        <EmptyNote>{timelineGames > 0 ? "Not enough games reach a 4th item yet." : NO_TIMELINE}</EmptyNote>
      )}
    </DetailCard>
  );
}

/** The completed items most often in the final inventory (any order, every game). */
export function BuildPopular({ builds }: { builds: ChampionBuilds }) {
  return (
    <DetailCard title="Popular items" icon={Flame} description="Completed items most often in the final inventory.">
      {builds.popular_items.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <OptionListHeader label="Item" />
          {builds.popular_items.slice(0, POPULAR_ROWS).map((option) => (
            <ItemOptionRow key={option.items.join("-")} option={option} />
          ))}
        </div>
      ) : (
        <EmptyNote>No completed items yet.</EmptyNote>
      )}
    </DetailCard>
  );
}
