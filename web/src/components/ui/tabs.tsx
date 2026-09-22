import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Tabs as TabsPrimitive } from "radix-ui";

import { cn } from "@/lib/cn";

function Tabs({ className, orientation = "horizontal", ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      orientation={orientation}
      className={cn("group/tabs flex gap-4 data-[orientation=horizontal]:flex-col", className)}
      {...props}
    />
  );
}

const tabsListVariants = cva(
  "group/tabs-list inline-flex w-fit max-w-full items-center overflow-x-auto scrollbar-thin text-text-secondary group-data-[orientation=vertical]/tabs:h-fit group-data-[orientation=vertical]/tabs:flex-col",
  {
    variants: {
      variant: {
        /** Segmented pill control on a surface. */
        default: "h-10 gap-1 rounded-xl border border-border bg-surface-1/80 p-1",
        /** Underlined page tabs (summoner page sections). */
        line: "h-11 gap-5 border-b border-border bg-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function TabsList({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-full shrink-0 items-center justify-center gap-1.5 text-sm font-medium whitespace-nowrap transition-colors duration-150",
        "hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold disabled:pointer-events-none disabled:opacity-45",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        // segmented
        "group-data-[variant=default]/tabs-list:rounded-lg group-data-[variant=default]/tabs-list:px-3",
        "group-data-[variant=default]/tabs-list:data-[state=active]:bg-surface-3 group-data-[variant=default]/tabs-list:data-[state=active]:text-text group-data-[variant=default]/tabs-list:data-[state=active]:shadow-[0_1px_0_0_rgba(255,255,255,0.06)_inset,0_2px_8px_-2px_rgba(0,0,0,0.6)]",
        // line
        "group-data-[variant=line]/tabs-list:px-0.5 group-data-[variant=line]/tabs-list:data-[state=active]:text-gold-bright",
        "after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-gold after:opacity-0 after:transition-opacity group-data-[variant=line]/tabs-list:data-[state=active]:after:opacity-100",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content data-slot="tabs-content" className={cn("flex-1 outline-none", className)} {...props} />;
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants };
