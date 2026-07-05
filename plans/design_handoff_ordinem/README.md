# Handoff: Ordinem Dashboard — Neumorphic Vue Component System

## Overview
Ordinem is a macOS dashboard app. Its primary surface is a set of "islands" — the
main one being an **Agent Pipeline** (read Jira tickets → draft tasks → hand off to
a Claude agent → review & commit), alongside calendar, to-do, and other API-backed
widgets, a left icon sidebar, and a right notifications column.

This bundle is the **visual design system** for that app: the look, tokens, and
component specs so every Vue component you build stays consistent.

## About the Design Files
The file in `reference/` is a **design reference authored in HTML** — a prototype
showing the intended look and behavior. It is **not** production code to copy.
The task is to **recreate these designs as Vue 3 components** in your codebase,
using its existing patterns (Vite/Nuxt, `<script setup>`, Pinia, your test setup).
Styling should be driven entirely by the CSS custom properties in `tokens.css`.

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, and shadows are final.
Recreate the UI pixel-accurately using the tokens provided.

## What's in this bundle
- `tokens.css` — **drop-in** design tokens (colors, shadows, radii, spacing, fonts).
  Import once at app root. Every component reads these vars; never hard-code values.
- `COMPONENT_BUILD_PROMPT.md` — paste this at the top of any Claude Code session
  when generating a new component, so they all come out consistent.
- `examples/NButton.vue` — the **canonical SFC pattern** to copy for every component.
- `reference/Ordinem Dashboard System.dc.html` — the full visual reference
  (open in a browser). Includes the app icon, foundations, and a live example
  dashboard screen. Needs its sibling `support.js` to render.

## How to use (quickstart)
1. Copy `tokens.css` into your app and import it once:
   ```ts
   // main.ts
   import './styles/tokens.css'
   ```
2. Open `reference/Ordinem Dashboard System.dc.html` to see the target look.
3. For each component, start a Claude Code task, paste `COMPONENT_BUILD_PROMPT.md`,
   name the component, and point at `examples/NButton.vue` as the pattern.

---

## Design Tokens
Full values live in `tokens.css`. Summary:

**Color**
- Surface `#E7EAF0` — app background AND every element's background (neumorphism only
  reads when an element's background matches its container's).
- Ink `#2A2E36` · Muted `#7E8794`
- Accent orange `#F26A1B` — **primary action / live-active state ONLY**, never decorative.
- Success `#2E9E5B`

**Elevation — two tools only**
- Raised: `box-shadow: var(--shadow-out)` → `5px 5px 11px #C4C9D3, -5px -5px 11px #FFFFFF`
  (interactive / grouped elements)
- Inset: `box-shadow: var(--shadow-in)` → `inset 4px 4px 8px #C4C9D3, inset -4px -4px 8px #FFFFFF`
  (wells, inputs, pressed states, slider/progress tracks)
- Max two nested elevation levels.

**Radii (SHARP)** — cards `--r-lg 10px` · controls `--r-md 7px` · small `--r-sm 4px` · pill `999px`

**Spacing** — 4 / 8 / 12 / 16 / 24 / 32

**Type**
- Display: `Space Grotesk` 600–700, letter-spacing -0.02em — titles/headings
- Body/UI: `IBM Plex Sans` 400–600, 13–15px
- Data: `IBM Plex Mono`, uppercase micro-labels, letter-spacing .14em, 10–11px

**App icon** — solid orange (`--accent`) squircle, ~23% corner radius, white **ō**
(lowercase o + macron) glyph filling ~56% of the tile. Alt treatments: charcoal tile
+ orange glyph (dock/dark), light neumorphic + orange, mono/deboss.

---

## Components to build (specs)
All share: background `var(--surface)`, transitions `box-shadow & transform 160ms ease`,
focus ring `0 0 0 1.5px var(--accent)`. Reserve orange for primary/active only.

- **Button** (`NButton`) — see `examples/NButton.vue`. Variants primary (orange fill,
  white text) / secondary (surface + `--shadow-out`); pressed swaps to `--shadow-in`;
  sizes sm 30px / md 38px; icon-only = square 38px. Radius `--r-md`.
- **Toggle** (`NToggle`) — track is an inset well (`--shadow-in`, pill); knob is a raised
  circle (`--shadow-out`). Active: track fills `--accent`, knob slides right (white).
- **Card / Panel** (`NCard`) — raised (`--shadow-out`), radius `--r-lg`, padding 20–24px.
  Islands (e.g. Agent Pipeline) are large NCards containing inset sub-wells.
- **Input / Select** (`NInput`, `NSelect`) — inset well (`--shadow-in`), radius `--r-md`,
  height 42px, mono uppercase label above. Focused: 1.5px `--accent` border, keep inset.
- **Tabs / Segmented** (`NTabs`) — segmented control sits in an inset track; the active
  segment is a raised chip. Underline-tab variant: active tab uses `--accent` text +
  2px `--accent` bottom border.
- **Badge / Status** (`NBadge`) — inset pill with colored dot + mono uppercase label:
  RUNNING (orange, pulsing dot), PASSED (green), QUEUED (grey). Count badge = solid
  orange pill, white text, raised.
- **Slider / Knob / Dial** (`NSlider`, `NKnob`, `NDial`) — inset track, orange fill,
  raised circular thumb. Radial/dial: inset ring with a raised inner disc; value in
  Space Grotesk, orange.
- **Sidebar item** (`NSidebarItem`) — 44px icon button; default raised, active = inset
  well with orange icon. Icons: 1.5–2px stroke, line style, `currentColor`.

## Interactions & Behavior
- Hover: lift ~1px (`translateY(-1px)` or +1px `--sh-dist`).
- Active/pressed: swap raised → inset.
- Focus-visible: `0 0 0 1.5px var(--accent)` ring, keep base shadow.
- Live/processing states (agent running, git sync): pulsing orange dot
  (opacity 1↔.35, ~1.5s) — never orange-fill purely for decoration.
- Transitions 160ms ease on box-shadow/transform.

## State Management (app-level, for reference)
- Pipeline columns (Backlog / Draft / Agent / Review-Commit) and their ticket cards.
- Per-ticket status: queued | drafting | running | review | committed.
- Notifications feed + unread count. System status (API latencies / busy flags).
- Data comes from external APIs (Jira, Claude, Git, calendar) — wire to your stores.

## Assets
- Icons are inline stroke SVGs in the reference (home, pipeline/nodes, calendar,
  check, bell, search, settings, +). Swap for your icon library (e.g. Lucide) at
  1.5–2px stroke, `currentColor`.
- Fonts: Space Grotesk, IBM Plex Sans, IBM Plex Mono (Google Fonts — see tokens.css).
- No raster image assets.

## A11y
- Never signal state by shadow alone — pair with color + icon/label.
- 4.5:1 text contrast; `--text-dim` only for secondary text ≥12px.
- Hit targets ≥44px.

## Dark theme
Deferred for now. `tokens.css` documents the override block to add later
(`[data-theme="dark"]`). Key gotcha: the dark highlight must stay near the surface
color (`#2C3036`), not white, or elements get a white glow.

## Files
- `tokens.css`
- `COMPONENT_BUILD_PROMPT.md`
- `examples/NButton.vue`
- `reference/Ordinem Dashboard System.dc.html` (+ `reference/support.js`)
