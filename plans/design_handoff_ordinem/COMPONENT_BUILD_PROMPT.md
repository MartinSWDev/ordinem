Build a Vue 3 component for the Ordinem dashboard — a neumorphic, mission-control
("NASA science") macOS app. Follow these rules exactly.

STYLE
- Soft-UI / neumorphism, SUBTLE depth. Shadow, not borders, creates elevation.
- The component's background MUST equal its parent's (--surface). This is what makes neumorphism work.
- Two elevation tools only:
    raised  → box-shadow: var(--shadow-out)   (interactive / grouped)
    inset   → box-shadow: var(--shadow-in)     (wells, inputs, pressed, tracks)
- Never exceed two nested elevation levels.

TOKENS (theme via CSS custom properties; light theme — dark deferred; all defined in tokens.css)
  --surface:  #E7EAF0
  --text:     #2A2E36
  --text-dim: #7E8794
  --accent:   #F26A1B   (orange)
  --success:  #2E9E5B
  --sh-dark:  #C4C9D3   --sh-light: #FFFFFF
  --sh-dist: 5px; --sh-blur: 11px; --sh-din: 4px; --sh-blin: 8px;
  --shadow-out / --shadow-in : composed from the atoms above
  radii:  --r-lg 10px (cards) · --r-md 7px (controls) · --r-sm 4px   (SHARP corners)
  space:  4 / 8 / 12 / 16 / 24 / 32
  app icon: solid --accent squircle (~23% radius) + white ō glyph @ 56%

TYPE
  Display : var(--font-display) 'Space Grotesk', 600–700, letter-spacing -0.02em (titles)
  Body/UI : var(--font-body)    'IBM Plex Sans', 400–600, 13–15px
  Data    : var(--font-mono)    'IBM Plex Mono', uppercase micro-labels, letter-spacing .14em, 10–11px

COLOR
- Orange = primary action OR live/active state ONLY. Everything else is grey ink on surface.
- Success green only for passing/added states.

INTERACTION
- hover: lift slightly (increase --sh-dist ~1px) ; active/pressed: swap to var(--shadow-in).
- focus: 1.5px solid var(--accent) ring; keep the inset well.
- Transition box-shadow & transform 160ms ease.

A11Y
- Never signal state with shadow alone — pair with color + icon/label.
- Maintain 4.5:1 text contrast; --text-dim only for secondary text ≥12px.

DELIVER
- A single-file Vue 3 SFC, <script setup> + scoped styles, props typed.
- Read tokens from CSS vars (never hard-coded). Emit standard events.
- Expose size/variant via props (variant: primary|secondary, size: sm|md).
