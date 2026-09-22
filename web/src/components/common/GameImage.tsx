import { useState, type ImgHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface GameImageProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, "src" | "onError"> {
  /** One URL, or candidates tried in order (e.g. this patch's asset, then the newest one). */
  src: string | readonly string[] | null | undefined;
  alt: string;
  /** Rendered instead of the <img> when every URL is empty or fails to load. */
  fallback?: ReactNode;
}

/**
 * Lazy Data Dragon image that falls through its candidate URLs and then to `fallback`, so a
 * missing asset never shows the browser's broken-image glyph.
 */
export function GameImage({ src, alt, fallback = null, className, loading = "lazy", ...rest }: GameImageProps) {
  const [failed, setFailed] = useState<readonly string[]>([]);
  const sources = (typeof src === "string" ? [src] : (src ?? [])).filter(Boolean);
  const current = sources.find((url) => !failed.includes(url));
  if (!current) return <>{fallback}</>;
  return (
    <img
      key={current}
      src={current}
      alt={alt}
      loading={loading}
      decoding="async"
      draggable={false}
      onError={() => setFailed((urls) => (urls.includes(current) ? urls : [...urls, current]))}
      className={cn("block select-none", className)}
      {...rest}
    />
  );
}
