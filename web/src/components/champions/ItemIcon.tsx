import type { ReactNode } from "react";

import { GameImage } from "@/components/common/GameImage";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { useDdragon } from "@/lib/ddragon";
import { formatInteger } from "@/lib/format";

import { itemLabel, useItemInfo } from "./detailModel";

/**
 * One item icon at the patch of the nearest `<DdragonPatch>` (falling back to the newest
 * version), with its name, summary and cost on hover.
 */
export function ItemIcon({ id, size = 32, className }: { id: number; size?: number; className?: string }) {
  const dd = useDdragon();
  const info = useItemInfo(id);
  const name = itemLabel(id, info);
  const tip: ReactNode = (
    <>
      <span className="font-medium text-text">{name}</span>
      {info?.plaintext ? <span className="block text-text-secondary">{info.plaintext}</span> : null}
      {info?.gold ? <span className="block text-gold tabular-nums">{formatInteger(info.gold)} gold</span> : null}
    </>
  );
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn("block shrink-0 overflow-hidden rounded-md bg-surface-3 ring-1 ring-white/10", className)}
          style={{ width: size, height: size }}
        >
          <GameImage
            src={[dd.itemIcon(id), dd.latest.itemIcon(id)]}
            alt={name}
            width={size}
            height={size}
            className="size-full object-cover"
            fallback={
              <span
                role="img"
                aria-label={name}
                className="flex size-full items-center justify-center font-display font-bold text-text-muted"
                style={{ fontSize: Math.round(size * 0.5) }}
              >
                ?
              </span>
            }
          />
        </span>
      </TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  );
}

/** The item's name as text (for rows that list single items); one line, or up to two with `lines={2}`. */
export function ItemName({ id, lines = 1, className }: { id: number; lines?: 1 | 2; className?: string }) {
  const info = useItemInfo(id);
  return <span className={cn(lines === 1 ? "truncate" : "line-clamp-2", className)}>{itemLabel(id, info)}</span>;
}
