import { islandClient } from "../../core/api";
import type { Island } from "../../core/types";
import type {
  AgentBackend,
  CheckRun,
  CommitPlan,
  MyTicketsSyncResult,
  NewLocalTicket,
  PrDraft,
  ProposedSubtask,
  RepoRef,
  Subtask,
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
    /** Live-probed dispatch targets (claude / cursor / local) for the picker. */
    listBackends: () => request<AgentBackend[]>("GET", "/backends"),
    createLocalTicket: (t: NewLocalTicket) => request<Ticket>("POST", "/local", t),
    /** refresh=false skips the Jira re-fetch — use it when polling. */
    getTicket: (id: string, refresh = true) =>
      request<TicketDetail>("GET", `/${id}${refresh ? "" : "?refresh=false"}`),
    processTicket: (id: string, branchName: string, confirmDocker: boolean, backend: string) =>
      request<TicketDetail>("POST", `/${id}/process`, {
        branch_name: branchName,
        confirm_active_docker_project: confirmDocker,
        backend,
      }),
    // --- plan -> gate -> dispatch ---
    /** Ask the planner for mini-tickets. Nothing runs until you approve. */
    planTicket: (id: string) => request<Subtask[]>("POST", `/${id}/plan`),
    /** The gate: your final list becomes the dispatchable work. */
    approvePlan: (id: string, miniTickets: ProposedSubtask[]) =>
      request<Subtask[]>("POST", `/${id}/plan/approve`, { mini_tickets: miniTickets }),
    dispatchPlan: (id: string, branchName: string, confirmDocker: boolean, backend: string) =>
      request<TicketDetail>("POST", `/${id}/dispatch`, {
        branch_name: branchName,
        confirm_active_docker_project: confirmDocker,
        backend,
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
