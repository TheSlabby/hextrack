import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

import { GlowCard } from "./GlowCard";

/** Lines of text. Last line is shorter so it reads as a paragraph. */
export function SkeletonText({ lines = 1, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-3", i === lines - 1 && lines > 1 ? "w-3/5" : "w-full")} />
      ))}
    </div>
  );
}

export function SkeletonCircle({ size = 40, className }: { size?: number; className?: string }) {
  return <Skeleton className={cn("rounded-full", className)} style={{ width: size, height: size }} />;
}

/** Placeholder for <StatTile />: same padding and line heights. */
export function SkeletonStatTile({ className }: { className?: string }) {
  return (
    <GlowCard className={cn("p-4", className)} aria-hidden="true">
      <div className="flex flex-col gap-1.5">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-8 w-24 sm:h-[35px]" />
        <Skeleton className="h-4 w-28" />
      </div>
    </GlowCard>
  );
}

/** Placeholder for a chart card body. */
export function SkeletonChart({ height = 220, className }: { height?: number; className?: string }) {
  return (
    <div className={cn("relative w-full overflow-hidden rounded-xl", className)} style={{ height }} aria-hidden="true">
      <div className="absolute inset-0 flex flex-col justify-between py-2">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-px w-full bg-white/[0.04]" />
        ))}
      </div>
      <Skeleton className="absolute inset-x-0 bottom-0 h-2/3 rounded-xl opacity-60 [clip-path:polygon(0_70%,12%_55%,25%_62%,38%_40%,50%_48%,63%_30%,75%_42%,88%_22%,100%_30%,100%_100%,0_100%)]" />
    </div>
  );
}

/** Generic card with header + body lines. */
export function SkeletonCard({ lines = 3, className, height }: { lines?: number; className?: string; height?: number }) {
  return (
    <GlowCard className={cn("flex flex-col gap-4 p-5", className)} style={height ? { height } : undefined} aria-hidden="true">
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
      <SkeletonText lines={lines} />
    </GlowCard>
  );
}

/** Table / list row: avatar + two text lines + trailing value. */
export function SkeletonRow({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-3 py-2.5", className)} aria-hidden="true">
      <Skeleton className="size-9 shrink-0 rounded-lg" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Skeleton className="h-3.5 w-1/3" />
        <Skeleton className="h-3 w-1/4" />
      </div>
      <Skeleton className="h-6 w-14 rounded-full" />
    </div>
  );
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("divide-y divide-border", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <SkeletonRow key={i} />
      ))}
    </div>
  );
}
