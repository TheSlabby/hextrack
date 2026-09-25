import { GlowCard } from "@/components/common/GlowCard";
import { SkeletonRows, SkeletonStatTile } from "@/components/common/Skeletons";
import { Skeleton } from "@/components/ui/skeleton";

function CardHeading({ wide = false }: { wide?: boolean }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Skeleton className="h-3 w-20" />
      <Skeleton className={wide ? "h-5 w-44" : "h-5 w-32"} />
    </div>
  );
}

function SummarySkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <GlowCard className="flex flex-wrap items-center gap-x-8 gap-y-4 p-5 sm:p-6" aria-hidden="true">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-10 w-40" />
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="flex gap-1.5">
          {Array.from({ length: 10 }, (_, i) => (
            <Skeleton key={i} className="size-3 rounded-full" />
          ))}
        </div>
      </GlowCard>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <SkeletonStatTile key={i} />
        ))}
      </div>
    </div>
  );
}

function AwardsSkeleton() {
  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5" aria-hidden="true">
      <CardHeading />
      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="flex items-center gap-3 rounded-xl border border-border p-3">
            <Skeleton className="size-10 shrink-0 rounded-full" />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-4 w-28" />
            </div>
          </div>
        ))}
      </div>
    </GlowCard>
  );
}

function LineupsSkeleton() {
  return (
    <GlowCard className="flex flex-col gap-3 p-4 sm:p-5" aria-hidden="true">
      <CardHeading />
      <div className="flex flex-col divide-y divide-border">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="flex items-center gap-3 py-2.5">
            <div className="flex -space-x-1.5">
              {Array.from({ length: 5 }, (_, j) => (
                <Skeleton key={j} className="size-7 rounded-full ring-2 ring-surface-1" />
              ))}
            </div>
            <Skeleton className="ml-auto h-3.5 w-16" />
            <Skeleton className="h-6 w-12 rounded-full" />
          </div>
        ))}
      </div>
    </GlowCard>
  );
}

function TableSkeleton({ rows }: { rows: number }) {
  return (
    <GlowCard className="flex flex-col gap-3 p-4 sm:p-5" aria-hidden="true">
      <CardHeading wide />
      <SkeletonRows rows={rows} />
    </GlowCard>
  );
}

function HighlightsSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-hidden="true">
      <Skeleton className="h-5 w-28" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <GlowCard key={i} className="flex flex-col gap-3 p-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-6 w-36" />
            <Skeleton className="h-3.5 w-full max-w-48" />
          </GlowCard>
        ))}
      </div>
    </div>
  );
}

/** Loading layout for /stacks, in the same order and grid as the loaded page. */
export function StacksSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading stacks">
      <SummarySkeleton />
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <AwardsSkeleton />
        <LineupsSkeleton />
      </div>
      <TableSkeleton rows={5} />
      <HighlightsSkeleton />
      <div className="flex flex-col gap-3" aria-hidden="true">
        <Skeleton className="h-5 w-20" />
        <SkeletonRows rows={4} />
      </div>
    </div>
  );
}
