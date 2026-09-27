import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { GlowCard } from "@/components/common/GlowCard";
import { cn } from "@/lib/cn";

/**
 * A champion page section: a compact card with an icon + title row, an optional one-line note
 * under it and optional right-aligned meta (e.g. "50 games"). Kept tight on purpose: the page
 * shows a lot of small sections side by side.
 */
export function DetailCard({
  title,
  icon: Icon,
  description,
  action,
  children,
  className,
  id,
}: {
  title: ReactNode;
  icon?: LucideIcon;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <GlowCard id={id} className={cn("flex min-w-0 flex-col gap-3 p-4", className)}>
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex min-w-0 items-center justify-between gap-3">
          <h2 className="flex min-w-0 items-center gap-2 font-display text-base font-semibold tracking-tight text-text">
            {Icon ? <Icon className="size-4 shrink-0 text-gold" aria-hidden="true" /> : null}
            <span className="truncate">{title}</span>
          </h2>
          {action ? <div className="flex shrink-0 items-center gap-2 text-xs text-text-muted">{action}</div> : null}
        </div>
        {description ? <p className="text-xs leading-relaxed text-text-muted">{description}</p> : null}
      </div>
      {children}
    </GlowCard>
  );
}

/** A small uppercase heading inside a card (e.g. "Item 4"). */
export function SubHeading({ children, className }: { children: ReactNode; className?: string }) {
  return <h3 className={cn("label-caps", className)}>{children}</h3>;
}

/** Dashed "nothing here" box for an empty list inside a card. */
export function EmptyNote({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={cn(
        "rounded-xl border border-dashed border-border-strong px-3 py-4 text-center text-xs leading-relaxed text-text-secondary",
        className,
      )}
    >
      {children}
    </p>
  );
}
