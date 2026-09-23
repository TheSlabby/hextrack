import { Link } from "@tanstack/react-router";

import { useMeta } from "@/api/queries";
import { LogoMark } from "@/components/common/Logo";
import { formatDate } from "@/lib/format";
import { modelVersionDate } from "@/lib/score";

const RIOT_LEGAL =
  "HexTrack isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.";

export function Footer() {
  const { data: meta } = useMeta();
  // Version ids ("20260922-170745") say nothing to a player; the date does, and the id is
  // still there on hover for anyone debugging.
  const trainedAt = meta ? (meta.model_trained_at ?? modelVersionDate(meta.model_version)) : null;
  return (
    <footer className="mt-16 border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm text-text-secondary">
            <LogoMark size={18} />
            <span className="font-display font-semibold text-text">HexTrack</span>
            <span className="text-text-muted">· League stats with an AI Score</span>
          </div>
          <nav aria-label="Footer" className="flex items-center gap-4 text-sm text-text-secondary">
            <Link to="/" className="rounded-sm hover:text-text">
              Home
            </Link>
            <Link to="/leaderboard" className="rounded-sm hover:text-text">
              Leaderboard
            </Link>
            <Link to="/squad" className="rounded-sm hover:text-text">
              Squad
            </Link>
            <Link to="/records" className="rounded-sm hover:text-text">
              Records
            </Link>
            <a href="/api/docs" className="rounded-sm hover:text-text">
              API
            </a>
          </nav>
        </div>
        <p className="max-w-4xl text-xs leading-relaxed text-text-muted">{RIOT_LEGAL}</p>
        {meta ? (
          <p className="text-xs text-text-muted tabular-nums" title={meta.model_version ?? undefined}>
            Data Dragon {meta.ddragon_version} · {meta.platform.toUpperCase()}
            {trainedAt ? ` · AI model trained ${formatDate(trainedAt)}` : ""}
          </p>
        ) : null}
      </div>
    </footer>
  );
}
