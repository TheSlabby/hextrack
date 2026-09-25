import { cn } from "@/lib/cn";

export interface LiveDotProps {
  size?: "sm" | "md";
  /** Show the "LIVE" text next to the dot (default). Without it the dot is decorative. */
  showLabel?: boolean;
  className?: string;
}

const DOT = { sm: "size-1.5", md: "size-2" } as const;
const TEXT = { sm: "text-[10px] tracking-[0.1em]", md: "text-[11px] tracking-[0.12em]" } as const;

/**
 * Red "on air" dot with a soft ping ring, plus an optional "LIVE" label. The ring only animates
 * with motion allowed (`motion-safe`), so reduced motion gets a steady dot.
 */
export function LiveDot({ size = "sm", showLabel = true, className }: LiveDotProps) {
  const dot = (
    <span aria-hidden="true" className={cn("relative inline-flex shrink-0", DOT[size])}>
      <span className="absolute inset-0 rounded-full bg-loss opacity-60 motion-safe:animate-ping" />
      <span className="relative inline-flex size-full rounded-full bg-loss shadow-[0_0_6px_0_var(--color-loss)]" />
    </span>
  );
  if (!showLabel) return <span className={cn("inline-flex items-center", className)}>{dot}</span>;

  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1.5 leading-none font-bold text-loss uppercase", TEXT[size], className)}>
      {dot}
      Live
    </span>
  );
}
