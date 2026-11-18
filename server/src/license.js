function tierMap(env) {
  try {
    return JSON.parse(env.TIER_MAP || "{}");
  } catch {
    return {};
  }
}

async function polar(env, key) {
  const base = env.POLAR_API_URL || "https://api.polar.sh";
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
  const tier = tierMap(env)[d.benefit_id] || null;
  const status = expired ? "expired" : d.status || "unknown";
  return {
    ok: status === "granted" && !!tier,
    tier,
    status: status === "granted" && !tier ? "unknown_plan" : status,
    customer: (d.customer && (d.customer.email || d.customer.name)) || d.customer_id || "",
    expiresAt: d.expires_at || null,
  };
}

async function lemonsqueezy(env, key) {
  const base = env.LS_API_URL || "https://api.lemonsqueezy.com";
  const r = await fetch(base + "/v1/licenses/validate", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ license_key: key }).toString(),
  });
  if (r.status >= 500) throw new Error(`license check failed (${r.status})`);
  const d = await r.json().catch(() => ({}));
  const lk = d.license_key || {};
  const meta = d.meta || {};
  if (!d.valid && !lk.status) return { ok: false, status: "invalid" };
  if (env.LS_STORE_ID && String(meta.store_id) !== String(env.LS_STORE_ID)) return { ok: false, status: "invalid" };
  const map = tierMap(env);
  const tier = map[String(meta.variant_id)] || map[String(meta.product_id)] || null;
  const status = lk.status || (d.valid ? "active" : "invalid");
  return {
    ok: !!d.valid && status === "active" && !!tier,
    tier,
    status: status === "active" && !tier ? "unknown_plan" : status,
    customer: meta.customer_email || meta.customer_name || "",
    expiresAt: lk.expires_at || null,
  };
}

export async function checkLicense(env, key) {
  const provider = (env.LICENSE_PROVIDER || "polar").toLowerCase();
  if (provider === "lemonsqueezy") return lemonsqueezy(env, key);
  return polar(env, key);
}

export async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
