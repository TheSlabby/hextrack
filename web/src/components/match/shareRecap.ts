/**
 * The shareable match recap: which facts go on it (`buildRecap`) and the 1200x675 PNG itself
 * (`renderRecapPng`), drawn straight onto a canvas so it uses the site's fonts and the
 * champion splash. No React here.
 */
import type { MatchDetail, ParticipantSummary } from "@/api/types";
import { championDisplayName } from "@/lib/champions";
import { formatCompact, formatDecimal, formatDuration, formatKdaRatio, formatPercent, formatShortDate } from "@/lib/format";
import { AI_SCORE_RESULT_NOTE, gradeForScore, toScore100, type GradeInfo } from "@/lib/score";

import { allParticipants, inGameRank, OUTCOME_LABEL, outcomeOf, type Outcome } from "./matchUtils";

export const RECAP_WIDTH = 1200;
export const RECAP_HEIGHT = 675;

export interface RecapBadge {
  label: string;
  /** "rank" = MVP / ACE (solid gold), "highlight" = a notable fact (outlined). */
  kind: "rank" | "highlight";
}

export interface Recap {
  outcome: Outcome;
  /** "Victory", "Defeat", "Remake", or "3rd place" in Arena. */
  title: string;
  /** Riot game name (the champion name when unknown) and tag, drawn separately. */
  gameName: string;
  tagLine: string | null;
  playerName: string;
  champion: string;
  kills: number;
  deaths: number;
  assists: number;
  /** "3.00 KDA" / "Perfect KDA". */
  kdaRatio: string;
  /** Supporting stats ("8.4 CS/min · 54% KP · 19.9K damage · Team kills 28 – 39"). */
  statLine: string;
  /** MVP / ACE first, then notable facts; at most three. */
  badges: RecapBadge[];
  /** 0..100, or null when the game has no score (remakes, not yet scored). */
  score: number | null;
  grade: GradeInfo | null;
  /** "#4 of 10 in the lobby" when the player isn't MVP / ACE. */
  lobbyRank: string | null;
  meta: string;
  /** The whole card as one sentence, for alt text. */
  alt: string;
}

function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

export function riotName(player: ParticipantSummary): string {
  if (!player.game_name) return championDisplayName(player.champion_name);
  return player.tag_line ? `${player.game_name}#${player.tag_line}` : player.game_name;
}

/**
 * Notable facts about one player's game, most notable first. `skipAiRank` drops the "highest AI
 * Score" line where an MVP / ACE pill already says it.
 */
export function highlightsFor(
  match: MatchDetail,
  player: ParticipantSummary,
  { limit = 2, skipAiRank = false }: { limit?: number; skipAiRank?: boolean } = {},
): string[] {
  if (match.remake) return ["Remade early, so this one isn't scored"];

  const everyone = allParticipants(match);
  const team = match.teams.find((t) => t.team_id === player.team_id);
  const topOf = (value: (p: ParticipantSummary) => number) =>
    everyone.length > 1 && everyone.every((p) => p === player || value(p) < value(player));
  const damageShare = team && team.damage_to_champions > 0 ? player.damage_to_champions / team.damage_to_champions : 0;

  const candidates: Array<string | false> = [
    player.largest_multikill >= 5 && "Pentakill",
    player.largest_multikill === 4 && "Quadra kill",
    player.largest_multikill === 3 && "Triple kill",
    player.deaths === 0 && player.kills + player.assists > 0 && "Deathless game",
    !skipAiRank && player.ai_rank === 1 && player.ai_score != null && "Highest AI Score in the lobby",
    topOf((p) => p.damage_to_champions) && "Most damage in the lobby",
    damageShare >= 0.3 && `${formatPercent(damageShare)} of team damage`,
    topOf((p) => p.vision_score) && "Top vision score in the lobby",
  ];
  // KP and CS/min aren't badges: the stat line next to them already shows both.
  return candidates.filter((c): c is string => Boolean(c)).slice(0, limit);
}

export function buildRecap(match: MatchDetail, player: ParticipantSummary): Recap {
  const outcome = outcomeOf(match.remake, player.win);
  const title = player.placement != null && match.teams.length > 2 && !match.remake
    ? `${ordinal(player.placement)} place`
    : OUTCOME_LABEL[outcome];
  const score = player.ai_score == null || match.remake ? null : toScore100(player.ai_score);
  const grade = score === null ? null : gradeForScore(score);
  const rank = inGameRank(player, match.teams, match.remake);
  const own = match.teams.find((t) => t.team_id === player.team_id);
  const other = match.teams.find((t) => t.team_id !== player.team_id);
  const champion = championDisplayName(player.champion_name);
  const playerName = riotName(player);
  const kdaRatio = `${formatKdaRatio(player.kda, player.deaths)} KDA`;
  const statLine = [
    `${formatDecimal(player.cs_per_min)} CS/min`,
    `${formatPercent(player.kill_participation)} KP`,
    `${formatCompact(player.damage_to_champions)} damage`,
    match.teams.length === 2 && own && other ? `Team kills ${own.kills} – ${other.kills}` : null,
  ].filter(Boolean).join("  ·  ");
  const isStar = rank !== null && rank.kind !== "rank";
  const badges: RecapBadge[] = [
    ...(isStar ? [{ label: rank.label, kind: "rank" as const }] : []),
    ...highlightsFor(match, player, { limit: isStar ? 2 : 3, skipAiRank: isStar }).map((label) => ({ label, kind: "highlight" as const })),
  ];
  const meta = [match.queue_label, formatShortDate(match.game_start), formatDuration(match.game_duration), `Patch ${match.patch}`].join("  ·  ");

  const alt = [
    `${playerName}: ${title} as ${champion}`,
    grade && score !== null ? `AI Score ${score}, grade ${grade.grade}, ${grade.label}` : "No AI Score",
    `${player.kills} kills, ${player.deaths} deaths, ${player.assists} assists, ${kdaRatio}`,
    badges.map((b) => (b.kind === "rank" ? rank?.description : b.label)).join(", "),
    statLine.replaceAll("  ·  ", ", "),
    meta.replaceAll("  ·  ", ", "),
  ].filter(Boolean).join(". ");

  return {
    outcome,
    title,
    gameName: player.game_name ?? champion,
    tagLine: player.game_name ? player.tag_line : null,
    playerName,
    champion,
    kills: player.kills,
    deaths: player.deaths,
    assists: player.assists,
    kdaRatio,
    statLine,
    badges,
    score,
    grade,
    lobbyRank: rank && !isStar ? `${rank.label} of 10 in the lobby` : null,
    meta,
    alt,
  };
}

// --- rendering ------------------------------------------------------------------------------

/** Mirrors the tokens in src/index.css (canvas can't read Tailwind classes). */
const C = {
  bg: "#07090f",
  surface: "#0d111a",
  border: "rgba(255,255,255,0.12)",
  text: "#e8ecf4",
  secondary: "#9aa4b8",
  muted: "#76829b",
  gold: "#c8aa6e",
  goldBright: "#f0e6d2",
  track: "rgba(255,255,255,0.08)",
} as const;
const OUTCOME_COLOR: Record<Outcome, string> = { win: "#4f8cff", loss: "#ff5d6c", remake: "#7a8499" };
const DISPLAY = '"Space Grotesk Variable", "Inter Variable", system-ui, sans-serif';
const SANS = '"Inter Variable", system-ui, sans-serif';

function loadImage(url: string, timeoutMs = 4000): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.decoding = "async";
    const timer = window.setTimeout(() => resolve(null), timeoutMs);
    image.onload = () => { window.clearTimeout(timer); resolve(image); };
    image.onerror = () => { window.clearTimeout(timer); resolve(null); };
    image.src = url;
  });
}

/** Trims `text` with an ellipsis until it fits in `maxWidth` at the current font. */
function fit(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let end = text.length;
  while (end > 1 && ctx.measureText(`${text.slice(0, end)}…`).width > maxWidth) end -= 1;
  return `${text.slice(0, end).trimEnd()}…`;
}

/** Greedy word wrap into at most `maxLines` lines; the last line is ellipsised if needed. */
function wrap(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(" ")) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width <= maxWidth || !line) {
      line = next;
    } else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  if (lines.length <= maxLines) return lines;
  const kept = lines.slice(0, maxLines);
  kept[maxLines - 1] = fit(ctx, `${kept[maxLines - 1]} ${lines.slice(maxLines).join(" ")}`, maxWidth);
  return kept;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

/** Largest font size (stepping down to `min`) at which `text` fits in `maxWidth`. */
function fitSize(ctx: CanvasRenderingContext2D, text: string, font: (px: number) => string, max: number, min: number, maxWidth: number): number {
  let px = max;
  ctx.font = font(px);
  while (px > min && ctx.measureText(text).width > maxWidth) {
    px -= 2;
    ctx.font = font(px);
  }
  return px;
}

/** Draws runs of differently coloured text on one baseline; returns the x after the last run. */
function runs(ctx: CanvasRenderingContext2D, x: number, y: number, parts: Array<[string, string]>): number {
  for (const [text, color] of parts) {
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
    x += ctx.measureText(text).width;
  }
  return x;
}

function draw(ctx: CanvasRenderingContext2D, recap: Recap, splash: HTMLImageElement | null, host: string) {
  const W = RECAP_WIDTH;
  const H = RECAP_HEIGHT;
  const accent = OUTCOME_COLOR[recap.outcome];
  const left = 72;
  const hasScore = recap.grade !== null && recap.score !== null;
  const panel = { x: 820, y: 104, w: 308, h: 452 };
  const contentW = hasScore ? panel.x - left - 40 : W - left * 2;

  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, W, H);

  // Champion splash, faded into the background like the match hero.
  if (splash) {
    const targetW = W * 0.72;
    const scale = Math.max(targetW / splash.naturalWidth, H / splash.naturalHeight);
    const sw = targetW / scale;
    const sh = H / scale;
    ctx.globalAlpha = 0.5;
    ctx.drawImage(splash, (splash.naturalWidth - sw) * 0.7, (splash.naturalHeight - sh) * 0.22, sw, sh, W - targetW, 0, targetW, H);
    ctx.globalAlpha = 1;
  }
  const fadeX = ctx.createLinearGradient(0, 0, W, 0);
  fadeX.addColorStop(0.3, C.bg);
  fadeX.addColorStop(0.65, "rgba(7,9,15,0.6)");
  fadeX.addColorStop(1, "rgba(7,9,15,0.2)");
  ctx.fillStyle = fadeX;
  ctx.fillRect(0, 0, W, H);
  const fadeY = ctx.createLinearGradient(0, H * 0.6, 0, H);
  fadeY.addColorStop(0, "rgba(7,9,15,0)");
  fadeY.addColorStop(1, C.bg);
  ctx.fillStyle = fadeY;
  ctx.fillRect(0, 0, W, H);

  // Outcome stripe (same signal as the match rows) and frame.
  ctx.fillStyle = accent;
  ctx.fillRect(0, 0, 10, H);
  ctx.strokeStyle = "rgba(200,170,110,0.28)";
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, W - 2, H - 2);
  ctx.textBaseline = "alphabetic";

  // Eyebrow: brand + game meta.
  ctx.font = `700 19px ${SANS}`;
  ctx.fillStyle = C.gold;
  ctx.letterSpacing = "4px";
  ctx.fillText("HEXTRACK", left, 72);
  const brandW = ctx.measureText("HEXTRACK").width;
  ctx.letterSpacing = "0px";
  ctx.font = `500 19px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, recap.meta, W - left * 2 - brandW - 24), left + brandW + 24, 72);

  // The player's name is the headline; the tag follows in muted text when it fits.
  const nameFont = (px: number) => `700 ${px}px ${DISPLAY}`;
  const tag = recap.tagLine ? `#${recap.tagLine}` : "";
  const namePx = fitSize(ctx, recap.gameName, nameFont, 88, 48, contentW);
  const name = fit(ctx, recap.gameName, contentW);
  ctx.fillStyle = C.text;
  ctx.fillText(name, left - 3, 176);
  const nameEnd = left + ctx.measureText(name).width;
  if (tag) {
    ctx.font = `500 ${Math.round(namePx * 0.42)}px ${DISPLAY}`;
    if (nameEnd + 12 + ctx.measureText(tag).width <= left + contentW) {
      ctx.fillStyle = C.muted;
      ctx.fillText(tag, nameEnd + 12, 176);
    }
  }

  // Result and champion.
  ctx.font = `600 36px ${DISPLAY}`;
  const titleEnd = runs(ctx, left, 232, [[recap.title, accent]]);
  ctx.font = `500 30px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, `  ·  ${recap.champion}`, left + contentW - titleEnd), titleEnd, 232);

  // KDA, deaths tinted like KdaLine, then the ratio.
  ctx.font = `600 112px ${DISPLAY}`;
  const slash = " / ";
  const kdaEnd = runs(ctx, left - 4, 360, [
    [String(recap.kills), C.text],
    [slash, C.muted],
    [String(recap.deaths), OUTCOME_COLOR.loss],
    [slash, C.muted],
    [String(recap.assists), C.text],
  ]);
  ctx.font = `600 30px ${SANS}`;
  if (kdaEnd + 28 + ctx.measureText(recap.kdaRatio).width <= left + contentW) {
    ctx.fillStyle = C.gold;
    ctx.fillText(recap.kdaRatio, kdaEnd + 28, 360);
  }
  ctx.font = `500 23px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, recap.statLine, contentW), left, 408);

  // Badges: MVP / ACE solid gold, highlights outlined.
  ctx.font = `700 25px ${SANS}`;
  let chipX = left;
  for (const badge of recap.badges) {
    const label = fit(ctx, badge.label, contentW - 44);
    const w = ctx.measureText(label).width + 44;
    if (chipX + w > left + contentW) break;
    roundRect(ctx, chipX, 446, w, 56, 28);
    if (badge.kind === "rank") {
      ctx.fillStyle = C.gold;
      ctx.fill();
      ctx.fillStyle = "#1a1408";
    } else {
      ctx.fillStyle = "rgba(200,170,110,0.12)";
      ctx.fill();
      ctx.strokeStyle = "rgba(200,170,110,0.5)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = C.goldBright;
    }
    ctx.fillText(label, chipX + 22, 483);
    chipX += w + 14;
  }

  // AI Score: a big ring on the right (mirrors AiScoreRing: track, grade-coloured arc, number, grade).
  if (hasScore && recap.grade && recap.score !== null) {
    const cx = panel.x + panel.w / 2;
    const cy = panel.y + 170;
    const r = 118;
    roundRect(ctx, panel.x, panel.y, panel.w, panel.h, 28);
    ctx.fillStyle = "rgba(13,17,26,0.85)";
    ctx.fill();
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.lineCap = "round";
    ctx.lineWidth = 18;
    ctx.strokeStyle = C.track;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    if (recap.score > 0) {
      ctx.shadowColor = recap.grade.color;
      ctx.shadowBlur = 18;
      ctx.strokeStyle = recap.grade.color;
      ctx.beginPath();
      ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * recap.score) / 100);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    ctx.textAlign = "center";
    ctx.font = `700 104px ${DISPLAY}`;
    ctx.fillStyle = C.text;
    ctx.fillText(String(recap.score), cx, cy + 30);
    ctx.font = `700 17px ${SANS}`;
    ctx.fillStyle = C.secondary;
    ctx.letterSpacing = "3px";
    ctx.fillText("AI SCORE", cx, cy + 64);
    ctx.letterSpacing = "0px";

    ctx.font = `700 28px ${SANS}`;
    ctx.fillStyle = recap.grade.color;
    ctx.fillText(fit(ctx, `${recap.grade.grade} · ${recap.grade.label}`, panel.w - 32), cx, panel.y + 368);
    if (recap.lobbyRank) {
      ctx.font = `500 20px ${SANS}`;
      ctx.fillStyle = C.secondary;
      ctx.fillText(recap.lobbyRank, cx, panel.y + 408);
    }
    ctx.textAlign = "left";
  }

  // Footer: how to read the score, and where it came from.
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(left, 590);
  ctx.lineTo(W - left, 590);
  ctx.stroke();
  ctx.font = `600 20px ${SANS}`;
  ctx.fillStyle = C.gold;
  ctx.textAlign = "right";
  ctx.fillText(host, W - left, 636);
  const hostW = ctx.measureText(host).width;
  ctx.textAlign = "left";
  if (hasScore) {
    ctx.font = `400 17px ${SANS}`;
    ctx.fillStyle = C.muted;
    const lines = wrap(ctx, AI_SCORE_RESULT_NOTE, W - left * 2 - hostW - 48, 2);
    lines.forEach((text, i) => ctx.fillText(text, left, 624 + i * 23 - (lines.length - 1) * 6));
  }
}

function toPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Couldn't encode the image"))), "image/png"),
  );
}

/** Renders the recap card to a PNG. Falls back to a card without the splash if it can't be loaded. */
export async function renderRecapPng(recap: Recap, splashUrl: string | null): Promise<Blob> {
  const sample = `${recap.title}${recap.playerName}${recap.champion}${recap.kdaRatio}${recap.statLine}${recap.badges.map((b) => b.label).join("")}0123456789/`;
  const [splash] = await Promise.all([
    splashUrl ? loadImage(splashUrl) : Promise.resolve(null),
    document.fonts.load(`700 104px ${DISPLAY}`, sample).catch(() => []),
    document.fonts.load(`500 34px ${SANS}`, sample).catch(() => []),
  ]);

  const render = (image: HTMLImageElement | null) => {
    const canvas = document.createElement("canvas");
    canvas.width = RECAP_WIDTH;
    canvas.height = RECAP_HEIGHT;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas unavailable");
    draw(ctx, recap, image, window.location.host);
    return toPng(canvas);
  };

  try {
    return await render(splash);
  } catch (error) {
    // A tainted canvas (image served without CORS) can't be exported; drop the splash.
    if (splash) return render(null);
    throw error;
  }
}

// --- clipboard / share support ---------------------------------------------------------------

/** Whether this browser can put a PNG on the clipboard (needs a secure context). */
export function canCopyImage(): boolean {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) return false;
  return typeof ClipboardItem.supports === "function" ? ClipboardItem.supports("image/png") : true;
}

/**
 * Copies the PNG. `blob` is passed as a promise and `clipboard.write` is called synchronously in
 * the click handler: Safari rejects writes that happen after an await (the user gesture is gone).
 */
export function copyImage(blob: Promise<Blob>): Promise<void> {
  return navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in Firefox and Safari.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
