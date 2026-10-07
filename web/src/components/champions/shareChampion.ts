/**
 * The shareable champion card: a roster player's season on one champion ("<Player>'s <Champion>
 * this season") next to how everyone plays it. `buildChampionCard` picks the facts and
 * `renderChampionCardPng` draws the 1200x675 PNG in the match recap's visual language, with the
 * recap's canvas helpers. No React here.
 */
import type { ChampionPlayer, ChampionTier, LeaderboardQueue } from "@/api/types";
import { championDisplayName } from "@/lib/champions";
import { buildDdragon, ddragonVersionForPatch, type DdragonUrls } from "@/lib/ddragon";
import type { RuneCatalog } from "@/lib/runes";
import {
  formatAvgKdaLine,
  formatCompact,
  formatDecimal,
  formatKdaRatio,
  formatPercent,
  formatShortDate,
  formatSigned,
  plural,
} from "@/lib/format";
import { POSITION_LABELS, POSITION_LONG_LABELS } from "@/lib/positions";
import { AI_AVERAGE_NOTE, AI_SCORE_RESULT_NOTE, averageOffset, toScore100 } from "@/lib/score";

import {
  C,
  DISPLAY,
  OUTCOME_COLOR,
  RECAP_WIDTH,
  SANS,
  drawBackdrop,
  drawBadge,
  drawEyebrow,
  drawFooter,
  drawKda,
  drawRing,
  fit,
  fitSize,
  loadFonts,
  loadImage,
  roundRect,
  runs,
  toImage,
  type RecapBadge,
} from "../match/shareRecap";

export interface ChampionCardBestGame {
  kills: number;
  deaths: number;
  assists: number;
  /** 0..100, or null when that game isn't scored. */
  score: number | null;
  /** "AI Score 96 · Win · Sep 21". */
  caption: string;
  /** "Best game: 12/2/9, AI Score 96". */
  line: string;
}

export interface ChampionCard {
  /** Data Dragon key (splash, filename). */
  championKey: string;
  champion: string;
  /** Riot game name and tag, drawn separately. */
  gameName: string;
  tagLine: string | null;
  playerName: string;
  /** "Walker's Jinx this season" (share sheet title). */
  title: string;
  /** "Ranked Solo/Duo  ·  Bot lane". */
  meta: string;
  /** The champion's tier in the player's main role ("S tier in Bot"), when ranked. */
  tier: { tier: ChampionTier; label: string } | null;
  /** "54%", or null with no games. */
  winRate: string | null;
  winRateColor: string;
  /** "14W 9L" / "No games yet". */
  record: string;
  /** "23 games". */
  gamesLabel: string;
  /** "vs 51% for all Jinx players" (or a plain caption without comparison data). */
  field: string;
  /** "6.2 / 4.1 / 8.7  ·  3.63 KDA  ·  8.4 CS/min  ·  21.3K damage". */
  statLine: string;
  /** "#1 Jinx player in the squad" / "#2 of 4 Jinx players in the squad". */
  squad: RecapBadge | null;
  /** Average AI Score 0..100: a plain number, never graded. */
  avgScore: number | null;
  /** "+4 vs a coin flip". */
  avgOffset: string | null;
  best: ChampionCardBestGame | null;
  /** The whole card as one sentence, for alt text. */
  alt: string;
}

const QUEUE_WORD: Readonly<Record<LeaderboardQueue, string>> = {
  all: "Ranked",
  solo: "Ranked Solo/Duo",
  flex: "Ranked Flex",
};

function squadBadge(player: ChampionPlayer, champion: string): RecapBadge | null {
  const { squad_rank: rank, squad_players: count } = player;
  if (rank == null || count < 1) return null;
  if (count === 1) return { label: `The squad's only ${champion} player`, kind: "rank" };
  if (rank === 1) return { label: `#1 ${champion} player in the squad`, kind: "rank" };
  return { label: `#${rank} of ${count} ${champion} players in the squad`, kind: "highlight" };
}

function tierBadge(player: ChampionPlayer, tier: ChampionTier | null): ChampionCard["tier"] {
  if (!tier) return null;
  const role = player.main_position === "UNKNOWN" ? null : POSITION_LABELS[player.main_position];
  return { tier, label: role ? `${tier} tier in ${role}` : `${tier} tier` };
}

/** Win rate colour, with the champion page's thresholds (`winRateTone`): blue ≥ 53%, red ≤ 47%. */
function winRateColor(rate: number | null): string {
  if (rate === null) return C.secondary;
  if (rate >= 0.53) return OUTCOME_COLOR.win;
  if (rate <= 0.47) return OUTCOME_COLOR.loss;
  return C.text;
}

export function buildChampionCard(player: ChampionPlayer, tier: ChampionTier | null): ChampionCard {
  const champion = championDisplayName(player.champion_name);
  const gameName = player.game_name ?? "Squad player";
  const tagLine = player.game_name ? player.tag_line : null;
  const playerName = tagLine ? `${gameName}#${tagLine}` : gameName;
  const hasGames = player.games > 0;
  const winRate = hasGames && player.win_rate != null ? player.win_rate : null;
  const position = player.main_position === "UNKNOWN" ? null : POSITION_LONG_LABELS[player.main_position];
  const meta = [QUEUE_WORD[player.queue], position].filter(Boolean).join("  ·  ");

  const field =
    hasGames && player.field_win_rate != null
      ? `vs ${formatPercent(player.field_win_rate)} for all ${champion} players`
      : hasGames
        ? "win rate"
        : `on ${champion} in ${QUEUE_WORD[player.queue].toLowerCase()} this season`;
  const statLine = hasGames
    ? [
        formatAvgKdaLine(player.avg_kills, player.avg_deaths, player.avg_assists),
        `${formatKdaRatio(player.kda, player.avg_deaths)} KDA`,
        `${formatDecimal(player.cs_per_min)} CS/min`,
        `${formatCompact(player.avg_damage)} damage`,
      ].join("  ·  ")
    : "";

  const avgScore = player.avg_ai_score == null ? null : toScore100(player.avg_ai_score);
  const offset = player.avg_ai_score == null ? null : averageOffset(player.avg_ai_score);
  const avgOffset = offset === null ? null : offset === 0 ? "Right on a coin flip" : `${formatSigned(offset)} vs a coin flip`;

  const g = player.best_game;
  const bestScore = g?.ai_score == null ? null : toScore100(g.ai_score);
  const best: ChampionCardBestGame | null = g
    ? {
        kills: g.kills,
        deaths: g.deaths,
        assists: g.assists,
        score: bestScore,
        caption: [bestScore !== null ? `Hex Score ${bestScore}` : null, g.win ? "Win" : "Loss", formatShortDate(g.game_start)]
          .filter(Boolean)
          .join("  ·  "),
        line: `Best game: ${g.kills}/${g.deaths}/${g.assists}${bestScore !== null ? `, Hex Score ${bestScore}` : ""}`,
      }
    : null;

  const card: Omit<ChampionCard, "alt"> = {
    championKey: player.champion_name,
    champion,
    gameName,
    tagLine,
    playerName,
    title: `${gameName}'s ${champion} this season`,
    meta,
    tier: tierBadge(player, tier),
    winRate: winRate === null ? null : formatPercent(winRate),
    winRateColor: winRateColor(winRate),
    record: hasGames ? `${player.wins}W ${player.games - player.wins}L` : "No games yet",
    gamesLabel: hasGames ? plural(player.games, "game") : "",
    field,
    statLine,
    squad: squadBadge(player, champion),
    avgScore,
    avgOffset,
    best,
  };
  const alt = [
    `${playerName}'s ${champion} this season, ${QUEUE_WORD[player.queue].toLowerCase()}`,
    card.tier ? `${champion} is ${card.tier.label} right now` : null,
    hasGames ? `${card.record} in ${card.gamesLabel}, ${card.winRate ?? "no"} win rate ${field}` : "No games yet",
    statLine.replaceAll("  ·  ", ", "),
    card.squad?.label,
    avgScore !== null ? `Average Hex Score ${avgScore}, ${avgOffset}` : null,
    best?.line,
  ]
    .filter(Boolean)
    .join(". ");
  return { ...card, alt };
}

// --- rendering ------------------------------------------------------------------------------

/** Image URLs for the card. Game assets list URLs to try in turn (the games' patch first, then newer). */
export interface ChampionCardArt {
  splash: string | null;
  /** Core items in build order. */
  items: ReadonlyArray<readonly string[]>;
  keystone: string | null;
  secondaryTree: string | null;
  spells: ReadonlyArray<readonly string[]>;
}

export interface ChampionCardArtOptions {
  /** Data Dragon CDN and newest version (from `useDdragon()`: `cdn`, `latest.version`). */
  cdn: string;
  latestVersion: string;
  /** Rune catalogue at a Data Dragon version (the button passes a cached `runeDataQuery` fetch). */
  runeCatalog: (version: string) => Promise<RuneCatalog | null>;
}

/**
 * Icon URLs for the card. Items and spells are tried at the patch of their newest game on the
 * champion, then their best game's, then the newest version: removed items 403 on newer versions.
 * Runes come from the first of those catalogues that knows the keystone. Champion splash: newest.
 */
export async function championCardArt(
  player: ChampionPlayer,
  { cdn, latestVersion, runeCatalog }: ChampionCardArtOptions,
): Promise<ChampionCardArt> {
  const versions = [
    ...new Set([
      ...[player.recent[0]?.patch, player.best_game?.patch].filter(Boolean).map((p) => ddragonVersionForPatch(p, latestVersion)),
      latestVersion,
    ]),
  ];
  const urls = versions.map((v) => buildDdragon(v, cdn, latestVersion));
  const chain = (url: (dd: DdragonUrls) => string) => [...new Set(urls.map(url).filter(Boolean))];

  let keystone: string | null = null;
  let secondaryTree: string | null = null;
  const page = player.rune_page;
  if (page) {
    for (const version of versions) {
      const catalog = await runeCatalog(version).catch(() => null);
      const found = catalog?.get(page.rune_ids[0] ?? 0);
      if (!catalog || !found) continue;
      keystone = found.icon;
      secondaryTree = catalog.get(page.secondary_style_id)?.icon ?? null;
      break;
    }
  }
  return {
    splash: buildDdragon(latestVersion, cdn).championSplash(player.champion_name),
    items: (player.core?.items ?? []).slice(0, 3).map((id) => chain((dd) => dd.itemIcon(id))),
    keystone,
    secondaryTree,
    spells: (player.spells?.spell_ids ?? []).map((id) => chain((dd) => dd.spellIcon(id))).filter((c) => c.length > 0),
  };
}

interface LoadedArt {
  splash: HTMLImageElement | null;
  items: Array<HTMLImageElement | null>;
  keystone: HTMLImageElement | null;
  secondaryTree: HTMLImageElement | null;
  spells: Array<HTMLImageElement | null>;
}

/** The first URL that loads (removed items 403 on newer patches, and older ones on the newest). */
async function loadFirst(urls: readonly string[]): Promise<HTMLImageElement | null> {
  for (const url of urls) {
    if (!url) continue;
    const image = await loadImage(url);
    if (image) return image;
  }
  return null;
}

/** Mirrors --color-champ-tier-* in src/index.css (the site's tier badge: S gold, A teal, B blue, C grey, D red). */
const TIER_COLOR: Readonly<Record<ChampionTier, string>> = {
  S: "#f2c96b",
  A: "#5cc6dc",
  B: "#8ea4dc",
  C: "#9aa4b8",
  D: "#d9828b",
};

function withAlpha(hex: string, alpha: number): string {
  const n = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/** Tier pill like ChampionTierBadge: fill, border and text tinted with the tier's colour. */
function drawTierChip(ctx: CanvasRenderingContext2D, x: number, y: number, h: number, tier: ChampionTier, label: string) {
  const color = TIER_COLOR[tier];
  const pad = Math.round(h * 0.4);
  roundRect(ctx, x, y, ctx.measureText(label).width + pad * 2, h, h / 2);
  ctx.fillStyle = withAlpha(color, 0.15);
  ctx.fill();
  ctx.strokeStyle = withAlpha(color, 0.55);
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(label, x + pad, y + h / 2 + 1);
  ctx.textBaseline = "alphabetic";
}

const ICON = 52;

/** Square game icon (item, spell) with a hairline frame; an empty tile when the image is missing. */
function drawIcon(ctx: CanvasRenderingContext2D, image: HTMLImageElement | null, x: number, y: number, size: number) {
  ctx.save();
  roundRect(ctx, x, y, size, size, 10);
  ctx.fillStyle = C.surface;
  ctx.fill();
  ctx.clip();
  if (image) ctx.drawImage(image, x, y, size, size);
  ctx.restore();
  roundRect(ctx, x + 0.5, y + 0.5, size - 1, size - 1, 10);
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 1;
  ctx.stroke();
}

interface BuildGroup {
  label: string;
  width: number;
  paint: (x: number, y: number) => void;
}

/** Core items, keystone + secondary tree, and spells, each under a small caps label. */
function buildGroups(ctx: CanvasRenderingContext2D, art: ChampionCardArt, images: LoadedArt | null): BuildGroup[] {
  const groups: BuildGroup[] = [];
  const row = (label: string, count: number, image: (i: number) => HTMLImageElement | null) => {
    if (count === 0) return;
    groups.push({
      label,
      width: count * ICON + (count - 1) * 8,
      paint: (x, y) => {
        for (let i = 0; i < count; i += 1) drawIcon(ctx, image(i), x + i * (ICON + 8), y, ICON);
      },
    });
  };
  row("CORE BUILD", art.items.length, (i) => images?.items[i] ?? null);
  if (art.keystone || art.secondaryTree) {
    const small = 30;
    groups.push({
      label: "RUNES",
      width: ICON + 6 + small,
      paint: (x, y) => {
        ctx.beginPath();
        ctx.arc(x + ICON / 2, y + ICON / 2, ICON / 2, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0,0,0,0.45)";
        ctx.fill();
        ctx.strokeStyle = "rgba(200,170,110,0.35)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
        if (images?.keystone) ctx.drawImage(images.keystone, x + 3, y + 3, ICON - 6, ICON - 6);
        if (images?.secondaryTree) ctx.drawImage(images.secondaryTree, x + ICON + 6, y + ICON - small - 2, small, small);
      },
    });
  }
  row("SPELLS", art.spells.length, (i) => images?.spells[i] ?? null);
  return groups;
}

function drawCaps(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string = C.muted) {
  ctx.font = `700 15px ${SANS}`;
  ctx.letterSpacing = "3px";
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
  ctx.letterSpacing = "0px";
}

function draw(ctx: CanvasRenderingContext2D, card: ChampionCard, art: ChampionCardArt, images: LoadedArt | null, host: string) {
  const W = RECAP_WIDTH;
  const left = 72;
  const hasPanel = card.avgScore !== null;
  const panel = { x: 820, y: 104, w: 308, h: card.best ? 452 : 340 };
  const contentW = hasPanel ? panel.x - left - 40 : W - left * 2;
  const right = left + contentW;

  drawBackdrop(ctx, images?.splash ?? null, C.gold);
  drawEyebrow(ctx, card.meta, left);

  // The player's name is the headline; the tag follows in muted text when it fits.
  const namePx = fitSize(ctx, card.gameName, (px) => `700 ${px}px ${DISPLAY}`, 80, 44, contentW);
  const name = fit(ctx, card.gameName, contentW);
  ctx.fillStyle = C.text;
  ctx.fillText(name, left - 3, 164);
  const nameEnd = left + ctx.measureText(name).width;
  if (card.tagLine) {
    const tag = `#${card.tagLine}`;
    ctx.font = `500 ${Math.round(namePx * 0.42)}px ${DISPLAY}`;
    if (nameEnd + 12 + ctx.measureText(tag).width <= right) {
      ctx.fillStyle = C.muted;
      ctx.fillText(tag, nameEnd + 12, 164);
    }
  }

  // "<Champion> this season", then the champion's tier in their main role.
  ctx.font = `600 40px ${DISPLAY}`;
  const champion = fit(ctx, card.champion, contentW);
  let x = runs(ctx, left - 1, 222, [[champion, C.gold]]);
  ctx.font = `500 28px ${SANS}`;
  if (x + ctx.measureText(" this season").width <= right) x = runs(ctx, x, 222, [[" this season", C.secondary]]);
  if (card.tier) {
    ctx.font = `700 20px ${SANS}`;
    const h = 38;
    if (x + 20 + ctx.measureText(card.tier.label).width + Math.round(h * 0.4) * 2 <= right) {
      drawTierChip(ctx, x + 20, 222 - 14 - h / 2, h, card.tier.tier, card.tier.label);
    }
  }

  // Win rate, big, with the record and the comparison with everyone beside it.
  const rowY = 336;
  ctx.font = `600 104px ${DISPLAY}`;
  ctx.fillStyle = card.winRateColor;
  const big = card.winRate ?? "–";
  ctx.fillText(big, left - 4, rowY);
  const sx = left - 4 + ctx.measureText(big).width + 28;
  const sw = right - sx;
  ctx.font = `600 30px ${DISPLAY}`;
  const recordEnd = runs(ctx, sx, rowY - 46, [[fit(ctx, card.record, sw), C.text]]);
  if (card.gamesLabel) {
    ctx.font = `500 24px ${SANS}`;
    const games = `  ·  ${card.gamesLabel}`;
    if (recordEnd + ctx.measureText(games).width <= right) runs(ctx, recordEnd, rowY - 46, [[games, C.secondary]]);
  }
  ctx.font = `500 23px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, card.field, sw), sx, rowY - 6);

  // Season averages.
  if (card.statLine) {
    ctx.font = `500 23px ${SANS}`;
    ctx.fillStyle = C.secondary;
    ctx.fillText(fit(ctx, card.statLine, contentW), left, 388);
  }

  // Chips: squad rank, and the best game when there's no AI panel to hold it.
  const chips: RecapBadge[] = [
    ...(card.squad ? [card.squad] : []),
    ...(!hasPanel && card.best ? [{ label: card.best.line, kind: "highlight" as const }] : []),
  ];
  ctx.font = `700 22px ${SANS}`;
  let chipX = left;
  for (const chip of chips) {
    const label = fit(ctx, chip.label, contentW - 40);
    if (chipX + ctx.measureText(label).width + 40 > right) break;
    chipX += drawBadge(ctx, chipX, 414, 48, chip, label) + 14;
  }

  // Their build: core items, keystone + secondary tree, spells.
  const groups = buildGroups(ctx, art, images);
  let gx = left;
  for (const group of groups) {
    if (gx + group.width > right) break;
    drawCaps(ctx, group.label, gx, 504);
    group.paint(gx, 516);
    gx += Math.max(group.width, ctx.measureText(group.label).width) + 44;
  }
  if (groups.length === 0 && card.gamesLabel) {
    ctx.font = `500 20px ${SANS}`;
    ctx.fillStyle = C.muted;
    ctx.fillText("Their build shows up here once their games are in.", left, 540);
  }

  // Average AI Score: a plain number in a cyan ring (no grade), then their best game.
  if (hasPanel && card.avgScore !== null) {
    const cx = panel.x + panel.w / 2;
    const cy = panel.y + 134;
    roundRect(ctx, panel.x, panel.y, panel.w, panel.h, 28);
    ctx.fillStyle = "rgba(13,17,26,0.85)";
    ctx.fill();
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    drawRing(ctx, cx, cy, 98, 16, card.avgScore, C.cyan);

    ctx.textAlign = "center";
    ctx.font = `700 86px ${DISPLAY}`;
    ctx.fillStyle = C.text;
    ctx.fillText(String(card.avgScore), cx, cy + 25);
    ctx.font = `700 15px ${SANS}`;
    ctx.fillStyle = C.secondary;
    ctx.letterSpacing = "3px";
    ctx.fillText("HEX SCORE AVG", cx, cy + 54);
    ctx.letterSpacing = "0px";
    if (card.avgOffset) {
      ctx.font = `600 22px ${SANS}`;
      ctx.fillStyle = C.text;
      ctx.fillText(card.avgOffset, cx, panel.y + 282);
    }
    ctx.font = `400 18px ${SANS}`;
    ctx.fillStyle = C.muted;
    ctx.fillText(fit(ctx, `Season average on ${card.champion}`, panel.w - 40), cx, panel.y + 310);

    if (card.best) {
      ctx.strokeStyle = C.border;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(panel.x + 28, panel.y + 336);
      ctx.lineTo(panel.x + panel.w - 28, panel.y + 336);
      ctx.stroke();
      ctx.font = `700 15px ${SANS}`;
      ctx.fillStyle = C.muted;
      ctx.letterSpacing = "3px";
      ctx.fillText("BEST GAME", cx, panel.y + 370);
      ctx.letterSpacing = "0px";
      ctx.textAlign = "left";
      ctx.font = `600 36px ${DISPLAY}`;
      const kda = `${card.best.kills} / ${card.best.deaths} / ${card.best.assists}`;
      drawKda(ctx, cx - ctx.measureText(kda).width / 2, panel.y + 412, card.best);
      ctx.textAlign = "center";
      ctx.font = `500 18px ${SANS}`;
      ctx.fillStyle = C.secondary;
      ctx.fillText(fit(ctx, card.best.caption, panel.w - 40), cx, panel.y + 440);
    }
    ctx.textAlign = "left";
  }

  const showNote = hasPanel || card.best?.score != null;
  drawFooter(ctx, host, showNote, left, hasPanel ? AI_AVERAGE_NOTE : AI_SCORE_RESULT_NOTE);
}

/** Renders the champion card to a PNG. Missing images leave empty tiles (or no splash) instead of failing. */
export async function renderChampionCardPng(card: ChampionCard, art: ChampionCardArt): Promise<Blob> {
  const sample = `${card.gameName}${card.tagLine ?? ""}${card.champion}${card.meta}${card.statLine}${card.field}${card.squad?.label ?? ""}0123456789/%·`;
  const [splash, items, keystone, secondaryTree, spells] = await Promise.all([
    art.splash ? loadImage(art.splash) : Promise.resolve(null),
    Promise.all(art.items.map(loadFirst)),
    art.keystone ? loadImage(art.keystone) : Promise.resolve(null),
    art.secondaryTree ? loadImage(art.secondaryTree) : Promise.resolve(null),
    Promise.all(art.spells.map(loadFirst)),
    loadFonts(sample),
  ]);
  const images: LoadedArt = { splash, items, keystone, secondaryTree, spells };
  return toImage((ctx, withImages) => draw(ctx, card, art, withImages ? images : null, window.location.host));
}

/** "hextrack-Jinx-Walker.png". */
export function championCardFilename(card: ChampionCard): string {
  return `hextrack-${card.championKey}-${card.gameName}.png`.replace(/[^\w.-]+/g, "_");
}
