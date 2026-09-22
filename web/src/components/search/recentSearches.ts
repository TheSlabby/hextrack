/**
 * Recently viewed summoners, kept per browser in localStorage.
 *
 * Storage can be unavailable (private windows, blocked site data) or hold stale/corrupt JSON,
 * so every access is wrapped and the list silently falls back to in-memory state. Components
 * read it with `useRecentSearches()`, which also follows changes made in other tabs.
 */
import { useSyncExternalStore } from "react";

import type { Division, SummonerProfile, SummonerSearchResult, Tier } from "@/api/types";
import { TIER_ORDER } from "@/lib/tiers";

const STORAGE_KEY = "hextrack:recent-summoners:v1";
/** Most entries kept (newest first). */
export const RECENT_LIMIT = 8;

export interface RecentSummoner {
  gameName: string;
  tagLine: string;
  profileIconId: number | null;
  summonerLevel: number | null;
  soloTier: Tier | null;
  soloRank: Division | null;
  /** Epoch ms of the last visit. */
  visitedAt: number;
}

/** Fields a caller may know when recording a visit; the rest are kept from earlier visits. */
export type RecentSummonerInput = Pick<RecentSummoner, "gameName" | "tagLine"> &
  Partial<Omit<RecentSummoner, "gameName" | "tagLine" | "visitedAt">>;

const DIVISIONS: readonly Division[] = ["I", "II", "III", "IV"];
const EMPTY: readonly RecentSummoner[] = [];

let memory: readonly RecentSummoner[] | null = null;
const listeners = new Set<() => void>();

/** Case-insensitive identity of a Riot ID (Riot IDs are case-insensitive). */
export function recentKey(gameName: string, tagLine: string): string {
  return `${gameName.trim().toLowerCase()}#${tagLine.trim().toLowerCase()}`;
}

function asTier(value: unknown): Tier | null {
  return typeof value === "string" && (TIER_ORDER as readonly string[]).includes(value) ? (value as Tier) : null;
}

function asDivision(value: unknown): Division | null {
  return typeof value === "string" && (DIVISIONS as readonly string[]).includes(value) ? (value as Division) : null;
}

function asInt(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function parseEntry(value: unknown): RecentSummoner | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const { gameName, tagLine, visitedAt } = record;
  if (typeof gameName !== "string" || typeof tagLine !== "string") return null;
  if (!gameName.trim() || !tagLine.trim()) return null;
  return {
    gameName: gameName.trim(),
    tagLine: tagLine.trim(),
    profileIconId: asInt(record.profileIconId),
    summonerLevel: asInt(record.summonerLevel),
    soloTier: asTier(record.soloTier),
    soloRank: asDivision(record.soloRank),
    visitedAt: typeof visitedAt === "number" && Number.isFinite(visitedAt) ? visitedAt : 0,
  };
}

function readStorage(): readonly RecentSummoner[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return EMPTY;
    const seen = new Set<string>();
    const entries: RecentSummoner[] = [];
    for (const item of parsed) {
      const entry = parseEntry(item);
      if (!entry) continue;
      const key = recentKey(entry.gameName, entry.tagLine);
      if (seen.has(key)) continue;
      seen.add(key);
      entries.push(entry);
    }
    return entries.slice(0, RECENT_LIMIT);
  } catch {
    return EMPTY;
  }
}

function writeStorage(entries: readonly RecentSummoner[]): void {
  try {
    if (entries.length === 0) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Storage full or blocked: keep the in-memory copy for this session.
  }
}

function getSnapshot(): readonly RecentSummoner[] {
  if (memory === null) memory = typeof window === "undefined" ? EMPTY : readStorage();
  return memory;
}

function getServerSnapshot(): readonly RecentSummoner[] {
  return EMPTY;
}

function commit(entries: readonly RecentSummoner[]): void {
  memory = entries;
  writeStorage(entries);
  listeners.forEach((listener) => listener());
}

function onStorage(event: StorageEvent): void {
  if (event.key !== null && event.key !== STORAGE_KEY) return;
  memory = readStorage();
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

/** Move a summoner to the front of the list, merging in any newly known details. */
export function recordRecentSearch(input: RecentSummonerInput): void {
  const gameName = input.gameName.trim();
  const tagLine = input.tagLine.trim().replace(/^#/, "");
  if (!gameName || !tagLine) return;
  const key = recentKey(gameName, tagLine);
  const current = getSnapshot();
  const previous = current.find((entry) => recentKey(entry.gameName, entry.tagLine) === key);
  const next: RecentSummoner = {
    gameName,
    tagLine,
    profileIconId: input.profileIconId !== undefined ? input.profileIconId : (previous?.profileIconId ?? null),
    summonerLevel: input.summonerLevel !== undefined ? input.summonerLevel : (previous?.summonerLevel ?? null),
    soloTier: input.soloTier !== undefined ? input.soloTier : (previous?.soloTier ?? null),
    soloRank: input.soloRank !== undefined ? input.soloRank : (previous?.soloRank ?? null),
    visitedAt: Date.now(),
  };
  const rest = current.filter((entry) => recentKey(entry.gameName, entry.tagLine) !== key);
  commit([next, ...rest].slice(0, RECENT_LIMIT));
}

export function clearRecentSearches(): void {
  if (getSnapshot().length > 0) commit(EMPTY);
}

/** Recent-visit input from a search suggestion. */
export function recentFromSearchResult(result: SummonerSearchResult): RecentSummonerInput {
  return {
    gameName: result.game_name,
    tagLine: result.tag_line,
    profileIconId: result.profile_icon_id,
    summonerLevel: result.summoner_level,
    soloTier: result.solo_tier,
    soloRank: result.solo_rank,
  };
}

/** Recent-visit input from a loaded profile (canonical casing, icon and solo rank). */
export function recentFromProfile(profile: SummonerProfile): RecentSummonerInput {
  return {
    gameName: profile.game_name,
    tagLine: profile.tag_line,
    profileIconId: profile.profile_icon_id,
    summonerLevel: profile.summoner_level,
    soloTier: profile.solo?.tier ?? null,
    soloRank: profile.solo?.rank ?? null,
  };
}

/** Recently viewed summoners, newest first. Re-renders on changes in this and other tabs. */
export function useRecentSearches(): readonly RecentSummoner[] {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
