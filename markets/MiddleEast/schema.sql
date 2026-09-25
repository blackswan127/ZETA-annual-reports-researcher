PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS issuers (
  issuer_id TEXT PRIMARY KEY,
  iso3 TEXT NOT NULL,
  mic TEXT NOT NULL,
  ticker TEXT NOT NULL,
  company_name TEXT NOT NULL,
  isin TEXT,
  lei TEXT,
  fiscal_year_end TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  universe_source TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expected_slots (
  issuer_id TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  required_class TEXT NOT NULL DEFAULT 'AR_FULL',
  status TEXT NOT NULL DEFAULT 'PENDING',
  selected_candidate_id TEXT,
  PRIMARY KEY (issuer_id, fiscal_year, required_class)
);

CREATE TABLE IF NOT EXISTS candidates (
  candidate_id TEXT PRIMARY KEY,
  issuer_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  direct_url TEXT,
  title TEXT,
  publication_date TEXT,
  period_end TEXT,
  resolved_fy INTEGER,
  fy_confidence REAL,
  language TEXT,
  language_confidence REAL,
  document_class TEXT NOT NULL,
  class_confidence REAL,
  discovered_at TEXT NOT NULL,
  UNIQUE(issuer_id, source_url)
);

CREATE TABLE IF NOT EXISTS downloads (
  candidate_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  bytes_downloaded INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  sha256 TEXT,
  local_path TEXT,
  error TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_profiles (
  source_key TEXT PRIMARY KEY,
  host TEXT NOT NULL,
  adapter TEXT NOT NULL,
  requests_per_second REAL NOT NULL DEFAULT 1.0,
  max_concurrency INTEGER NOT NULL DEFAULT 2,
  health TEXT NOT NULL DEFAULT 'UNKNOWN',
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  terms_reviewed INTEGER NOT NULL DEFAULT 0,
  last_success TEXT,
  last_failure TEXT
);
