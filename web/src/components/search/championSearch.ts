/** Champion matches for the search palette, from the Data Dragon champion list. */
import { normalizeChampionQuery } from "@/components/champions/ChampionListModel";
import type { ChampionCatalog, ChampionInfo } from "@/components/match/useChampionCatalog";

export interface ChampionMatch extends ChampionInfo {
  /** The display name starts with the query ("ahr" -> Ahri). */
  prefix: boolean;
}

/** Shortest query that lists champions (one letter would match half the roster). */
export const CHAMPION_QUERY_MIN = 2;

/**
 * Champions whose name (or Data Dragon key: "monkeyking") contains the query, ignoring case,
 * spaces and punctuation ("kaisa" finds Kai'Sa). Name prefixes first, then word starts
 * ("sol" -> Aurelion Sol), then anything containing it; alphabetical within each.
 */
export function searchChampions(catalog: ChampionCatalog | undefined, query: string, limit: number): ChampionMatch[] {
  const q = normalizeChampionQuery(query);
  if (!catalog || q.length < CHAMPION_QUERY_MIN || query.includes("#")) return [];
  const scored: { info: ChampionInfo; score: number }[] = [];
  for (const info of catalog.values()) {
    const name = normalizeChampionQuery(info.name);
    let score = -1;
    if (name.startsWith(q)) score = 0;
    else if (info.name.split(/[\s'.&]+/).some((word) => normalizeChampionQuery(word).startsWith(q))) score = 1;
    else if (name.includes(q) || normalizeChampionQuery(info.key).includes(q)) score = 2;
    if (score >= 0) scored.push({ info, score });
  }
  scored.sort((a, b) => a.score - b.score || a.info.name.localeCompare(b.info.name));
  return scored.slice(0, limit).map(({ info, score }) => ({ ...info, prefix: score === 0 }));
}
