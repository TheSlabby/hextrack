import type { Position } from "@/api/types";
import { cn } from "@/lib/cn";
import { POSITION_ICONS, POSITION_LONG_LABELS } from "@/lib/positions";

export interface PositionIconProps {
  position: Position;
  size?: number;
  className?: string;
  /** Accessible label; defaults to the role name. Pass "" to hide from assistive tech. */
  title?: string;
}

/** Two-tone role glyph drawn in currentColor. */
export function PositionIcon({ position, size = 16, className, title }: PositionIconProps) {
  const icon = POSITION_ICONS[position];
  const label = title ?? POSITION_LONG_LABELS[position];
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={cn("shrink-0", className)}
      fill="currentColor"
      role={label ? "img" : undefined}
      aria-label={label || undefined}
      aria-hidden={label ? undefined : true}
    >
      {label ? <title>{label}</title> : null}
      {icon.secondary ? <path d={icon.secondary} opacity={0.38} /> : null}
      <path d={icon.primary} />
    </svg>
  );
}
