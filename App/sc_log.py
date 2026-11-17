import calendar
import json
import os
import re
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

import sc_paths as P

APP_DIR = P.APP_DIR
HISTORY_CACHE = P.cache("sc_history_cache.json")
HISTORY_DAYS = 30

TS = re.compile(r"^<(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?Z> ?")
NOTE_END = re.compile(r'"\s*\[\d+\] to queue\.')
MISSION_ID = re.compile(r"MissionId: \[([0-9a-fA-F-]+)\]")
OBJECTIVE_ID = re.compile(r"ObjectiveId: \[([^\]]*)\]")
VEH_DESTROYED = re.compile(r"Vehicle '(?P<veh>[^']+)' \[(?P<vid>\d+)\] class '(?P<cls>[^']+)' \(owner player \[(?P<owner>\d+)\], "
                           r"driver \[(?P<driver>\d+)\]\) destroyed: reason \[(?P<reason>[^\]]*)\] level \[(?P<l0>\d+)\] -> "
                           r"\[(?P<l1>\d+)\].*?killer '(?P<killer>[^']*)' \[(?P<kid>\d+)\]")
ACTOR_DEAD = re.compile(r"Actor '(?P<who>[^']+)' \[(?P<id>\d+)\](?: ejected from zone '(?P<zone>[^']+)')?(?:.*?due to (?P<why>[^\[]+))?")
END_MISSION = re.compile(r"MissionId\[(?P<mid>[^\]]*)\] Player\[(?P<player>[^\]]*)\].*?CompletionType\[(?P<type>[^\]]*)\] Reason\[(?P<reason>[^\]]*)\]")
MISSION_ENDED = re.compile(r"mission_id (?P<mid>[0-9a-fA-F-]+) - mission_state MISSION_STATE_(?P<state>\w+)")
OBJ_UPSERT = re.compile(r"mission_id (?P<mid>[0-9a-fA-F-]+) - objective_id (?P<oid>[0-9a-fA-F-]+) - state MISSION_OBJECTIVE_STATE_(?P<state>\w+)")
OBJ_UPDATE = re.compile(r"Objective updated id=(?P<oid>[^,]+),.*?hidden=(?P<hidden>\d), hiddenInUI=(?P<hui>\d).*?\[Text=(?P<text>[^\]]*)\]")
QT_TARGET = re.compile(r"\| (?P<ent>[^|\[\s]+)\[\d+\]\|.*?selected point (?P<target>\S+) as their destination")
QT_ARRIVED = re.compile(r"\| (?P<ent>[^|\[\s]+)\[\d+\]\|")
LOC_INV = re.compile(r"Player\[(?P<player>[^\]]+)\] requested inventory for Location\[(?P<loc>[^\]]+)\]")
SHOP_BUY = re.compile(r"shopName\[(?P<shop>[^\]]*)\].*?client_price\[(?P<price>[\d.]+)\].*?itemName\[(?P<item>[^\]]*)\] quantity\[(?P<qty>\d+)\]")
SHOP_RESP = re.compile(r"result\[(?P<result>\w+)\](?: type\[(?P<type>\w+)\])?")
CHAN_DISC = re.compile(r'cause=(?P<cause>\d+) reason="(?P<reason>[^"]*)"')
NICK = re.compile(r'nickname="(?P<nick>[^"]+)" playerGEID=(?P<geid>\d+)')
CLIENT_NODE = re.compile(r"Local client node \[(\d+)\]")
CONTROL_TOKEN = re.compile(r"control token for '(?P<ent>[^']+)'")
ENTITY_ID = re.compile(r"^(?P<cls>.+?)_(?P<id>\d{6,})$")
MONEY_IN = re.compile(r"^(?P<who>.+?) has sent you:\s*(?P<amt>[\d,]+)\s*aUEC", re.S)
JOIN_CHAN = re.compile(r"^You have joined channel '(?P<ship>.+?) : (?P<owner>[^']+)'")
LEFT_CHAN = re.compile(r"^You have left the channel '(?P<ship>.+?) : (?P<owner>[^']+)'")
JURIS = re.compile(r"^Entered (?P<j>.+?) Jurisdiction")
PLACEHOLDER = re.compile(r"~\w+\(([^)]*)\)")

MAKERS = {"AEGS": "Aegis", "ANVL": "Anvil", "ARGO": "Argo", "BANU": "Banu", "CNOU": "C.O.", "CRUS": "Crusader", "DRAK": "Drake",
          "ESPR": "Esperia", "GAMA": "Gatac", "GRIN": "Greycat", "KRIG": "Kruger", "MISC": "MISC", "MRAI": "Mirai",
          "ORIG": "Origin", "RSI": "RSI", "TMBL": "Tumbril", "VNCL": "Vanduul", "XIAN": "Aopoa", "XNAA": "Aopoa",
          "AOPOA": "Aopoa", "GLSN": "Gallenson", "BEHR": "Behring"}
PLACES = {"Stanton1": "Hurston", "Stanton2": "Crusader", "Stanton3": "ArcCorp", "Stanton4": "microTech",
          "Pyro1": "Pyro I", "Pyro2": "Pyro II", "Pyro3": "Pyro III", "Pyro4": "Pyro IV", "Pyro5": "Pyro V", "Pyro6": "Pyro VI"}


SYSTEM_JURIS = {"Rough & Ready": "Pyro", "Citizens for Prosperity": "Pyro", "Headhunters": "Pyro", "XenoThreat": "Pyro",
                "People's Alliance": "Nyx", "Hurston Dynamics": "Stanton", "Crusader Industries": "Stanton", "ArcCorp": "Stanton",
                "microTech": "Stanton"}
STANTON_WORDS = ("stanton", "hurston", "crusader", "arccorp", "microtech", "lorville", "area18", "area 18", "orison", "babbage",
                 "grimhex", "grim hex", "everus", "baijini", "seraphim", "tressler", "olisar", "rr_hur", "rr_cru", "rr_arc",
                 "rr_mic", "hur-l", "cru-l", "arc-l", "mic-l", "stan-", "yela", "daymar", "cellin", "aberdeen", "arial", "ita ",
                 "magda", "wala", "lyria", "calliope", "clio", "euterpe")


def guess_system(text):
    t = (text or "").lower()
    hits = set()
    if "pyro" in t:
        hits.add("Pyro")
    if any(w in t for w in ("nyx", "levski", "keeger", "delamar")):
        hits.add("Nyx")
    if any(w in t for w in STANTON_WORDS):
        hits.add("Stanton")
    return hits.pop() if len(hits) == 1 else None


def ts_of(m):
    y, mo, d, h, mi, s, frac = m.groups()
    t = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s)))
    return t + (float("0." + frac) if frac else 0.0)


def strip_id(name):
    m = ENTITY_ID.match(name or "")
    return m.group("cls") if m else (name or "")


def is_ai(cls):
    return "_AI_" in cls or cls.endswith("_AI") or "PU_AI" in cls


def pretty_vehicle(cls):
    cls = strip_id(cls)
    cut = re.split(r"_PU_|_AI_|_PU$", cls)[0]
    parts = [p for p in cut.split("_") if p]
    if not parts:
        return cls or "unknown ship"
    maker = MAKERS.get(parts[0].upper())
    rest = " ".join(parts[1:] if maker else parts)
    return f"{maker} {rest}".strip() if maker else rest


def clean_place(name):
    if not name:
        return ""
    n = strip_id(name)
    low = n.lower()
    if low.startswith("navpoint_dynamic"):
        return "a custom nav marker"
    if low.startswith("mission_qt_"):
        return "mission marker (" + n[11:].replace("_", " ").replace("Beacon", "beacon").strip() + ")"
    for k, v in PLACES.items():
        if n.startswith(k):
            n = v + n[len(k):]
            break
    n = re.sub(r"(^|_)jp(\d*)$", r" jump point", n, flags=re.I)
    n = re.sub(r"^RR_", "Rest stop ", n)
    n = re.sub(r"^rs_(ext|entry)_", "Rest stop ", n, flags=re.I)
    return re.sub(r"\s+", " ", n.replace("_", " ")).strip()


def clean_item(name):
    return re.sub(r"\s+", " ", (name or "").replace("_", " ")).strip()


def short_money(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0"
    a = abs(n)
    if a >= 1e9:
        return f"{n / 1e9:.2f}B"
    if a >= 1e6:
        return f"{n / 1e6:.1f}M"
    if a >= 1e4:
        return f"{n / 1e3:.0f}k"
    if a >= 1e3:
        return f"{n / 1e3:.1f}k"
    return f"{n:.0f}"


def spoken_money(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "nothing"
    a = abs(n)
    trim = lambda x: f"{x:.1f}".rstrip("0").rstrip(".")
    if a >= 1e9:
        return f"{trim(n / 1e9)} billion"
    if a >= 1e6:
        return f"{trim(n / 1e6)} million"
    if a >= 1e3:
        return f"{n / 1e3:.0f} thousand"
    return f"{n:.0f}"


def ago(t, now=None):
    if not t:
        return "never"
    s = int((now or time.time()) - t)
    if s < 60:
        return f"{max(s, 0)}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60}m ago"
    return f"{s // 86400}d ago"


def hm(t):
    return datetime.fromtimestamp(t).strftime("%H:%M") if t else "—"


def a_an(word):
    return "an" if (word or "x")[0].lower() in "aeiou" else "a"


class GameState:
    def __init__(self):
        self.lock = threading.RLock()
        self.listeners = []
        self.history = []
        self.install = None
        self.log_path = None
        self.loaded = False
        self.live = False
        self.running = False
        self.error = ""
        self.version = 0
        self.handle = ""
        self.geid = ""
        self.reset()

    def reset(self):
        self.game_version = ""
        self.session_start = 0.0
        self.last_ts = 0.0
        self.ship = None
        self.ship_entity = ""
        self.jurisdiction = ""
        self.jurisdiction_ts = 0.0
        self.armistice = None
        self.monitored = None
        self.comms_down = False
        self.private_property = False
        self.location = ""
        self.location_ts = 0.0
        self.star_system = ""
        self.qt_target = ""
        self.qt_target_ts = 0.0
        self.qt_arrived_ts = 0.0
        self.qt_obstructed_ts = 0.0
        self.qt_log = []
        self.contracts = {}
        self.obj_mission = {}
        self.kills = []
        self.losses = []
        self.deaths = []
        self.downed = []
        self.destroyed = []
        self.crimes = []
        self.purchases = []
        self.pending_buy = None
        self.money_in = []
        self.party = []
        self.party_events = []
        self.disconnects = []
        self.crashes = []
        self.hangar_ts = 0.0
        self.low_fuel_ts = 0.0
        self.events = deque(maxlen=400)
        self.note = None
        self.seen_vehicles = {}
        self.bump()

    def bump(self):
        self.version += 1

    def log(self, ts, text):
        self.events.append((ts, text))

    def me(self, name):
        return bool(name) and bool(self.handle) and name.lower() == self.handle.lower()

    # ------------------------------------------------------------ parsing
    def feed_line(self, line):
        """Feed one raw log line. Returns a list of (event, info) for callouts."""
        line = line.rstrip("\r\n")
        if not line:
            return []
        m = TS.match(line)
        if m:
            ts = ts_of(m)
            rest = line[m.end():]
            self.last_ts = ts
        else:
            ts = self.last_ts
            rest = line
        out = []
        if self.note is not None:
            if rest.startswith("[Notice]") or rest.startswith("[Error]") or rest.startswith("[Warning]") or len(self.note["parts"]) > 12:
                n, self.note = self.note, None
                out += self.notification(n["ts"], "\n".join(n["parts"]), "", "")
            else:
                self.note["parts"].append(rest)
                out += self._try_finish_note()
                return out
        try:
            out += self.dispatch(ts, rest)
        except Exception:
            traceback.print_exc()
        if out:
            self.bump()
        return out

    def _try_finish_note(self):
        n = self.note
        joined = "\n".join(n["parts"])
        mm = NOTE_END.search(joined)
        if not mm:
            return []
        self.note = None
        tail = joined[mm.end():]
        mid = MISSION_ID.search(tail)
        oid = OBJECTIVE_ID.search(tail)
        return self.notification(n["ts"], joined[:mm.start()], mid.group(1) if mid else "", oid.group(1) if oid else "")

    def dispatch(self, ts, rest):
        if 'Added notification "' in rest:
            if "<SHUDEvent_OnNotification>" not in rest:
                return []
            self.note = {"ts": ts, "parts": [rest.split('Added notification "', 1)[1]]}
            return self._try_finish_note()
        if "<Vehicle Destroyed>" in rest:
            return self.vehicle_destroyed(ts, rest)
        if "<[ActorState] Dead>" in rest:
            return self.actor_dead(ts, rest)
        if "<EndMission>" in rest:
            return self.end_mission(ts, rest)
        if "<MissionEnded>" in rest:
            m = MISSION_ENDED.search(rest)
            if m:
                return self.contract_end(ts, m.group("mid"), m.group("state").lower(), None)
            return []
        if "<ObjectiveUpserted>" in rest:
            m = OBJ_UPSERT.search(rest)
            if m:
                self.obj_mission[m.group("oid")] = m.group("mid")
            return []
        if "<CMissionLogEntry::UpdateActiveObjective>" in rest:
            m = OBJ_UPDATE.search(rest)
            if m and m.group("hidden") == "0" and m.group("hui") == "0" and m.group("text").strip():
                c = self.contracts.get(self.obj_mission.get(m.group("oid").strip(), ""))
                if c and c["status"] == "active":
                    c["current"] = m.group("text").strip()
                    self.bump()
            return []
        if "Player Selected Quantum Target" in rest:
            m = QT_TARGET.search(rest)
            if m:
                self.ship_entity = m.group("ent")
                tgt = m.group("target")
                if tgt != self.qt_target or ts - self.qt_target_ts > 30:
                    self.log(ts, f"Quantum target set: {clean_place(tgt)}")
                self.qt_target, self.qt_target_ts = tgt, ts
                return [("qt_target", {"target": clean_place(tgt)})]
            return []
        if "Quantum Drive Arrived - Arrived at Final Destination" in rest:
            m = QT_ARRIVED.search(rest)
            if m:
                self.ship_entity = m.group("ent")
            if ts - self.qt_arrived_ts < 5:
                return []
            self.qt_arrived_ts = ts
            dest = clean_place(self.qt_target) if self.qt_target and ts - self.qt_target_ts < 3600 else ""
            self.qt_log.append({"ts": ts, "to": dest, "result": "arrived"})
            self.log(ts, "Quantum travel complete" + (f": {dest}" if dest else ""))
            return [("qt_arrived", {"to": dest})]
        if "<RequestLocationInventory>" in rest:
            m = LOC_INV.search(rest)
            if m:
                self._who(m.group("player"))
                if m.group("loc") != self.location:
                    self.log(ts, f"At {clean_place(m.group('loc'))}")
                self.location, self.location_ts = m.group("loc"), ts
                self.star_system = guess_system(m.group("loc")) or self.star_system
                self.bump()
            return []
        if "SendShopBuyRequest" in rest:
            m = SHOP_BUY.search(rest)
            if m:
                self._commit_buy()
                self.pending_buy = {"ts": ts, "shop": m.group("shop"), "item": m.group("item"), "qty": int(m.group("qty")),
                                    "price": float(m.group("price"))}
            return []
        if "RmShopFlowResponse" in rest:
            m = SHOP_RESP.search(rest)
            if m and self.pending_buy:
                if m.group("result") == "Success":
                    return self._commit_buy()
                p, self.pending_buy = self.pending_buy, None
                self.log(ts, f"Purchase failed: {clean_item(p['item'])}")
            return []
        if "<Channel Disconnected>" in rest:
            m = CHAN_DISC.search(rest)
            n = NICK.search(rest)
            if n:
                self._who(n.group("nick"), n.group("geid"))
            if m and m.group("cause") not in ("30010", "30016"):
                if self.disconnects and ts - self.disconnects[-1]["ts"] < 10:
                    return []
                d = {"ts": ts, "cause": m.group("cause"), "reason": m.group("reason")}
                self.disconnects.append(d)
                self.log(ts, f"Disconnected ({m.group('cause')}): {m.group('reason')}")
                return [("disconnect", d)]
            return []
        if "<Vehicle Control Flow>" in rest:
            m = CONTROL_TOKEN.search(rest)
            if m:
                self.ship_entity = m.group("ent")
            return []
        if "Saved dump file to" in rest or rest.startswith("GPU crash message") or "- GPU crash message" in rest:
            if not self.crashes or (ts and ts - self.crashes[-1]["ts"] > 30):
                c = {"ts": ts, "text": rest.split(":", 1)[-1].strip()[:200]}
                self.crashes.append(c)
                self.log(ts, "Game crashed" + (" (GPU / Vulkan device lost)" if "GPU" in rest else ""))
                return [("crash", c)]
            return []
        if not self.handle and 'nickname="' in rest:
            n = NICK.search(rest)
            if n:
                self._who(n.group("nick"), n.group("geid"))
            return []
        if not self.geid and "Local client node [" in rest:
            n = CLIENT_NODE.search(rest)
            if n and n.group(1) != "0":
                self.geid = n.group(1)
            return []
        if rest.startswith("Log started on"):
            self.session_start = ts
            return []
        if rest.startswith("FileVersion:"):
            self.game_version = rest.split(":", 1)[1].strip()
            return []
        return []

    def _who(self, nick, geid=None):
        if nick and not self.handle:
            self.handle = nick
        if geid and nick and self.me(nick) and geid != self.geid:
            self.geid = geid

    def _commit_buy(self):
        p, self.pending_buy = self.pending_buy, None
        if not p:
            return []
        self.purchases.append(p)
        self.log(p["ts"], f"Bought {p['qty']}x {clean_item(p['item'])} for {p['price']:,.0f} aUEC")
        return [("purchase", p)]

    # ------------------------------------------------------------ events
    def vehicle_destroyed(self, ts, rest):
        m = VEH_DESTROYED.search(rest)
        if not m:
            return []
        d = m.groupdict()
        vid, l1 = d["vid"], int(d["l1"])
        prev = self.seen_vehicles.get(vid, 0)
        self.seen_vehicles[vid] = max(prev, l1)
        if prev >= 1 or l1 < 1:
            return []
        cls = d["cls"]
        victim = pretty_vehicle(cls)
        ai = is_ai(cls)
        killer = d["killer"]
        km = ENTITY_ID.match(killer)
        killer_txt = "unknown" if killer in ("", "none", "unknown") else (pretty_vehicle(killer) + " (AI)" if km and is_ai(killer)
                                                                          else pretty_vehicle(killer) if km else killer)
        reason = d["reason"]
        mine = (self.geid and d["owner"] == self.geid) or (self.geid and d["driver"] == self.geid)
        by_me = self.me(killer) or (self.geid and d["kid"] == self.geid)
        rec = {"ts": ts, "victim": victim, "cls": strip_id(cls), "ai": ai, "player_owned": d["owner"] != "0",
               "killer": killer_txt, "killer_is_player": not km and killer not in ("", "none", "unknown"),
               "reason": reason, "level": l1}
        self.destroyed.append(rec)
        events = []
        if mine and not by_me:
            self.losses.append(rec)
            why = {"SelfDestruct": "self-destruct", "Combat": f"killed by {killer_txt}", "Collision": "collision",
                   "BoundaryViolation": "boundary violation"}.get(reason, reason)
            self.log(ts, f"Your {victim} was destroyed ({why})")
            events.append(("ship_lost", rec))
        elif mine and by_me:
            self.losses.append(rec)
            self.log(ts, f"Your {victim} was destroyed ({'self-destruct' if reason == 'SelfDestruct' else reason})")
            events.append(("ship_lost", rec))
        elif by_me and reason != "SelfDestruct":
            self.kills.append(rec)
            tag = " (AI)" if ai else " (player ship)" if rec["player_owned"] else ""
            self.log(ts, f"You destroyed {a_an(victim)} {victim}{tag}")
            events.append(("kill", rec))
        else:
            tag = " (AI)" if ai else ""
            if reason == "SelfDestruct":
                self.log(ts, f"{a_an(victim).capitalize()} {victim}{tag} self-destructed nearby")
            else:
                self.log(ts, f"{killer_txt} destroyed {a_an(victim)} {victim}{tag}")
            events.append(("destroyed_nearby", rec))
        return events

    def actor_dead(self, ts, rest):
        m = ACTOR_DEAD.search(rest)
        if not m or not self.me(m.group("who")):
            return []
        if self.deaths and ts - self.deaths[-1]["ts"] < 20:
            return []
        zone = m.group("zone") or ""
        why = (m.group("why") or "").strip()
        detail = ""
        if zone and "destroyed vehicle" in why:
            detail = f"went down with the {pretty_vehicle(zone)}"
        rec = {"ts": ts, "detail": detail}
        self.deaths.append(rec)
        self.log(ts, "You died" + (f" ({detail})" if detail else ""))
        return [("death", rec)]

    def end_mission(self, ts, rest):
        m = END_MISSION.search(rest)
        if not m:
            return []
        self._who(m.group("player"))
        t = m.group("type").lower()
        status = {"complete": "complete", "abandon": "abandoned", "fail": "failed", "failed": "failed"}.get(t, t)
        return self.contract_end(ts, m.group("mid"), status, m.group("reason"))

    def contract_end(self, ts, mid, status, reason):
        status = {"completed": "complete", "failed": "failed", "abandoned": "abandoned", "withdrawn": "abandoned"}.get(status, status)
        c = self.contracts.get(mid)
        if not c or c["status"] != "active":
            return []
        c["status"], c["ended"] = status, ts
        if reason:
            c["reason"] = reason
        self.log(ts, f"Contract {status}: {c['name']}")
        return [("contract_end", dict(c))]

    def notification(self, ts, text, mid, oid):
        text = text.strip()
        if not text:
            return []
        m = MONEY_IN.match(text)
        if m:
            amt = int(m.group("amt").replace(",", ""))
            rec = {"ts": ts, "from": m.group("who").strip(), "amount": amt}
            self.money_in.append(rec)
            self.log(ts, f"{rec['from']} sent you {amt:,} aUEC")
            return [("money_in", rec)]
        if "\n" in text:
            title, body = text.split("\n", 1)
        else:
            title, _, body = text.partition(":")
        title, body = title.strip().rstrip(":"), body.strip().rstrip(":").strip()
        body = PLACEHOLDER.sub(lambda m: re.sub(r"(?<!^)(?=[A-Z])", " ", m.group(1)).lower(), body)
        if title.startswith("Contract Accepted"):
            if not mid or set(mid) <= {"0", "-"}:
                return []
            c = self.contracts.get(mid)
            if c and c["status"] == "active":
                return []
            self.contracts[mid] = {"id": mid, "name": body, "accepted": ts, "status": "active", "ended": 0.0,
                                   "objectives": {}, "current": ""}
            self.log(ts, f"Contract accepted: {body}")
            return [("contract_accepted", {"name": body})]
        if title.startswith("Contract Complete") or title.startswith("Contract Failed"):
            status = "complete" if "Complete" in title else "failed"
            c = self.contracts.get(mid)
            if c and c["status"] == "active":
                return self.contract_end(ts, mid, status, None)
            if c:
                return []
            self.contracts[mid or f"x{ts}"] = {"id": mid, "name": body, "accepted": 0.0, "status": status, "ended": ts,
                                               "objectives": {}, "current": ""}
            self.log(ts, f"Contract {status}: {body}")
            return [("contract_end", {"name": body, "status": status})]
        if title.startswith("Contract Shared"):
            self.log(ts, f"Contract shared with party: {body}")
            return []
        if title.startswith("New Objective"):
            c = self.contracts.get(mid)
            if c:
                c["objectives"][oid or body] = {"text": body, "done": False}
                c["current"] = body
                if oid:
                    self.obj_mission[oid] = mid
            return [("objective", {"text": body, "contract": c["name"] if c else ""})]
        if title.startswith("Objective Complete"):
            c = self.contracts.get(mid)
            if c:
                o = c["objectives"].get(oid) or next((x for x in c["objectives"].values() if x["text"] == body), None)
                if o:
                    o["done"] = True
                if c.get("current") == body:
                    c["current"] = ""
            return [("objective_done", {"text": body})]
        jm = JURIS.match(title)
        if jm:
            j = jm.group("j").strip()
            if j == self.jurisdiction:
                return []
            prev, self.jurisdiction, self.jurisdiction_ts = self.jurisdiction, j, ts
            self.star_system = SYSTEM_JURIS.get(j, self.star_system)
            self.log(ts, f"Entered {j} jurisdiction")
            return [("jurisdiction", {"name": j, "prev": prev})]
        if title.startswith("Entering Armistice Zone"):
            was, self.armistice = self.armistice, True
            if was is not True:
                self.log(ts, "Entered an armistice zone")
                return [("armistice", {"on": True})]
            return []
        if title.startswith("Leaving Armistice Zone"):
            was, self.armistice = self.armistice, False
            if was is not False:
                self.log(ts, "Left the armistice zone")
                return [("armistice", {"on": False})]
            return []
        if title.startswith("Entered Monitored Space"):
            was, self.monitored = self.monitored, True
            self.comms_down = False
            return [("monitored", {"on": True})] if was is False else []
        if title.startswith("Exited Monitored Space"):
            was, self.monitored = self.monitored, False
            if was is not False:
                self.log(ts, "Left monitored space")
                return [("monitored", {"on": False})]
            return []
        if title.startswith("Monitored Space Down"):
            self.comms_down = True
            self.log(ts, "Comm array down: no monitoring here")
            return [("comms_down", {})]
        if title.startswith("Monitored Space Restored") or title.startswith("Monitored Space Up"):
            self.comms_down = False
            return []
        if title.startswith("Entering Private Property"):
            self.private_property = True
            self.log(ts, "Entered private property")
            return [("private", {"on": True})]
        if title.startswith("Leaving Private Property"):
            self.private_property = False
            return [("private", {"on": False})]
        if title.startswith("Quantum Travel") and "obstructed" in text.lower():
            if ts - self.qt_obstructed_ts < 5:
                return []
            self.qt_obstructed_ts = ts
            dest = clean_place(self.qt_target) if self.qt_target and ts - self.qt_target_ts < 600 else ""
            self.qt_log.append({"ts": ts, "to": dest, "result": "obstructed"})
            self.log(ts, "Quantum path obstructed" + (f" ({dest})" if dest else ""))
            return [("qt_obstructed", {"to": dest})]
        if title.startswith("Quantum Travel Calibration"):
            who = title.split(" By ", 1)[1].strip() if " By " in title else ""
            if "Complete" in title and who:
                return [("party_qt", {"who": who})]
            return []
        if title.startswith("Hangar Request Completed"):
            self.hangar_ts = ts
            self.log(ts, "Hangar ready")
            return [("hangar", {})]
        if title.startswith("Incapacitated"):
            if self.downed and ts - self.downed[-1] < 60:
                return []
            self.downed.append(ts)
            self.log(ts, "You were incapacitated")
            return [("downed", {})]
        if title.startswith("Medical Bed") and "restored" in body:
            self.log(ts, "Healed at a medical bed")
            return []
        if title.startswith("CrimeStat Rating"):
            change = title.replace("CrimeStat Rating", "").strip().lower() or "changed"
            self.crimes.append({"ts": ts, "change": change})
            self.log(ts, f"CrimeStat {change}")
            return [("crime", {"change": change})]
        if title.startswith("Low Fuel"):
            self.low_fuel_ts = ts
            return [("low_fuel", {})]
        if title.startswith("New Member Joined"):
            mm = re.match(r"(.+?) has joined the party", body)
            who = mm.group(1).strip() if mm else body
            if who and who not in self.party:
                self.party.append(who)
            self.log(ts, f"{who} joined the party")
            return [("party", {"who": who, "joined": True})]
        if title.startswith("Member Left"):
            mm = re.match(r"(.+?) has left the party", body)
            who = mm.group(1).strip() if mm else body
            if who in self.party:
                self.party.remove(who)
            self.log(ts, f"{who} left the party")
            return [("party", {"who": who, "joined": False})]
        if title.startswith("Party Disbanded"):
            self.party = []
            self.log(ts, "Party disbanded")
            return []
        if title.startswith("New Party Leader"):
            mm = re.match(r"(.+?) is now party leader", body)
            self.log(ts, f"{mm.group(1).strip() if mm else body} is now party leader")
            return []
        if title.startswith("You have created") and "party" in body.lower():
            self.log(ts, "You created a party")
            return []
        jc = JOIN_CHAN.match(text)
        if jc:
            ship, owner = jc.group("ship").strip(), jc.group("owner").strip()
            if not self.handle:
                return []
            if self.ship and self.ship["name"] == ship and self.ship["owner"] == owner:
                return []
            self.ship = {"name": ship, "owner": owner, "since": ts}
            self.log(ts, f"Boarded {'your' if self.me(owner) else owner + chr(39) + 's'} {ship}")
            return [("boarded", dict(self.ship))]
        lc = LEFT_CHAN.match(text)
        if lc:
            if self.ship and self.ship["name"] == lc.group("ship").strip():
                self.log(ts, f"Left the {self.ship['name']}")
                self.ship = None
            return []
        if title.startswith("Friend Added"):
            self.log(ts, f"Friend added: {body}")
            return []
        if title.startswith("Received Blueprint"):
            self.log(ts, f"Blueprint: {body}")
            return []
        if title.startswith("You've Earned"):
            self.log(ts, f"Earned: {body or title.split(':', 1)[-1].strip()}")
            return []
        if title.startswith("Journal Entry Added"):
            self.log(ts, f"Journal entry: {body}")
            return []
        return []

    # ------------------------------------------------------------ summaries
    def active_contracts(self):
        return sorted((c for c in self.contracts.values() if c["status"] == "active"), key=lambda c: c["accepted"])

    def ended_contracts(self):
        return sorted((c for c in self.contracts.values() if c["status"] != "active"), key=lambda c: -c["ended"])

    def spent(self):
        return sum(p["price"] for p in self.purchases)

    def received(self):
        return sum(m["amount"] for m in self.money_in)

    def ship_text(self):
        if self.ship:
            return self.ship["name"] if self.me(self.ship["owner"]) else f"{self.ship['owner']}'s {self.ship['name']}"
        if self.ship_entity:
            return pretty_vehicle(self.ship_entity) + " (last flown)"
        return ""

    def zone_text(self):
        bits = []
        if self.jurisdiction:
            bits.append(f"{self.jurisdiction} jurisdiction")
        if self.armistice:
            bits.append("armistice zone")
        if self.private_property:
            bits.append("private property")
        if self.comms_down:
            bits.append("comm array down")
        elif self.monitored is False:
            bits.append("unmonitored")
        return " · ".join(bits)

    def summary(self, name=""):
        done = [c["name"] for c in self.contracts.values() if c["status"] == "complete"]
        failed = [c["name"] for c in self.contracts.values() if c["status"] in ("failed", "abandoned")]
        ships = []
        for _, x in self.events:
            if x.startswith("Boarded your "):
                s = x[len("Boarded your "):]
                if s not in ships:
                    ships.append(s)
        return {"file": name, "start": self.session_start or (self.events[0][0] if self.events else 0), "end": self.last_ts,
                "version": self.game_version, "handle": self.handle,
                "kills": [{"ts": k["ts"], "victim": k["victim"], "ai": k["ai"]} for k in self.kills],
                "losses": [{"ts": k["ts"], "ship": k["victim"], "reason": k["reason"], "killer": k["killer"]} for k in self.losses],
                "deaths": len(self.deaths), "downed": len(self.downed), "contracts_done": done, "contracts_failed": failed,
                "qt": sum(1 for q in self.qt_log if q["result"] == "arrived"), "spent": self.spent(),
                "received": self.received(), "ships": ships, "crashed": bool(self.crashes),
                "disconnects": [d["reason"] for d in self.disconnects]}

    def snapshot_text(self):
        now = time.time()
        L = []
        L.append(f"Pilot: {self.handle or 'unknown'} · Star Citizen {self.game_version or '?'} · game "
                 f"{'running' if self.running else 'NOT running (data is from the last session)'}"
                 f" · session started {hm(self.session_start)} · last log line {ago(self.last_ts, now)}")
        L.append(f"Ship: {self.ship_text() or 'none known (on foot or not boarded yet)'}")
        if self.star_system:
            L.append(f"Star system (best guess from the log): {self.star_system}")
        where = self.zone_text() or "unknown"
        L.append(f"Zone: {where}" + (f" · last place: {clean_place(self.location)} ({ago(self.location_ts, now)})" if self.location else ""))
        if self.qt_target and now - self.qt_target_ts < 7200:
            st = "arrived" if self.qt_arrived_ts > self.qt_target_ts else \
                "path obstructed" if self.qt_obstructed_ts > self.qt_target_ts else "set, not arrived yet"
            L.append(f"Quantum target: {clean_place(self.qt_target)} ({st}, set {ago(self.qt_target_ts, now)})")
        act = self.active_contracts()
        if act:
            L.append("Active contracts: " + "; ".join(f"{c['name']}" + (f" (now: {c['current']})" if c.get("current") else "")
                                                      for c in act[:6]))
        else:
            L.append("Active contracts: none seen this session")
        L.append(f"This session: {len(self.kills)} ship kills, {len(self.losses)} ships lost, {len(self.deaths)} deaths, "
                 f"{len(self.downed)} times downed, {sum(1 for q in self.qt_log if q['result'] == 'arrived')} quantum jumps, "
                 f"{sum(1 for c in self.contracts.values() if c['status'] == 'complete')} contracts done, "
                 f"spent {self.spent():,.0f} aUEC, received {self.received():,.0f} aUEC")
        if self.party:
            L.append("Party: " + ", ".join(self.party))
        goods = []
        for c in act:
            for o in c["objectives"].values():
                m2 = re.search(r"\bof ([A-Z][A-Za-z ()'-]{2,40})$", o["text"])
                if m2 and not o["done"] and m2.group(1) not in goods:
                    goods.append(m2.group(1))
        if goods:
            L.append("Commodities in active contract objectives: " + ", ".join(goods))
        if self.crimes and now - self.crimes[-1]["ts"] < 3 * 3600:
            L.append(f"CrimeStat: last change '{self.crimes[-1]['change']}' {ago(self.crimes[-1]['ts'], now)}")
        recent = list(self.events)[-8:]
        if recent:
            L.append("Recent: " + " | ".join(f"{hm(t)} {x}" for t, x in recent))
        return "\n".join(L)


def parse_file(path, state=None):
    st = state or GameState()
    with open(path, "rb") as f:
        data = f.read()
    for raw in data.split(b"\n"):
        st.feed_line(raw.decode("utf-8", "ignore"))
    return st


class LogWatcher(threading.Thread):
    def __init__(self, state, install, binds_mod=None):
        super().__init__(daemon=True, name="gamelog")
        self.state = state
        self.install = Path(install) if install else None
        self.binds_mod = binds_mod
        self.state.install = self.install
        self.path = self.install / "Game.log" if self.install else None
        self.state.log_path = self.path
        self.stop_flag = False
        self.offset = 0
        self.partial = b""
        self.head = b""
        self.last_proc_check = 0
        self.proc_running = False

    def emit(self, events):
        if not self.state.live:
            return
        for name, info in events:
            for fn in list(self.state.listeners):
                try:
                    fn(name, info)
                except Exception:
                    traceback.print_exc()

    def _head(self):
        try:
            with open(self.path, "rb") as f:
                return f.read(160)
        except OSError:
            return b""

    def read_more(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        head = self._head()
        if size < self.offset or (self.head and head[:120] != self.head[:120]):
            with self.state.lock:
                handle, geid = self.state.handle, self.state.geid
                self.state.reset()
                self.state.handle, self.state.geid = handle, geid
                self.state.log(time.time(), "New game session started")
            self.offset, self.partial = 0, b""
        self.head = head
        if size == self.offset:
            return
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read(size - self.offset)
        except OSError:
            return
        self.offset += len(chunk)
        data = self.partial + chunk
        lines = data.split(b"\n")
        self.partial = lines.pop()
        for raw in lines:
            with self.state.lock:
                ev = self.state.feed_line(raw.decode("utf-8", "ignore"))
            if ev:
                self.emit(ev)

    def update_running(self):
        now = time.time()
        try:
            age = now - os.path.getmtime(self.path)
        except (OSError, TypeError):
            age = 1e9
        if self.binds_mod and now - self.last_proc_check > 8:
            self.last_proc_check = now
            try:
                self.proc_running = self.binds_mod.game_process_running()
            except Exception:
                self.proc_running = False
        running = self.proc_running or age < 90
        if running != self.state.running:
            with self.state.lock:
                self.state.running = running
                self.state.bump()

    def load_history(self):
        if not self.install:
            return
        folder = self.install / "logbackups"
        try:
            files = [p for p in folder.glob("Game*.log") if time.time() - p.stat().st_mtime < HISTORY_DAYS * 86400]
        except OSError:
            return
        files.sort(key=lambda p: p.stat().st_mtime)
        try:
            cache = json.loads(HISTORY_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        out, new_cache = [], {}
        for p in files:
            key = f"{p.name}:{p.stat().st_size}"
            s = cache.get(key)
            if s is None:
                try:
                    st = GameState()
                    st.handle, st.geid = self.state.handle, self.state.geid
                    parse_file(p, st)
                    s = st.summary(p.name)
                except Exception:
                    traceback.print_exc()
                    continue
            new_cache[key] = s
            out.append(s)
        try:
            HISTORY_CACHE.write_text(json.dumps(new_cache), encoding="utf-8")
        except OSError:
            pass
        out.sort(key=lambda h: h.get("start") or 0)
        with self.state.lock:
            self.state.history = out
            self.state.bump()

    def run(self):
        if not self.path or not self.path.exists():
            with self.state.lock:
                self.state.error = (f"Couldn't find Game.log in {self.install}" if self.install else
                                    "Couldn't find your Star Citizen install. Set the LIVE folder in Settings.")
                self.state.loaded = True
                self.state.bump()
        else:
            try:
                self.read_more()
            except Exception:
                self.state.error = traceback.format_exc(limit=4)
        self.update_running()
        with self.state.lock:
            self.state.live = True
            self.state.loaded = True
            self.state.bump()
        threading.Thread(target=self.load_history, daemon=True, name="history").start()
        while not self.stop_flag:
            try:
                if self.path:
                    if not self.path.exists():
                        time.sleep(1)
                        continue
                    self.read_more()
                    self.update_running()
            except Exception:
                traceback.print_exc()
            time.sleep(0.25)
