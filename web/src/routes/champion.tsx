/**
 * /champions/$champion: one champion's stats by role, builds, runes, spells, skill order,
 * lane matchups and the squad on it. Patch / queue / role live in the URL.
 */
import { getRouteApi } from "@tanstack/react-router";

import { championDisplayName } from "@/lib/champions";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";

const route = getRouteApi("/champions/$champion");

export function ChampionPage() {
  const { champion } = route.useParams();
  useDocumentTitle(pageTitle(championDisplayName(champion)));
  return <div className="flex min-w-0 flex-col gap-4 sm:gap-5">{champion}</div>;
}
