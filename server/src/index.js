import {
  STANDARD_MODEL, SMART_MODEL, MAX_TOKENS, MAX_BODY_CHARS, MAX_DEVICES, DEVICE_WINDOW_DAYS,
  LICENSE_CACHE_SECONDS, tiers, costUsd,
} from "./plans.js";
import { checkLicense, sha256 } from "./license.js";
import { meterStream, isNewQuestion, emptyUsage, mergeUsage } from "./meter.js";
import * as S from "./store.js";

const ANTHROPIC = "https://api.anthropic.com";
const VERSION = "1.0.0";

function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...headers } });
}

function fail(status, type, message, extra = {}) {
  return json({ type: "error", error: { type, message, ...extra } }, status);
}

function nextDay(now) {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1)).toISOString();
}

async function authorize(req, env) {
  const key = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!key || key.length > 200) {
    return { error: fail(401, "authentication_error", "Add your Co-Pilot license key in Settings.") };
  }
  const keyHash = await sha256(key);
  const now = Date.now();
  let lic = await S.getLicense(env.DB, keyHash);
  if (!lic || now - lic.checked_at >= LICENSE_CACHE_SECONDS * 1000) {
    try {
      const r = await checkLicense(env, key);
      await S.putLicense(env.DB, keyHash, r, now);
      lic = { ok: r.ok ? 1 : 0, tier: r.tier, status: r.status, customer: r.customer, expires_at: r.expiresAt, checked_at: now };
    } catch {
      if (!lic) return { error: fail(503, "overloaded_error", "Couldn't check your license right now. Try again in a minute.") };
    }
  }
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
  const device = (req.headers.get("x-copilot-device") || "").slice(0, 80);
  if (device && !(await S.seeDevice(env.DB, keyHash, device, now, DEVICE_WINDOW_DAYS, MAX_DEVICES))) {
    return {
      error: fail(403, "permission_error",
        `This key is already in use on ${MAX_DEVICES} PCs this month. One subscription covers your own PCs only.`),
    };
  }
  return { keyHash, tierId: lic.tier, tier, lic, now };
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

async function messages(req, env, ctx) {
  const a = await authorize(req, env);
  if (a.error) return a.error;
  const text = await req.text();
  if (text.length > MAX_BODY_CHARS) return fail(413, "request_too_large", "That request is too big for the Co-Pilot service.");
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return fail(400, "invalid_request_error", "That request wasn't valid JSON.");
  }

  const now = new Date(a.now);
  const period = S.periodKey(a.tier, now);
  const day = S.dayKey(now);
  const [u, d] = await Promise.all([S.getUsage(env.DB, a.keyHash, period), S.getUsage(env.DB, a.keyHash, day)]);
  const fresh = isNewQuestion(body);
  const resets = S.resetsAt(a.tier, now);
  const quota = (message, resetsAt) => fail(429, "quota_exceeded", message, { resets_at: resetsAt, plan: a.tierId });

  if (u.cost_micro >= a.tier.costCap * 1e6) {
    return quota("You've reached this month's Co-Pilot limit.", resets);
  }
  if (fresh && u.replies >= a.tier.replies) {
    return quota(a.tier.lifetime
      ? "Your free trial replies are used up. Subscribe to keep the AI going."
      : `You've used all ${a.tier.replies} AI replies this month.`, resets);
  }
  if (fresh && d.replies >= a.tier.daily) {
    return quota(`That's today's limit of ${a.tier.daily} AI replies. It resets at midnight UTC.`, nextDay(now));
  }
  if ((await S.bumpMinute(env.DB, a.keyHash, a.now)) > a.tier.perMinute) {
    return fail(429, "rate_limit_error", "Too many questions at once. Give it a minute.", { retry_after: 60 });
  }

  const notices = [];
  const wantSmart = String(body.model || "").startsWith("claude-sonnet");
  const smart = wantSmart && a.tier.smart > 0 && (!fresh || u.smart < a.tier.smart);
  if (wantSmart && !smart) notices.push(a.tier.smart > 0 ? "smart-limit" : "smart-not-in-plan");
  body.model = smart ? SMART_MODEL : STANDARD_MODEL;
  body.max_tokens = Math.min(Number(body.max_tokens) || MAX_TOKENS, MAX_TOKENS);

  if (Array.isArray(body.tools)) {
    const left = a.tier.web - u.web;
    body.tools = body.tools.flatMap((t) => {
      if (!t || typeof t.type !== "string" || !t.type.startsWith("web_search")) return [t];
      if (left <= 0) {
        notices.push("web-limit");
        return [];
      }
      return [{ ...t, max_uses: Math.max(1, Math.min(left, t.max_uses || 2, 2)) }];
    });
    if (!body.tools.length) delete body.tools;
  }

  const headers = {
    "content-type": "application/json",
    "x-api-key": env.ANTHROPIC_API_KEY || "",
    "anthropic-version": req.headers.get("anthropic-version") || "2023-06-01",
  };
  const beta = req.headers.get("anthropic-beta");
  if (beta) headers["anthropic-beta"] = beta;
  const upstream = await fetch((env.ANTHROPIC_URL || ANTHROPIC) + "/v1/messages", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  const out = new Headers({ "content-type": upstream.headers.get("content-type") || "application/json", "cache-control": "no-store" });
  if (notices.length) out.set("x-copilot-notice", [...new Set(notices)].join(","));

  if (!upstream.ok) {
    const st = upstream.status;
    const errText = await upstream.text().catch(() => "");
    if (st === 401 || st === 403) return fail(502, "api_error", "The Co-Pilot service has a problem on our end. We're on it.");
    if (st === 429) return fail(503, "overloaded_error", "The Co-Pilot service is busy. Try again in a moment.");
    if (st >= 500) return fail(st === 529 ? 529 : 502, "overloaded_error", "The AI is overloaded right now. Try again in a moment.");
    return new Response(errText || JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: `Request refused (${st}).` } }),
      { status: st, headers: out });
  }

  const model = body.model;
  const record = (usage) => {
    const stmts = [S.addUsage(env.DB, a.keyHash, period, {
      replies: fresh ? 1 : 0,
      smart: fresh && smart ? 1 : 0,
      web: usage.web_search_requests,
      input_tokens: usage.input_tokens,
      output_tokens: usage.output_tokens,
      cache_read: usage.cache_read_input_tokens,
      cache_write: usage.cache_creation_input_tokens,
      cost_micro: Math.round(costUsd(model, usage) * 1e6),
    })];
    if (fresh) stmts.push(S.addUsage(env.DB, a.keyHash, day, { replies: 1 }));
    return env.DB.batch(stmts);
  };

  if (body.stream && upstream.body) {
    const meter = meterStream((usage) => ctx.waitUntil(record(usage)));
    return new Response(upstream.body.pipeThrough(meter), { status: 200, headers: out });
  }
  const data = await upstream.json();
  ctx.waitUntil(record(mergeUsage(emptyUsage(), data.usage)));
  return new Response(JSON.stringify(data), { status: 200, headers: out });
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    try {
      if (url.pathname === "/health") return json({ ok: true, version: VERSION });
      if (url.pathname === "/v1/account" && req.method === "GET") return await account(req, env);
      if (url.pathname === "/v1/messages" && req.method === "POST") return await messages(req, env, ctx);
      return fail(404, "not_found_error", "Nothing here.");
    } catch (e) {
      console.error(e && e.stack ? e.stack : e);
      return fail(500, "api_error", "The Co-Pilot service hit a snag. Try again.");
    }
  },
};
