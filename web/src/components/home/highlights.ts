/** Roster highlights computed client-side from the season leaderboard. */
import type { BestAlly, LeaderboardEntry } from "@/api/types";

export interface PlayerHighlight {
  entry: LeaderboardEntry;
  value: number;
}

export interface DuoHighlight {
  entry: LeaderboardEntry;
  ally: BestAlly;
  /** The ally's own leaderboard row, when they are on the roster. */
  allyEntry: LeaderboardEntry | null;
}

export interface RosterHighlights {
  bestWinrate: PlayerHighlight | null;
  /** Games required to qualify for best win rate. */
  winrateMinGames: number;
  mostGames: PlayerHighlight | null;
  climber: PlayerHighlight | null;
  duo: DuoHighlight | null;
}

/** Win rates over tiny samples are noise: require 5 games, or everyone's max if lower. */
const WINRATE_MIN_GAMES = 5;
const DUO_MIN_GAMES = 3;

function maxBy<T>(items: readonly T[], score: (item: T) => number, tieBreak: (item: T) => number): T | null {
  let best: T | null = null;
  for (const item of items) {
    if (
      best === null ||
      score(item) > score(best) ||
      (score(item) === score(best) && tieBreak(item) > tieBreak(best))
    ) {
      best = item;
    }
  }
  return best;
}

export function computeHighlights(entries: readonly LeaderboardEntry[]): RosterHighlights {
  const withGames = entries.filter((e) => e.games > 0);
  const maxGames = withGames.reduce((max, e) => Math.max(max, e.games), 0);
  const winrateMinGames = Math.max(1, Math.min(WINRATE_MIN_GAMES, maxGames));

  const winrateCandidates = withGames.filter((e) => e.games >= winrateMinGames);
  const bestWinrateEntry = maxBy(
    winrateCandidates,
    (e) => e.winrate,
    (e) => e.games,
  );
  const mostGamesEntry = maxBy(
    withGames,
    (e) => e.games,
    (e) => e.winrate,
  );

  const climberCandidates = entries.filter((e) => e.lp_delta !== null);
  const climberEntry = maxBy(
    climberCandidates,
    (e) => e.lp_delta ?? 0,
    (e) => e.games,
  );

  const duos = entries.flatMap((entry) => (entry.best_ally ? [{ entry, ally: entry.best_ally }] : []));
  const qualified = duos.filter((d) => d.ally.games >= DUO_MIN_GAMES);
  const duoPick = maxBy(
    qualified.length ? qualified : duos,
    (d) => d.ally.winrate,
    (d) => d.ally.games,
  );

  return {
    bestWinrate: bestWinrateEntry ? { entry: bestWinrateEntry, value: bestWinrateEntry.winrate } : null,
    winrateMinGames,
    mostGames: mostGamesEntry ? { entry: mostGamesEntry, value: mostGamesEntry.games } : null,
    climber: climberEntry ? { entry: climberEntry, value: climberEntry.lp_delta ?? 0 } : null,
    duo: duoPick
      ? {
          entry: duoPick.entry,
          ally: duoPick.ally,
          allyEntry: entries.find((e) => e.puuid === duoPick.ally.puuid) ?? null,
        }
      : null,
  };
}
