/**
 * Win / loss streaks from a newest-first list of results, and the fun label for each length.
 * Only runs of MIN_STREAK or more are worth a badge.
 */

export const MIN_STREAK = 3;
/** How many results the API sends: `SummonerProfile.recent_form` and `LeaderboardEntry.recent_form`. */
export const PROFILE_FORM_LIMIT = 20;
export const LEADERBOARD_FORM_LIMIT = 10;

export interface Streak {
  win: boolean;
  length: number;
  /** True when the whole capped list is one streak, so it may be longer ("10+"). */
  open: boolean;
}

export interface StreakInfo extends Streak {
  /** "5W streak" / "10+L streak". */
  short: string;
  /** "On fire", "Tilt watch" ... */
  mood: string;
  /** "5 ranked wins in a row". */
  description: string;
}

/**
 * Current streak from results ordered newest first; null when there are no results. `limit` is
 * how many results the source can hold: a streak filling a full list may run further back.
 */
export function currentStreak(resultsNewestFirst: readonly boolean[], limit = Infinity): Streak | null {
  const first = resultsNewestFirst[0];
  if (first === undefined) return null;
  let length = 0;
  for (const result of resultsNewestFirst) {
    if (result !== first) break;
    length += 1;
  }
  return { win: first, length, open: length === resultsNewestFirst.length && length >= limit };
}

const WIN_MOODS: ReadonlyArray<readonly [number, string]> = [
  [10, "Is this a smurf?"],
  [8, "Unstoppable"],
  [5, "On fire"],
  [3, "Heating up"],
];
const LOSS_MOODS: ReadonlyArray<readonly [number, string]> = [
  [10, "Uninstall?"],
  [7, "Please touch grass"],
  [5, "Tilt watch"],
  [3, "Rough patch"],
];

/** A streak worth showing (MIN_STREAK+), with its labels; null otherwise. */
export function streakInfo(resultsNewestFirst: readonly boolean[], limit: number): StreakInfo | null {
  const streak = currentStreak(resultsNewestFirst, limit);
  if (!streak || streak.length < MIN_STREAK) return null;
  const count = `${streak.length}${streak.open ? "+" : ""}`;
  const moods = streak.win ? WIN_MOODS : LOSS_MOODS;
  const mood = moods.find(([min]) => streak.length >= min)?.[1] ?? "";
  return {
    ...streak,
    short: `${count}${streak.win ? "W" : "L"} streak`,
    mood,
    description: `${streak.open ? "At least " : ""}${streak.length} ranked ${streak.win ? "wins" : "losses"} in a row`,
  };
}
