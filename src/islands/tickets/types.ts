// Tickets island — orchestrator ticket domain types.

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
  /** Local (self-authored) tickets have no Jira key or curated `jira` view. */
  jira_key: string | null;
  source: "jira" | "local";
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

// --- Review & ship (checks / commit / PR) ----------------------------------

export interface CheckRun {
  id: string;
  ticket_id: string;
  check_name: string;
  status: "pass" | "fail" | "error";
  output: string | null;
  run_at: string;
}

export interface CommitPlan {
  id: string;
  ticket_id: string;
  subtask_id: string | null;
  proposed_message: string;
  files: unknown;
  status: "proposed" | "approved" | "edited" | "committed" | "rejected";
  sha: string | null;
  created_at: string;
}

export interface PrDraft {
  id: string;
  ticket_id: string;
  template_fields: Record<string, any>;
  status: "draft" | "opened";
  pr_url: string | null;
  created_at: string;
}

/** A registered repo — the new-ticket repo picker. */
export interface RepoRef {
  id: string;
  name: string;
  jira_project_key: string;
  local_path: string | null;
  default_branch: string;
}

export interface NewLocalTicket {
  title: string;
  repo_id: string;
  description?: string | null;
  processing_instructions?: string | null;
}
