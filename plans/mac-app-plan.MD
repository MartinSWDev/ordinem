# Dashboard shell — build spec

## Build spec for Claude Code

This specifies the container app that will host all dashboard islands (ticket
workflow, todos/calendar rollup, home PC stats, and anything added later). This
is the shell only — no island logic lives here. The goal is a running,
navigable skeleton that proves the plumbing, ready for islands and styling to
be layered on afterward.

**Explicitly out of scope for this build pass: all visual design and styling.**
Use plain unstyled markup or default component library styles. Structure,
config loading, navigation, and data-fetching plumbing matter here — not
appearance. Visual design will be done by hand separately.

---

## 1. Goal

A single codebase, built with Tauri, that runs on both Macs (work and
personal) and the Windows/Linux home PC, showing a left-hand navigation menu
of "islands" and a main pane that renders whichever island is selected. Which
islands appear, and what credentials they use, is controlled entirely by a
per-device config file — not by anything hardcoded in the app.

Non-goals for this pass:
- No actual island functionality (ticket workflow, todos, etc.) — those are
  separate builds against their own specs.
- No iPhone build — that's a separate client, out of scope here.
- No visual styling.

---

## 2. Why Tauri

- One frontend codebase (HTML/CSS/JS, framework of choice) shared across
  work Mac, personal Mac, and the home PC.
- Uses the OS's native webview rather than bundling Chromium, keeping the
  binary small and memory footprint low — relevant given the work MacBook Air
  is RAM-constrained.
- Rust is only needed for shell-level native functionality (secure storage,
  filesystem access); the bulk of the app is plain frontend work.

---

## 3. Core mechanism: the device manifest

On launch, the app reads a local config file (not bundled into the app,
not synced automatically) that declares which islands this device shows and
how each one authenticates. This file is what makes "work Mac sees Jira
islands, personal Mac doesn't" true by construction rather than by a UI
toggle — an island absent from the manifest is never mounted, never fetched,
never rendered.

Example manifest shape:

```json
{
  "device_name": "work-macbook-air",
  "islands": [
    {
      "id": "ticket-workflow",
      "title": "Tickets",
      "endpoint_base": "https://orchestrator.<tailnet>.ts.net/api/tickets",
      "credential_ref": "work_api_token"
    },
    {
      "id": "todos",
      "title": "Todos",
      "endpoint_base": "https://orchestrator.<tailnet>.ts.net/api/todos",
      "credential_ref": "shared_api_token"
    }
  ]
}
```

- `credential_ref` is a lookup key, not the credential itself. Actual tokens
  are resolved at runtime from the OS keychain (via Tauri's secure storage
  APIs), never stored in the manifest file or in plaintext on disk.
- The manifest file lives outside the app bundle (e.g. a fixed path in the
  user's home directory) so it can differ per machine without rebuilding the
  app, and isn't accidentally checked into version control.
- Manifest is loaded once at startup. A "reload config" action re-reads it
  without requiring a full app restart.

---

## 4. Shell structure

- **Sidebar (left):** one entry per island in the manifest, in the order
  listed. No hardcoded island list anywhere in the shell code.
- **Main pane:** renders the selected island's panel. For this build pass,
  each island panel is a generic component that:
  1. Resolves its credential via `credential_ref`.
  2. Fetches from `endpoint_base` (a simple `GET` against the base URL is
     sufficient to prove connectivity for this pass).
  3. Renders the raw response (formatted JSON is fine) in the main pane.
  4. Shows a clear, distinct state if the fetch fails (endpoint unreachable,
     auth rejected, timeout) rather than a blank pane or silent failure —
     this matters in particular for islands that depend on the home PC being
     awake and reachable over Tailscale.
- **No island-specific rendering logic in this pass.** The generic
  fetch-and-display panel described above stands in for every island until
  each one gets its own real build.

---

## 5. Credential handling

- Tokens are written to the OS keychain out-of-band (a one-time setup step,
  manual or via a small CLI helper — not part of the shell UI in this pass).
- The shell only ever reads credentials by `credential_ref` at request time;
  it never displays, logs, or persists the raw token value anywhere,
  including in error messages.

---

## 6. Networking behavior

- All island endpoints are expected to be reachable over Tailscale
  (`*.ts.net` addresses) or localhost (for the home PC's own local-agent
  island, once that exists).
- Requests should have a short, explicit timeout (a few seconds) rather than
  hanging — an unreachable home PC should fail fast and visibly, not freeze
  the pane.
- No retry/backoff logic needed in this pass — a manual "retry" action in the
  failed-fetch state is sufficient.

---

## 7. Acceptance criteria for this build pass

- App launches on macOS (Intel and Apple Silicon) and on the home PC's OS.
- Sidebar renders entries strictly from whatever manifest file is present —
  swapping the manifest file (with the app closed) changes what appears on
  next launch, with no code change.
- Selecting an island fetches from its configured endpoint and displays the
  raw response, or a clear failure state if unreachable.
- No credential value ever appears in the UI, logs, or manifest file.
- Two manifest files with different island lists, tested on two separate
  device profiles, produce visibly different sidebars — proving the scoping
  model actually holds.

---

## 8. Open questions to confirm before/while building

- Exact filesystem path convention for the manifest file across macOS vs the
  PC's OS.
- Whether manifest reload should be a manual action only, or also triggered
  automatically on file change (not required for this pass, but worth a
  decision either way).
- Whether the "generic fetch-and-display" panel should support anything
  beyond `GET` in this pass (later islands will need `POST` for actions like
  "process ticket" — confirm whether to build that affordance now or defer it
  to when the first real island is built against this shell).
