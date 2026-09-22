/**
 * Summoner profile: /summoner/$region/$riotId (slug "GameName-TAG", split on the last "-").
 * The active tab lives in the validated `?tab=` search param (overview is the default and is
 * kept out of the URL).
 */
import { useCallback } from "react";
import { getRouteApi } from "@tanstack/react-router";

import { useSummonerProfile } from "@/api/queries";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import { SummonerSkeleton } from "@/components/summoner/SummonerSkeleton";
import { InvalidRiotIdState, SummonerErrorState } from "@/components/summoner/SummonerStates";
import { SummonerView } from "@/components/summoner/SummonerView";
import type { SummonerTabValue } from "@/components/summoner/tabs";
import { formatRiotId, parseSlug } from "@/lib/riotId";

const route = getRouteApi("/summoner/$region/$riotId");

export function SummonerPage() {
  const { region, riotId } = route.useParams();
  const parsed = parseSlug(riotId);

  if (!parsed) return <InvalidSlug slug={riotId} region={region} />;
  // Re-mount per player so mutation state, countdowns and local toggles never leak across profiles.
  const key = `${parsed.gameName.toLowerCase()}#${parsed.tagLine.toLowerCase()}`;
  return <SummonerProfilePage key={key} region={region} gameName={parsed.gameName} tagLine={parsed.tagLine} />;
}

function InvalidSlug({ slug, region }: { slug: string; region: string }) {
  useDocumentTitle(pageTitle("Summoner not found"));
  return <InvalidRiotIdState slug={slug} region={region} />;
}

interface SummonerProfilePageProps {
  region: string;
  gameName: string;
  tagLine: string;
}

function SummonerProfilePage({ region, gameName, tagLine }: SummonerProfilePageProps) {
  const { tab = "overview" } = route.useSearch();
  const navigate = route.useNavigate();
  const profile = useSummonerProfile(gameName, tagLine);

  const title = profile.data ? formatRiotId(profile.data.game_name, profile.data.tag_line) : formatRiotId(gameName, tagLine);
  useDocumentTitle(pageTitle(title));

  const setTab = useCallback(
    (next: SummonerTabValue) => {
      void navigate({
        search: (previous) => ({ ...previous, tab: next === "overview" ? undefined : next }),
        resetScroll: false,
      });
    },
    [navigate],
  );

  if (profile.data) {
    return <SummonerView profile={profile.data} region={region} tab={tab} onTabChange={setTab} />;
  }
  if (profile.isError) {
    return (
      <SummonerErrorState
        error={profile.error}
        gameName={gameName}
        tagLine={tagLine}
        region={region}
        onRetry={() => void profile.refetch()}
      />
    );
  }
  return <SummonerSkeleton gameName={gameName} tagLine={tagLine} />;
}
