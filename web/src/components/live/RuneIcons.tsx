import { GameImage } from "@/components/common/GameImage";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { useRunes, type RuneInfo } from "@/lib/runes";

export interface RuneIconsProps {
  keystoneId: number | null | undefined;
  secondaryStyleId: number | null | undefined;
  /** Primary tree, only used for the accessible name ("Electrocute (Domination)"). */
  primaryStyleId?: number | null;
  size?: "sm" | "md";
  orientation?: "vertical" | "horizontal";
  className?: string;
}

const PX = {
  sm: { keystone: 16, tree: 12 },
  md: { keystone: 20, tree: 14 },
} as const;

function RuneSlot({
  rune,
  label,
  px,
  loading,
  className,
}: {
  rune: RuneInfo | undefined;
  label: string;
  px: number;
  loading: boolean;
  className?: string;
}) {
  if (!rune && loading) return <Skeleton className="shrink-0 rounded-full" style={{ width: px, height: px }} />;
  const fallback = (
    <span
      className="block size-full rounded-full border border-dashed border-border-strong"
      role="img"
      aria-label={label}
    />
  );
  return (
    <span
      title={label}
      className={cn("flex shrink-0 items-center justify-center overflow-hidden rounded-full", className)}
      style={{ width: px, height: px }}
    >
      {rune ? (
        <GameImage src={rune.icon} alt={label} width={px} height={px} className="size-full object-contain" fallback={fallback} />
      ) : (
        fallback
      )}
    </span>
  );
}

/** Keystone above the secondary tree (op.gg layout), sized to sit next to `SpellIcons`. */
export function RuneIcons({
  keystoneId,
  secondaryStyleId,
  primaryStyleId,
  size = "md",
  orientation = "vertical",
  className,
}: RuneIconsProps) {
  const runes = useRunes(Boolean(keystoneId || secondaryStyleId));
  const keystone = runes.info(keystoneId);
  const primary = runes.info(primaryStyleId);
  const secondary = runes.info(secondaryStyleId);
  const px = PX[size];

  const keystoneLabel = keystone
    ? primary
      ? `${keystone.name} (${primary.name})`
      : keystone.name
    : "Unknown keystone";
  const secondaryLabel = secondary ? `Secondary: ${secondary.name}` : "Unknown secondary tree";

  return (
    <div
      className={cn("flex items-center gap-0.5", orientation === "vertical" ? "flex-col" : "flex-row", className)}
      style={orientation === "vertical" ? { width: px.keystone } : undefined}
    >
      <RuneSlot rune={keystone} label={keystoneLabel} px={px.keystone} loading={runes.loading} className="bg-black/40" />
      <RuneSlot rune={secondary} label={secondaryLabel} px={px.tree} loading={runes.loading} className="p-px" />
    </div>
  );
}
