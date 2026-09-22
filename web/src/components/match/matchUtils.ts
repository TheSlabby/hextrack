/**
 * Pure helpers shared by the match list, match rows and match detail (no React here, so
 * component files stay react-refresh clean).
 */
import type { MatchDetail, MatchSummary, ParticipantSummary, Position, TeamId } from "@/api/types";
import { championDisplayName } from "@/lib/champions";
import { POSITION_ORDER } from "@/lib/positions";
import { QUEUE_FLEX, QUEUE_SOLO, queueRowLabel } from "@/lib/queues";

// --- outcome ------------------------------------------------------------------------------

export type Outcome = "win" | "loss" | "remake";

export function outcomeOf(remake: boolean, win: boolean): Outcome {
  if (remake) return "remake";
  return win ? "win" : "loss";
}

export const OUTCOME_LABEL: Readonly<Record<Outcome, string>> = {
  win: "Victory",
  loss: "Defeat",
  remake: "Remake",
};

export const OUTCOME_SHORT: Readonly<Record<Outcome, string>> = {
  win: "W",
  loss: "L",
  remake: "R",
};

export interface OutcomeStyle {
  /** Result text colour. */
  text: string;
  /** Solid left stripe. */
  stripe: string;
  /** Horizontal tint wash over the row surface. */
  wash: string;
  /** Row border. */
  border: string;
  /** Hover border. */
  hoverBorder: string;
  /** Solid bar fill (damage bars). */
  bar: string;
  /** Soft chip (day header record, team header). */
  chip: string;
}

export const OUTCOME_STYLES: Readonly<Record<Outcome, OutcomeStyle>> = {
  win: {
    text: "text-win",
    stripe: "bg-win",
    wash: "from-win/[0.13] via-win/[0.06] to-win/[0.02]",
    border: "border-win/20",
    hoverBorder: "hover:border-win/40",
    bar: "bg-win",
    chip: "border-win/30 bg-win/10 text-win",
  },
  loss: {
    text: "text-loss",
    stripe: "bg-loss",
    wash: "from-loss/[0.12] via-loss/[0.05] to-loss/[0.02]",
    border: "border-loss/20",
    hoverBorder: "hover:border-loss/40",
    bar: "bg-loss",
    chip: "border-loss/30 bg-loss/10 text-loss",
  },
  remake: {
    text: "text-remake",
    stripe: "bg-remake",
    wash: "from-remake/[0.1] via-remake/[0.04] to-transparent",
    border: "border-remake/20",
    hoverBorder: "hover:border-remake/40",
    bar: "bg-remake",
    chip: "border-remake/30 bg-remake/10 text-remake",
  },
};

// --- queues -------------------------------------------------------------------------------

export const QUEUE_NORMAL_DRAFT = 400;
export const QUEUE_NORMAL_BLIND = 430;
export const QUEUE_SWIFTPLAY = 480;
export const QUEUE_QUICKPLAY = 490;
export const QUEUE_ARAM = 450;

/** Every Summoner's Rift normal queue: Draft, Blind, Swiftplay and Quickplay. */
export const NORMAL_QUEUES: readonly number[] = [
  QUEUE_NORMAL_DRAFT,
  QUEUE_NORMAL_BLIND,
  QUEUE_SWIFTPLAY,
  QUEUE_QUICKPLAY,
];

export type HistoryQueueFilterId = "all" | "solo" | "flex" | "normal" | "aram";

export interface HistoryQueueFilter {
  id: HistoryQueueFilterId;
  /** Queue ids sent to the API (null = all queues). */
  queues: readonly number[] | null;
  label: string;
  short: string;
  description: string;
}

/** Match-history filter chips. "Normal" covers every normal Summoner's Rift queue. */
export const HISTORY_QUEUE_FILTERS: readonly [HistoryQueueFilter, ...HistoryQueueFilter[]] = [
  { id: "all", queues: null, label: "All", short: "All", description: "All queues" },
  { id: "solo", queues: [QUEUE_SOLO], label: "Ranked Solo", short: "Solo", description: "Ranked Solo/Duo" },
  { id: "flex", queues: [QUEUE_FLEX], label: "Ranked Flex", short: "Flex", description: "Ranked Flex" },
  { id: "normal", queues: NORMAL_QUEUES, label: "Normal", short: "Normal", description: "Normal" },
  { id: "aram", queues: [QUEUE_ARAM], label: "ARAM", short: "ARAM", description: "ARAM" },
];

export function historyQueueFilter(id: HistoryQueueFilterId): HistoryQueueFilter {
  return HISTORY_QUEUE_FILTERS.find((f) => f.id === id) ?? HISTORY_QUEUE_FILTERS[0];
}

/**
 * Queue name that fits a dense row ("Ranked Solo"). Delegates to `@/lib/queues`, which knows
 * the row names, the server label and the game mode, so a queue id neither side knows yet
 * still reads "Summoner's Rift" / "ARAM" instead of "Queue 710".
 */
export function rowQueueLabel(queueId: number, gameMode: string | null | undefined, serverLabel: string): string {
  return queueRowLabel(queueId, gameMode, serverLabel);
}

// --- KDA ----------------------------------------------------------------------------------

/** Colour class for a KDA ratio: >= 5 (or perfect) gold, >= 3 cyan, otherwise secondary. */
export function kdaToneClass(kda: number, deaths: number): string {
  if ((deaths === 0 && kda > 0) || kda >= 5) return "text-gold";
  if (kda >= 3) return "text-cyan";
  return "text-text-secondary";
}

const MULTIKILL_LABELS: Readonly<Record<number, string>> = {
  2: "Double Kill",
  3: "Triple Kill",
  4: "Quadra Kill",
  5: "Penta Kill",
};

export function multikillLabel(largest: number): string | null {
  return MULTIKILL_LABELS[largest] ?? null;
}

// --- in-game AI rank (op.gg-style MVP / ACE) ------------------------------------------------

export type InGameRankKind = "mvp" | "ace" | "rank";

export interface InGameRank {
  kind: InGameRankKind;
  /** "MVP", "ACE" or "#3". */
  label: string;
  /** Match-wide AI rank (1 = best of all 10). */
  rank: number;
  /** Tooltip / aria description. */
  description: string;
}

interface RankableTeam {
  team_id: TeamId;
  win: boolean;
  participants: readonly ParticipantSummary[];
}

/**
 * MVP = the best AI score on the winning team, ACE = the best on the losing team (as on
 * op.gg); everyone else shows their match-wide rank ("#3"). Null for remakes and unscored
 * players.
 */
export function inGameRank(
  participant: ParticipantSummary,
  teams: readonly RankableTeam[],
  remake: boolean,
): InGameRank | null {
  const rank = participant.ai_rank;
  if (remake || rank === null || participant.ai_score === null) return null;
  const team = teams.find((t) => t.team_id === participant.team_id);
  const teamRanks = (team?.participants ?? [])
    .map((p) => p.ai_rank)
    .filter((r): r is number => r !== null);
  const bestOnTeam = teamRanks.length > 0 ? Math.min(...teamRanks) : null;
  if (team && bestOnTeam === rank) {
    return team.win
      ? { kind: "mvp", label: "MVP", rank, description: `Best AI Score on the winning team (#${rank} of 10)` }
      : { kind: "ace", label: "ACE", rank, description: `Best AI Score on the losing team (#${rank} of 10)` };
  }
  return { kind: "rank", label: `#${rank}`, rank, description: `#${rank} of 10 by AI Score in this match` };
}

// --- participants -------------------------------------------------------------------------

const POSITION_INDEX = new Map<Position, number>(POSITION_ORDER.map((p, i) => [p, i]));

/** Lane order (top → support) when every position is known, otherwise participant id order. */
export function sortByPosition<T extends Pick<ParticipantSummary, "team_position" | "participant_id">>(
  participants: readonly T[],
): T[] {
  const known = participants.every((p) => POSITION_INDEX.has(p.team_position));
  return [...participants].sort((a, b) => {
    if (known) {
      const diff = (POSITION_INDEX.get(a.team_position) ?? 9) - (POSITION_INDEX.get(b.team_position) ?? 9);
      if (diff !== 0) return diff;
    }
    return a.participant_id - b.participant_id;
  });
}

export interface RiotIdPair {
  gameName: string;
  tagLine: string;
}

/** The participant's Riot ID, or null when the snapshot has no name (e.g. very old games). */
export function riotIdOf(participant: Pick<ParticipantSummary, "game_name" | "tag_line">): RiotIdPair | null {
  const gameName = participant.game_name?.trim();
  const tagLine = participant.tag_line?.trim();
  return gameName && tagLine ? { gameName, tagLine } : null;
}

/** Display name: game name, or the champion when the Riot ID is unknown. */
export function displayName(participant: Pick<ParticipantSummary, "game_name" | "champion_name">): string {
  return participant.game_name?.trim() || championDisplayName(participant.champion_name);
}

export const TEAM_SIDE_LABEL: Readonly<Record<TeamId, string>> = {
  100: "Blue side",
  200: "Red side",
};

// --- day grouping -------------------------------------------------------------------------

const weekdayFormatter = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });
const weekdayYearFormatter = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  year: "numeric",
});

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Local calendar-day key, e.g. "2026-9-14". */
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

/** "Today", "Yesterday", "Mon, Sep 14" (the year is added outside the current year). */
export function dayLabel(date: Date, now: Date = new Date()): string {
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.getFullYear() === now.getFullYear() ? weekdayFormatter.format(date) : weekdayYearFormatter.format(date);
}

export interface DayGroup {
  key: string;
  label: string;
  matches: MatchSummary[];
  wins: number;
  losses: number;
}

/** Group newest-first matches into consecutive local days. */
export function groupByDay(matches: readonly MatchSummary[], now: Date = new Date()): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const match of matches) {
    const date = new Date(match.game_start);
    const key = dayKey(date);
    let group = groups[groups.length - 1];
    if (!group || group.key !== key) {
      group = { key, label: dayLabel(date, now), matches: [], wins: 0, losses: 0 };
      groups.push(group);
    }
    group.matches.push(match);
    if (!match.remake) {
      if (match.me.win) group.wins += 1;
      else group.losses += 1;
    }
  }
  return groups;
}

// --- history summary ----------------------------------------------------------------------

export interface ChampionRecord {
  champion: string;
  games: number;
  wins: number;
  kills: number;
  deaths: number;
  assists: number;
}

export interface HistorySummary {
  /** Loaded games, remakes included. */
  loaded: number;
  /** Games that count (remakes excluded). */
  games: number;
  wins: number;
  losses: number;
  remakes: number;
  winrate: number | null;
  avgKills: number;
  avgDeaths: number;
  avgAssists: number;
  /** (k + a) / d over the totals; k + a when there were no deaths. */
  kda: number;
  totalDeaths: number;
  avgKillParticipation: number | null;
  avgAiScore: number | null;
  scoredGames: number;
  topChampions: ChampionRecord[];
}

export function summarizeHistory(matches: readonly MatchSummary[], topN = 3): HistorySummary {
  let wins = 0;
  let losses = 0;
  let remakes = 0;
  let kills = 0;
  let deaths = 0;
  let assists = 0;
  let kp = 0;
  let aiTotal = 0;
  let scored = 0;
  const champions = new Map<string, ChampionRecord>();

  for (const match of matches) {
    if (match.remake) {
      remakes += 1;
      continue;
    }
    const me = match.me;
    if (me.win) wins += 1;
    else losses += 1;
    kills += me.kills;
    deaths += me.deaths;
    assists += me.assists;
    kp += me.kill_participation;
    if (me.ai_score !== null) {
      aiTotal += me.ai_score;
      scored += 1;
    }
    const record = champions.get(me.champion_name) ?? {
      champion: me.champion_name,
      games: 0,
      wins: 0,
      kills: 0,
      deaths: 0,
      assists: 0,
    };
    record.games += 1;
    record.wins += me.win ? 1 : 0;
    record.kills += me.kills;
    record.deaths += me.deaths;
    record.assists += me.assists;
    champions.set(me.champion_name, record);
  }

  const games = wins + losses;
  const topChampions = [...champions.values()]
    .sort((a, b) => b.games - a.games || b.wins - a.wins || a.champion.localeCompare(b.champion))
    .slice(0, topN);

  return {
    loaded: matches.length,
    games,
    wins,
    losses,
    remakes,
    winrate: games > 0 ? wins / games : null,
    avgKills: games > 0 ? kills / games : 0,
    avgDeaths: games > 0 ? deaths / games : 0,
    avgAssists: games > 0 ? assists / games : 0,
    kda: deaths > 0 ? (kills + assists) / deaths : kills + assists,
    totalDeaths: deaths,
    avgKillParticipation: games > 0 ? kp / games : null,
    avgAiScore: scored > 0 ? aiTotal / scored : null,
    scoredGames: scored,
    topChampions,
  };
}

/** KDA ratio of a champion record (k + a when deathless). */
export function recordKda(record: Pick<ChampionRecord, "kills" | "deaths" | "assists">): number {
  return record.deaths > 0 ? (record.kills + record.assists) / record.deaths : record.kills + record.assists;
}

// --- match detail -------------------------------------------------------------------------

export interface MatchMaxima {
  damage: number;
  taken: number;
}

export function matchMaxima(match: Pick<MatchDetail, "teams">): MatchMaxima {
  let damage = 0;
  let taken = 0;
  for (const team of match.teams) {
    for (const p of team.participants) {
      damage = Math.max(damage, p.damage_to_champions);
      taken = Math.max(taken, p.damage_taken);
    }
  }
  return { damage, taken };
}

export function allParticipants(match: Pick<MatchDetail, "teams">): ParticipantSummary[] {
  return match.teams.flatMap((team) => team.participants);
}

/** Ratio in [0, 1] of `value / max` (0 when max is 0). */
export function ratioOf(value: number, max: number): number {
  return max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
}
