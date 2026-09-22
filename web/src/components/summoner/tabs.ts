/** Summoner page tabs (mirrors `SummonerSearch["tab"]` in src/router.tsx). */
export const SUMMONER_TAB_VALUES = ["overview", "matches", "ai"] as const;
export type SummonerTabValue = (typeof SUMMONER_TAB_VALUES)[number];

export function isSummonerTabValue(value: string): value is SummonerTabValue {
  return (SUMMONER_TAB_VALUES as readonly string[]).includes(value);
}
