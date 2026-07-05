-- X Lead Generator — Supabase schema
-- Run this once in the Supabase SQL editor.

-- Never-scan-twice guarantee: every tweet ID that survives cheap pre-filters
-- is written here BEFORE any LLM call. Rejected or scored, it never comes back.
create table if not exists x_seen_tweets (
  tweet_id text primary key,
  first_seen_run text,
  first_seen_at timestamptz default now()
);

create table if not exists x_leads (
  tweet_id text primary key,
  author_id text,
  handle text,
  author_name text,
  text text,
  bio text,
  location text,
  followers integer,
  tweet_url text,
  niche text,
  tweet_type text,
  query_id text,
  score integer,
  confidence integer,
  score_json jsonb,
  styles_used text[],
  reply_draft_a text,
  reply_draft_b text,
  dm_draft text,
  status text default 'delivered', -- delivered | borderline | rejected | replied | converted
  tweet_created_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists x_runs (
  run_id text primary key,
  started_at timestamptz default now(),
  finished_at timestamptz,
  query_stats jsonb,
  tweets_scraped integer default 0,
  seen_skipped integer default 0,
  prefiltered integer default 0,
  scored integer default 0,
  delivered integer default 0,
  borderline integer default 0,
  est_cost_usd numeric(8,4) default 0
);

create index if not exists idx_x_leads_status on x_leads (status);
create index if not exists idx_x_leads_created on x_leads (created_at desc);
create index if not exists idx_x_runs_started on x_runs (started_at desc);
