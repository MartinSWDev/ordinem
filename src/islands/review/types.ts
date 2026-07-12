// Review island — pre-PR review domain types.

export interface RepoRef {
  id: string;
  name: string;
  jira_project_key: string;
  git_remote_url: string;
  docker_compose_path: string | null;
  local_path: string | null;
  default_branch: string;
  created_at: string;
}

export interface ReviewFinding {
  file: string;
  line: number | null;
  severity: "high" | "medium" | "low";
  category: string;
  comment: string;
  suggestion: string | null;
}

export interface ReviewResult {
  summary: string;
  findings: ReviewFinding[];
}

export interface Review {
  id: string;
  repo_id: string;
  base_branch: string;
  head_branch: string;
  result: ReviewResult;
  created_at: string;
}
