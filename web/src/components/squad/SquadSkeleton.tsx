import { GlowCard } from "@/components/common/GlowCard";
import { SkeletonRows } from "@/components/common/Skeletons";
import { Skeleton } from "@/components/ui/skeleton";

const GRID = 8;

function MatrixCardSkeleton() {
  return (
    <GlowCard className="flex max-w-full flex-none flex-col gap-4 p-4 sm:p-5" aria-hidden="true">
      <div className="flex flex-col gap-1.5">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-5 w-36" />
        <Skeleton className="h-4 w-full max-w-md" />
      </div>
      <div className="flex gap-6">
        <Skeleton className="h-10 w-52" />
        <Skeleton className="hidden h-10 w-44 sm:block" />
      </div>
      <div className="overflow-hidden">
        <div className="flex flex-col gap-0.5">
          <div className="flex gap-0.5 pl-[98px] sm:pl-[172px]">
            {Array.from({ length: GRID }, (_, c) => (
              <div key={c} className="flex w-[52px] shrink-0 flex-col items-center gap-1 pb-2 sm:w-16">
                <Skeleton className="size-7 rounded-full" />
                <Skeleton className="h-3 w-10" />
              </div>
            ))}
          </div>
          {Array.from({ length: GRID }, (_, r) => (
            <div key={r} className="flex items-center gap-0.5">
              <div className="flex w-[96px] shrink-0 items-center gap-2 sm:w-[170px]">
                <Skeleton className="size-5 rounded-full" />
                <Skeleton className="h-3.5 w-14 sm:w-24" />
              </div>
              {Array.from({ length: GRID }, (_, c) => (
                <Skeleton key={c} className="h-11 w-[52px] shrink-0 rounded-md sm:h-12 sm:w-16" />
              ))}
            </div>
          ))}
        </div>
      </div>
    </GlowCard>
  );
}

function ListCardSkeleton() {
  return (
    <GlowCard className="flex flex-col gap-3 p-4 sm:p-5" aria-hidden="true">
      <div className="flex flex-col gap-1.5">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-4 w-24" />
      </div>
      <SkeletonRows rows={5} />
    </GlowCard>
  );
}

/** Loading layout for /squad, sized like the final grids and lists. */
export function SquadSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading the squad">
      <div className="flex flex-wrap items-start gap-6">
        <MatrixCardSkeleton />
        <div className="flex min-w-[min(100%,20rem)] flex-1 basis-80 flex-col gap-6">
          <ListCardSkeleton />
          <ListCardSkeleton />
        </div>
      </div>
    </div>
  );
}
