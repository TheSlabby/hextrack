import { GlowCard } from "@/components/common/GlowCard";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/cn";

import { LEADERBOARD_COLUMNS } from "./columns";

const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;

/** Cell placeholders sized like the real cell content (rows come out the same height). */
function CellSkeleton({ column }: { column: string }) {
  switch (column) {
    case "standing":
      return <Skeleton className="mx-auto size-7 rounded-lg" />;
    case "player":
      return (
        <div className="flex items-center gap-2.5">
          <Skeleton className="size-7 shrink-0 rounded-full" />
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-3 w-16" />
          </div>
        </div>
      );
    case "rank":
      return (
        <div className="flex items-center gap-2">
          <Skeleton className="size-[30px] shrink-0 rounded-lg" />
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-20" />
            <Skeleton className="h-3 w-12" />
          </div>
        </div>
      );
    case "games":
      return <Skeleton className="ml-auto h-3.5 w-7" />;
    case "winrate":
      return (
        <div className="flex w-full max-w-28 flex-col gap-1.5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-1.5 w-full rounded-full" />
        </div>
      );
    case "kda":
      return (
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3.5 w-14" />
          <Skeleton className="h-3 w-20" />
        </div>
      );
    case "ai":
      return <Skeleton className="mx-auto h-6 w-14 rounded-full" />;
    case "lp":
      return <Skeleton className="ml-auto h-3.5 w-10" />;
    case "ally":
      return (
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-3 w-20" />
        </div>
      );
    case "champions":
      return (
        <div className="flex">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className={cn("size-7 rounded-md ring-2 ring-surface-1", i > 0 && "-ml-1.5")} />
          ))}
        </div>
      );
    case "form":
      return <Skeleton className="h-3.5 w-[78px]" />;
    default:
      return <Skeleton className="h-3.5 w-12" />;
  }
}

/** Table placeholder with the real header labels and column widths. */
export function LeaderboardTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <GlowCard className="overflow-clip" role="status" aria-label="Loading leaderboard">
      <Table className="min-w-[1120px] xl:min-w-0 xl:table-fixed" aria-hidden="true">
        <TableHeader>
          <TableRow>
            {LEADERBOARD_COLUMNS.map((column) => (
              <TableHead key={column.id} className={cn("h-11 px-2", ALIGN[column.align ?? "left"], column.className)}>
                {column.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: rows }, (_, row) => (
            <TableRow key={row} className="hover:bg-transparent">
              {LEADERBOARD_COLUMNS.map((column) => (
                <TableCell key={column.id} className={cn("h-[57px] px-2", column.className)}>
                  <CellSkeleton column={column.id} />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </GlowCard>
  );
}

/** Mobile card placeholders. */
export function LeaderboardCardsSkeleton({ cards = 4 }: { cards?: number }) {
  return (
    <div className="flex flex-col gap-3" role="status" aria-label="Loading leaderboard">
      {Array.from({ length: cards }, (_, i) => (
        <GlowCard key={i} className="p-4" aria-hidden="true">
          <div className="flex items-center gap-3">
            <Skeleton className="size-7 rounded-lg" />
            <Skeleton className="size-7 rounded-full" />
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-3 w-24" />
            </div>
            <Skeleton className="h-8 w-16 rounded-full" />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {[0, 1, 2].map((j) => (
              <div key={j} className="flex flex-col gap-1.5">
                <Skeleton className="h-3 w-12" />
                <Skeleton className="h-4 w-10" />
              </div>
            ))}
          </div>
          <Skeleton className="mt-3 h-6 w-full" />
          <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
            <Skeleton className="h-8 w-28" />
            <Skeleton className="h-7 w-[72px]" />
          </div>
          <div className="mt-3 flex items-center justify-between">
            <Skeleton className="h-3 w-10" />
            <Skeleton className="h-3.5 w-[78px]" />
          </div>
        </GlowCard>
      ))}
    </div>
  );
}
