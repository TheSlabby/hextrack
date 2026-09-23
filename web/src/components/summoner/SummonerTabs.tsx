import { useRef } from "react";
import { useReducedMotion } from "motion/react";
import { Activity, LayoutGrid, Sparkles, Swords } from "lucide-react";

import type { SummonerProfile } from "@/api/types";
import { AiInsightsPanel } from "@/components/ai/AiInsightsPanel";
import { AnimateOnce } from "@/components/common/Motion";
import { MatchList } from "@/components/match/MatchList";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { OverviewTab } from "./OverviewTab";
import { isSummonerTabValue, type SummonerTabValue } from "./tabs";
import { TrendsTab } from "./trends/TrendsTab";

export interface SummonerTabsProps {
  profile: SummonerProfile;
  tab: SummonerTabValue;
  onTabChange: (tab: SummonerTabValue) => void;
  /** Below lg the sidebar is gone, so Overview carries the season cards. */
  showSeasonCards?: boolean;
}

/** Overview | Matches | Trends | AI Insights, controlled by the `?tab=` search param. */
export function SummonerTabs({ profile, tab, onTabChange, showSeasonCards = false }: SummonerTabsProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  /** Switch tabs from inside the content and bring the tab bar back into view. */
  const jumpTo = (next: SummonerTabValue) => {
    onTabChange(next);
    const node = listRef.current;
    if (node && node.getBoundingClientRect().top < 64) {
      node.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
    }
  };

  return (
    <Tabs
      value={tab}
      onValueChange={(value) => {
        if (isSummonerTabValue(value)) onTabChange(value);
      }}
      className="gap-5"
    >
      <div ref={listRef} className="scroll-mt-20">
        <TabsList variant="line" aria-label="Profile sections" className="w-full justify-start gap-4 max-sm:[&_svg]:hidden sm:gap-6">
          <TabsTrigger value="overview">
            <LayoutGrid aria-hidden="true" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="matches">
            <Swords aria-hidden="true" />
            Matches
          </TabsTrigger>
          <TabsTrigger value="trends">
            <Activity aria-hidden="true" />
            Trends
          </TabsTrigger>
          <TabsTrigger value="ai" className="group-data-[variant=line]/tabs-list:data-[state=active]:text-cyan data-[state=active]:after:bg-cyan">
            <Sparkles aria-hidden="true" />
            AI Insights
          </TabsTrigger>
        </TabsList>
      </div>

      {/* Radix unmounts inactive panels, so each one plays its entrance once per page visit. */}
      <TabsContent value="overview" className="min-w-0">
        <AnimateOnce id="summoner-tab-overview">
          <OverviewTab
            profile={profile}
            onShowMatches={() => jumpTo("matches")}
            onShowAi={() => jumpTo("ai")}
            showSeasonCards={showSeasonCards}
          />
        </AnimateOnce>
      </TabsContent>
      <TabsContent value="matches" className="min-w-0">
        <AnimateOnce id="summoner-tab-matches">
          <MatchList puuid={profile.puuid} />
        </AnimateOnce>
      </TabsContent>
      <TabsContent value="trends" className="min-w-0">
        <AnimateOnce id="summoner-tab-trends">
          <TrendsTab puuid={profile.puuid} />
        </AnimateOnce>
      </TabsContent>
      <TabsContent value="ai" className="min-w-0">
        <AnimateOnce id="summoner-tab-ai">
          <AiInsightsPanel
            puuid={profile.puuid}
            season={{ average: profile.stats.avg_ai_score, games: profile.stats.ai_scored_games }}
            showRing={false}
          />
        </AnimateOnce>
      </TabsContent>
    </Tabs>
  );
}
