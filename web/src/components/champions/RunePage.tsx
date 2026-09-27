import { useMemo } from "react";

import type { RunePageOption, RunePick, ShardPick, ShardSetOption } from "@/api/types";
import { GameImage } from "@/components/common/GameImage";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { useRuneTrees, type RuneInfo, type RuneTree } from "@/lib/runes";
import { SHARD_ROW_LABELS, SHARD_ROWS, shardRowOptions, statShard, type ShardRow } from "@/lib/statShards";

import { pct } from "./detailModel";

interface PickNumbers {
  pick_rate: number;
  win_rate: number;
  games: number;
}

/** "54%", "<1%" for runes under the API's 1% cut. */
function pickText(pick: PickNumbers | undefined): string {
  return pick ? formatPercent(pick.pick_rate) : "<1%";
}

/** One rune or shard: bright and ringed when on the page, greyed otherwise, pick rate underneath. */
function PerkCell({
  name,
  icon,
  glyph,
  selected,
  pick,
  size,
  keystone,
  detail,
  cellClass = "w-8 sm:w-9",
}: {
  name: string;
  icon: string;
  glyph?: string;
  selected: boolean;
  pick: PickNumbers | undefined;
  /** Tailwind size classes for the icon, e.g. "size-7 sm:size-8". */
  size: string;
  keystone?: boolean;
  /** Extra tooltip line (a shard's effect). */
  detail?: string;
  /** Width of the cell (icon + pick rate). */
  cellClass?: string;
}) {
  const fallback = (
    <span className="flex size-full items-center justify-center text-[10px] font-bold text-text-secondary">
      {glyph ?? name.slice(0, 2).toUpperCase()}
    </span>
  );
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn("flex flex-col items-center gap-1", cellClass)}>
          <span
            className={cn(
              "block shrink-0 overflow-hidden rounded-full transition-[opacity,filter] duration-150",
              size,
              selected
                ? keystone
                  ? "bg-black/50 ring-2 ring-gold shadow-[0_0_16px_-4px_rgba(200,170,110,0.7)]"
                  : "bg-black/40 ring-2 ring-gold/70"
                : "bg-black/30 opacity-35 ring-1 ring-white/10 grayscale",
            )}
          >
            <GameImage src={icon} alt={selected ? name : ""} className="size-full object-contain" fallback={fallback} />
          </span>
          <span
            className={cn(
              "text-[11px] leading-none tabular-nums",
              selected ? "font-semibold text-text" : "text-text-muted",
            )}
          >
            {pickText(pick)}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <span className="block font-medium text-text">{name}</span>
        {detail ? <span className="block text-text-secondary">{detail}</span> : null}
        {pick ? (
          <span className="block text-text-secondary tabular-nums">
            Taken in {pct(pick.pick_rate)} of games · {pct(pick.win_rate)} win rate
          </span>
        ) : (
          <span className="block text-text-secondary">Taken in under 1% of games.</span>
        )}
      </TooltipContent>
    </Tooltip>
  );
}

function RuneRow({
  runes,
  chosen,
  picks,
  keystone,
}: {
  runes: readonly RuneInfo[];
  chosen: ReadonlySet<number>;
  picks: ReadonlyMap<number, RunePick>;
  keystone?: boolean;
}) {
  return (
    <div className="flex justify-center gap-1 sm:gap-2">
      {runes.map((rune) => (
        <PerkCell
          key={rune.id}
          name={rune.name}
          icon={rune.icon}
          selected={chosen.has(rune.id)}
          pick={picks.get(rune.id)}
          size={keystone ? "size-8 sm:size-9" : "size-6 sm:size-7"}
          keystone={keystone}
        />
      ))}
    </div>
  );
}

function TreeColumn({
  tree,
  label,
  rows,
  chosen,
  picks,
  withKeystone,
}: {
  tree: RuneTree;
  label: string;
  rows: readonly (readonly RuneInfo[])[];
  chosen: ReadonlySet<number>;
  picks: ReadonlyMap<number, RunePick>;
  withKeystone: boolean;
}) {
  return (
    <section aria-label={`${label}: ${tree.name}`} className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center justify-center gap-2">
        <GameImage src={tree.icon} alt="" className="size-5 shrink-0 object-contain" />
        <div className="flex min-w-0 flex-col">
          <span className="label-caps leading-none">{label}</span>
          <span className="truncate text-sm font-semibold text-text">{tree.name}</span>
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {rows.map((runes, i) => (
          <div key={i} className={cn(withKeystone && i === 0 && "border-b border-border pb-3")}>
            <RuneRow runes={runes} chosen={chosen} picks={picks} keystone={withKeystone && i === 0} />
          </div>
        ))}
      </div>
    </section>
  );
}

function TreeSkeleton({ rows }: { rows: number }) {
  return (
    <div className="flex flex-col items-center gap-3" aria-hidden="true">
      <Skeleton className="h-8 w-28" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex gap-2">
          {Array.from({ length: 3 }, (_, j) => (
            <Skeleton key={j} className={cn("rounded-full", i === 0 && rows === 4 ? "size-9" : "size-7")} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** The three stat shard rows; the most common set is lit. */
function ShardRows({ top, picks }: { top: ShardSetOption | undefined; picks: readonly ShardPick[] }) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {SHARD_ROWS.map((row: ShardRow) => {
        const rowPicks = new Map(picks.filter((p) => p.row === row).map((p) => [p.shard_id, p]));
        const selected = top?.shard_ids[row];
        return (
          <section key={row} aria-label={`${SHARD_ROW_LABELS[row]} shard`} className="flex min-w-0 flex-col items-center gap-2">
            <span className="label-caps">{SHARD_ROW_LABELS[row]}</span>
            <div className="flex flex-wrap justify-center gap-0.5 sm:gap-1">
              {shardRowOptions(row, rowPicks.keys()).map((id) => {
                const shard = statShard(id);
                return (
                  <PerkCell
                    key={id}
                    name={shard.name}
                    icon={shard.icon}
                    glyph={shard.glyph}
                    detail={shard.effect}
                    selected={id === selected}
                    pick={rowPicks.get(id)}
                    size="size-6"
                    cellClass="w-7 sm:w-8"
                  />
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export interface RunePageProps {
  page: RunePageOption;
  /** Every rune's pick rate (any page), for the small numbers under the icons. */
  picks: readonly RunePick[];
  shards: readonly ShardSetOption[];
  shardPicks: readonly ShardPick[];
  /** Patch whose rune trees to draw ("16.18"). */
  patch: string | null;
}

/** A full rune page: primary tree (keystone + 3 rows), secondary tree (3 rows, 2 picked), stat shards. */
export function RunePage({ page, picks, shards, shardPicks, patch }: RunePageProps) {
  const trees = useRuneTrees(patch);
  const primary = trees.tree(page.primary_style_id);
  const secondary = trees.tree(page.secondary_style_id);
  const chosen = useMemo(() => new Set(page.rune_ids), [page.rune_ids]);
  const pickMap = useMemo(() => new Map(picks.map((p) => [p.rune_id, p])), [picks]);

  let treesBody;
  if (trees.loading) {
    treesBody = (
      <>
        <TreeSkeleton rows={4} />
        <TreeSkeleton rows={3} />
      </>
    );
  } else if (!primary || !secondary) {
    // Unknown trees (Data Dragon down, or runes from a patch it no longer describes): name what we can.
    const names = page.rune_ids.map((id) => trees.info(id)?.name ?? `Rune ${id}`);
    treesBody = (
      <p className="col-span-2 rounded-xl border border-dashed border-border-strong px-3 py-4 text-center text-sm text-text-secondary">
        {names.join(" · ")}
      </p>
    );
  } else {
    treesBody = (
      <>
        <TreeColumn tree={primary} label="Primary" rows={primary.slots} chosen={chosen} picks={pickMap} withKeystone />
        <TreeColumn tree={secondary} label="Secondary" rows={secondary.slots.slice(1)} chosen={chosen} picks={pickMap} withKeystone={false} />
      </>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-x-3 gap-y-4 sm:gap-x-6">{treesBody}</div>
      <div className="border-t border-border pt-4">
        <ShardRows top={shards[0]} picks={shardPicks} />
      </div>
    </div>
  );
}
