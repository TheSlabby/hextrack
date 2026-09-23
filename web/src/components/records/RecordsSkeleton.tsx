/** Loading placeholders sized like the record cards, so nothing shifts when data lands. */
import { GlowCard } from "@/components/common/GlowCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

/** One record card: title, the holder (56px champion + three lines) and two runner-up rows. */
export function RecordCardSkeleton({ runnersUp = 2, className }: { runnersUp?: number; className?: string }) {
  return (
    <GlowCard className={cn("flex h-full flex-col gap-3 p-4", className)} aria-hidden="true">
      <div className="flex items-center gap-2">
        <Skeleton className="size-4 rounded-md" />
        <Skeleton className="h-3.5 w-28" />
      </div>
      <div className="flex items-center gap-3 py-1.5">
        <Skeleton className="size-14 shrink-0 rounded-lg" />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Skeleton className="h-7 w-20" />
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-3 w-32" />
        </div>
      </div>
      {runnersUp > 0 ? (
        <div className="flex flex-col gap-0.5 border-t border-border pt-2">
          {Array.from({ length: runnersUp }, (_, i) => (
            <div key={i} className="flex h-8 items-center gap-2">
              <Skeleton className="h-3 w-3" />
              <Skeleton className="size-5 rounded-md" />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-8" />
            </div>
          ))}
        </div>
      ) : null}
    </GlowCard>
  );
}

/** The /records body: the card grid, the AI Score card and the hall of fame. */
export function RecordsSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading records">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 16 }, (_, i) => (
          <RecordCardSkeleton key={i} />
        ))}
        <GlowCard className="flex flex-col gap-3 p-4 sm:col-span-2 sm:p-5 xl:col-span-4" aria-hidden="true">
          <Skeleton className="h-3.5 w-40" />
          <div className="grid gap-2 xl:grid-cols-3">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-[62px] rounded-xl" />
            ))}
          </div>
        </GlowCard>
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <GlowCard className="flex flex-col gap-4 p-4 sm:p-5" aria-hidden="true">
          <Skeleton className="h-5 w-48" />
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-[62px] rounded-xl" />
            ))}
          </div>
        </GlowCard>
        <GlowCard className="flex flex-col gap-3 p-4 sm:p-5" aria-hidden="true">
          <Skeleton className="h-5 w-32" />
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-7" />
          ))}
        </GlowCard>
      </div>
    </div>
  );
}
