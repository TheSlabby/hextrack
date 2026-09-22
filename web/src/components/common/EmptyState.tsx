import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  /** Buttons / links guiding the next step. */
  action?: ReactNode;
  /** Tighter padding for use inside small cards. */
  compact?: boolean;
  /** Accent for the icon medallion. */
  tone?: "default" | "ai";
  className?: string;
}

/** Friendly "nothing here yet" block: icon medallion, title, guidance and an optional action. */
export function EmptyState({ icon: Icon = Inbox, title, description, action, compact, tone = "default", className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-2 px-4 py-6" : "gap-3 px-6 py-12",
        className,
      )}
    >
      <span
        className={cn(
          "flex items-center justify-center rounded-2xl border",
          compact ? "size-10" : "size-14",
          tone === "ai" ? "border-cyan/25 bg-cyan/8 text-cyan" : "border-border-strong bg-surface-2 text-gold",
        )}
      >
        <Icon className={compact ? "size-5" : "size-6"} aria-hidden="true" />
      </span>
      <div className="flex max-w-sm flex-col gap-1">
        <p className={cn("font-display font-semibold text-text", compact ? "text-sm" : "text-base")}>{title}</p>
        {description ? <div className="text-sm leading-relaxed text-text-secondary">{description}</div> : null}
      </div>
      {action ? <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
    </div>
  );
}
