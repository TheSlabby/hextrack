import type * as React from "react";
import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon } from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

/** App-wide toast host, themed to the Hextech night palette (dark only). */
function Toaster(props: ToasterProps) {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4 text-score-a" />,
        info: <InfoIcon className="size-4 text-cyan" />,
        warning: <TriangleAlertIcon className="size-4 text-score-c" />,
        error: <OctagonXIcon className="size-4 text-loss" />,
        loading: <Loader2Icon className="size-4 animate-spin text-gold" />,
      }}
      toastOptions={{
        classNames: {
          toast: "!font-sans !shadow-[var(--shadow-raised)]",
          title: "!text-text !font-semibold",
          description: "!text-text-secondary",
          actionButton: "!bg-gold !text-primary-foreground",
          cancelButton: "!bg-surface-3 !text-text-secondary",
        },
      }}
      style={
        {
          "--normal-bg": "var(--color-surface-2)",
          "--normal-text": "var(--color-text)",
          "--normal-border": "var(--color-border-strong)",
          "--border-radius": "var(--radius-xl)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
}

export { Toaster };
