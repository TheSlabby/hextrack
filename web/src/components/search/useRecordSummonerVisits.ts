import { useEffect } from "react";
import { hashKey, useQueryClient } from "@tanstack/react-query";
import { useMatch } from "@tanstack/react-router";

import { queryKeys } from "@/api/queries";
import type { SummonerProfile } from "@/api/types";
import { parseSlug } from "@/lib/riotId";

import { recentFromProfile, recordRecentSearch } from "./recentSearches";

function isProfile(value: unknown): value is SummonerProfile {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<Record<keyof SummonerProfile, unknown>>;
  return (
    typeof record.puuid === "string" && typeof record.game_name === "string" && typeof record.tag_line === "string"
  );
}

/**
 * Records every summoner page the user opens in the recent-searches list, whichever way
 * they got there (search, leaderboard, match links). The entry is written once the
 * profile has loaded, so typos and unknown Riot IDs never pollute the list, and it uses the
 * canonical casing, icon and rank from the profile.
 */
export function useRecordSummonerVisits(): void {
  const riotId = useMatch({
    from: "/summoner/$region/$riotId",
    shouldThrow: false,
    select: (match) => match.params.riotId,
  });
  const client = useQueryClient();

  useEffect(() => {
    if (!riotId) return;
    const parts = parseSlug(riotId);
    if (!parts) return;
    const key = queryKeys.profile(parts.gameName, parts.tagLine);

    const cached: unknown = client.getQueryData(key);
    if (isProfile(cached)) {
      recordRecentSearch(recentFromProfile(cached));
      return;
    }

    const hash = hashKey(key);
    const unsubscribe = client.getQueryCache().subscribe((event) => {
      if (event.type !== "updated" || event.action.type !== "success") return;
      if (event.query.queryHash !== hash) return;
      const data: unknown = event.query.state.data;
      if (!isProfile(data)) return;
      recordRecentSearch(recentFromProfile(data));
      unsubscribe();
    });
    return unsubscribe;
  }, [riotId, client]);
}
