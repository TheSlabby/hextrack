/**
 * "Viewing as": which roster player this browser belongs to, remembered in localStorage (there
 * are no accounts). Used by the champion page's "Your games" card; any page may read it.
 */
import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "hextrack:me";
const EVENT = "hextrack:me-change";

function read(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function subscribe(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) onChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(EVENT, onChange);
  };
}

/** The remembered player's puuid (null if none) and a setter (null forgets). */
export function useMe(): [string | null, (puuid: string | null) => void] {
  const me = useSyncExternalStore(subscribe, read, () => null);
  const setMe = useCallback((puuid: string | null) => {
    try {
      if (puuid) window.localStorage.setItem(STORAGE_KEY, puuid);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Private mode / blocked storage: the choice just doesn't stick.
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [me, setMe];
}
