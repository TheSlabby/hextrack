import { Wand2 } from "lucide-react";

import type { SpellOption } from "@/api/types";
import { GameImage } from "@/components/common/GameImage";
import { cn } from "@/lib/cn";
import { spellName, useDdragon } from "@/lib/ddragon";

import { OptionListHeader, OptionStats } from "./BuildPathRow";
import { DetailCard, EmptyNote } from "./DetailCard";

const SPELL_ROWS = 2;

function SpellIcon({ id, size = 28 }: { id: number; size?: number }) {
  const dd = useDdragon();
  const name = spellName(id);
  return (
    <span
      title={name}
      className="block shrink-0 overflow-hidden rounded-md bg-surface-3 ring-1 ring-white/10"
      style={{ width: size, height: size }}
    >
      <GameImage
        src={[dd.spellIcon(id), dd.latest.spellIcon(id)]}
        alt={name}
        width={size}
        height={size}
        className="size-full object-cover"
      />
    </span>
  );
}

/** The two most common summoner spell pairs. */
export function SpellOptions({ spells, className }: { spells: readonly SpellOption[]; className?: string }) {
  return (
    <DetailCard title="Summoner spells" icon={Wand2} className={className}>
      {spells.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <OptionListHeader label="Spells" />
          {spells.slice(0, SPELL_ROWS).map((option, i) => (
            <div
              key={option.spell_ids.join("-")}
              className={cn(
                "flex min-w-0 items-center justify-between gap-3 rounded-xl border px-3 py-2",
                i === 0 ? "border-gold/20 bg-gold/[0.04]" : "border-border bg-surface-2/40",
              )}
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="flex shrink-0 gap-1">
                  {option.spell_ids.map((id) => (
                    <SpellIcon key={id} id={id} />
                  ))}
                </span>
                <span className="truncate text-sm font-medium text-text">
                  {option.spell_ids.map(spellName).join(" + ")}
                </span>
              </div>
              <OptionStats option={option} />
            </div>
          ))}
        </div>
      ) : (
        <EmptyNote>No spell pair is common enough to show.</EmptyNote>
      )}
    </DetailCard>
  );
}
