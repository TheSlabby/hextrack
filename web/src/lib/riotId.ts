/**
 * Riot ID helpers. URLs use `/summoner/na/<GameName>-<TAG>`; tags never contain "-", so
 * splitting a slug on its LAST "-" is lossless even when the game name contains dashes.
 *
 * Tag rules mirror the backend (api/src/hextrack/riotid.py `_validate`): 2 to 5 characters
 * once trimmed, no "#". They are usually alphanumeric, but real tags contain spaces
 * ("NA 1", "Do It", "F L Y"), so the only characters ruled out here are "#" and the "-"
 * that would break a slug.
 */
import type { RiotIdParts } from "@/api/types";

export const DEFAULT_REGION = "na";

const TAG_RE = /^[^#-]{2,5}$/u;

export function normalizeTagLine(tagLine: string): string {
  return tagLine.normalize("NFC").trim().replace(/^#+/, "").trim();
}

/** Is this a usable tag line (2-5 characters, no "#" or "-")? */
function isValidTagLine(tagLine: string): boolean {
  return TAG_RE.test(normalizeTagLine(tagLine));
}

/** "Game Name" + "NA1" -> "Game Name-NA1" (not URL-encoded). */
export function toSlug(gameName: string, tagLine: string): string {
  return `${gameName.trim()}-${normalizeTagLine(tagLine)}`;
}

/** "Some-Name-NA1" -> { gameName: "Some-Name", tagLine: "NA1" }; null when there is no tag. */
export function parseSlug(slug: string): RiotIdParts | null {
  let decoded = slug;
  try {
    decoded = decodeURIComponent(slug);
  } catch {
    // Already decoded (router params) or malformed escapes: use as-is.
  }
  const at = decoded.lastIndexOf("-");
  if (at <= 0 || at === decoded.length - 1) return null;
  const gameName = decoded.slice(0, at).trim();
  const tagLine = decoded.slice(at + 1).trim();
  if (!gameName || !tagLine) return null;
  return { gameName, tagLine };
}

/** "Game Name#NA1". */
export function formatRiotId(gameName: string, tagLine: string): string {
  return `${gameName}#${normalizeTagLine(tagLine)}`;
}

/**
 * Parse user input: "Name#TAG", "Name #TAG" or a slug "Name-TAG". Returns null when the
 * input has no recognisable tag line.
 */
export function parseRiotIdInput(input: string): RiotIdParts | null {
  const text = input.trim();
  if (!text) return null;
  const hash = text.lastIndexOf("#");
  if (hash >= 0) {
    const gameName = text.slice(0, hash).trim();
    const tagLine = normalizeTagLine(text.slice(hash + 1));
    return gameName && isValidTagLine(tagLine) ? { gameName, tagLine } : null;
  }
  const parsed = parseSlug(text);
  return parsed && isValidTagLine(parsed.tagLine) ? parsed : null;
}

/** Path of a summoner page: "/summoner/na/<encoded slug>". */
export function summonerPath(gameName: string, tagLine: string, region: string = DEFAULT_REGION): string {
  return `/summoner/${encodeURIComponent(region)}/${encodeURIComponent(toSlug(gameName, tagLine))}`;
}

/** Router params for `<Link to="/summoner/$region/$riotId" params={...}>` (the router encodes them). */
export function summonerParams(
  gameName: string,
  tagLine: string,
  region: string = DEFAULT_REGION,
): { region: string; riotId: string } {
  return { region, riotId: toSlug(gameName, tagLine) };
}
