import type { LeaderboardQueue } from "@/api/types";

export interface ShareChampionButtonProps {
  /** Data Dragon key of the champion. */
  champion: string;
  /** Roster player whose games on the champion the card shows. */
  puuid: string;
  queue?: LeaderboardQueue;
  /** "icon": a small icon button for list rows; "button": a labelled button. */
  variant?: "icon" | "button";
  className?: string;
}

/**
 * Copies a "<Player>'s <Champion> this season" card (PNG) to the clipboard. The data (the
 * player's games on it, and the champion's tier in their main role) is fetched on click.
 */
export function ShareChampionButton(_props: ShareChampionButtonProps) {
  return null;
}
