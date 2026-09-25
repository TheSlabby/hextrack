/**
 * Shared helpers for live games (no React here, so component files stay react-refresh clean).
 */
import type { LiveGame, LiveParticipant } from "@/api/types";

/** Seconds since the game started, or null while it's loading (no start time yet). */
export function liveElapsedSeconds(game: Pick<LiveGame, "started_at">, now: number): number | null {
  if (!game.started_at) return null;
  return Math.max(0, Math.floor((now - Date.parse(game.started_at)) / 1000));
}

/** "23:05" (or "1:02:40"); "Loading" before the game starts. */
export function formatLiveClock(seconds: number | null): string {
  if (seconds === null) return "Loading";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

/** Roster players in the game, per team (blue first). */
export function rosterByTeam(game: LiveGame): { teamId: LiveParticipant["team_id"]; players: LiveParticipant[] }[] {
  return ([100, 200] as const)
    .map((teamId) => ({ teamId, players: game.participants.filter((p) => p.team_id === teamId && p.is_tracked) }))
    .filter((team) => team.players.length > 0);
}

/** "Solo", "Duo", "3-stack" ... for a team's roster players. */
export function partyLabel(count: number): string {
  return count <= 1 ? "Solo" : count === 2 ? "Duo" : `${count}-stack`;
}

/** The live game a roster player is in, if any. */
export function liveGameFor(games: readonly LiveGame[] | undefined, puuid: string): LiveGame | undefined {
  return games?.find((g) => g.participants.some((p) => p.puuid === puuid));
}
