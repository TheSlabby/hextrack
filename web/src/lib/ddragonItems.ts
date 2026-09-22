/**
 * Item id -> name, from Data Dragon's static `item.json`.
 *
 * Match data stores item ids, so a build tells the reader nothing without this map. The newest
 * catalogue covers almost every id; a game's own patch is fetched as well, but only when one of
 * the items on screen has since been removed from the game (~700 kB per catalogue, so it is
 * worth avoiding). Both are static CDN data, cached for the session and keyed by version.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useDdragon } from "./ddragon";

export interface ItemInfo {
  id: number;
  name: string;
  /** Short summary, e.g. "Grants Ability Power"; empty for most finished items. */
  plaintext: string;
  /** Total gold cost, when Data Dragon knows one. */
  gold: number | null;
}

export type ItemCatalog = ReadonlyMap<number, ItemInfo>;

const DAY_MS = 24 * 60 * 60 * 1000;

export function parseItemCatalog(payload: unknown): ItemCatalog {
  const data = payload && typeof payload === "object" ? (payload as { data?: unknown }).data : undefined;
  if (!data || typeof data !== "object") throw new Error("Unexpected item.json shape");
  const catalog = new Map<number, ItemInfo>();
  for (const [key, entry] of Object.entries(data as Record<string, unknown>)) {
    const id = Number.parseInt(key, 10);
    if (!Number.isFinite(id) || !entry || typeof entry !== "object") continue;
    const { name, plaintext, gold } = entry as { name?: unknown; plaintext?: unknown; gold?: unknown };
    if (typeof name !== "string" || !name) continue;
    const total = gold && typeof gold === "object" ? (gold as { total?: unknown }).total : undefined;
    catalog.set(id, {
      id,
      name,
      plaintext: typeof plaintext === "string" ? plaintext : "",
      gold: typeof total === "number" && total > 0 ? total : null,
    });
  }
  return catalog;
}

function useCatalogQuery(cdn: string, url: string, version: string, enabled: boolean) {
  return useQuery({
    queryKey: ["ddragon", "items", cdn, version] as const,
    queryFn: async ({ signal }): Promise<ItemCatalog> => {
      const response = await fetch(url, { signal });
      if (!response.ok) throw new Error(`Data Dragon item list failed (${response.status})`);
      return parseItemCatalog(await response.json());
    },
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: DAY_MS,
  });
}

export interface ItemLookup {
  /** The item, or undefined while the catalogues load or when no catalogue knows the id. */
  info: (id: number) => ItemInfo | undefined;
  /** Every catalogue this row needs has answered: an unknown id really is a removed item. */
  ready: boolean;
}

/** Look up the items in `ids` (0 for empty slots) for a game on `patch`. */
export function useItemCatalog(ids: readonly number[], patch?: string | null): ItemLookup {
  const dd = useDdragon(patch);
  const latest = useCatalogQuery(dd.cdn, dd.latest.itemData(), dd.latest.version, true);
  const removed = Boolean(latest.data) && ids.some((id) => id > 0 && !latest.data?.has(id));
  const wantPatch = removed && dd.version !== dd.latest.version;
  const atPatch = useCatalogQuery(dd.cdn, dd.itemData(), dd.version, wantPatch);
  const fromLatest = latest.data;
  const fromPatch = atPatch.data;
  const ready = latest.isFetched && (!wantPatch || atPatch.isFetched);
  return useMemo(
    () => ({ info: (id: number) => fromLatest?.get(id) ?? fromPatch?.get(id), ready }),
    [fromLatest, fromPatch, ready],
  );
}
