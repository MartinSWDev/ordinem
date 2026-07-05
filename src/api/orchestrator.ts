import { invoke } from "@tauri-apps/api/core";
import type {
  FetchOutcome,
  Island,
  MyTicketsSyncResult,
  Ticket,
  TicketDetail,
} from "../types";

export class ApiError extends Error {
  constructor(message: string, public code?: number) {
    super(message);
  }
}

/**
 * Thin client over the Rust `api_request` command for one island. The island's
 * `endpoint_base` is the orchestrator's `/tickets` root; sub-paths hang off it.
 * The credential is resolved in Rust from the keychain (never seen here).
 */
export function useOrchestrator(island: Island) {
  const base = island.endpoint_base.replace(/\/$/, "");
  const cred = island.credential_ref;

  async function request<T>(
    method: string,
    path: string,
    body?: unknown
  ): Promise<T> {
    const outcome = await invoke<FetchOutcome>("api_request", {
      method,
      url: `${base}${path}`,
      credentialRef: cred,
      body: body === undefined ? null : JSON.stringify(body),
    });
    if (outcome.status === "error") {
      throw new ApiError(outcome.message);
    }
    if (outcome.code >= 400) {
      // Surface the orchestrator's `detail` message when present.
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

  return {
    /** Direct URL to the attachment proxy — for use as an <img> src (bypasses
     * api_request; the local orchestrator streams the bytes with Jira auth). */
    attachmentUrl: (ticketId: string, index: number) =>
      `${base}/${ticketId}/attachments/${index}`,
    listTickets: (project?: string) =>
      request<Ticket[]>("GET", `${project ? `?project=${encodeURIComponent(project)}` : ""}`),
    syncMyTickets: () => request<MyTicketsSyncResult>("POST", "/sync"),
    getTicket: (id: string) => request<TicketDetail>("GET", `/${id}`),
    processTicket: (id: string, branchName: string, confirmDocker: boolean) =>
      request<TicketDetail>("POST", `/${id}/process`, {
        branch_name: branchName,
        confirm_active_docker_project: confirmDocker,
      }),
  };
}
