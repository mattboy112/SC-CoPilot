"""Screenshots of Star Citizen, so the co-pilot can look at the HUD and check itself instead of trusting its memory."""
import base64
import io
import json
import re
import sys
import time

import numpy as np

import sc_hud as HUD

WIN = sys.platform == "win32"
MAX_SIDE = 1280
QUALITY = 72
STATES = {"power": ("on", "off"), "engines": ("on", "off"), "gear": ("up", "down"), "in_seat": ("yes", "no")}

CHECK_SYSTEM = """You look at one screenshot from the game Star Citizen and report the ship's state to the co-pilot program.
Reply with only this JSON object and nothing else:
{"in_seat": "yes|no|unknown", "power": "on|off|unknown", "engines": "on|off|unknown", "gear": "up|down|unknown", "seen": "under 15 words: what showed it"}

How to tell:
- in_seat: "yes" if the view is from a pilot seat in a cockpit, "no" if the player is on foot, in a menu, on the map or a loading screen.
- Power off: the cockpit screens (MFDs) and the flight HUD are dark or blank.
- Power on, engines off: cockpit screens are lit, but there's no flight HUD (no speed, throttle or flight ladder), or a screen says engines or thrusters are off or offline.
- Engines on: the flight HUD shows speed, throttle or the flight ladder, or a screen shows engines or thrusters online.
- Gear: only from a landing gear indicator or icon you can actually see.
Use "unknown" whenever the picture doesn't clearly show it. Never guess. A blacked-out rectangle is the co-pilot's own window; ignore it."""


def available():
    if not WIN:
        return False, "Screen checks only work on Windows."
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False, "Screen checks need the Pillow package. Run Install.bat again."
    return True, ""


def client_rect(hwnd):
    """(left, top, right, bottom) of a window's inside on screen, or None."""
    if not (WIN and hwnd):
        return None
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    u.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    r = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(r)) or r.right <= 0 or r.bottom <= 0:
        return None
    p = wintypes.POINT(0, 0)
    if not u.ClientToScreen(hwnd, ctypes.byref(p)):
        return None
    return (p.x, p.y, p.x + r.right, p.y + r.bottom)


def blackout(img, origin, rects):
    """Paint the co-pilot's own windows black, so the AI can't mistake our text for the game's."""
    h, w = img.shape[:2]
    ox, oy = origin
    for rect in rects or ():
        if not rect:
            continue
        l, t, r, b = (int(v) for v in rect)
        l, r = max(0, l - ox), min(w, r - ox)
        t, b = max(0, t - oy), min(h, b - oy)
        if l < r and t < b:
            img[t:b, l:r] = 0
    return img


def shrink(img, max_side=MAX_SIDE):
    from PIL import Image
    pic = Image.fromarray(img)
    w, h = pic.size
    scale = min(1.0, max_side / float(max(w, h)))
    if scale < 1.0:
        pic = pic.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR)
    return pic


def encode(pic, quality=QUALITY):
    buf = io.BytesIO()
    pic.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def snapshot(rect, hide=(), grab=None):
    """A JPEG of a screen rectangle (left, top, right, bottom) with our own windows blacked out, ready for the AI.

    Returns {"media_type", "data" (base64), "width", "height", "bytes"} or None if the screen couldn't be read."""
    if not rect:
        return None
    l, t, r, b = rect
    img = (grab or HUD.capture)((l, t, r - l, b - t))
    if img is None or not img.size or float(img.mean()) < 0.5:
        return None
    img = blackout(np.ascontiguousarray(img), (l, t), hide)
    pic = shrink(img)
    raw = encode(pic)
    return {"media_type": "image/jpeg", "data": base64.b64encode(raw).decode("ascii"), "width": pic.size[0], "height": pic.size[1],
            "bytes": len(raw)}


def image_block(shot):
    return {"type": "image", "source": {"type": "base64", "media_type": shot["media_type"], "data": shot["data"]}}


def parse_check(text):
    """The AI's JSON answer as {"in_seat", "power", "engines", "gear", "seen"}, with anything odd turned into "unknown"."""
    out = {k: "unknown" for k in STATES}
    out["seen"] = ""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return out
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return out
    if not isinstance(d, dict):
        return out
    for k, words in STATES.items():
        v = str(d.get(k, "")).strip().lower()
        out[k] = v if v in words else "unknown"
    out["seen"] = str(d.get("seen", ""))[:120]
    return out


def flight_verdict(check):
    """True if power and engines are clearly on, False if either is clearly off, None if the picture didn't say."""
    if check.get("in_seat") == "no":
        return None
    if check.get("power") == "off" or check.get("engines") == "off":
        return False
    if check.get("engines") == "on":
        return True
    return None


class FlightCheck:
    """After pre-flight: look at the HUD, and if power or engines didn't come on, press once more and look again.

    look() -> (shot, why_not); ask_ai(shot) -> parse_check dict; press(action_id) -> (ok, problem_text);
    say(text) speaks; log(text) notes it in the chat; can_press(action_id) -> bool; ship is the ShipState."""
    SPINUP = 6.0

    def __init__(self, look, ask_ai, press, say, log, can_press, ship, sleep=time.sleep):
        self.look, self.ask_ai, self.press, self.say, self.log = look, ask_ai, press, say, log
        self.can_press, self.ship, self.sleep = can_press, ship, sleep

    def check(self):
        shot, why = self.look()
        if not shot:
            self.log(f"couldn't double-check the HUD: {why}")
            return None, None
        try:
            res = self.ask_ai(shot)
        except Exception as ex:
            self.log(f"couldn't double-check the HUD: {ex}")
            return None, None
        self.log(f"HUD check: power {res['power']}, engines {res['engines']}" + (f" · {res['seen']}" if res.get("seen") else ""))
        verdict = flight_verdict(res)
        if verdict is not None:
            self.ship.observe("power", verdict)
        if res["engines"] in ("on", "off") and res["in_seat"] != "no":
            self.ship.observe("thrusters", res["engines"] == "on")
        return verdict, res

    def fix_action(self, res):
        """Flight ready from cold, or just the engines when the power's already on (flight ready could switch it off)."""
        if res and res.get("power") == "on" and res.get("engines") == "off":
            for aid in ("thrusters_on", "thrusters_toggle"):
                if self.can_press(aid):
                    return aid
        return "flight_ready" if self.can_press("flight_ready") else None

    def run(self, pressed, from_memory=False):
        """pressed: flight ready was just pressed, so let the ship spin up first.
        from_memory: pressing was skipped because we remembered being flight ready, so always say what the HUD showed."""
        if pressed:
            self.sleep(self.SPINUP)
        ok, res = self.check()
        if ok is None:
            if from_memory:
                self.say("Already flight ready, I think. Couldn't confirm it on the HUD, so say it again if I've got that wrong.")
            return "unknown"
        if ok:
            if from_memory:
                self.say("Already flight ready. Engines are running.")
            return "ok"
        fix = self.fix_action(res)
        if not fix:
            self.say("Engines look off, and there's no key set for flight ready. Assign one on the Controls tab.")
            return "no_key"
        self.say("Engines are off. Starting them up." if from_memory else "Engines didn't come on. Trying again.")
        done, problem = self.press(fix)
        if not done:
            if problem:
                self.say(problem)
            return "press_failed"
        self.sleep(self.SPINUP)
        again, _ = self.check()
        if again:
            self.say("Engines are up.")
            return "fixed"
        if again is False:
            self.say("Still not seeing engines. Check your power screen.")
            return "still_off"
        self.say("Pressed it again, but couldn't confirm it on the HUD.")
        return "unconfirmed"
