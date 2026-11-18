import http from "node:http";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const FAKE_PORT = 8788;
const WORKER_PORT = 8787;
const BASE = `http://127.0.0.1:${WORKER_PORT}`;

const KEYS = {
  "PILOT-KEY": { status: "granted", benefit_id: "ben-pilot", customer: { email: "pilot@example.com" } },
  "PILOT-KEY-2": { status: "granted", benefit_id: "ben-pilot" },
  "CAPTAIN-KEY": { status: "granted", benefit_id: "ben-captain" },
  "TRIAL-KEY": { status: "granted", benefit_id: "ben-trial" },
  "REVOKED-KEY": { status: "revoked", benefit_id: "ben-pilot" },
  "OTHER-PRODUCT": { status: "granted", benefit_id: "ben-something-else" },
};
let lastBody = null;
let licenseCalls = 0;

function sse(res, events) {
  res.writeHead(200, { "content-type": "text/event-stream" });
  for (const e of events) res.write(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`);
  res.end();
}

const fake = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    if (req.url === "/v1/customer-portal/license-keys/validate") {
      licenseCalls++;
      const { key } = JSON.parse(raw);
      const hit = KEYS[key];
      if (!hit) return res.writeHead(404).end(JSON.stringify({ detail: "Not found" }));
      return res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ id: "lk", key, ...hit }));
    }
    if (req.url === "/v1/messages") {
      if (req.headers["x-api-key"] !== "sk-test") return res.writeHead(401).end("{}");
      const body = JSON.parse(raw);
      lastBody = body;
      const said = JSON.stringify(body.messages);
      if (said.includes("make it 400")) {
        return res.writeHead(400, { "content-type": "application/json" })
          .end(JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: "thinking.type: disabled is not supported" } }));
      }
      const web = (body.tools || []).some((t) => String(t.type).startsWith("web_search")) && said.includes("search") ? 1 : 0;
      const start = { type: "message_start", message: { id: "m", model: body.model, usage: { input_tokens: 1000, cache_read_input_tokens: 4000, cache_creation_input_tokens: 0, output_tokens: 1 } } };
      const deltas = [
        { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
        { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "Copy that. " } },
        { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "Gear's down." } },
        { type: "content_block_stop", index: 0 },
        { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: 42, server_tool_use: { web_search_requests: web } } },
        { type: "message_stop" },
      ];
      if (body.stream) return sse(res, [start, ...deltas]);
      return res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({
        id: "m", type: "message", model: body.model, content: [{ type: "text", text: "Copy that." }], stop_reason: "end_turn",
        usage: { input_tokens: 1000, output_tokens: 42, cache_read_input_tokens: 4000, server_tool_use: { web_search_requests: web } },
      }));
    }
    res.writeHead(404).end();
  });
});

function ask(key, text, extra = {}, headers = {}) {
  const body = {
    model: "claude-haiku-5-5", max_tokens: 9999, stream: true, system: "test",
    messages: [{ role: "user", content: text }],
    tools: [{ type: "web_search_20250305", name: "web_search", max_uses: 5 }, { name: "press_keys", input_schema: { type: "object" } }],
    ...extra,
  };
  return fetch(`${BASE}/v1/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(key ? { authorization: `Bearer ${key}` } : {}), ...headers },
    body: JSON.stringify(body),
  });
}

async function account(key) {
  const r = await fetch(`${BASE}/v1/account`, { headers: { authorization: `Bearer ${key}` } });
  return { status: r.status, body: await r.json() };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
async function check(name, fn) {
  let timer;
  try {
    await Promise.race([fn(), new Promise((_, no) => (timer = setTimeout(() => no(new Error("timed out")), 20000)))]);
    results.push(["PASS", name]);
  } catch (e) {
    results.push(["FAIL", name, e.message]);
  } finally {
    clearTimeout(timer);
  }
  console.log(results[results.length - 1].join("  "));
}

async function main() {
  const step = (m) => process.env.DEBUG && console.log("..", m);
  await new Promise((r) => fake.listen(FAKE_PORT, "127.0.0.1", r));
  step("fake servers up");
  const state = mkdtempSync(join(tmpdir(), "scsvc-"));
  writeFileSync(join(root, ".dev.vars"), [
    "ANTHROPIC_API_KEY=sk-test",
    `ANTHROPIC_URL=http://127.0.0.1:${FAKE_PORT}`,
    `POLAR_API_URL=http://127.0.0.1:${FAKE_PORT}`,
    "POLAR_ORG_ID=org-test",
    'TIER_MAP={"ben-pilot":"pilot","ben-captain":"captain","ben-trial":"trial"}',
    'TIERS_JSON={"pilot":{"replies":4,"web":1,"daily":100,"perMinute":50},"captain":{"replies":50,"smart":1,"perMinute":50},"trial":{"replies":2,"perMinute":50}}',
    "MANAGE_URL=https://example.com/portal",
    "UPGRADE_URL=https://example.com/buy",
  ].join("\n"));
  const env = { ...process.env, NO_PROXY: "127.0.0.1,localhost", no_proxy: "127.0.0.1,localhost", WRANGLER_SEND_METRICS: "false" };
  execFileSync("npx", ["wrangler", "d1", "execute", "sc-copilot", "--local", "--persist-to", state, "--file=schema.sql"], { cwd: root, env, stdio: "pipe" });
  step("database ready");
  const dev = spawn("npx", ["wrangler", "dev", "--local", "--port", String(WORKER_PORT), "--ip", "127.0.0.1", "--persist-to", state, "--show-interactive-dev-session=false"], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"], detached: true });
  let log = "";
  dev.stdout.on("data", (d) => (log += d));
  dev.stderr.on("data", (d) => (log += d));
  for (let i = 0; i < 120; i++) {
    try {
      if ((await fetch(`${BASE}/health`)).ok) break;
    } catch {
    }
    await sleep(500);
  }
  step("worker up");

  try {
    await check("health", async () => assert.equal((await (await fetch(`${BASE}/health`)).json()).ok, true));

    await check("no key / bad key / revoked / unknown plan", async () => {
      assert.equal((await ask("", "hi")).status, 401);
      assert.equal((await ask("NOPE", "hi")).status, 401);
      const rv = await ask("REVOKED-KEY", "hi");
      assert.equal(rv.status, 402);
      assert.match((await rv.json()).error.message, /isn't active/);
      assert.equal((await ask("OTHER-PRODUCT", "hi")).status, 402);
    });

    await check("pilot: streams through, clamps max_tokens, forces the standard model", async () => {
      const r = await ask("PILOT-KEY", "gear down please", { model: "claude-opus-5-5" });
      assert.equal(r.status, 200);
      const text = await r.text();
      assert.match(text, /Gear's down/);
      assert.equal(lastBody.model, "claude-haiku-5-5");
      assert.equal(lastBody.max_tokens, 1024);
      assert.equal(lastBody.tools[0].max_uses, 1);
    });

    await check("license result is cached (one provider call per key)", async () => {
      const before = licenseCalls;
      await (await ask("PILOT-KEY", "status")).text();
      assert.equal(licenseCalls, before);
    });

    await sleep(300);
    await check("account shows plan, usage and limits", async () => {
      const a = await account("PILOT-KEY");
      assert.equal(a.status, 200);
      assert.equal(a.body.plan, "pilot");
      assert.equal(a.body.plan_name, "Pilot");
      assert.equal(a.body.usage.replies, 2);
      assert.equal(a.body.limits.replies, 4);
      assert.equal(a.body.customer, "pilot@example.com");
      assert.equal(a.body.manage_url, "https://example.com/portal");
      assert.ok(a.body.resets_at.endsWith("T00:00:00.000Z"));
    });

    await check("tool follow-ups don't count as a new reply", async () => {
      const r = await ask("PILOT-KEY", "", {
        messages: [
          { role: "user", content: "where can I refuel" },
          { role: "assistant", content: [{ type: "tool_use", id: "t1", name: "find_services", input: {} }] },
          { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "{}" }] },
        ],
      });
      await r.text();
      await sleep(300);
      assert.equal((await account("PILOT-KEY")).body.usage.replies, 2);
    });

    await check("web searches are metered, then the web tool is removed when they run out", async () => {
      await (await ask("PILOT-KEY", "search the web for the patch notes")).text();
      await sleep(300);
      assert.equal((await account("PILOT-KEY")).body.usage.web, 1);
      const r = await ask("PILOT-KEY", "search again");
      await r.text();
      assert.equal(r.headers.get("x-copilot-notice"), "web-limit");
      assert.ok(!(lastBody.tools || []).some((t) => String(t.type).startsWith("web_search")));
      assert.ok(lastBody.tools.some((t) => t.name === "press_keys"));
    });

    await sleep(300);
    await check("monthly reply limit returns 429 with a reset date", async () => {
      const r = await ask("PILOT-KEY", "one more");
      assert.equal(r.status, 429);
      const e = (await r.json()).error;
      assert.equal(e.type, "quota_exceeded");
      assert.match(e.message, /all 4 AI replies/);
      assert.ok(e.resets_at);
    });

    await check("Anthropic's own 400 messages pass through unchanged", async () => {
      const r = await ask("CAPTAIN-KEY", "make it 400");
      assert.equal(r.status, 400);
      assert.match((await r.json()).error.message, /thinking/);
    });

    await check("captain gets the smart model until its allowance runs out", async () => {
      await (await ask("CAPTAIN-KEY", "deep question", { model: "claude-sonnet-5-5" })).text();
      assert.equal(lastBody.model, "claude-sonnet-5-5");
      await sleep(300);
      const r = await ask("CAPTAIN-KEY", "another deep one", { model: "claude-sonnet-5-5" });
      await r.text();
      assert.equal(lastBody.model, "claude-haiku-5-5");
      assert.equal(r.headers.get("x-copilot-notice"), "smart-limit");
      const p = await ask("PILOT-KEY-2", "smart please", { model: "claude-sonnet-5-5" });
      await p.text();
      assert.equal(p.headers.get("x-copilot-notice"), "smart-not-in-plan");
    });

    await check("trial is a one-time allowance", async () => {
      for (const q of ["a", "b"]) {
        await (await ask("TRIAL-KEY", q)).text();
        await sleep(250);
      }
      const r = await ask("TRIAL-KEY", "c");
      assert.equal(r.status, 429);
      assert.match((await r.json()).error.message, /free trial/);
      const a = await account("TRIAL-KEY");
      assert.equal(a.body.resets_at, null);
    });

    await check("a key works on 3 PCs, not a 4th", async () => {
      for (const dev of ["pc-1", "pc-2", "pc-3"]) {
        const r = await ask("CAPTAIN-KEY", "hi", {}, { "x-copilot-device": dev });
        assert.equal(r.status, 200, dev);
        await r.text();
      }
      const r = await ask("CAPTAIN-KEY", "hi", {}, { "x-copilot-device": "pc-4" });
      assert.equal(r.status, 403);
      const again = await ask("CAPTAIN-KEY", "hi", {}, { "x-copilot-device": "pc-2" });
      assert.equal(again.status, 200);
      await again.text();
    });

    await check("oversized requests are refused", async () => {
      const r = await ask("CAPTAIN-KEY", "x".repeat(260000));
      assert.equal(r.status, 413);
    });

    await check("cost is recorded", async () => {
      const out = execFileSync("npx", ["wrangler", "d1", "execute", "sc-copilot", "--local", "--persist-to", state, "--json",
        "--command", "SELECT period, replies, web, input_tokens, output_tokens, cache_read, cost_micro FROM usage WHERE period NOT LIKE 'd:%'"],
        { cwd: root, env, stdio: "pipe" }).toString();
      const rows = JSON.parse(out)[0].results;
      const pilot = rows.find((r) => r.web === 1 && r.replies === 4);
      assert.ok(pilot, JSON.stringify(rows));
      const expectHaiku = (1000 * 0.1 + 42 * 0.5 + 4000 * 0.01) / 1e6;
      assert.equal(pilot.cost_micro, Math.round((expectHaiku * 5 + 0.01) * 1e6));
    });
  } finally {
    try {
      process.kill(-dev.pid, "SIGTERM");
    } catch {
    }
    fake.closeAllConnections();
    fake.close();
    rmSync(join(root, ".dev.vars"), { force: true });
    rmSync(state, { recursive: true, force: true });
  }

  const failed = results.filter((r) => r[0] === "FAIL").length;
  if (failed) {
    console.log("\n--- worker log ---\n" + log.slice(-4000));
    process.exit(1);
  }
  console.log(`\n${results.length} checks passed`);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
