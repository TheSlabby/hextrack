/**
 * The big Riot ID search field on the home page: an accessible combobox with live
 * suggestions, recent visits when empty, inline validation and "look up anyone" on Enter.
 */
import { useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ArrowRight, History, Loader2, Search, UserRoundSearch } from "lucide-react";

import { useSearch } from "@/api/queries";
import type { RiotIdParts, SummonerSearchResult } from "@/api/types";
import { Kbd } from "@/components/common/Kbd";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { formatRiotId, parseRiotIdInput, summonerParams } from "@/lib/riotId";

import {
  recentFromSearchResult,
  recentKey,
  recordRecentSearch,
  useRecentSearches,
  type RecentSummoner,
  type RecentSummonerInput,
} from "./recentSearches";
import { sameRiotId, validateRiotIdInput } from "./riotIdInput";
import { SummonerOption } from "./SummonerOption";
import { useDebouncedValue } from "./useDebouncedValue";

export interface RiotIdSearchProps {
  className?: string;
  /** Placeholder for the input. */
  placeholder?: string;
}

type Option =
  | { kind: "lookup"; id: string; parts: RiotIdParts }
  | { kind: "result"; id: string; result: SummonerSearchResult }
  | { kind: "recent"; id: string; entry: RecentSummoner };

const SUGGESTION_LIMIT = 6;
const RECENT_LIMIT = 5;

export function RiotIdSearch({ className, placeholder = "Search a Riot ID, e.g. Hexwalker#NA1" }: RiotIdSearchProps) {
  const navigate = useNavigate();
  const uid = useId();
  const inputId = `${uid}-input`;
  const listId = `${uid}-list`;
  const hintId = `${uid}-hint`;
  const inputRef = useRef<HTMLInputElement>(null);

  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = text.trim();
  const debounced = useDebouncedValue(query, 140);
  const searchEnabled = query.length >= 2 && debounced.length >= 2;
  const search = useSearch(searchEnabled ? debounced : "", SUGGESTION_LIMIT);
  const recents = useRecentSearches();
  const searching = query.length >= 2 && (debounced !== query || search.isFetching);

  const options = useMemo<Option[]>(() => {
    if (!query) {
      return recents
        .slice(0, RECENT_LIMIT)
        .map((entry) => ({ kind: "recent", id: `recent-${recentKey(entry.gameName, entry.tagLine)}`, entry }));
    }
    const results = searchEnabled && search.data ? search.data : [];
    const parsed = parseRiotIdInput(query);
    const out: Option[] = [];
    if (parsed && !results.some((r) => sameRiotId(parsed, { gameName: r.game_name, tagLine: r.tag_line }))) {
      out.push({ kind: "lookup", id: "lookup", parts: parsed });
    }
    const ordered = parsed
      ? [...results].sort(
          (a, b) =>
            Number(sameRiotId(parsed, { gameName: b.game_name, tagLine: b.tag_line })) -
            Number(sameRiotId(parsed, { gameName: a.game_name, tagLine: a.tag_line })),
        )
      : results;
    for (const result of ordered) out.push({ kind: "result", id: `result-${result.puuid}`, result });
    return out;
  }, [query, recents, searchEnabled, search.data]);

  const open = focused && !dismissed && options.length > 0;

  // Active option: resets whenever the option list changes (first option when typing,
  // nothing for the recent list so Enter on an empty box shows the hint instead).
  const signature = `${query ? "q" : "empty"}|${options.map((o) => o.id).join(",")}`;
  const [active, setActive] = useState({ signature: "", index: -1 });
  const defaultIndex = query && options.length > 0 ? 0 : -1;
  const activeIndex = active.signature === signature ? active.index : defaultIndex;
  const setActiveIndex = (index: number) => setActive({ signature, index });
  const optionId = (index: number) => `${listId}-${index}`;

  const go = (parts: RiotIdParts, remember?: RecentSummonerInput) => {
    if (remember) recordRecentSearch(remember);
    setText("");
    setError(null);
    setDismissed(true);
    inputRef.current?.blur();
    void navigate({ to: "/summoner/$region/$riotId", params: summonerParams(parts.gameName, parts.tagLine) });
  };

  const choose = (option: Option) => {
    switch (option.kind) {
      case "lookup":
        // Recorded once the profile resolves (see useRecordSummonerVisits).
        go(option.parts);
        break;
      case "result":
        go(
          { gameName: option.result.game_name, tagLine: option.result.tag_line },
          recentFromSearchResult(option.result),
        );
        break;
      case "recent":
        go(option.entry, { gameName: option.entry.gameName, tagLine: option.entry.tagLine });
        break;
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const highlighted = open && activeIndex >= 0 ? options[activeIndex] : undefined;
    if (highlighted) {
      choose(highlighted);
      return;
    }
    const validation = validateRiotIdInput(text);
    if (validation.ok) {
      go(validation.parts);
      return;
    }
    // A bare name that matches known players: take the best suggestion.
    const first = options.find((o) => o.kind === "result");
    if (query && first) {
      choose(first);
      return;
    }
    setError(validation.message);
    inputRef.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case "ArrowDown": {
        event.preventDefault();
        if (!open) {
          setDismissed(false);
          return;
        }
        setActiveIndex(activeIndex + 1 >= options.length ? 0 : activeIndex + 1);
        break;
      }
      case "ArrowUp": {
        if (!open) return;
        event.preventDefault();
        setActiveIndex(activeIndex <= 0 ? options.length - 1 : activeIndex - 1);
        break;
      }
      case "Escape": {
        if (open) {
          event.preventDefault();
          setDismissed(true);
        } else if (text) {
          event.preventDefault();
          setText("");
          setError(null);
        }
        break;
      }
      case "Tab":
        setDismissed(true);
        break;
    }
  };

  const hasRecentList = !query && open;
  const statusText = !open
    ? ""
    : hasRecentList
      ? `${options.length} recent ${options.length === 1 ? "search" : "searches"}. Use the arrow keys to choose.`
      : `${options.length} ${options.length === 1 ? "suggestion" : "suggestions"}. Use the arrow keys to choose.`;

  return (
    <form
      role="search"
      aria-label="Find a summoner"
      onSubmit={submit}
      className={cn("relative w-full text-left", className)}
      noValidate
    >
      <label htmlFor={inputId} className="sr-only">
        Riot ID
      </label>
      <div className="relative">
        <div
          className={cn(
            "group relative flex h-14 items-center gap-2 rounded-2xl border bg-surface-1/85 pr-1.5 pl-4 shadow-[var(--shadow-raised)] backdrop-blur-md transition-[border-color,box-shadow] duration-200 sm:h-16 sm:pr-2 sm:pl-5",
            error
              ? "border-loss/60 shadow-[var(--shadow-raised),0_0_0_4px_rgba(255,93,108,0.12)]"
              : "border-border-strong hover:border-white/20 focus-within:border-gold/60 focus-within:shadow-[var(--shadow-raised),0_0_0_4px_rgba(200,170,110,0.14)]",
          )}
        >
          <Search className="size-5 shrink-0 text-gold" aria-hidden="true" />
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={open && activeIndex >= 0 ? optionId(activeIndex) : undefined}
            aria-invalid={error ? true : undefined}
            aria-describedby={hintId}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            enterKeyHint="search"
            maxLength={64}
            placeholder={placeholder}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setDismissed(false);
              if (error) setError(null);
            }}
            onFocus={() => {
              setFocused(true);
              setDismissed(false);
            }}
            onBlur={() => setFocused(false)}
            onKeyDown={onKeyDown}
            className="h-full min-w-0 flex-1 bg-transparent text-base text-text outline-none placeholder:text-text-muted focus-visible:outline-none sm:text-lg"
          />
          {searching ? <Loader2 className="size-4 shrink-0 animate-spin text-text-muted" aria-hidden="true" /> : null}
          <Button type="submit" size="lg" className="h-11 rounded-xl px-4 sm:h-12 sm:px-5" aria-label="Search">
            <span className="hidden sm:inline">Search</span>
            <ArrowRight className="size-4" aria-hidden="true" />
          </Button>
        </div>

        <div
          hidden={!open}
          className="surface-raised absolute inset-x-0 top-full z-30 mt-2 max-h-[min(420px,60dvh)] overflow-y-auto rounded-xl p-1.5 scrollbar-thin"
          onMouseDown={(event) => event.preventDefault()}
        >
          {hasRecentList ? (
            <div aria-hidden="true" className="label-caps px-2.5 pt-1.5 pb-1">
              Recent
            </div>
          ) : null}
          <ul id={listId} role="listbox" aria-label={hasRecentList ? "Recent searches" : "Suggestions"}>
            {options.map((option, index) => (
              <li
                key={option.id}
                id={optionId(index)}
                role="option"
                aria-selected={index === activeIndex}
                data-active={index === activeIndex ? "" : undefined}
                onMouseMove={() => {
                  if (index !== activeIndex) setActiveIndex(index);
                }}
                onClick={() => choose(option)}
                className="group flex min-h-12 cursor-pointer items-center gap-3 rounded-lg px-2.5 py-1.5 text-sm data-[active]:bg-white/[0.06]"
              >
                <OptionContent option={option} />
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p
        id={hintId}
        className={cn(
          "mt-2.5 flex min-h-5 items-center justify-center gap-1.5 text-center text-sm",
          error ? "text-loss" : "text-text-muted",
        )}
        aria-live="polite"
      >
        {error ?? (
          <>
            Any Riot ID works; new players load from Riot.
            <span className="hidden items-center gap-1 sm:inline-flex">
              Press <Kbd>/</Kbd> anywhere to search.
            </span>
          </>
        )}
      </p>
      <span className="sr-only" role="status" aria-live="polite">
        {statusText}
      </span>
    </form>
  );
}

const ACTIVE_ARROW = "size-4 shrink-0 text-text-muted opacity-0 transition-opacity group-data-[active]:opacity-100";

function OptionContent({ option }: { option: Option }) {
  switch (option.kind) {
    case "lookup":
      return (
        <>
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-gold/30 bg-gold/10">
            <UserRoundSearch className="size-4 text-gold" aria-hidden="true" />
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-text">
              Look up <span className="font-semibold">{formatRiotId(option.parts.gameName, option.parts.tagLine)}</span>
            </span>
            <span className="truncate text-xs text-text-muted">Loads their profile from Riot</span>
          </span>
          <ArrowRight className={ACTIVE_ARROW} aria-hidden="true" />
        </>
      );
    case "result": {
      const r = option.result;
      return (
        <>
          <SummonerOption
            gameName={r.game_name}
            tagLine={r.tag_line}
            profileIconId={r.profile_icon_id}
            tier={r.solo_tier}
            rank={r.solo_rank}
            caption={r.summoner_level !== null ? `Level ${r.summoner_level}` : null}
            trailing={r.is_tracked ? <Badge className="shrink-0">Tracked</Badge> : null}
          />
          <ArrowRight className={ACTIVE_ARROW} aria-hidden="true" />
        </>
      );
    }
    case "recent":
      return (
        <>
          <SummonerOption
            gameName={option.entry.gameName}
            tagLine={option.entry.tagLine}
            profileIconId={option.entry.profileIconId}
            tier={option.entry.soloTier}
            rank={option.entry.soloRank}
            caption={
              option.entry.visitedAt > 0 ? (
                <span className="inline-flex items-center gap-1">
                  <History className="size-3" aria-hidden="true" />
                  Viewed {timeAgo(option.entry.visitedAt)}
                </span>
              ) : null
            }
          />
          <ArrowRight className={ACTIVE_ARROW} aria-hidden="true" />
        </>
      );
  }
}
