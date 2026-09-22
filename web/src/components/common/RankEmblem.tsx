import { useId } from "react";

import type { Tier } from "@/api/types";
import { cn } from "@/lib/cn";
import { TIER_COLORS, TIER_ORDER, formatTier, tierIndex, UNRANKED_COLOR } from "@/lib/tiers";

export interface RankEmblemProps {
  tier: Tier | null | undefined;
  size?: number;
  className?: string;
  /** Accessible label; defaults to the tier name. */
  title?: string;
}

/** Mix a hex colour toward white (amount > 0) or black (amount < 0). */
function shade(hex: string, amount: number): string {
  const n = Number.parseInt(hex.slice(1), 16);
  const channels = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  const target = amount >= 0 ? 255 : 0;
  const t = Math.abs(amount);
  const mixed = channels.map((c) => Math.round(c + (target - c) * t));
  return `#${mixed.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

// Geometry on a 100x100 canvas, pointy-top hexagons centred at (50, 52).
const OUTER_HEX = "M50 10 L84 30 L84 72 L50 92 L16 72 L16 30 Z";
const INNER_HEX = "M50 20 L75.5 35 L75.5 67 L50 82 L24.5 67 L24.5 35 Z";
const GEM = "M50 34 L63 51 L50 70 L37 51 Z";
const GEM_FACET = "M50 34 L63 51 L50 51 Z";
const WINGS = "M16 36 L4 30 L9 46 L4 60 L16 56 Z M84 36 L96 30 L91 46 L96 60 L84 56 Z";
const WINGS_LARGE = "M16 32 L0 22 L6 42 L0 54 L6 66 L16 62 Z M84 32 L100 22 L94 42 L100 54 L94 66 L84 62 Z";
const CROWN_SMALL = "M40 14 L44 3 L50 10 L56 3 L60 14 L50 10 Z";
const CROWN = "M36 16 L38 0 L45 9 L50 -2 L55 9 L62 0 L64 16 L50 10 Z";
const BASE = "M34 86 L50 98 L66 86 L50 92 Z";

/**
 * Hand-built hextech rank emblem: a faceted hexagon in the tier colour. Higher tiers gain
 * wings (Platinum+), a crest (Diamond+) and a crown (apex tiers). No external images.
 */
export function RankEmblem({ tier, size = 48, className, title }: RankEmblemProps) {
  const uid = useId().replace(/:/g, "");
  const color = tier ? TIER_COLORS[tier] : UNRANKED_COLOR;
  const idx = tier ? tierIndex(tier) : -1;
  const label = title ?? formatTier(tier);
  const light = shade(color, 0.45);
  const dark = shade(color, -0.55);
  const deep = shade(color, -0.82);
  const apex = idx >= TIER_ORDER.indexOf("MASTER");

  return (
    <svg
      viewBox="-2 -4 104 106"
      width={size}
      height={size}
      role="img"
      aria-label={label}
      className={cn("shrink-0 overflow-visible", className)}
    >
      <title>{label}</title>
      <defs>
        <linearGradient id={`${uid}-frame`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={light} />
          <stop offset="55%" stopColor={color} />
          <stop offset="100%" stopColor={dark} />
        </linearGradient>
        <linearGradient id={`${uid}-core`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={shade(color, -0.6)} />
          <stop offset="100%" stopColor={deep} />
        </linearGradient>
        <radialGradient id={`${uid}-glow`} cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor={color} stopOpacity={tier ? 0.45 : 0.15} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </radialGradient>
        <linearGradient id={`${uid}-gem`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={shade(color, 0.7)} />
          <stop offset="50%" stopColor={color} />
          <stop offset="100%" stopColor={shade(color, -0.35)} />
        </linearGradient>
      </defs>

      <circle cx="50" cy="52" r="50" fill={`url(#${uid}-glow)`} />

      {idx >= TIER_ORDER.indexOf("PLATINUM") ? (
        <path d={idx >= TIER_ORDER.indexOf("DIAMOND") ? WINGS_LARGE : WINGS} fill={`url(#${uid}-frame)`} opacity={0.9} />
      ) : null}
      {apex ? <path d={CROWN} fill={`url(#${uid}-frame)`} /> : idx >= TIER_ORDER.indexOf("GOLD") ? <path d={CROWN_SMALL} fill={`url(#${uid}-frame)`} /> : null}
      {idx >= TIER_ORDER.indexOf("SILVER") ? <path d={BASE} fill={dark} /> : null}

      <path d={OUTER_HEX} fill={`url(#${uid}-frame)`} />
      <path d={OUTER_HEX} fill="none" stroke={light} strokeOpacity={0.5} strokeWidth={1} />
      <path d={INNER_HEX} fill={`url(#${uid}-core)`} />
      <path d={INNER_HEX} fill="none" stroke={shade(color, -0.2)} strokeWidth={1.5} />

      {tier ? (
        <>
          <path d={GEM} fill={`url(#${uid}-gem)`} />
          <path d={GEM_FACET} fill="#ffffff" opacity={0.28} />
          <path d={GEM} fill="none" stroke={light} strokeWidth={1} strokeOpacity={0.8} />
        </>
      ) : (
        <path d={GEM} fill="none" stroke={color} strokeWidth={2} strokeDasharray="4 3" opacity={0.8} />
      )}
    </svg>
  );
}
