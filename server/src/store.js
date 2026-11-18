export function periodKey(tier, now = new Date()) {
  return tier && tier.lifetime ? "life" : now.toISOString().slice(0, 7);
}

export function dayKey(now = new Date()) {
  return "d:" + now.toISOString().slice(0, 10);
}

export function resetsAt(tier, now = new Date()) {
  if (tier && tier.lifetime) return null;
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1)).toISOString();
}

export async function getLicense(db, keyHash) {
  return db.prepare("SELECT * FROM licenses WHERE key_hash = ?").bind(keyHash).first();
}

export async function putLicense(db, keyHash, lic, now) {
  await db.prepare(
    "INSERT INTO licenses (key_hash, ok, tier, status, customer, expires_at, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?) " +
    "ON CONFLICT(key_hash) DO UPDATE SET ok = excluded.ok, tier = excluded.tier, status = excluded.status, " +
    "customer = excluded.customer, expires_at = excluded.expires_at, checked_at = excluded.checked_at"
  ).bind(keyHash, lic.ok ? 1 : 0, lic.tier || null, lic.status || null, lic.customer || "", lic.expiresAt || null, now).run();
}

export async function getUsage(db, keyHash, period) {
  const row = await db.prepare("SELECT * FROM usage WHERE key_hash = ? AND period = ?").bind(keyHash, period).first();
  return row || { replies: 0, web: 0, smart: 0, input_tokens: 0, output_tokens: 0, cache_read: 0, cache_write: 0, cost_micro: 0 };
}

export function addUsage(db, keyHash, period, d) {
  return db.prepare(
    "INSERT INTO usage (key_hash, period, replies, web, smart, input_tokens, output_tokens, cache_read, cache_write, cost_micro) " +
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key_hash, period) DO UPDATE SET " +
    "replies = replies + excluded.replies, web = web + excluded.web, smart = smart + excluded.smart, " +
    "input_tokens = input_tokens + excluded.input_tokens, output_tokens = output_tokens + excluded.output_tokens, " +
    "cache_read = cache_read + excluded.cache_read, cache_write = cache_write + excluded.cache_write, " +
    "cost_micro = cost_micro + excluded.cost_micro"
  ).bind(keyHash, period, d.replies || 0, d.web || 0, d.smart || 0, d.input_tokens || 0, d.output_tokens || 0,
    d.cache_read || 0, d.cache_write || 0, d.cost_micro || 0);
}

export async function bumpMinute(db, keyHash, now) {
  const slot = Math.floor(now / 60000);
  const row = await db.prepare(
    "INSERT INTO minute (key_hash, slot, n) VALUES (?, ?, 1) ON CONFLICT(key_hash, slot) DO UPDATE SET n = n + 1 RETURNING n"
  ).bind(keyHash, slot).first();
  if (Math.random() < 0.02) await db.prepare("DELETE FROM minute WHERE slot < ?").bind(slot - 5).run();
  return row ? row.n : 1;
}

export async function seeDevice(db, keyHash, device, now, windowDays, maxDevices) {
  if (!device) return true;
  const since = now - windowDays * 86400000;
  const known = await db.prepare("SELECT last_seen FROM devices WHERE key_hash = ? AND device = ?").bind(keyHash, device).first();
  if (!known || known.last_seen < since) {
    const row = await db.prepare(
      "SELECT COUNT(*) AS n FROM devices WHERE key_hash = ? AND last_seen >= ? AND device != ?"
    ).bind(keyHash, since, device).first();
    if ((row ? row.n : 0) >= maxDevices) return false;
  }
  await db.prepare(
    "INSERT INTO devices (key_hash, device, last_seen) VALUES (?, ?, ?) ON CONFLICT(key_hash, device) DO UPDATE SET last_seen = excluded.last_seen"
  ).bind(keyHash, device, now).run();
  return true;
}
