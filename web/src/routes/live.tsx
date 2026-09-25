import { getRouteApi } from "@tanstack/react-router";

const route = getRouteApi("/live/$gameId");

/** Live game page (placeholder until the full view lands). */
export function LiveGamePage() {
  const { gameId } = route.useParams();
  return <p className="text-text-secondary">Live game {gameId}</p>;
}
