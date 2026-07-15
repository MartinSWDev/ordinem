import { islandClient } from "../../core/api";
import type { Island } from "../../core/types";
import type {
  CheckRun,
  CommitPlan,
  MyTicketsSyncResult,
  NewLocalTicket,
  PrDraft,
  RepoRef,
  Ticket,
  TicketDetail,
} from "./types";

export { ApiError } from "../../core/api";

/** Tickets-island client: everything hangs off the island's `/tickets` base,
 *  except commit-plan approval, which targets the `/commit-plans` sibling. */
export function useTickets(island: Island) {
  const { base, root, call, request } = islandClient(island);

  return {
    /** Direct URL for an <img> src — bypasses api_request; the local
     *  orchestrator streams the bytes with Jira auth. */
    attachmentUrl: (ticketId: string, index: number) =>
      `${base}/${ticketId}/attachments/${index}`,
    listTickets: (project?: string) =>
      request<Ticket[]>("GET", `${project ? `?project=${encodeURIComponent(project)}` : ""}`),
    syncMyTickets: () => request<MyTicketsSyncResult>("POST", "/sync"),
    listRepos: () => request<RepoRef[]>("GET", "/repos"),
    createLocalTicket: (t: NewLocalTicket) => request<Ticket>("POST", "/local", t),
    getTicket: (id: string) => request<TicketDetail>("GET", `/${id}`),
    processTicket: (id: string, branchName: string, confirmDocker: boolean) =>
      request<TicketDetail>("POST", `/${id}/process`, {
        branch_name: branchName,
        confirm_active_docker_project: confirmDocker,
      }),
    // --- review & ship ---
    runChecks: (id: string) => request<CheckRun>("POST", `/${id}/checks`),
    draftCommitPlan: (id: string) => request<CommitPlan>("POST", `/${id}/commit-plan`, {}),
    approveCommitPlan: (planId: string, editedMessage: string | null) =>
      call<CommitPlan>("POST", `${root}/commit-plans/${planId}/approve`, {
        edited_message: editedMessage,
      }),
    generatePrDraft: (id: string) => request<PrDraft>("POST", `/${id}/pr-draft`),
    markPrOpened: (id: string, prUrl: string) =>
      request<PrDraft>("POST", `/${id}/pr-draft/opened`, { pr_url: prUrl }),
  };
}
