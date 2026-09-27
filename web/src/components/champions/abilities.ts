/**
 * A champion's four abilities (name + icon) from Data Dragon's per-champion json, for the skill
 * order. ~20-60 kB per champion, static, cached for the session at the newest version.
 */
import { useQuery } from "@tanstack/react-query";

import { championKey, useDdragon } from "@/lib/ddragon";

export interface ChampionAbility {
  key: "Q" | "W" | "E" | "R";
  name: string;
  /** Absolute icon URL. */
  icon: string;
}

const KEYS = ["Q", "W", "E", "R"] as const;
const DAY_MS = 24 * 60 * 60 * 1000;

export function parseChampionAbilities(payload: unknown, key: string, imageBase: string): ChampionAbility[] {
  const data = payload && typeof payload === "object" ? (payload as { data?: unknown }).data : undefined;
  const entry = data && typeof data === "object" ? (data as Record<string, unknown>)[key] : undefined;
  const spells = entry && typeof entry === "object" ? (entry as { spells?: unknown }).spells : undefined;
  if (!Array.isArray(spells) || spells.length < 4) throw new Error("Unexpected champion json shape");
  return KEYS.map((slot, i) => {
    const spell = spells[i] as { name?: unknown; image?: { full?: unknown } } | undefined;
    const full = spell?.image?.full;
    return {
      key: slot,
      name: typeof spell?.name === "string" ? spell.name : slot,
      icon: typeof full === "string" ? `${imageBase}/${full}` : "",
    };
  });
}

/** Q / W / E / R of a champion (Data Dragon key, e.g. "MonkeyKing"); undefined while loading or on failure. */
export function useChampionAbilities(champion: string | null | undefined): readonly ChampionAbility[] | undefined {
  const { cdn, latest } = useDdragon();
  const key = champion ? championKey(champion) : "";
  const version = latest.version;
  const query = useQuery({
    queryKey: ["ddragon", "champion", cdn, version, key] as const,
    queryFn: async ({ signal }): Promise<ChampionAbility[]> => {
      const response = await fetch(`${cdn}/${version}/data/en_US/champion/${encodeURIComponent(key)}.json`, { signal });
      if (!response.ok) throw new Error(`Data Dragon champion data failed (${response.status})`);
      return parseChampionAbilities(await response.json(), key, `${cdn}/${version}/img/spell`);
    },
    enabled: key !== "",
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: DAY_MS,
    retry: 1,
  });
  return query.data;
}
