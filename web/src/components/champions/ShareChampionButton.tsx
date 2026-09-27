import type { ChampionPlayer, ChampionTier } from "@/api/types";

export interface ShareChampionButtonProps {
  /** The player's games on the champion (from `useChampionPlayer`). */
  player: ChampionPlayer;
  /** The champion's tier in the player's main role for the page's patch window, if ranked. */
  tier: ChampionTier | null;
  className?: string;
}

/** Copies a "My <Champion> this season" card (PNG) for the player. */
export function ShareChampionButton(_props: ShareChampionButtonProps) {
  return null;
}
