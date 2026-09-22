/**
 * Global search palette (⌘K / Ctrl+K / "/"). AppShell owns the open state and the shortcut;
 * this renders the dialog: live summoner search, recent visits, the tracked roster, page
 * navigation and a "Look up Name#TAG" fallback for players HexTrack has never seen.
 */
import { Fragment, useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Command as CommandPrimitive } from "cmdk";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  CornerDownLeft,
  History,
  Home,
  Loader2,
  Search,
  Trash2,
  Trophy,
  UserRoundSearch,
  X,
} from "lucide-react";

import { useRoster, useSearch } from "@/api/queries";
import type { RiotIdParts, RosterEntry, SummonerSearchResult } from "@/api/types";
import { Kbd } from "@/components/common/Kbd";
import { Badge } from "@/components/ui/badge";
import { CommandEmpty, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { formatShortDate, timeAgo } from "@/lib/format";
import { formatRiotId, parseRiotIdInput, summonerParams } from "@/lib/riotId";

import {
  clearRecentSearches,
  recentFromSearchResult,
  recentKey,
  recordRecentSearch,
  useRecentSearches,
  type RecentSummoner,
  type RecentSummonerInput,
} from "./recentSearches";
import { matchesRiotIdQuery, sameRiotId } from "./riotIdInput";
import { SummonerOption } from "./SummonerOption";
import { useDebouncedValue } from "./useDebouncedValue";
import { useRecordSummonerVisits } from "./useRecordSummonerVisits";

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface PageCommand {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
  to: "/" | "/leaderboard";
  keywords: readonly string[];
}

const PAGES: readonly PageCommand[] = [
  {
    id: "page:home",
    label: "Home",
    description: "Search, the squad and roster highlights",
    icon: Home,
    to: "/",
    keywords: ["home", "start", "squad", "highlights"],
  },
  {
    id: "page:leaderboard",
    label: "Leaderboard",
    description: "Season standings of the tracked roster",
    icon: Trophy,
    to: "/leaderboard",
    keywords: ["leaderboard", "ladder", "ranking", "standings", "roster", "season"],
  },
];

const SEARCH_LIMIT = 8;
const SEARCH_DEBOUNCE_MS = 120;
/** Roster rows shown with an empty query (all matches are shown while typing). */
const ROSTER_PREVIEW = 6;

type PaletteItem =
  | { kind: "lookup"; id: string; parts: RiotIdParts }
  | { kind: "summoner"; id: string; result: SummonerSearchResult }
  | { kind: "recent"; id: string; entry: RecentSummoner }
  | { kind: "roster"; id: string; entry: RosterEntry }
  | { kind: "page"; id: string; page: PageCommand }
  | { kind: "clear-recent"; id: string };

interface PaletteGroup {
  id: string;
  heading: string;
  items: PaletteItem[];
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  // Mounted for the whole session (AppShell renders it once), so visits are recorded even
  // while the dialog is closed.
  useRecordSummonerVisits();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="top-[8dvh] w-full translate-y-0 gap-0 overflow-hidden rounded-2xl p-0 sm:top-[14dvh] sm:max-w-xl"
      >
        <DialogTitle className="sr-only">Search summoners</DialogTitle>
        <DialogDescription className="sr-only">
          Search a Riot ID, jump to a tracked player or open a page. Use the arrow keys to move and Enter to open.
        </DialogDescription>
        {/* Only mounted while open, so roster and search queries don't run in the background. */}
        <PaletteBody onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const query = text.trim();
  const debounced = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  const searchEnabled = query.length >= 2 && debounced.length >= 2;
  const search = useSearch(searchEnabled ? debounced : "", SEARCH_LIMIT);
  const roster = useRoster();
  const recents = useRecentSearches();

  const results = useMemo(() => (searchEnabled && search.data ? search.data : []), [searchEnabled, search.data]);
  const searching = query.length >= 2 && (debounced !== query || search.isFetching);
  const searchFailed = searchEnabled && search.isError;

  const groups = useMemo<PaletteGroup[]>(() => {
    const seen = new Set<string>();
    const take = (gameName: string, tagLine: string) => {
      const key = recentKey(gameName, tagLine);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    };
    const out: PaletteGroup[] = [];
    const parsed = parseRiotIdInput(query);

    if (parsed) {
      const exact = results.some((r) => sameRiotId(parsed, { gameName: r.game_name, tagLine: r.tag_line }));
      if (!exact) {
        out.push({
          id: "lookup",
          heading: "Look up",
          items: [{ kind: "lookup", id: `lookup:${recentKey(parsed.gameName, parsed.tagLine)}`, parts: parsed }],
        });
      }
    }

    if (results.length > 0) {
      // Put an exact Riot ID match first, keep the server's order (tracked first) otherwise.
      const ordered = parsed
        ? [...results].sort(
            (a, b) =>
              Number(sameRiotId(parsed, { gameName: b.game_name, tagLine: b.tag_line })) -
              Number(sameRiotId(parsed, { gameName: a.game_name, tagLine: a.tag_line })),
          )
        : results;
      const items = ordered
        .filter((r) => take(r.game_name, r.tag_line))
        .map((result): PaletteItem => ({ kind: "summoner", id: `summoner:${result.puuid}`, result }));
      if (items.length) out.push({ id: "summoners", heading: "Summoners", items });
    }

    const recentItems = recents
      .filter((entry) => matchesRiotIdQuery(query, entry.gameName, entry.tagLine))
      .slice(0, query ? 4 : 5)
      .filter((entry) => take(entry.gameName, entry.tagLine))
      .map((entry): PaletteItem => ({
        kind: "recent",
        id: `recent:${recentKey(entry.gameName, entry.tagLine)}`,
        entry,
      }));
    if (recentItems.length) out.push({ id: "recent", heading: "Recent", items: recentItems });

    const rosterItems = [...(roster.data ?? [])]
      .sort((a, b) => a.game_name.localeCompare(b.game_name, undefined, { sensitivity: "base" }))
      .filter((entry) => matchesRiotIdQuery(query, entry.game_name, entry.tag_line))
      .filter((entry) => take(entry.game_name, entry.tag_line))
      .slice(0, query ? undefined : ROSTER_PREVIEW)
      .map((entry): PaletteItem => ({ kind: "roster", id: `roster:${entry.puuid}`, entry }));
    if (rosterItems.length) out.push({ id: "roster", heading: "Roster", items: rosterItems });

    const q = query.toLowerCase();
    const pageItems: PaletteItem[] = PAGES.filter(
      (page) => !q || page.label.toLowerCase().includes(q) || page.keywords.some((k) => k.startsWith(q)),
    ).map((page) => ({ kind: "page", id: page.id, page }));
    if (!query && recents.length > 0) pageItems.push({ kind: "clear-recent", id: "action:clear-recent" });
    if (pageItems.length) out.push({ id: "pages", heading: query ? "Pages" : "Go to", items: pageItems });

    return out;
  }, [query, results, recents, roster.data]);

  // Controlled selection: highlight the first item whenever the list changes, then follow
  // the user's arrow keys / pointer until it changes again.
  const values = groups.flatMap((group) => group.items.map((item) => item.id));
  const signature = values.join("\n");
  const [selection, setSelection] = useState({ signature: "", value: "" });
  const selectedValue =
    selection.signature === signature && values.includes(selection.value) ? selection.value : (values[0] ?? "");

  const goToSummoner = (parts: RiotIdParts, remember?: RecentSummonerInput) => {
    if (remember) recordRecentSearch(remember);
    onClose();
    void navigate({ to: "/summoner/$region/$riotId", params: summonerParams(parts.gameName, parts.tagLine) });
  };

  const runItem = (item: PaletteItem) => {
    switch (item.kind) {
      case "lookup":
        // Unknown players are recorded once their profile resolves (useRecordSummonerVisits).
        goToSummoner(item.parts);
        break;
      case "summoner":
        goToSummoner(
          { gameName: item.result.game_name, tagLine: item.result.tag_line },
          recentFromSearchResult(item.result),
        );
        break;
      case "recent":
        goToSummoner(item.entry, { gameName: item.entry.gameName, tagLine: item.entry.tagLine });
        break;
      case "roster":
        goToSummoner(
          { gameName: item.entry.game_name, tagLine: item.entry.tag_line },
          { gameName: item.entry.game_name, tagLine: item.entry.tag_line, profileIconId: item.entry.profile_icon_id },
        );
        break;
      case "page":
        onClose();
        void navigate({ to: item.page.to });
        break;
      case "clear-recent":
        clearRecentSearches();
        break;
    }
  };

  const showEmpty = !searching && !searchFailed;
  // Search progress / failure sits where the Summoners group appears (after "Look up").
  const statusRow =
    results.length > 0 ? null : searching ? (
      <div className="flex items-center gap-2 px-3 py-3 text-sm text-text-secondary" role="status">
        <Loader2 className="size-4 animate-spin text-text-muted" aria-hidden="true" />
        Searching summoners…
      </div>
    ) : searchFailed ? (
      <p className="px-3 py-3 text-sm text-text-secondary" role="status">
        Summoner search is unavailable right now. You can still look up a full Riot ID.
      </p>
    ) : null;
  const statusIndex = groups[0]?.id === "lookup" ? 1 : 0;

  return (
    <CommandPrimitive
      label="Search summoners"
      shouldFilter={false}
      loop
      value={selectedValue}
      onValueChange={(value) => setSelection({ signature, value })}
      className="flex w-full flex-col text-text"
    >
      <div className="flex h-14 items-center gap-3 border-b border-border px-4">
        <Search className="size-5 shrink-0 text-gold" aria-hidden="true" />
        <CommandPrimitive.Input
          value={text}
          onValueChange={setText}
          placeholder="Search a Riot ID…"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          maxLength={64}
          className="h-full min-w-0 flex-1 bg-transparent text-base text-text outline-none placeholder:text-text-muted focus-visible:outline-none"
        />
        {searching ? <Loader2 className="size-4 shrink-0 animate-spin text-text-muted" aria-hidden="true" /> : null}
        <button
          type="button"
          onClick={onClose}
          className="hidden shrink-0 rounded-md sm:inline-flex"
          aria-label="Close search"
        >
          <Kbd>Esc</Kbd>
        </button>
        <button
          type="button"
          onClick={onClose}
          className="-mr-1.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-text-secondary hover:bg-white/5 hover:text-text sm:hidden"
          aria-label="Close search"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>

      <CommandList className="max-h-[min(500px,62dvh)] px-1.5 py-1.5">
        {showEmpty ? (
          <CommandEmpty>
            <div className="flex flex-col items-center gap-1.5 px-6">
              <UserRoundSearch className="size-6 text-gold" aria-hidden="true" />
              <p className="font-medium text-text">No matches for “{query}”</p>
              <p className="text-text-secondary">
                Type the full Riot ID with its tag, like <span className="text-text">Name#NA1</span>, to look anyone up.
              </p>
            </div>
          </CommandEmpty>
        ) : null}

        {groups.map((group, index) => (
          <Fragment key={group.id}>
            {index === statusIndex ? statusRow : null}
            <CommandGroup heading={group.heading}>
              {group.items.map((item) => (
                <CommandItem
                  key={item.id}
                  value={item.id}
                  onSelect={() => runItem(item)}
                  className="group min-h-11 gap-3 px-2.5 py-1.5"
                >
                  <PaletteItemContent item={item} />
                </CommandItem>
              ))}
            </CommandGroup>
          </Fragment>
        ))}
        {statusIndex >= groups.length ? statusRow : null}
      </CommandList>

      <div className="flex items-center justify-between gap-3 border-t border-border bg-surface-1/40 px-4 py-2.5 text-[11px] text-text-muted">
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Kbd aria-hidden="true">↑</Kbd>
            <Kbd aria-hidden="true">↓</Kbd>
            <span>Navigate</span>
          </span>
          <span className="flex items-center gap-1">
            <Kbd aria-hidden="true">
              <CornerDownLeft className="size-3" />
            </Kbd>
            <span>Open</span>
          </span>
          <span className="hidden items-center gap-1 sm:flex">
            <Kbd aria-hidden="true">Esc</Kbd>
            <span>Close</span>
          </span>
        </span>
        <span className="truncate">
          Riot IDs look like <span className="font-medium text-text-secondary">Name#TAG</span>
        </span>
      </div>
    </CommandPrimitive>
  );
}

const SELECTED_ARROW =
  "size-4 shrink-0 text-text-muted opacity-0 transition-opacity group-data-[selected=true]:opacity-100";

function PaletteItemContent({ item }: { item: PaletteItem }) {
  switch (item.kind) {
    case "lookup":
      return (
        <>
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-gold/30 bg-gold/10">
            <UserRoundSearch className="size-4 text-gold" aria-hidden="true" />
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-text">
              Look up <span className="font-semibold">{formatRiotId(item.parts.gameName, item.parts.tagLine)}</span>
            </span>
            <span className="truncate text-xs text-text-muted">Loads their profile from Riot</span>
          </span>
          <ArrowRight className={SELECTED_ARROW} aria-hidden="true" />
        </>
      );
    case "summoner": {
      const r = item.result;
      const level = r.summoner_level !== null ? `Level ${r.summoner_level}` : null;
      return (
        <>
          <SummonerOption
            gameName={r.game_name}
            tagLine={r.tag_line}
            profileIconId={r.profile_icon_id}
            tier={r.solo_tier}
            rank={r.solo_rank}
            caption={level}
            trailing={
              r.is_tracked ? (
                <Badge variant="default" className="shrink-0">
                  Tracked
                </Badge>
              ) : null
            }
          />
          <ArrowRight className={SELECTED_ARROW} aria-hidden="true" />
        </>
      );
    }
    case "recent":
      return (
        <>
          <SummonerOption
            gameName={item.entry.gameName}
            tagLine={item.entry.tagLine}
            profileIconId={item.entry.profileIconId}
            tier={item.entry.soloTier}
            rank={item.entry.soloRank}
            caption={
              item.entry.visitedAt > 0 ? (
                <span className="inline-flex items-center gap-1">
                  <History className="size-3 text-text-muted" aria-hidden="true" />
                  Viewed {timeAgo(item.entry.visitedAt)}
                </span>
              ) : null
            }
          />
          <ArrowRight className={SELECTED_ARROW} aria-hidden="true" />
        </>
      );
    case "roster":
      return (
        <>
          <SummonerOption
            gameName={item.entry.game_name}
            tagLine={item.entry.tag_line}
            profileIconId={item.entry.profile_icon_id}
            caption={
              item.entry.tracked_since ? `Tracked since ${formatShortDate(item.entry.tracked_since)}` : "Tracked"
            }
          />
          <ArrowRight className={SELECTED_ARROW} aria-hidden="true" />
        </>
      );
    case "page": {
      const Icon = item.page.icon;
      return (
        <>
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border-strong bg-surface-3">
            <Icon className="size-4 text-gold" aria-hidden="true" />
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-text">{item.page.label}</span>
            <span className="truncate text-xs text-text-muted">{item.page.description}</span>
          </span>
          <ArrowRight className={SELECTED_ARROW} aria-hidden="true" />
        </>
      );
    }
    case "clear-recent":
      return (
        <>
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border-strong bg-surface-3">
            <Trash2 className="size-4 text-text-secondary" aria-hidden="true" />
          </span>
          <span className="truncate text-text-secondary">Clear recent searches</span>
        </>
      );
  }
}
