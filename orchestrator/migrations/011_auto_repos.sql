-- Repos are now auto-created from tickets on sync (one per Jira project), so a
-- repo row often exists before we know its git remote. Relax the NOT NULL:
-- the only field dispatch truly needs is local_path (the checkout), which the
-- user binds via the repo picker.

alter table repos alter column git_remote_url drop not null;
