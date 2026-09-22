/** Shared grid classes so the loaded page and its skeleton line up exactly. */

/** Sidebar (340px at lg) + main column. Below lg the rank strip stacks above the tabs. */
export const SUMMONER_GRID = "grid items-start gap-6 lg:grid-cols-[340px_minmax(0,1fr)]";

/** Sidebar cards, stacked beside the main column (the sidebar only exists at lg and up). */
export const SIDEBAR_GRID = "grid min-w-0 gap-4";

/** Season cards inside the Overview tab below lg: two columns once there is room. */
export const SEASON_GRID = "md:grid-cols-2";

/** The season AI Score panel in the profile header (fixed footprint so loading never shifts it). */
export const AI_PANEL =
  "flex items-center gap-4 self-stretch rounded-2xl border border-cyan/15 bg-surface-1/55 p-3 pr-4 shadow-[var(--shadow-card),0_0_40px_-22px_rgba(10,200,185,0.5)] backdrop-blur-md min-h-[11rem] sm:min-h-[10.75rem] sm:gap-5 sm:self-start sm:p-4 sm:pr-6 lg:w-[26.5rem] lg:self-auto";
