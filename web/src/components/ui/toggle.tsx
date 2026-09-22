import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Toggle as TogglePrimitive } from "radix-ui";

import { cn } from "@/lib/cn";

const toggleVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium whitespace-nowrap text-text-secondary transition-[color,background-color,box-shadow] duration-150 outline-none",
    "hover:bg-white/5 hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold disabled:pointer-events-none disabled:opacity-45",
    "data-[state=on]:bg-surface-3 data-[state=on]:text-gold-bright data-[state=on]:shadow-[0_1px_0_0_rgba(255,255,255,0.06)_inset]",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ].join(" "),
  {
    variants: {
      variant: {
        default: "bg-transparent",
        outline: "border border-border bg-surface-1/60 hover:border-border-strong",
      },
      size: {
        default: "h-9 min-w-9 px-2.5",
        sm: "h-8 min-w-8 px-2 text-[13px]",
        lg: "h-10 min-w-10 px-3",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Toggle({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> & VariantProps<typeof toggleVariants>) {
  return <TogglePrimitive.Root data-slot="toggle" className={cn(toggleVariants({ variant, size, className }))} {...props} />;
}

export { Toggle, toggleVariants };
