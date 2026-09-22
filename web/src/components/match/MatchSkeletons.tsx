import { GlowCard } from "@/components/common/GlowCard";
import { SkeletonChart } from "@/components/common/Skeletons";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

/** Placeholder with the same box model as <MatchRow /> (collapsed), at every container width. */
export function MatchRowSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("relative overflow-hidden rounded-xl border border-border bg-surface-1 shadow-card", className)}
    >
      <span className="absolute inset-y-0 left-0 w-1 bg-surface-3" />
      <div className="flex flex-col gap-2.5 py-3 pr-3 pl-4 @2xl:flex-row @2xl:items-center @2xl:gap-3 @2xl:py-2.5">
        {/* mobile header */}
        <div className="flex h-4 items-center gap-2 @2xl:hidden">
          <Skeleton className="h-3.5 w-14" />
          <Skeleton className="h-3 w-40" />
        </div>
        {/* desktop game info */}
        <div className="hidden w-[84px] shrink-0 flex-col gap-1.5 @2xl:flex @4xl:w-[92px]">
          <Skeleton className="h-3.5 w-20" />
          <Skeleton className="h-3 w-14" />
          <span className="my-0.5 h-px w-8 bg-border-strong" />
          <Skeleton className="h-3.5 w-12" />
          <Skeleton className="h-3 w-10" />
        </div>
        {/* core */}
        <div className="flex min-w-0 flex-col gap-2 @2xl:w-[256px] @2xl:shrink-0 @4xl:w-[276px]">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <Skeleton className="size-14 rounded-lg" />
              <div className="flex flex-col gap-0.5">
                <Skeleton className="size-5 rounded-[5px]" />
                <Skeleton className="size-5 rounded-[5px]" />
              </div>
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-3 w-14" />
            </div>
            <div className="flex w-[76px] flex-col items-center gap-1">
              <Skeleton className="h-6 w-14 rounded-full" />
              <Skeleton className="h-[18px] w-9 rounded-full" />
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="size-[22px] rounded-md" />
            ))}
            <Skeleton className="ml-1.5 size-[22px] rounded-full" />
          </div>
        </div>
        {/* stats */}
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 @2xl:w-[84px] @2xl:shrink-0 @2xl:flex-col @4xl:w-[104px]">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex h-4 items-center">
              <Skeleton className="h-3 w-16" />
            </div>
          ))}
        </div>
        {/* participants */}
        <div className="hidden min-w-0 flex-1 grid-cols-2 gap-x-2.5 @2xl:grid @3xl:gap-x-3">
          {Array.from({ length: 2 }, (_, col) => (
            <div key={col} className="flex flex-col gap-0.5">
              {Array.from({ length: 5 }, (_, i) => (
                <div key={i} className="flex h-4 items-center gap-1.5">
                  <Skeleton className="size-4 rounded-[4px]" />
                  <Skeleton className="h-2.5 w-16" />
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="hidden w-7 @2xl:block" />
      </div>
    </div>
  );
}

function TeamPanelSkeleton({ embedded }: { embedded?: boolean }) {
  const inner = (
    <>
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <Skeleton className="h-5 w-1 rounded-full" />
        <Skeleton className="h-4 w-36" />
        <div className="ml-auto hidden gap-1.5 @3xl:flex">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-6 w-10 rounded-md" />
          ))}
        </div>
      </div>
      <div className="divide-y divide-border">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-2.5">
            <Skeleton className="size-7 rounded-md" />
            <div className="flex w-32 flex-col gap-1.5">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-2.5 w-16" />
            </div>
            <Skeleton className="ml-auto h-5 w-12 rounded-full @3xl:ml-0" />
            <div className="hidden flex-1 items-center gap-6 @3xl:flex">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-12" />
              <Skeleton className="h-3 w-10" />
              <Skeleton className="ml-auto h-[22px] w-40 rounded-md" />
            </div>
          </div>
        ))}
      </div>
    </>
  );
  if (embedded) {
    return <div className="overflow-hidden rounded-xl border border-border bg-surface-2/40">{inner}</div>;
  }
  return <GlowCard className="overflow-hidden">{inner}</GlowCard>;
}

/** Placeholder for <MatchDetailView /> with the same sections and heights. */
export function MatchDetailSkeleton({ embedded }: { embedded?: boolean }) {
  return (
    <div role="status" aria-label="Loading match" className={cn("@container flex flex-col", embedded ? "gap-3" : "gap-6")}>
      {embedded ? (
        <div className="flex items-center gap-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-32" />
          <Skeleton className="ml-auto h-3 w-24" />
        </div>
      ) : (
        <GlowCard className="flex flex-col gap-4 p-5 sm:p-6">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-3.5 w-72 max-w-full" />
        </GlowCard>
      )}
      <TeamPanelSkeleton embedded={embedded} />
      <TeamPanelSkeleton embedded={embedded} />
      <div className={cn("grid @3xl:grid-cols-2", embedded ? "gap-3" : "gap-6")}>
        {Array.from({ length: 2 }, (_, i) =>
          embedded ? (
            <div key={i} className="rounded-xl border border-border bg-surface-2/40 p-4">
              <Skeleton className="mb-3 h-3.5 w-28" />
              <SkeletonChart height={180} />
            </div>
          ) : (
            <GlowCard key={i} className="p-5">
              <Skeleton className="mb-4 h-4 w-32" />
              <SkeletonChart height={220} />
            </GlowCard>
          ),
        )}
      </div>
    </div>
  );
}
