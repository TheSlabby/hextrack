import { championDisplayName } from "@/lib/champions";
import { useDdragon } from "@/lib/ddragon";
import { cn } from "@/lib/cn";

import { GameImage } from "./GameImage";
import { ICON_PX, type IconSize } from "./sizes";

export interface ChampionIconProps {
  /** Data Dragon key / match champion_name, e.g. "MonkeyKing". */
  champion: string;
  size?: IconSize;
  /** Champion level badge (bottom-right). */
  level?: number | null;
  shape?: "rounded" | "circle";
  /** Highlight ring (e.g. the focused player). */
  highlight?: boolean;
  className?: string;
}

/** Square champion portrait with a lazy image, level badge and initials fallback. */
export function ChampionIcon({ champion, size = "md", level, shape = "rounded", highlight, className }: ChampionIconProps) {
  const dd = useDdragon();
  const px = ICON_PX[size];
  const name = championDisplayName(champion);
  const radius = shape === "circle" ? "rounded-full" : size === "xs" || size === "sm" ? "rounded-md" : "rounded-lg";

  return (
    <span
      className={cn("relative inline-flex shrink-0", className)}
      style={{ width: px, height: px }}
      title={name}
    >
      <span
        className={cn(
          "relative block size-full overflow-hidden bg-surface-3 ring-1 ring-white/10",
          radius,
          highlight && "ring-2 ring-gold",
        )}
      >
        <GameImage
          // Champions are never removed, so the newest version is always right (and best cached).
          src={champion ? dd.latest.championIcon(champion) : ""}
          alt={name}
          width={px}
          height={px}
          // Riot portraits have a thin baked-in border; crop it.
          className="size-full scale-[1.08] object-cover"
          fallback={
            <span
              aria-label={name}
              role="img"
              className="flex size-full items-center justify-center font-display font-semibold text-text-secondary"
              style={{ fontSize: Math.max(9, px * 0.34) }}
            >
              {name.slice(0, 2).toUpperCase()}
            </span>
          }
        />
      </span>
      {level !== undefined && level !== null ? (
        <span
          className={cn(
            "absolute -right-1 -bottom-1 flex items-center justify-center rounded-full border border-bg bg-surface-3 px-1 font-semibold tabular-nums text-text",
            px >= 56 ? "h-5 min-w-5 text-[11px]" : "h-4 min-w-4 text-[10px]",
          )}
          aria-label={`Level ${level}`}
        >
          {level}
        </span>
      ) : null}
    </span>
  );
}
