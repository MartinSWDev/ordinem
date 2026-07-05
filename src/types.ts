export interface Island {
  id: string;
  title: string;
  endpoint_base: string;
  credential_ref: string;
  /** Optional custom component key (e.g. "tickets"). Falls back to generic panel. */
  component?: string | null;
}

export interface Manifest {
  device_name: string;
  islands: Island[];
}

export type FetchOutcome =
  | { status: "ok"; code: number; body: string }
  | { status: "error"; message: string };

// --- Orchestrator ticket domain --------------------------------------------

export type TicketStatus =
  | "new"
  | "planned"
  | "in_progress"
  | "review"
  | "checks_failed"
  | "ready_to_push"
  | "pushed"
  | "done"
  | "abandoned";

export type SubtaskStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface Ticket {
  id: string;
  repo_id: string | null;
  jira_project_key: string | null;
  jira_key: string;
  title: string;
  description: string | null;
  raw_jira: Record<string, any> | null;
  processing_instructions: string | null;
  branch_name: string | null;
  status: TicketStatus;
  actionable: boolean;
  created_at: string;
  updated_at: string;
}

export interface Subtask {
  id: string;
  ticket_id: string;
  title: string;
  description: string | null;
  order_index: number;
  status: SubtaskStatus;
  backend: string | null;
  error: string | null;
}

export interface TicketDetail {
  ticket: Ticket;
  subtasks: Subtask[];
}

export interface MyTicketsSyncResult {
  synced: number;
  tickets: Ticket[];
  unregistered_projects: string[];
}
