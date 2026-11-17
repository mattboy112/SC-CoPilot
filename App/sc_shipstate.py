"""What state the ship is in (gear, master mode, lights...), so the co-pilot doesn't undo things by repeating them.

Star Citizen doesn't write these to its log, so the co-pilot keeps track itself:
- from the commands it sends,
- from your own presses of the same keys (watched while the game is in front),
- and it forgets everything when you board a different ship, die, or go back to the hangar.

How it uses that:
- If the action has a separate on/off key (gear deploy / retract...), it always presses: repeating those can't hurt.
  It just says "already down" when it knew.
- If only a toggle key exists, pressing it again would undo it. So a repeat is skipped, unless you say it again
  within a few seconds (in case the co-pilot got it wrong).
"""
import threading
import time

# state key -> on action, off action, toggle action, how to say each state, what to call it
GROUPS = {
    "gear": ("gear_down", "gear_up", "gear_toggle", ("down", "up"), "Gear"),
    "master": ("nav_mode", "scm_mode", "master_mode_cycle", ("in NAV mode", "in SCM mode"), "We're"),
    "power": ("power_on", "power_off", "power_toggle", ("on", "off"), "Power's"),
    "lights": ("lights_on", "lights_off", "lights_toggle", ("on", "off"), "Lights are"),
    "doors": ("doors_open", "doors_close", "doors_toggle", ("open", "closed"), "Doors are"),
    "vtol": ("vtol_on", "vtol_off", "vtol_toggle", ("on", "off"), "VTOL's"),
    "decoupled": ("decouple_on", "decouple_off", "decouple_toggle", ("on", "off"), "Decoupled mode's"),
    "shields": ("shields_on", "shields_off", "shields_toggle", ("up", "down"), "Shields are"),
    "weapons": ("weapons_power_on", "weapons_power_off", "weapons_power_toggle", ("online", "offline"), "Weapons are"),
    "thrusters": ("thrusters_on", "thrusters_off", "thrusters_toggle", ("on", "off"), "Thrusters are"),
    "gimbals": ("gimbals_lock", "gimbals_unlock", "gimbals_toggle", ("locked", "free"), "Gimbals are"),
}

EFFECT = {}
for _key, (_on, _off, _tog, _words, _name) in GROUPS.items():
    EFFECT[_on] = (_key, True)
    EFFECT[_off] = (_key, False)
    EFFECT[_tog] = (_key, "toggle")
EFFECT["flight_ready"] = ("power", "flight")

FORCE_WINDOW = 12.0
RESET_EVENTS = {"death", "hangar", "disconnect", "downed"}


class ShipState:
    def __init__(self):
        self.v = {}
        self.when = {}
        self.skipped = {}
        self.ship = None
        self.lock = threading.Lock()

    def get(self, key):
        return self.v.get(key)

    def reset(self, why=""):
        with self.lock:
            self.v.clear()
            self.when.clear()
            self.skipped.clear()

    def on_event(self, name, info=None):
        """Forget what we knew when the ship under us changes."""
        if name in RESET_EVENTS:
            self.reset(name)
        elif name == "boarded":
            ship = (info or {}).get("name")
            if ship != self.ship:
                self.reset("boarded")
            self.ship = ship

    def describe(self, key):
        val = self.v.get(key)
        if val is None or key not in GROUPS:
            return ""
        _on, _off, _tog, words, name = GROUPS[key]
        return f"{name} already {words[0] if val else words[1]}."

    def plan(self, action_id, pressable, now=None):
        """Decide what to press for `action_id`.

        Returns (action_to_press or None, note). note is "already" (pressing anyway, it was already like that),
        "skip" (not pressing: a toggle would undo it), "forced" (pressing a toggle because the request was repeated) or None.
        """
        now = time.time() if now is None else now
        eff = EFFECT.get(action_id)
        if not eff:
            return action_id, None
        key, val = eff
        if val == "toggle":
            return action_id, None
        cur = self.v.get(key)
        if val == "flight":
            if cur is True:
                return self._skip_or_force(key, True, action_id, now)
            return action_id, None
        on, off, tog, _w, _n = GROUPS[key]
        if pressable(action_id):
            return action_id, ("already" if cur == val else None)
        if not pressable(tog):
            return action_id, None
        if cur == val:
            return self._skip_or_force(key, val, tog, now)
        return tog, None

    def _skip_or_force(self, key, val, press, now):
        with self.lock:
            last = self.skipped.get(key)
            if last and last[0] == val and now - last[1] < FORCE_WINDOW:
                self.skipped.pop(key, None)
                return press, "forced"
            self.skipped[key] = (val, now)
        return None, "skip"

    def apply(self, action_id, intent=None, now=None):
        """Record that `action_id` was pressed. `intent` is what a toggle was pressed to achieve, if known."""
        now = time.time() if now is None else now
        eff = EFFECT.get(action_id)
        if not eff:
            return
        key, val = eff
        with self.lock:
            if val == "flight":
                cur = self.v.get(key)
                val = True if cur is not True else False
            elif val == "toggle":
                if intent is not None:
                    val = intent
                elif key in self.v:
                    val = not self.v[key]
                else:
                    return
            self.v[key] = val
            self.when[key] = now
            self.skipped.pop(key, None)


VK = {"lctrl": 0xA2, "rctrl": 0xA3, "lshift": 0xA0, "rshift": 0xA1, "lalt": 0xA4, "ralt": 0xA5,
      "mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06, "space": 0x20, "enter": 0x0D, "np_enter": 0x0D, "tab": 0x09,
      "backspace": 0x08, "escape": 0x1B, "capslock": 0x14, "pgup": 0x21, "pgdn": 0x22, "end": 0x23, "home": 0x24,
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "delete": 0x2E,
      "np_multiply": 0x6A, "np_add": 0x6B, "np_subtract": 0x6D, "np_period": 0x6E, "np_divide": 0x6F,
      "semicolon": 0xBA, "equals": 0xBB, "comma": 0xBC, "minus": 0xBD, "period": 0xBE, "slash": 0xBF, "grave": 0xC0,
      "lbracket": 0xDB, "backslash": 0xDC, "rbracket": 0xDD, "apostrophe": 0xDE}
VK.update({f"np_{i}": 0x60 + i for i in range(10)})
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
VK.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})


def vk_combo(spec, split_key):
    s = split_key(spec)
    if not s:
        return None
    key, mods = s
    codes = [VK.get(m) for m in mods] + [VK.get(key)]
    return tuple(codes) if all(codes) else None


class KeyWatcher:
    """Notices you pressing the ship-state keys yourself, so the co-pilot's picture stays right.

    Polls only those few keys, only while Star Citizen is in front, and ignores the co-pilot's own presses.
    """

    def __init__(self, state, binds_ref, action_index, split_key, is_busy, game_focused, interval=0.04):
        self.state = state
        self.binds_ref = binds_ref
        self.action_index = action_index
        self.split_key = split_key
        self.is_busy = is_busy
        self.game_focused = game_focused
        self.interval = interval
        self.watch = []
        self.built_for = None
        self.down = {}
        self.stop = threading.Event()

    def rebuild(self, binds):
        out = []
        for aid, (key, _v) in EFFECT.items():
            a = self.action_index.get(aid)
            if not a or not binds:
                continue
            k = binds.spec_for(a["sc"])
            if not k:
                continue
            combo = vk_combo(k[0], self.split_key)
            if not combo:
                continue
            kind, dur = binds.timing(k[1], k[2], k[3], k[4])
            out.append((aid, combo, dur - 0.15 if kind == "hold" else 0.0))
        self.watch = out
        self.built_for = binds

    def poll_once(self, pressed, now):
        """pressed(vk) -> bool. Feeds completed presses into the ship state. Returns the action ids it saw."""
        seen = []
        for aid, combo, need in self.watch:
            is_down = all(pressed(c) for c in combo)
            started = self.down.get(aid)
            if is_down and started is None:
                self.down[aid] = [now, False]
            elif is_down and started and not started[1] and now - started[0] >= need and need > 0:
                started[1] = True
                seen.append(aid)
            elif not is_down and started is not None:
                if need <= 0 and not started[1]:
                    seen.append(aid)
                self.down.pop(aid, None)
        for aid in seen:
            self.state.apply(aid)
        return seen

    def run(self):
        import ctypes
        get = ctypes.WinDLL("user32").GetAsyncKeyState
        get.argtypes = [ctypes.c_int]
        get.restype = ctypes.c_short
        pressed = lambda vk: bool(get(vk) & 0x8000)
        while not self.stop.wait(self.interval):
            try:
                binds = self.binds_ref()
                if binds is not self.built_for:
                    self.rebuild(binds)
                if not self.watch or self.is_busy() or not self.game_focused():
                    self.down.clear()
                    continue
                self.poll_once(pressed, time.time())
            except Exception:
                time.sleep(1)

    def start(self):
        threading.Thread(target=self.run, daemon=True, name="keywatch").start()
