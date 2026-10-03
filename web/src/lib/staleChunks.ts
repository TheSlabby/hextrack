/**
 * After a deploy, a tab opened earlier still runs the old app, whose lazily loaded page chunks
 * (hash-named files in /assets) may no longer exist. Loading one fails, so the page would
 * error out. Instead, reload once to pick up the new version.
 */
const RELOADED_AT = "hextrack:chunk-reload-at";
/** Don't reload again within this window (a chunk that's really missing would loop). */
const GUARD_MS = 30_000;

/** True for the errors browsers raise when a dynamic import / module preload fails. */
export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? `${error.name} ${error.message}` : String(error ?? "");
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported|Unable to preload CSS|ChunkLoadError|Failed to fetch module/i.test(
    message,
  );
}

/** Reload the page once to load the current deploy; false if we already just did. */
export function reloadForNewVersion(): boolean {
  try {
    const last = Number(window.sessionStorage.getItem(RELOADED_AT) ?? 0);
    if (Date.now() - last < GUARD_MS) return false;
    window.sessionStorage.setItem(RELOADED_AT, String(Date.now()));
  } catch {
    // No sessionStorage: reload anyway; the guard just can't stop a loop, which is unlikely.
  }
  window.location.reload();
  return true;
}

/** Vite fires `vite:preloadError` when a lazy chunk (or its CSS) fails to load. */
export function installStaleChunkReload(): void {
  window.addEventListener("vite:preloadError", (event) => {
    if (reloadForNewVersion()) event.preventDefault();
  });
}
