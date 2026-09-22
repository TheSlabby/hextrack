import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

import { GlowCard, SkeletonChart, SkeletonText } from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "@/lib/hooks";

import { ProfileBanner } from "./ProfileBanner";
import { AI_PANEL, SIDEBAR_GRID, SUMMONER_GRID } from "./layout";

/** After this long, explain that first lookups go through Riot. */
const SLOW_AFTER_MS = 2_500;

export interface SummonerSkeletonProps {
  gameName: string;
  tagLine: string;
}

/** Card placeholder; `height` is [phone, sm and up] in px, measured from the loaded cards. */
function CardSkeleton({ height, className, children }: { height: [number, number]; className?: string; children?: ReactNode }) {
  const style = { "--skeleton-h": `${height[0]}px`, "--skeleton-h-sm": `${height[1]}px` } as CSSProperties;
  return (
    <GlowCard
      className={cn("flex min-h-[var(--skeleton-h)] flex-col gap-4 p-4 sm:min-h-[var(--skeleton-h-sm)] sm:p-5", className)}
      style={style}
      aria-hidden="true"
    >
      <div className="flex flex-col gap-1.5">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-4 w-32" />
      </div>
      {children}
    </GlowCard>
  );
}

/** Loading layout that mirrors the profile page, so nothing jumps when data arrives. */
export function SummonerSkeleton({ gameName, tagLine }: SummonerSkeletonProps) {
  const sidebar = useMediaQuery("(min-width: 1024px)");
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => window.clearTimeout(id);
  }, []);

  return (
    <div className="flex flex-col gap-6 sm:gap-8" role="status" aria-live="polite" aria-label={`Loading ${gameName}#${tagLine}`}>
      <header className="relative isolate pt-2 sm:pt-8">
        <ProfileBanner champion={null} />
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex min-w-0 items-start gap-4 sm:items-center sm:gap-5">
            <div className="mb-2 shrink-0">
              <Skeleton className="size-20 rounded-full" />
            </div>
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex h-[22px] items-center gap-1.5">
                <Skeleton className="h-[22px] w-10 rounded-full" />
              </div>
              <p className="font-display text-[28px] leading-[1.1] font-bold tracking-tight [overflow-wrap:anywhere] text-text/80 sm:text-4xl">
                {gameName}
                <span className="ml-1.5 text-xl font-medium text-text-muted sm:text-2xl">#{tagLine}</span>
              </p>
              <p className="flex h-5 items-center gap-1.5 text-sm text-text-secondary">
                <Loader2 className="size-3.5 animate-spin text-gold" aria-hidden="true" />
                {slow ? "Looking this player up on Riot. First visits take a few seconds…" : "Loading profile…"}
              </p>
              <div className="mt-1 flex items-center gap-2">
                <Skeleton className="h-9 w-[7.5rem] rounded-lg" />
                <Skeleton className="size-9 rounded-lg" />
              </div>
            </div>
          </div>

          <div className={AI_PANEL}>
            <Skeleton className="size-[100px] shrink-0 rounded-full sm:size-[124px]" />
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-5 w-28" />
              <SkeletonText lines={2} />
              <Skeleton className="h-6 w-24 rounded-md" />
            </div>
          </div>
        </div>
      </header>

      <div className={SUMMONER_GRID}>
        {/* Mirrors SummonerView: sidebar at lg, a compact rank strip below it. The season
            cards then load at the end of the Overview tab, below the fold. */}
        {sidebar ? (
          <div className={SIDEBAR_GRID} aria-hidden="true">
            <CardSkeleton height={[205, 213]}>
              <div className="flex items-center gap-4">
                <Skeleton className="size-[76px] shrink-0 rounded-2xl" />
                <div className="flex flex-1 flex-col gap-2">
                  <Skeleton className="h-5 w-28" />
                  <Skeleton className="h-3.5 w-14" />
                  <Skeleton className="h-1 w-full" />
                </div>
              </div>
            </CardSkeleton>
            <CardSkeleton height={[200, 208]}>
              <div className="flex items-center gap-4">
                <Skeleton className="size-[60px] shrink-0 rounded-2xl" />
                <div className="flex flex-1 flex-col gap-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-3.5 w-14" />
                  <Skeleton className="h-1 w-full" />
                </div>
              </div>
            </CardSkeleton>
            <CardSkeleton height={[396, 419]}>
              <div className="grid grid-cols-3 gap-2">
                {Array.from({ length: 3 }, (_, i) => (
                  <Skeleton key={i} className="h-24 rounded-xl" />
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} className="h-20 rounded-xl" />
                ))}
              </div>
            </CardSkeleton>
            <CardSkeleton height={[482, 490]}>
              <div className="flex flex-col gap-4">
                {Array.from({ length: 7 }, (_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="size-7 shrink-0 rounded-md" />
                    <Skeleton className="h-3.5 flex-1" />
                    <Skeleton className="h-5 w-10 rounded-full" />
                  </div>
                ))}
              </div>
            </CardSkeleton>
            <CardSkeleton height={[244, 252]}>
              <div className="flex flex-col gap-4">
                {Array.from({ length: 3 }, (_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="size-7 shrink-0 rounded-lg" />
                    <Skeleton className="h-2 flex-1 rounded-full" />
                    <Skeleton className="h-4 w-9" />
                  </div>
                ))}
              </div>
            </CardSkeleton>
          </div>
        ) : (
          <GlowCard className="grid grid-cols-2 gap-px overflow-hidden bg-border p-0" aria-hidden="true">
            {Array.from({ length: 2 }, (_, i) => (
              <div key={i} className="flex min-h-[8.5rem] min-w-0 flex-col gap-2 bg-surface-1 p-3 sm:p-4">
                <Skeleton className="h-3 w-24" />
                <div className="flex items-center gap-2.5 sm:gap-3">
                  <Skeleton className="size-11 shrink-0 rounded-xl" />
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Skeleton className="h-4 w-20" />
                    <Skeleton className="h-3 w-12" />
                  </div>
                </div>
                <Skeleton className="h-1 w-full" />
                <Skeleton className="h-3 w-full" />
              </div>
            ))}
          </GlowCard>
        )}

        <div className="flex min-w-0 flex-col gap-5">
          <div className="flex h-11 items-center gap-6 border-b border-border" aria-hidden="true">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-24" />
          </div>
          <div className="flex flex-col gap-6">
            <CardSkeleton height={[394, 386]}>
              <Skeleton className="h-5 w-56" />
              <SkeletonChart height={240} />
            </CardSkeleton>
            <div className="grid gap-6 md:grid-cols-2">
              <CardSkeleton height={[332, 340]}>
                <SkeletonChart height={180} />
              </CardSkeleton>
              <CardSkeleton height={[247, 340]}>
                <div className="grid grid-cols-3 gap-2">
                  {Array.from({ length: 3 }, (_, i) => (
                    <Skeleton key={i} className="h-14 rounded-xl" />
                  ))}
                </div>
                <div className="grid grid-cols-10 gap-1">
                  {Array.from({ length: 20 }, (_, i) => (
                    <Skeleton key={i} className="h-7 rounded-md" />
                  ))}
                </div>
              </CardSkeleton>
            </div>
            <CardSkeleton height={[454, 462]}>
              <div className="flex flex-col gap-2">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-[62px] rounded-xl" />
                ))}
              </div>
            </CardSkeleton>
          </div>
        </div>
      </div>
    </div>
  );
}
