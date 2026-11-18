export const STANDARD_MODEL = "claude-haiku-5-5";
export const SMART_MODEL = "claude-sonnet-5-5";

export const TIERS = {
  trial: { name: "Free trial", replies: 100, web: 5, smart: 0, daily: 100, perMinute: 8, costCap: 0.25, lifetime: true },
  pilot: { name: "Pilot", replies: 2000, web: 50, smart: 0, daily: 300, perMinute: 12, costCap: 2.5 },
  captain: { name: "Captain", replies: 5000, web: 150, smart: 200, daily: 600, perMinute: 15, costCap: 5.0 },
};

export const PRICES = {
  "claude-haiku-5-5": { in: 0.1, out: 0.5, cacheRead: 0.01, cacheWrite: 0.125 },
  "claude-sonnet-5-5": { in: 2.0, out: 10.0, cacheRead: 0.1, cacheWrite: 2.5 },
};
export const WEB_SEARCH_USD = 0.01;

export const MAX_TOKENS = 1024;
export const MAX_BODY_CHARS = 250_000;
export const MAX_DEVICES = 3;
export const DEVICE_WINDOW_DAYS = 30;
export const LICENSE_CACHE_SECONDS = 600;

export function tiers(env) {
  try {
    const extra = env.TIERS_JSON ? JSON.parse(env.TIERS_JSON) : {};
    const out = { ...TIERS };
    for (const [k, v] of Object.entries(extra)) out[k] = { ...(TIERS[k] || {}), ...v };
    return out;
  } catch {
    return TIERS;
  }
}

export function priceFor(model) {
  const m = String(model || "");
  const hit = Object.keys(PRICES).find((k) => m === k || m.startsWith(k));
  return PRICES[hit || STANDARD_MODEL];
}

export function costUsd(model, u) {
  const p = priceFor(model);
  return ((u.input_tokens || 0) * p.in + (u.output_tokens || 0) * p.out +
    (u.cache_read_input_tokens || 0) * p.cacheRead + (u.cache_creation_input_tokens || 0) * p.cacheWrite) / 1e6 +
    (u.web_search_requests || 0) * WEB_SEARCH_USD;
}
