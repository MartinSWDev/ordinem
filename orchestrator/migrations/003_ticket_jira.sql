-- Store a curated, LLM-useful projection of the Jira issue alongside the raw
-- payload. raw_jira stays (debugging), but the API returns `jira` — comments,
-- acceptance criteria, labels, links, attachments, etc. — instead of the
-- ~120-key firehose.

alter table tickets add column jira jsonb;
