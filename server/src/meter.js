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

export function meterStream(onDone) {
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
      try {
        mergeUsage(total, usageFromEvent(JSON.parse(data)));
      } catch {
      }
    }
  };
  return new TransformStream({
    transform(chunk, controller) {
      controller.enqueue(chunk);
      scan(decoder.decode(chunk, { stream: true }));
    },
    flush() {
      scan(decoder.decode() + "\n");
      onDone(total);
    },
  });
}

export function isNewQuestion(body) {
  const msgs = Array.isArray(body.messages) ? body.messages : [];
  const last = msgs[msgs.length - 1];
  if (!last || last.role !== "user") return false;
  if (typeof last.content === "string") return true;
  if (!Array.isArray(last.content)) return false;
  return !last.content.some((b) => b && b.type === "tool_result") && last.content.some((b) => b && b.type === "text");
}
