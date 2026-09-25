import { useMemo } from "react";

import { useLiveGames } from "@/api/queries";

/** puuids of roster players in a live game right now (empty while loading or when none). */
export function useLivePuuids(): ReadonlySet<string> {
  const { data } = useLiveGames();
  return useMemo(
    () =>
      new Set(
        (data?.games ?? []).flatMap((game) =>
          game.participants.filter((p) => p.is_tracked && p.puuid).map((p) => p.puuid as string),
        ),
      ),
    [data],
  );
}
