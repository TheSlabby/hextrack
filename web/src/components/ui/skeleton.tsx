import * as React from "react";

import { cn } from "@/lib/cn";

/** Shimmering placeholder block. Size it exactly like the content it replaces. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="skeleton" aria-hidden="true" className={cn("shimmer rounded-md", className)} {...props} />;
}

export { Skeleton };
