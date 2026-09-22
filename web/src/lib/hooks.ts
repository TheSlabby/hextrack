/** Small app-wide React hooks: page title and media queries. */
import { useCallback, useEffect, useSyncExternalStore } from "react";

export const SITE_NAME = "HexTrack";

/** Join title parts with the app-wide " · " separator and append the site name. */
export function pageTitle(...parts: ReadonlyArray<string | null | undefined | false>): string {
  return [...parts.filter((part): part is string => Boolean(part)), SITE_NAME].join(" · ");
}

/** Set `document.title` while mounted; restores the previous title on unmount. */
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
}

/** Live `matchMedia(query).matches` (false without matchMedia, e.g. during prerender). */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  const getSnapshot = () =>
    typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false;
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
