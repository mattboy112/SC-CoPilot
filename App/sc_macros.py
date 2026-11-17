import copy
import re
import time

DEFAULT_MACROS = [
    {"name": "Prep for takeoff", "phrases": ["prep for takeoff", "prepare for takeoff", "ready for takeoff", "preflight"],
     "say": "Prepping for takeoff.",
     "steps": [{"action": "flight_ready", "wait": 5.0}, {"action": "doors_close", "wait": 0.6},
               {"action": "doors_lock", "wait": 0.6}, {"action": "request_landing", "wait": 0}]},
    {"name": "Landing prep", "phrases": ["landing prep", "prep for landing", "coming in to land", "on approach"],
     "say": "Requesting landing. Gear coming down.",
     "steps": [{"action": "request_landing", "wait": 1.0}, {"action": "gear_down", "wait": 0}]},
    {"name": "Combat ready", "phrases": ["combat ready", "battle stations", "lock and load"],
     "say": "Battle stations.",
     "steps": [{"action": "scm_mode", "wait": 0.6}, {"action": "shields_on", "wait": 0.3},
               {"action": "weapons_power_on", "wait": 0.3}, {"action": "lights_off", "wait": 0}]},
    {"name": "Go dark", "phrases": ["go dark", "run silent", "silent running"],
     "say": "Going dark. Lights, weapons and shields off.",
     "steps": [{"action": "lights_off", "wait": 0.3}, {"action": "weapons_power_off", "wait": 0.3},
               {"action": "shields_off", "wait": 0}]},
    {"name": "Evasive", "phrases": ["evasive", "evasive maneuvers", "break break", "missile incoming"],
     "say": "Countermeasures out.",
     "steps": [{"action": "decoys", "wait": 0.4}, {"action": "noise", "wait": 0.4}, {"action": "decoys", "wait": 0.3},
               {"action": "max_engines", "wait": 0}]},
]

FILLER = re.compile(r"\b(please|hey|ok|okay|computer|copilot|co pilot|go ahead and|let's|lets|the|a|an|now|time to|run|do|"
                    r"execute|macro)\b")


def defaults():
    return copy.deepcopy(DEFAULT_MACROS)


def _norm(t, name=""):
    t = re.sub(r"[^a-z0-9' ]+", " ", (t or "").lower())
    for part in {name.lower(), name.lower().replace("-", " ")} if name else ():
        t = re.sub(r"\b" + re.escape(part) + r"\b", " ", t)
    t = FILLER.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def match(text, macros, name=""):
    """A macro fires when what was said is (nearly) exactly one of its phrases."""
    said = _norm(text, name)
    if not said or "?" in text:
        return None
    for m in macros or []:
        for ph in m.get("phrases", []) + [m.get("name", "")]:
            p = _norm(ph)
            if p and (said == p or said == p + " macro" or said.replace(" ", "") == p.replace(" ", "")):
                return m
    return None


def find(macros, name):
    n = _norm(name)
    for m in macros or []:
        if _norm(m.get("name")) == n or n in [_norm(p) for p in m.get("phrases", [])]:
            return m
    for m in macros or []:
        if n and n in _norm(m.get("name")):
            return m
    return None


def run(macro, binds, actions_index, stop_flag=None, on_step=None):
    """Press each step in order. Steps without a key are skipped (never swapped for a blind toggle)."""
    done, skipped = [], []
    for i, st in enumerate(macro.get("steps", [])):
        if stop_flag is not None and stop_flag.is_set():
            skipped.append("stopped")
            break
        a = actions_index.get(st.get("action"))
        if not a:
            skipped.append(f"{st.get('action')} (unknown action)")
            continue
        if not binds.pressable(a["sc"]):
            skipped.append(f"{a['label']} (no key yet)")
        else:
            ok, msg = binds.press(a["sc"], focus=(i == 0 or not done))
            (done if ok else skipped).append(f"{a['label']}" + ("" if ok else f" ({msg})"))
            if not ok and "isn't running" in msg:
                break
        if on_step:
            on_step(i, st)
        w = float(st.get("wait") or 0)
        if w > 0 and i < len(macro["steps"]) - 1:
            end = time.time() + min(w, 30)
            while time.time() < end:
                if stop_flag is not None and stop_flag.is_set():
                    break
                time.sleep(0.05)
    return done, skipped
