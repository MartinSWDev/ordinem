# ordinem

Dashboard shell for personal islands (ticket workflow, todos/calendar,
home PC stats, etc.), built with Tauri + Vue. See
[plans/mac-app-plan.MD](plans/mac-app-plan.MD) for the full build spec.

This is the shell only: sidebar navigation driven entirely by a per-device
manifest file, and a generic fetch-and-display panel per island. No
island-specific logic, no styling.

## Device manifest

On launch the app reads `~/.ordinem/manifest.json`. This file is not part of
the repo and is expected to differ per machine. Example:

```json
{
  "device_name": "work-macbook-air",
  "islands": [
    {
      "id": "tickets",
      "title": "Tickets",
      "endpoint_base": "http://127.0.0.1:8787/tickets",
      "credential_ref": "",
      "component": "tickets"
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

`credential_ref` is a lookup key, not a secret — leave it `""` to skip auth
(e.g. the local orchestrator). When set, the token is resolved at request time
from the OS keychain (service name `ordinem`, account name equal to
`credential_ref`). Add tokens out-of-band, e.g. on macOS:

```sh
security add-generic-password -a shared_api_token -s ordinem -w "<token value>"
```

`component` selects a custom UI for an island (currently `"tickets"` — the
clickable ticket-workflow board that talks to the orchestrator). Omit it and
the island falls back to the generic fetch-and-display panel.

Use the "Reload config" button in the sidebar to re-read the manifest
without restarting the app.

## Development

```sh
npm install
npm run tauri dev
```

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/) + [Vue - Official](https://marketplace.visualstudio.com/items?itemName=Vue.volar) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
