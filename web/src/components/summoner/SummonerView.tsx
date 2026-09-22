import type { SummonerProfile } from "@/api/types";
import { Reveal, Stagger, StaggerItem } from "@/components/common";
import { useMediaQuery } from "@/lib/hooks";

import { SIDEBAR_GRID, SUMMONER_GRID } from "./layout";
import { ProfileHeader } from "./ProfileHeader";
import { RankCard } from "./RankCard";
import { RankStrip } from "./RankStrip";
import { SeasonCards } from "./SeasonCards";
import { SummonerTabs } from "./SummonerTabs";
import type { SummonerTabValue } from "./tabs";

export interface SummonerViewProps {
  profile: SummonerProfile;
  region: string;
  tab: SummonerTabValue;
  onTabChange: (tab: SummonerTabValue) => void;
}

/**
 * The loaded profile page: header, season sidebar and the tabbed main column.
 *
 * Below `lg` there is no room for a sidebar, and stacking it above the tabs would push the
 * match history two screens down. Phones and tablets get a compact rank strip instead, with
 * the season cards moved inside the Overview tab.
 */
export function SummonerView({ profile, region, tab, onTabChange }: SummonerViewProps) {
  const sidebar = useMediaQuery("(min-width: 1024px)");

  return (
    <div className="flex flex-col gap-6 sm:gap-8">
      <Reveal>
        <ProfileHeader profile={profile} region={region} />
      </Reveal>

      <div className={SUMMONER_GRID}>
        {sidebar ? (
          <div className="flex min-w-0 flex-col gap-4">
            <Stagger className={SIDEBAR_GRID}>
              <StaggerItem className="min-w-0">
                <RankCard queue="RANKED_SOLO_5x5" entry={profile.solo} className="h-full" />
              </StaggerItem>
              <StaggerItem className="min-w-0">
                <RankCard queue="RANKED_FLEX_SR" entry={profile.flex} compact className="h-full" />
              </StaggerItem>
            </Stagger>
            <SeasonCards profile={profile} />
          </div>
        ) : (
          <Reveal className="min-w-0">
            <RankStrip solo={profile.solo} flex={profile.flex} />
          </Reveal>
        )}

        <section aria-label="Profile details" className="min-w-0">
          <SummonerTabs profile={profile} tab={tab} onTabChange={onTabChange} showSeasonCards={!sidebar} />
        </section>
      </div>
    </div>
  );
}
