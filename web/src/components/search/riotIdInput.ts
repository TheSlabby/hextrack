/**
 * Search-box helpers: Riot ID validation with friendly messages and local matching of
 * known players (recent visits, roster) against what the user typed.
 */
import type { RiotIdParts } from "@/api/types";
import { parseRiotIdInput } from "@/lib/riotId";

/** Riot caps game names at 16 characters. */
const MAX_GAME_NAME = 16;

export type RiotIdValidation = { ok: true; parts: RiotIdParts } | { ok: false; message: string };

/** Validate free text as a Riot ID ("Name#TAG" or a "Name-TAG" slug). */
export function validateRiotIdInput(input: string): RiotIdValidation {
  const text = input.trim();
  if (!text) return { ok: false, message: "Enter a Riot ID, like Hexwalker#NA1." };
  const parts = parseRiotIdInput(text);
  if (parts) {
    if ([...parts.gameName].length > MAX_GAME_NAME) {
      return { ok: false, message: `Riot names are at most ${MAX_GAME_NAME} characters.` };
    }
    return { ok: true, parts };
  }
  const hash = text.lastIndexOf("#");
  if (hash < 0) return { ok: false, message: "Add the tag after a #, like Hexwalker#NA1." };
  if (!text.slice(0, hash).trim()) return { ok: false, message: "Enter the name before the #." };
  if (!text.slice(hash + 1).trim()) return { ok: false, message: "Add the tag after the #, like NA1." };
  return { ok: false, message: "Tags are 2 to 5 characters, like NA1." };
}

/** Riot IDs compare case-insensitively. */
export function sameRiotId(a: RiotIdParts, b: RiotIdParts): boolean {
  return (
    a.gameName.trim().toLowerCase() === b.gameName.trim().toLowerCase() &&
    a.tagLine.trim().toLowerCase() === b.tagLine.trim().toLowerCase()
  );
}

/**
 * Does a known player match the typed text? "hex" matches names containing "hex";
 * "hex#na" matches names containing "hex" whose tag starts with "na".
 */
export function matchesRiotIdQuery(query: string, gameName: string, tagLine: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const name = gameName.toLowerCase();
  const tag = tagLine.toLowerCase();
  const hash = q.lastIndexOf("#");
  if (hash >= 0) {
    const nameQuery = q.slice(0, hash).trim();
    const tagQuery = q.slice(hash + 1).trim();
    return (!nameQuery || name.includes(nameQuery)) && tag.startsWith(tagQuery);
  }
  return name.includes(q) || `${name}#${tag}`.includes(q);
}
