function tierFor(env, ...ids) {
  let map = {};
  try {
    map = JSON.parse(env.TIER_MAP || "{}");
  } catch {
  }
  for (const id of ids) {
    const k = String(id ?? "");
    if (k && map && typeof map === "object" && Object.hasOwn(map, k) && typeof map[k] === "string") return map[k];
  }
  return null;
}

export function localOnly(url, fallback) {
  try {
    const u = new URL(url);
    if (u.protocol === "http:" && (u.hostname === "127.0.0.1" || u.hostname === "localhost")) return url.replace(/\/+$/, "");
  } catch {
  }
  return fallback;
}

async function polar(env, key) {
  const base = localOnly(env.POLAR_API_URL, "https://api.polar.sh");
  const path = env.POLAR_TOKEN ? "/v1/license-keys/validate" : "/v1/customer-portal/license-keys/validate";
  const headers = { "content-type": "application/json", accept: "application/json" };
  if (env.POLAR_TOKEN) headers.authorization = `Bearer ${env.POLAR_TOKEN}`;
  const r = await fetch(base + path, {
    method: "POST",
    headers,
    body: JSON.stringify({ key, organization_id: env.POLAR_ORG_ID }),
  });
  if (r.status === 404 || r.status === 422 || r.status === 400) return { ok: false, status: "invalid" };
  if (!r.ok) throw new Error(`license check failed (${r.status})`);
  const d = await r.json();
  const expired = d.expires_at && Date.parse(d.expires_at) < Date.now();
  const tier = tierFor(env, d.benefit_id);
  const status = expired ? "expired" : d.status || "unknown";
  return {
    ok: status === "granted" && !!tier,
    tier,
    status: status === "granted" && !tier ? "unknown_plan" : status,
    customer: maskEmail(d.customer && d.customer.email),
    expiresAt: d.expires_at || null,
  };
}

async function lemonsqueezy(env, key) {
  const base = localOnly(env.LS_API_URL, "https://api.lemonsqueezy.com");
  const r = await fetch(base + "/v1/licenses/validate", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ license_key: key }).toString(),
  });
  if (r.status === 404) return { ok: false, status: "invalid" };
  if (!r.ok) throw new Error(`license check failed (${r.status})`);
  const d = await r.json();
  const lk = d.license_key || {};
  const meta = d.meta || {};
  if (!d.license_key) return { ok: false, status: "invalid" };
  if (!env.LS_STORE_ID) throw new Error("LS_STORE_ID isn't set");
  if (String(meta.store_id) !== String(env.LS_STORE_ID)) return { ok: false, status: "invalid" };
  const tier = tierFor(env, meta.variant_id, meta.product_id);
  const expired = lk.expires_at && Date.parse(lk.expires_at) < Date.now();
  const raw = expired ? "expired" : lk.status || "unknown";
  const usable = raw === "active" || raw === "inactive";
  return {
    ok: usable && !!tier,
    tier,
    status: usable ? (tier ? "granted" : "unknown_plan") : raw,
    customer: maskEmail(meta.customer_email),
    expiresAt: lk.expires_at || null,
  };
}

export async function checkLicense(env, key) {
  const provider = (env.LICENSE_PROVIDER || "polar").toLowerCase();
  if (provider === "lemonsqueezy") return lemonsqueezy(env, key);
  return polar(env, key);
}

export function maskEmail(email) {
  const m = /^([^@\s]+)@([^@\s]+)$/.exec(String(email || "").trim());
  if (!m) return "";
  return `${m[1].slice(0, 1)}•••@${m[2]}`;
}

export async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function keyHash(env, key) {
  const enc = new TextEncoder();
  const k = await crypto.subtle.importKey("raw", enc.encode(env.KEY_PEPPER || "sc-copilot"), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(key));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
