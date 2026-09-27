/**
 * Runes from Data Dragon's static `runesReforged.json`: an id lookup (`useRunes`) and the full
 * trees with their rows (`useRuneTrees`, for drawing a whole rune page).
 *
 * Live games (spectator-v5) and champion pages list runes as numeric perk ids: the keystone and the
 * primary / secondary trees. The file is an array of trees, each with slots of runes (slot 0 = the
 * keystones); icon paths are relative to `${cdn}/img/`. Stat shards are not in this file (see
 * `lib/statShards.ts`). Static CDN data, cached for the session and keyed by version.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useDdragon } from "./ddragon";

export interface RuneInfo {
  id: number;
  name: string;
  /** Absolute icon URL. */
  icon: string;
  /** "tree" for a path (Precision, Domination...), "rune" for a keystone or minor rune. */
  kind: "tree" | "rune";
}

export type RuneCatalog = ReadonlyMap<number, RuneInfo>;

/** One rune tree (path) with its rows: `slots[0]` holds the keystones, `slots[1..3]` the minor rows. */
export interface RuneTree extends RuneInfo {
  kind: "tree";
  slots: readonly (readonly RuneInfo[])[];
}

interface RuneData {
  catalog: RuneCatalog;
  trees: readonly RuneTree[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

interface RawRune {
  id?: unknown;
  name?: unknown;
  icon?: unknown;
}

function toInfo(raw: RawRune, kind: RuneInfo["kind"], imgBase: string): RuneInfo | null {
  const { id, name, icon } = raw;
  if (typeof id !== "number" || typeof name !== "string" || typeof icon !== "string") return null;
  return { id, name, icon: `${imgBase}/${icon.replace(/^\/+/, "")}`, kind };
}

/** Parse `runesReforged.json` into its trees (rows kept in order). */
export function parseRuneTrees(payload: unknown, cdn: string): RuneTree[] {
  if (!Array.isArray(payload)) throw new Error("Unexpected runesReforged.json shape");
  const imgBase = `${cdn}/img`;
  const trees: RuneTree[] = [];
  for (const raw of payload as unknown[]) {
    if (!raw || typeof raw !== "object") continue;
    const info = toInfo(raw as RawRune, "tree", imgBase);
    if (!info) continue;
    const slots: RuneInfo[][] = [];
    const rawSlots = (raw as { slots?: unknown }).slots;
    if (Array.isArray(rawSlots)) {
      for (const slot of rawSlots as unknown[]) {
        const runes = slot && typeof slot === "object" ? (slot as { runes?: unknown }).runes : undefined;
        if (!Array.isArray(runes)) continue;
        slots.push(
          (runes as unknown[])
            .map((rune) => (rune && typeof rune === "object" ? toInfo(rune as RawRune, "rune", imgBase) : null))
            .filter((rune): rune is RuneInfo => rune !== null),
        );
      }
    }
    trees.push({ ...info, kind: "tree", slots });
  }
  return trees;
}

function catalogOf(trees: readonly RuneTree[]): RuneCatalog {
  const catalog = new Map<number, RuneInfo>();
  for (const tree of trees) {
    catalog.set(tree.id, { id: tree.id, name: tree.name, icon: tree.icon, kind: "tree" });
    for (const slot of tree.slots) for (const rune of slot) catalog.set(rune.id, rune);
  }
  return catalog;
}

/** Parse `runesReforged.json` into an id lookup covering both trees and runes. */
export function parseRuneCatalog(payload: unknown, cdn: string): RuneCatalog {
  return catalogOf(parseRuneTrees(payload, cdn));
}

function useRuneData(version: string, cdn: string, enabled: boolean) {
  return useQuery({
    queryKey: ["ddragon", "runes", cdn, version] as const,
    queryFn: async ({ signal }): Promise<RuneData> => {
      const response = await fetch(`${cdn}/${version}/data/en_US/runesReforged.json`, { signal });
      if (!response.ok) throw new Error(`Data Dragon rune list failed (${response.status})`);
      const trees = parseRuneTrees(await response.json(), cdn);
      return { trees, catalog: catalogOf(trees) };
    },
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: DAY_MS,
  });
}

export interface RuneLookup {
  /** The rune or tree, or undefined while loading / for unknown ids. */
  info: (id: number | null | undefined) => RuneInfo | undefined;
  /** The catalogue is still loading (unknown ids aren't final yet). */
  loading: boolean;
}

/** Rune and rune-tree lookup for the newest Data Dragon version. */
export function useRunes(enabled = true): RuneLookup {
  const { cdn, latest } = useDdragon();
  const query = useRuneData(latest.version, cdn, enabled);
  const catalog = query.data?.catalog;
  const loading = enabled && query.isPending;
  return useMemo(
    () => ({ info: (id: number | null | undefined) => (id ? catalog?.get(id) : undefined), loading }),
    [catalog, loading],
  );
}

export interface RuneTreesLookup extends RuneLookup {
  /** Every tree, or undefined while loading. */
  trees: readonly RuneTree[] | undefined;
  /** One tree by style id (8000 Precision, 8100 Domination...). */
  tree: (id: number | null | undefined) => RuneTree | undefined;
  /** The file failed to load. */
  error: boolean;
}

/**
 * Whole rune trees for `patch` ("16.18"; the newest version when omitted or newer than Data
 * Dragon). Trees change between patches (runes are swapped out), so a page of old games is drawn
 * with the trees of its own patch.
 */
export function useRuneTrees(patch?: string | null): RuneTreesLookup {
  const dd = useDdragon(patch);
  const query = useRuneData(dd.version, dd.cdn, true);
  const data = query.data;
  const loading = query.isPending;
  const error = query.isError;
  return useMemo(
    () => ({
      trees: data?.trees,
      tree: (id: number | null | undefined) => (id ? data?.trees.find((t) => t.id === id) : undefined),
      info: (id: number | null | undefined) => (id ? data?.catalog.get(id) : undefined),
      loading,
      error,
    }),
    [data, loading, error],
  );
}
