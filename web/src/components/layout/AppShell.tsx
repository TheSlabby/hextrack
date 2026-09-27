import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronDown, Search } from "lucide-react";

import { Kbd } from "@/components/common/Kbd";
import { MotionMemory } from "@/components/common/Motion";
import { Logo } from "@/components/common/Logo";
import { CommandPalette } from "@/components/search/CommandPalette";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/cn";

import { Background } from "./Background";
import { Footer } from "./Footer";
import { MobileTabBar } from "./MobileTabBar";
import { isActivePath, NAV_MAIN, NAV_MORE } from "./nav";
import { StatusPill } from "./StatusPill";

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

const NAV_LINK =
  "inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-text-secondary transition-colors hover:bg-white/5 hover:text-text";

/** The overflow pages as a dropdown; the trigger lights up while one of them is open. */
function MoreMenu({ pathname }: { pathname: string }) {
  const active = NAV_MORE.some((item) => isActivePath(pathname, item.to));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(NAV_LINK, "xl:hidden", active && "bg-white/5 text-gold-bright")}
          aria-label="More pages"
        >
          More
          <ChevronDown className="size-3.5 opacity-70" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-40">
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
  );
}

/** App frame: sticky glass nav (logo, links, search, status), page content, footer and, on phones, a bottom tab bar. */
export function AppShell({ children }: { children: ReactNode }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Entrance motion plays once per page: sections that re-mount inside it (tab panels) render
  // settled, and a new path starts a fresh memory.
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const openPalette = useCallback(() => setPaletteOpen(true), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !isTypingTarget(event.target)) {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="relative flex min-h-dvh flex-col pb-[calc(3.75rem+env(safe-area-inset-bottom))] sm:pb-0">
      <Background />
      <a
        href="#main"
        className="sr-only z-[60] rounded-md bg-gold px-3 py-2 text-sm font-semibold text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>

      <header className="glass sticky top-0 z-40 border-b border-border">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4 sm:gap-4 sm:px-6 lg:px-8">
          <Link to="/" className="shrink-0 rounded-lg" aria-label="HexTrack home">
            <Logo />
          </Link>

          <nav aria-label="Main" className="hidden items-center gap-1 sm:flex">
            {[...NAV_MAIN, ...NAV_MORE].map(({ to, label, icon: Icon }) => {
              const overflow = NAV_MORE.some((item) => item.to === to);
              return (
                <Link
                  key={to}
                  to={to}
                  className={cn(NAV_LINK, overflow && "hidden xl:inline-flex")}
                  activeProps={{ className: cn(NAV_LINK, overflow && "hidden xl:inline-flex", "bg-white/5 text-gold-bright") }}
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </Link>
              );
            })}
            <MoreMenu pathname={pathname} />
          </nav>

          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            <button
              type="button"
              onClick={openPalette}
              className="group hidden h-9 w-44 items-center gap-2 rounded-lg border border-border-strong bg-surface-1/70 px-3 text-sm text-text-muted transition-colors hover:border-white/20 hover:text-text-secondary md:flex lg:w-72"
              aria-label="Search players and champions"
              aria-keyshortcuts={IS_MAC ? "Meta+K /" : "Control+K /"}
            >
              <Search className="size-4 text-gold" aria-hidden="true" />
              <span className="flex-1 truncate text-left">Riot ID or champion…</span>
              <span className="hidden items-center gap-0.5 lg:flex">
                <Kbd>{IS_MAC ? "⌘" : "Ctrl"}</Kbd>
                <Kbd>K</Kbd>
              </span>
            </button>
            <Button variant="ghost" size="icon" className="md:hidden" onClick={openPalette} aria-label="Search players and champions">
              <Search className="text-gold" />
            </Button>
            <StatusPill className="hidden lg:inline-flex" />
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 pt-6 pb-10 sm:px-6 sm:pt-8 lg:px-8">
        <MotionMemory scope={pathname}>{children}</MotionMemory>
      </main>

      <Footer />
      <MobileTabBar pathname={pathname} />
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
