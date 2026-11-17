import sys
import time
import tkinter as tk
import tkinter.font as tkfont

import sc_avatar as AV
from sc_log import clean_place

CORNERS = [("top_right", "Top right"), ("top_left", "Top left"), ("top_center", "Top center"), ("bottom_left", "Bottom left"),
           ("bottom_right", "Bottom right")]

INK = "#e8f4fb"
DIM = "#8fb0c2"
ACCENT = "#36b8e0"
GOOD = "#3fcf7f"
WARN = "#f0b54a"
BAD = "#ef6461"
PANEL = "#0b1117"
CHIP = "#13202a"
WIN = sys.platform == "win32"


_U32 = []
TOP_STATE = {"ok": None, "err": 0, "fails": 0}
HWND_TOPMOST = -1
SWP_FLAGS = 0x0001 | 0x0002 | 0x0010 | 0x0040 | 0x0200  # no move, no size, no activate, show, leave owner alone


def _user32():
    """Our own copy of user32 with the argument types spelled out. Window handles are 64-bit, and without this ctypes
    sends -1 (HWND_TOPMOST) as a 32-bit number, so Windows never sees it and silently refuses."""
    if _U32:
        return _U32[0]
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    H = wintypes.HWND
    u.SetWindowPos.argtypes = (H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    u.SetWindowPos.restype = wintypes.BOOL
    u.GetWindowLongW.argtypes = (H, ctypes.c_int)
    u.GetWindowLongW.restype = wintypes.LONG
    u.SetWindowLongW.argtypes = (H, ctypes.c_int, wintypes.LONG)
    u.SetWindowLongW.restype = wintypes.LONG
    u.GetParent.argtypes = (H,)
    u.GetParent.restype = H
    u.GetTopWindow.argtypes = (H,)
    u.GetTopWindow.restype = H
    u.GetWindow.argtypes = (H, wintypes.UINT)
    u.GetWindow.restype = H
    u.GetForegroundWindow.restype = H
    u.IsWindowVisible.argtypes = (H,)
    u.GetWindowRect.argtypes = (H, ctypes.POINTER(wintypes.RECT))
    u.MonitorFromWindow.argtypes = (H, wintypes.DWORD)
    u.MonitorFromWindow.restype = wintypes.HMONITOR
    u.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.c_void_p)
    _U32.append(u)
    return u


def _hwnd(win):
    try:
        return int(win.wm_frame(), 16)
    except (tk.TclError, ValueError, TypeError):
        return _user32().GetParent(win.winfo_id()) or win.winfo_id()


EX_WANT = 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000  # layered, transparent, toolwindow, noactivate


def _click_through(win):
    if not WIN:
        return
    try:
        u = _user32()
        h = _hwnd(win)
        style = u.GetWindowLongW(h, -20) & 0xFFFFFFFF
        if style & EX_WANT != EX_WANT:
            new = style | EX_WANT
            u.SetWindowLongW(h, -20, new - (1 << 32) if new >= 1 << 31 else new)
    except Exception:
        pass


def _keep_on_top(win):
    if WIN:
        try:
            import ctypes
            ok = bool(_user32().SetWindowPos(_hwnd(win), HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS))
            err = 0 if ok else ctypes.get_last_error()
            if not ok:
                TOP_STATE["fails"] += 1
                if TOP_STATE["fails"] in (1, 50, 500):
                    print(f"[{time.strftime('%H:%M:%S')}] overlay: Windows refused always-on-top (error {err})", flush=True)
            TOP_STATE.update(ok=ok, err=err)
            if ok:
                return
        except Exception as e:
            TOP_STATE.update(ok=False, err=f"{type(e).__name__}: {e}")
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass


def monitor_rect(hwnd):
    """(left, top, right, bottom) of the monitor a window is on, or None."""
    if not (WIN and hwnd):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        u = _user32()
        mon = u.MonitorFromWindow(hwnd, 2)
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if mon and u.GetMonitorInfoW(mon, ctypes.byref(mi)):
            r = mi.rcMonitor
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None


def stack_report(ov, game):
    """Where the overlay and the game sit in Windows' window stack, for the overlay test log."""
    if not WIN:
        return {}
    import ctypes
    from ctypes import wintypes
    u = _user32()
    out = {"game_found": bool(game)}
    fg = u.GetForegroundWindow()
    out["game_focused"] = bool(game) and fg == game
    ov_i = game_i = None
    h, i = u.GetTopWindow(None), 0
    while h and i < 4000 and (ov_i is None or (game and game_i is None)):
        if h == ov:
            ov_i = i
        if game and h == game:
            game_i = i
        h, i = u.GetWindow(h, 2), i + 1
    out["overlay_pos"] = ov_i
    out["game_pos"] = game_i
    out["overlay_above_game"] = None if ov_i is None or game_i is None else ov_i < game_i
    ex = u.GetWindowLongW(ov, -20) & 0xFFFFFFFF
    out["overlay_topmost"] = bool(ex & 0x8)
    out["topmost_call"] = dict(TOP_STATE)
    out["overlay_owner"] = bool(u.GetWindow(ov, 4))
    out["overlay_visible"] = bool(u.IsWindowVisible(ov))
    if game:
        out["game_topmost"] = bool(u.GetWindowLongW(game, -20) & 0x8)
        r = wintypes.RECT()
        u.GetWindowRect(game, ctypes.byref(r))
        out["game_rect"] = (r.left, r.top, r.right, r.bottom)
        out["same_monitor"] = monitor_rect(ov) == monitor_rect(game)
    try:
        cloaked = wintypes.DWORD(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(ov), 14, ctypes.byref(cloaked), 4)
        out["overlay_cloaked"] = cloaked.value
    except Exception:
        pass
    return out


class Overlay:
    """Small always-on-top, click-through HUD. Shows over Star Citizen when the game runs in Borderless Windowed mode.
    It's created once and then only faded in and out, so it never grabs focus from the game."""

    ROWS = ("chips", "ship", "objective", "qt", "callout")

    def __init__(self, root, get_settings, game_window=None, get_activity=None):
        self.root = root
        self.get_activity = get_activity or (lambda: ("idle", 0.0))
        self.avatar = None
        self.get_settings = get_settings
        self.game_window = game_window
        self.game_mon = None
        self.game_mon_t = 0.0
        self.win = None
        self.rows = {}
        self.last_sig = None
        self.visible = False
        self.last_top = 0.0
        self.callout = ("", 0.0)
        self.built_style = None

    def _font(self, size, bold=False):
        families = set(tkfont.families(self.root))
        fam = next((f for f in ("Segoe UI", "Inter", "DejaVu Sans") if f in families), "TkDefaultFont")
        return (fam, size, "bold") if bold else (fam, size)

    def _style(self):
        s = self.get_settings()
        return (int(s.get("overlay_scale", 100)), int(s.get("overlay_opacity", 82)), s.get("overlay_corner", "top_right"),
                AV.setting(s))

    def build(self):
        scale_pct, opacity, corner, avatar = self.built_style = self._style()
        scale = max(0.7, min(2.0, scale_pct / 100.0))
        self.opacity = max(0.3, min(1.0, opacity / 100.0))
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.configure(bg=PANEL)
        try:
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        frame = tk.Frame(self.win, bg=PANEL, padx=int(12 * scale), pady=int(8 * scale), highlightthickness=1,
                         highlightbackground="#1f3442")
        frame.pack(fill="both", expand=True)
        side = "left" if "left" in corner else "right"
        if avatar != "off":
            px = int(AV.SIZE_PX[avatar] * scale)
            self.avatar = AV.Avatar(frame, px, PANEL, self.get_activity)
            self.avatar.canvas.pack(side=side, padx=(int(10 * scale), 0) if side == "right" else (0, int(10 * scale)))
        text = tk.Frame(frame, bg=PANEL)
        text.pack(side="left" if side == "right" else "right", fill="y")
        frame = text
        self.tiny = self._font(int(8 * scale), True)
        wrap = int(440 * scale)
        self.rows = {"chips": tk.Frame(frame, bg=PANEL)}
        for key, font, color in (("ship", self._font(int(10 * scale)), DIM), ("objective", self._font(int(11 * scale), True), INK),
                                 ("qt", self._font(int(10 * scale)), DIM), ("callout", self._font(int(10 * scale)), ACCENT)):
            self.rows[key] = tk.Label(frame, text="", font=font, fg=color, bg=PANEL, anchor="w", justify="left", wraplength=wrap)
        for i, key in enumerate(self.ROWS):
            self.rows[key].grid(row=i, column=0, sticky="w", pady=(0, int(2 * scale)))
            self.rows[key].grid_remove()
        self.win.update_idletasks()
        _click_through(self.win)
        _keep_on_top(self.win)
        self.visible = False
        self.last_sig = None

    def destroy(self):
        if self.avatar is not None:
            self.avatar.stop()
            self.avatar = None
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.last_sig = None
        self.visible = False

    def set_callout(self, text):
        self.callout = (text, time.time())

    def _show(self, on):
        if on == self.visible:
            return
        self.visible = on
        try:
            self.win.attributes("-alpha", self.opacity if on else 0.0)
        except tk.TclError:
            pass
        if self.avatar is not None:
            (self.avatar.start if on else self.avatar.stop)()

    def _place(self):
        corner = self.get_settings().get("overlay_corner", "top_right")
        m = int(self.get_settings().get("overlay_margin", 24))
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        if self.game_mon:
            l, t, r, b = self.game_mon
        else:
            l, t, r, b = 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = l + m if "left" in corner else l + (r - l - w) // 2 if "center" in corner else r - w - m
        y = t + m if corner.startswith("top") else b - h - m - 40
        self.win.geometry(f"+{x}+{y}")

    def _track_game_monitor(self):
        now = time.time()
        if self.game_window is None or now - self.game_mon_t < 3:
            return False
        self.game_mon_t = now
        try:
            mon = monitor_rect(self.game_window())
        except Exception:
            mon = None
        if mon and mon != self.game_mon:
            self.game_mon = mon
            return True
        return False

    def report(self):
        if self.win is None or not WIN:
            return {"overlay": "not built"}
        try:
            game = self.game_window() if self.game_window else None
            r = stack_report(_hwnd(self.win), game)
            r["alpha"] = self.opacity if self.visible else 0.0
            r["avatar"] = self.avatar.report() if self.avatar is not None else \
                ("switched off in Settings" if AV.setting(self.get_settings()) == "off" else "not built")
            return r
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def update(self, state, status="", force=False):
        s = self.get_settings()
        want = force or (bool(s.get("overlay_on", False)) and (state.running or not s.get("overlay_only_in_game", True)))
        if not want:
            if self.win is not None:
                self._show(False)
            return
        if self.win is None or self._style() != self.built_style:
            self.destroy()
            self.build()
        now = time.time()
        with state.lock:
            chips = []
            if state.jurisdiction:
                danger = state.jurisdiction in ("Ungoverned", "Headhunters", "XenoThreat")
                chips.append((state.jurisdiction.upper(), BAD if danger else ACCENT))
            if state.armistice is not None:
                chips.append(("ARMISTICE", GOOD) if state.armistice else ("WEAPONS FREE", WARN))
            if state.comms_down:
                chips.append(("COMMS DOWN", WARN))
            elif state.monitored is False:
                chips.append(("UNMONITORED", WARN))
            if state.private_property:
                chips.append(("PRIVATE", WARN))
            ship = state.ship_text()
            act = state.active_contracts()
            obj = ""
            if act:
                c = act[-1]
                obj = f"▸ {c['current']}" if c.get("current") else f"▸ {c['name']}"
                if len(act) > 1:
                    obj += f"   (+{len(act) - 1} more)"
            qt = ""
            if state.qt_target and now - state.qt_target_ts < 3600:
                st = "arrived" if state.qt_arrived_ts > state.qt_target_ts else \
                    "path blocked" if state.qt_obstructed_ts > state.qt_target_ts else "set"
                if st != "arrived" or now - state.qt_arrived_ts < 60:
                    qt = f"QT ▸ {clean_place(state.qt_target)} · {st}"
        ctext, cts = self.callout
        call = status or (f"“{ctext}”" if ctext and now - cts < float(s.get("overlay_callout_secs", 8)) else "")
        if not (chips or ship or obj or qt or call):
            ship = "SC Co-Pilot"
        sig = (tuple(chips), ship, obj, qt, call)
        if sig != self.last_sig:
            self.last_sig = sig
            for w in self.rows["chips"].winfo_children():
                w.destroy()
            for text, color in chips:
                tk.Label(self.rows["chips"], text=text, font=self.tiny, fg=color, bg=CHIP, padx=6, pady=1).pack(side="left", padx=(0, 4))
            vals = {"chips": bool(chips), "ship": ship, "objective": obj, "qt": qt, "callout": call}
            for key in ("ship", "objective", "qt", "callout"):
                self.rows[key].config(text=vals[key])
            self.rows["callout"].config(fg=BAD if status.startswith("●") else ACCENT)
            for key in self.ROWS:
                (self.rows[key].grid if vals[key] else self.rows[key].grid_remove)()
            self._track_game_monitor()
            self._place()
        elif self._track_game_monitor():
            self._place()
        self._show(True)
        self.pin()

    def pin(self):
        """Re-assert always-on-top. The game grabs the top of the stack whenever it's clicked, so this runs constantly."""
        if self.win is None or not self.visible:
            return
        now = time.time()
        if now - self.last_top >= 0.2:
            self.last_top = now
            _click_through(self.win)
            _keep_on_top(self.win)
