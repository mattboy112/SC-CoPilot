const FIELDS = ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"];

export function emptyUsage() {
  return { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, web_search_requests: 0 };
}

export function mergeUsage(total, u) {
  if (!u) return total;
  for (const f of FIELDS) if (typeof u[f] === "number") total[f] = Math.max(total[f], u[f]);
  const web = u.server_tool_use && u.server_tool_use.web_search_requests;
  if (typeof web === "number") total.web_search_requests = Math.max(total.web_search_requests, web);
  return total;
}

export function usageFromEvent(ev) {
  if (!ev || typeof ev !== "object") return null;
  if (ev.type === "message_start" && ev.message) return ev.message.usage || null;
  if (ev.type === "message_delta") return ev.usage || null;
  return null;
}

export function toolUseId(ev) {
  if (ev && ev.type === "content_block_start" && ev.content_block && ev.content_block.type === "tool_use") {
    const id = ev.content_block.id;
    if (typeof id === "string" && /^[A-Za-z0-9_-]{1,100}$/.test(id)) return id;
  }
  return null;
}

export function usageScanner(onToolUse = () => {}) {
  const decoder = new TextDecoder();
  let buf = "";
  const total = emptyUsage();
  const scan = (text) => {
    buf += text;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      let ev;
      try {
        ev = JSON.parse(data);
      } catch {
        continue;
      }
      mergeUsage(total, usageFromEvent(ev));
      const id = toolUseId(ev);
      if (id) onToolUse(id);
    }
  };
  return {
    push: (chunk) => scan(decoder.decode(chunk, { stream: true })),
    done: () => {
      scan(decoder.decode() + "\n");
      return total;
    },
  };
}

export async function meterBody(stream, onToolUse) {
  const scanner = usageScanner(onToolUse);
  const reader = stream.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      scanner.push(value);
    }
  } catch {
  }
  return scanner.done();
}

export function toolResultIds(body) {
  const msgs = body && Array.isArray(body.messages) ? body.messages : [];
  const last = msgs[msgs.length - 1];
  if (!last || last.role !== "user" || !Array.isArray(last.content) || !last.content.length) return [];
  if (!last.content.every((b) => b && b.type === "tool_result")) return [];
  const ids = last.content.map((b) => String(b.tool_use_id || ""));
  return [...new Set(ids)];
}
