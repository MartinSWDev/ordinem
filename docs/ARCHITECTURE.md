# Architecture — the island pattern

Ordinem is a dashboard made of **islands**. Each island is one self-contained
feature (Tickets, Calendar, Review, …) with a **frontend folder** and a
**backend package**, over a thin shared core. Which islands appear on a device
is controlled entirely by `~/.ordinem/manifest.json` — nothing is hardcoded.

> **For future agents: follow this pattern.** A new feature = a new island. Give
> it its own frontend folder and backend package, each with a `README.md`. Do
> not scatter its code across shared files. See "Adding an island" below.

## The three pieces

```
Tauri shell (src/)  ──api_request──▶  orchestrator (orchestrator/)  ──▶  Postgres / Jira / LLM
   manifest-driven islands              per-island FastAPI routers
```

- **Shell** (`src/`) — Vue + Tauri. Reads the manifest, renders one island's
  component in the main pane. Credentials resolve in Rust from the OS keychain.
- **Orchestrator** (`orchestrator/`) — Python/FastAPI. One package per island;
  each island exposes its endpoints under a path (`/tickets`, `/calendar`, …).
- An island's manifest `endpoint_base` points the shell at that island's routes.

## Frontend layout (`src/`)

```
core/            shell types (Island/Manifest/FetchOutcome), api base (islandClient), IslandPanel
ui/              shared neumorphic design system (N* components, LinkedText, tokens.css)
islands/
  <name>/        <Name>Island.vue · api.ts (use<Name>) · types.ts · README.md
App.vue          reads manifest, maps island.component -> component (islandComponents)
main.ts
```

- Each island's `api.ts` builds its typed methods on `core/api.ts`'s
  `islandClient(island)` — never calls `invoke` directly.
- Shared design-system components live in `ui/`; islands import from there.
- Islands **do not import each other**.

## Backend layout (`orchestrator/app/`)

```
core/            config.py · db.py · deps.py · repos.py (shared "registered repos")
islands/
  <name>/        router.py · schemas.py · repository.py · services/ · README.md
migrations/      central, numbered .sql (ordering matters across islands)
main.py          wires the shared core + registers every island's routers
tests/<name>/    tests per island
```

- Island packages use **absolute imports** (`from app.core.config import …`,
  `from app.islands.tickets import repository`).
- Shared-across-islands data (`repos`) lives in `core/repos.py`. Everything else
  is island-local.
- Migrations stay central and numbered so cross-island ordering is well-defined.
- `main.py` imports each island's router(s) and registers them.

## Adding an island

1. **Backend** — `orchestrator/app/islands/<name>/`: `router.py` (an `APIRouter`
   with `prefix="/<name>"`), `schemas.py`, `repository.py` (if it has tables),
   `services/` (external integrations), and a `README.md`. Add any new tables as
   a new numbered file in `migrations/`. Register the router in `app/main.py`.
   Add tests under `tests/<name>/`.
2. **Frontend** — `src/islands/<name>/`: `<Name>Island.vue`, `api.ts`
   (`use<Name>(island)` over `islandClient`), `types.ts`, `README.md`. Register
   the component in `src/App.vue`'s `islandComponents` map under a `component`
   key. Reuse `src/ui/` for styling.
3. **Manifest** — document a sample island entry in the top-level `README.md`
   (`endpoint_base` → the orchestrator route, `component` → your key).
4. Keep the island self-contained: shared code goes to `core/` (backend) or
   `core/`/`ui/` (frontend), never cross-island imports.
