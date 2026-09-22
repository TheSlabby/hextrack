import { UserRound } from "lucide-react";

import { useDdragon } from "@/lib/ddragon";
import { cn } from "@/lib/cn";

import { GameImage } from "./GameImage";
import { ICON_PX, type IconSize } from "./sizes";

export interface ProfileIconProps {
  iconId: number | null | undefined;
  level?: number | null;
  size?: IconSize;
  className?: string;
  alt?: string;
}

/** Summoner profile icon inside a gold hextech ring, with an optional level plate. */
export function ProfileIcon({ iconId, level, size = "lg", className, alt = "Profile icon" }: ProfileIconProps) {
  const dd = useDdragon();
  const px = ICON_PX[size];
  const ring = px >= 56 ? 3 : 2;
  const showLevel = level !== undefined && level !== null && px >= 40;

  return (
    <span className={cn("relative inline-flex shrink-0", showLevel && "mb-2", className)} style={{ width: px, height: px }}>
      <span
        className="block size-full rounded-full bg-gradient-to-b from-gold-bright via-gold to-gold-deep shadow-[0_0_24px_-6px_rgba(200,170,110,0.55)]"
        style={{ padding: ring }}
      >
        <span className="block size-full overflow-hidden rounded-full bg-surface-3 ring-2 ring-bg">
          <GameImage
            src={iconId !== null && iconId !== undefined ? dd.latest.profileIcon(iconId) : ""}
            alt={alt}
            width={px}
            height={px}
            className="size-full object-cover"
            fallback={
              <span className="flex size-full items-center justify-center text-text-muted">
                <UserRound style={{ width: px * 0.5, height: px * 0.5 }} aria-hidden="true" />
              </span>
            }
          />
        </span>
      </span>
      {showLevel ? (
        <span
          className="absolute -bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-gold/60 bg-bg px-1.5 py-px text-[11px] leading-4 font-semibold tabular-nums text-gold-bright"
          aria-label={`Level ${level}`}
        >
          {level}
        </span>
      ) : null}
    </span>
  );
}
