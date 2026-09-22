import type { ReactNode } from "react";

import { DdragonPatchContext } from "@/lib/ddragon";

/**
 * Sets the game patch for everything inside, so items and summoner spells load the assets of
 * that patch instead of the newest one (removed items 403 on the newest version). Wrap a match
 * row, a team table or a match page: `<DdragonPatch patch={match.patch}>`.
 */
export function DdragonPatch({ patch, children }: { patch: string | null | undefined; children: ReactNode }) {
  return <DdragonPatchContext.Provider value={patch ?? null}>{children}</DdragonPatchContext.Provider>;
}
