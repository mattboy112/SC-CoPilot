import assert from "node:assert/strict";
import { costUsd, worstCaseUsd } from "../src/plans.js";
import { checkLicense, localOnly } from "../src/license.js";
import { networkOf, missingConfig } from "../src/index.js";
import { toolResultIds, usageScanner } from "../src/meter.js";
import { sanitize, BadRequest } from "../src/sanitize.js";

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("long requests are priced at the higher rate", () => {
  const small = costUsd("claude-haiku-5-5", { input_tokens: 99_000 });
  const big = costUsd("claude-haiku-5-5", { input_tokens: 101_000 });
  assert.ok(big > small * 5 * 0.99);
});

test("worst case is never below the real cost of the same request", () => {
  const real = costUsd("claude-sonnet-5-5", { input_tokens: 2000, cache_read_input_tokens: 20000, output_tokens: 1024, web_search_requests: 2 });
  assert.ok(worstCaseUsd("claude-sonnet-5-5", 22000, 1024, 2) >= real);
});

test("the service refuses to run with a secret or setting missing", () => {
  const full = { ANTHROPIC_API_KEY: "k", KEY_PEPPER: "p", POLAR_ORG_ID: "o", TIER_MAP: '{"b":"pilot"}' };
  assert.deepEqual(missingConfig(full), []);
  assert.deepEqual(missingConfig({ ...full, KEY_PEPPER: "" }), ["KEY_PEPPER"]);
  assert.deepEqual(missingConfig({ ...full, ANTHROPIC_API_KEY: undefined }), ["ANTHROPIC_API_KEY"]);
  assert.deepEqual(missingConfig({ ...full, TIER_MAP: "{}" }), ["TIER_MAP"]);
  assert.deepEqual(missingConfig({ ...full, TIER_MAP: "not json" }), ["TIER_MAP"]);
  assert.deepEqual(missingConfig({ ...full, LICENSE_PROVIDER: "lemonsqueezy" }), ["LS_STORE_ID"]);
});

test("IPv6 addresses are grouped by /64, or by /48 for the stricter limits", () => {
  assert.equal(networkOf("2001:db8:1:2:aaaa::1"), "2001:db8:1:2::/64");
  assert.equal(networkOf("2001:0db8:0001:0002:ffff:ffff:ffff:ffff"), "2001:db8:1:2::/64");
  assert.equal(networkOf("2001:db8::5"), "2001:db8:0:0::/64");
  assert.equal(networkOf("2001:db8:1:2:aaaa::1", 48), "2001:db8:1::/48");
  assert.equal(networkOf("2001:db8:1:9999::1", 48), networkOf("2001:db8:1:2::1", 48), "one /48 is one network for new-key checks");
  assert.equal(networkOf("203.0.113.7"), "203.0.113.7");
  assert.equal(networkOf("203.0.113.7", 48), "203.0.113.7");
  assert.equal(networkOf(null), "unknown");
});

test("web search requests reserve for every pass and every result re-read", () => {
  const body = 40_000;
  const twoSearches = costUsd("claude-haiku-5-5", { input_tokens: 3 * body + 30_000 + 60_000, output_tokens: 1024, web_search_requests: 2 });
  assert.ok(worstCaseUsd("claude-haiku-5-5", body, 1024, 2) >= twoSearches);
  const reviewerCase = costUsd("claude-sonnet-5-5", { input_tokens: 105_000, output_tokens: 1024, web_search_requests: 2 });
  assert.ok(worstCaseUsd("claude-sonnet-5-5", 20_000, 1024, 2) >= reviewerCase);
});

test("only Haiku 5.5 has the 5x long-prompt price", () => {
  assert.ok(costUsd("claude-haiku-5-5", { input_tokens: 150_000 }) > 5 * 0.99 * costUsd("claude-haiku-5-5", { input_tokens: 99_000 }) * (150 / 99));
  assert.equal(costUsd("claude-sonnet-5-5", { input_tokens: 150_000 }), 150_000 * 2 / 1e6);
});

test("test-only URLs are ignored unless they point at this machine", () => {
  assert.equal(localOnly("http://127.0.0.1:8788", "https://api.polar.sh"), "http://127.0.0.1:8788");
  assert.equal(localOnly("https://evil.example", "https://api.polar.sh"), "https://api.polar.sh");
  assert.equal(localOnly("http://127.0.0.1.evil.example", "https://x"), "https://x");
  assert.equal(localOnly(undefined, "https://x"), "https://x");
});

test("Lemon Squeezy: busy is an error, inactive keys work, other stores don't", async () => {
  const env = { LICENSE_PROVIDER: "lemonsqueezy", LS_STORE_ID: "42", TIER_MAP: '{"7":"pilot","__proto__":"captain"}' };
  const real = globalThis.fetch;
  const answer = (status, body) => { globalThis.fetch = async () => new Response(JSON.stringify(body), { status }); };
  try {
    answer(429, { error: "Too many requests" });
    await assert.rejects(checkLicense(env, "k"));
    answer(400, { error: "bad" });
    await assert.rejects(checkLicense(env, "k"));
    answer(404, { valid: false, error: "license_key not found.", license_key: null });
    assert.equal((await checkLicense(env, "k")).status, "invalid");
    answer(200, { valid: true, license_key: { status: "inactive" }, meta: { store_id: 42, variant_id: 7 } });
    assert.deepEqual([(await checkLicense(env, "k")).ok, (await checkLicense(env, "k")).tier], [true, "pilot"]);
    answer(200, { valid: false, license_key: { status: "expired" }, meta: { store_id: 42, variant_id: 7 } });
    assert.equal((await checkLicense(env, "k")).ok, false);
    answer(200, { valid: true, license_key: { status: "active" }, meta: { store_id: 99, variant_id: 7 } });
    assert.equal((await checkLicense(env, "k")).status, "invalid");
    answer(200, { valid: true, license_key: { status: "active" }, meta: { store_id: 42, variant_id: "__proto__" } });
    assert.equal((await checkLicense({ ...env, TIER_MAP: '{"7":"pilot"}' }, "k")).ok, false, "prototype keys never map to a plan");
  } finally {
    globalThis.fetch = real;
  }
});

test("tool result IDs are read from the last user message only", () => {
  assert.deepEqual(toolResultIds({ messages: [{ role: "user", content: [{ type: "tool_result", tool_use_id: "a" }, { type: "tool_result", tool_use_id: "a" }, { type: "tool_result", tool_use_id: "b" }] }] }), ["a", "b"]);
  assert.deepEqual(toolResultIds({ messages: [{ role: "user", content: "hi" }] }), []);
  assert.deepEqual(toolResultIds({}), []);
  assert.deepEqual(toolResultIds({ messages: [{ role: "user", content: [{ type: "tool_result", tool_use_id: "a" }, { type: "text", text: "new question" }] }] }), []);
});

test("the meter picks up tool IDs as they stream", () => {
  const seen = [];
  const s = usageScanner((id) => seen.push(id));
  const enc = new TextEncoder();
  s.push(enc.encode('data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_1","name":"x"}}\n'));
  s.push(enc.encode('data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"bad id!"}}\n'));
  s.done();
  assert.deepEqual(seen, ["toolu_1"]);
});

test("odd JSON values can't sneak past the filter", () => {
  const opts = { model: "m", maxTokens: 1024, webLeft: 2, userId: "u" };
  const out = sanitize({ max_tokens: 1e309, messages: [{ role: "user", content: "x" }], __proto__: { admin: true }, constructor: "y" }, opts);
  assert.equal(out.body.max_tokens, 1024);
  assert.deepEqual(Object.keys(out.body).sort(), ["max_tokens", "messages", "metadata", "model"]);
  assert.equal(sanitize({ max_tokens: -5, messages: [{ role: "user", content: "x" }] }, opts).body.max_tokens, 1);
  assert.throws(() => sanitize({ messages: [{ role: "system", content: "x" }] }, opts), BadRequest);
  assert.throws(() => sanitize([], opts), BadRequest);
});

test("forced tool calls are stripped and tool results are capped", () => {
  const opts = { model: "claude-haiku-5-5", maxTokens: 1024, webLeft: 0, userId: "u" };
  const tools = [{ name: "get_contracts", input_schema: { type: "object" } }];
  const msgs = [{ role: "user", content: "hi" }, { role: "assistant", content: [{ type: "tool_use", id: "t1", name: "get_contracts", input: {} }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "x".repeat(50_000) }] }];
  for (const tc of [{ type: "any" }, { type: "tool", name: "get_contracts" }]) {
    assert.equal(sanitize({ messages: msgs, tools, tool_choice: tc }, opts).body.tool_choice, undefined);
  }
  assert.deepEqual(sanitize({ messages: msgs, tools, tool_choice: { type: "auto" } }, opts).body.tool_choice, { type: "auto" });
  assert.equal(sanitize({ messages: msgs, tools }, opts).body.messages[2].content[0].content.length, 10_000);
});

test("deeply nested tool schemas are refused before they can crash anything", () => {
  const opts = { model: "claude-haiku-5-5", maxTokens: 1024, webLeft: 0, userId: "u" };
  const deep = JSON.parse('{"a":'.repeat(15000) + "1" + "}".repeat(15000));
  assert.throws(() => sanitize({ messages: [{ role: "user", content: "hi" }], tools: [{ name: "t", input_schema: deep }] }, opts), BadRequest);
  const ok = { type: "object", properties: { a: { type: "object", properties: { b: { type: "string" } } } } };
  assert.equal(sanitize({ messages: [{ role: "user", content: "hi" }], tools: [{ name: "t", input_schema: ok }] }, opts).body.tools.length, 1);
  const deepArr = JSON.parse("[".repeat(40000) + "]".repeat(40000));
  assert.throws(() => sanitize({ messages: [{ role: "user", content: [{ type: deepArr }] }] }, opts), BadRequest);
  const odd = sanitize({ messages: [{ role: "assistant", content: [{ type: "tool_use", id: deepArr, name: "t", input: {} }] }] }, opts);
  assert.equal(odd.body.messages[0].content[0].id, "");
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`PASS  ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL  ${name}  ${e.message}`);
  }
}
if (failed) process.exit(1);
console.log(`${tests.length} unit checks passed`);
