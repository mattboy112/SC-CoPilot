"""The co-pilot's avatar: a glowing core with spinning rings inside a slowly turning cloud of points.

It reacts to what the app is doing:
  idle    - breathes slowly
  listen  - (push-to-talk held) the cloud pulls in tight and the rings brighten and open out
  think   - (transcribing / asking the AI) everything spins faster and a light chases round the edge
  speak   - the core pulses and the cloud ripples with the loudness of the voice

AvatarModel does the maths and returns plain shapes, so it can be tested without a screen.
Avatar draws those shapes on a Tk canvas, creating the items once and only moving them each frame.
"""
import math
import time
import tkinter as tk

CYAN = "#3cc8f5"
WHITE = "#e9eef2"
MODES = ("idle", "listen", "think", "speak")
SIZES = [("small", "Small"), ("medium", "Medium"), ("large", "Large")]
CHOICES = [("off", "Off")] + SIZES


def setting(s):
    """The avatar setting: 'off' or a size. Older settings used avatar_on + avatar_size; the size carries over."""
    v = s.get("avatar")
    if v in SIZE_PX or v == "off":
        return v
    size = s.get("avatar_size", "medium")
    return size if size in SIZE_PX else "medium"
SIZE_PX = {"small": 72, "medium": 96, "large": 132}
SHADES = 6


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(color, bg, amount):
    """`amount` of `color` over `bg` (Tk has no see-through colours, so glow is faked by blending)."""
    a = max(0.0, min(1.0, amount))
    c, b = _rgb(color), _rgb(bg)
    return "#%02x%02x%02x" % tuple(round(b[i] + (c[i] - b[i]) * a) for i in range(3))


def fake_level(t):
    """A believable talking rhythm, for voices where the real loudness isn't available (Windows voices)."""
    syllable = max(0.0, math.sin(t * 11) * math.sin(t * 3.1 + 1))
    word = 1.0 if math.sin(t * 1.3) > -0.6 else 0.1
    return min(1.0, (0.25 + 0.75 * syllable) * word * (0.8 + 0.2 * math.sin(t * 37)))


class AvatarModel:
    POINTS = 90
    TARGETS = {
        "idle": dict(spin=1.0, swarm=1.0, ring=0.0, bright=0.0, flat=0.0),
        "listen": dict(spin=0.8, swarm=0.84, ring=1.0, bright=1.0, flat=0.0),
        "think": dict(spin=3.0, swarm=0.95, ring=0.3, bright=0.4, flat=0.55),
        "speak": dict(spin=1.4, swarm=1.0, ring=0.2, bright=0.3, flat=0.0),
    }

    def __init__(self, size, bg):
        self.size, self.bg = size, bg
        self.u = size / 280.0
        self.c = size / 2.0
        self.level = 0.0
        self.p = dict(self.TARGETS["idle"])
        self.angle = 0.0
        self.ring_angle = [0.0, 0.0]
        self.chase = 0.0
        self.chase_a = 0.0
        self.t_last = None
        golden = math.pi * (3 - math.sqrt(5))
        self.sphere = []
        for i in range(self.POINTS):
            y = 1 - 2 * (i + 0.5) / self.POINTS
            r = math.sqrt(1 - y * y)
            self.sphere.append((math.cos(i * golden) * r, y, math.sin(i * golden) * r))
        self.palette = {k: [mix(col, bg, (j + 1) / SHADES) for j in range(SHADES)] for k, col in (("c", CYAN), ("w", WHITE))}

    def shade(self, which, amount):
        return self.palette[which][max(0, min(SHADES - 1, int(amount * SHADES)))]

    def step(self, t, mode, level=0.0):
        """Advance to time `t` (seconds) and return the shapes to draw."""
        dt = 0.0 if self.t_last is None else max(0.0, min(0.1, t - self.t_last))
        self.t_last = t
        mode = mode if mode in MODES else "idle"
        target = level if mode == "speak" else 0.0
        if mode == "speak" and level < 0:
            target = fake_level(t)
        k = 0.5 if target > self.level else 0.2
        self.level += (target - self.level) * min(1.0, k * dt * 30)
        ease = min(1.0, dt * 4)
        for key, goal in self.TARGETS[mode].items():
            self.p[key] += (goal - self.p[key]) * ease
        self.chase_a += ((1.0 if mode == "think" else 0.0) - self.chase_a) * min(1.0, dt * 6)
        p, u, c, lv = self.p, self.u, self.c, self.level
        self.angle += dt * 0.45 * p["spin"]
        self.ring_angle[0] += dt * 52 * p["spin"]
        self.ring_angle[1] -= dt * 32 * p["spin"]
        self.chase += dt * 300
        breath = math.sin(t * 1.6)

        core_r = (28 + lv * 13 + breath * 1.5 * (1 - min(1.0, lv * 3))) * u
        bright = p["bright"]
        core = [
            (core_r + 16 * u, self.shade("c", 0.16 + 0.08 * bright + 0.1 * lv)),
            (core_r + 6 * u, self.shade("c", 0.42 + 0.15 * bright + 0.2 * lv)),
            (max(2.0, core_r - 5 * u), WHITE),
        ]

        arcs = []
        for (radius, n, which, alpha), base in zip(((54, 6, "w", 0.62), (70, 4, "c", 0.5)), self.ring_angle):
            r = (radius + 7 * p["ring"]) * u
            a = min(1.0, alpha + 0.32 * bright + 0.25 * lv)
            extent = 360.0 / n * 0.56
            for i in range(n):
                start = base + i * 360.0 / n
                arcs.append((r, start, extent, 5.5 * u, self.shade(which, a * 0.35)))
                arcs.append((r, start, extent, 2.2 * u, self.shade(which, a)))

        ca, sa = math.cos(self.angle), math.sin(self.angle)
        base_r = 98 * u * p["swarm"]
        flat = p["flat"]
        points = []
        for i, (x, y, z) in enumerate(self.sphere):
            X, Z = x * ca + z * sa, -x * sa + z * ca
            Y = y * (1 - flat)
            rr = base_r * (1 + 0.24 * lv * math.sin(i * 1.7 + t * 14) + 0.02 * breath * math.sin(i))
            depth = (Z + 1.4) / 2.4
            col = self.shade("w" if depth > 0.72 else "c", 0.4 + 0.6 * depth + 0.15 * bright)
            points.append((c + X * rr, c + Y * rr, (1.6 + 3.0 * depth) * u * 1.15, col, Z > 0))

        chase = None
        if self.chase_a > 0.03:
            r = 128 * u
            chase = (r, -self.chase, 55.0, (6 * u, self.shade("w", 0.35 * self.chase_a)), (2.6 * u, self.shade("w", self.chase_a)),
                     (1.4 * u, self.shade("c", 0.32 * self.chase_a)))
        return {"core": core, "arcs": arcs, "points": points, "chase": chase}


class Avatar:
    """Animated avatar on its own canvas. Call start() when it's on screen and stop() when it isn't."""

    def __init__(self, parent, size, bg, get_activity, fps=30):
        self.size = int(size)
        self.bg = bg
        self.get_activity = get_activity
        self.fps = fps
        self.model = AvatarModel(self.size, bg)
        self.canvas = tk.Canvas(parent, width=self.size, height=self.size, bg=bg, highlightthickness=0, bd=0)
        self.job = None
        self.error = ""
        self.frames = 0
        self.t0 = time.time()
        self.front = []
        cv = self.canvas
        self.point_ids = [cv.create_oval(0, 0, 0, 0, fill=bg, outline="") for _ in range(AvatarModel.POINTS)]
        self.core_ids = [cv.create_oval(0, 0, 0, 0, fill=bg, outline="") for _ in range(3)]
        self.arc_ids = [cv.create_arc(0, 0, 0, 0, style="arc", outline=bg, width=1) for _ in range(20)]
        self.track_id = cv.create_oval(0, 0, 0, 0, outline=bg, width=1, state="hidden")
        self.chase_ids = [cv.create_arc(0, 0, 0, 0, style="arc", outline=bg, width=1, state="hidden") for _ in range(2)]
        self.front = [None] * AvatarModel.POINTS
        self.last = {}
        self.draw(self.model.step(0.0, "idle"))

    def _set(self, item, **kw):
        old = self.last.get(item)
        if old != kw:
            self.canvas.itemconfigure(item, **kw)
            self.last[item] = kw

    def draw(self, shapes):
        cv, c = self.canvas, self.size / 2.0
        for item, (r, color) in zip(self.core_ids, shapes["core"]):
            cv.coords(item, c - r, c - r, c + r, c + r)
            self._set(item, fill=color)
        for item, (r, start, extent, width, color) in zip(self.arc_ids, shapes["arcs"]):
            cv.coords(item, c - r, c - r, c + r, c + r)
            cv.itemconfigure(item, start=start % 360, extent=extent)
            self._set(item, outline=color, width=max(1, round(width)))
        for i, (item, (x, y, r, color, front)) in enumerate(zip(self.point_ids, shapes["points"])):
            cv.coords(item, x - r, y - r, x + r, y + r)
            self._set(item, fill=color)
            if front != self.front[i]:
                (cv.tag_raise if front else cv.tag_lower)(item)
                self.front[i] = front
        chase = shapes["chase"]
        if chase is None:
            self._set(self.track_id, state="hidden")
        else:
            r = chase[0]
            cv.coords(self.track_id, c - r, c - r, c + r, c + r)
            self._set(self.track_id, state="normal", outline=chase[5][1], width=max(1, round(chase[5][0])))
            cv.tag_lower(self.track_id)
        for item, layer in zip(self.chase_ids, (0, 1)):
            if chase is None:
                self._set(item, state="hidden")
                continue
            r, start, extent = chase[:3]
            width, color = chase[3 + layer]
            cv.coords(item, c - r, c - r, c + r, c + r)
            cv.itemconfigure(item, start=start % 360, extent=extent)
            self._set(item, state="normal", outline=color, width=max(1, round(width)))
            cv.tag_raise(item)

    def tick(self):
        self.job = None
        try:
            mode, level = self.get_activity()
        except Exception:
            mode, level = "idle", 0.0
        try:
            self.draw(self.model.step(time.time() - self.t0, mode, level))
            self.frames += 1
        except tk.TclError as e:
            self.error = f"TclError: {e}"
            return
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        self.job = self.canvas.after(int(1000 / (self.fps if mode != "idle" else max(12, self.fps * 2 // 3))), self.tick)

    def report(self):
        cv = self.canvas
        try:
            shown, w = bool(cv.winfo_ismapped()), cv.winfo_width()
        except tk.TclError:
            shown, w = False, 0
        return {"shown": shown, "px": w, "running": self.job is not None, "frames": self.frames, "error": self.error}

    def start(self):
        if self.job is None:
            self.tick()

    def stop(self):
        if self.job is not None:
            try:
                self.canvas.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
