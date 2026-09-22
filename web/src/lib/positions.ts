/** Team positions: labels, order and hand-drawn icon geometry (24x24 viewBox). */
import type { Position } from "@/api/types";

export const POSITION_ORDER: readonly Position[] = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];

export const POSITION_LABELS: Readonly<Record<Position, string>> = {
  TOP: "Top",
  JUNGLE: "Jungle",
  MIDDLE: "Mid",
  BOTTOM: "Bot",
  UTILITY: "Support",
  UNKNOWN: "Unknown",
};

export const POSITION_LONG_LABELS: Readonly<Record<Position, string>> = {
  TOP: "Top lane",
  JUNGLE: "Jungle",
  MIDDLE: "Mid lane",
  BOTTOM: "Bot lane",
  UTILITY: "Support",
  UNKNOWN: "Unknown role",
};

export interface PositionIconPaths {
  /** Primary shape, drawn in currentColor. */
  primary: string;
  /** Secondary shape, drawn at reduced opacity. */
  secondary?: string;
}

/** Simplified lane-map glyphs in the style of the in-game role icons. */
export const POSITION_ICONS: Readonly<Record<Position, PositionIconPaths>> = {
  TOP: {
    primary: "M3 3h14l-3.5 3.5H6.5v7L3 17z",
    secondary: "M9.5 9.5h5v5h-5zM20 7v14H6l3.5-3.5h7v-7z",
  },
  MIDDLE: {
    primary: "M16.5 3H21v4.5L7.5 21H3v-4.5z",
    secondary: "M3 3h9l-3 3H6v3l-3 3zM21 21h-9l3-3h3v-3l3-3z",
  },
  BOTTOM: {
    primary: "M21 21H7l3.5-3.5h7v-7L21 7z",
    secondary: "M9.5 9.5h5v5h-5zM4 17V3h14l-3.5 3.5h-7v7z",
  },
  JUNGLE: {
    primary:
      "M7.2 2.5c2.9 3.2 4.3 6.9 4.4 11.2.1 2.3-.4 4.7-1.4 7.8-1.9-3.9-2.6-7.2-2.2-10.2C5.6 9.4 4.3 6.4 4 2.8c1.5 1.9 2.9 3.2 4.3 4-.1-1.4-.5-2.8-1.1-4.3zM16.8 2.5c-.6 1.5-1 2.9-1.1 4.3 1.4-.8 2.8-2.1 4.3-4-.3 3.6-1.6 6.6-4 8.6.4 3-.3 6.3-2.2 10.2-.5-1.6-.9-3-1.1-4.4.8-2.5 1-4.9.5-7.2.8-2.9 2-5.4 3.6-7.5z",
  },
  UTILITY: {
    primary:
      "M12 21l-3.2-4.2.9-6.3L12 12l2.3-1.5.9 6.3zM9.5 5h5L13.3 8 12 9 10.7 8zM2 7h6.3l1.4 2.6L7.3 12 5 11.4 6.3 9.3z M22 7h-6.3l-1.4 2.6 2.4 2.4 2.3-.6-1.3-2.1z",
  },
  UNKNOWN: {
    primary: "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zm0 2.2a6.8 6.8 0 1 0 0 13.6 6.8 6.8 0 0 0 0-13.6z",
    secondary: "M11 15.5h2v2h-2zM12 6.5c1.9 0 3.3 1.3 3.3 3 0 1.3-.8 2-1.6 2.6-.5.3-.7.6-.7 1.2v.4h-2v-.6c0-1.1.5-1.8 1.3-2.3.6-.4 1-.7 1-1.3 0-.7-.6-1.2-1.3-1.2-.8 0-1.4.5-1.5 1.3l-2-.3c.3-1.7 1.7-2.8 3.5-2.8z",
  },
};

export function positionLabel(position: Position | null | undefined): string {
  return position ? POSITION_LABELS[position] : POSITION_LABELS.UNKNOWN;
}
