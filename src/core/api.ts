import { invoke } from "@tauri-apps/api/core";
import type { FetchOutcome, Island } from "./types";

export class ApiError extends Error {
  constructor(message: string, public code?: number) {
    super(message);
  }
}

/**
 * Shared request plumbing for one island. Resolves the credential in Rust (via
 * the `api_request` command — never seen here) and returns helpers each island's
 * typed `api.ts` builds its methods on:
 *   - `request(method, path, body)` — path is relative to the island's endpoint_base
 *   - `call(method, url, body)` — absolute url (for sibling resources)
 *   - `base` / `root` — the island endpoint and the orchestrator root
 */
export function islandClient(island: Island) {
  const base = island.endpoint_base.replace(/\/$/, "");
  // Orchestrator root (strip the island's trailing path segment) for siblings.
  const root = base.replace(/\/[^/]+$/, "");
  const cred = island.credential_ref;

  async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
    const outcome = await invoke<FetchOutcome>("api_request", {
      method,
      url,
      credentialRef: cred,
      body: body === undefined ? null : JSON.stringify(body),
    });
    if (outcome.status === "error") {
      throw new ApiError(outcome.message);
    }
    if (outcome.code >= 400) {
      let detail = `request failed (${outcome.code})`;
      try {
        const parsed = JSON.parse(outcome.body);
        if (parsed?.detail) detail = parsed.detail;
      } catch {
        /* non-JSON body */
      }
      throw new ApiError(detail, outcome.code);
    }
    return JSON.parse(outcome.body) as T;
  }

  const request = <T>(method: string, path: string, body?: unknown) =>
    call<T>(method, `${base}${path}`, body);

  return { base, root, call, request };
}
