/** Top-level pages, shared by the header nav and the phone tab bar. */
import { Layers, Medal, Swords, Trophy, UsersRound, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: "/leaderboard" | "/champions" | "/squad" | "/stacks" | "/records";
  label: string;
  icon: LucideIcon;
}

/**
 * Main pages: text links in the header from `sm`, tabs in the phone tab bar. The rest
 * (`NAV_MORE`) sit in a "More" menu (header until xl, always on phones).
 */
export const NAV_MAIN: readonly NavItem[] = [
  { to: "/leaderboard", label: "Leaderboard", icon: Trophy },
  { to: "/champions", label: "Champions", icon: Swords },
  { to: "/squad", label: "Squad", icon: UsersRound },
];
export const NAV_MORE: readonly NavItem[] = [
  { to: "/stacks", label: "Stacks", icon: Layers },
  { to: "/records", label: "Records", icon: Medal },
];

export function isActivePath(pathname: string, to: string): boolean {
  return pathname === to || pathname.startsWith(`${to}/`);
}
