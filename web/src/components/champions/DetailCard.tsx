import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { GlowCard } from "@/components/common/GlowCard";
import { SectionHeader } from "@/components/common/SectionHeader";
import { cn } from "@/lib/cn";

/** A champion page section: card, title row (eyebrow, icon, description, actions), body. */
export function DetailCard({
  title,
  eyebrow,
  icon,
  description,
  action,
  children,
  className,
  id,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  icon?: LucideIcon;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <GlowCard id={id} className={cn("flex flex-col gap-4 p-4 sm:p-5", className)}>
      <SectionHeader title={title} eyebrow={eyebrow} icon={icon} description={description} action={action} />
      {children}
    </GlowCard>
  );
}

/** Dashed "nothing here" box for an empty list inside a card. */
export function EmptyNote({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={cn(
        "rounded-xl border border-dashed border-border-strong px-3 py-5 text-center text-sm text-text-secondary",
        className,
      )}
    >
      {children}
    </p>
  );
}
