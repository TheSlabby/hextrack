import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { useDdragon } from "@/lib/ddragon";
import { useItemCatalog } from "@/lib/ddragonItems";
import { formatInteger } from "@/lib/format";

import { GameImage } from "./GameImage";

export interface ItemSlotsProps {
  /** item0..item6 as returned by the API (item6 = trinket, 0 = empty). */
  items: readonly number[];
  size?: "sm" | "md";
  /** Hide the trinket slot. */
  hideTrinket?: boolean;
  /** Game patch ("16.16"), so removed items still have icons. Defaults to `<DdragonPatch>`. */
  patch?: string | null;
  className?: string;
}

const SLOT_PX = { sm: 22, md: 28 } as const;

function EmptySlot({ px, round }: { px: number; round?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn("block shrink-0 bg-white/[0.035] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)]", round ? "rounded-full" : "rounded-md")}
      style={{ width: px, height: px }}
    />
  );
}

/** Item whose icon can't be loaded: clearly "something was here", never a blank slot. */
function UnknownSlot({ px }: { px: number }) {
  return (
    <span
      aria-hidden="true"
      className="flex size-full items-center justify-center font-display font-bold text-text-muted"
      style={{ fontSize: Math.round(px * 0.55) }}
    >
      ?
    </span>
  );
}

/** Six item slots plus the trinket, named on hover. Empty slots stay visibly empty. */
export function ItemSlots({ items, size = "md", hideTrinket, patch, className }: ItemSlotsProps) {
  const dd = useDdragon(patch);
  const catalog = useItemCatalog(items, patch);
  const px = SLOT_PX[size];
  const slots = Array.from({ length: 7 }, (_, i) => items[i] ?? 0);
  const main = slots.slice(0, 6);
  const trinket = slots[6] ?? 0;

  const renderSlot = (id: number, index: number, round = false) => {
    if (id <= 0) return <EmptySlot key={index} px={px} round={round} />;
    const info = catalog.info(id);
    const name = info?.name ?? `Item ${id}`;
    const sources = [dd.itemIcon(id), dd.latest.itemIcon(id)];
    const tip: ReactNode = (
      <>
        <span className="font-medium text-text">{name}</span>
        {info?.plaintext ? <span className="block text-text-secondary">{info.plaintext}</span> : null}
        {info?.gold ? (
          <span className="block text-gold tabular-nums">{formatInteger(info.gold)} gold</span>
        ) : !info && catalog.ready ? (
          <span className="block text-text-secondary">No longer in the game.</span>
        ) : null}
      </>
    );
    return (
      <Tooltip key={index}>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "block shrink-0 overflow-hidden bg-surface-3 ring-1 ring-white/10",
              round ? "rounded-full" : "rounded-md",
            )}
            style={{ width: px, height: px }}
          >
            <GameImage
              src={sources}
              alt={name}
              width={px}
              height={px}
              className="size-full object-cover"
              fallback={<UnknownSlot px={px} />}
            />
          </span>
        </TooltipTrigger>
        <TooltipContent>{tip}</TooltipContent>
      </Tooltip>
    );
  };

  return (
    <div className={cn("flex items-center gap-1", className)} aria-label="Items">
      <div className="grid grid-flow-col grid-rows-1 gap-0.5">{main.map((id, i) => renderSlot(id, i))}</div>
      {hideTrinket ? null : <div className="ml-0.5">{renderSlot(trinket, 6, true)}</div>}
    </div>
  );
}
