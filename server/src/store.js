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
  return row || { replies: 0, web: 0, smart: 0, calls: 0, smart_calls: 0, input_tokens: 0, output_tokens: 0, cache_read: 0, cache_write: 0, cost_micro: 0 };
}

export function addUsage(db, keyHash, period, d) {
  return db.prepare(
    "INSERT INTO usage (key_hash, period, replies, web, smart, calls, smart_calls, input_tokens, output_tokens, cache_read, cache_write, cost_micro) " +
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key_hash, period) DO UPDATE SET " +
    "replies = replies + excluded.replies, web = web + excluded.web, smart = smart + excluded.smart, " +
    "calls = calls + excluded.calls, smart_calls = smart_calls + excluded.smart_calls, " +
    "input_tokens = input_tokens + excluded.input_tokens, output_tokens = output_tokens + excluded.output_tokens, " +
    "cache_read = cache_read + excluded.cache_read, cache_write = cache_write + excluded.cache_write, " +
    "cost_micro = cost_micro + excluded.cost_micro"
  ).bind(keyHash, period, d.replies || 0, d.web || 0, d.smart || 0, d.calls || 0, d.smart_calls || 0, d.input_tokens || 0, d.output_tokens || 0,
    d.cache_read || 0, d.cache_write || 0, d.cost_micro || 0);
}

export async function bump(db, key, now, slotMs = 60000) {
  const slot = Math.floor(now / slotMs);
  const row = await db.prepare(
    "INSERT INTO minute (key_hash, slot, n) VALUES (?, ?, 1) ON CONFLICT(key_hash, slot) DO UPDATE SET n = n + 1 RETURNING n"
  ).bind(key, slot).first();
  return row ? row.n : 1;
}

export async function bumpMinute(db, keyHash, now) {
  return bump(db, keyHash, now, 60000);
}

export async function tidy(db, now) {
  await db.batch([
    db.prepare("DELETE FROM minute WHERE slot < ? AND key_hash NOT LIKE '%:%'").bind(Math.floor(now / 60000) - 5),
    db.prepare("DELETE FROM minute WHERE slot < ? AND key_hash LIKE 'ip:%'").bind(Math.floor(now / 600000) - 2),
    db.prepare("DELETE FROM minute WHERE slot < ? AND key_hash LIKE 'trialnet%'").bind(Math.floor(now / 86400000) - 2),
    db.prepare("DELETE FROM licenses WHERE ok = 0 AND status = 'invalid' AND checked_at < ?").bind(now - 3600000),
    db.prepare("DELETE FROM tool_ids WHERE at < ?").bind(now - 3600000),
    db.prepare("DELETE FROM inflight WHERE started_at < ?").bind(now - 3600000),
    db.prepare("DELETE FROM minute WHERE slot < ? AND key_hash LIKE 'provider:%'").bind(Math.floor(now / 60000) - 5),
  ]);
}

export async function seeDevice(db, keyHash, device, now, windowDays, maxDevices) {
  if (!device) return false;
  const since = now - windowDays * 86400000;
  const known = await db.prepare("SELECT last_seen FROM devices WHERE key_hash = ? AND device = ?").bind(keyHash, device).first();
  if (known && known.last_seen >= now - 3600000) return true;
  const row = await db.prepare(
    "INSERT INTO devices (key_hash, device, last_seen) SELECT ?1, ?2, ?3 " +
    "WHERE EXISTS (SELECT 1 FROM devices WHERE key_hash = ?1 AND device = ?2 AND last_seen >= ?4) " +
    "OR (SELECT COUNT(*) FROM devices WHERE key_hash = ?1 AND device != ?2 AND last_seen >= ?4) < ?5 " +
    "ON CONFLICT(key_hash, device) DO UPDATE SET last_seen = excluded.last_seen RETURNING device"
  ).bind(keyHash, device, now, since, maxDevices).first();
  return !!row;
}

export async function trialOwner(db, device) {
  const row = await db.prepare("SELECT key_hash FROM trials WHERE device = ?").bind(device).first();
  return row ? row.key_hash : null;
}

export async function addTrial(db, device, keyHash, now) {
  await db.prepare("INSERT INTO trials (device, key_hash, first_seen) VALUES (?, ?, ?) ON CONFLICT(device) DO NOTHING")
    .bind(device, keyHash, now).run();
  return (await trialOwner(db, device)) === keyHash;
}

export function ensureUsage(db, keyHash, period) {
  return db.prepare("INSERT INTO usage (key_hash, period) VALUES (?, ?) ON CONFLICT(key_hash, period) DO NOTHING").bind(keyHash, period);
}

export function reserveKey(db, keyHash, period, d, lim) {
  return db.prepare(
    "UPDATE usage SET replies = replies + ?1, smart = smart + ?2, calls = calls + 1, smart_calls = smart_calls + ?3, web = web + ?4, " +
    "cost_micro = cost_micro + ?5 WHERE key_hash = ?6 AND period = ?7 AND cost_micro + ?5 <= ?8 AND calls < ?9 " +
    "AND (?1 = 0 OR replies + ?1 <= ?10) AND (?2 = 0 OR smart + ?2 <= ?11) AND (?3 = 0 OR smart_calls + ?3 <= ?12) " +
    "AND (?4 = 0 OR web + ?4 <= ?13) RETURNING cost_micro"
  ).bind(d.replies, d.smart, d.smart_calls, d.web, d.cost, keyHash, period, lim.cost, lim.calls, lim.replies, lim.smart, lim.smartCalls, lim.web);
}

export async function enterFlight(db, keyHash, id, now, max, staleMs) {
  const row = await db.prepare(
    "INSERT INTO inflight (key_hash, id, started_at) SELECT ?1, ?2, ?3 " +
    "WHERE (SELECT COUNT(*) FROM inflight WHERE key_hash = ?1 AND started_at >= ?4) < ?5 RETURNING id"
  ).bind(keyHash, id, now, now - staleMs, max).first();
  return !!row;
}

export function leaveFlight(db, keyHash, id) {
  return db.prepare("DELETE FROM inflight WHERE key_hash = ? AND id = ?").bind(keyHash, id);
}

export function reserveDay(db, keyHash, day, replies, lim) {
  return db.prepare(
    "UPDATE usage SET replies = replies + ?1, calls = calls + 1 WHERE key_hash = ?2 AND period = ?3 AND calls < ?4 " +
    "AND (?1 = 0 OR replies + ?1 <= ?5) RETURNING calls"
  ).bind(replies, keyHash, day, lim.calls, lim.replies);
}

export function reserveBudget(db, key, day, cost, limitMicro) {
  return db.prepare(
    "UPDATE usage SET calls = calls + 1, cost_micro = cost_micro + ?1 WHERE key_hash = ?2 AND period = ?3 " +
    "AND (?4 <= 0 OR cost_micro + ?1 <= ?4) RETURNING cost_micro"
  ).bind(cost, key, day, limitMicro);
}

export function rememberToolIds(db, keyHash, ids, now) {
  return db.batch(ids.map((id) => db.prepare("INSERT INTO tool_ids (key_hash, id, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING").bind(keyHash, id, now)));
}

export async function knownToolIds(db, keyHash, ids, since) {
  const marks = ids.map(() => "?").join(", ");
  const row = await db.prepare(`SELECT COUNT(*) AS n FROM tool_ids WHERE key_hash = ? AND at >= ? AND id IN (${marks})`)
    .bind(keyHash, since, ...ids).first();
  return row ? row.n : 0;
}

export function forgetToolIds(db, keyHash, ids) {
  const marks = ids.map(() => "?").join(", ");
  return db.prepare(`DELETE FROM tool_ids WHERE key_hash = ? AND id IN (${marks})`).bind(keyHash, ...ids);
}
