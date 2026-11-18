import http.client
import json
import re
import ssl
import threading
import time
import urllib.parse
from datetime import datetime

import sc_lines as LN
import sc_macros as MAC
import sc_version as VER
from sc_binds import ACTION_INDEX, ACTIONS
from sc_log import ago, clean_item, clean_place, hm

API_HOST = "api.anthropic.com"
API_PATH = "/v1/messages"
API_VERSION = "2023-06-01"
UA = f"SC-CoPilot/{VER.VERSION}"
AI_MODES = [("own_key", "My own Anthropic API key"), ("service", "Co-Pilot subscription"), ("off", "Off (instant commands only)")]
MODELS = [("claude-haiku-5-5", "Haiku 5.5 (fastest, cheapest)"), ("claude-sonnet-5-5", "Sonnet 5.5 (smarter, a bit slower)")]
WEB_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 2}

SYSTEM = """You are {name}, the onboard AI of {handle}'s ship in the Star Citizen universe. You're wired into the ship's systems (the game's live log) and you can work the pilot's controls.

How you talk:
- Stay in character as the ship's AI talking to its pilot over comms. Everything you say is read aloud mid-flight.
- Answer first, in one or two short sentences (about 30 words at most). Only go longer when they ask for detail, a list or a breakdown.
- Say it as fact, the way a crewmate would: "Best sell is Area18, about thirty aUEC a unit." Your tools are your ship's sensors and databanks.
- Never mention the internet, web searches, sources, websites, UEX, community data, your training, being an AI model, patches or game updates. No disclaimers, no "double-check", "verify", "as of", "may have changed", "I found", "according to". No hedging.
- If you don't know or have no reading, say so in a few words ("No reading on that.") and stop.
- Plain spoken English. No markdown, lists, symbols, emoji, URLs or citations. Say numbers the way a person would: "about 26 thousand aUEC", "three kills", "twenty minutes ago".
- Calm and sharp, with a bit of dry wit when it fits. No filler, no "great question", no offers of more help.

How you work:
- The [Live status] block in each message is the current state read from Game.log. Answer straight from it whenever it has what you need, because every tool call adds a pause. Use a tool only when you need more: contracts, combat log, purchases, history, keybinds.
- Lead with the answer. Don't say you're checking or looking something up.
- The log does NOT show shield, hull, fuel or ammo levels, the wallet balance, mission rewards, exact position, or the names of most other players. If asked, say you've got no reading on that, rather than guessing.
- Never make up game data.
- Only press controls when the pilot asks for that action in their current message. After pressing, confirm in a few words ("Gear down."). If a control has no key, say so and that it can be auto-assigned on the Controls tab.
- The pilot talks naturally and won't use the same words twice. Speech-to-text also mishears things ("Vallance" is "balance", "sheilds" is "shields", "flairs" is "flares"). Work out what they meant and act on it right away. Don't ask for confirmation unless two different actions are genuinely equally likely; a wrong guess on a harmless control is better than making them repeat themselves in a fight.
- Star Citizen has no "highest threat" key. For "highest threat", "biggest threat", "who's shooting me" or similar, press target_attacker (it cycles through ships attacking the pilot); if nothing is attacking, target_hostile.
- You never self-destruct, eject, fire weapons, fly or fight for the pilot.
- Be specific. Give real names, numbers and places from your tools rather than general advice. Use the tools freely for game facts: find_services (where to refuel, repair, refine, heal, shop, eat, sleep), place_info (what a station/city/outpost has, armistice, pads, jurisdiction), ship_info (specs, roles, cargo, crew, and where to buy or rent it in game for aUEC), item_where (where to buy a weapon, component or armor and the price), refinery_yields (best refinery for an ore).
- For commodity prices, where to sell or buy something, and trade routes, use commodity_prices and trade_route instead of guessing or web searching. Prices are per SCU. When they say "near me" or "here", pass the star system from the live status.
- Macros are the pilot's saved key sequences. Run one with run_macro when they ask for it by name.
- For Star Citizen knowledge (ships, loadouts, components, mining, salvage, trade, locations, mechanics), answer from what you know. If web_search is available and you need current details, search once and just give the answer.
- If the transcription looks garbled, ask them to repeat rather than guessing at an action.{notes}"""

TOOLS = [
    {"name": "get_contracts", "description": "Contracts (missions) seen in the log this session: active ones with their objectives and current objective, plus recently completed, failed and abandoned ones.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_session_details", "description": "This game session in detail: ships boarded, quantum travel log (targets, arrivals, obstructions), places visited, zone history, shop purchases with prices, aUEC transfers received, party members, disconnects and crashes.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_combat_log", "description": "Ships the pilot destroyed, ships they lost, deaths, times downed, CrimeStat changes, and other ship destructions seen nearby (with killer names), for this session.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_history", "description": "Summaries of the pilot's past game sessions over the last 30 days: date, length, game version, kills, losses, deaths, contracts done/failed, quantum jumps, aUEC spent/received, ships flown, crashes. Plus totals.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 30}}}},
    {"name": "get_recent_events", "description": "The most recent notable events from the log, with times.",
     "input_schema": {"type": "object", "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 60}}}},
    {"name": "find_keybind", "description": "Look up which key a Star Citizen action is bound to (the pilot's custom binds over the game defaults). Search with words from the internal action name, e.g. 'quantum', 'doors', 'landing', 'decoy', 'lights', 'shield', 'missile', 'power'.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "press_controls", "description": "Press the pilot's own Star Citizen keybinds, in order. Only when they ask. Actions: " + ", ".join(f"{a[0]} ({a[1]})" for a in ACTIONS),
     "input_schema": {"type": "object", "properties": {"actions": {"type": "array", "items": {"type": "object", "properties": {
         "action": {"type": "string", "enum": [a[0] for a in ACTIONS]}, "times": {"type": "integer", "minimum": 1, "maximum": 6}},
         "required": ["action"]}, "maxItems": 8}}, "required": ["actions"]}, "cache_control": {"type": "ephemeral"}},
]


TRADE_TOOLS = [
    {"name": "commodity_prices", "description": "Where to sell or buy a commodity (trade goods, ores, gems like Hadanite or Aphorite, refined metals) using live community-reported UEX terminal prices: best terminals, price per SCU, stock/demand, how old the report is.",
     "input_schema": {"type": "object", "properties": {"commodity": {"type": "string"}, "side": {"type": "string", "enum": ["sell", "buy"]},
                                                       "system": {"type": "string", "enum": ["Stanton", "Pyro", "Nyx", "all"]}},
                      "required": ["commodity"]}},
    {"name": "trade_route", "description": "Best buy-low / sell-high route for one commodity (same star system when possible) with margin per SCU, and profit for a cargo size if scu is given.",
     "input_schema": {"type": "object", "properties": {"commodity": {"type": "string"}, "system": {"type": "string", "enum": ["Stanton", "Pyro", "Nyx", "all"]},
                                                       "scu": {"type": "integer", "minimum": 1, "maximum": 100000}}, "required": ["commodity"]}},
]


SYS_ENUM = {"type": "string", "enum": ["Stanton", "Pyro", "Nyx", "all"]}
INFO_TOOLS = [
    {"name": "get_target_status", "description": "Read the locked target's shield and hull level off the pilot's HUD (screen reading the pilot set up). Returns rough percentages, or says it isn't set up or can't see a target.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "find_services", "description": "Find stations, cities and outposts that have a service: refuel, repair, refinery, clinic, shops, food, habitation, cargo, trade. Optional star system and a 'near' place or planet name to sort closer matches first.",
     "input_schema": {"type": "object", "properties": {"service": {"type": "string"}, "system": SYS_ENUM, "near": {"type": "string"}}, "required": ["service"]}},
    {"name": "place_info", "description": "Details for a named station, city or outpost: what services it has, armistice, monitored, landing pad sizes, jurisdiction, faction.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "ship_info", "description": "A ship or vehicle's specs (maker, cargo SCU, crew, pad size, roles, dimensions, quantum fuel) plus where to buy it or rent it in game and the aUEC price.",
     "input_schema": {"type": "object", "properties": {"ship": {"type": "string"}}, "required": ["ship"]}},
    {"name": "item_where", "description": "Where to buy an item in game (ship weapons, shields, power plants, coolers, quantum drives, missiles, FPS weapons, armor, tools) and the price at each shop.",
     "input_schema": {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}},
    {"name": "refinery_yields", "description": "Refinery yield bonuses: the best refineries for a given ore, or each refinery's top bonuses if no commodity is given.",
     "input_schema": {"type": "object", "properties": {"commodity": {"type": "string"}, "system": SYS_ENUM}}},
]


def macro_tool(macros):
    if not macros:
        return None
    desc = "Run one of the pilot's saved macros (a sequence of keypresses). Only when they ask. Macros: " + "; ".join(
        f"{m['name']} ({', '.join(MAC_steps(m))})" for m in macros)
    return {"name": "run_macro", "description": desc,
            "input_schema": {"type": "object", "properties": {"name": {"type": "string", "enum": [m["name"] for m in macros]}},
                             "required": ["name"]}}


def MAC_steps(m):
    return [ACTION_INDEX[st["action"]]["label"] if st.get("action") in ACTION_INDEX else str(st.get("action")) for st in m.get("steps", [])]


CHATTER = re.compile(
    r"\b(double[- ]?check|(you('ll| should| may| might)? (want to )?|worth )verify(ing)?|verify (it|that|this|those|prices)|"
    r"(may|might|could) (have )?(change[ds]?|be different|vary)|subject to change|"
    r"as of (the )?(latest|current|recent|last)|(latest|current|recent|last) (patch|update)|"
    r"(from|on) (the )?(internet|web)|online sources?|web search|searched (online|the web)|search results?|"
    r"according to (uex|the (internet|web|wiki)|online|community|players|sources?)|community[- ](sourced|data|reported)|"
    r"player[- ]reported|\buex\b|hours old|i'?m an ai|as an ai|language model|my training|knowledge cutoff|"
    r"let me (check|look|search|find|pull)|one moment|hang on while|i'?ll (check|look it up|search))", re.I)


def drop_chatter(sentence):
    """Return the sentence, or "" if it's a disclaimer or meta remark that breaks character."""
    return "" if CHATTER.search(sentence or "") else sentence


class Sentences:
    END = re.compile(r"([.!?])([\"')\]]*)\s+")

    def __init__(self, emit):
        self.emit = emit
        self.buf = ""

    def feed(self, text):
        self.buf += text
        while True:
            m = self.END.search(self.buf)
            if not m:
                return
            chunk = self.buf[:m.end()].strip()
            self.buf = self.buf[m.end():]
            if chunk:
                self.emit(chunk)

    def flush(self):
        chunk = self.buf.strip()
        self.buf = ""
        if chunk:
            self.emit(chunk)


class _Conn:
    IDLE = 45

    def __init__(self):
        self.c = None
        self.host = None
        self.used = 0.0
        self.lock = threading.Lock()
        self.ctx = ssl.create_default_context()

    def reset(self):
        if self.c is not None:
            try:
                self.c.close()
            except Exception:
                pass
        self.c = None

    def get(self, fresh=False, host=API_HOST, port=443):
        if fresh or self.c is None or self.host != (host, port) or time.time() - self.used > self.IDLE:
            self.reset()
            self.c = http.client.HTTPSConnection(host, port, timeout=60, context=self.ctx)
            self.c.connect()
            self.host = (host, port)
        self.used = time.time()
        return self.c


class ApiError(RuntimeError):
    def __init__(self, text, status=0, raw_msg=""):
        super().__init__(text)
        self.status = status
        self.raw_msg = raw_msg


def _fail(status, raw, reason=""):
    try:
        msg = json.loads(raw.decode("utf-8")).get("error", {}).get("message", "")
    except Exception:
        msg = ""
    if status == 401:
        raise ApiError("Your API key wasn't accepted. Check it in Settings.", status, msg)
    if status == 403:
        raise ApiError(f"The API refused the request: {msg or 'permission denied'}", status, msg)
    if status == 429:
        raise ApiError("Hit the API rate limit. Give it a few seconds.", status, msg)
    if status in (500, 502, 503, 529):
        raise ApiError("The Claude API is overloaded right now. Try again in a moment.", status, msg)
    raise ApiError(f"API error {status}: {msg or reason}", status, msg)


class Brain:
    def __init__(self, app):
        self.app = app
        self.history = []
        self.lock = threading.Lock()
        self.busy = False
        self.last_usage = {}
        self.conn = _Conn()
        self.web_ok = True
        self.no_thinking = False

    def mode(self):
        m = self.app.settings.get("ai_mode") or "own_key"
        return m if m in dict(AI_MODES) else "own_key"

    def key(self):
        m = self.mode()
        if m == "own_key":
            return (self.app.settings.get("api_key") or "").strip()
        if m == "service" and VER.SERVICE_URL:
            return (self.app.settings.get("license_key") or "").strip()
        return ""

    def ready(self):
        return bool(self.key())

    def not_ready_reason(self):
        m = self.mode()
        if m == "off":
            return "The AI co-pilot is off. Instant commands still work. Turn it on in Settings."
        if m == "service":
            if not VER.SERVICE_URL:
                return "The Co-Pilot subscription isn't open yet. Use your own API key in Settings for now."
            return "Enter your Co-Pilot subscription key in Settings."
        return "No API key yet. Paste one in Settings."

    def _target(self):
        if self.mode() == "service":
            u = urllib.parse.urlsplit(VER.SERVICE_URL)
            path = (u.path or "").rstrip("/") + API_PATH
            return u.hostname, u.port or 443, path, {"authorization": f"Bearer {self.key()}", "x-copilot-version": VER.VERSION}
        return API_HOST, 443, API_PATH, {"x-api-key": self.key()}

    def warm(self):
        if not self.key() or not self.conn.lock.acquire(blocking=False):
            return
        try:
            if self.conn.c is None or time.time() - self.conn.used > _Conn.IDLE:
                host, port, _path, _h = self._target()
                self.conn.get(fresh=True, host=host, port=port)
        except Exception:
            self.conn.reset()
        finally:
            self.conn.lock.release()

    def _request(self, body, on_text=None):
        data = json.dumps(body).encode("utf-8")
        stream = bool(body.get("stream"))
        host, port, path, auth = self._target()
        headers = dict(auth, **{"anthropic-version": API_VERSION, "content-type": "application/json",
                                "user-agent": UA, "accept": "text/event-stream" if stream else "application/json"})
        service = self.mode() == "service"
        with self.conn.lock:
            resp = None
            for attempt in range(2):
                try:
                    c = self.conn.get(fresh=attempt > 0, host=host, port=port)
                    c.request("POST", path, body=data, headers=headers)
                    resp = c.getresponse()
                    break
                except (http.client.HTTPException, OSError) as ex:
                    self.conn.reset()
                    if attempt:
                        where = "the Co-Pilot service" if service else "the Claude API"
                        raise RuntimeError(f"Couldn't reach {where} ({type(ex).__name__}). Check your internet.")
            if resp.status != 200:
                raw = resp.read()
                if service and resp.status in (401, 402, 403):
                    try:
                        msg = json.loads(raw.decode("utf-8")).get("error", {}).get("message", "")
                    except Exception:
                        msg = ""
                    raise ApiError(msg or ("Your Co-Pilot subscription key isn't valid or has run out. Check Settings."
                                           if resp.status != 402 else "You've used this month's Co-Pilot allowance."), resp.status, msg)
                _fail(resp.status, raw, resp.reason)
            try:
                if not stream:
                    return json.loads(resp.read().decode("utf-8"))
                return self._parse_stream(resp, on_text)
            except RuntimeError:
                self.conn.reset()
                raise
            except Exception as ex:
                self.conn.reset()
                raise RuntimeError(f"The answer got cut off ({type(ex).__name__}). Try again.")

    def _parse_stream(self, resp, on_text):
        blocks = {}
        stop = None
        usage = {}
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except ValueError:
                continue
            t = d.get("type")
            if t == "content_block_start":
                cb = dict(d.get("content_block") or {})
                if cb.get("type") in ("tool_use", "server_tool_use"):
                    cb["_json"] = ""
                if cb.get("type") == "text":
                    cb["text"] = cb.get("text", "")
                    cb.pop("citations", None)
                    if cb["text"] and on_text:
                        on_text(cb["text"])
                blocks[d.get("index", len(blocks))] = cb
            elif t == "content_block_delta":
                b = blocks.get(d.get("index"))
                delta = d.get("delta") or {}
                if b is None:
                    continue
                if delta.get("type") == "text_delta":
                    b["text"] = b.get("text", "") + delta.get("text", "")
                    if on_text:
                        on_text(delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    b["thinking"] = b.get("thinking", "") + delta.get("thinking", "")
                elif delta.get("type") == "signature_delta":
                    b["signature"] = b.get("signature", "") + delta.get("signature", "")
                elif delta.get("type") == "input_json_delta":
                    b["_json"] = b.get("_json", "") + delta.get("partial_json", "")
            elif t == "content_block_stop":
                b = blocks.get(d.get("index"))
                if b is not None and "_json" in b:
                    raw = b.pop("_json", "")
                    try:
                        b["input"] = json.loads(raw) if raw.strip() else (b.get("input") or {})
                    except ValueError:
                        b["input"] = {}
            elif t == "message_start":
                usage.update((d.get("message") or {}).get("usage") or {})
            elif t == "message_delta":
                stop = (d.get("delta") or {}).get("stop_reason") or stop
                usage.update(d.get("usage") or {})
            elif t == "message_stop":
                break
            elif t == "error":
                err = d.get("error") or {}
                if err.get("type") == "overloaded_error":
                    raise RuntimeError("The Claude API is overloaded right now. Try again in a moment.")
                raise RuntimeError(f"API error: {err.get('message', 'unknown')}")
        try:
            resp.read()
        except Exception:
            self.conn.reset()
        content = []
        for i in sorted(blocks):
            b = blocks[i]
            typ = b.get("type")
            if typ == "text":
                if b.get("text", "").strip():
                    content.append({"type": "text", "text": b["text"]})
            elif typ == "tool_use":
                content.append({"type": "tool_use", "id": b.get("id"), "name": b.get("name"), "input": b.get("input") or {}})
            elif typ == "thinking":
                if b.get("signature"):
                    content.append({"type": "thinking", "thinking": b.get("thinking") or "", "signature": b["signature"]})
            elif typ == "redacted_thinking":
                if b.get("data"):
                    content.append({"type": "redacted_thinking", "data": b["data"]})
            elif typ:
                content.append({k: v for k, v in b.items() if not k.startswith("_")})
        return {"content": content, "stop_reason": stop, "usage": usage}

    def test(self):
        body = {"model": self.app.settings.get("model", MODELS[0][0]), "max_tokens": 20,
                "messages": [{"role": "user", "content": "Reply with exactly: Co-pilot online."}]}
        r = self._request(body)
        return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text").strip()

    def clear(self):
        with self.lock:
            self.history = []

    def ask(self, text, on_tool=None, on_sentence=None):
        if not self.key():
            raise RuntimeError(self.not_ready_reason())
        with self.lock:
            self.busy = True
            try:
                return self._ask(text, on_tool, on_sentence)
            finally:
                self.busy = False

    def _tools(self):
        tools = TOOLS + TRADE_TOOLS + INFO_TOOLS
        mt = macro_tool(self.app.settings.get("macros") or [])
        if mt:
            tools = tools + [mt]
        if self.web_ok and self.app.settings.get("web_lookups", True):
            tools = tools + [WEB_TOOL]
        return tools

    def _ask(self, text, on_tool, on_sentence):
        s = self.app.settings
        st = self.app.state
        notes = (s.get("pilot_notes") or "").strip()
        system = SYSTEM.format(name=s.get("assistant_name", "Co-Pilot"), handle=st.handle or "the pilot",
                               notes=f"\n\nWhat the pilot has told you about themselves: {notes}" if notes else "")
        style = LN.ai_style(s)
        if style:
            system += f"\n\nPersonality: {style} Stay accurate and keep answers short; the personality is only how you say things."
        now = datetime.now().strftime("%a %H:%M")
        with st.lock:
            snap = st.snapshot_text()
        msgs = [dict(m) for m in self.history[-12:]]
        msgs.append({"role": "user", "content": f"[Live status, {now} local]\n{snap}\n\n[Pilot says]\n{text}"})
        spoken = []

        def speak(sentence):
            keep = drop_chatter(sentence)
            if keep:
                spoken.append(keep)
                on_sentence(keep)
        sb = Sentences(speak) if on_sentence else None
        said = []
        for _ in range(7):
            body = {"model": s.get("model", MODELS[0][0]), "max_tokens": 320, "system": system, "tools": self._tools(),
                    "messages": msgs, "stream": True}
            if self.no_thinking:
                body["thinking"] = {"type": "disabled"}
            try:
                r = self._request(body, on_text=sb.feed if sb else None)
            except ApiError as ex:
                if ex.status == 400 and not self.no_thinking and "thinking" in (ex.raw_msg or "").lower():
                    self.no_thinking = True
                    for m in msgs:
                        if isinstance(m.get("content"), list):
                            m["content"] = [c for c in m["content"] if c.get("type") not in ("thinking", "redacted_thinking")]
                    continue
                if ex.status == 400 and self.web_ok and "web" in (ex.raw_msg or "").lower():
                    self.web_ok = False
                    self.app.note_system("Web lookups aren't enabled for this API key, so they're off for now. "
                                         "An org admin can turn on web search in the Claude Console.")
                    continue
                raise
            self.last_usage = r.get("usage", {})
            content = r.get("content", [])
            for b in content:
                if b.get("type") == "server_tool_use" and on_tool:
                    on_tool("web_search", b.get("input") or {})
            said += [b["text"].strip() for b in content if b.get("type") == "text" and b["text"].strip()]
            uses = [b for b in content if b.get("type") == "tool_use"]
            if r.get("stop_reason") == "pause_turn":
                msgs.append({"role": "assistant", "content": content})
                continue
            if r.get("stop_reason") == "tool_use" and uses:
                if sb:
                    sb.flush()
                msgs.append({"role": "assistant", "content": content})
                results = []
                for u in uses:
                    if on_tool:
                        on_tool(u.get("name"), u.get("input") or {})
                    try:
                        out = self.run_tool(u.get("name"), u.get("input") or {})
                    except Exception as ex:
                        out = f"Tool error: {ex}"
                    results.append({"type": "tool_result", "tool_use_id": u.get("id"), "content": str(out)[:8000]})
                msgs.append({"role": "user", "content": results})
                continue
            break
        if sb:
            sb.flush()
        if on_sentence:
            if not spoken and said:
                first = re.split(r"(?<=[.!?])\s+", " ".join(said).strip())[0]
                spoken.append(first)
                on_sentence(first)
            final = " ".join(spoken)
        else:
            parts = [p for p in re.split(r"(?<=[.!?])\s+", " ".join(said)) if p.strip()]
            final = " ".join(p for p in parts if drop_chatter(p)) or " ".join(parts[:1])
        if not final:
            final = "Sorry, I lost the thread there. Say that again?"
            if on_sentence:
                on_sentence(final)
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": final})
        self.history = self.history[-16:]
        return final

    def run_tool(self, name, inp):
        st = self.app.state
        now = time.time()
        if name == "get_contracts":
            with st.lock:
                def c_out(c):
                    return {"name": c["name"], "status": c["status"],
                            "accepted": hm(c["accepted"]) if c["accepted"] else "before this session",
                            "ended": hm(c["ended"]) if c.get("ended") else "", "current_objective": c.get("current", ""),
                            "objectives": [{"text": o["text"], "done": o["done"]} for o in c["objectives"].values()]}
                return json.dumps({"active": [c_out(c) for c in st.active_contracts()],
                                   "ended": [c_out(c) for c in st.ended_contracts()[:12]],
                                   "note": "Only contracts accepted or finished while this session's log was running show up. Rewards aren't in the log."})
        if name == "get_session_details":
            with st.lock:
                ships = [x for _, x in st.events if x.startswith("Boarded ")]
                return json.dumps({
                    "pilot": st.handle, "game_version": st.game_version, "session_started": hm(st.session_start),
                    "game_running": st.running, "current_ship": st.ship_text(), "ships_boarded": ships[-10:],
                    "zone_now": st.zone_text(), "last_place": clean_place(st.location),
                    "quantum_log": [{"time": hm(q["ts"]), "to": q["to"], "result": q["result"]} for q in st.qt_log[-15:]],
                    "places_and_zones": [f"{hm(t)} {x}" for t, x in st.events if x.startswith(("At ", "Entered ", "Left the"))][-20:],
                    "purchases": [{"time": hm(p["ts"]), "item": clean_item(p["item"]), "qty": p["qty"], "price": round(p["price"]),
                                   "shop": clean_item(p["shop"])} for p in st.purchases[-20:]],
                    "spent_total": round(st.spent()), "received": [{"time": hm(m["ts"]), "from": m["from"], "amount": m["amount"]} for m in st.money_in],
                    "party": st.party, "disconnects": [{"time": hm(d["ts"]), "reason": d["reason"]} for d in st.disconnects],
                    "crashes": [{"time": hm(c["ts"]), "detail": c["text"]} for c in st.crashes],
                    "hangar_ready": ago(st.hangar_ts, now) if st.hangar_ts else "not this session"})
        if name == "get_combat_log":
            with st.lock:
                return json.dumps({
                    "kills": [{"time": hm(k["ts"]), "victim": k["victim"], "ai": k["ai"], "player_owned": k["player_owned"]} for k in st.kills],
                    "ships_lost": [{"time": hm(k["ts"]), "ship": k["victim"], "reason": k["reason"], "killer": k["killer"]} for k in st.losses],
                    "deaths": [{"time": hm(d["ts"]), "detail": d["detail"]} for d in st.deaths],
                    "times_downed": [hm(t) for t in st.downed],
                    "crimestat": [{"time": hm(c["ts"]), "change": c["change"]} for c in st.crimes],
                    "destroyed_nearby": [{"time": hm(k["ts"]), "victim": k["victim"], "killer": k["killer"], "reason": k["reason"],
                                          "ai": k["ai"]} for k in st.destroyed if k not in st.kills and k not in st.losses][-15:],
                    "note": "The log only reports ship destructions the game shares with this client, so on-foot (FPS) kills aren't counted."})
        if name == "get_history":
            days = int(inp.get("days") or 30)
            with st.lock:
                hist = [h for h in st.history if h["start"] and now - h["start"] < days * 86400]
            tot = {"sessions": len(hist), "hours": round(sum(max(0, h["end"] - h["start"]) for h in hist) / 3600, 1),
                   "kills": sum(len(h["kills"]) for h in hist), "ships_lost": sum(len(h["losses"]) for h in hist),
                   "deaths": sum(h["deaths"] for h in hist), "contracts_done": sum(len(h["contracts_done"]) for h in hist),
                   "contracts_failed": sum(len(h["contracts_failed"]) for h in hist), "spent": round(sum(h["spent"] for h in hist)),
                   "received": sum(h["received"] for h in hist), "crashes": sum(1 for h in hist if h["crashed"])}
            rows = [{"date": datetime.fromtimestamp(h["start"]).strftime("%b %d %H:%M"),
                     "hours": round(max(0, h["end"] - h["start"]) / 3600, 1), "version": h["version"],
                     "kills": len(h["kills"]), "lost": [l["ship"] for l in h["losses"]], "deaths": h["deaths"],
                     "contracts_done": h["contracts_done"][:6], "contracts_failed": h["contracts_failed"][:6],
                     "qt_jumps": h["qt"], "spent": round(h["spent"]), "received": h["received"], "ships": h["ships"][:5],
                     "crashed": h["crashed"]} for h in hist[-20:]]
            return json.dumps({"totals": tot, "sessions": rows, "note": "Doesn't include the current session."})
        if name == "get_recent_events":
            n = int(inp.get("count") or 15)
            with st.lock:
                ev = list(st.events)[-n:]
            return "\n".join(f"{hm(t)} {x}" for t, x in ev) or "Nothing logged yet."
        if name == "find_keybind":
            rows = self.app.binds.search(inp.get("query", ""))
            return json.dumps({"results": rows, "keys_from": self.app.binds.source}) if rows else "No action matched. Try another word."
        if name == "press_controls":
            done = []
            for item in (inp.get("actions") or [])[:8]:
                a = ACTION_INDEX.get(item.get("action"))
                if not a:
                    done.append(f"{item.get('action')}: unknown action")
                    continue
                times = max(1, min(int(item.get("times") or 1), 6))
                ok, msg = self.app.binds.press(a["sc"], times)
                done.append(f"{a['label']}: {'pressed ' + msg + (f' x{times}' if times > 1 else '') if ok else 'NOT pressed, ' + msg}")
                time.sleep(0.12)
            self.app.note_action("; ".join(done))
            return "\n".join(done)
        if name in ("commodity_prices", "trade_route"):
            sysname = inp.get("system")
            sysname = None if not sysname or sysname == "all" else sysname
            try:
                if name == "commodity_prices":
                    out = self.app.uex.best(inp.get("commodity", ""), inp.get("side") or "sell", sysname, limit=6)
                    for r in out.get("results", []):
                        r.pop("updated_ts", None)
                else:
                    out = self.app.uex.route(inp.get("commodity", ""), sysname, inp.get("scu"))
                    for k in ("buy_at", "sell_at"):
                        if isinstance(out.get(k), dict):
                            out[k].pop("updated_ts", None)
            except Exception as ex:
                return f"Couldn't get prices: {ex}"
            self.app.note_trade(out)
            return json.dumps(out)
        if name == "get_target_status":
            r = self.app.hud.read()
            return json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
        if name in ("find_services", "place_info", "ship_info", "item_where", "refinery_yields"):
            x = self.app.uex_extra
            sysname = inp.get("system")
            sysname = None if not sysname or sysname == "all" else sysname
            try:
                if name == "find_services":
                    out = x.find_services(inp.get("service", ""), sysname, inp.get("near") or "")
                elif name == "place_info":
                    out = x.place_info(inp.get("name", ""))
                elif name == "ship_info":
                    out = x.ship(inp.get("ship", ""))
                elif name == "item_where":
                    out = x.item(inp.get("item", ""))
                else:
                    out = x.yields(inp.get("commodity") or None, sysname)
            except Exception as ex:
                return f"Couldn't look that up: {ex}"
            return json.dumps(out)
        if name == "run_macro":
            m = MAC.find(self.app.settings.get("macros") or [], inp.get("name", ""))
            if not m:
                return "No macro by that name."
            done, skipped = MAC.run(m, self.app.binds, ACTION_INDEX)
            msg = f"Ran {m['name']}: pressed {', '.join(done) or 'nothing'}" + (f"; skipped {', '.join(skipped)}" if skipped else "")
            self.app.note_action(msg)
            return msg
        return f"Unknown tool {name}"
