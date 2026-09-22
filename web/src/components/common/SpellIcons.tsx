import { spellName, useDdragon } from "@/lib/ddragon";
import { cn } from "@/lib/cn";

import { GameImage } from "./GameImage";

export interface SpellIconsProps {
  spell1: number;
  spell2: number;
  size?: "sm" | "md";
  orientation?: "vertical" | "horizontal";
  /** Game patch ("16.16"), so retired spells still have icons. Defaults to `<DdragonPatch>`. */
  patch?: string | null;
  className?: string;
}

const PX = { sm: 16, md: 20 } as const;

/** The two summoner spells, stacked by default (op.gg layout). */
export function SpellIcons({ spell1, spell2, size = "md", orientation = "vertical", patch, className }: SpellIconsProps) {
  const dd = useDdragon(patch);
  const px = PX[size];
  return (
    <div className={cn("flex gap-0.5", orientation === "vertical" ? "flex-col" : "flex-row", className)}>
      {[spell1, spell2].map((id, i) => (
        <span
          key={i}
          title={spellName(id)}
          className="block shrink-0 overflow-hidden rounded-[5px] bg-surface-3 ring-1 ring-white/10"
          style={{ width: px, height: px }}
        >
          <GameImage
            src={[dd.spellIcon(id), dd.latest.spellIcon(id)]}
            alt={spellName(id)}
            width={px}
            height={px}
            className="size-full object-cover"
          />
        </span>
      ))}
    </div>
  );
}
