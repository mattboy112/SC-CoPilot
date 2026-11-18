export class BadRequest extends Error {}

const NAME = /^[a-zA-Z0-9_-]{1,64}$/;
const WEB_SEARCH_TYPES = new Set(["web_search_20250305"]);
const MAX_TOOLS = 40;
const MAX_MESSAGES = 120;
const MAX_BLOCKS = 100;
const MAX_TOOL_RESULT = 10_000;

const MAX_DEPTH = 24;

const obj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

function shallow(v, what) {
  const stack = [[v, 1]];
  while (stack.length) {
    const [x, d] = stack.pop();
    if (x === null || typeof x !== "object") continue;
    if (d > MAX_DEPTH) throw new BadRequest(`${what} is nested too deeply.`);
    for (const k of Object.keys(x)) stack.push([x[k], d + 1]);
  }
  return v;
}
const str = (v, max = 100_000) =>
  (typeof v === "string" ? v : typeof v === "number" || typeof v === "boolean" ? String(v) : "").slice(0, max);

function withCache(out, cc) {
  if (obj(cc) && cc.type === "ephemeral") out.cache_control = { type: "ephemeral" };
  return out;
}

function textBlock(b) {
  if (!obj(b) || b.type !== "text" || typeof b.text !== "string") throw new BadRequest("Each text block needs text.");
  return withCache({ type: "text", text: b.text }, b.cache_control);
}

function webResults(content) {
  if (Array.isArray(content)) {
    return content.filter((r) => obj(r) && r.type === "web_search_result").slice(0, 20).map((r) => {
      const out = { type: "web_search_result", url: str(r.url, 2000), title: str(r.title, 500), encrypted_content: str(r.encrypted_content, 200_000) };
      if (r.page_age) out.page_age = str(r.page_age, 50);
      return out;
    });
  }
  if (obj(content) && content.type === "web_search_tool_result_error") {
    return { type: "web_search_tool_result_error", error_code: str(content.error_code, 50) };
  }
  throw new BadRequest("Web search results aren't in the expected shape.");
}

function block(b, role) {
  if (!obj(b)) throw new BadRequest("Message content isn't in the expected shape.");
  const assistant = role === "assistant";
  switch (b.type) {
    case "text":
      return textBlock(b);
    case "tool_use":
      if (!assistant || !NAME.test(String(b.name))) break;
      return withCache({ type: "tool_use", id: str(b.id, 200), name: b.name, input: obj(b.input) ? shallow(b.input, "A tool call") : {} }, b.cache_control);
    case "tool_result": {
      if (assistant) break;
      const content = Array.isArray(b.content)
        ? b.content.slice(0, 10).map(textBlock).map((t) => ({ ...t, text: t.text.slice(0, MAX_TOOL_RESULT) }))
        : str(b.content, MAX_TOOL_RESULT);
      const out = { type: "tool_result", tool_use_id: str(b.tool_use_id, 200), content };
      if (b.is_error === true) out.is_error = true;
      return withCache(out, b.cache_control);
    }
    case "thinking":
      if (!assistant) break;
      return { type: "thinking", thinking: str(b.thinking), signature: str(b.signature, 100_000) };
    case "redacted_thinking":
      if (!assistant) break;
      return { type: "redacted_thinking", data: str(b.data, 200_000) };
    case "server_tool_use":
      if (!assistant || b.name !== "web_search") break;
      return { type: "server_tool_use", id: str(b.id, 200), name: "web_search", input: obj(b.input) ? { query: str(b.input.query, 500) } : {} };
    case "web_search_tool_result":
      if (!assistant) break;
      return { type: "web_search_tool_result", tool_use_id: str(b.tool_use_id, 200), content: webResults(b.content) };
  }
  throw new BadRequest(`Content of type "${str(b.type, 40)}" isn't supported by the Co-Pilot service.`);
}

function messages(list) {
  if (!Array.isArray(list) || !list.length || list.length > MAX_MESSAGES) throw new BadRequest("The conversation isn't in the expected shape.");
  return list.map((m) => {
    if (!obj(m) || (m.role !== "user" && m.role !== "assistant")) throw new BadRequest("Each message needs a user or assistant role.");
    if (typeof m.content === "string") return { role: m.role, content: m.content };
    if (!Array.isArray(m.content) || !m.content.length || m.content.length > MAX_BLOCKS) {
      throw new BadRequest("Message content isn't in the expected shape.");
    }
    return { role: m.role, content: m.content.map((b) => block(b, m.role)) };
  });
}

function system(s) {
  if (s === undefined || s === null) return undefined;
  if (typeof s === "string") return s;
  if (Array.isArray(s) && s.length <= 10) return s.map(textBlock);
  throw new BadRequest("The system prompt isn't in the expected shape.");
}

function tools(list, webLeft) {
  const out = [];
  let web = false;
  let dropped = false;
  if (!Array.isArray(list)) return { tools: out, web, dropped };
  for (const t of list.slice(0, MAX_TOOLS)) {
    if (!obj(t)) continue;
    if (typeof t.type === "string" && t.type.startsWith("web_search")) {
      if (!WEB_SEARCH_TYPES.has(t.type)) continue;
      if (web) continue;
      if (webLeft <= 0) {
        dropped = true;
        continue;
      }
      web = true;
      const uses = Math.max(1, Math.min(webLeft, Number(t.max_uses) || 2, 2));
      out.push(withCache({ type: t.type, name: "web_search", max_uses: uses }, t.cache_control));
      continue;
    }
    if ((t.type === undefined || t.type === "custom") && NAME.test(String(t.name)) && obj(t.input_schema)) {
      const tool = { name: t.name, input_schema: shallow(t.input_schema, "A tool definition") };
      if (t.description) tool.description = str(t.description, 8000);
      out.push(withCache(tool, t.cache_control));
    }
  }
  return { tools: out, web, dropped };
}

function toolChoice(tc) {
  if (!obj(tc)) return undefined;
  if (!["auto", "none"].includes(tc.type)) return undefined;
  const out = { type: tc.type };
  if (tc.disable_parallel_tool_use === true) out.disable_parallel_tool_use = true;
  return out;
}

function thinking(t, maxTokens) {
  if (!obj(t)) return undefined;
  if (t.type === "disabled" || t.type === "adaptive") return { type: t.type };
  if (t.type === "enabled") {
    const budget = Math.floor(Number(t.budget_tokens) || 0);
    if (budget >= 1024 && budget < maxTokens) return { type: "enabled", budget_tokens: budget };
    return { type: "disabled" };
  }
  return undefined;
}

export function sanitize(input, { model, maxTokens, webLeft, userId }) {
  if (!obj(input)) throw new BadRequest("That request wasn't a JSON object.");
  const max = Math.max(1, Math.min(Math.floor(Number(input.max_tokens)) || maxTokens, maxTokens));
  const body = { model, max_tokens: max, messages: messages(input.messages), metadata: { user_id: userId } };
  const sys = system(input.system);
  if (sys !== undefined) body.system = sys;
  const t = tools(input.tools, webLeft);
  if (t.tools.length) body.tools = t.tools;
  const tc = t.tools.length ? toolChoice(input.tool_choice) : undefined;
  if (tc) body.tool_choice = tc;
  const th = thinking(input.thinking, max);
  if (th) body.thinking = th;
  if (obj(input.output_config) && ["low", "medium", "high"].includes(input.output_config.effort)) {
    body.output_config = { effort: input.output_config.effort };
  }
  if (typeof input.temperature === "number" && input.temperature >= 0 && input.temperature <= 1) body.temperature = input.temperature;
  if (Array.isArray(input.stop_sequences)) {
    const stops = input.stop_sequences.filter((s) => typeof s === "string" && s && s.length <= 100).slice(0, 4);
    if (stops.length) body.stop_sequences = stops;
  }
  if (input.stream === true) body.stream = true;
  return { body, web: t.web, dropped: t.dropped };
}
