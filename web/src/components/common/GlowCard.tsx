import * as React from "react";
import { Slot } from "radix-ui";

import { cn } from "@/lib/cn";

export interface GlowCardProps extends React.ComponentProps<"div"> {
  /** Lift + brighten the border on hover (for clickable cards). */
  interactive?: boolean;
  /** Coloured edge glow: gold (highlight) or cyan (AI). */
  glow?: "gold" | "cyan" | null;
  /** Render as the child element (e.g. a router <Link>). */
  asChild?: boolean;
}

/**
 * The standard page-section surface: 1px border, 16px radius, faint top-edge highlight and
 * a soft shadow. Pass `interactive` for hover lift, `glow` for an accent edge.
 */
export function GlowCard({ interactive, glow, asChild, className, ...props }: GlowCardProps) {
  const Comp = asChild ? Slot.Root : "div";
  return (
    <Comp
      data-slot="glow-card"
      className={cn(
        "surface-card min-w-0",
        interactive &&
          "transition-[transform,border-color,box-shadow] duration-200 ease-out hover:-translate-y-px hover:border-border-strong hover:shadow-[var(--shadow-raised)] focus-visible:border-gold/50",
        glow === "gold" && "border-gold/25 shadow-[var(--shadow-card),0_0_40px_-18px_rgba(200,170,110,0.45)]",
        glow === "cyan" && "border-cyan/25 shadow-[var(--shadow-card),0_0_40px_-18px_rgba(10,200,185,0.45)]",
        className,
      )}
      {...props}
    />
  );
}
