import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

/** Keyboard key hint, e.g. <Kbd>⌘</Kbd><Kbd>K</Kbd>. */
export function Kbd({ className, ...props }: ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] border border-border-strong bg-surface-2 px-1 font-sans text-[11px] leading-none font-medium text-text-secondary shadow-[inset_0_-1px_0_rgba(255,255,255,0.06)]",
        className,
      )}
      {...props}
    />
  );
}
