import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";

import { championDisplayName, championSlug } from "@/lib/champions";
import { cn } from "@/lib/cn";

export interface ChampionLinkProps {
  /** Data Dragon key, e.g. "MonkeyKing". */
  champion: string;
  /** Defaults to the champion's display name. */
  children?: ReactNode;
  className?: string;
  /** Accessible name when the children are only an icon. */
  "aria-label"?: string;
}

/**
 * Link to a champion's page. Never nest it inside another link (a match row that is itself
 * a link): use it only where the champion sits in plain content.
 */
export function ChampionLink({ champion, children, className, "aria-label": ariaLabel }: ChampionLinkProps) {
  return (
    <Link
      to="/champions/$champion"
      params={{ champion: championSlug(champion) }}
      aria-label={ariaLabel}
      title={championDisplayName(champion)}
      className={cn(
        "rounded-sm transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        className,
      )}
    >
      {children ?? championDisplayName(champion)}
    </Link>
  );
}
