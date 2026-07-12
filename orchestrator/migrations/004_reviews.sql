-- Pre-PR reviewer: where the repo is checked out (for git diff), and a log of
-- reviews with their structured findings.

alter table repos add column local_path text;

create table reviews (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid not null references repos(id) on delete cascade,
  base_branch text not null,
  head_branch text not null,
  result jsonb not null,   -- { summary, findings: [...] }
  created_at timestamptz not null default now()
);

create index reviews_repo_idx on reviews (repo_id, created_at desc);
