/**
 * Champion id → Data Dragon key/name, from the static `champion.json` of the current patch.
 *
 * Match detail lists bans as numeric champion ids, and Data Dragon portraits are addressed by
 * key, so the ban row needs this map. It is static CDN data (like the portraits themselves),
 * cached for the session and keyed by the Data Dragon version.
 */
import { useQuery } from "@tanstack/react-query";

import { useDdragon } from "@/lib/ddragon";

export interface ChampionInfo {
  /** Data Dragon key, e.g. "MonkeyKing". */
  key: string;
  /** Display name, e.g. "Wukong". */
  name: string;
}

export type ChampionCatalog = ReadonlyMap<number, ChampionInfo>;

const DAY_MS = 24 * 60 * 60 * 1000;

export function parseChampionCatalog(payload: unknown): ChampionCatalog {
  const data = payload && typeof payload === "object" ? (payload as { data?: unknown }).data : undefined;
  if (!data || typeof data !== "object") throw new Error("Unexpected champion.json shape");
  const catalog = new Map<number, ChampionInfo>();
  for (const entry of Object.values(data as Record<string, unknown>)) {
    if (!entry || typeof entry !== "object") continue;
    const { id, key, name } = entry as { id?: unknown; key?: unknown; name?: unknown };
    const numericId = typeof key === "string" ? Number.parseInt(key, 10) : Number.NaN;
    if (typeof id === "string" && typeof name === "string" && Number.isFinite(numericId)) {
      catalog.set(numericId, { key: id, name });
    }
  }
  return catalog;
}

export function useChampionCatalog(enabled = true) {
  const { version, cdn } = useDdragon();
  return useQuery({
    queryKey: ["ddragon", "champions", cdn, version] as const,
    queryFn: async ({ signal }): Promise<ChampionCatalog> => {
      const response = await fetch(`${cdn}/${version}/data/en_US/champion.json`, { signal });
      if (!response.ok) throw new Error(`Data Dragon champion list failed (${response.status})`);
      return parseChampionCatalog(await response.json());
    },
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: DAY_MS,
  });
}
