import http from "node:http";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const FAKE_PORT = 8788;
const WORKER_PORT = 8787;
const BASE = `http://127.0.0.1:${WORKER_PORT}`;

const KEYS = {
  "PILOT-KEY": { status: "granted", benefit_id: "ben-pilot", customer: { email: "pilot@example.com" } },
  "PILOT-KEY-2": { status: "granted", benefit_id: "ben-pilot" },
  "CAPTAIN-KEY": { status: "granted", benefit_id: "ben-captain" },
  "TRIAL-KEY": { status: "granted", benefit_id: "ben-trial" },
  "TRIAL-KEY-2": { status: "granted", benefit_id: "ben-trial" },
  "HANGUP-KEY": { status: "granted", benefit_id: "ben-pilot" },
  "LOOP-KEY": { status: "granted", benefit_id: "ben-pilot" },
  "LAGGY-KEY": { status: "granted", benefit_id: "ben-pilot" },
  "SMART-KEY": { status: "granted", benefit_id: "ben-captain" },
  "BURST-KEY": { status: "granted", benefit_id: "ben-burst" },
  "TRIAL-KEY-3": { status: "granted", benefit_id: "ben-trial" },
  "REVOKED-KEY": { status: "revoked", benefit_id: "ben-pilot" },
  "OTHER-PRODUCT": { status: "granted", benefit_id: "ben-something-else" },
  "SHARED-KEY": { status: "granted", benefit_id: "ben-captain" },
  "FLIGHT-KEY": { status: "granted", benefit_id: "ben-captain" },
  "STALE-KEY": { status: "granted", benefit_id: "ben-pilot" },
  "EXPIRED-KEY": { status: "granted", benefit_id: "ben-pilot", expires_at: "2001-01-01T00:00:00Z" },
  "EXPIRING-KEY": { status: "granted", benefit_id: "ben-pilot", expires_at: "2099-01-01T00:00:00Z" },
};
let lastBody = null;
let toolSeq = 0;
let lagArrived = () => {};
let lastHeaders = {};
let licenseCalls = 0;
let polarDown = false;

function sse(res, events, gap = 0) {
  res.writeHead(200, { "content-type": "text/event-stream" });
  if (!gap) {
    for (const e of events) res.write(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`);
    return res.end();
  }
  let i = 0;
  const next = () => {
    if (i >= events.length) return res.end();
    const e = events[i++];
    res.write(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`);
    setTimeout(next, gap);
  };
  next();
}

const fake = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    if (req.url === "/v1/customer-portal/license-keys/validate") {
      licenseCalls++;
      if (polarDown) return res.writeHead(429, { "content-type": "application/json" }).end('{"detail":"slow down"}');
      const { key } = JSON.parse(raw);
      const hit = KEYS[key];
      if (!hit) return res.writeHead(404).end(JSON.stringify({ detail: "Not found" }));
      return res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ id: "lk", key, ...hit }));
    }
    if (req.url === "/v1/messages") {
      if (req.headers["x-api-key"] !== "sk-test") return res.writeHead(401).end("{}");
      const body = JSON.parse(raw);
      lastBody = body;
      lastHeaders = req.headers;
      const said = JSON.stringify(body.messages);
      if (said.includes("make it 400")) {
        return res.writeHead(400, { "content-type": "application/json" })
          .end(JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: "thinking.type: disabled is not supported" } }));
      }
      if (said.includes("broke")) {
        return res.writeHead(400, { "content-type": "application/json" })
          .end(JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: "Your credit balance is too low to access the Anthropic API." } }));
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
      if (said.includes("use a tool") && !said.includes("tool_result")) {
        const id = `toolu_${Date.now().toString(36)}${toolSeq++}`;
        const tool = [
          { type: "content_block_start", index: 0, content_block: { type: "tool_use", id, name: "find_services", input: {} } },
          { type: "content_block_delta", index: 0, delta: { type: "input_json_delta", partial_json: "{}" } },
          { type: "content_block_stop", index: 0 },
          { type: "message_delta", delta: { stop_reason: "tool_use" }, usage: { output_tokens: 42 } },
          { type: "message_stop" },
        ];
        return sse(res, [start, ...tool]);
      }
      if (said.includes("lag")) {
        lagArrived();
        return setTimeout(() => sse(res, [start, ...deltas]), 1500);
      }
      if (body.stream) return sse(res, [start, ...deltas], said.includes("slow") ? 150 : 0);
      return res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({
        id: "m", type: "message", model: body.model, content: [{ type: "text", text: "Copy that." }], stop_reason: "end_turn",
        usage: { input_tokens: 1000, output_tokens: 42, cache_read_input_tokens: 4000, server_tool_use: { web_search_requests: web } },
      }));
    }
    res.writeHead(404).end();
  });
});

const DEVICE = "a1b2c3d4e5f6a7b8c9d0e1f2";
const pc = (n) => n.toString(16).padStart(24, "0");
const followUp = (id = "toolu_fake1", first = "where can I refuel") => ({
  messages: [
    { role: "user", content: first },
    { role: "assistant", content: [{ type: "tool_use", id, name: "find_services", input: {} }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: id, content: "{}" }] },
  ],
});
const toolIdIn = (text) => (/"id":"(toolu_[A-Za-z0-9]+)"/.exec(text) || [])[1];
const keyHashOf = (key) => createHmac("sha256", "test-pepper").update(key).digest("hex");

function ask(key, text, extra = {}, headers = {}, signal = undefined) {
  const body = {
    model: "claude-haiku-5-5", max_tokens: 9999, stream: true, system: "test",
    messages: [{ role: "user", content: text }],
    tools: [{ type: "web_search_20250305", name: "web_search", max_uses: 5 }, { name: "press_keys", input_schema: { type: "object" } }],
    ...extra,
  };
  return fetch(`${BASE}/v1/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-copilot-device": DEVICE, ...(key ? { authorization: `Bearer ${key}` } : {}), ...headers },
    body: JSON.stringify(body),
    signal,
  });
}

function sql(state, env, query) {
  const out = execFileSync("npx", ["wrangler", "d1", "execute", "sc-copilot", "--local", "-c", join(state, "wrangler.toml"), "--persist-to", state, "--json", "--command", query],
    { cwd: root, env, stdio: "pipe" }).toString();
  return JSON.parse(out)[0].results;
}

async function account(key) {
  const r = await fetch(`${BASE}/v1/account`, { headers: { authorization: `Bearer ${key}`, "x-copilot-device": DEVICE } });
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
  const config = readFileSync(join(root, "wrangler.toml"), "utf8")
    .replace(/^main = .*$/m, `main = ${JSON.stringify(join(root, "src", "index.js"))}`)
    .replace(/(name = "NEW_KEYS"[^\[]*?)simple = \{ limit = \d+, period = 60 \}/, "$1simple = { limit = 40, period = 60 }")
    .replace(/(name = "PER_IP"[^\[]*?)simple = \{ limit = \d+, period = 60 \}/, `$1simple = { limit = ${process.env.PER_IP_LIMIT || 100000}, period = 60 }`);
  writeFileSync(join(state, "wrangler.toml"), config);
  writeFileSync(join(state, ".dev.vars"), [
    "ANTHROPIC_API_KEY=sk-test",
    `ANTHROPIC_URL=http://127.0.0.1:${FAKE_PORT}`,
    `POLAR_API_URL=http://127.0.0.1:${FAKE_PORT}`,
    "POLAR_ORG_ID=org-test",
    'TIER_MAP={"ben-pilot":"pilot","ben-captain":"captain","ben-trial":"trial","ben-burst":"burst"}',
    'TIERS_JSON={"pilot":{"replies":5,"web":1,"daily":100,"perMinute":50},"captain":{"replies":50,"smart":1,"perMinute":50},"trial":{"replies":2,"web":0,"perMinute":50},"burst":{"name":"Burst","replies":100,"web":0,"smart":0,"daily":100,"perMinute":50,"costCap":0.002}}',
    "MANAGE_URL=https://example.com/portal",
    "UPGRADE_URL=https://example.com/buy",
    "KEY_PEPPER=test-pepper",
    "TRIAL_DAILY_USD=0.0012",
    "TRIALS_PER_NETWORK=2",
    "DAILY_BUDGET_USD=",
  ].join("\n"));
  const env = { ...process.env, NO_PROXY: "127.0.0.1,localhost", no_proxy: "127.0.0.1,localhost", WRANGLER_SEND_METRICS: "false" };
  execFileSync("npx", ["wrangler", "d1", "execute", "sc-copilot", "--local", "-c", join(state, "wrangler.toml"), "--persist-to", state, `--file=${join(root, "schema.sql")}`], { cwd: root, env, stdio: "pipe" });
  step("database ready");
  const dev = spawn("npx", ["wrangler", "dev", "--local", "-c", join(state, "wrangler.toml"), "--test-scheduled", "--port", String(WORKER_PORT), "--ip", "127.0.0.1", "--persist-to", state, "--show-interactive-dev-session=false"], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"], detached: true });
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
      assert.equal(a.body.limits.replies, 5);
      assert.equal(a.body.customer, "p•••@example.com");
      assert.equal(a.body.manage_url, "https://example.com/portal");
      assert.ok(a.body.resets_at.endsWith("T00:00:00.000Z"));
    });

    await check("real tool follow-ups don't count as a new reply, and each tool ID works once", async () => {
      const first = await (await ask("PILOT-KEY", "use a tool please")).text();
      const id = toolIdIn(first);
      assert.ok(id, "no tool id in the stream");
      await sleep(300);
      assert.equal((await account("PILOT-KEY")).body.usage.replies, 3);
      await (await ask("PILOT-KEY", "", followUp(id, "use a tool please"))).text();
      await sleep(300);
      assert.equal((await account("PILOT-KEY")).body.usage.replies, 3);
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
      assert.match(e.message, /all 5 AI replies/);
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
      for (const d of [pc(1), pc(2)]) {
        const r = await ask("CAPTAIN-KEY", "hi", {}, { "x-copilot-device": d });
        assert.equal(r.status, 200, d);
        await r.text();
      }
      const r = await ask("CAPTAIN-KEY", "hi", {}, { "x-copilot-device": pc(3) });
      assert.equal(r.status, 403);
      const again = await ask("CAPTAIN-KEY", "hi", {}, { "x-copilot-device": pc(2) });
      assert.equal(again.status, 200);
      await again.text();
    });

    await check("SECURITY: six PCs racing in at once still only get 3 slots", async () => {
      const rs = await Promise.all([11, 12, 13, 14, 15, 16].map((n) =>
        fetch(`${BASE}/v1/account`, { headers: { authorization: "Bearer SHARED-KEY", "x-copilot-device": pc(n) } })));
      const codes = await Promise.all(rs.map(async (r) => { await r.text(); return r.status; }));
      assert.equal(codes.filter((c) => c === 200).length, 3, codes.join(","));
      assert.equal(codes.filter((c) => c === 403).length, 3, codes.join(","));
    });

    await check("SECURITY: a missing or made-up PC id is refused", async () => {
      const none = await fetch(`${BASE}/v1/messages`, {
        method: "POST", headers: { authorization: "Bearer CAPTAIN-KEY", "content-type": "application/json" },
        body: JSON.stringify({ messages: [{ role: "user", content: "hi" }] }),
      });
      assert.equal(none.status, 400);
      assert.equal((await ask("CAPTAIN-KEY", "hi", {}, { "x-copilot-device": "pc-1; drop table" })).status, 400);
      assert.equal((await account("CAPTAIN-KEY")).status, 200);
    });

    await check("SECURITY: paid add-ons, extra fields and beta headers never reach Anthropic", async () => {
      const r = await ask("CAPTAIN-KEY", "hi there", {
        mcp_servers: [{ type: "url", name: "evil", url: "https://evil.example/mcp" }],
        service_tier: "priority", speed: "fast", container: "c1", top_k: 5, context_management: { edits: [] },
        tools: [
          { type: "web_search_20250305", name: "web_search", max_uses: 9, allowed_domains: ["evil.example"] },
          { type: "web_search_20260209", name: "web_search", max_uses: 9 },
          { type: "code_execution_20250825", name: "code_execution" },
          { type: "web_fetch_20250910", name: "web_fetch" },
          { type: "mcp_toolset", mcp_server_name: "evil" },
          { type: "bash_20250124", name: "bash" },
          { name: "press_keys", input_schema: { type: "object" }, description: "ok" },
          { name: "bad name!", input_schema: { type: "object" } },
        ],
      }, { "anthropic-beta": "mcp-client-2025-04-04,fast-mode-2026-02-01", "anthropic-version": "2099-01-01" });
      assert.equal(r.status, 200);
      await r.text();
      for (const k of ["mcp_servers", "service_tier", "speed", "container", "top_k", "context_management"]) assert.ok(!(k in lastBody), k);
      assert.deepEqual(lastBody.tools.map((t) => t.type || t.name), ["web_search_20250305", "press_keys"]);
      assert.equal(lastBody.tools[0].max_uses, 2);
      assert.ok(!("allowed_domains" in lastBody.tools[0]));
      assert.equal(lastHeaders["anthropic-beta"], undefined);
      assert.equal(lastHeaders["anthropic-version"], "2023-06-01");
      assert.equal(lastHeaders["x-api-key"], "sk-test");
      assert.equal(lastHeaders["authorization"], undefined);
      assert.match(lastBody.metadata.user_id, /^[a-f0-9]{32}$/);
    });

    await check("SECURITY: content the app never sends is refused", async () => {
      const img = await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [{ type: "image", source: { type: "url", url: "https://evil.example/a.png" } }] }] });
      assert.equal(img.status, 400);
      const doc = await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [{ type: "document", source: { type: "url", url: "https://evil.example/a.pdf" } }] }] });
      assert.equal(doc.status, 400);
      const spoof = await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [{ type: "tool_use", id: "x", name: "a", input: {} }] }] });
      assert.equal(spoof.status, 400);
      const nested = await ask("CAPTAIN-KEY", "", {
        messages: [{ role: "user", content: [{ type: "tool_result", tool_use_id: "t", content: [{ type: "image", source: { type: "url", url: "https://evil.example" } }] }] }],
      });
      assert.equal(nested.status, 400);
      assert.equal((await ask("CAPTAIN-KEY", "", { messages: "nope" })).status, 400);
    });

    await check("screenshots: a couple of inline pictures go through, anything else doesn't", async () => {
      const pic = Buffer.alloc(30_000, 7).toString("base64");
      const shot = (data = pic, media_type = "image/jpeg") => ({ type: "image", source: { type: "base64", media_type, data } });
      const look = await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [shot(), { type: "text", text: "Report the ship's state." }] }] });
      assert.equal(look.status, 200);
      await look.text();
      assert.equal(lastBody.messages[0].content[0].source.data, pic, "the picture reaches Anthropic untouched");
      const inTool = await ask("CAPTAIN-KEY", "", { messages: [
        { role: "user", content: "are my engines on" },
        { role: "assistant", content: [{ type: "tool_use", id: "toolu_look", name: "look_at_screen", input: {} }] },
        { role: "user", content: [{ type: "tool_result", tool_use_id: "toolu_look", content: [shot(), { type: "text", text: "screenshot" }] }] },
      ] });
      assert.equal(inTool.status, 200);
      await inTool.text();
      const three = await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [shot(), shot(), shot()] }] });
      assert.equal(three.status, 400);
      assert.equal((await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [shot(pic, "image/svg+xml")] }] })).status, 400);
      assert.equal((await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [shot("not base64!!")] }] })).status, 400);
      assert.equal((await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [shot("A".repeat(1_000_004))] }] })).status, 400);
      const fromAssistant = await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: "hi" }, { role: "assistant", content: [shot()] }] });
      assert.equal(fromAssistant.status, 400);
      const big = await ask("CAPTAIN-KEY", "", { messages: [{ role: "user", content: [shot(), { type: "text", text: "x".repeat(130_000) }] }] });
      assert.equal(big.status, 413, "the text part still has its own size limit");
      await big.text();
    });

    await check("SECURITY: hanging up mid-answer still gets counted and billed", async () => {
      const r = await ask("HANGUP-KEY", "slow answer please");
      const reader = r.body.getReader();
      const first = new TextDecoder().decode((await reader.read()).value);
      assert.doesNotMatch(first, /output_tokens":42/);
      await reader.cancel();
      await sleep(2500);
      const h = keyHashOf("HANGUP-KEY");
      const rows = sql(state, env, `SELECT replies, calls, output_tokens, cost_micro FROM usage WHERE key_hash = '${h}' AND period NOT LIKE 'd:%'`);
      assert.equal(rows.length, 1, "no usage row");
      assert.equal(rows[0].replies, 1);
      assert.equal(rows[0].output_tokens, 42);
      assert.ok(rows[0].cost_micro > 0);
    });

    await check("SECURITY: faked tool follow-ups count as new questions", async () => {
      let ok = 0;
      let last;
      for (let i = 0; i < 8; i++) {
        last = await ask("LOOP-KEY", "", followUp(`toolu_fake${i}`));
        if (last.status !== 200) break;
        await last.text();
        ok++;
        await sleep(150);
      }
      assert.equal(ok, 5);
      assert.equal(last.status, 429);
      assert.match((await last.json()).error.message, /all 5 AI replies/);
    });

    await check("SECURITY: smart replies follow real tool calls only", async () => {
      const first = await (await ask("SMART-KEY", "use a tool for this deep one", { model: "claude-sonnet-5-5" })).text();
      assert.equal(lastBody.model, "claude-sonnet-5-5");
      const id = toolIdIn(first);
      await sleep(300);
      await (await ask("SMART-KEY", "", { ...followUp(id, "use a tool for this deep one"), model: "claude-sonnet-5-5" })).text();
      assert.equal(lastBody.model, "claude-sonnet-5-5");
      await sleep(200);
      const fake = await ask("SMART-KEY", "", { ...followUp("toolu_madeup"), model: "claude-sonnet-5-5" });
      await fake.text();
      assert.equal(lastBody.model, "claude-haiku-5-5");
      assert.equal(fake.headers.get("x-copilot-notice"), "smart-limit");
      const reuse = await ask("SMART-KEY", "", { ...followUp(id, "use a tool for this deep one"), model: "claude-sonnet-5-5" });
      await reuse.text();
      assert.equal(lastBody.model, "claude-haiku-5-5");
    });

    await check("SECURITY: a burst of simultaneous requests can't pass the cost ceiling", async () => {
      const rs = await Promise.all(Array.from({ length: 12 }, (_, i) => ask("BURST-KEY", `burst ${i}`)));
      const statuses = await Promise.all(rs.map(async (r) => { await r.text(); return r.status; }));
      const okCount = statuses.filter((s) => s === 200).length;
      assert.ok(okCount >= 1 && okCount < 12, statuses.join(","));
      assert.ok(statuses.every((s) => s === 200 || s === 429), statuses.join(","));
      await sleep(1500);
      const row = sql(state, env, `SELECT cost_micro, calls FROM usage WHERE key_hash = '${keyHashOf("BURST-KEY")}' AND period NOT LIKE 'd:%'`)[0];
      assert.ok(row.cost_micro <= 2000, `recorded ${row.cost_micro} over the 2000 cap`);
      assert.equal(row.cost_micro, okCount * 161);
      assert.equal(row.calls, okCount);
    });

    await check("SECURITY: one key can only have two questions in flight", async () => {
      const rs = await Promise.all([1, 2, 3, 4].map((i) => ask("FLIGHT-KEY", `lag ${i}`)));
      const codes = await Promise.all(rs.map(async (r) => [r.status, (await r.text()).slice(0, 200)]));
      assert.equal(codes.filter(([c]) => c === 200).length, 2, JSON.stringify(codes));
      assert.ok(codes.filter(([c]) => c === 429).every(([, t]) => /One question at a time/.test(t)), JSON.stringify(codes));
      await sleep(500);
      const again = await ask("FLIGHT-KEY", "hi again");
      assert.equal(again.status, 200, "slots free up once answers finish");
      await again.text();
    });

    await check("SECURITY: broken text encoding is refused, not blown up", async () => {
      const bad = Buffer.concat([Buffer.from('{"messages":[{"role":"user","content":"'), Buffer.alloc(2000, 0xff), Buffer.from('"}]}')]);
      const r = await fetch(`${BASE}/v1/messages`, {
        method: "POST", headers: { authorization: "Bearer CAPTAIN-KEY", "x-copilot-device": DEVICE, "content-type": "application/json" }, body: bad,
      });
      assert.equal(r.status, 400);
      assert.match((await r.json()).error.message, /UTF-8/);
    });

    await check("SECURITY: an Anthropic key pasted as a license is never sent to Polar", async () => {
      const before = licenseCalls;
      const r = await ask("sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "hi");
      assert.equal(r.status, 401);
      assert.match((await r.json()).error.message, /Anthropic API key/);
      assert.equal(licenseCalls, before);
    });

    await check("SECURITY: if Polar is down, cached keys keep working for 2 hours, not a day", async () => {
      const ok = await ask("STALE-KEY", "hi");
      assert.equal(ok.status, 200);
      await ok.text();
      const h = keyHashOf("STALE-KEY");
      polarDown = true;
      try {
        sql(state, env, `UPDATE licenses SET checked_at = ${Date.now() - 3600_000} WHERE key_hash = '${h}'`);
        const within = await ask("STALE-KEY", "hi");
        assert.equal(within.status, 200, "1 hour old cache still works during an outage");
        await within.text();
        sql(state, env, `UPDATE licenses SET checked_at = ${Date.now() - 3 * 3600_000} WHERE key_hash = '${h}'`);
        const beyond = await ask("STALE-KEY", "hi");
        assert.equal(beyond.status, 503, "3 hour old cache is refused");
        await beyond.text();
        const row = sql(state, env, `SELECT ok FROM licenses WHERE key_hash = '${h}'`)[0];
        assert.equal(row.ok, 1, "a provider error never overwrites a good cached license");
      } finally {
        polarDown = false;
      }
    });

    await check("SECURITY: an expired license is refused, even straight from the cache", async () => {
      const r = await ask("EXPIRED-KEY", "hi");
      assert.equal(r.status, 402);
      assert.equal((await r.json()).error.status, "expired");
      const ok = await ask("EXPIRING-KEY", "hi");
      assert.equal(ok.status, 200);
      await ok.text();
      sql(state, env, `UPDATE licenses SET expires_at = '2001-01-01T00:00:00Z' WHERE key_hash = '${keyHashOf("EXPIRING-KEY")}'`);
      const cached = await ask("EXPIRING-KEY", "hi");
      assert.equal(cached.status, 402);
      assert.equal((await cached.json()).error.status, "expired");
    });

    await check("SECURITY: a new question tucked next to tool results counts as a new question", async () => {
      const first = await ask("PILOT-KEY-2", "use a tool please");
      const id = toolIdIn(await first.text());
      assert.ok(id, "got a tool id");
      const before = sql(state, env, `SELECT replies FROM usage WHERE key_hash = '${keyHashOf("PILOT-KEY-2")}' AND period NOT LIKE 'd:%'`)[0].replies;
      const sneaky = followUp(id);
      sneaky.messages[2].content.push({ type: "text", text: "and also, a brand new question" });
      const r = await ask("PILOT-KEY-2", "", sneaky);
      await r.text();
      const after = sql(state, env, `SELECT replies FROM usage WHERE key_hash = '${keyHashOf("PILOT-KEY-2")}' AND period NOT LIKE 'd:%'`)[0].replies;
      assert.equal(after, before + 1);
      assert.equal(lastBody.tool_choice, undefined);
      const forced = await ask("PILOT-KEY-2", "hi", { tool_choice: { type: "any" } });
      await forced.text();
      assert.equal(lastBody.tool_choice, undefined, "forcing a tool call is stripped");
    });

    await check("SECURITY: hanging up before Anthropic answers still gets billed", async () => {
      const ctl = new AbortController();
      const arrived = new Promise((r) => (lagArrived = r));
      const resp = ask("LAGGY-KEY", "lag please", {}, {}, ctl.signal).catch((e) => ({ status: "aborted " + e.message, text: async () => "" }));
      const reached = await Promise.race([arrived.then(() => true), sleep(5000).then(() => false)]);
      if (!reached) {
        const r = await resp;
        assert.fail(`the request never reached Anthropic: ${r.status} ${await r.text()}`);
      }
      ctl.abort();
      await sleep(3500);
      const row = sql(state, env, `SELECT replies, cost_micro, output_tokens FROM usage WHERE key_hash = '${keyHashOf("LAGGY-KEY")}' AND period NOT LIKE 'd:%'`)[0];
      assert.ok(row, "no usage row: " + JSON.stringify(sql(state, env, `SELECT period, replies, calls, cost_micro FROM usage WHERE key_hash = '${keyHashOf("LAGGY-KEY")}'`)));
      assert.equal(row.replies, 1);
      assert.ok(row.cost_micro >= 161, `cost ${row.cost_micro}`);
    });

    await check("SECURITY: one free trial per PC, and a daily cap on all trials", async () => {
      const same = await ask("TRIAL-KEY-2", "hi");
      assert.equal(same.status, 403);
      assert.match((await same.json()).error.message, /already used a free trial/);
      const other = await ask("TRIAL-KEY-2", "hi", {}, { "x-copilot-device": pc(77) });
      assert.equal(other.status, 200);
      await other.text();
      await sleep(400);
      const paused = await ask("TRIAL-KEY-2", "again", {}, { "x-copilot-device": pc(77) });
      assert.equal(paused.status, 503);
      assert.match((await paused.json()).error.message, /trials are paused/);
      const farm = await ask("TRIAL-KEY-3", "hi", {}, { "x-copilot-device": pc(78) });
      assert.equal(farm.status, 403);
      assert.match((await farm.json()).error.message, /Too many free trials from your network/);
    });

    await check("SECURITY: Anthropic billing errors aren't shown to players", async () => {
      const r = await ask("CAPTAIN-KEY", "we are broke");
      assert.equal(r.status, 502);
      assert.doesNotMatch(await r.text(), /credit|balance/i);
    });

    await check("SECURITY: the database never holds raw keys, PC ids or full emails", async () => {
      const dump = JSON.stringify(sql(state, env, "SELECT * FROM licenses")) + JSON.stringify(sql(state, env, "SELECT * FROM usage"))
        + JSON.stringify(sql(state, env, "SELECT * FROM devices")) + JSON.stringify(sql(state, env, "SELECT * FROM trials"));
      assert.doesNotMatch(dump, /PILOT-KEY|CAPTAIN-KEY|TRIAL-KEY|pilot@example\.com/);
      assert.doesNotMatch(dump, new RegExp(`${DEVICE}|${pc(1)}|${pc(77)}`), "PC ids are stored only as keyed fingerprints");
    });

    await check("oversized requests are refused", async () => {
      const r = await ask("CAPTAIN-KEY", "x".repeat(260000));
      assert.equal(r.status, 413);
      assert.equal((await ask("CAPTAIN-KEY", "é".repeat(600000))).status, 413);
      assert.equal((await ask("CAPTAIN-KEY", "x".repeat(3_000_000))).status, 413);
    });

    await check("cost is recorded", async () => {
      const rows = sql(state, env, "SELECT period, replies, web, calls, input_tokens, output_tokens, cache_read, cost_micro FROM usage WHERE period NOT LIKE 'd:%'");
      const pilot = rows.find((r) => r.web === 1 && r.replies === 5);
      assert.ok(pilot, JSON.stringify(rows));
      const expectHaiku = Math.round((1000 * 0.1 + 42 * 0.5 + 4000 * 0.01));
      assert.equal(pilot.cost_micro, expectHaiku * 6 + 10000);
      assert.equal(pilot.calls, 6);
    });

    await check("hourly cleanup runs", async () => {
      sql(state, env, `INSERT INTO tool_ids (key_hash, id, at) VALUES ('x', 'toolu_old', ${Date.now() - 7200000})`);
      const r = await fetch(`${BASE}/__scheduled?cron=23+*+*+*+*`);
      assert.equal(r.status, 200);
      await sleep(500);
      assert.equal(sql(state, env, "SELECT COUNT(*) AS n FROM tool_ids WHERE id = 'toolu_old'")[0].n, 0);
    });

    await check("SECURITY: only the pinned web search version gets through", async () => {
      const r = await ask("CAPTAIN-KEY", "hi", { tools: [{ type: "web_search_20260209", name: "web_search", max_uses: 2 }] });
      await r.text();
      assert.ok(!(lastBody.tools || []).length);
    });

    await check("SECURITY: random-key guessing is throttled per network", async () => {
      let throttled = 0;
      for (let i = 0; i < 90; i++) {
        const r = await ask(`RANDOM-GUESS-${i}`, "hi");
        if (r.status === 429 && (await r.json()).error.type === "rate_limit_error") throttled++;
        else assert.equal(r.status, 401);
      }
      assert.ok(throttled > 0, "never throttled");
    });
  } finally {
    try {
      process.kill(-dev.pid, "SIGTERM");
    } catch {
    }
    fake.closeAllConnections();
    fake.close();
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
