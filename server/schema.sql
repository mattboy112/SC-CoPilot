CREATE TABLE IF NOT EXISTS licenses (
  key_hash TEXT PRIMARY KEY,
  ok INTEGER NOT NULL,
  tier TEXT,
  status TEXT,
  customer TEXT,
  expires_at TEXT,
  checked_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
  key_hash TEXT NOT NULL,
  period TEXT NOT NULL,
  replies INTEGER NOT NULL DEFAULT 0,
  web INTEGER NOT NULL DEFAULT 0,
  smart INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read INTEGER NOT NULL DEFAULT 0,
  cache_write INTEGER NOT NULL DEFAULT 0,
  cost_micro INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (key_hash, period)
);

CREATE TABLE IF NOT EXISTS minute (
  key_hash TEXT NOT NULL,
  slot INTEGER NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (key_hash, slot)
);

CREATE TABLE IF NOT EXISTS devices (
  key_hash TEXT NOT NULL,
  device TEXT NOT NULL,
  last_seen INTEGER NOT NULL,
  PRIMARY KEY (key_hash, device)
);
