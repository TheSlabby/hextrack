import { Link, useRouter, type ErrorComponentProps } from "@tanstack/react-router";
import { Compass, Home } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Button } from "@/components/ui/button";

/** Shown for unknown URLs. */
export function NotFoundPage() {
  return (
    <GlowCard className="mx-auto mt-8 max-w-xl">
      <EmptyState
        icon={Compass}
        title="This page wandered into the fog of war"
        description="The link may be wrong or the page may have moved. Search for a summoner or head back home."
        action={
          <Button asChild>
            <Link to="/">
              <Home aria-hidden="true" />
              Back to home
            </Link>
          </Button>
        }
      />
    </GlowCard>
  );
}

/** Route-level error boundary. */
export function RouteErrorPage({ error, reset }: ErrorComponentProps) {
  const router = useRouter();
  return (
    <GlowCard className="mx-auto mt-8 max-w-xl">
      <ErrorState
        error={error}
        onRetry={() => {
          reset();
          void router.invalidate();
        }}
        action={
          <Button variant="ghost" size="sm" asChild>
            <Link to="/">Go home</Link>
          </Button>
        }
      />
    </GlowCard>
  );
}

/** Route transition indicator: a thin gold progress bar under the nav. */
export function RoutePending() {
  return (
    <div className="fixed inset-x-0 top-14 z-50 h-0.5 overflow-hidden" role="progressbar" aria-label="Loading page">
      <div className="h-full w-1/3 animate-indeterminate bg-gradient-to-r from-transparent via-gold to-transparent" />
    </div>
  );
}
