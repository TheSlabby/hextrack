/**
 * Rune id -> name + icon URL, from Data Dragon's static `runesReforged.json`.
 *
 * Live games (spectator-v5) list runes as numeric perk ids: the keystone and the primary /
 * secondary trees. The file is an array of trees, each with slots of runes; icon paths are
 * relative to `${cdn}/img/`. Static CDN data, cached for the session and keyed by version.
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

const DAY_MS = 24 * 60 * 60 * 1000;

interface RawRune {
  id?: unknown;
  name?: unknown;
  icon?: unknown;
}

function add(catalog: Map<number, RuneInfo>, raw: RawRune, kind: RuneInfo["kind"], imgBase: string): void {
  const { id, name, icon } = raw;
  if (typeof id !== "number" || typeof name !== "string" || typeof icon !== "string") return;
  catalog.set(id, { id, name, icon: `${imgBase}/${icon.replace(/^\/+/, "")}`, kind });
}

/** Parse `runesReforged.json` into an id lookup covering both trees and runes. */
export function parseRuneCatalog(payload: unknown, cdn: string): RuneCatalog {
  if (!Array.isArray(payload)) throw new Error("Unexpected runesReforged.json shape");
  const imgBase = `${cdn}/img`;
  const catalog = new Map<number, RuneInfo>();
  for (const tree of payload as unknown[]) {
    if (!tree || typeof tree !== "object") continue;
    add(catalog, tree as RawRune, "tree", imgBase);
    const slots = (tree as { slots?: unknown }).slots;
    if (!Array.isArray(slots)) continue;
    for (const slot of slots as unknown[]) {
      const runes = slot && typeof slot === "object" ? (slot as { runes?: unknown }).runes : undefined;
      if (!Array.isArray(runes)) continue;
      for (const rune of runes as unknown[]) {
        if (rune && typeof rune === "object") add(catalog, rune as RawRune, "rune", imgBase);
      }
    }
  }
  return catalog;
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
  const version = latest.version;
  const query = useQuery({
    queryKey: ["ddragon", "runes", cdn, version] as const,
    queryFn: async ({ signal }): Promise<RuneCatalog> => {
      const response = await fetch(`${cdn}/${version}/data/en_US/runesReforged.json`, { signal });
      if (!response.ok) throw new Error(`Data Dragon rune list failed (${response.status})`);
      return parseRuneCatalog(await response.json(), cdn);
    },
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: DAY_MS,
  });
  const catalog = query.data;
  const loading = enabled && query.isPending;
  return useMemo(
    () => ({ info: (id: number | null | undefined) => (id ? catalog?.get(id) : undefined), loading }),
    [catalog, loading],
  );
}
