import { Link } from "@tanstack/react-router";
import { motion } from "motion/react";
import { Sparkles } from "lucide-react";

import type { LeaderboardEntry } from "@/api/types";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { RiotIdSearch } from "@/components/search/RiotIdSearch";
import { Skeleton } from "@/components/ui/skeleton";
import { summonerParams } from "@/lib/riotId";

import { HeroBackdrop } from "./HeroBackdrop";
import { useMediaQuery } from "@/lib/hooks";
import { EASE_OUT, MOTION, useEntranceMotion } from "@/lib/motion";

export interface HomeHeroProps {
  /** A few roster players to suggest as one-click examples (top of the standings). */
  examples?: readonly LeaderboardEntry[];
  /** The roster is still loading: hold the examples row's space with placeholders. */
  loading?: boolean;
}

/** Home hero: headline, one line on the AI Score, the Riot ID search and example players. */
export function HomeHero({ examples = [], loading = false }: HomeHeroProps) {
  const entrance = useEntranceMotion();
  const wide = useMediaQuery("(min-width: 640px)");
  // Delays stay inside one stagger span so the whole hero has settled within ~0.4 s.
  const enter = (delay: number) =>
    entrance
      ? {
          initial: { opacity: 0, y: 8 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: MOTION.duration, ease: EASE_OUT, delay },
        }
      : {};

  return (
    <section aria-labelledby="home-hero-title" className="relative z-20 pt-8 pb-4 sm:pt-16 sm:pb-8 lg:pt-20">
      <HeroBackdrop className="-inset-x-4 -top-6 -bottom-10 sm:-inset-x-6 sm:-top-8 lg:-inset-x-8" />

      <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
        <motion.span
          {...enter(0)}
          className="inline-flex items-center gap-1.5 rounded-full border border-cyan/25 bg-cyan/8 px-3 py-1 text-xs font-medium text-cyan shadow-[0_0_24px_-10px_rgba(10,200,185,0.7)]"
        >
          <Sparkles className="size-3.5" aria-hidden="true" />
          Every performance, graded by AI
        </motion.span>

        <motion.h1
          {...enter(0.03)}
          id="home-hero-title"
          className="mt-5 font-display text-[2.6rem] leading-[1.02] font-semibold tracking-[-0.03em] text-text sm:text-6xl lg:text-7xl"
        >
          Every game, <span className="text-gold-gradient">scored.</span>
        </motion.h1>

        <motion.p {...enter(0.06)} className="mt-4 max-w-xl text-base leading-relaxed text-text-secondary sm:text-lg">
          Match history, ranks and LP for you and your friends, plus an AI Score on every game: a neural net's read on
          how often your stat line wins.
        </motion.p>

        <motion.div {...enter(0.09)} className="relative z-10 mt-8 w-full max-w-2xl">
          <RiotIdSearch placeholder={wide ? "Search a Riot ID, e.g. Hexwalker#NA1" : "Riot ID, e.g. Hexwalker#NA1"} />
        </motion.div>

        {loading ? (
          <div className="mt-3 flex max-w-2xl flex-wrap items-center justify-center gap-2" aria-hidden="true">
            <Skeleton className="h-3 w-6" />
            {[112, 120, 116].map((width) => (
              <Skeleton key={width} className="h-8 rounded-full" style={{ width }} />
            ))}
          </div>
        ) : examples.length > 0 ? (
          <motion.div
            {...enter(0.12)}
            className="mt-3 flex max-w-2xl flex-wrap items-center justify-center gap-2"
            aria-label="Try a tracked player"
            role="group"
          >
            <span className="label-caps mr-0.5">Try</span>
            {examples.map((entry) => (
              <Link
                key={entry.puuid}
                to="/summoner/$region/$riotId"
                params={summonerParams(entry.game_name, entry.tag_line)}
                className="inline-flex h-8 max-w-full items-center gap-2 rounded-full border border-border bg-surface-1/70 pr-3 pl-1 text-[13px] text-text-secondary backdrop-blur transition-colors hover:border-border-strong hover:bg-surface-2 hover:text-text"
              >
                <ProfileIcon iconId={entry.profile_icon_id} size="xs" alt="" />
                <span className="truncate font-medium text-text">{entry.game_name}</span>
                <span className="-ml-1 text-text-muted">#{entry.tag_line}</span>
              </Link>
            ))}
          </motion.div>
        ) : null}
      </div>
    </section>
  );
}
