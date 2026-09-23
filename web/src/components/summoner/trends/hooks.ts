/** Hooks for the Trends tab: the remembered filters and the `?player=` value for match links. */
import { useCallback, useState } from "react";
import { useParams } from "@tanstack/react-router";

import { parseSlug, toSlug } from "@/lib/riotId";

import { DEFAULT_TRENDS_FILTERS, isLeaderboardQueue, isStatsSince, type TrendsFilters } from "./model";

const STORAGE_KEY = "hextrack.trends.filters";

function readStoredFilters(): TrendsFilters {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_TRENDS_FILTERS;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_TRENDS_FILTERS;
    const { since, queue } = parsed as Record<string, unknown>;
    return {
      since: isStatsSince(since) ? since : DEFAULT_TRENDS_FILTERS.since,
      queue: isLeaderboardQueue(queue) ? queue : DEFAULT_TRENDS_FILTERS.queue,
    };
  } catch {
    return DEFAULT_TRENDS_FILTERS;
  }
}

/**
 * Period and queue filters for the Trends tab. Radix unmounts inactive tabs, so the choice is
 * kept in sessionStorage (per browser tab) and survives switching tabs or profiles. Storage is
 * a convenience only: without it the filters simply start at "this season, all queues".
 */
export function useTrendsFilters(): [TrendsFilters, (next: TrendsFilters) => void] {
  const [filters, setFilters] = useState<TrendsFilters>(readStoredFilters);
  const update = useCallback((next: TrendsFilters) => {
    setFilters(next);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Private mode or blocked storage: the filter still applies for this view.
    }
  }, []);
  return [filters, update];
}

/**
 * `?player=` value for this profile's match links: the Riot ID slug of the summoner page
 * (short and readable), or the puuid when the page has no parsable Riot ID.
 */
export function usePlayerSearchValue(puuid: string): string {
  const params = useParams({ strict: false });
  const slug = typeof params.riotId === "string" ? parseSlug(params.riotId) : null;
  return slug ? toSlug(slug.gameName, slug.tagLine) : puuid;
}
