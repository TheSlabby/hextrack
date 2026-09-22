/**
 * The `?player=` search param of /match/$matchId: a Riot ID slug ("Game Name-TAG", as built
 * by `toSlug`). A raw puuid is accepted too, so links built either way resolve.
 */
import type { MatchDetail, ParticipantSummary } from "@/api/types";
import { parseRiotIdInput, toSlug } from "@/lib/riotId";

import { allParticipants, riotIdOf, type RiotIdPair } from "./matchUtils";

/** Riot ID slugs are at most ~22 characters; puuids are 78. */
const MAX_SLUG_LENGTH = 40;

export interface FocusPlayer {
  /** Resolved once the match is loaded and the player is found in it. */
  puuid: string | null;
  /** Riot ID for the breadcrumb (from the slug, or the participant snapshot). */
  riotId: RiotIdPair | null;
  participant: ParticipantSummary | null;
}

const lower = (value: string) => value.trim().toLowerCase();

/** Parse `?player=` against the (optional) loaded match. Null when there is no usable value. */
export function resolveFocusPlayer(player: string | undefined, match: MatchDetail | undefined): FocusPlayer | null {
  const value = player?.trim();
  if (!value) return null;
  const participants = match ? allParticipants(match) : [];

  const byPuuid = participants.find((p) => p.puuid === value);
  if (byPuuid) return { puuid: byPuuid.puuid, riotId: riotIdOf(byPuuid), participant: byPuuid };

  const slug = value.length <= MAX_SLUG_LENGTH ? parseRiotIdInput(value) : null;
  if (!slug) return null;
  const participant =
    participants.find(
      (p) => p.game_name !== null && p.tag_line !== null && lower(p.game_name) === lower(slug.gameName) && lower(p.tag_line) === lower(slug.tagLine),
    ) ?? null;
  return {
    puuid: participant?.puuid ?? null,
    riotId: (participant ? riotIdOf(participant) : null) ?? slug,
    participant,
  };
}

/** `?player=` value for a participant: their Riot ID slug, or the puuid when the name is unknown. */
export function playerSearchValue(participant: Pick<ParticipantSummary, "puuid" | "game_name" | "tag_line">): string {
  const riotId = riotIdOf(participant);
  return riotId ? toSlug(riotId.gameName, riotId.tagLine) : participant.puuid;
}
