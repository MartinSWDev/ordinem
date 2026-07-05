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
      "id": "ticket-workflow",
      "title": "Tickets",
      "endpoint_base": "https://orchestrator.<tailnet>.ts.net/api/tickets",
      "credential_ref": "work_api_token"
    }
  ]
}
```

`credential_ref` is a lookup key, not a secret. The actual token is resolved
at request time from the OS keychain (service name `ordinem`, account name
equal to `credential_ref`). Add tokens out-of-band, e.g. on macOS:

```sh
security add-generic-password -a work_api_token -s ordinem -w "<token value>"
```

Use the "Reload config" button in the sidebar to re-read the manifest
without restarting the app.

## Development

```sh
npm install
npm run tauri dev
```

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/) + [Vue - Official](https://marketplace.visualstudio.com/items?itemName=Vue.volar) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
