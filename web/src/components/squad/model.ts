/**
 * View model for /squad (duo synergy grid, who carries whom) built from `GET /squad/pairs`.
 *
 * Pairs come back once per roster pair (`a_puuid < b_puuid`, same team only); the grids
 * read them from either side, so every value here is "oriented": `row*` is the row player,
 * `col*` the column player. AI values stay on the API's 0..1 scale (the UI multiplies by
 * 100 when it prints them), including `diff`.
 */
import type { SquadPair, SquadPairs, SquadPlayer } from "@/api/types";
import { formatSigned } from "@/lib/format";
import { toScore100 } from "@/lib/score";

/** Best / worst duo lists only rank pairs with at least this many games together. */
export const DUO_LIST_MIN_GAMES = 10;
/** Carry-rate ranking: at least this many scored duo games (summed over partners). */
export const CARRY_MIN_GAMES = 10;
/** How many duos each list shows. */
export const DUO_LIST_SIZE = 5;

export interface SquadModel {
  /** Players in the grids: tracked players with at least one duo game, most duo games first. */
  players: SquadPlayer[];
  /** Tracked players left out of the grids (no duo games in the period). */
  benched: SquadPlayer[];
  /** Display name per puuid; "#TAG" is appended when two grid players share a game name. */
  labels: ReadonlyMap<string, string>;
  /** Players by puuid. */
  byPuuid: ReadonlyMap<string, SquadPlayer>;
  /** Grid cells below this many games are muted (from the response). */
  minGames: number;
  /** The pair for two players, in either order. */
  pair: (a: string, b: string) => SquadPair | undefined;
  /** Every pair, as returned (most games first). */
  pairs: readonly SquadPair[];
  /** Pairs with at least one game where both players were scored by the active model. */
  scoredPairs: number;
}

/** One pair seen from the row player's side. */
export interface DuoView {
  pair: SquadPair;
  row: SquadPlayer;
  col: SquadPlayer;
  games: number;
  wins: number;
  losses: number;
  winrate: number;
  expected: number;
  delta: number;
  /** Row / column player's average AI Score in the scored shared games (0..1). */
  rowAi: number | null;
  colAi: number | null;
  scored: number;
  rowHigher: number;
  colHigher: number;
  ties: number;
  /** Row minus column average AI Score (0..1 scale, -1..1). */
  diff: number | null;
  /** Share of scored shared games in which the row player had the higher score. */
  rowShare: number | null;
}

function pairKey(a: string, b: string): string {
  return a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}

export function buildSquadModel(data: SquadPairs): SquadModel {
  const byPuuid = new Map(data.players.map((player) => [player.puuid, player]));
  const pairs = new Map<string, SquadPair>();
  const duoGames = new Map<string, number>();
  let scoredPairs = 0;
  for (const pair of data.pairs) {
    if (!byPuuid.has(pair.a_puuid) || !byPuuid.has(pair.b_puuid)) continue;
    pairs.set(pairKey(pair.a_puuid, pair.b_puuid), pair);
    duoGames.set(pair.a_puuid, (duoGames.get(pair.a_puuid) ?? 0) + pair.games);
    duoGames.set(pair.b_puuid, (duoGames.get(pair.b_puuid) ?? 0) + pair.games);
    if (pair.scored_games > 0) scoredPairs += 1;
  }

  // The response lists players most games first; the grids put the busiest duo players
  // top-left so the dense part of the matrix sits together.
  const order = new Map(data.players.map((player, index) => [player.puuid, index]));
  const players = data.players
    .filter((player) => (duoGames.get(player.puuid) ?? 0) > 0)
    .sort(
      (a, b) =>
        (duoGames.get(b.puuid) ?? 0) - (duoGames.get(a.puuid) ?? 0) ||
        (order.get(a.puuid) ?? 0) - (order.get(b.puuid) ?? 0),
    );
  const benched = data.players.filter((player) => (duoGames.get(player.puuid) ?? 0) === 0);

  const nameCounts = new Map<string, number>();
  for (const player of players) {
    const key = player.game_name.toLocaleLowerCase();
    nameCounts.set(key, (nameCounts.get(key) ?? 0) + 1);
  }
  const labels = new Map(
    players.map((player) => [
      player.puuid,
      (nameCounts.get(player.game_name.toLocaleLowerCase()) ?? 0) > 1
        ? `${player.game_name}#${player.tag_line}`
        : player.game_name,
    ]),
  );

  return {
    players,
    benched,
    labels,
    byPuuid,
    minGames: data.min_games,
    pair: (a, b) => pairs.get(pairKey(a, b)),
    pairs: data.pairs.filter((pair) => pairs.has(pairKey(pair.a_puuid, pair.b_puuid))),
    scoredPairs,
  };
}

/** A pair seen from `row`'s side. */
export function orient(pair: SquadPair, row: SquadPlayer, col: SquadPlayer): DuoView {
  const rowIsA = pair.a_puuid === row.puuid;
  const diff = pair.avg_score_diff === null ? null : rowIsA ? pair.avg_score_diff : -pair.avg_score_diff;
  const rowHigher = rowIsA ? pair.a_higher : pair.b_higher;
  return {
    pair,
    row,
    col,
    games: pair.games,
    wins: pair.wins,
    losses: pair.games - pair.wins,
    winrate: pair.winrate,
    expected: pair.expected_winrate,
    delta: pair.winrate_delta,
    rowAi: rowIsA ? pair.avg_ai_a : pair.avg_ai_b,
    colAi: rowIsA ? pair.avg_ai_b : pair.avg_ai_a,
    scored: pair.scored_games,
    rowHigher,
    colHigher: rowIsA ? pair.b_higher : pair.a_higher,
    ties: pair.ties,
    diff,
    rowShare: pair.scored_games > 0 ? rowHigher / pair.scored_games : null,
  };
}

export interface DuoEntry {
  a: SquadPlayer;
  b: SquadPlayer;
  pair: SquadPair;
}

/**
 * Best and worst duos: pairs with at least {@link DUO_LIST_MIN_GAMES} games, ranked by win
 * rate together minus their usual (expected) win rate. A duo only makes the "best" list
 * when it beats its expected win rate, and the "worst" list when it falls short.
 */
export function rankDuos(model: SquadModel): { best: DuoEntry[]; worst: DuoEntry[]; eligible: number } {
  const entries: DuoEntry[] = [];
  for (const pair of model.pairs) {
    const a = model.byPuuid.get(pair.a_puuid);
    const b = model.byPuuid.get(pair.b_puuid);
    if (a && b && pair.games >= DUO_LIST_MIN_GAMES) entries.push({ a, b, pair });
  }
  const best = entries
    .filter((entry) => entry.pair.winrate_delta > 0)
    .sort((x, y) => y.pair.winrate_delta - x.pair.winrate_delta || y.pair.games - x.pair.games)
    .slice(0, DUO_LIST_SIZE);
  const worst = entries
    .filter((entry) => entry.pair.winrate_delta < 0)
    .sort((x, y) => x.pair.winrate_delta - y.pair.winrate_delta || y.pair.games - x.pair.games)
    .slice(0, DUO_LIST_SIZE);
  return { best, worst, eligible: entries.length };
}

export interface CarryStanding {
  player: SquadPlayer;
  /** Scored duo games, summed over squad teammates (a game with two teammates counts twice). */
  scored: number;
  higher: number;
  lower: number;
  ties: number;
  /** higher / scored, or null without scored games. */
  rate: number | null;
  /** Average of (own score minus teammate's score) over those games, 0..1 scale. */
  avgDiff: number | null;
  /** Squad teammates with at least one scored duo game. */
  partners: number;
  qualified: boolean;
}

/**
 * Carry-rate ranking: for every grid player, the share of their scored duo games (summed
 * over squad teammates) in which they had the higher AI Score. Players under
 * {@link CARRY_MIN_GAMES} scored duo games are listed last and not ranked.
 */
export function carryStandings(model: SquadModel): CarryStanding[] {
  const standings = model.players.map((player): CarryStanding => {
    let scored = 0;
    let higher = 0;
    let lower = 0;
    let ties = 0;
    let diffSum = 0;
    let partners = 0;
    for (const other of model.players) {
      if (other.puuid === player.puuid) continue;
      const pair = model.pair(player.puuid, other.puuid);
      if (!pair || pair.scored_games === 0) continue;
      const view = orient(pair, player, other);
      scored += view.scored;
      higher += view.rowHigher;
      lower += view.colHigher;
      ties += view.ties;
      diffSum += (view.diff ?? 0) * view.scored;
      partners += 1;
    }
    return {
      player,
      scored,
      higher,
      lower,
      ties,
      rate: scored > 0 ? higher / scored : null,
      avgDiff: scored > 0 ? diffSum / scored : null,
      partners,
      qualified: scored >= CARRY_MIN_GAMES,
    };
  });
  return standings.sort(
    (x, y) =>
      Number(y.qualified) - Number(x.qualified) ||
      (y.rate ?? -1) - (x.rate ?? -1) ||
      y.scored - x.scored,
  );
}

/** Average AI Score gap in points: 0.031 -> "+3", -0.12 -> "−12". */
export function gapText(diff: number): string {
  return formatSigned(Math.round(diff * 100));
}

/** A 0..1 AI Score as a 0..100 figure, or "not scored". */
export function scoreText(score: number | null): string {
  return score === null ? "not scored" : String(toScore100(score));
}
