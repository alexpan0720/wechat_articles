-- PostgreSQL/Supabase bootstrap migration. The application also supports `python -m app.cli init-db`.
create table if not exists source_accounts (
  id varchar(36) primary key,
  account_name varchar(200) not null,
  account_identifier varchar(200) not null unique,
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists articles (
  id varchar(36) primary key,
  source_account_id varchar(36) not null references source_accounts(id),
  source_article_id varchar(300) not null,
  title varchar(500) not null,
  slug varchar(550) not null unique,
  summary text,
  author varchar(200),
  cover_url text,
  source_url text not null,
  content_html text not null default '',
  raw_html text not null default '',
  content_hash varchar(64) not null,
  status varchar(32) not null default 'processing',
  failure_reason text,
  published_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_source_article unique (source_account_id, source_article_id)
);
create index if not exists ix_articles_status_published on articles(status, published_at);

create table if not exists article_versions (
  id varchar(36) primary key,
  article_id varchar(36) not null references articles(id) on delete cascade,
  version integer not null,
  raw_html text not null,
  content_html text not null,
  content_hash varchar(64) not null,
  created_at timestamptz not null default now(),
  constraint uq_article_version unique(article_id, version)
);

create table if not exists article_assets (
  id varchar(36) primary key,
  article_id varchar(36) not null references articles(id) on delete cascade,
  source_url text not null,
  storage_path text,
  media_type varchar(100) not null default 'image',
  status varchar(32) not null default 'pending',
  checksum varchar(64),
  error text
);

create table if not exists sync_runs (
  id varchar(36) primary key,
  trigger varchar(50) not null default 'manual',
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  result varchar(32) not null default 'running',
  success_count integer not null default 0,
  skipped_count integer not null default 0,
  failed_count integer not null default 0,
  error text
);

create table if not exists sync_items (
  id varchar(36) primary key,
  run_id varchar(36) not null references sync_runs(id) on delete cascade,
  source_article_id varchar(300) not null,
  article_id varchar(36) references articles(id),
  status varchar(32) not null,
  error_code varchar(100),
  message text,
  attempts integer not null default 1,
  created_at timestamptz not null default now()
);

create table if not exists admin_profiles (
  id varchar(36) primary key,
  username varchar(100) not null unique,
  password_hash varchar(500) not null,
  role varchar(50) not null default 'admin',
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

-- For Supabase deployments, expose public article data through a read-only view or API.
-- Never grant anonymous access to raw_html, sync tables, or admin_profiles.

