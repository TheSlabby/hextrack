import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";

import { cn } from "@/lib/cn";

const buttonVariants = cva(
  [
    "relative inline-flex shrink-0 items-center justify-center gap-2 rounded-lg text-sm font-medium whitespace-nowrap select-none",
    "transition-[color,background-color,border-color,box-shadow,transform] duration-150 ease-out",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
    "disabled:pointer-events-none disabled:opacity-45 active:translate-y-px",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ].join(" "),
  {
    variants: {
      variant: {
        /** Gold call to action (Update, Search). */
        default:
          "bg-gradient-to-b from-[#d9bf86] to-gold text-primary-foreground shadow-[0_1px_0_0_rgba(255,255,255,0.35)_inset,0_6px_18px_-8px_rgba(200,170,110,0.6)] hover:from-gold-bright hover:to-[#d4b77c]",
        /** Cyan accent, reserved for AI actions. */
        ai: "bg-cyan/12 text-cyan border border-cyan/30 hover:bg-cyan/20 hover:border-cyan/50",
        destructive: "bg-loss/15 text-loss border border-loss/30 hover:bg-loss/25",
        outline:
          "border border-border-strong bg-surface-1/60 text-text hover:bg-surface-2 hover:border-white/20",
        secondary: "bg-surface-2 text-text border border-border hover:bg-surface-3 hover:border-border-strong",
        ghost: "text-text-secondary hover:bg-white/5 hover:text-text",
        link: "text-gold underline-offset-4 hover:underline hover:text-gold-bright px-0",
      },
      size: {
        default: "h-9 px-4 has-[>svg]:px-3",
        xs: "h-6 gap-1 rounded-md px-2 text-xs has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 rounded-md px-3 text-[13px] has-[>svg]:px-2.5",
        lg: "h-11 rounded-xl px-6 text-[15px] has-[>svg]:px-4",
        icon: "size-9",
        "icon-xs": "size-6 rounded-md [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8 rounded-md",
        "icon-lg": "size-11 rounded-xl",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot.Root : "button";

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
