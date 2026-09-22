import { useId } from "react";

import { cn } from "@/lib/cn";

export interface LogoProps {
  /** Mark height in px. */
  size?: number;
  /** Show the "HexTrack" wordmark next to the mark. */
  wordmark?: boolean;
  className?: string;
}

/** HexTrack hex mark: gold faceted hexagon with a cyan core, plus the wordmark. */
export function LogoMark({ size = 28, className }: { size?: number; className?: string }) {
  const uid = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} className={cn("shrink-0", className)} aria-hidden="true">
      <defs>
        <linearGradient id={`${uid}-g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f0e6d2" />
          <stop offset="55%" stopColor="#c8aa6e" />
          <stop offset="100%" stopColor="#785a28" />
        </linearGradient>
        <linearGradient id={`${uid}-c`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#5ef2e4" />
          <stop offset="100%" stopColor="#0a7b74" />
        </linearGradient>
      </defs>
      <path d="M16 1.5 29 9v14l-13 7.5L3 23V9z" fill={`url(#${uid}-g)`} />
      <path d="M16 5.2 25.8 10.9v10.2L16 26.8 6.2 21.1V10.9z" fill="#07090f" />
      <path d="M16 9.5 21.5 16 16 22.5 10.5 16z" fill={`url(#${uid}-c)`} />
      <path d="M16 9.5 21.5 16H16z" fill="#ffffff" opacity="0.35" />
      <path d="M8.6 13.3v5.4M23.4 13.3v5.4" stroke="#c8aa6e" strokeWidth="1.4" strokeLinecap="round" opacity="0.7" />
    </svg>
  );
}

export function Logo({ size = 28, wordmark = true, className }: LogoProps) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark size={size} />
      {wordmark ? (
        <span className="font-display text-[17px] leading-none font-bold tracking-tight">
          <span className="text-gold-gradient">Hex</span>
          <span className="text-text">Track</span>
        </span>
      ) : null}
      <span className="sr-only">HexTrack</span>
    </span>
  );
}
