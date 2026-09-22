import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface SectionHeaderProps {
  title: ReactNode;
  /** Small uppercase label above the title. */
  eyebrow?: ReactNode;
  description?: ReactNode;
  icon?: LucideIcon;
  /** Right-aligned controls (filters, links). */
  action?: ReactNode;
  /** Heading level for the title (default h2). */
  as?: "h1" | "h2" | "h3";
  size?: "sm" | "md" | "lg";
  className?: string;
}

const TITLE = {
  sm: "text-sm font-semibold",
  md: "text-lg font-semibold",
  lg: "text-2xl sm:text-3xl font-semibold",
} as const;

/** Section title row: optional eyebrow + icon, title, description and actions. */
export function SectionHeader({ title, eyebrow, description, icon: Icon, action, as: Heading = "h2", size = "md", className }: SectionHeaderProps) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-x-4 gap-y-2", className)}>
      <div className="flex min-w-0 flex-col gap-1">
        {eyebrow ? <span className="label-caps">{eyebrow}</span> : null}
        <div className="flex items-center gap-2">
          {Icon ? <Icon className={cn("shrink-0 text-gold", size === "sm" ? "size-4" : "size-5")} aria-hidden="true" /> : null}
          <Heading className={cn("font-display tracking-tight text-text", TITLE[size])}>{title}</Heading>
        </div>
        {description ? <p className="text-sm text-text-secondary">{description}</p> : null}
      </div>
      {action ? <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div> : null}
    </div>
  );
}
