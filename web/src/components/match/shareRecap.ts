/**
 * The shareable match recap: which facts go on it (`buildRecap`) and the 1200x675 PNG itself
 * (`renderRecapPng`), drawn straight onto a canvas so it uses the site's fonts and the
 * champion splash. No React here.
 */
import type { MatchDetail, ParticipantSummary } from "@/api/types";
import { championDisplayName } from "@/lib/champions";
import { formatDecimal, formatDuration, formatKdaRatio, formatPercent, formatShortDate } from "@/lib/format";
import { AI_SCORE_RESULT_NOTE, gradeForScore, toScore100, type GradeInfo } from "@/lib/score";

import { allParticipants, OUTCOME_LABEL, outcomeOf, type Outcome } from "./matchUtils";

export const RECAP_WIDTH = 1200;
export const RECAP_HEIGHT = 675;

export interface Recap {
  outcome: Outcome;
  /** "Victory", "Defeat", "Remake", or "3rd place" in Arena. */
  title: string;
  playerName: string;
  champion: string;
  championKey: string;
  kdaLine: string;
  /** Short stat line under the KDA ("KDA 4.33 · 7.8 CS/min · 64% KP"). */
  statLine: string;
  /** Up to two notable facts from this game, most notable first. */
  highlights: string[];
  /** 0..100, or null when the game has no score (remakes, not yet scored). */
  score: number | null;
  grade: GradeInfo | null;
  /** "24 – 18" (own team first), when the game has exactly two teams. */
  teamKills: string | null;
  meta: string;
  /** The whole card as one sentence, for the preview's alt text. */
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

function highlightsFor(match: MatchDetail, player: ParticipantSummary): string[] {
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
    player.ai_rank === 1 && player.ai_score != null && "Highest AI Score in the lobby",
    topOf((p) => p.damage_to_champions) && "Most damage in the lobby",
    damageShare >= 0.3 && `${formatPercent(damageShare)} of team damage`,
    player.kill_participation >= 0.6 && `${formatPercent(player.kill_participation)} kill participation`,
    topOf((p) => p.vision_score) && "Top vision score in the lobby",
    player.cs_per_min >= 8 && `${formatDecimal(player.cs_per_min)} CS per minute`,
  ];
  const picked = candidates.filter((c): c is string => Boolean(c)).slice(0, 2);
  return picked.length > 0 ? picked : [`${formatPercent(player.kill_participation)} kill participation`];
}

export function buildRecap(match: MatchDetail, player: ParticipantSummary): Recap {
  const outcome = outcomeOf(match.remake, player.win);
  const title = player.placement != null && match.teams.length > 2 && !match.remake
    ? `${ordinal(player.placement)} place`
    : OUTCOME_LABEL[outcome];
  const score = player.ai_score == null || match.remake ? null : toScore100(player.ai_score);
  const grade = score === null ? null : gradeForScore(score);
  const own = match.teams.find((t) => t.team_id === player.team_id);
  const other = match.teams.find((t) => t.team_id !== player.team_id);
  const teamKills = match.teams.length === 2 && own && other ? `${own.kills} – ${other.kills}` : null;
  const champion = championDisplayName(player.champion_name);
  const playerName = riotName(player);
  const kdaLine = `${player.kills} / ${player.deaths} / ${player.assists}`;
  const statLine = [
    `KDA ${formatKdaRatio(player.kda, player.deaths)}`,
    `${formatDecimal(player.cs_per_min)} CS/min`,
    `${formatPercent(player.kill_participation)} KP`,
  ].join("  ·  ");
  const highlights = highlightsFor(match, player);
  const meta = [match.queue_label, formatShortDate(match.game_start), formatDuration(match.game_duration), `Patch ${match.patch}`].join("  ·  ");

  const alt = [
    `${title} for ${playerName} as ${champion}`,
    `${player.kills} kills, ${player.deaths} deaths, ${player.assists} assists`,
    highlights.join(", "),
    grade && score !== null ? `AI Score ${score}, grade ${grade.grade}, ${grade.label}` : "No AI Score",
    teamKills ? `team kills ${teamKills}` : null,
    meta.replaceAll("  ·  ", ", "),
  ].filter(Boolean).join(". ");

  return { outcome, title, playerName, champion, championKey: player.champion_name, kdaLine, statLine, highlights, score, grade, teamKills, meta, alt };
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

function draw(ctx: CanvasRenderingContext2D, recap: Recap, splash: HTMLImageElement | null, host: string) {
  const W = RECAP_WIDTH;
  const H = RECAP_HEIGHT;
  const accent = OUTCOME_COLOR[recap.outcome];
  const left = 72;

  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, W, H);

  // Champion splash on the right, faded into the background like the match hero.
  if (splash) {
    const targetW = W * 0.72;
    const scale = Math.max(targetW / splash.naturalWidth, H / splash.naturalHeight);
    const sw = targetW / scale;
    const sh = H / scale;
    const sx = (splash.naturalWidth - sw) * 0.7;
    const sy = (splash.naturalHeight - sh) * 0.22;
    ctx.globalAlpha = 0.55;
    ctx.drawImage(splash, sx, sy, sw, sh, W - targetW, 0, targetW, H);
    ctx.globalAlpha = 1;
  }
  const fadeX = ctx.createLinearGradient(0, 0, W, 0);
  fadeX.addColorStop(0.28, C.bg);
  fadeX.addColorStop(0.62, "rgba(7,9,15,0.55)");
  fadeX.addColorStop(1, "rgba(7,9,15,0.1)");
  ctx.fillStyle = fadeX;
  ctx.fillRect(0, 0, W, H);
  const fadeY = ctx.createLinearGradient(0, H * 0.55, 0, H);
  fadeY.addColorStop(0, "rgba(7,9,15,0)");
  fadeY.addColorStop(1, C.bg);
  ctx.fillStyle = fadeY;
  ctx.fillRect(0, 0, W, H);

  // Outcome stripe (same signal as the match rows) and the card frame.
  ctx.fillStyle = accent;
  ctx.fillRect(0, 0, 10, H);
  ctx.strokeStyle = "rgba(200,170,110,0.28)";
  ctx.lineWidth = 2;
  roundRect(ctx, 1, 1, W - 2, H - 2, 0);
  ctx.stroke();

  ctx.textBaseline = "alphabetic";
  const contentW = recap.grade ? 700 : 1000;

  // Eyebrow: brand + game meta.
  ctx.font = `700 20px ${SANS}`;
  ctx.fillStyle = C.gold;
  ctx.letterSpacing = "4px";
  ctx.fillText("HEXTRACK", left, 84);
  const brandW = ctx.measureText("HEXTRACK").width;
  ctx.letterSpacing = "0px";
  ctx.font = `500 20px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, recap.meta, W - left * 2 - brandW - 24), left + brandW + 24, 84);

  // Result and who.
  ctx.font = `600 104px ${DISPLAY}`;
  ctx.fillStyle = accent;
  ctx.fillText(fit(ctx, recap.title, contentW), left - 4, 196);
  ctx.font = `500 34px ${SANS}`;
  ctx.fillStyle = C.text;
  const name = fit(ctx, recap.playerName, contentW - 220);
  ctx.fillText(name, left, 252);
  const nameW = ctx.measureText(name).width;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, `  as ${recap.champion}`, contentW - nameW), left + nameW, 252);

  // KDA and the supporting stats.
  ctx.font = `600 76px ${DISPLAY}`;
  ctx.fillStyle = C.text;
  ctx.fillText(recap.kdaLine, left - 2, 358);
  ctx.font = `500 24px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, recap.statLine, contentW), left, 402);

  // Highlights as gold chips.
  ctx.font = `600 24px ${SANS}`;
  let chipX = left;
  for (const highlight of recap.highlights) {
    const label = fit(ctx, highlight, contentW - 40);
    const w = ctx.measureText(label).width + 40;
    if (chipX + w > left + contentW) break;
    roundRect(ctx, chipX, 440, w, 50, 25);
    ctx.fillStyle = "rgba(200,170,110,0.12)";
    ctx.fill();
    ctx.strokeStyle = "rgba(200,170,110,0.45)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = C.goldBright;
    ctx.fillText(label, chipX + 20, 473);
    chipX += w + 14;
  }

  // Team kills.
  if (recap.teamKills) {
    ctx.font = `600 24px ${SANS}`;
    ctx.fillStyle = C.muted;
    ctx.letterSpacing = "2px";
    ctx.fillText("TEAM KILLS", left, 548);
    const labelW = ctx.measureText("TEAM KILLS").width;
    ctx.letterSpacing = "0px";
    ctx.font = `600 28px ${DISPLAY}`;
    ctx.fillStyle = C.text;
    ctx.fillText(recap.teamKills, left + labelW + 18, 549);
  }

  // AI Score ring, bottom right (mirrors AiScoreRing: track, grade-coloured arc, number, grade).
  if (recap.grade && recap.score !== null) {
    const cx = W - 200;
    const cy = 330;
    const r = 112;
    roundRect(ctx, cx - 160, cy - 172, 320, 390, 28);
    ctx.fillStyle = "rgba(13,17,26,0.82)";
    ctx.fill();
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.lineCap = "round";
    ctx.lineWidth = 16;
    ctx.strokeStyle = C.track;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    if (recap.score > 0) {
      ctx.strokeStyle = recap.grade.color;
      ctx.beginPath();
      ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * recap.score) / 100);
      ctx.stroke();
    }

    ctx.textAlign = "center";
    ctx.font = `600 84px ${DISPLAY}`;
    ctx.fillStyle = C.text;
    ctx.fillText(String(recap.score), cx, cy + 22);
    ctx.font = `700 18px ${SANS}`;
    ctx.fillStyle = C.muted;
    ctx.letterSpacing = "3px";
    ctx.fillText("AI SCORE", cx, cy + 58);
    ctx.letterSpacing = "0px";
    ctx.font = `600 26px ${SANS}`;
    ctx.fillStyle = recap.grade.color;
    ctx.fillText(`${recap.grade.grade} · ${recap.grade.label}`, cx, cy + 180);
    ctx.textAlign = "left";
  }

  // Footer: how to read the score, and where it came from.
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(left, 596);
  ctx.lineTo(W - left, 596);
  ctx.stroke();
  ctx.font = `600 20px ${SANS}`;
  ctx.fillStyle = C.gold;
  ctx.textAlign = "right";
  ctx.fillText(host, W - left, 640);
  const hostW = ctx.measureText(host).width;
  ctx.textAlign = "left";
  if (recap.grade) {
    ctx.font = `400 18px ${SANS}`;
    ctx.fillStyle = C.muted;
    const lines = wrap(ctx, AI_SCORE_RESULT_NOTE, W - left * 2 - hostW - 48, 2);
    lines.forEach((text, i) => ctx.fillText(text, left, 628 + i * 24 - (lines.length - 1) * 6));
  }
}

function toPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Couldn't encode the image"))), "image/png"),
  );
}

/** Renders the recap card to a PNG. Falls back to a card without the splash if it can't be loaded. */
export async function renderRecapPng(recap: Recap, splashUrl: string | null): Promise<Blob> {
  const sample = `${recap.title}${recap.playerName}${recap.champion}${recap.kdaLine}${recap.statLine}${recap.highlights.join("")}`;
  const [splash] = await Promise.all([
    splashUrl ? loadImage(splashUrl) : Promise.resolve(null),
    document.fonts.load(`600 104px ${DISPLAY}`, sample).catch(() => []),
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
