/**
 * The shareable match recap: which facts go on it (`buildRecap`) and the 1200x675 PNG itself
 * (`renderRecapPng`), drawn straight onto a canvas so it uses the site's fonts and the
 * champion splash. No React here.
 */
import type { MatchDetail, ParticipantSummary } from "@/api/types";
import { championDisplayName } from "@/lib/champions";
import { formatCompact, formatDecimal, formatDuration, formatKdaRatio, formatPercent, formatShortDate } from "@/lib/format";
import { AI_SCORE_RESULT_NOTE, gradeForScore, toScore100, type GradeInfo } from "@/lib/score";

import { verdictBadge, verdictText, verdictTier } from "./verdicts";
import { allParticipants, inGameRank, OUTCOME_LABEL, outcomeOf, sortByPosition, type Outcome } from "./matchUtils";

export const RECAP_WIDTH = 1200;
export const RECAP_HEIGHT = 675;

export interface RecapBadge {
  label: string;
  /**
   * "rank" = MVP / ACE and "carry" (solid gold), "highlight" = a notable fact (outlined),
   * "down" = the teammate who ran it down (red).
   */
  kind: "rank" | "highlight" | "carry" | "down";
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

export function buildRecap(match: MatchDetail, player: ParticipantSummary, { badgeLimit = 3 }: { badgeLimit?: number } = {}): Recap {
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
    ...highlightsFor(match, player, { limit: 3, skipAiRank: isStar }).map((label) => ({ label, kind: "highlight" as const })),
  ].slice(0, badgeLimit);
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

// --- duo / squad ----------------------------------------------------------------------------

export interface GroupRecap {
  kind: "duo" | "squad";
  outcome: Outcome;
  /** "Duo Victory", "Squad Defeat", "Duo · 3rd place". */
  title: string;
  /** The focused player first, then teammates in lane order. */
  members: Recap[];
  /** "Team kills 39 – 28  ·  25:56". */
  teamLine: string;
  /** "Together this season: 14–9 · 61%" (duos with a few games together only). */
  together: string | null;
  /** Banter headline from comparing teammates' AI Scores: "colton carried", "Dantes ran it down". */
  verdict: string | null;
  meta: string;
  alt: string;
}

/** Record of a pair over the season, as the squad endpoint reports it. */
export interface PairRecord {
  games: number;
  wins: number;
}

/** Only show a duo record once it means something. */
const MIN_TOGETHER_GAMES = 3;
/**
 * Banter lines by how lopsided the teammates' AI Scores were. `{top}` / `{low}` are the called-out
 * players; `{rest}` is everyone else ("Dantes", or "the squad"). One line is picked per match, so
 * the same game always reads the same.
 */
function teamVerdict(
  recaps: readonly Recap[],
  kind: "duo" | "squad",
  seed: string,
): { index: number | null; badge: RecapBadge | null; text: string } | null {
  const outcome = recaps[0]?.outcome;
  if (!outcome) return null;
  const verdict = verdictTier(
    recaps.map((r) => r.score),
    outcome,
  );
  if (!verdict) return null;
  const target = recaps[verdict.targetIndex ?? 0] as Recap;
  const others = recaps.filter((_, i) => i !== (verdict.targetIndex ?? 0));
  const rest = kind === "duo" && others[0] ? others[0].gameName : "the squad";
  const badge = verdictBadge(verdict.tier);
  return {
    index: badge ? verdict.targetIndex : null,
    badge,
    text: verdictText(verdict.tier, target.gameName, rest, seed),
  };
}

/**
 * Tracked players on `player`'s team (Arena: same subteam), `player` first, then lane order.
 * Two or more means a duo / squad recap is possible.
 */
export function groupMembers(match: MatchDetail, player: ParticipantSummary): ParticipantSummary[] {
  const team = match.teams.find((t) => t.team_id === player.team_id);
  const mates = (team?.participants ?? []).filter(
    (p) =>
      p.puuid !== player.puuid &&
      p.is_tracked &&
      (player.subteam_id == null || p.subteam_id === player.subteam_id),
  );
  return [player, ...sortByPosition(mates)];
}

export function buildGroupRecap(match: MatchDetail, members: readonly ParticipantSummary[], pair: PairRecord | null): GroupRecap {
  const [lead] = members;
  if (!lead || members.length < 2) throw new Error("A group recap needs at least two players");
  const kind = members.length === 2 ? "duo" : "squad";
  const badgeLimit = kind === "duo" ? 2 : 1;
  const recaps = members.map((m) => buildRecap(match, m, { badgeLimit }));
  const verdict = teamVerdict(recaps, kind, match.match_id);
  if (verdict?.badge && verdict.index !== null) {
    const target = recaps[verdict.index] as Recap;
    target.badges = [verdict.badge, ...target.badges].slice(0, badgeLimit);
  }
  const leadRecap = recaps[0] as Recap;
  const word = kind === "duo" ? "Duo" : "Squad";
  const title = leadRecap.title.endsWith("place") ? `${word} · ${leadRecap.title}` : `${word} ${leadRecap.title}`;
  const own = match.teams.find((t) => t.team_id === lead.team_id);
  const other = match.teams.find((t) => t.team_id !== lead.team_id);
  const teamLine = [
    match.teams.length === 2 && own && other ? `Team kills ${own.kills} – ${other.kills}` : null,
    formatDuration(match.game_duration),
  ].filter(Boolean).join("  ·  ");
  const together =
    kind === "duo" && pair && pair.games >= MIN_TOGETHER_GAMES
      ? `Together this season: ${pair.wins}–${pair.games - pair.wins}  ·  ${formatPercent(pair.wins / pair.games)}`
      : null;
  const meta = [match.queue_label, formatShortDate(match.game_start), `Patch ${match.patch}`].join("  ·  ");
  const alt = [title, verdict?.text, ...recaps.map((r) => r.alt.split(". ").slice(0, 3).join(", ")), teamLine, together, meta]
    .filter(Boolean)
    .join(". ");
  return { kind, outcome: leadRecap.outcome, title, members: recaps, teamLine, together, verdict: verdict?.text ?? null, meta, alt };
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

function drawBackdrop(ctx: CanvasRenderingContext2D, splash: HTMLImageElement | null, accent: string) {
  const W = RECAP_WIDTH;
  const H = RECAP_HEIGHT;
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
}

function drawEyebrow(ctx: CanvasRenderingContext2D, meta: string, left: number) {
  ctx.font = `700 19px ${SANS}`;
  ctx.fillStyle = C.gold;
  ctx.letterSpacing = "4px";
  ctx.fillText("HEXTRACK", left, 72);
  const brandW = ctx.measureText("HEXTRACK").width;
  ctx.letterSpacing = "0px";
  ctx.font = `500 19px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, meta, RECAP_WIDTH - left * 2 - brandW - 24), left + brandW + 24, 72);
}

/** Divider, the AI Score note (when any score is shown) and the site host. */
function drawFooter(ctx: CanvasRenderingContext2D, host: string, showNote: boolean, left: number) {
  const W = RECAP_WIDTH;
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
  if (showNote) {
    ctx.font = `400 17px ${SANS}`;
    ctx.fillStyle = C.muted;
    const lines = wrap(ctx, AI_SCORE_RESULT_NOTE, W - left * 2 - hostW - 48, 2);
    lines.forEach((text, i) => ctx.fillText(text, left, 624 + i * 23 - (lines.length - 1) * 6));
  }
}

/** Score ring like AiScoreRing: track, grade-coloured arc (with a soft glow), number centred. */
function drawRing(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number, stroke: number, score: number, color: string) {
  ctx.lineCap = "round";
  ctx.lineWidth = stroke;
  ctx.strokeStyle = C.track;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.stroke();
  if (score > 0) {
    ctx.shadowColor = color;
    ctx.shadowBlur = stroke;
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * score) / 100);
    ctx.stroke();
    ctx.shadowBlur = 0;
  }
}

/** KDA with deaths tinted (like KdaLine); returns the x where it ends. */
function drawKda(ctx: CanvasRenderingContext2D, x: number, y: number, recap: Pick<Recap, "kills" | "deaths" | "assists">): number {
  const slash = " / ";
  return runs(ctx, x, y, [
    [String(recap.kills), C.text],
    [slash, C.muted],
    [String(recap.deaths), OUTCOME_COLOR.loss],
    [slash, C.muted],
    [String(recap.assists), C.text],
  ]);
}

/** One badge chip at (x, y); returns its width. MVP / ACE solid gold, highlights outlined. */
function drawBadge(ctx: CanvasRenderingContext2D, x: number, y: number, h: number, badge: RecapBadge, label: string): number {
  const pad = Math.round(h * 0.4);
  const w = ctx.measureText(label).width + pad * 2;
  roundRect(ctx, x, y, w, h, h / 2);
  if (badge.kind === "rank" || badge.kind === "carry") {
    ctx.fillStyle = C.gold;
    ctx.fill();
    ctx.fillStyle = "#1a1408";
  } else if (badge.kind === "down") {
    ctx.fillStyle = "rgba(255,93,108,0.16)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255,93,108,0.7)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = "#ff8a95";
  } else {
    ctx.fillStyle = "rgba(200,170,110,0.12)";
    ctx.fill();
    ctx.strokeStyle = "rgba(200,170,110,0.5)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = C.goldBright;
  }
  ctx.textBaseline = "middle";
  ctx.fillText(label, x + pad, y + h / 2 + 1);
  ctx.textBaseline = "alphabetic";
  return w;
}

function draw(ctx: CanvasRenderingContext2D, recap: Recap, splash: HTMLImageElement | null, host: string) {
  const W = RECAP_WIDTH;
  const accent = OUTCOME_COLOR[recap.outcome];
  const left = 72;
  const hasScore = recap.grade !== null && recap.score !== null;
  const panel = { x: 820, y: 104, w: 308, h: 452 };
  const contentW = hasScore ? panel.x - left - 40 : W - left * 2;

  drawBackdrop(ctx, splash, accent);

  // Eyebrow: brand + game meta.
  drawEyebrow(ctx, recap.meta, left);

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
  const kdaEnd = drawKda(ctx, left - 4, 360, recap);
  ctx.font = `600 30px ${SANS}`;
  if (kdaEnd + 28 + ctx.measureText(recap.kdaRatio).width <= left + contentW) {
    ctx.fillStyle = C.gold;
    ctx.fillText(recap.kdaRatio, kdaEnd + 28, 360);
  }
  ctx.font = `500 23px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(fit(ctx, recap.statLine, contentW), left, 408);

  // Badges.
  ctx.font = `700 25px ${SANS}`;
  let chipX = left;
  for (const badge of recap.badges) {
    const label = fit(ctx, badge.label, contentW - 44);
    if (chipX + ctx.measureText(label).width + 44 > left + contentW) break;
    chipX += drawBadge(ctx, chipX, 446, 56, badge, label) + 14;
  }

  // AI Score: a big ring on the right.
  if (hasScore && recap.grade && recap.score !== null) {
    const cx = panel.x + panel.w / 2;
    const cy = panel.y + 170;
    roundRect(ctx, panel.x, panel.y, panel.w, panel.h, 28);
    ctx.fillStyle = "rgba(13,17,26,0.85)";
    ctx.fill();
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    drawRing(ctx, cx, cy, 118, 18, recap.score, recap.grade.color);

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

  drawFooter(ctx, host, hasScore, left);
}

/**
 * Duo / squad card: one headline, then a column per player (champion, name, AI Score ring,
 * KDA, badges), then team kills and the duo's record together.
 */
function drawGroup(
  ctx: CanvasRenderingContext2D,
  group: GroupRecap,
  splash: HTMLImageElement | null,
  icons: ReadonlyArray<HTMLImageElement | null>,
  host: string,
) {
  const W = RECAP_WIDTH;
  const left = 72;
  const n = group.members.length;
  const k = n === 2 ? 1 : n === 3 ? 0.9 : n === 4 ? 0.8 : 0.7;
  const px = (v: number) => Math.round(v * k);
  const gap = n === 2 ? 28 : 18;
  const top = 158;
  const bottom = 548;
  const colW = (W - left * 2 - gap * (n - 1)) / n;

  drawBackdrop(ctx, splash, OUTCOME_COLOR[group.outcome]);
  drawEyebrow(ctx, group.meta, left);

  ctx.font = `700 60px ${DISPLAY}`;
  ctx.fillStyle = OUTCOME_COLOR[group.outcome];
  const title = fit(ctx, group.title, W - left * 2);
  ctx.fillText(title, left - 2, 134);
  if (group.verdict) {
    const titleEnd = left + ctx.measureText(title).width;
    const room = W - left - titleEnd - 40;
    fitSize(ctx, group.verdict, (v) => `600 ${v}px ${DISPLAY}`, 34, 22, room);
    ctx.fillStyle = group.outcome === "win" ? C.gold : "#ff8a95";
    ctx.textAlign = "right";
    ctx.fillText(fit(ctx, group.verdict, room), W - left, 132);
    ctx.textAlign = "left";
  }

  group.members.forEach((m, i) => {
    const x = left + i * (colW + gap);
    const cx = x + colW / 2;
    const inner = colW - 28;
    roundRect(ctx, x, top, colW, bottom - top, 22);
    ctx.fillStyle = "rgba(13,17,26,0.82)";
    ctx.fill();
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Champion portrait.
    const size = px(60);
    let y = top + px(18);
    const icon = icons[i];
    ctx.save();
    roundRect(ctx, cx - size / 2, y, size, size, px(14));
    ctx.clip();
    if (icon) {
      ctx.drawImage(icon, cx - size / 2, y, size, size);
    } else {
      ctx.fillStyle = C.surface;
      ctx.fillRect(cx - size / 2, y, size, size);
    }
    ctx.restore();
    y += size;

    // Name and champion.
    ctx.textAlign = "center";
    const namePx = fitSize(ctx, m.gameName, (v) => `700 ${v}px ${DISPLAY}`, px(40), 18, inner);
    y += Math.round(namePx * 1.1);
    ctx.fillStyle = C.text;
    ctx.fillText(fit(ctx, m.gameName, inner), cx, y);
    ctx.font = `500 ${px(20)}px ${SANS}`;
    ctx.fillStyle = C.secondary;
    y += px(25);
    ctx.fillText(fit(ctx, m.champion, inner), cx, y);

    // AI Score ring, or a note when the game isn't scored.
    const r = px(54);
    y += px(14) + r;
    if (m.grade && m.score !== null) {
      drawRing(ctx, cx, y, r, px(11), m.score, m.grade.color);
      ctx.font = `700 ${px(46)}px ${DISPLAY}`;
      ctx.fillStyle = C.text;
      ctx.fillText(String(m.score), cx, y + px(12));
      ctx.font = `700 ${Math.max(10, px(12))}px ${SANS}`;
      ctx.fillStyle = m.grade.color;
      ctx.fillText(fit(ctx, `${m.grade.grade} · AI SCORE`, r * 1.5), cx, y + px(32));
    } else {
      ctx.font = `500 ${px(20)}px ${SANS}`;
      ctx.fillStyle = C.muted;
      ctx.fillText("Not scored", cx, y + px(7));
    }
    y += r;

    // KDA, centred: measure first, then draw left-aligned from the start.
    ctx.font = `600 ${px(40)}px ${DISPLAY}`;
    ctx.textAlign = "left";
    const kdaText = `${m.kills} / ${m.deaths} / ${m.assists}`;
    y += px(48);
    drawKda(ctx, cx - ctx.measureText(kdaText).width / 2, y, m);

    // Badges, centred as a row.
    ctx.font = `700 ${Math.max(12, px(17))}px ${SANS}`;
    const h = px(32);
    const labels = m.badges.map((b) => ({ badge: b, label: fit(ctx, b.label, inner - h) }));
    const widths = labels.map(({ label }) => ctx.measureText(label).width + Math.round(h * 0.4) * 2);
    let shown = 0;
    let total = 0;
    for (const w of widths) {
      if (total + w + (shown > 0 ? 10 : 0) > inner) break;
      total += w + (shown > 0 ? 10 : 0);
      shown += 1;
    }
    let bx = cx - total / 2;
    const by = y + px(14);
    labels.slice(0, shown).forEach(({ badge, label }) => {
      bx += drawBadge(ctx, bx, by, h, badge, label) + 10;
    });
  });

  // Shared strip: team result on the left, the duo's record on the right.
  ctx.textAlign = "left";
  ctx.font = `500 21px ${SANS}`;
  ctx.fillStyle = C.secondary;
  ctx.fillText(group.teamLine, left, 576);
  if (group.together) {
    ctx.font = `700 21px ${SANS}`;
    ctx.fillStyle = C.gold;
    ctx.textAlign = "right";
    ctx.fillText(group.together, W - left, 576);
    ctx.textAlign = "left";
  }

  drawFooter(ctx, host, group.members.some((m) => m.grade !== null), left);
}

function toPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Couldn't encode the image"))), "image/png"),
  );
}

async function loadFonts(sample: string) {
  await Promise.all([
    document.fonts.load(`700 104px ${DISPLAY}`, sample).catch(() => []),
    document.fonts.load(`500 34px ${SANS}`, sample).catch(() => []),
  ]);
}

/** Draws onto a fresh canvas and encodes it; retries without images if they taint the canvas. */
async function toImage(paint: (ctx: CanvasRenderingContext2D, withImages: boolean) => void): Promise<Blob> {
  const render = (withImages: boolean) => {
    const canvas = document.createElement("canvas");
    canvas.width = RECAP_WIDTH;
    canvas.height = RECAP_HEIGHT;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas unavailable");
    paint(ctx, withImages);
    return toPng(canvas);
  };
  try {
    return await render(true);
  } catch {
    // A tainted canvas (image served without CORS) can't be exported; drop the images.
    return render(false);
  }
}

/** Renders the solo recap card to a PNG. Falls back to a card without the splash if it can't be loaded. */
export async function renderRecapPng(recap: Recap, splashUrl: string | null): Promise<Blob> {
  const sample = `${recap.title}${recap.playerName}${recap.champion}${recap.kdaRatio}${recap.statLine}${recap.badges.map((b) => b.label).join("")}0123456789/`;
  const [splash] = await Promise.all([splashUrl ? loadImage(splashUrl) : Promise.resolve(null), loadFonts(sample)]);
  return toImage((ctx, withImages) => draw(ctx, recap, withImages ? splash : null, window.location.host));
}

/** Renders the duo / squad card. `iconUrls` are the members' champion portraits, in member order. */
export async function renderGroupRecapPng(group: GroupRecap, splashUrl: string | null, iconUrls: readonly string[]): Promise<Blob> {
  const sample = `${group.title}${group.teamLine}${group.together ?? ""}${group.members.map((m) => `${m.gameName}${m.champion}${m.badges.map((b) => b.label).join("")}`).join("")}0123456789/`;
  const [splash, icons] = await Promise.all([
    splashUrl ? loadImage(splashUrl) : Promise.resolve(null),
    Promise.all(iconUrls.map((url) => loadImage(url))),
    loadFonts(sample),
  ]);
  return toImage((ctx, withImages) =>
    drawGroup(ctx, group, withImages ? splash : null, withImages ? icons : [], window.location.host),
  );
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
