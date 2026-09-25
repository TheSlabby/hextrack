# HexTrack design system: "Hextech night"

A short guide for anyone building pages in `web/`. Premium and calm. Dense with data, like op.gg or u.gg, but cleaner.
The theme is dark only. Tokens live in `src/index.css` (`@theme`). Shared building blocks live in
`src/components/common` (import them from `@/components/common`). Restyled shadcn primitives live in `src/components/ui`.

## Tokens

Use the Tailwind utilities generated from the tokens. Never hard-code hex values in class names.

| Role | Utilities | Notes |
|---|---|---|
| App background | `bg-bg` | Set on `body`. `<Background />` adds the glows and the hex grid. |
| Card | `bg-surface-1` / the `surface-card` utility | Every page section sits on a card. |
| Raised / hover | `bg-surface-2`, `bg-surface-3` | Popovers, tooltips, active segments, hovered rows. |
| Borders | `border-border` (6%), `border-border-strong` (12%) | Use strong for hover, inputs and popovers. |
| Text | `text-text`, `text-text-secondary`, `text-text-muted` | Muted is `#76829b`. The brief's `#5f6b82` failed WCAG AA. |
| Primary accent | `text-gold`, `bg-gold`, `text-gold-bright` | Highlights, key numbers, focus rings, the primary CTA. |
| AI accent | `text-cyan`, `bg-cyan/10`, `border-cyan/30` | Only for AI features and interactive AI affordances. |
| Outcomes | `text-win` / `bg-win-tint`, `text-loss` / `bg-loss-tint`, `text-remake` | Blue = win, red = loss, grey = remake. |
| AI grades | `text-score-{s,a,b,c,d}` | Pick them through `lib/score.ts`; never choose a grade colour by hand. |
| Tiers | `text-tier-{iron..challenger}` | Pick them through `lib/tiers.ts` (`TIER_TEXT_CLASS`, `TIER_COLORS`). |

Other utilities: `surface-raised`, `glass` (the nav), `label-caps` (section labels), `shimmer`, `text-gold-gradient`,
`scrollbar-thin`. Radii: `rounded-2xl` (16px) for cards, `rounded-xl` (14px) for inner panels and popovers, `rounded-lg` for
controls, `rounded-md` for icons.

**Typography.** Inter Variable (`font-sans`) is the UI face. Space Grotesk (`font-display`) is for headings and big numbers,
and `h1` to `h3` get it automatically. Every stat gets `tabular-nums`. Hierarchy runs `label-caps` label, then a bold number,
then a secondary caption.

## Spacing and layout

- Use Tailwind's 4px scale. Cards pad `p-4` (dense) or `p-5` (default). Gaps: `gap-3` inside a grid of tiles, `gap-6` between
  page sections, `gap-1.5` between a label and its value.
- `AppShell` already provides the page container: `max-w-7xl`, a 16px gutter (`px-4`, then `sm:px-6 lg:px-8`), and
  `pt-6 pb-10`. Pages render their content directly and must not add another max-width wrapper.
- Test at 375, 768 and 1280 px. The page must never scroll horizontally. Wide tables scroll inside their card: `<Table>`
  already wraps itself in an `overflow-x-auto` container.
- Default grids: `grid-cols-2 md:grid-cols-4` for stat tiles, and `lg:grid-cols-[minmax(0,1fr)_320px]` for a main column
  with a sidebar. Always add `min-w-0` on grid children that hold text or charts.

## Which component to use

| Need | Use |
|---|---|
| A page section | `GlowCard` (`interactive` for clickable cards, `glow="gold" \| "cyan"` for emphasis, `asChild` to wrap a `<Link>`) |
| A section title row | `SectionHeader` (`eyebrow`, `icon`, `description`, `action` slot for filters) |
| A headline stat | `StatTile` (count-up value, `caption`, signed `delta`). Use `bare` inside another card. |
| An AI score in a row or table | `AiScoreBadge` (one game: grade + number; an average: `kind="average"`, no grade). MVP/ACE comes from `AiScoreWithRank` |
| The hero AI score | `AiScoreRing` (gauge; `kind="average"` for a season average, `animate={false}` for extra rings — only one sweeps per view) |
| A rank | `TierBadge` ("Diamond II · 54 LP") or `RankEmblem` alone (hand-drawn SVG, tinted per tier) |
| A champion / items / spells | `ChampionIcon` (xs to xl, `level`, `highlight`), `ItemSlots`, `SpellIcons` |
| A player avatar | `ProfileIcon` (gold ring, level plate) |
| A role | `PositionIcon` + `positionLabel()` |
| Win/loss | `WinRateBar` (split bar plus W/L text), `FormDots` (newest first, W/L letters) |
| Loading | The skeletons in `Skeletons.tsx`, sized like the final layout so nothing shifts. `Skeleton` for custom shapes. |
| Nothing to show | `EmptyState` (icon, title, guidance, action; `tone="ai"` for AI) |
| A failed query | `ErrorState error={query.error} onRetry={() => query.refetch()}`. Riot-key, rate-limit, network and 404 copy is built in. |
| A keyboard hint | `Kbd` |
| Entrance motion | `Stagger` + `StaggerItem`, or `Reveal`; `MotionMemory` + `AnimateOnce` on a page with tabs |
| Buttons | `Button` variants: `default` (gold CTA, one per view), `outline`, `secondary`, `ghost`, `ai`, `destructive`, `link` |
| Badges | `Badge` variants: `default` (gold), `secondary`, `ai`, `win`, `loss`, `remake`, `outline` |
| Segmented filters | `ToggleGroup type="single"` or `Tabs` (`variant="line"` for page tabs, `default` for pills) |

Data rules:

- All server data goes through the hooks in `@/api/queries`. Never call `fetch`, and never call `api.GET` inside components.
- Types come from `@/api/types`. Never hand-write response shapes.
- `useAiExplain` resolves to `null` when no model is trained. Render an `EmptyState` for that, not an error.
- `useRefreshSummoner()` already shows the toasts for the Update button. Callers only disable the button and show the cooldown.
- Build URLs with `lib/riotId.ts`: `summonerPath()`, or `<Link to="/summoner/$region/$riotId" params={summonerParams(name, tag)}>`.
- Pages read route params with `getRouteApi("/summoner/$region/$riotId")`. Never import `@/router` from a page, because that
  creates an import cycle.
- Format values with `lib/format.ts` (`timeAgo`, `formatDuration`, `formatKdaRatio`, `formatPercent`, `formatLpDelta`...).
- Get Data Dragon URLs from `useDdragon()`. Assets that belong to one game (items, summoner spells) must resolve against
  that game's patch, because removed items 403 on the newest version: wrap the rows in `<DdragonPatch patch={match.patch}>`
  (or pass `patch` to `ItemSlots` / `SpellIcons`). Champion portraits and profile icons stay on the newest version.
- Queue names come from `lib/queues.ts` (`queueLabel`, `queueRowLabel`, `queueShortLabel`). Pass the match's `game_mode`:
  Riot adds queue ids faster than they are mapped, and an unmapped one must read "Summoner's Rift", never "Queue 710".

## Motion

Timings live in `lib/motion.ts` (`MOTION`). The page must stop moving within about 600ms of its data arriving, even
though sections arrive one query at a time.

- Use the `motion` library (`motion/react`). `main.tsx` sets `<MotionConfig reducedMotion="user">`, and a global CSS rule
  turns off animations under `prefers-reduced-motion`. For custom animations, gate on `useEntranceMotion()`: it is false
  under reduced motion and inside a section that has already played.
- On mount: a staggered fade and slide-in (8px, **0.26s**, expo-out, **30ms** stagger, compressed so the last item starts
  by 0.15s). Count-ups and the AI Score ring take **0.45s**; Recharts series **350ms** (`chartAnimation`,
  `useChartAnimation`).
- Animate a page's first paint only: not refetches, and not tab switches. Radix unmounts inactive `TabsContent`, so a
  page with tabs wraps itself in `<MotionMemory>` and each re-mountable section in `<AnimateOnce id="…">`; later mounts
  render settled.
- Hover: lift cards by 1px, brighten the border to `border-border-strong`, and raise the shadow (`GlowCard interactive`).
  Transitions last 150 to 200ms.
- Key numbers count up once, on first paint, and only when they are on screen at that moment; anything else renders its
  final value (`CountUp`; `StatTile` counts up only with `animate`). Keep count-ups and gauges to hero figures: one
  `AiScoreRing` sweeps per view, the rest pass `animate={false}`.
- Never animate layout-shifting properties on data updates. Keep the previous data on screen at reduced opacity while a
  refetch runs.

## Charts (Recharts)

Import everything from `@/lib/chartTheme`:

```tsx
<ResponsiveContainer width="100%" height={220}>
  <AreaChart data={points} margin={chartMargin}>
    <CartesianGrid {...gridProps} />
    <XAxis dataKey="x" {...xAxisProps} />
    <YAxis {...yAxisProps} domain={[0, 100]} />
    <Tooltip {...tooltipProps} content={<ChartTooltip valueFormatter={(v) => `${v}`} />} />
    <Area dataKey="y" {...areaProps} stroke={CHART_COLORS.ai} fill="url(#ai-wash)" {...useChartAnimation()} />
  </AreaChart>
</ResponsiveContainer>
```

- Every chart uses `<ChartTooltip />`. It renders a surface-2 card in which the value leads and the series name follows,
  keyed by a short stroke of the series colour.
- Colours: `CHART_COLORS.ai` for AI score, `.lp` for LP/rank, `.win` and `.loss`, and `.positive`/`.negative`/`.neutral`
  (`divergingColor()`) for attributions. These are validated steps of the brand colours; don't swap in the raw brand hexes
  when there are several series. Categorical order is fixed (`CATEGORICAL_SERIES`) and never cycles.
- One y-axis per chart, never two. The grid is horizontal hairlines only, solid, at 5% white. Axis text is muted at 11px.
- Lines are 2px with no dots and an active dot of r=5 with a surface ring. Areas get a wash of about 10 to 14% fading to 0.
  Bars are at most 24px thick, with 4px rounded ends and a square baseline (`barProps`, `horizontalBarProps`).
- Text never takes a series colour: labels and legends use the text tokens, and the coloured mark next to them carries the
  identity. Charts with two or more series get a legend. Label sparingly (endpoints, extremes) and never every point.
- Rank charts plot `rank_value` and label the axis with tier names, never raw numbers (see
  `components/summoner/lpChartModel.ts`, which builds the bands from `MASTER_BASE` and `shortTier()`).
- Loading uses `SkeletonChart` at the same height. Empty data uses `EmptyState compact` inside the chart card.

## AI Score copy

The score is the model's estimate of how often a stat line like this one wins. The result is not an input, but the
stats that weigh most (gold, towers, objectives) come with winning, so a game's score mostly follows its result: wins
typically score around 90, losses around 10. Averages over a season collapse onto win rate.

- **Do** describe a grade as how much a line looks like a winning one ("Winning line", "Leaning loss"), and read scores
  against games with the same result. All the copy lives in `lib/score.ts` (`GRADES`, `AI_SCORE_SUMMARY`,
  `AI_SCORE_RESULT_NOTE`, `AI_AVERAGE_NOTE`); don't write new wording next to a score.
- **Don't** call a score a carry, claim it ignores the result, or say a high score is "above what a winner posts".
  The one exception is teammate banter: teammates share the result, so comparing their scores is fair, and a verdict
  calls out who carried or ran it down by the size of the gap. It appears only on the share card, the match hero and the
  Stacks page (all via `components/match/verdicts.ts`, with tiers computed server-side in `stats/verdict.py` for
  Stacks). Averages stay plain numbers.
- **Don't** grade an average (season, roster, champion) or give it a single game's description. Show the number with
  `kind="average"`, next to its distance from a coin flip or its place on the roster.
- Rank a roster on averages only with a minimum sample and shrinkage towards 50 (`computeStandings`), so ten good games
  can't outrank a season.

## Accessibility

- Focus rings are gold (`outline-gold`, 2px, offset 2px). Every primitive already has one, and custom interactive
  elements need one too.
- Icon-only buttons need an `aria-label`. Decorative icons need `aria-hidden="true"`.
- Colour is never the only signal. W/L also appears as text, grades show their letter, tiers show their name, and charts
  have legends or labels.
- Keep contrast at AA or better. Don't put `text-text-muted` below 11px, and don't use it on `surface-3`.

## Do / don't

- **Do** use one gold CTA per view, and cyan only for AI.
- **Do** use tabular numerals for stats, and a proper minus sign for negatives (`formatSigned`).
- **Do** match skeletons to the final layout.
- **Don't** use shadcn's default greys (`bg-muted`, `text-muted-foreground`). Use the tokens above.
- **Don't** add new colours, fonts or shadows without adding a token to `index.css`.
- **Don't** nest cards more than one level deep. Inside a card, use `bg-surface-2` panels or dividers.
- **Don't** use `dark:` variants. The app is dark only.
