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

export interface JiraComment {
  author: string | null;
  created: string | null;
  body: string;
}

export interface JiraLink {
  relation: string | null;
  direction: "inward" | "outward";
  key: string | null;
  summary: string | null;
  status: string | null;
}

export interface JiraSubtask {
  key: string | null;
  summary: string | null;
  status: string | null;
}

export interface JiraAttachment {
  filename: string | null;
  url: string | null;
  size: number | null;
  mime: string | null;
}

/** Curated, LLM-useful projection of the Jira issue (replaces raw_jira). */
export interface NormalizedJira {
  key: string;
  url: string;
  summary: string | null;
  issue_type: string | null;
  status: string | null;
  status_category: string | null;
  priority: string | null;
  labels: string[];
  components: string[];
  assignee: string | null;
  reporter: string | null;
  created: string | null;
  updated: string | null;
  due_date: string | null;
  fix_versions: string[];
  parent: { key: string | null; summary: string | null } | null;
  description: string | null;
  acceptance_criteria: string | null;
  subtasks: JiraSubtask[];
  links: JiraLink[];
  comments: JiraComment[];
  attachments: JiraAttachment[];
}

export interface Ticket {
  id: string;
  repo_id: string | null;
  jira_project_key: string | null;
  jira_key: string;
  title: string;
  description: string | null;
  jira: NormalizedJira | null;
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

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string | null;
  calendar_name: string;
}
