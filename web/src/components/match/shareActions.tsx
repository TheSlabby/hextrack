/**
 * What the share buttons do with a rendered card PNG: copy it (with a preview toast), download
 * it, or hand it to the phone's share sheet. Shared by the match recap and the champion card.
 */
import { toast } from "sonner";

import { errorMessage } from "@/api/client";

import { copyImage, downloadBlob } from "./shareRecap";

/** Whether the phone share sheet can take a PNG (touch devices only; desktops copy instead). */
export function canShareFiles(): boolean {
  return (
    typeof navigator.canShare === "function" &&
    window.matchMedia("(pointer: coarse)").matches &&
    navigator.canShare({ files: [new File([], "recap.png", { type: "image/png" })] })
  );
}

function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("Couldn't read the image"));
    reader.readAsDataURL(blob);
  });
}

export interface CopyToastOptions {
  /** Success toast title, e.g. "Recap copied. Paste it into Discord." (read once the copy is done). */
  message: string | (() => string);
  /** Alt text of the preview image in the toast (read once the copy is done). */
  alt: () => string;
  /** When the browser blocks the copy: guidance, and an optional button in the toast (e.g. Download). */
  blocked?: { description: string; fallback?: { label: string; run: () => void } };
}

/**
 * Copies the PNG and toasts the result, with a small preview so it's clear what will be pasted.
 * Call it synchronously in the click handler: `copyImage` hands the clipboard a `Promise<Blob>`
 * right away, because Safari drops clipboard writes made after an await. Resolves true on success.
 */
export function copyWithToast(blob: Promise<Blob>, { message, alt, blocked }: CopyToastOptions): Promise<boolean> {
  return copyImage(blob).then(
    async () => {
      const src = await blob.then(toDataUrl).catch(() => null);
      toast.success(typeof message === "function" ? message() : message, {
        description: src ? (
          <img src={src} alt={alt()} className="mt-2 aspect-[16/9] w-full rounded-md border border-border-strong" />
        ) : undefined,
      });
      return true;
    },
    async () => {
      // Either the image couldn't be made (data or render failed) or the browser refused the write.
      const failure = await blob.then(
        () => null,
        (error: unknown) => error,
      );
      if (failure !== null) {
        toast.error("Couldn't create the image", { description: errorMessage(failure) });
      } else {
        toast.error("Couldn't copy the image", {
          description: blocked?.description ?? "Your browser blocked it. Use Download instead.",
          action: blocked?.fallback ? { label: blocked.fallback.label, onClick: blocked.fallback.run } : undefined,
        });
      }
      return false;
    },
  );
}

/** Downloads the PNG once it's ready; toasts `failureTitle` if it couldn't be made. */
export function downloadWithToast(blob: Promise<Blob>, filename: string | (() => string), failureTitle: string): Promise<void> {
  return blob.then(
    (b) => downloadBlob(b, typeof filename === "function" ? filename() : filename),
    (error: unknown) => void toast.error(failureTitle, { description: errorMessage(error) }),
  );
}

/** Opens the share sheet with the PNG. A cancelled sheet is not an error. */
export function shareWithToast(blob: Promise<Blob>, filename: string | (() => string), title: string | (() => string)): Promise<void> {
  return blob
    .then((b) =>
      navigator.share({
        files: [new File([b], typeof filename === "function" ? filename() : filename, { type: "image/png" })],
        title: typeof title === "function" ? title() : title,
      }),
    )
    .catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      toast.error("Couldn't share the image", { description: "Use Download instead." });
    });
}
