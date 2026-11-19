export const STANDARD_MODEL = "claude-haiku-5-5";
export const SMART_MODEL = "claude-sonnet-5-5";

export const TIERS = {
  trial: { name: "Free trial", replies: 100, web: 5, smart: 0, daily: 100, perMinute: 8, costCap: 0.25, lifetime: true },
  pilot: { name: "Pilot", replies: 2000, web: 50, smart: 0, daily: 300, perMinute: 12, costCap: 2.5 },
  captain: { name: "Captain", replies: 5000, web: 150, smart: 200, daily: 600, perMinute: 15, costCap: 5.0 },
};

export const PRICES = {
  "claude-haiku-5-5": { in: 0.1, out: 0.5, cacheRead: 0.01, cacheWrite: 0.125, longContext: true },
  "claude-sonnet-5-5": { in: 2.0, out: 10.0, cacheRead: 0.1, cacheWrite: 2.5, longContext: false },
};
export const WEB_SEARCH_USD = 0.01;
export const LONG_CONTEXT_TOKENS = 100_000;
export const LONG_CONTEXT_MULT = 5;
export const WEB_RESULT_TOKENS = 30_000;
export const TOOL_PROMPT_TOKENS = 2_000;

export const MAX_TOKENS = 1024;
export const MAX_BODY_BYTES = 2_200_000;
export const MAX_TEXT_BYTES = 120_000;
export const IMAGE_TOKENS = 6_000;
export const MAX_DEVICES = 3;
export const DEVICE_WINDOW_DAYS = 30;
export const LICENSE_CACHE_SECONDS = 600;
export const CALLS_PER_REPLY = 3;
export const LOOKUPS_PER_10_MIN = 20;
export const TRIAL_DAILY_USD = 3;
export const TRIALS_PER_NETWORK_DAY = 3;
export const STALE_LICENSE_SECONDS = 7_200;
export const INVALID_CACHE_SECONDS = 120;
export const PROVIDER_CHECKS_PER_MIN = 60;
export const TRIALS_WIDE_FACTOR = 8;
export const MAX_IN_FLIGHT = 2;
export const IN_FLIGHT_SECONDS = 120;
export const DAILY_BUDGET_USD = 25;
export const TOOL_ID_SECONDS = 900;

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
  const input = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
  const mult = p.longContext && input > LONG_CONTEXT_TOKENS ? LONG_CONTEXT_MULT : 1;
  return mult * ((u.input_tokens || 0) * p.in + (u.output_tokens || 0) * p.out +
    (u.cache_read_input_tokens || 0) * p.cacheRead + (u.cache_creation_input_tokens || 0) * p.cacheWrite) / 1e6 +
    (u.web_search_requests || 0) * WEB_SEARCH_USD;
}

export function worstCaseUsd(model, bodyBytes, maxTokens, webUses) {
  const passes = webUses + 1;
  const input = passes * (bodyBytes + TOOL_PROMPT_TOKENS) + WEB_RESULT_TOKENS * (webUses * (webUses + 1)) / 2;
  return costUsd(model, {
    cache_creation_input_tokens: input,
    output_tokens: maxTokens,
    web_search_requests: webUses,
  });
}
