import { Link } from "@tanstack/react-router";
import { Ellipsis, House, type LucideIcon } from "lucide-react";

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/cn";

import { isActivePath, NAV_MAIN, NAV_MORE } from "./nav";

const TAB =
  "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-lg py-1.5 text-[10px] leading-none font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-gold";

function Tab({ to, label, icon: Icon, active }: { to: string; label: string; icon: LucideIcon; active: boolean }) {
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      className={cn(TAB, active ? "text-gold-bright" : "text-text-muted hover:text-text-secondary")}
    >
      <Icon className={cn("size-5", active && "text-gold")} aria-hidden="true" />
      <span className="max-w-full truncate">{label}</span>
    </Link>
  );
}

/**
 * Phone navigation: a labelled tab bar fixed to the bottom of the screen (below `sm`), so every
 * page is one thumb tap away and named. Stacks and Records sit behind "More".
 */
export function MobileTabBar({ pathname }: { pathname: string }) {
  const moreActive = NAV_MORE.some((item) => isActivePath(pathname, item.to));
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-bg/85 px-2 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl sm:hidden"
    >
      <div className="mx-auto flex max-w-md items-stretch gap-1 py-1">
        <Tab to="/" label="Home" icon={House} active={pathname === "/"} />
        {NAV_MAIN.map((item) => (
          <Tab key={item.to} to={item.to} label={item.label} icon={item.icon} active={isActivePath(pathname, item.to)} />
        ))}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className={cn(TAB, moreActive ? "text-gold-bright" : "text-text-muted hover:text-text-secondary")}
            >
              <Ellipsis className={cn("size-5", moreActive && "text-gold")} aria-hidden="true" />
              More
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="end" className="min-w-40">
            {NAV_MORE.map(({ to, label, icon: Icon }) => (
              <DropdownMenuItem key={to} asChild>
                <Link
                  to={to}
                  className={cn("cursor-pointer", isActivePath(pathname, to) && "text-gold-bright [&_svg]:text-gold")}
                >
                  <Icon aria-hidden="true" />
                  {label}
                </Link>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </nav>
  );
}
