import * as React from "react";

import { cn } from "@/lib/cn";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-10 w-full min-w-0 rounded-lg border border-border-strong bg-surface-1/80 px-3 py-1 text-base text-text shadow-[inset_0_1px_2px_rgba(0,0,0,0.3)] transition-[border-color,box-shadow,background-color] outline-none md:text-sm",
        "placeholder:text-text-muted selection:bg-gold/30",
        "hover:border-white/20 focus-visible:border-gold/60 focus-visible:bg-surface-1 focus-visible:shadow-[0_0_0_3px_rgba(200,170,110,0.18)]",
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-loss/60 aria-invalid:shadow-[0_0_0_3px_rgba(255,93,108,0.15)]",
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-text",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
