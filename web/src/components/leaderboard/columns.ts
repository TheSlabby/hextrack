import type { SortKey } from "./sorting";

export interface LeaderboardColumn {
  id: string;
  label: string;
  sortKey?: SortKey;
  align?: "left" | "right" | "center";
  /** Explains the column in a header tooltip. */
  hint?: string;
  className?: string;
}

/**
 * Column layout shared with the loading skeleton so both render the same widths. From xl the
 * table uses a fixed layout that always fits its card (the player column takes the rest);
 * below xl it keeps a minimum width and scrolls inside the card.
 */
export const LEADERBOARD_COLUMNS: readonly LeaderboardColumn[] = [
  {
    id: "standing",
    label: "#",
    sortKey: "standing",
    align: "center",
    className: "w-[52px] pl-4",
    hint: "Overall standing by average AI Score, for players with at least 20 ranked games this season",
  },
  { id: "player", label: "Player", sortKey: "player", className: "min-w-48 xl:min-w-0" },
  { id: "rank", label: "Rank", sortKey: "rank", className: "w-32" },
  { id: "games", label: "Games", sortKey: "games", align: "right", className: "w-20" },
  { id: "winrate", label: "Win rate", sortKey: "winrate", className: "w-[124px]" },
  { id: "kda", label: "KDA", sortKey: "kda", className: "w-24" },
  {
    id: "ai",
    label: "AI Score",
    sortKey: "ai",
    align: "center",
    className: "w-24",
    hint: "Average AI Score this season (0 to 100), with where the player's games sit among all scored games in the same role. Averages follow win rate closely, so they aren't graded",
  },
  {
    id: "lp",
    label: "Season LP",
    sortKey: "lp",
    align: "right",
    className: "w-[108px]",
    hint: "Solo/Duo LP gained or lost since the season started",
  },
  { id: "ally", label: "Best duo", className: "w-32", hint: "Tracked teammate with the most wins together" },
  { id: "champions", label: "Champions", className: "w-24", hint: "Most played champions this season" },
  {
    id: "form",
    label: "Form",
    className: "w-[156px] pr-4",
    hint: "Last 10 games, newest first, with the current streak once it reaches 3",
  },
];
