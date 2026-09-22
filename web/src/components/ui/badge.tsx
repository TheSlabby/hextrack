import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";

import { cn } from "@/lib/cn";

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border px-2 py-0.5 text-[11px] leading-4 font-semibold whitespace-nowrap tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "border-gold/30 bg-gold/12 text-gold",
        secondary: "border-border bg-surface-2 text-text-secondary",
        ai: "border-cyan/30 bg-cyan/10 text-cyan",
        win: "border-win/30 bg-win/12 text-win",
        loss: "border-loss/30 bg-loss/12 text-loss",
        remake: "border-remake/30 bg-remake/12 text-remake",
        destructive: "border-loss/30 bg-loss/12 text-loss",
        outline: "border-border-strong bg-transparent text-text-secondary [a&]:hover:text-text",
        ghost: "border-transparent text-text-secondary [a&]:hover:bg-white/5",
        link: "border-transparent text-gold underline-offset-4 [a&]:hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span";

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
