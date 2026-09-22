/**
 * Data Dragon asset URLs. The newest version comes from `/api/v1/meta` (cached ~1h) with a
 * static fallback so icons render before meta resolves or when the API is down.
 *
 * Items are removed from the game every few patches, and the newest version then answers 403
 * for them, so anything that belongs to one game (items, summoner spells) is addressed at that
 * game's patch: Data Dragon publishes "<patch>.1" for every patch, e.g. "16.16" -> "16.16.1".
 * Components take the patch from the nearest `<DdragonPatch patch={match.patch}>` (or a `patch`
 * prop). Champion portraits and profile icons are never removed, so they stay on the newest
 * version, where they share the browser cache across patches.
 */
import { createContext, useContext, useMemo } from "react";

import { useMeta } from "@/api/queries";

export const DDRAGON_CDN = "https://ddragon.leagueoflegends.com/cdn";
/** Mirrors api/src/hextrack/riot/ddragon.py FALLBACK_VERSION. */
export const FALLBACK_DDRAGON_VERSION = "16.18.1";

/** Summoner spell id -> Data Dragon key + display name. */
export const SUMMONER_SPELLS: Readonly<Record<number, { key: string; name: string }>> = {
  1: { key: "SummonerBoost", name: "Cleanse" },
  3: { key: "SummonerExhaust", name: "Exhaust" },
  4: { key: "SummonerFlash", name: "Flash" },
  6: { key: "SummonerHaste", name: "Ghost" },
  7: { key: "SummonerHeal", name: "Heal" },
  11: { key: "SummonerSmite", name: "Smite" },
  12: { key: "SummonerTeleport", name: "Teleport" },
  13: { key: "SummonerMana", name: "Clarity" },
  14: { key: "SummonerDot", name: "Ignite" },
  21: { key: "SummonerBarrier", name: "Barrier" },
  30: { key: "SummonerPoroRecall", name: "To the King!" },
  31: { key: "SummonerPoroThrow", name: "Poro Toss" },
  32: { key: "SummonerSnowball", name: "Mark" },
  39: { key: "SummonerSnowURFSnowball_Mark", name: "Mark" },
  54: { key: "Summoner_UltBookPlaceholder", name: "Placeholder" },
  55: { key: "Summoner_UltBookSmitePlaceholder", name: "Placeholder and Attack-Smite" },
  2201: { key: "SummonerCherryHold", name: "Flee" },
  2202: { key: "SummonerCherryFlash", name: "Flash" },
};

/** Match-v5 champion names that differ from their Data Dragon keys. */
const CHAMPION_KEY_FIXES: Readonly<Record<string, string>> = {
  FiddleSticks: "Fiddlesticks",
  Wukong: "MonkeyKing",
  "Nunu & Willump": "Nunu",
  "Renata Glasc": "Renata",
};

/** Normalise a champion name from match data to a Data Dragon key. */
export function championKey(name: string): string {
  return CHAMPION_KEY_FIXES[name] ?? name.replace(/[^A-Za-z0-9]/g, "");
}

export function spellName(id: number): string {
  return SUMMONER_SPELLS[id]?.name ?? "Unknown spell";
}

const PATCH_RE = /^(\d+)\.(\d+)/;

function patchNumbers(value: string | null | undefined): [number, number] | null {
  const match = value ? PATCH_RE.exec(value.trim()) : null;
  if (!match) return null;
  const [major, minor] = [Number(match[1]), Number(match[2])];
  return Number.isFinite(major) && Number.isFinite(minor) ? [major, minor] : null;
}

/**
 * Data Dragon version for a match patch ("16.16" -> "16.16.1"), or `latest` when the patch is
 * unknown, unparseable, or at least as new as the newest published version.
 */
function ddragonVersionForPatch(patch: string | null | undefined, latest: string): string {
  const wanted = patchNumbers(patch);
  if (!wanted) return latest;
  const newest = patchNumbers(latest);
  if (newest && (wanted[0] > newest[0] || (wanted[0] === newest[0] && wanted[1] >= newest[1]))) return latest;
  return `${wanted[0]}.${wanted[1]}.1`;
}

/** URL builders for one Data Dragon version. */
export interface DdragonUrls {
  version: string;
  championIcon: (key: string) => string;
  championSplash: (key: string, skin?: number) => string;
  championLoading: (key: string, skin?: number) => string;
  /** Empty string for 0 / empty slots. */
  itemIcon: (id: number) => string;
  itemData: () => string;
  profileIcon: (id: number) => string;
  /** Empty string for unknown spell ids. */
  spellIcon: (id: number) => string;
}

export interface DdragonAssets extends DdragonUrls {
  cdn: string;
  /** The same builders at the newest known version (fallback for removed assets). */
  latest: DdragonUrls;
}

function buildUrls(version: string, cdn: string): DdragonUrls {
  return {
    version,
    championIcon: (key) => `${cdn}/${version}/img/champion/${championKey(key)}.png`,
    championSplash: (key, skin = 0) => `${cdn}/img/champion/splash/${championKey(key)}_${skin}.jpg`,
    championLoading: (key, skin = 0) => `${cdn}/img/champion/loading/${championKey(key)}_${skin}.jpg`,
    itemIcon: (id) => (id > 0 ? `${cdn}/${version}/img/item/${id}.png` : ""),
    itemData: () => `${cdn}/${version}/data/en_US/item.json`,
    profileIcon: (id) => `${cdn}/${version}/img/profileicon/${id}.png`,
    spellIcon: (id) => {
      const spell = SUMMONER_SPELLS[id];
      return spell ? `${cdn}/${version}/img/spell/${spell.key}.png` : "";
    },
  };
}

export function buildDdragon(version: string, cdn: string = DDRAGON_CDN, latestVersion: string = version): DdragonAssets {
  return {
    ...buildUrls(version, cdn),
    cdn,
    latest: version === latestVersion ? buildUrls(version, cdn) : buildUrls(latestVersion, cdn),
  };
}

/** Patch of the game being rendered ("16.16"), set by `<DdragonPatch>`. */
export const DdragonPatchContext = createContext<string | null>(null);

/** The patch set by the nearest `<DdragonPatch>`, if any. */
function useDdragonPatch(): string | null {
  return useContext(DdragonPatchContext);
}

/**
 * Data Dragon URL builders. Assets that belong to one game resolve against `patch` (or the
 * nearest `<DdragonPatch>`); everything else uses the newest version.
 */
export function useDdragon(patch?: string | null): DdragonAssets {
  const { data } = useMeta();
  const contextPatch = useDdragonPatch();
  const latest = data?.ddragon_version ?? FALLBACK_DDRAGON_VERSION;
  const cdn = (data?.ddragon_cdn ?? DDRAGON_CDN).replace(/\/+$/, "");
  const wanted = patch ?? contextPatch;
  const version = ddragonVersionForPatch(wanted, latest);
  return useMemo(() => buildDdragon(version, cdn, latest), [version, cdn, latest]);
}
