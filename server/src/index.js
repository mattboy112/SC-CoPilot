import {
  STANDARD_MODEL, SMART_MODEL, MAX_TOKENS, MAX_BODY_BYTES, MAX_TEXT_BYTES, IMAGE_TOKENS, MAX_DEVICES, DEVICE_WINDOW_DAYS, LICENSE_CACHE_SECONDS,
  CALLS_PER_REPLY, LOOKUPS_PER_10_MIN, TRIAL_DAILY_USD, TRIALS_PER_NETWORK_DAY, STALE_LICENSE_SECONDS, TOOL_ID_SECONDS,
  INVALID_CACHE_SECONDS, PROVIDER_CHECKS_PER_MIN, TRIALS_WIDE_FACTOR, MAX_IN_FLIGHT, IN_FLIGHT_SECONDS, DAILY_BUDGET_USD,
  tiers, costUsd, worstCaseUsd,
} from "./plans.js";
import { checkLicense, keyHash, sha256, localOnly } from "./license.js";
import { meterBody, toolResultIds, emptyUsage, mergeUsage } from "./meter.js";
import { sanitize, BadRequest } from "./sanitize.js";
import * as S from "./store.js";

const ANTHROPIC = "https://api.anthropic.com";
const ANTHROPIC_VERSION = "2023-06-01";
const VERSION = "1.2.0";
const KEY_SHAPE = /^[A-Za-z0-9_-]{8,128}$/;
const DEVICE_SHAPE = /^[a-f0-9]{16,64}$/;
const SAFE_HEADERS = { "cache-control": "no-store", "x-content-type-options": "nosniff" };

function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...SAFE_HEADERS, ...headers } });
}

function fail(status, type, message, extra = {}) {
  return json({ type: "error", error: { type, message, ...extra } }, status);
}

function nextDay(now) {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1)).toISOString();
}

function num(v, fallback) {
  if (v === undefined || v === null || v === "") return fallback;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ourProblem = () => fail(502, "api_error", "The Co-Pilot service has a problem on our end. We're on it.");

export function networkOf(ip, bits = 64) {
  ip = String(ip || "").trim().toLowerCase();
  if (!ip.includes(":")) return ip || "unknown";
  const [head, tail] = ip.split("::");
  const h = head ? head.split(":") : [];
  const t = tail ? tail.split(":") : [];
  const groups = ip.includes("::") ? [...h, ...Array(Math.max(0, 8 - h.length - t.length)).fill("0"), ...t] : h;
  const n = bits === 48 ? 3 : 4;
  return groups.slice(0, n).map((g) => g.replace(/^0+(?=.)/, "")).join(":") + `::/${n * 16}`;
}

async function networkTag(req, env, prefix, bits = 64) {
  const net = networkOf(req.headers.get("cf-connecting-ip"), bits);
  return `${prefix}:` + (await sha256(`${env.KEY_PEPPER || "sc-copilot"}|${net}`)).slice(0, 32);
}

async function newKeyAllowed(req, env) {
  const tag = await networkTag(req, env, "ip", 48);
  if (env.NEW_KEYS && typeof env.NEW_KEYS.limit === "function") {
    const { success } = await env.NEW_KEYS.limit({ key: tag });
    return success;
  }
  return (await S.bump(env.DB, tag, Date.now(), 600000)) <= num(env.LOOKUP_LIMIT, LOOKUPS_PER_10_MIN);
}

export function missingConfig(env) {
  const need = ["ANTHROPIC_API_KEY", "KEY_PEPPER"];
  const provider = (env.LICENSE_PROVIDER || "polar").toLowerCase();
  need.push(provider === "lemonsqueezy" ? "LS_STORE_ID" : "POLAR_ORG_ID");
  const missing = need.filter((k) => !String(env[k] || "").trim());
  let map = null;
  try {
    map = JSON.parse(env.TIER_MAP || "{}");
  } catch {
  }
  if (!map || typeof map !== "object" || !Object.keys(map).length) missing.push("TIER_MAP");
  return missing;
}

async function authorize(req, env) {
  const missing = missingConfig(env);
  if (missing.length) {
    console.error("service isn't configured, missing:", missing.join(", "));
    return { error: fail(503, "api_error", "The Co-Pilot service isn't switched on yet. Try again later.") };
  }
  const key = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!key) return { error: fail(401, "authentication_error", "Add your Co-Pilot license key in Settings.") };
  if (/^sk-ant-/i.test(key)) {
    return { error: fail(401, "authentication_error", "That's an Anthropic API key, not a Co-Pilot license key. To use it, pick \"My own Anthropic API key\" in Settings.") };
  }
  if (!KEY_SHAPE.test(key)) return { error: fail(401, "authentication_error", "That license key isn't valid. Check it in Settings.") };
  const rawDevice = req.headers.get("x-copilot-device") || "";
  if (!DEVICE_SHAPE.test(rawDevice)) {
    return { error: fail(400, "invalid_request_error", "This version of SC Co-Pilot can't use the subscription. Update the app.") };
  }
  const device = (await keyHash(env, `device|${rawDevice}`)).slice(0, 32);
  const hash = await keyHash(env, key);
  const now = Date.now();
  let lic = await S.getLicense(env.DB, hash);
  const ttl = (lic && !lic.ok && lic.status === "invalid" ? INVALID_CACHE_SECONDS : LICENSE_CACHE_SECONDS) * 1000;
  if (!lic || now - lic.checked_at >= ttl) {
    const unknown = !lic || !lic.ok;
    if (unknown && !(await newKeyAllowed(req, env))) {
      return { error: fail(429, "rate_limit_error", "Too many license checks from your network. Try again in a few minutes.", { retry_after: 600 }) };
    }
    const stale = () => lic && lic.ok && now - lic.checked_at < STALE_LICENSE_SECONDS * 1000;
    const busy = () => ({ error: fail(503, "overloaded_error", "Couldn't check your license right now. Try again in a minute.") });
    if (unknown && (await S.bump(env.DB, "provider:new", now, 60000)) > num(env.PROVIDER_CHECKS_PER_MIN, PROVIDER_CHECKS_PER_MIN)) {
      return busy();
    } else {
      try {
        const r = await checkLicense(env, key);
        await S.putLicense(env.DB, hash, r, now);
        lic = { ok: r.ok ? 1 : 0, tier: r.tier, status: r.status, customer: r.customer, expires_at: r.expiresAt, checked_at: now };
      } catch {
        if (!stale()) return busy();
      }
    }
  }
  if (lic.ok && lic.expires_at && Date.parse(lic.expires_at) < now) lic = { ...lic, ok: 0, status: "expired" };
  if (!lic.ok) {
    if (lic.status === "invalid") {
      return { error: fail(401, "authentication_error", "That license key isn't valid. Check it in Settings.") };
    }
    return {
      error: fail(402, "subscription_inactive",
        "Your Co-Pilot subscription isn't active. Renew it, or switch to your own key in Settings.", { status: lic.status }),
    };
  }
  const tier = tiers(env)[lic.tier];
  if (!tier) return { error: fail(402, "subscription_inactive", "Your plan isn't recognised. Contact support.") };
  if (!(await S.seeDevice(env.DB, hash, device, now, DEVICE_WINDOW_DAYS, MAX_DEVICES))) {
    return {
      error: fail(403, "permission_error",
        `This key is already in use on ${MAX_DEVICES} PCs this month. One subscription covers your own PCs only.`),
    };
  }
  if (tier.lifetime) {
    const owner = await S.trialOwner(env.DB, device);
    if (owner && owner !== hash) {
      return { error: fail(403, "permission_error", "This PC has already used a free trial. Subscribe to keep the AI going.") };
    }
    if (!owner) {
      const net = await networkTag(req, env, "trialnet");
      const wide = await networkTag(req, env, "trialnet48", 48);
      const perNet = num(env.TRIALS_PER_NETWORK, TRIALS_PER_NETWORK_DAY);
      const [n64, n48] = [await S.bump(env.DB, net, now, 86400000), await S.bump(env.DB, wide, now, 86400000)];
      if (n64 > perNet || n48 > perNet * TRIALS_WIDE_FACTOR) {
        return { error: fail(403, "permission_error", "Too many free trials from your network today. Try again tomorrow, or subscribe.") };
      }
      if (!(await S.addTrial(env.DB, device, hash, now))) {
        return { error: fail(403, "permission_error", "This PC has already used a free trial. Subscribe to keep the AI going.") };
      }
    }
  }
  return { keyHash: hash, tierId: lic.tier, tier, lic, now };
}

async function account(req, env) {
  const a = await authorize(req, env);
  if (a.error) return a.error;
  const now = new Date(a.now);
  const period = S.periodKey(a.tier, now);
  const [u, d] = await Promise.all([S.getUsage(env.DB, a.keyHash, period), S.getUsage(env.DB, a.keyHash, S.dayKey(now))]);
  return json({
    plan: a.tierId,
    plan_name: a.tier.name,
    status: a.lic.status,
    customer: a.lic.customer || "",
    period,
    resets_at: S.resetsAt(a.tier, now),
    usage: { replies: u.replies, web: u.web, smart: u.smart, today: d.replies },
    limits: { replies: a.tier.replies, web: a.tier.web, smart: a.tier.smart, daily: a.tier.daily },
    models: { standard: STANDARD_MODEL, smart: a.tier.smart > 0 ? SMART_MODEL : null },
    manage_url: env.MANAGE_URL || "",
    upgrade_url: env.UPGRADE_URL || "",
  });
}

async function readBody(req, maxBytes) {
  if (Number(req.headers.get("content-length") || 0) > maxBytes) return null;
  if (!req.body) return { text: "", bytes: 0 };
  const reader = req.body.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const buf = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) {
    buf.set(c, at);
    at += c.byteLength;
  }
  try {
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(buf), bytes: total };
  } catch {
    return { text: null, bytes: total };
  }
}

async function isContinuation(env, keyHash, input, now) {
  const ids = toolResultIds(input);
  if (!ids.length || ids.length > 20) return { yes: false, ids: [] };
  const since = now - TOOL_ID_SECONDS * 1000;
  for (let attempt = 0; attempt < 2; attempt++) {
    if ((await S.knownToolIds(env.DB, keyHash, ids, since)) === ids.length) return { yes: true, ids };
    if (attempt === 0) await sleep(400);
  }
  return { yes: false, ids: [] };
}

async function messages(req, env, ctx) {
  const a = await authorize(req, env);
  if (a.error) return a.error;
  const raw = await readBody(req, MAX_BODY_BYTES);
  if (raw === null) return fail(413, "request_too_large", "That request is too big for the Co-Pilot service.");
  if (raw.text === null) return fail(400, "invalid_request_error", "That request wasn't valid UTF-8 text.");
  let input;
  try {
    input = JSON.parse(raw.text);
  } catch {
    return fail(400, "invalid_request_error", "That request wasn't valid JSON.");
  }

  const now = new Date(a.now);
  const period = S.periodKey(a.tier, now);
  const day = S.dayKey(now);
  const trial = !!a.tier.lifetime;
  const [u, d, all, trials, cont] = await Promise.all([
    S.getUsage(env.DB, a.keyHash, period),
    S.getUsage(env.DB, a.keyHash, day),
    S.getUsage(env.DB, "__all__", day),
    trial ? S.getUsage(env.DB, "__trial__", day) : null,
    isContinuation(env, a.keyHash, input, a.now),
  ]);
  const fresh = !cont.yes;
  const notices = [];
  const wantSmart = !!input && typeof input.model === "string" && input.model.startsWith("claude-sonnet");
  const smart = wantSmart && a.tier.smart > 0 && u.smart_calls < a.tier.smart * CALLS_PER_REPLY && (!fresh || u.smart < a.tier.smart);
  if (wantSmart && !smart) notices.push(a.tier.smart > 0 ? "smart-limit" : "smart-not-in-plan");
  const model = smart ? SMART_MODEL : STANDARD_MODEL;

  let clean;
  try {
    clean = sanitize(input, { model, maxTokens: MAX_TOKENS, webLeft: a.tier.web - u.web, userId: a.keyHash.slice(0, 32) });
  } catch (e) {
    if (e instanceof BadRequest) return fail(400, "invalid_request_error", e.message);
    throw e;
  }
  if (clean.dropped) notices.push("web-limit");
  const webTool = (clean.body.tools || []).find((t) => t.name === "web_search" && t.type);
  const reservedWeb = webTool ? webTool.max_uses : 0;
  let upstreamBody;
  try {
    upstreamBody = JSON.stringify(clean.body);
  } catch {
    return fail(400, "invalid_request_error", "That request is nested too deeply.");
  }
  const textBytes = new TextEncoder().encode(upstreamBody).byteLength - clean.imageChars;
  if (textBytes > MAX_TEXT_BYTES) return fail(413, "request_too_large", "That request is too big for the Co-Pilot service.");
  const reserved = Math.ceil(worstCaseUsd(model, textBytes + clean.images * IMAGE_TOKENS, clean.body.max_tokens, reservedWeb) * 1e6);

  const resets = S.resetsAt(a.tier, now);
  const quota = (message, resetsAt) => fail(429, "quota_exceeded", message, { resets_at: resetsAt, plan: a.tierId });
  const monthly = a.tier.lifetime
    ? "Your free trial replies are used up. Subscribe to keep the AI going."
    : `You've used all ${a.tier.replies} AI replies this month.`;
  const capMicro = Math.round(a.tier.costCap * 1e6);
  const dailyMsg = `That's today's limit of ${a.tier.daily} AI replies. It resets at midnight UTC.`;
  const budgetMicro = Math.round((num(env.DAILY_BUDGET_USD, DAILY_BUDGET_USD) || DAILY_BUDGET_USD) * 1e6);
  const trialMicro = Math.round(num(env.TRIAL_DAILY_USD, TRIAL_DAILY_USD) * 1e6);
  const pausedMsg = "The Co-Pilot service has hit its daily safety limit. It'll be back tomorrow.";
  const trialsMsg = "Free trials are paused for today. Try again tomorrow, or subscribe.";

  if (u.cost_micro + reserved > capMicro) return quota("You've reached this month's Co-Pilot limit.", resets);
  if (u.calls >= a.tier.replies * CALLS_PER_REPLY) return quota(monthly, resets);
  if (fresh && u.replies >= a.tier.replies) return quota(monthly, resets);
  if (d.calls >= a.tier.daily * CALLS_PER_REPLY || (fresh && d.replies >= a.tier.daily)) return quota(dailyMsg, nextDay(now));
  if (budgetMicro > 0 && all.cost_micro + reserved > budgetMicro) return fail(503, "overloaded_error", pausedMsg);
  if (trial && trials.cost_micro + reserved > trialMicro) return fail(503, "overloaded_error", trialsMsg);
  if ((await S.bumpMinute(env.DB, a.keyHash, a.now)) > a.tier.perMinute) {
    return fail(429, "rate_limit_error", "Too many questions at once. Give it a minute.", { retry_after: 60 });
  }
  const flight = crypto.randomUUID();
  if (!(await S.enterFlight(env.DB, a.keyHash, flight, a.now, num(env.MAX_IN_FLIGHT, MAX_IN_FLIGHT), IN_FLIGHT_SECONDS * 1000))) {
    return fail(429, "rate_limit_error", "One question at a time. Wait for the answer, then ask again.", { retry_after: 5 });
  }
  const land = () => S.leaveFlight(env.DB, a.keyHash, flight).run().catch(() => {});

  const keyDelta = { replies: fresh ? 1 : 0, smart: fresh && smart ? 1 : 0, smart_calls: smart ? 1 : 0, web: reservedWeb, cost: reserved };
  const stmts = [
    S.ensureUsage(env.DB, a.keyHash, period),
    S.ensureUsage(env.DB, a.keyHash, day),
    S.ensureUsage(env.DB, "__all__", day),
    S.reserveKey(env.DB, a.keyHash, period, keyDelta, {
      cost: capMicro, calls: a.tier.replies * CALLS_PER_REPLY, replies: a.tier.replies, smart: a.tier.smart,
      smartCalls: a.tier.smart * CALLS_PER_REPLY, web: a.tier.web,
    }),
    S.reserveDay(env.DB, a.keyHash, day, keyDelta.replies, { calls: a.tier.daily * CALLS_PER_REPLY, replies: a.tier.daily }),
    S.reserveBudget(env.DB, "__all__", day, reserved, budgetMicro),
  ];
  if (trial) stmts.push(S.ensureUsage(env.DB, "__trial__", day), S.reserveBudget(env.DB, "__trial__", day, reserved, trialMicro));
  if (cont.yes) stmts.push(S.forgetToolIds(env.DB, a.keyHash, cont.ids));
  let res;
  try {
    res = await env.DB.batch(stmts);
  } catch (e) {
    await land();
    throw e;
  }
  const got = (i) => !!(res[i] && res[i].results && res[i].results.length);
  const ok = { key: got(3), day: got(4), all: got(5), trial: trial ? got(7) : true };

  const undo = (which) => {
    const back = [];
    if (which.key) {
      back.push(S.addUsage(env.DB, a.keyHash, period, {
        replies: -keyDelta.replies, smart: -keyDelta.smart, calls: -1, smart_calls: -keyDelta.smart_calls, web: -reservedWeb, cost_micro: -reserved,
      }));
    }
    if (which.day) back.push(S.addUsage(env.DB, a.keyHash, day, { replies: -keyDelta.replies, calls: -1 }));
    if (which.all) back.push(S.addUsage(env.DB, "__all__", day, { calls: -1, cost_micro: -reserved }));
    if (trial && which.trial) back.push(S.addUsage(env.DB, "__trial__", day, { calls: -1, cost_micro: -reserved }));
    return back.length ? env.DB.batch(back) : Promise.resolve();
  };

  if (!ok.key || !ok.day || !ok.all || !ok.trial) {
    ctx.waitUntil(undo(ok).catch(() => {}).then(land));
    if (!ok.key) return quota("You've reached this month's Co-Pilot limit.", resets);
    if (!ok.day) return quota(dailyMsg, nextDay(now));
    if (!ok.all) return fail(503, "overloaded_error", pausedMsg);
    return fail(503, "overloaded_error", trialsMsg);
  }
  const release = () => undo({ key: true, day: true, all: true, trial: true }).catch(() => {}).then(land);

  const idWrites = [];
  const onToolUse = (id) => {
    idWrites.push(S.rememberToolIds(env.DB, a.keyHash, [id], Date.now()).catch(() => {}));
  };
  const settle = async (usage) => {
    const cost = Math.round(costUsd(model, usage) * 1e6);
    const delta = cost - reserved;
    const st = [
      S.addUsage(env.DB, a.keyHash, period, {
        web: usage.web_search_requests - reservedWeb,
        input_tokens: usage.input_tokens,
        output_tokens: usage.output_tokens,
        cache_read: usage.cache_read_input_tokens,
        cache_write: usage.cache_creation_input_tokens,
        cost_micro: delta,
      }),
      S.addUsage(env.DB, "__all__", day, { cost_micro: delta }),
    ];
    if (trial) st.push(S.addUsage(env.DB, "__trial__", day, { cost_micro: delta }));
    await Promise.all(idWrites);
    st.push(S.leaveFlight(env.DB, a.keyHash, flight));
    await env.DB.batch(st);
  };

  let background = Promise.resolve();
  const reply = (async () => {
    let upstream;
    try {
      upstream = await fetch(localOnly(env.ANTHROPIC_URL, ANTHROPIC) + "/v1/messages", {
        method: "POST",
        headers: { "content-type": "application/json", "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": ANTHROPIC_VERSION },
        body: upstreamBody,
      });
    } catch {
      background = release();
      return fail(502, "api_error", "Couldn't reach the AI right now. Try again in a moment.");
    }

    if (!upstream.ok) {
      background = release();
      const st = upstream.status;
      const errText = await upstream.text().catch(() => "");
      if (st === 401 || st === 403 || st === 404) return ourProblem();
      if (st === 429) return fail(503, "overloaded_error", "The Co-Pilot service is busy. Try again in a moment.");
      if (st >= 500) return fail(st === 529 ? 529 : 502, "overloaded_error", "The AI is overloaded right now. Try again in a moment.");
      if (/credit|billing|balance|spend|organi[sz]ation|workspace/i.test(errText)) return ourProblem();
      let message = `Request refused (${st}).`;
      try {
        const e = JSON.parse(errText);
        if (e && e.error && typeof e.error.message === "string") message = e.error.message.slice(0, 500);
      } catch {
      }
      return fail(st === 413 ? 413 : 400, "invalid_request_error", message);
    }

    const headers = { "content-type": upstream.headers.get("content-type") || "application/json", ...SAFE_HEADERS };
    if (notices.length) headers["x-copilot-notice"] = [...new Set(notices)].join(",");

    if (clean.body.stream && upstream.body) {
      const [toPlayer, toMeter] = upstream.body.tee();
      background = meterBody(toMeter, onToolUse).then(settle);
      return new Response(toPlayer, { status: 200, headers });
    }
    const data = await upstream.json();
    for (const b of Array.isArray(data.content) ? data.content : []) {
      if (b && b.type === "tool_use" && typeof b.id === "string") onToolUse(b.id);
    }
    background = settle(mergeUsage(emptyUsage(), data.usage));
    return new Response(JSON.stringify(data), { status: 200, headers });
  })();

  ctx.waitUntil(reply.then(() => background).catch((e) => {
    console.error("metering failed:", e && e.message);
    return land();
  }));
  return reply;
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    try {
      if (url.pathname === "/health") return json({ ok: true, version: VERSION });
      if (url.pathname.startsWith("/v1/") && env.PER_IP && typeof env.PER_IP.limit === "function") {
        const { success } = await env.PER_IP.limit({ key: await networkTag(req, env, "req") });
        if (!success) return fail(429, "rate_limit_error", "Too many requests from your network. Give it a minute.", { retry_after: 60 });
      }
      if (url.pathname === "/v1/account" && req.method === "GET") return await account(req, env);
      if (url.pathname === "/v1/messages" && req.method === "POST") return await messages(req, env, ctx);
      return fail(404, "not_found_error", "Nothing here.");
    } catch (e) {
      console.error(e && e.stack ? e.stack : e);
      return fail(500, "api_error", "The Co-Pilot service hit a snag. Try again.");
    }
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(S.tidy(env.DB, Date.now()));
  },
};
