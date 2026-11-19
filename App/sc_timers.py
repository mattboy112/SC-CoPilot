"""Timers for refinery jobs, mission deadlines and anything else, with spoken alerts and a countdown on the overlay."""
import json
import re
import threading
import time
from pathlib import Path

MAX_TIMERS = 10
MAX_SECONDS = 72 * 3600
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
         "couple": 2, "few": 3}
UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
         "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600}
NUM = r"(?:\d+(?:\.\d+)?|" + "|".join(sorted(WORDS, key=len, reverse=True)) + r")(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?"
UNIT = r"(?:" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")"
DURATION = rf"(?:(?:and )?(?:a )?(?:half (?:an? )?(?:hour|minute)|{NUM} (?:and a half )?{UNIT}(?: and a half)?)[ ,]*)+"


def _num(tok):
    tok = tok.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", tok):
        return float(tok)
    parts = re.split(r"[ -]", tok)
    return float(sum(WORDS.get(p, 0) for p in parts))


def parse_duration(text):
    """Seconds in a spoken duration like "an hour and a half", "1 hour 20 minutes", "90 seconds" or "half an hour"; None if none."""
    t = " " + re.sub(r"[^a-z0-9. -]+", " ", (text or "").lower()) + " "
    total = 0.0
    found = False
    for m in re.finditer(r"\bhalf (?:an? )?(hour|minute)\b", t):
        total += UNITS[m.group(1)] / 2
        found = True
    t = re.sub(r"\bhalf (?:an? )?(?:hour|minute)\b", " ", t)
    for m in re.finditer(rf"\b({NUM}) ((?:and a half )?)({UNIT})\b((?: and a half)?)", t):
        n = _num(m.group(1))
        if m.group(2) or m.group(4):
            n += 0.5
        total += n * UNITS[m.group(3)]
        found = True
    if not found or total <= 0:
        return None
    return int(round(min(total, MAX_SECONDS)))


def spoken(seconds):
    """12 minutes, 1 hour 5 minutes, 45 seconds."""
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} hour{'s' * (h != 1)}" + (f" {m} minute{'s' * (m != 1)}" if m else "")
    if m:
        if m < 5 and sec >= 30:
            return f"{m} and a half minutes"
        return f"{m} minute{'s' * (m != 1)}"
    return f"{sec} second{'s' * (sec != 1)}"


def clock(seconds):
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _label(text):
    text = re.sub(r"\s+", " ", (text or "").strip(" .,!?")).strip()
    text = re.sub(r"^(?:the|my|a|an)\s+", "", text, flags=re.I)
    return text[:40]


SET = re.compile(rf"^(?:please )?(?:set|start|make|put on|give me)(?: me)?(?: up)? (?:a |an |the )?(?:new )?(?:(?P<pre>[a-z ]{{1,30}}?) )?"
                 rf"(?:timer|countdown|reminder)(?: for| of)? (?P<dur>{DURATION})(?:(?:for|called|named|to|on|about) (?P<label>.+))?$")
SET_FIRST = re.compile(rf"^(?:please )?(?:set|start|make|put on|give me)(?: me)?(?: up)? (?:a |an |the )?(?P<dur>{DURATION})"
                       rf"(?:(?P<pre>[a-z ]{{1,30}}?) )?(?:timer|countdown|reminder)(?: (?:for|called|named|to|on|about) (?P<label>.+))?$")
SET_SHORT = re.compile(rf"^(?P<dur>{DURATION})(?:timer|countdown)(?: (?:for|on) (?P<label>.+))?$")
REMIND = re.compile(rf"^remind me in (?P<dur>{DURATION})(?:(?:to|about|that|for) (?P<label>.+))?$")
REMIND_AFTER = re.compile(rf"^remind me (?:to |about )(?P<label>.+?) in (?P<dur>{DURATION})$")
LIST = re.compile(r"^(?:how (?:long|much time)(?: is)?(?: left| remaining)?(?: on)?(?: the| my)?(?: (?P<label>[a-z ]+?))? ?(?:timers?|countdown)?"
                  r"|(?:what(?:'s| is| are)? )?(?:my |the )?timers?(?: status| left)?|timer status|any timers|check (?:my |the )?timers?)$")
CANCEL = re.compile(r"^(?:cancel|stop|clear|delete|kill|remove)(?: all)?(?: the| my)?(?: (?P<label>[a-z ]+?))? (?:timers?|countdowns?|reminders?)$")


def parse_command(text, name=""):
    """An instant timer command from what was said, or None.

    {"kind": "timer", "op": "set", "seconds": 600, "label": "refinery"} / {"op": "list", "label": ...} / {"op": "cancel", ...}"""
    t = (text or "").lower().strip()
    if name:
        for part in {name.lower(), name.lower().replace("-", " "), name.lower().replace("-", "")}:
            t = re.sub(r"^(?:hey |ok |okay )?" + re.escape(part) + r"[ ,]+", "", t)
    t = re.sub(r"[^a-z0-9' .-]+", " ", t).replace("'", "")
    t = re.sub(r"\s+", " ", t).strip(" .")
    for pat in (SET, SET_FIRST, SET_SHORT, REMIND, REMIND_AFTER):
        m = pat.match(t)
        if m:
            secs = parse_duration(m.group("dur"))
            if not secs:
                return None
            gd = m.groupdict()
            label = _label(gd.get("label") or gd.get("pre") or "")
            return {"kind": "timer", "op": "set", "seconds": secs, "label": label}
    m = CANCEL.match(t)
    if m:
        lab = _label(m.group("label") or "")
        return {"kind": "timer", "op": "cancel", "label": "" if lab in ("all", "every") else lab}
    m = LIST.match(t)
    if m:
        lab = _label(m.groupdict().get("label") or "")
        return {"kind": "timer", "op": "list", "label": "" if lab in ("timer", "timers", "countdown") else lab,
                "explicit": bool(re.search(r"\b(timers?|countdown)\b", t))}
    return None


class Timers:
    """The running timers, saved to disk so a 3-hour refinery job survives a restart."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.items = []
        self.next_id = 1
        self.load()

    def load(self):
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [i for i in data.get("timers", []) if isinstance(i, dict) and "ends" in i][:MAX_TIMERS]
            self.next_id = max([int(i.get("id", 0)) for i in self.items] + [0]) + 1
        except Exception:
            self.items = []

    def save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"timers": self.items}), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def add(self, seconds, label="", now=None):
        """Start a timer. Returns it, or raises ValueError with a sentence to say."""
        now = time.time() if now is None else now
        seconds = int(seconds)
        if seconds < 1:
            raise ValueError("That timer has no length.")
        if seconds > MAX_SECONDS:
            raise ValueError("Timers can run for up to 72 hours.")
        with self.lock:
            if len(self.items) >= MAX_TIMERS:
                raise ValueError(f"You've got {MAX_TIMERS} timers running already. Cancel one first.")
            item = {"id": self.next_id, "label": _label(label), "seconds": seconds, "ends": now + seconds, "started": now}
            self.next_id += 1
            self.items.append(item)
            self.items.sort(key=lambda i: i["ends"])
            self.save()
        return item

    def find(self, label=""):
        """Timers whose name contains the words, or all of them when no words are given."""
        lab = _label(label).lower()
        with self.lock:
            if not lab:
                return list(self.items)
            return [i for i in self.items if lab in i["label"].lower() or i["label"].lower() in lab and i["label"]]

    def cancel(self, label=""):
        hit = self.find(label)
        ids = {i["id"] for i in hit}
        with self.lock:
            self.items = [i for i in self.items if i["id"] not in ids]
            self.save()
        return hit

    def due(self, now=None):
        """Remove and return every timer that has run out."""
        now = time.time() if now is None else now
        with self.lock:
            done = [i for i in self.items if i["ends"] <= now]
            if done:
                self.items = [i for i in self.items if i["ends"] > now]
                self.save()
        return done

    def rows(self, now=None, limit=3):
        """[(name, "12:34"), ...] for the overlay, soonest first."""
        now = time.time() if now is None else now
        with self.lock:
            return [(i["label"] or "Timer", clock(i["ends"] - now)) for i in self.items[:limit]]

    def describe(self, label="", now=None):
        now = time.time() if now is None else now
        hit = self.find(label)
        if not hit:
            return f"No {label} timer running." if label else "No timers running."
        parts = [f"{i['label'] or 'timer'}: {spoken(i['ends'] - now)} left" for i in hit[:4]]
        more = f", and {len(hit) - 4} more" if len(hit) > 4 else ""
        text = "; ".join(parts) + more + "."
        return text[0].upper() + text[1:]

    def as_tool_text(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if not self.items:
                return "No timers running."
            return "\n".join(f"- {i['label'] or 'timer'}: {spoken(i['ends'] - now)} left (ends {time.strftime('%H:%M', time.localtime(i['ends']))})"
                             for i in self.items)
