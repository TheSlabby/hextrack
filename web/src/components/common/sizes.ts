/** Shared icon size scale (px) for champion / profile / item art. */
export type IconSize = "xs" | "sm" | "md" | "lg" | "xl";

export const ICON_PX: Readonly<Record<IconSize, number>> = {
  xs: 20,
  sm: 28,
  md: 40,
  lg: 56,
  xl: 80,
};
