import { GlowCard } from "@/components/common/GlowCard";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/cn";

import { championListColumns } from "./ChampionListModel";

const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;
const ROWS = 12;

function CellSkeleton({ column }: { column: string }) {
  switch (column) {
    case "rank":
      return <Skeleton className="mx-auto h-3 w-4" />;
    case "champion":
      return (
        <div className="flex items-center gap-2.5">
          <Skeleton className="size-7 shrink-0 rounded-md" />
          <Skeleton className="h-3.5 w-24" />
        </div>
      );
    case "roles":
      return <Skeleton className="h-4 w-10" />;
    case "win_rate":
      return (
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3.5 w-12" />
          <Skeleton className="h-1 w-14 rounded-full" />
        </div>
      );
    default:
      return <Skeleton className="ml-auto h-3.5 w-10" />;
  }
}

/** Desktop table placeholder, same columns and row height as the real table. */
export function ChampionListTableSkeleton() {
  const columns = championListColumns(null);
  return (
    <GlowCard className="overflow-clip" role="status" aria-label="Loading champions">
      <Table className="min-w-[680px] lg:min-w-0 lg:table-fixed" containerClassName="lg:overflow-visible">
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column.id} className={cn("h-11 px-2", ALIGN[column.align ?? "left"], column.className)}>
                {column.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: ROWS }, (_, row) => (
            <TableRow key={row} className="hover:bg-transparent">
              {columns.map((column) => (
                <TableCell key={column.id} className={cn("h-[53px] px-2", column.className)}>
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

/** Phone list placeholder. */
export function ChampionListCardsSkeleton() {
  return (
    <GlowCard className="overflow-clip" role="status" aria-label="Loading champions">
      <div className="divide-y divide-border">
        {Array.from({ length: ROWS }, (_, row) => (
          <div key={row} className="flex items-center gap-2.5 px-3 py-2.5">
            <Skeleton className="h-3 w-6 shrink-0" />
            <Skeleton className="size-7 shrink-0 rounded-md" />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-3 w-36" />
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <Skeleton className="h-3.5 w-12" />
              <Skeleton className="h-3 w-14" />
            </div>
          </div>
        ))}
      </div>
    </GlowCard>
  );
}
