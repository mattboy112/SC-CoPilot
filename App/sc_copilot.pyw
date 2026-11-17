import base64
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sc_paths as P

APP_NAME = P.APP_NAME
APP_DIR = P.APP_DIR
MIGRATED = P.migrate_legacy()
SETTINGS_FILE = P.SETTINGS_FILE
LOG_FILE = P.LOG_FILE

if sys.stderr is None or sys.stdout is None:
    try:
        _log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stderr = sys.stderr or _log
        sys.stdout = sys.stdout or _log
    except OSError:
        pass

import sc_binds as B
import sc_brain as BR
import sc_callouts as CO
import sc_fx as FX
import sc_log as L
import sc_macros as MAC
import sc_hud as HUD
import sc_lines as LN
import sc_nvidia as NV
import sc_winicon as WI
import sc_update as UPD
import sc_version as VER
import sc_overlay as OV
import sc_quick as Q
import sc_trade as T
import sc_voice as V

C = {
    "bg": "#15191f", "bar": "#0f1216", "card": "#1b2028", "card2": "#191e25", "line": "#29313c",
    "input": "#12161b", "text": "#d9e2ea", "hi": "#f0f5f9", "muted": "#8b98a6", "dim": "#5a6673",
    "accent": "#36b8e0", "accent_hover": "#5ccaec", "on_accent": "#06161d", "good": "#3fcf7f",
    "low": "#f0b54a", "toss": "#ef6461", "blue": "#8fb3ff", "gray": "#7d858f", "sel": "#16283a",
    "btn": "#232a33", "btn_hover": "#2e3742", "chip_on": "#e6eef4", "chip_on_text": "#121619", "teal": "#22b39b",
    "amber_bg": "#3a2c12", "red_bg": "#3a1a1a", "blue_bg": "#13293a", "green_bg": "#123224",
}
KINDS = {
    "primary": (C["accent"], C["on_accent"], C["accent_hover"]),
    "normal": (C["btn"], C["text"], C["btn_hover"]),
    "ghost": (C["bg"], C["text"], C["btn"]),
    "danger": (C["btn"], C["toss"], C["btn_hover"]),
    "on": (C["chip_on"], C["chip_on_text"], "#ffffff"),
    "tab": (C["bg"], C["muted"], C["card"]),
    "tab_on": (C["card"], C["hi"], C["card"]),
    "talk": ("#10222c", C["accent"], "#163140"),
    "talk_on": (C["toss"], "#1f0b0b", C["toss"]),
}
F = {}
SCALE = [1.0]

DEFAULTS = {
    "api_key": "", "model": BR.MODELS[0][0], "assistant_name": "Co-Pilot", "voice": "en-GB-RyanNeural", "tts_engine": "neural",
    "tts_rate": 0, "volume": 90, "chirps": True, "speak_answers": True, "instant_commands": True, "web_lookups": True,
    "pilot_notes": "", "ptt": {"kind": "key", "vk": 0x05, "name": "Mouse 4"}, "mic": None, "stt_model": "base.en",
    "stt_device": "cpu", "callouts": {c: True for c, _ in CO.CATEGORIES}, "install_dir": "", "geometry": "", "tab": "overview",
    "kokoro_voice": V.KOKORO_DEFAULT, "voice_fx": "computer", "voice_fx_amount": 100, "voice_pitch": 0, "macros": MAC.defaults(),
    "overlay_on": False, "overlay_corner": "top_right", "overlay_scale": 100, "overlay_opacity": 82, "overlay_only_in_game": True,
    "overlay_callout_secs": 8, "trade_system": "auto", "run_as_admin": False,
    "ai_mode": "own_key", "license_key": "", "check_updates": True, "last_update_check": 0, "setup_done": False,
    "personality": "standard", "lines": {}, "hud_profiles": {}, "hud_watch": False,
}
STT_MODELS = [("tiny.en", "Tiny (fastest, rougher)"), ("base.en", "Base (good balance)"), ("small.en", "Small (most accurate, slower)")]
STT_DEVICES = [("cpu", "CPU (recommended)"), ("cuda", "NVIDIA GPU (needs CUDA 12 + cuDNN 9)")]
ENGINES = V.ENGINES
EDGE_CACHE = P.cache("sc_edge_voices.json")


def px(n):
    return int(round(n * SCALE[0]))


def setup_fonts(root):
    families = set(tkfont.families(root))
    fam = next((f for f in ("Segoe UI", "Inter", "DejaVu Sans") if f in families), "TkDefaultFont")
    mono = next((f for f in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono") if f in families), "TkFixedFont")
    F.update({
        "base": (fam, 10), "small": (fam, 9), "small_bold": (fam, 9, "bold"), "tiny_bold": (fam, 8, "bold"),
        "btn": (fam, 10, "bold"), "label": (fam, 8, "bold"), "num": (fam, 11), "table": (fam, 10), "brand": (fam, 15, "bold"),
        "h2": (fam, 12, "bold"), "big": (fam, 26, "bold"), "metric": (fam, 17, "bold"), "chat": (fam, 10), "mono": (mono, 9),
    })


def load_settings():
    s = json.loads(json.dumps(DEFAULTS))
    saved = None
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        pass
    if saved is None:
        s["_first_run"] = True
    for k, v in (saved or {}).items():
        if k == "callouts" and isinstance(v, dict):
            s["callouts"].update(v)
        else:
            s[k] = v
    return s


_SAVE_LOCK = threading.Lock()


def save_settings(s):
    with _SAVE_LOCK:
        tmp = SETTINGS_FILE.with_name(f"sc_settings.{threading.get_ident()}.tmp")
        try:
            data = json.dumps({k: v for k, v in dict(s).items() if not k.startswith("_")}, indent=2)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, SETTINGS_FILE)
        except (OSError, RuntimeError, TypeError, ValueError):
            traceback.print_exc()


class FlatButton(tk.Button):
    def __init__(self, parent, text, command, kind="normal", font=None, padx=14, pady=6, **kw):
        super().__init__(parent, text=text, command=command, relief="flat", bd=0, padx=padx, pady=pady,
                         cursor="hand2", font=font or F["btn"], highlightthickness=0, **kw)
        self.set_kind(kind)
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg))

    def set_kind(self, kind):
        self._bg, fg, self._hover = KINDS[kind]
        self.config(bg=self._bg, fg=fg, activebackground=self._hover, activeforeground=fg)


def card(parent, **kw):
    return tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["line"], **kw)


def label(parent, text="", font="base", fg="text", bg="card", **kw):
    return tk.Label(parent, text=text, font=F[font], fg=C.get(fg, fg), bg=C.get(bg, bg), **kw)


def entry(parent, width=10, **kw):
    return tk.Entry(parent, width=width, bg=C["input"], fg=C["hi"], insertbackground=C["accent"], relief="flat",
                    highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["accent"], font=F["num"], **kw)


def chip(parent, text, fg, bg):
    return tk.Label(parent, text=text, font=F["tiny_bold"], fg=C.get(fg, fg), bg=C.get(bg, bg), padx=px(8), pady=px(3))


def menu_opts():
    return dict(tearoff=False, bg=C["card2"], fg=C["text"], activebackground=C["accent"], activeforeground=C["on_accent"],
                bd=0, font=F["small"])


def chooser(parent, options, current, on_pick, width=26):
    mb = tk.Menubutton(parent, text="", font=F["small_bold"], fg=C["text"], bg=C["btn"], activebackground=C["btn_hover"],
                       activeforeground=C["hi"], relief="flat", bd=0, padx=10, pady=5, cursor="hand2", highlightthickness=0,
                       direction="below", width=width, anchor="w")
    menu = tk.Menu(mb, **menu_opts())
    names = dict(options)

    def pick(v):
        mb.config(text=names.get(v, str(v)) + "  ▾")
        on_pick(v)
    for v, n in options:
        menu.add_command(label=n, command=lambda v=v: pick(v))
    mb.config(menu=menu, text=names.get(current, str(current) if current is not None else "—") + "  ▾")
    return mb


def check(parent, text, var, command, bg="card"):
    return tk.Checkbutton(parent, text=text, variable=var, command=command, font=F["small"], fg=C["text"], bg=C[bg],
                          activebackground=C[bg], activeforeground=C["hi"], selectcolor=C["input"], highlightthickness=0,
                          bd=0, anchor="w", cursor="hand2", wraplength=px(700), justify="left")


def slider(parent, frm, to, value, command, length=220, res=1):
    f = tk.Frame(parent, bg=C["card"])
    val = tk.Label(f, text=str(int(value)), font=F["small_bold"], fg=C["hi"], bg=C["card"], width=4, anchor="w")

    def moved(v):
        n = int(round(float(v) / res) * res)
        val.config(text=str(n))
        command(n)
    sc = ttk.Scale(f, from_=frm, to=to, orient="horizontal", length=px(length), style="Dark.Horizontal.TScale", command=moved)
    sc.set(value)
    sc.pack(side="left")
    val.pack(side="left", padx=(px(10), 0))
    return f


class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.bgc = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner = None
        self.win = None
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _resize(self, e):
        if self.win:
            self.canvas.itemconfigure(self.win, width=e.width)

    def swap(self, builder):
        y = self.canvas.yview()[0]
        new = tk.Frame(self.canvas, bg=self.bgc)
        builder(new)
        old = self.inner
        if self.win:
            self.canvas.delete(self.win)
        self.win = self.canvas.create_window(0, 0, window=new, anchor="nw", width=max(1, self.canvas.winfo_width()))
        self.inner = new
        new.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        if old is not None:
            old.destroy()
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(y)


def self_command(*args):
    """How to start this app again: the .exe when installed, pythonw + the script when run from source."""
    if P.FROZEN:
        return Path(sys.executable), " ".join(f'"{a}"' for a in args)
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    target = pyw if pyw.exists() else exe
    return target, " ".join([f'"{APP_DIR / "sc_copilot.pyw"}"'] + [f'"{a}"' for a in args])


def create_desktop_shortcut():
    target, args = self_command()
    qq = lambda p: str(p).replace("'", "''")
    icon = WI.stable_icon() or P.resource("sc_copilot.ico")
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'SC Co-Pilot.lnk'));"
        f"$s.TargetPath='{qq(target)}';"
        + (f"$s.Arguments='{qq(args)}';" if args else "")
        + f"$s.WorkingDirectory='{qq(P.EXE_DIR)}';"
        + (f"$s.IconLocation='{qq(icon)},0';" if icon.exists() else "")
        + "$s.Save()"
    )
    WI.powershell(ps)
    WI.refresh_icons(WI.desktop_dir() / WI.SHORTCUT_NAME)


def relaunch_command():
    target, args = self_command()
    return f'"{target}" {args}'.strip()


def open_path(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            webbrowser.open(Path(path).resolve().as_uri())
    except Exception:
        pass


def package_status():
    out = []
    for mod, pip in (("numpy", "numpy"), ("sounddevice", "sounddevice"), ("faster_whisper", "faster-whisper"),
                     ("edge_tts", "edge-tts"), ("zstandard", "zstandard"), ("kokoro_onnx", "kokoro-onnx"), ("soundfile", "soundfile")):
        try:
            __import__(mod)
            out.append((pip, True))
        except Exception:
            out.append((pip, False))
    return out


def relaunch_elevated():
    if sys.platform != "win32":
        return False
    import ctypes
    target, params = self_command("--relaunch")
    try:
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", str(target), params, str(P.EXE_DIR), 1) > 32
    except Exception:
        return False


def models_dir():
    return P.MODELS_DIR


class App:
    TABS = [("overview", "Overview"), ("contracts", "Contracts"), ("combat", "Combat"), ("history", "History"), ("trade", "Trade"),
            ("copilot", "Co-Pilot"), ("macros", "Macros"), ("lines", "Personality"), ("controls", "Controls"), ("settings", "Settings")]
    DATA_TABS = ("overview", "contracts", "combat", "history")

    def __init__(self, root):
        self.root = root
        self.settings = load_settings()
        self.first_run = self.settings.pop("_first_run", False)
        if not self.first_run and not self.settings.get("setup_done"):
            self.settings["setup_done"] = True
        self.update_info = None
        self.migrations = []
        if MIGRATED:
            self.migrations.append("Moved your settings, logs and voice files into your Windows user folder, "
                                   "so updates never touch them.")
        if self.settings.get("stt_model") == "tiny.en" and not self.settings.get("mig_stt_base"):
            self.settings["stt_model"] = "base.en"
            self.migrations.append("Switched speech recognition from Tiny to Base so it understands you better.")
        self.settings["mig_stt_base"] = True
        if not self.settings.get("mig_weapons_hot"):
            for m in self.settings.get("macros") or []:
                if m.get("name") == "Combat ready" and "weapons hot" in m.get("phrases", []):
                    m["phrases"].remove("weapons hot")
            self.settings["mig_weapons_hot"] = True
        self.overlay_test_until = 0.0
        install = B.find_install(self.settings.get("install_dir") or None)
        self.state = L.GameState()
        self.binds = B.Binds(install)
        self.recorder = V.Recorder()
        self.recorder.device = self.settings.get("mic")
        self.transcriber = V.Transcriber(models_dir())
        self.speaker = V.Speaker(lambda: self.settings, self._speaking)
        self.kokoro = V.Kokoro(P.MODELS_DIR / "kokoro")
        self.speaker.kokoro = self.kokoro
        self.uex = T.Uex()
        self.uex_extra = T.UexExtra(self.uex)
        self.overlay = OV.Overlay(root, lambda: self.settings, B.game_window)
        self.hud = HUD.Reader(lambda: self.settings, lambda: (self.state.ship or {}).get("name", ""))
        self.hud.watch_ok = lambda: bool(self.state.running)
        self.hud.on_shields_down = lambda: self.settings.get("callouts", {}).get("combat", True) and self.callout(
            LN.line(self.settings, "target_shields_down"))
        self.hud.start_watch()
        self.nv = None
        self.overlay_diag_t = 0.0

        self.edge_voices = V.edge_voice_list(EDGE_CACHE)
        self.trade_view = None
        self.trade_busy = False
        self.macro_running = False
        self._ov_t = 0.0
        self.brain = BR.Brain(self)
        self.callouts = CO.Callouts(self)
        self.uiq = queue.Queue()
        if sys.platform == "win32":
            threading.Thread(target=self.check_nvidia, args=(True,), daemon=True).start()
        self.transcript = []
        self.listening = False
        self.thinking = False
        self.speaking_now = False
        self.capture = None
        self.capture_started = 0
        self.tab = self.settings.get("tab", "overview")
        if self.tab not in dict(self.TABS):
            self.tab = "overview"
        self.frames = {}
        self.rendered = {}
        self.last_render = {}
        self.chat = None
        self.state.listeners.append(self.on_game_event)
        self.watcher = L.LogWatcher(self.state, install, B)
        self.style_ttk()
        self.set_icon()
        self.build()
        self.watcher.start()
        self.speaker.start()
        self.ptt = V.PTTWatcher(lambda: self.settings.get("ptt"), self.ptt_down, self.ptt_up)
        self.ptt.start()
        self.load_stt()
        save_settings(self.settings)
        if self.settings.get("tts_engine") == "kokoro" and self.kokoro.installed():
            threading.Thread(target=self.kokoro.load, daemon=True, name="kokoro").start()
        if not EDGE_CACHE.exists():
            threading.Thread(target=self.refresh_edge_voices, args=(False,), daemon=True).start()
        if self.first_run:
            self.root.after(700, self.open_wizard)
        self.root.after(9000, self.auto_update_check)
        for i, msg in enumerate(self.migrations):
            self.root.after(2000 + 3800 * i, lambda m=msg: self.toast(m))
        try:
            n_clash = len(self.binds.clashes())
        except Exception:
            n_clash = 0
        if n_clash:
            self.root.after(2500 + 3800 * len(self.migrations), lambda: self.toast(
                f"{n_clash} keys the app set up clash with other game keys. Controls tab → Fix."))
        self.root.after(200, self.tick)
        self.root.after(4000, self.prewarm)
        if sys.platform == "win32":
            self.root.after(3000, self.heal_shortcut)

    def set_icon(self):
        png = P.resource("sc_copilot.png")
        ico = P.resource("sc_copilot.ico")
        if sys.platform == "win32" and ico.exists():
            try:
                self.root.iconbitmap(default=str(ico))
            except tk.TclError:
                pass
        if png.exists():
            try:
                self._icon = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._icon)
            except tk.TclError:
                pass

    def style_ttk(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("Dark.Vertical.TScrollbar", background=C["btn"], troughcolor=C["bg"], bordercolor=C["bg"],
                     arrowcolor=C["muted"], lightcolor=C["btn"], darkcolor=C["btn"], gripcount=0, arrowsize=px(12))
        st.map("Dark.Vertical.TScrollbar", background=[("pressed", C["btn_hover"]), ("active", C["btn_hover"])])
        st.configure("Dark.Horizontal.TScale", background=C["accent"], troughcolor=C["input"], bordercolor=C["card"],
                     lightcolor=C["accent"], darkcolor=C["accent"], sliderthickness=px(14), troughrelief="flat")
        st.map("Dark.Horizontal.TScale", background=[("active", C["accent_hover"])])

    def ui(self, item):
        self.uiq.put(item)

    # ------------------------------------------------------------------ layout
    def build(self):
        self.root.configure(bg=C["bg"])
        h = tk.Frame(self.root, bg=C["bar"], padx=px(20), pady=px(12))
        h.pack(fill="x")
        left = tk.Frame(h, bg=C["bar"])
        left.pack(side="left")
        tk.Label(left, text="SC Co-Pilot", font=F["brand"], fg=C["hi"], bg=C["bar"]).pack(anchor="w")
        self.sub = tk.Label(left, text="Reading your Game.log…", font=F["small"], fg=C["muted"], bg=C["bar"])
        self.sub.pack(anchor="w")
        right = tk.Frame(h, bg=C["bar"])
        right.pack(side="right")
        self.activity = tk.Label(right, text="", font=F["small_bold"], fg=C["hi"], bg=C["bar"], padx=px(10), pady=px(4))
        self.activity.pack(side="right", padx=(px(10), 0))
        self.chips = {}
        for key in ("brain", "voice", "game"):
            lb = tk.Label(right, text="", font=F["small_bold"], fg=C["muted"], bg=C["btn"], padx=px(10), pady=px(4))
            lb.pack(side="right", padx=(px(6), 0))
            self.chips[key] = lb
        tabs = tk.Frame(self.root, bg=C["bg"], padx=px(16), pady=px(8))
        tabs.pack(fill="x")
        self.tab_btns = {}
        for key, name in self.TABS:
            b = FlatButton(tabs, name, lambda k=key: self.show(k), "tab", padx=14, pady=7)
            b.pack(side="left", padx=(0, px(4)))
            self.tab_btns[key] = b
        self.body = tk.Frame(self.root, bg=C["bg"])
        self.body.pack(fill="both", expand=True, padx=px(16), pady=(0, px(14)))
        self.show(self.tab)

    def show(self, key):
        self.tab = key
        self.settings["tab"] = key
        for k, b in self.tab_btns.items():
            b.set_kind("tab_on" if k == key else "tab")
        for k, f in self.frames.items():
            f.pack_forget()
        if key not in self.frames:
            if key in self.DATA_TABS:
                f = ScrollFrame(self.body, C["bg"])
            else:
                f = tk.Frame(self.body, bg=C["bg"])
                getattr(self, "build_" + key)(f)
            self.frames[key] = f
        self.frames[key].pack(fill="both", expand=True)
        if key in self.DATA_TABS:
            self.render(key, force=True)
        elif key == "controls":
            self.refresh_controls()
        elif key == "macros":
            self.refresh_macros()
        elif key == "lines":
            self.refresh_lines()
        elif key == "trade":
            self.draw_trade_chips()

    def render(self, key, force=False):
        st = self.state
        sig = (st.version, st.loaded, len(st.history), st.running)
        now = time.time()
        if not force:
            if sig == self.rendered.get(key) and now - self.last_render.get(key, 0) < 15:
                return
            if now - self.last_render.get(key, 0) < 0.8:
                return
        self.rendered[key] = sig
        self.last_render[key] = now
        try:
            self.frames[key].swap(getattr(self, "render_" + key))
        except Exception:
            traceback.print_exc()

    def section(self, parent, title, sub=None):
        f = tk.Frame(parent, bg=C["bg"])
        f.pack(fill="x", pady=(px(4), px(8)))
        label(f, title, "h2", "hi", "bg").pack(side="left")
        if sub:
            label(f, "   " + sub, "small", "muted", "bg").pack(side="left", pady=(px(3), 0))
        return f

    def metric(self, parent, title, value, sub="", color="hi"):
        c = card(parent, padx=px(16), pady=px(12))
        label(c, title.upper(), "label", "muted").pack(anchor="w")
        label(c, value, "metric", color).pack(anchor="w", pady=(px(2), 0))
        if sub:
            label(c, sub, "small", "dim", wraplength=px(250), justify="left").pack(anchor="w")
        return c

    def empty(self, parent, title, text):
        c = card(parent, padx=px(24), pady=px(28))
        c.pack(fill="x")
        label(c, title, "h2", "hi").pack(anchor="w")
        label(c, text, "small", "muted", wraplength=px(760), justify="left").pack(anchor="w", pady=(px(6), 0))

    def rows_card(self, parent, title, rows, empty_text, cols=(12, 0)):
        c = card(parent, padx=px(18), pady=px(14))
        c.pack(fill="x", pady=(px(12), 0))
        label(c, title.upper(), "label", "muted").pack(anchor="w", pady=(0, px(6)))
        if not rows:
            label(c, empty_text, "small", "dim").pack(anchor="w")
        for left, text, color in rows:
            r = tk.Frame(c, bg=C["card"])
            r.pack(fill="x", pady=px(1))
            label(r, left, "small", "dim", width=cols[0], anchor="w").pack(side="left")
            label(r, text, "small", color or "text", anchor="w", justify="left", wraplength=px(900)).pack(side="left")
        return c

    # ------------------------------------------------------------------ data tabs
    def render_overview(self, p):
        st = self.state
        with st.lock:
            if not st.loaded:
                self.empty(p, "Reading your Game.log…", f"Looking in {self.binds.install or 'your Star Citizen folder'}.")
                return
            if st.error and not st.handle:
                self.empty(p, "Couldn't read the game log", st.error)
                return
            top = card(p, padx=px(18), pady=px(14))
            top.pack(fill="x")
            label(top, st.handle or "Pilot", "brand", "hi").pack(anchor="w")
            ship = st.ship_text()
            label(top, ship or "No ship boarded yet", "base", "accent" if ship else "dim").pack(anchor="w", pady=(px(2), 0))
            bits = []
            if st.location:
                bits.append(f"Last seen at {L.clean_place(st.location)}")
            if st.qt_target and time.time() - st.qt_target_ts < 7200:
                qs = "arrived" if st.qt_arrived_ts > st.qt_target_ts else "path obstructed" if st.qt_obstructed_ts > st.qt_target_ts else "en route / set"
                bits.append(f"QT target: {L.clean_place(st.qt_target)} ({qs})")
            bits.append(f"Star Citizen {st.game_version or '?'}" + ("" if st.running else "  ·  game not running"))
            label(top, "  ·  ".join(bits), "small", "muted", wraplength=px(1000), justify="left").pack(anchor="w", pady=(px(2), px(10)))
            zones = tk.Frame(top, bg=C["card"])
            zones.pack(anchor="w")
            if st.jurisdiction:
                danger = st.jurisdiction in ("Ungoverned", "Headhunters", "XenoThreat")
                chip(zones, st.jurisdiction.upper(), "toss" if danger else "accent", "red_bg" if danger else "blue_bg").pack(side="left", padx=(0, px(5)))
            if st.armistice is not None:
                chip(zones, "ARMISTICE" if st.armistice else "WEAPONS FREE", "good" if st.armistice else "low",
                     "green_bg" if st.armistice else "amber_bg").pack(side="left", padx=(0, px(5)))
            if st.comms_down:
                chip(zones, "COMM ARRAY DOWN", "low", "amber_bg").pack(side="left", padx=(0, px(5)))
            elif st.monitored is not None:
                chip(zones, "MONITORED" if st.monitored else "UNMONITORED", "text" if st.monitored else "low",
                     "input" if st.monitored else "amber_bg").pack(side="left", padx=(0, px(5)))
            if st.private_property:
                chip(zones, "PRIVATE PROPERTY", "low", "amber_bg").pack(side="left", padx=(0, px(5)))
            if st.party:
                chip(zones, f"PARTY: {', '.join(st.party[:4])}", "blue", "blue_bg").pack(side="left", padx=(0, px(5)))
            if not (st.jurisdiction or st.armistice is not None or st.party):
                label(zones, "Zone info shows up once you're in the verse.", "small", "dim").pack(side="left")
            grid = tk.Frame(p, bg=C["bg"])
            grid.pack(fill="x", pady=(px(12), 0))
            for i in range(4):
                grid.columnconfigure(i, weight=1, uniform="m")
            m1 = self.metric(grid, "Combat this session", f"{len(st.kills)} kills",
                             f"{len(st.losses)} ships lost · {len(st.deaths)} deaths · downed {len(st.downed)}×",
                             "accent" if st.kills else "hi")
            m1.grid(row=0, column=0, sticky="nsew", padx=(0, px(6)))
            act = st.active_contracts()
            done = sum(1 for c in st.contracts.values() if c["status"] == "complete")
            m2 = self.metric(grid, "Contracts", f"{len(act)} active" if act else "None active",
                             (act[0]["name"][:60] + (f" · now: {act[0]['current'][:40]}" if act[0].get("current") else "")) if act
                             else f"{done} completed this session", "hi" if act else "dim")
            m2.grid(row=0, column=1, sticky="nsew", padx=px(6))
            jumps = sum(1 for q in st.qt_log if q["result"] == "arrived")
            m3 = self.metric(grid, "Travel", f"{jumps} QT jumps",
                             f"last arrival {L.ago(st.qt_arrived_ts)}" if st.qt_arrived_ts else "No quantum jumps yet")
            m3.grid(row=0, column=2, sticky="nsew", padx=px(6))
            m4 = self.metric(grid, "aUEC this session", f"-{L.short_money(st.spent())}" if st.spent() else "0 spent",
                             f"{len(st.purchases)} purchases · +{L.short_money(st.received())} received")
            m4.grid(row=0, column=3, sticky="nsew", padx=(px(6), 0))
            recent = list(st.events)[-16:][::-1]
            self.rows_card(p, "Recent events", [(datetime.fromtimestamp(t).strftime("%b %d %H:%M"), x, self.event_color(x))
                                                for t, x in recent], "Nothing yet. Events show up as you play.")

    def event_color(self, x):
        if x.startswith(("You destroyed", "Contract complete", "Healed")) or "sent you" in x:
            return "good"
        if x.startswith(("Your ", "You died", "You were incap", "Contract failed", "Disconnected", "Game crashed", "CrimeStat")):
            return "toss"
        if "Ungoverned" in x or "obstructed" in x or x.startswith("Left the armistice") or "destroyed" in x:
            return "low"
        if x.startswith(("Boarded", "Quantum travel complete", "Contract accepted")):
            return "accent"
        return "text"

    def render_contracts(self, p):
        st = self.state
        with st.lock:
            act = st.active_contracts()
            ended = st.ended_contracts()
            self.section(p, "Contracts", "From this session's log. Rewards aren't logged, so they don't show here.")
            if not act and not ended:
                self.empty(p, "No contracts yet this session", "Accept a contract in your mobiGlas and it'll show up here, "
                                                                 "with its objectives ticking off as you go.")
                return
            for c in act:
                cc = card(p, padx=px(18), pady=px(14))
                cc.pack(fill="x", pady=(0, px(10)))
                row = tk.Frame(cc, bg=C["card"])
                row.pack(fill="x")
                label(row, c["name"], "h2", "hi").pack(side="left")
                label(row, f"accepted {L.hm(c['accepted'])}", "small", "dim").pack(side="right")
                if c.get("current"):
                    label(cc, f"Now: {c['current']}", "small_bold", "accent").pack(anchor="w", pady=(px(4), 0))
                for o in c["objectives"].values():
                    label(cc, ("✓  " if o["done"] else "○  ") + o["text"], "small", "good" if o["done"] else "text",
                          anchor="w").pack(anchor="w")
            if ended:
                self.rows_card(p, "Finished this session",
                               [(L.hm(c["ended"]), f"{c['status'].upper():10s} {c['name']}",
                                 "good" if c["status"] == "complete" else "toss" if c["status"] == "failed" else "dim")
                                for c in ended[:30]], "")

    def render_combat(self, p):
        st = self.state
        with st.lock:
            self.section(p, "Combat", "Ship kills and losses the game writes to your log. On-foot kills aren't logged anymore.")
            grid = tk.Frame(p, bg=C["bg"])
            grid.pack(fill="x")
            for i in range(4):
                grid.columnconfigure(i, weight=1, uniform="m")
            hist = [h for h in st.history if h["start"] and time.time() - h["start"] < 30 * 86400]
            hk = sum(len(h["kills"]) for h in hist) + len(st.kills)
            self.metric(grid, "Ship kills", str(len(st.kills)), f"{hk} in the last 30 days", "accent" if st.kills else "hi") \
                .grid(row=0, column=0, sticky="nsew", padx=(0, px(6)))
            self.metric(grid, "Ships lost", str(len(st.losses)), f"{sum(len(h['losses']) for h in hist) + len(st.losses)} in 30 days",
                        "toss" if st.losses else "hi").grid(row=0, column=1, sticky="nsew", padx=px(6))
            self.metric(grid, "Deaths", str(len(st.deaths)), f"downed {len(st.downed)}× this session",
                        "toss" if st.deaths else "hi").grid(row=0, column=2, sticky="nsew", padx=px(6))
            cs = st.crimes[-1]["change"] if st.crimes else "none"
            self.metric(grid, "CrimeStat", cs.title(), f"{len(st.crimes)} changes this session",
                        "toss" if "increase" in cs else "hi").grid(row=0, column=3, sticky="nsew", padx=(px(6), 0))
            rows = []
            for k in st.kills[::-1]:
                rows.append((L.hm(k["ts"]), f"You destroyed {L.a_an(k['victim'])} {k['victim']}" + (" (AI)" if k["ai"] else " (player ship)" if k["player_owned"] else ""), "good"))
            for k in st.losses[::-1]:
                rows.append((L.hm(k["ts"]), f"Lost your {k['victim']} ({k['reason']}, {k['killer']})", "toss"))
            for d in st.deaths[::-1]:
                rows.append((L.hm(d["ts"]), "You died" + (f" ({d['detail']})" if d["detail"] else ""), "toss"))
            rows.sort(key=lambda r: r[0], reverse=True)
            self.rows_card(p, "Your fights this session", rows, "Nothing yet. Go get 'em.")
            near = [k for k in st.destroyed if k not in st.kills and k not in st.losses][::-1][:25]
            self.rows_card(p, "Destroyed nearby", [(L.hm(k["ts"]), (f"{k['killer']} destroyed {L.a_an(k['victim'])} {k['victim']}"
                                                                     if k["reason"] != "SelfDestruct" else f"{k['victim']} self-destructed")
                                                     + (" (AI)" if k["ai"] else ""), "low" if k["killer_is_player"] else "text")
                                                    for k in near], "Nothing seen yet.")
            hk_rows = []
            for h in hist[::-1]:
                for k in h["kills"][::-1]:
                    hk_rows.append((datetime.fromtimestamp(k["ts"]).strftime("%b %d %H:%M"), f"{k['victim']}" + (" (AI)" if k["ai"] else ""), "text"))
            self.rows_card(p, "Kills in the last 30 days (earlier sessions)", hk_rows[:40], "None logged.")

    def render_history(self, p):
        st = self.state
        with st.lock:
            hist = list(st.history)
        self.section(p, "Session history", f"Your last {L.HISTORY_DAYS} days of play, read from the game's log backups.")
        if not hist:
            self.empty(p, "Reading old sessions…" if st.loaded else "Nothing yet",
                       "This fills in a few seconds after start-up the first time, then it's cached.")
            return
        grid = tk.Frame(p, bg=C["bg"])
        grid.pack(fill="x")
        for i in range(4):
            grid.columnconfigure(i, weight=1, uniform="m")
        hours = sum(max(0, h["end"] - h["start"]) for h in hist) / 3600
        self.metric(grid, "Sessions", str(len(hist)), f"{hours:.0f} hours played").grid(row=0, column=0, sticky="nsew", padx=(0, px(6)))
        self.metric(grid, "Contracts done", str(sum(len(h["contracts_done"]) for h in hist)),
                    f"{sum(len(h['contracts_failed']) for h in hist)} failed or abandoned").grid(row=0, column=1, sticky="nsew", padx=px(6))
        self.metric(grid, "aUEC spent in shops", L.short_money(sum(h["spent"] for h in hist)),
                    f"+{L.short_money(sum(h['received'] for h in hist))} sent to you").grid(row=0, column=2, sticky="nsew", padx=px(6))
        crashes = sum(1 for h in hist if h["crashed"])
        self.metric(grid, "Crashes", str(crashes), "sessions that ended in a crash", "toss" if crashes else "hi") \
            .grid(row=0, column=3, sticky="nsew", padx=(px(6), 0))
        c = card(p, padx=px(18), pady=px(14))
        c.pack(fill="x", pady=(px(12), 0))
        heads = [("DATE", 14), ("HOURS", 7), ("VERSION", 12), ("KILLS", 6), ("DEATHS", 7), ("CONTRACTS", 10), ("QT", 5),
                 ("SPENT", 8), ("SHIPS", 0)]
        hr = tk.Frame(c, bg=C["card"])
        hr.pack(fill="x", pady=(0, px(4)))
        for t, w in heads:
            label(hr, t, "label", "muted", width=w or None, anchor="w").pack(side="left")
        for h in hist[::-1]:
            r = tk.Frame(c, bg=C["card"])
            r.pack(fill="x", pady=px(1))
            vals = [datetime.fromtimestamp(h["start"]).strftime("%b %d %H:%M") if h["start"] else "?",
                    f"{max(0, h['end'] - h['start']) / 3600:.1f}", (h["version"] or "")[:11], str(len(h["kills"])), str(h["deaths"]),
                    f"{len(h['contracts_done'])}✓ {len(h['contracts_failed'])}✗", str(h["qt"]), L.short_money(h["spent"]),
                    ", ".join(h["ships"][:3]) + (" · crashed" if h["crashed"] else "")]
            for (t, w), v in zip(heads, vals):
                label(r, v, "small", "toss" if (t == "SHIPS" and h["crashed"]) else "text", width=w or None, anchor="w").pack(side="left")

    # ------------------------------------------------------------------ co-pilot tab
    def build_copilot(self, p):
        p.columnconfigure(0, weight=3)
        p.columnconfigure(1, weight=1)
        p.rowconfigure(0, weight=1)
        lc = card(p)
        lc.grid(row=0, column=0, sticky="nsew", padx=(0, px(6)))
        top = tk.Frame(lc, bg=C["card"], padx=px(14), pady=px(10))
        top.pack(fill="x")
        label(top, "CONVERSATION", "label", "muted").pack(side="left")
        FlatButton(top, "Clear", self.clear_chat, "normal", font=F["small_bold"], padx=10, pady=3).pack(side="right")
        FlatButton(top, "Status report", lambda: self.ask("Give me a quick status report."), "normal", font=F["small_bold"],
                   padx=10, pady=3).pack(side="right", padx=(0, px(6)))
        wrap = tk.Frame(lc, bg=C["card"], padx=px(14))
        wrap.pack(fill="both", expand=True)
        self.chat = tk.Text(wrap, bg=C["input"], fg=C["text"], relief="flat", bd=0, wrap="word", font=F["chat"], padx=px(12),
                            pady=px(10), highlightthickness=0, cursor="arrow", spacing1=px(2), spacing3=px(4))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.chat.yview, style="Dark.Vertical.TScrollbar")
        self.chat.configure(yscrollcommand=sb.set)
        self.chat.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, col in (("you", C["hi"]), ("copilot", C["accent"]), ("sys", C["muted"]), ("callout", C["blue"]),
                         ("tool", C["dim"]), ("action", C["good"]), ("time", C["dim"])):
            self.chat.tag_configure(tag, foreground=col)
        self.chat.tag_configure("who", font=F["small_bold"])
        self.chat.configure(state="disabled")
        for item in self.transcript:
            self._append(*item, store=False)
        bot = tk.Frame(lc, bg=C["card"], padx=px(14), pady=px(12))
        bot.pack(fill="x")
        self.talk = FlatButton(bot, "●  Hold to talk", None, "talk", padx=16, pady=8)
        self.talk.pack(side="left")
        self.talk.bind("<ButtonPress-1>", lambda e: self.ptt_down("button"))
        self.talk.bind("<ButtonRelease-1>", lambda e: self.ptt_up("button"))
        self.say_entry = entry(bot, width=40)
        self.say_entry.pack(side="left", fill="x", expand=True, padx=(px(10), px(8)), ipady=px(5))
        self.say_entry.bind("<Return>", lambda e: self.send_typed())
        FlatButton(bot, "Send", self.send_typed, "primary", padx=16, pady=7).pack(side="left")
        rc = card(p, padx=px(16), pady=px(14))
        rc.grid(row=0, column=1, sticky="nsew", padx=(px(6), 0))
        label(rc, "PUSH-TO-TALK", "label", "muted").pack(anchor="w")
        self.ptt_lbl = label(rc, self.settings.get("ptt", {}).get("name", "not set"), "h2", "accent")
        self.ptt_lbl.pack(anchor="w", pady=(px(2), px(2)))
        label(rc, "Hold it in game, talk, let go. Change it in Settings.", "small", "dim", wraplength=px(240), justify="left").pack(anchor="w")
        label(rc, "CALLOUTS", "label", "muted").pack(anchor="w", pady=(px(16), px(4)))
        self.callout_vars = {}
        for key, text in CO.CATEGORIES:
            v = tk.BooleanVar(value=self.settings["callouts"].get(key, True))
            self.callout_vars[key] = v
            cb = check(rc, text, v, self.save_callouts)
            cb.config(wraplength=px(240))
            cb.pack(anchor="w", pady=px(1))
        label(rc, "TRY SAYING", "label", "muted").pack(anchor="w", pady=(px(16), px(4)))
        for ex in ("“Drop the gear.”  “Kill the lights.”  “Guns hot.”", "“Target the biggest threat.”  “Who's shooting me?”",
                   "“Prep for takeoff.”  “Combat ready.”  “Evasive.”", "“All power to shields.”  “Pop flares.”",
                   "“Where can I refuel near me?”", "“Where do I buy a Cutlass Black in game?”", "“Where can I buy an FR-76 shield?”",
                   "“Best refinery for Quantainium?”", "“Where do I sell Hadanite near me?”"):
            label(rc, ex, "small", "text", wraplength=px(240), justify="left").pack(anchor="w", pady=px(1))
        FlatButton(rc, "Test voice", lambda: self.speaker.say(f"{self.settings.get('assistant_name', 'Co-Pilot')} online. All systems green.", True),
                   "normal", font=F["small_bold"], padx=10, pady=4).pack(anchor="w", pady=(px(16), 0))

    def _append(self, kind, text, ts=None, store=True):
        ts = ts or time.time()
        if store:
            self.transcript.append((kind, text, ts))
            self.transcript = self.transcript[-300:]
        if not self.chat:
            return
        who = {"you": "You", "copilot": self.settings.get("assistant_name", "Co-Pilot"), "sys": "•", "callout": "Callout",
               "tool": "↳", "action": "Pressed"}.get(kind, kind)
        self.chat.configure(state="normal")
        self.chat.insert("end", datetime.fromtimestamp(ts).strftime("%H:%M  "), ("time",))
        self.chat.insert("end", f"{who}  ", (kind, "who"))
        self.chat.insert("end", text + "\n", (kind,))
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def clear_chat(self):
        self.transcript = []
        self.brain.clear()
        if self.chat:
            self.chat.configure(state="normal")
            self.chat.delete("1.0", "end")
            self.chat.configure(state="disabled")

    def save_callouts(self):
        for k, v in self.callout_vars.items():
            self.settings["callouts"][k] = bool(v.get())
        save_settings(self.settings)

    def send_typed(self):
        t = self.say_entry.get().strip()
        if not t:
            return
        self.say_entry.delete(0, "end")
        cmd = Q.parse(t, self.settings.get("assistant_name", "Co-Pilot"), self.settings.get("macros")) \
            if self.settings.get("instant_commands", True) else None
        if cmd:
            self.ui(("you", t))
            threading.Thread(target=self.run_quick, args=(cmd,), daemon=True).start()
        else:
            self.ask(t)

    # ------------------------------------------------------------------ controls tab
    def build_controls(self, p):
        self.controls_frame = ScrollFrame(p, C["bg"])
        self.controls_frame.pack(fill="both", expand=True)

    def refresh_controls(self):
        if "controls" in self.frames:
            self.controls_frame.swap(self.render_controls)

    def render_controls(self, p):
        b = self.binds
        head = self.section(p, "Controls the Co-Pilot can press", "Your own keys, only when you ask.")
        FlatButton(head, "Reload keybinds", self.reload_binds, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="right")
        info = card(p, padx=px(18), pady=px(14))
        info.pack(fill="x", pady=(0, px(12)))
        if b.error:
            label(info, b.error, "small_bold", "toss", wraplength=px(900), justify="left").pack(anchor="w")
        label(info, f"Default keys from {b.source}.  Your custom binds: {b.actionmaps_file or '—'}", "small", "muted",
              wraplength=px(900), justify="left").pack(anchor="w")
        clashes = b.clashes()
        if clashes:
            label(info, f"{len(clashes)} key{'s' if len(clashes) != 1 else ''} the app set up earlier also do something else in the game:",
                  "small_bold", "toss", wraplength=px(900), justify="left").pack(anchor="w", pady=(px(6), px(2)))
            for c in clashes:
                label(info, f"•  {c['label']} is on {c['key']}, which is also: {', '.join(c['with'])}", "small", "text",
                      wraplength=px(900), justify="left").pack(anchor="w")
            label(info, "Fix moves just these to free Right Ctrl keys. Your own binds aren't touched, and actionmaps.xml is backed up "
                        "first. Close Star Citizen before you click it.", "small", "muted", wraplength=px(900), justify="left").pack(anchor="w", pady=(px(4), px(6)))
            FlatButton(info, f"Fix {len(clashes)} clashing key{'s' if len(clashes) != 1 else ''}", self.fix_clashes, "primary",
                       padx=14, pady=6).pack(anchor="w", pady=(0, px(6)))
        missing = b.missing()
        ready = sum(1 for a in B.ACTIONS if b.pressable(a[2]))
        label(info, f"{ready} of {len(B.ACTIONS)} actions have a key it can press.", "h2", "good" if not missing else "hi").pack(anchor="w", pady=(px(6), 0))
        if missing:
            label(info, "The rest are the explicit ones Star Citizen leaves unbound, like “gear down”, “lights off” or “shields on”. "
                        "Those are the best ones for voice, because the game doesn't tell outside apps whether your gear or lights are "
                        "already on, so a plain toggle can guess wrong. Auto-assign gives each a spare key (spare numpad keys first, "
                        "then Insert/Home/End and similar, then Right Ctrl + letter). It never changes a key you've set, and backs up "
                        "actionmaps.xml first. Close Star Citizen before you run it; the new keys are live next time you start the game.",
                  "small", "text", wraplength=px(900), justify="left").pack(anchor="w", pady=(px(6), px(8)))
            FlatButton(info, f"Auto-assign {len(missing)} missing keys", self.auto_assign, "primary", padx=14, pady=6).pack(anchor="w")
        group = None
        c = None
        for aid, lbl, sc, grp in B.ACTIONS:
            if grp != group:
                group = grp
                label(p, grp.upper(), "label", "muted", "bg").pack(anchor="w", pady=(px(10), px(4)))
                c = card(p, padx=px(14), pady=px(6))
                c.pack(fill="x")
                c.columnconfigure(0, minsize=px(320))
                c.columnconfigure(1, minsize=px(190))
                c.columnconfigure(2, weight=1)
            r = c.grid_size()[1]
            label(c, lbl, "small_bold", "hi", anchor="w").grid(row=r, column=0, sticky="w", pady=px(3))
            k = b.describe(sc)
            ok = b.pressable(sc)
            label(c, (k if ok else (f"{k} (won't press)" if k else "no key yet")), "small_bold" if ok else "small",
                  "accent" if ok else "low", anchor="w").grid(row=r, column=1, sticky="w")
            label(c, sc, "small", "dim", anchor="w").grid(row=r, column=2, sticky="w")
            if ok:
                FlatButton(c, "Test", lambda s=sc: self.test_press(s), "normal", font=F["tiny_bold"], padx=8, pady=2).grid(row=r, column=3, sticky="e")

    def test_press(self, sc):
        def go():
            ok, msg = self.binds.press(sc)
            self.ui(("sys", f"Test {sc}: {'pressed ' + msg if ok else msg}"))
            self.ui(("toast", f"{'Pressed ' + msg if ok else 'Not pressed: ' + msg}"))
        threading.Thread(target=go, daemon=True).start()

    def reload_binds(self):
        self.binds.load()
        self.refresh_controls()
        self.toast("Keybinds reloaded")

    def auto_assign(self):
        if B.game_process_running():
            messagebox.showwarning(APP_NAME, "Close Star Citizen first. It rewrites your keybinds file when it quits.", parent=self.root)
            return
        missing = self.binds.missing()
        if not messagebox.askyesno(APP_NAME, f"Give {len(missing)} actions a spare keyboard key?\n\nOnly unbound actions get a key, "
                                   "and actionmaps.xml is backed up first.", parent=self.root):
            return
        avoid = [V.source_sc_key(self.settings.get("ptt"))]
        try:
            assigned, skipped, backup = self.binds.auto_assign(avoid=[a for a in avoid if a])
        except Exception as ex:
            messagebox.showerror(APP_NAME, str(ex), parent=self.root)
            return
        lines = [f"{a}: {k}" for a, k in assigned]
        msg = f"Assigned {len(assigned)} keys." + (f"\nBackup: {backup.name}" if backup else "")
        if lines:
            msg += "\n\n" + "\n".join(lines[:40])
        if skipped:
            msg += "\n\nSkipped:\n" + "\n".join(f"{a} ({why})" for a, why in skipped[:15])
        msg += "\n\nStart Star Citizen and the new keys are live."
        messagebox.showinfo(APP_NAME, msg, parent=self.root)
        self.refresh_controls()

    def fix_clashes(self):
        if B.game_process_running():
            messagebox.showwarning(APP_NAME, "Close Star Citizen first. It rewrites your keybinds file when it quits.", parent=self.root)
            return
        avoid = [V.source_sc_key(self.settings.get("ptt"))]
        try:
            changed, backup = self.binds.fix_clashes(avoid=[a for a in avoid if a])
        except Exception as ex:
            messagebox.showerror(APP_NAME, str(ex), parent=self.root)
            return
        if not changed:
            self.toast("Nothing to fix.")
        else:
            lines = "\n".join(f"{lbl}: {old} → {new}" for lbl, old, new in changed)
            messagebox.showinfo(APP_NAME, f"Moved {len(changed)} keys:\n\n{lines}\n\nBackup: {backup.name}\n\nStart Star Citizen and they're live.",
                                parent=self.root)
        self.refresh_controls()

    # ------------------------------------------------------------------ settings tab
    def build_settings(self, p):
        sf = ScrollFrame(p, C["bg"])
        sf.pack(fill="both", expand=True)
        sf.swap(self.render_settings)
        self.settings_frame = sf

    def srow(self, parent, title, sub=None):
        r = tk.Frame(parent, bg=C["card"])
        r.pack(fill="x", pady=px(6))
        r.columnconfigure(0, minsize=px(250))
        r.columnconfigure(1, weight=1)
        lt = tk.Frame(r, bg=C["card"])
        lt.grid(row=0, column=0, sticky="nw")
        label(lt, title, "small_bold", "hi", anchor="w").pack(anchor="w")
        if sub:
            label(lt, sub, "small", "dim", anchor="w", wraplength=px(230), justify="left").pack(anchor="w")
        rt = tk.Frame(r, bg=C["card"])
        rt.grid(row=0, column=1, sticky="nw")
        return rt

    def scard(self, p, title):
        label(p, title.upper(), "label", "muted", "bg").pack(anchor="w", pady=(px(10), px(4)))
        c = card(p, padx=px(18), pady=px(10))
        c.pack(fill="x")
        return c

    def set_and_save(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)

    def render_settings(self, p):
        s = self.settings
        c = self.scard(p, "AI co-pilot")
        rt = self.srow(c, "AI mode", "Instant voice commands, callouts and the overlay work in every mode. The AI answers "
                                     "questions and handles anything that isn't an instant command.")
        chooser(rt, self.ai_mode_choices(), self.brain.mode(), self.set_ai_mode, 34).pack(side="left")
        mode = self.brain.mode()
        self.key_entry = None
        if mode == "own_key":
            rt = self.srow(c, "API key", "From platform.claude.com. You pay Anthropic per question (about a tenth of a cent with Haiku).")
            self.key_entry = entry(rt, width=44, show="•")
            self.key_entry.insert(0, s.get("api_key", ""))
            self.key_entry.pack(side="left", ipady=px(3))
            self.key_shown = False

            def toggle():
                self.key_shown = not self.key_shown
                self.key_entry.config(show="" if self.key_shown else "•")
            FlatButton(rt, "Show", toggle, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(6), 0))
            FlatButton(rt, "Save", lambda: (self.set_and_save("api_key", self.key_entry.get().strip()), self.toast("API key saved")),
                       "primary", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(6), 0))
            FlatButton(rt, "Test", self.test_api, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(6), 0))
            FlatButton(rt, "Get a key", lambda: webbrowser.open("https://platform.claude.com/"), "ghost", font=F["small_bold"],
                       padx=10, pady=4).pack(side="left", padx=(px(6), 0))
            rt = self.srow(c, "Model", "Haiku answers fastest, which matters for voice.")
            chooser(rt, BR.MODELS, s.get("model"), lambda v: self.set_and_save("model", v), 34).pack(side="left")
        elif mode == "service":
            if VER.SERVICE_URL:
                rt = self.srow(c, "Subscription key", "The key from your Co-Pilot subscription email.")
                self.key_entry = entry(rt, width=44, show="•")
                self.key_entry.insert(0, s.get("license_key", ""))
                self.key_entry.pack(side="left", ipady=px(3))
                FlatButton(rt, "Save", lambda: (self.set_and_save("license_key", self.key_entry.get().strip()), self.toast("Key saved")),
                           "primary", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(6), 0))
                FlatButton(rt, "Test", self.test_api, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(6), 0))
                if VER.STORE_URL:
                    FlatButton(rt, "Get a subscription", lambda: webbrowser.open(VER.STORE_URL), "ghost", font=F["small_bold"],
                               padx=10, pady=4).pack(side="left", padx=(px(6), 0))
            else:
                label(c, "Coming soon: a monthly Co-Pilot subscription, so you won't need your own API key. Until it opens, "
                         "use your own key or leave the AI off.", "small", "low", wraplength=px(900), justify="left").pack(anchor="w", pady=(0, px(6)))
        if mode == "off":
            label(c, "The AI is off. Instant commands like “gear down”, macros, callouts, the overlay and the trade tab all still work.",
                  "small", "muted", wraplength=px(900), justify="left").pack(anchor="w", pady=(0, px(6)))
        rt = self.srow(c, "Web lookups", "Lets it search the web for patch-dependent stuff (prices, where to buy, current meta). About a cent per search.")
        v = tk.BooleanVar(value=s.get("web_lookups", True))
        check(rt, "Allow web search", v, lambda v=v: (self.set_and_save("web_lookups", bool(v.get())), setattr(self.brain, "web_ok", True))).pack(anchor="w")
        rt = self.srow(c, "About you", "Anything it should always know: your ships, what you do, where you're based.")
        ne = entry(rt, width=70)
        ne.insert(0, s.get("pilot_notes", ""))
        ne.pack(side="left", ipady=px(3))
        save_n = lambda e=None: self.set_and_save("pilot_notes", ne.get().strip())
        ne.bind("<FocusOut>", save_n)
        ne.bind("<Return>", save_n)

        c = self.scard(p, "Voice")
        rt = self.srow(c, "Co-pilot name", "What it calls itself. Saying it in a command is fine, it gets ignored.")
        ae = entry(rt, width=20)
        ae.insert(0, s.get("assistant_name", "Co-Pilot"))
        ae.pack(side="left", ipady=px(3))
        ae.bind("<FocusOut>", lambda e: self.set_and_save("assistant_name", ae.get().strip() or "Co-Pilot"))
        ae.bind("<Return>", lambda e: self.set_and_save("assistant_name", ae.get().strip() or "Co-Pilot"))
        rt = self.srow(c, "Voice engine", "Kokoro sounds the most natural and runs on your PC. Microsoft needs internet. Windows is instant but robotic.")
        chooser(rt, self.engine_choices(), s.get("tts_engine"), self.set_engine, 34).pack(side="left")
        rt = self.srow(c, "Kokoro voice", "Free and offline. ★ = the best-sounding ones.")
        if not self.kokoro_available():
            label(rt, "Not included in the installer version yet. The Microsoft voices are the next best.", "small", "dim").pack(side="left")
        elif self.kokoro.installed():
            chooser(rt, self.kokoro.voices(), s.get("kokoro_voice", V.KOKORO_DEFAULT),
                    lambda v: (self.set_and_save("kokoro_voice", v), self.preview_voice()), 30).pack(side="left")
            label(rt, f"  {self.kokoro.status if self.kokoro.package_ok() else 'run Install.bat to add kokoro-onnx'}", "small", "dim").pack(side="left")
        else:
            self.kokoro_btn = FlatButton(rt, "Download Kokoro voices (~350 MB)", self.download_kokoro, "primary", font=F["small_bold"], padx=10, pady=4)
            self.kokoro_btn.pack(side="left")
            self.kokoro_lbl = label(rt, "  One-time download from GitHub. Then pick it as the engine.", "small", "dim")
            self.kokoro_lbl.pack(side="left")
        rt = self.srow(c, "Microsoft voice", f"{len(self.edge_voices)} English voices.")
        chooser(rt, self.edge_voices, s.get("voice"), lambda v: (self.set_and_save("voice", v), self.preview_voice()), 34).pack(side="left")
        FlatButton(rt, "Refresh list", lambda: threading.Thread(target=self.refresh_edge_voices, daemon=True).start(), "normal",
                   font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(8), 0))
        rt = self.srow(c, "Voice effect", "How it sounds: through your ship or helmet, deep and dark, or in an echo chamber. Works with Kokoro and Microsoft voices.")
        chooser(rt, FX.PRESETS, s.get("voice_fx", "computer"), lambda v: (self.set_and_save("voice_fx", v), self.preview_voice()), 26).pack(side="left")
        FlatButton(rt, "Test voice", self.preview_voice, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(8), 0))
        rt = self.srow(c, "Effect amount")
        slider(rt, 0, 100, s.get("voice_fx_amount", 100), lambda v: self.set_and_save("voice_fx_amount", int(float(v)))).pack(side="left")
        rt = self.srow(c, "Pitch", "Lower is deeper, higher is lighter. Works with any effect, even Off. Not for the Windows voices.")
        slider(rt, FX.PITCH_RANGE[0], FX.PITCH_RANGE[1], s.get("voice_pitch", 0),
               lambda v: self.set_and_save("voice_pitch", int(float(v)))).pack(side="left")
        FlatButton(rt, "Test", self.preview_voice, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(8), 0))
        rt = self.srow(c, "Speed")
        slider(rt, -30, 30, s.get("tts_rate", 0), lambda v: self.set_and_save("tts_rate", int(float(v)))).pack(side="left")
        rt = self.srow(c, "Volume")
        slider(rt, 0, 100, s.get("volume", 90), lambda v: self.set_and_save("volume", int(float(v)))).pack(side="left")
        rt = self.srow(c, "Options")
        for key, text in (("speak_answers", "Speak answers out loud"),
                          ("instant_commands", "Instant commands: simple controls and macros run on your PC with no Claude delay"),
                          ("chirps", "Chirp when listening starts and stops")):
            bv = tk.BooleanVar(value=s.get(key, True))
            check(rt, text, bv, lambda k=key, bv=bv: self.set_and_save(k, bool(bv.get()))).pack(anchor="w")

        c = self.scard(p, "Push-to-talk and speech recognition")
        rt = self.srow(c, "Push-to-talk", "Any key, mouse button, controller or joystick button.")
        self.ptt_set_lbl = label(rt, s.get("ptt", {}).get("name", "not set"), "h2", "accent")
        self.ptt_set_lbl.pack(side="left")
        self.ptt_btn = FlatButton(rt, "Change", self.start_capture, "normal", font=F["small_bold"], padx=10, pady=4)
        self.ptt_btn.pack(side="left", padx=(px(10), 0))
        self.ptt_hint = label(c, self.ptt_warning(), "small", "low", wraplength=px(760), justify="left")
        self.ptt_hint.pack(anchor="w")
        rt = self.srow(c, "Microphone")
        devs = [(None, "System default")] + V.input_devices()
        chooser(rt, devs, s.get("mic"), self.set_mic, 40).pack(side="left")
        rt = self.srow(c, "Speech model", "Runs on your PC. Downloads once (75–480 MB).")
        chooser(rt, STT_MODELS, s.get("stt_model"), lambda v: (self.set_and_save("stt_model", v), self.load_stt()), 30).pack(side="left")
        rt = self.srow(c, "Run speech model on")
        chooser(rt, STT_DEVICES, s.get("stt_device"), lambda v: (self.set_and_save("stt_device", v), self.load_stt()), 30).pack(side="left")
        self.stt_lbl = label(c, f"Speech model: {self.transcriber.status}", "small", "muted")
        self.stt_lbl.pack(anchor="w", pady=(px(4), 0))

        c = self.scard(p, "In-game overlay")
        label(c, "A small see-through panel on top of the game: zone, current objective, quantum status and the last callout. "
                 "Your mouse clicks go straight through it. You can also say “overlay on” / “overlay off”.",
              "small", "text", wraplength=px(900), justify="left").pack(anchor="w", pady=(px(4), px(4)))
        label(c, "If it vanishes when you click into the game: (1) in Star Citizen set Graphics → Window Mode to Borderless, and "
                 "(2) in NVIDIA Control Panel → Manage 3D settings → Program Settings → add StarCitizen.exe → set "
                 "“Vulkan/OpenGL present method” to “Prefer layered on DXGI Swapchain” → Apply, then restart the game. "
                 "Star Citizen runs on Vulkan, and without that setting the driver takes over the whole screen when the game "
                 "has focus, which hides every other window.",
              "small", "low", wraplength=px(900), justify="left").pack(anchor="w", pady=(0, px(6)))
        rt = self.srow(c, "Overlay")
        ov = tk.BooleanVar(value=s.get("overlay_on", False))
        check(rt, "Show the overlay", ov, lambda: self.set_and_save("overlay_on", bool(ov.get()))).pack(anchor="w")
        og = tk.BooleanVar(value=s.get("overlay_only_in_game", True))
        check(rt, "Only while Star Citizen is running", og, lambda: self.set_and_save("overlay_only_in_game", bool(og.get()))).pack(anchor="w")
        FlatButton(rt, "Show it for 20 seconds (test)", self.test_overlay, "normal", font=F["small_bold"], padx=10, pady=4).pack(anchor="w", pady=(px(4), 0))
        rt = self.srow(c, "NVIDIA setting", "Checked straight from your graphics driver.")
        text, tone = self.nvidia_text()
        label(rt, text, "small", tone, wraplength=px(620), justify="left").pack(anchor="w")
        btns = tk.Frame(rt, bg=rt["bg"])
        btns.pack(anchor="w", pady=(px(4), 0))
        if self.nv and self.nv.get("ok") and not self.nv.get("good"):
            FlatButton(btns, "Fix it", self.fix_nvidia, "primary", font=F["small_bold"], padx=12, pady=4).pack(side="left", padx=(0, px(6)))
        FlatButton(btns, "Check again", lambda: threading.Thread(target=self.check_nvidia, args=(True,), daemon=True).start(), "normal",
                   font=F["small_bold"], padx=10, pady=4).pack(side="left")
        rt = self.srow(c, "Position")
        chooser(rt, OV.CORNERS, s.get("overlay_corner", "top_right"), lambda v: self.set_and_save("overlay_corner", v), 20).pack(side="left")
        rt = self.srow(c, "Size")
        slider(rt, 70, 160, s.get("overlay_scale", 100), lambda v: self.set_and_save("overlay_scale", int(float(v)))).pack(side="left")
        rt = self.srow(c, "Opacity")
        slider(rt, 30, 100, s.get("overlay_opacity", 82), lambda v: self.set_and_save("overlay_opacity", int(float(v)))).pack(side="left")
        rt = self.srow(c, "Show callouts for", "Seconds a spoken callout stays on the overlay.")
        slider(rt, 3, 20, s.get("overlay_callout_secs", 8), lambda v: self.set_and_save("overlay_callout_secs", int(float(v)))).pack(side="left")

        c = self.scard(p, "Star Citizen folder and app")
        rt = self.srow(c, "LIVE folder", "Leave blank to find it automatically.")
        je = entry(rt, width=60)
        je.insert(0, s.get("install_dir", ""))
        je.pack(side="left", ipady=px(3))

        def browse():
            d = filedialog.askdirectory(parent=self.root, initialdir=str(self.binds.install or Path.home()))
            if d:
                je.delete(0, "end")
                je.insert(0, d)
                self.set_and_save("install_dir", d)
                self.toast("Saved. Restart SC Co-Pilot to use the new folder.")
        FlatButton(rt, "Browse", browse, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(6), 0))
        label(c, f"Using: {self.binds.install or 'not found'}", "small", "dim").pack(anchor="w")
        rt = self.srow(c, "App")
        if not P.FROZEN:
            FlatButton(rt, "Make desktop shortcut", self.make_shortcut, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(0, px(6)))
        if not B.self_elevated():
            FlatButton(rt, "Restart as administrator", self.restart_admin, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(0, px(6)))
        FlatButton(rt, "Open settings folder", lambda: open_path(P.DATA_DIR), "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(0, px(6)))
        FlatButton(rt, "Open log", lambda: open_path(LOG_FILE) if LOG_FILE.exists() else self.toast("No log yet"), "normal",
                   font=F["small_bold"], padx=10, pady=4).pack(side="left")
        rt = self.srow(c, "Administrator", "Only needed if Star Citizen runs as administrator. Windows blocks keypresses from a normal app into an admin one.")
        av = tk.BooleanVar(value=s.get("run_as_admin", False))
        check(rt, "Always start SC Co-Pilot as administrator (Windows asks each time)", av,
              lambda: self.set_and_save("run_as_admin", bool(av.get()))).pack(anchor="w")
        ga = B.game_elevated()
        label(rt, ("SC Co-Pilot is running as administrator." if B.self_elevated() else "SC Co-Pilot is running normally.")
              + ("  Star Citizen is running as administrator." if ga else "  Star Citizen is running normally." if ga is False else ""),
              "small", "toss" if B.admin_mismatch() else "dim").pack(anchor="w")
        if not P.FROZEN:
            pk = package_status()
            miss = [n for n, ok in pk if not ok]
            txt = "Packages: " + "   ".join(f"{n} {'✓' if ok else '✗'}" for n, ok in pk)
            if miss:
                txt += "\nSome are missing. Close this app, run Install.bat, then start it again. The dashboard works without them."
            label(c, txt, "small", "low" if miss else "good", justify="left").pack(anchor="w", pady=(px(8), 0))
        self.render_hud_card(p)
        self.render_about(p)

    def render_hud_card(self, p):
        s = self.settings
        c = self.scard(p, "Target reader (beta)")
        label(c, "Reads your locked target's shield and hull off the HUD, so you can ask “are his shields down?”, “how's his hull?” "
                 "or “target status”. It only looks at the two small boxes you draw. Nothing is saved or sent anywhere.",
              "small", "text", wraplength=px(900), justify="left").pack(anchor="w", pady=(px(4), px(4)))
        profs = s.get("hud_profiles") or {}
        ship = (self.state.ship or {}).get("name", "")
        rt = self.srow(c, "Setup", "Lock a target with full shields, click Capture, and switch to the game.")
        names = ["any ship" if k == "default" else k for k in profs]
        label(rt, ("Set up for: " + ", ".join(names)) if names else "Not set up yet.", "small_bold", "good" if names else "low").pack(anchor="w")
        row = tk.Frame(rt, bg=rt["bg"])
        row.pack(anchor="w", pady=(px(4), 0))
        FlatButton(row, "Capture in 5 seconds", lambda: self.hud_capture(5), "primary", font=F["small_bold"], padx=12, pady=4).pack(side="left", padx=(0, px(6)))
        if profs:
            FlatButton(row, "Read it now (3 s)", self.hud_test, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(0, px(6)))
            FlatButton(row, "Remove setup", self.hud_remove, "ghost", font=F["small_bold"], padx=10, pady=4).pack(side="left")
        label(rt, f"Setup saves for the ship you're in now ({ship or 'unknown, so it applies to any ship'}). Each ship or seat can have "
                  "its own boxes. Works best in space; a bright planet behind the HUD can throw it off.", "small", "dim",
              wraplength=px(620), justify="left").pack(anchor="w", pady=(px(4), 0))
        rt = self.srow(c, "Callout")
        hv = tk.BooleanVar(value=s.get("hud_watch", False))
        check(rt, "Say when the target's shields drop", hv, lambda: self.set_and_save("hud_watch", bool(hv.get()))).pack(anchor="w")

    def hud_capture(self, delay=5):
        if not HUD.WIN:
            self.toast("The target reader only works on Windows.")
            return
        self.toast(f"Switch to Star Citizen now and keep a target locked with full shields. Capturing in {delay} seconds…")

        def go():
            time.sleep(delay)
            mon = OV.monitor_rect(B.game_window())
            if not mon:
                import ctypes
                mon = (0, 0, ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1))
            l, t, r, b = mon
            try:
                img = HUD.capture((l, t, r - l, b - t))
            except Exception as ex:
                img = None
                print(f"[{time.strftime('%H:%M:%S')}] hud capture failed: {ex}", flush=True)
            self.ui(("call", lambda: self.open_hud_setup(img, (l, t)) if img is not None else self.toast("Couldn't capture the screen.")))
        threading.Thread(target=go, daemon=True).start()

    def hud_test(self):
        self.toast("Reading in 3 seconds. Switch to the game with a target locked.")

        def go():
            time.sleep(3)
            r = self.hud.read()
            self.ui(("toast", r.get("text", "No reading.")))
            self.speaker.say(r.get("text", ""), priority=True)
        threading.Thread(target=go, daemon=True).start()

    def hud_remove(self):
        profs = dict(self.settings.get("hud_profiles") or {})
        ship = (self.state.ship or {}).get("name", "")
        key = ship if ship in profs else "default" if "default" in profs else next(iter(profs), None)
        if key and messagebox.askyesno(APP_NAME, f"Remove the target reader setup for {'any ship' if key == 'default' else key}?", parent=self.root):
            profs.pop(key, None)
            self.set_and_save("hud_profiles", profs)
            self.uiq.put(("rerender_settings", None))

    def open_hud_setup(self, img, origin):
        import base64
        import struct
        import zlib
        import numpy as np
        h, w = img.shape[:2]
        step = max(1, int(np.ceil(max(w / px(1100), h / px(600)))))
        small = np.ascontiguousarray(img[::step, ::step])
        sh, sw = small.shape[:2]
        raw = b"".join(b"\x00" + small[y].tobytes() for y in range(sh))

        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", sw, sh, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))
        win = tk.Toplevel(self.root)
        win.title("Target reader setup")
        win.configure(bg=C["bg"])
        win.transient(self.root)
        photo = tk.PhotoImage(data=base64.b64encode(png))
        win._photo = photo
        top = label(win, "", "base", "hi", "bg", wraplength=sw, justify="left")
        top.pack(anchor="w", padx=px(12), pady=(px(10), px(4)))
        cv = tk.Canvas(win, width=sw, height=sh, bg="black", highlightthickness=0, cursor="crosshair")
        cv.pack(padx=px(12))
        cv.create_image(0, 0, image=photo, anchor="nw")
        info = label(win, "", "small", "muted", "bg", wraplength=sw, justify="left")
        info.pack(anchor="w", padx=px(12), pady=px(4))
        nav = tk.Frame(win, bg=C["bg"])
        nav.pack(fill="x", padx=px(12), pady=(0, px(12)))
        st = {"step": "shield", "start": None, "rect_id": None, "box": None, "result": {}}
        steps = {"shield": ("Step 1 of 2: drag a box tightly around the target's SHIELD display.", "color"),
                 "hull": ("Step 2 of 2: drag a box tightly around the target's HULL display.", "any")}
        nxt = FlatButton(nav, "Next", lambda: advance(), "primary", font=F["small_bold"], padx=12, pady=4)
        skip = FlatButton(nav, "Skip hull", lambda: finish(), "ghost", font=F["small_bold"], padx=10, pady=4)
        FlatButton(nav, "Cancel", win.destroy, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left")
        nxt.pack(side="right")

        def show_step():
            top.config(text=steps[st["step"]][0])
            info.config(text="Click and drag on the picture. You can redraw it as many times as you like.", fg=C["muted"])
            nxt.config(state="disabled", text="Next" if st["step"] == "shield" else "Save")
            if st["step"] == "hull":
                skip.pack(side="right", padx=(0, px(8)))

        def press(e):
            st["start"] = (e.x, e.y)
            if st["rect_id"]:
                cv.delete(st["rect_id"])
            st["rect_id"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline=C["accent"], width=2)

        def drag(e):
            if st["start"] and st["rect_id"]:
                cv.coords(st["rect_id"], st["start"][0], st["start"][1], e.x, e.y)

        def release(e):
            if not st["start"]:
                return
            x0, y0 = st["start"]
            x1, y1 = min(max(e.x, 0), sw), min(max(e.y, 0), sh)
            st["start"] = None
            bx, by, bw, bh = min(x0, x1) * step, min(y0, y1) * step, abs(x1 - x0) * step, abs(y1 - y0) * step
            if bw < 6 or bh < 6:
                info.config(text="That box is too small. Drag a bigger one.", fg=C["toss"])
                return
            crop = img[by:by + bh, bx:bx + bw]
            try:
                cal = HUD.calibrate_region(crop, steps[st["step"]][1])
            except ValueError as ex:
                info.config(text=str(ex), fg=C["toss"])
                nxt.config(state="disabled")
                return
            st["result"][st["step"]] = {"rect": [origin[0] + bx, origin[1] + by, bw, bh], "cal": cal}
            what = "shield display" if st["step"] == "shield" else "hull display"
            info.config(text=f"✓ Got the {what} ({cal['full']} lit pixels counted as full). Click {'Next' if st['step'] == 'shield' else 'Save'}.",
                        fg=C["good"])
            nxt.config(state="normal")

        def advance():
            if st["step"] == "shield":
                st["step"] = "hull"
                if st["rect_id"]:
                    cv.delete(st["rect_id"])
                    st["rect_id"] = None
                show_step()
            else:
                finish()

        def finish():
            if "shield" not in st["result"]:
                return
            ship = (self.state.ship or {}).get("name", "") or "default"
            profs = dict(self.settings.get("hud_profiles") or {})
            profs[ship] = dict(st["result"])
            profs.setdefault("default", dict(st["result"]))
            self.set_and_save("hud_profiles", profs)
            win.destroy()
            self.uiq.put(("rerender_settings", None))
            self.toast("Target reader is set up. Try saying “target status”.")
        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", drag)
        cv.bind("<ButtonRelease-1>", release)
        show_step()
        win.update_idletasks()
        win.geometry(f"+{self.root.winfo_rootx() + px(20)}+{self.root.winfo_rooty() + px(20)}")

    def render_about(self, p):
        s = self.settings
        c = self.scard(p, "About")
        label(c, f"{APP_NAME} {VER.VERSION}", "h2", "hi").pack(anchor="w", pady=(px(4), px(2)))
        rt = self.srow(c, "Updates")
        if self.update_info:
            label(rt, f"Version {self.update_info['tag'].lstrip('v')} is out.", "small_bold", "good").pack(anchor="w")
            row = tk.Frame(rt, bg=rt["bg"])
            row.pack(anchor="w", pady=(px(4), 0))
            FlatButton(row, "Install update", self.install_update, "primary", font=F["small_bold"], padx=12, pady=4).pack(side="left", padx=(0, px(6)))
            FlatButton(row, "What's new", lambda: webbrowser.open(self.update_info["url"]), "normal", font=F["small_bold"],
                       padx=10, pady=4).pack(side="left")
        else:
            FlatButton(rt, "Check for updates", self.check_updates_now, "normal", font=F["small_bold"], padx=10, pady=4).pack(anchor="w")
        uv = tk.BooleanVar(value=s.get("check_updates", True))
        check(rt, "Check for updates automatically", uv, lambda: self.set_and_save("check_updates", bool(uv.get()))).pack(anchor="w", pady=(px(4), 0))
        rt = self.srow(c, "Help")
        for text, fn in (("Report a problem", lambda: webbrowser.open(VER.ISSUES_URL)), ("Copy diagnostics", self.copy_diagnostics),
                         ("Open logs folder", lambda: open_path(P.LOG_DIR)), ("Run setup again", self.open_wizard)):
            FlatButton(rt, text, fn, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(0, px(6)))
        rt = self.srow(c, "Legal")
        for text, name in (("License", "LICENSE.txt"), ("Credits & licenses", "THIRD_PARTY_NOTICES.md"), ("Privacy", "PRIVACY.md")):
            FlatButton(rt, text, lambda n=name: open_path(P.resource("legal") / n), "normal", font=F["small_bold"],
                       padx=10, pady=4).pack(side="left", padx=(0, px(6)))
        label(c, VER.DISCLAIMER, "small", "dim", wraplength=px(900), justify="left").pack(anchor="w", pady=(px(8), px(2)))

    def ptt_warning(self):
        src = self.settings.get("ptt") or {}
        if src.get("kind") == "pad":
            if src.get("mask") == 0x0400:
                return "The Xbox button works if Xbox Game Bar isn't grabbing it (Windows Settings → Gaming → Game Bar)."
            return "Heads up: Star Citizen still sees this controller button and does whatever it's bound to there."
        k = V.source_sc_key(src)
        if k and k in self.binds.used:
            return f"Heads up: Star Citizen also uses {src.get('name')} for something, so it'll fire in game too. A spare key is better."
        return ""

    def set_mic(self, v):
        self.settings["mic"] = v
        self.recorder.device = v
        save_settings(self.settings)

    def start_capture(self):
        self.capture = V.Capture()
        self.capture_started = time.time()
        self.ptt.paused = True
        self.ptt_set_lbl.config(text="Press it now…", fg=C["hi"])

    def finish_capture(self, spec):
        self.capture = None
        self.ptt.paused = False
        if spec:
            self.settings["ptt"] = spec
            save_settings(self.settings)
        name = self.settings.get("ptt", {}).get("name", "not set")
        self.ptt_set_lbl.config(text=name, fg=C["accent"])
        if self.chat:
            self.ptt_lbl.config(text=name)
        self.ptt_hint.config(text=self.ptt_warning())

    def test_overlay(self):
        self.overlay_test_until = time.time() + 20
        threading.Thread(target=lambda: print(f"[{time.strftime('%H:%M:%S')}] overlay-test nvidia {self.check_nvidia()}", flush=True),
                         daemon=True).start()
        self.overlay.set_callout("Overlay test. Click into the game and see if I stay on top.")
        self.toast("Overlay showing for 20 seconds. Click into Star Citizen and check it stays visible.")

    def check_nvidia(self, rerender=False):
        self.nv = NV.check()
        if rerender:
            self.uiq.put(("rerender_settings", None))
        return self.nv

    def nvidia_text(self):
        nv = self.nv
        if nv is None:
            return "Checking your NVIDIA setting for Star Citizen…", "muted"
        if not nv.get("ok"):
            return f"Couldn't read your NVIDIA settings ({nv.get('error')}). Set it by hand with the steps above.", "low"
        where = f"profile “{nv['profile']}”" if nv.get("profile") else "no Star Citizen profile"
        if nv["good"]:
            return (f"✓ NVIDIA is set to “{nv['name']}” for Star Citizen ({where}). If the overlay still hides, "
                    f"run the test and click Open log.", "good")
        return (f"✗ NVIDIA is set to “{nv['name']}” for Star Citizen (coming from {nv['from']}, {where}). That's why the overlay "
                f"vanishes. Click Fix it, then restart Star Citizen.", "toss")

    def fix_nvidia(self):
        def work():
            result = NV.fix()
            if result == "admin":
                out = P.cache("sc_nvfix_result.json")
                try:
                    out.unlink()
                except OSError:
                    pass
                import ctypes
                target, params = self_command("--nvfix", str(out))
                ok = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(target), params, str(P.EXE_DIR), 0) > 32
                if not ok:
                    self.uiq.put(("toast", "Windows didn't allow it. Set it by hand in NVIDIA Control Panel."))
                    return
                for _ in range(120):
                    time.sleep(0.5)
                    if out.exists():
                        try:
                            result = json.loads(out.read_text(encoding="utf-8")).get("result", "failed")
                        except (OSError, ValueError):
                            continue
                        break
                else:
                    result = "timed out waiting for the admin helper"
            self.check_nvidia(rerender=True)
            if result == "ok" and self.nv and self.nv.get("good"):
                self.uiq.put(("toast", "Fixed. Now fully close Star Citizen and start it again."))
            else:
                self.uiq.put(("toast", f"Couldn't change it: {result}"))
        threading.Thread(target=work, daemon=True).start()

    def restart_admin(self):
        if relaunch_elevated():
            self.on_close()
        else:
            self.toast("Didn't get administrator rights (the Windows prompt was cancelled).")

    def heal_shortcut(self):
        def work():
            try:
                print(f"[icon] desktop shortcut: {WI.heal_desktop_shortcut()}", flush=True)
            except Exception as e:
                print(f"[icon] desktop shortcut: couldn't update ({e})", flush=True)
        threading.Thread(target=work, daemon=True).start()

    def make_shortcut(self):
        try:
            create_desktop_shortcut()
            self.toast("Desktop shortcut made")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Couldn't make the shortcut:\n{e}", parent=self.root)

    # ------------------------------------------------------------------ first-run setup
    WIZ_STEPS = ("welcome", "game", "talk", "ai", "voice", "ingame", "done")

    def open_wizard(self):
        w = getattr(self, "wiz", None)
        if w is not None and w.winfo_exists():
            w.lift()
            return
        w = tk.Toplevel(self.root)
        self.wiz = w
        w.title(f"Set up {APP_NAME}")
        w.configure(bg=C["bg"])
        w.transient(self.root)
        if getattr(self, "_icon", None) is not None:
            try:
                w.iconphoto(False, self._icon)
            except tk.TclError:
                pass
        W, H = px(780), px(580)
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - W) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - H) // 3)
        w.geometry(f"{W}x{H}+{x}+{y}")
        w.minsize(W, H)
        w.protocol("WM_DELETE_WINDOW", lambda: self.close_wizard(skipped=True))
        top = tk.Frame(w, bg=C["bg"])
        top.pack(fill="x", padx=px(24), pady=(px(18), px(6)))
        self.wiz_step_lbl = label(top, "", "label", "muted", "bg")
        self.wiz_step_lbl.pack(anchor="w")
        nav = tk.Frame(w, bg=C["bg"])
        nav.pack(side="bottom", fill="x", padx=px(24), pady=px(16))
        self.wiz_body = card(w, padx=px(22), pady=px(16))
        self.wiz_body.pack(fill="both", expand=True, padx=px(24))
        self.wiz_back = FlatButton(nav, "Back", lambda: self.wiz_go(-1), "normal")
        self.wiz_back.pack(side="left")
        self.wiz_next = FlatButton(nav, "Next", lambda: self.wiz_go(1), "primary")
        self.wiz_next.pack(side="right")
        self.wiz_skip = FlatButton(nav, "Skip setup", lambda: self.close_wizard(skipped=True), "ghost")
        self.wiz_skip.pack(side="right", padx=(0, px(8)))
        self.wiz_i = 0
        self.wiz_leave = None
        self.wiz_render()

    def wiz_render(self):
        for ch in self.wiz_body.winfo_children():
            ch.destroy()
        self.wiz_leave = None
        n = len(self.WIZ_STEPS)
        step = self.WIZ_STEPS[self.wiz_i]
        getattr(self, f"wiz_{step}")(self.wiz_body)
        self.wiz_step_lbl.config(text=f"SETUP  ·  STEP {self.wiz_i + 1} OF {n}")
        self.wiz_back.config(state="normal" if self.wiz_i else "disabled")
        self.wiz_next.config(text="Get started" if self.wiz_i == 0 else "Finish" if self.wiz_i == n - 1 else "Next")
        if self.wiz_i == n - 1:
            self.wiz_skip.pack_forget()

    def wiz_go(self, d):
        if self.wiz_leave:
            self.wiz_leave()
        i = self.wiz_i + d
        if i >= len(self.WIZ_STEPS):
            self.close_wizard(skipped=False)
            return
        self.wiz_i = max(0, i)
        self.wiz_render()

    def close_wizard(self, skipped):
        if self.wiz_leave:
            try:
                self.wiz_leave()
            except Exception:
                pass
        self.settings["setup_done"] = True
        save_settings(self.settings)
        try:
            self.wiz.destroy()
        except (tk.TclError, AttributeError):
            pass
        self.uiq.put(("rerender_settings", None))
        if skipped:
            self.toast("Setup skipped. You can run it any time from Settings → About.")
        else:
            self.toast("All set. Hold your push-to-talk button and try “gear down”.")

    def wiz_h(self, b, title, text=""):
        label(b, title, "h2", "hi").pack(anchor="w", pady=(0, px(8)))
        if text:
            label(b, text, "base", "text", wraplength=px(690), justify="left").pack(anchor="w", pady=(0, px(10)))

    def wiz_row(self, b, title):
        r = tk.Frame(b, bg=C["card"])
        r.pack(anchor="w", fill="x", pady=px(5))
        label(r, title, "small_bold", "hi", width=16, anchor="w").pack(side="left")
        return r

    def wiz_welcome(self, b):
        self.wiz_h(b, f"Welcome to {APP_NAME}",
                   "A voice co-pilot and live dashboard for Star Citizen. It reads the log file the game writes as you play, "
                   "talks back, presses your own keybinds when you ask, and can show a small overlay in game.\n\n"
                   "It doesn't modify the game or read its memory. It only reads the game's log file and presses keys the "
                   "way your keyboard does.\n\nSetup takes about two minutes, and you can change everything later in Settings.")
        label(b, VER.DISCLAIMER, "small", "dim", wraplength=px(690), justify="left").pack(anchor="w", pady=(px(14), 0))

    def wiz_game(self, b):
        inst = self.binds.install
        self.wiz_h(b, "Your Star Citizen folder", "The app reads Game.log and your keybinds from the game's LIVE folder.")
        lbl = label(b, f"✓ Found it: {inst}" if inst else "Couldn't find it automatically. Pick your StarCitizen\\LIVE folder.",
                    "small_bold", "good" if inst else "low", wraplength=px(690), justify="left")
        lbl.pack(anchor="w", pady=(0, px(8)))

        def browse():
            d = filedialog.askdirectory(parent=self.wiz, initialdir=str(inst or Path.home()))
            if not d:
                return
            if not ((Path(d) / "Game.log").exists() or (Path(d) / "Data.p4k").exists()):
                lbl.config(text="That folder has no Game.log or Data.p4k. Pick the LIVE folder inside StarCitizen.", fg=C["toss"])
                return
            self.set_and_save("install_dir", d)
            lbl.config(text=f"✓ Using: {d}\nRestart SC Co-Pilot after setup so it picks this up.", fg=C["good"])
        FlatButton(b, "Choose a different folder…" if inst else "Browse…", browse, "normal", font=F["small_bold"],
                   padx=10, pady=4).pack(anchor="w")

    def wiz_talk(self, b):
        s = self.settings
        self.wiz_h(b, "Talking to it", "Hold your push-to-talk button, say a command, let go. A mouse side button or a spare "
                                       "joystick button works well. Avoid keys the game already uses.")
        r = self.wiz_row(b, "Push-to-talk")
        self.ptt_set_lbl = label(r, s.get("ptt", {}).get("name", "not set"), "h2", "accent")
        self.ptt_set_lbl.pack(side="left")
        self.ptt_btn = FlatButton(r, "Change", self.start_capture, "normal", font=F["small_bold"], padx=10, pady=4)
        self.ptt_btn.pack(side="left", padx=(px(10), 0))
        self.ptt_hint = label(b, self.ptt_warning(), "small", "low", wraplength=px(690), justify="left")
        self.ptt_hint.pack(anchor="w")
        r = self.wiz_row(b, "Microphone")
        chooser(r, [(None, "System default")] + V.input_devices(), s.get("mic"), self.set_mic, 40).pack(side="left")
        label(b, "Speech recognition runs on your PC. The first time you talk, it downloads a speech model (about 140 MB).",
              "small", "dim", wraplength=px(690), justify="left").pack(anchor="w", pady=(px(10), 0))

    def wiz_ai(self, b):
        s = self.settings
        self.wiz_h(b, "The AI co-pilot (optional)",
                   "Instant commands like “gear down”, “combat ready” or “pop flares” run on your PC for free. The AI answers "
                   "questions (“where do I sell Laranite?”, “how many kills this week?”) and handles anything that isn't an "
                   "instant command.")
        mode = tk.StringVar(value=self.brain.mode())
        keyf = tk.Frame(b, bg=C["card"])
        options = [("own_key", "Use my own Anthropic API key",
                    "You pay Anthropic directly: roughly a tenth of a cent per question with the default model. "
                    "Make a key at platform.claude.com and add a few dollars of credit."),
                   ("service", "Co-Pilot subscription" + ("" if VER.SERVICE_URL else "  (coming soon)"),
                    "A monthly subscription. No key or Anthropic account needed."),
                   ("off", "No AI for now", "Everything except questions works. You can turn it on later in Settings.")]
        for k, title, desc in options:
            state = "disabled" if k == "service" and not VER.SERVICE_URL else "normal"
            tk.Radiobutton(b, text=title, variable=mode, value=k, command=lambda: refresh(), font=F["small_bold"], fg=C["hi"],
                           bg=C["card"], activebackground=C["card"], activeforeground=C["hi"], selectcolor=C["input"],
                           disabledforeground=C["dim"], highlightthickness=0, bd=0, anchor="w", state=state,
                           cursor="hand2").pack(anchor="w", pady=(px(4), 0))
            label(b, desc, "small", "dim", wraplength=px(660), justify="left").pack(anchor="w", padx=(px(24), 0))
        keyf.pack(anchor="w", fill="x", pady=(px(10), 0))
        ent = {"w": None}

        def refresh():
            for ch in keyf.winfo_children():
                ch.destroy()
            ent["w"] = None
            m = mode.get()
            if m == "own_key" or (m == "service" and VER.SERVICE_URL):
                field = "api_key" if m == "own_key" else "license_key"
                r = self.wiz_row(keyf, "API key" if m == "own_key" else "Subscription key")
                e = entry(r, width=40, show="•")
                e.insert(0, s.get(field, ""))
                e.pack(side="left", ipady=px(3))
                ent["w"] = (field, e)
                if m == "own_key":
                    FlatButton(r, "Get a key", lambda: webbrowser.open("https://platform.claude.com/"), "ghost", font=F["small_bold"],
                               padx=10, pady=4).pack(side="left", padx=(px(6), 0))
                elif VER.STORE_URL:
                    FlatButton(r, "Subscribe", lambda: webbrowser.open(VER.STORE_URL), "ghost", font=F["small_bold"],
                               padx=10, pady=4).pack(side="left", padx=(px(6), 0))

                def test():
                    leave()
                    self.key_entry = None
                    self.test_api()
                FlatButton(r, "Test", test, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(6), 0))

        def leave():
            self.settings["ai_mode"] = mode.get()
            if ent["w"] is not None:
                field, e = ent["w"]
                try:
                    self.settings[field] = e.get().strip()
                except tk.TclError:
                    pass
            save_settings(self.settings)
        refresh()
        self.wiz_leave = leave

    def wiz_voice(self, b):
        s = self.settings
        self.wiz_h(b, "Its voice", "Kokoro sounds the most natural and runs offline on your PC (one-time download of about "
                                   "350 MB). Microsoft voices are free but need internet. Windows voices are instant but robotic.")
        r = self.wiz_row(b, "Voice engine")
        chooser(r, self.engine_choices(), s.get("tts_engine"), self.set_engine, 34).pack(side="left")
        if self.kokoro_available() and not self.kokoro.installed():
            r = self.wiz_row(b, "Kokoro")
            self.kokoro_btn = FlatButton(r, "Download Kokoro voices (~350 MB)", self.download_kokoro, "primary", font=F["small_bold"],
                                         padx=10, pady=4)
            self.kokoro_btn.pack(side="left")
            self.kokoro_lbl = label(r, "", "small", "dim")
            self.kokoro_lbl.pack(side="left")
        r = self.wiz_row(b, "Effect")
        chooser(r, FX.PRESETS, s.get("voice_fx", "computer"), lambda v: (self.set_and_save("voice_fx", v), self.preview_voice()),
                26).pack(side="left")
        FlatButton(r, "Test voice", self.preview_voice, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="left", padx=(px(8), 0))

    def wiz_ingame(self, b):
        s = self.settings
        self.wiz_h(b, "In the game")
        ov = tk.BooleanVar(value=s.get("overlay_on", False))
        check(b, "Show the in-game overlay (zone, current objective, quantum status, last callout)", ov,
              lambda: self.set_and_save("overlay_on", bool(ov.get()))).pack(anchor="w")
        label(b, "For the overlay to stay on top, set Star Citizen's Graphics → Window Mode to Borderless.", "small", "dim",
              wraplength=px(660), justify="left").pack(anchor="w", padx=(px(24), 0), pady=(0, px(6)))
        if sys.platform == "win32":
            text, tone = self.nvidia_text()
            label(b, text, "small", tone, wraplength=px(660), justify="left").pack(anchor="w", padx=(px(24), 0))
            if self.nv and self.nv.get("ok") and not self.nv.get("good"):
                FlatButton(b, "Fix the NVIDIA setting", self.fix_nvidia, "primary", font=F["small_bold"], padx=10,
                           pady=4).pack(anchor="w", padx=(px(24), 0), pady=(px(4), 0))
        ready = sum(1 for a in B.ACTIONS if self.binds.pressable(a[2]))
        missing = len(self.binds.missing())
        label(b, f"Keybinds: {ready} of {len(B.ACTIONS)} actions already have a key the co-pilot can press.", "small_bold", "hi",
              wraplength=px(690), justify="left").pack(anchor="w", pady=(px(14), px(2)))
        if missing:
            label(b, "Star Citizen leaves some unbound on purpose, like separate gear up / gear down or lights on / off. "
                     "The Controls tab can give those spare keys. Close the game before you do that.", "small", "dim",
                  wraplength=px(690), justify="left").pack(anchor="w")

    def wiz_done(self, b):
        self.wiz_h(b, "You're set", "Hold push-to-talk and try:")
        for line in ("“Gear down.”   “Lights on.”   “Shields up.”", "“Combat ready.”   “Pop flares.”   “Target the biggest threat.”",
                     "“What's my objective?”   “Where can I refuel near me?”   (these need the AI)", "“Overlay on.”"):
            label(b, line, "base", "accent", anchor="w").pack(anchor="w", pady=px(2))
        label(b, "Everything here can be changed in Settings, and you can run this setup again from Settings → About.",
              "small", "dim", wraplength=px(690), justify="left").pack(anchor="w", pady=(px(14), 0))

    def kokoro_available(self):
        return self.kokoro.package_ok() or not P.FROZEN

    def engine_choices(self):
        return [(k, v) for k, v in ENGINES if k != "kokoro" or self.kokoro_available()]

    def ai_mode_choices(self):
        return [(k, v + ("  (coming soon)" if k == "service" and not VER.SERVICE_URL else "")) for k, v in BR.AI_MODES]

    def set_ai_mode(self, v):
        self.set_and_save("ai_mode", v)
        self.uiq.put(("rerender_settings", None))

    def auto_update_check(self):
        if not P.FROZEN or not self.settings.get("check_updates", True):
            return
        if time.time() - float(self.settings.get("last_update_check") or 0) < 6 * 3600:
            return
        self.check_updates_now(quiet=True)

    def check_updates_now(self, quiet=False):
        def go():
            try:
                info = UPD.check()
            except Exception as ex:
                if not quiet:
                    self.ui(("toast", f"Couldn't check for updates ({type(ex).__name__})."))
                return
            self.settings["last_update_check"] = time.time()
            save_settings(self.settings)
            self.update_info = info
            if info:
                self.ui(("toast", f"{APP_NAME} {info['tag'].lstrip('v')} is out. Settings → About to install it."))
            elif not quiet:
                self.ui(("toast", f"You're on the latest version ({VER.VERSION})."))
            self.ui(("rerender_settings", None))
        threading.Thread(target=go, daemon=True).start()

    def install_update(self):
        info = self.update_info
        if not info:
            return
        if not info.get("asset") or sys.platform != "win32":
            webbrowser.open(info["url"])
            return
        self.toast("Downloading the update…")

        def go():
            try:
                path = UPD.download(info)
            except Exception as ex:
                self.ui(("toast", f"Download failed ({type(ex).__name__}). Opening the download page instead."))
                webbrowser.open(info["url"])
                return

            def launch():
                try:
                    os.startfile(str(path))
                except OSError as ex:
                    self.toast(f"Couldn't start the installer: {ex}")
                    return
                self.on_close()
            self.ui(("call", launch))
        threading.Thread(target=go, daemon=True).start()

    def copy_diagnostics(self):
        import platform
        b = self.binds
        lines = [f"{APP_NAME} {VER.VERSION} ({'installed' if P.FROZEN else 'source'})", f"Windows: {platform.platform()}",
                 f"Python: {platform.python_version()}", f"Game folder: {b.install or 'not found'}", f"Keybinds: {b.source}",
                 f"Missing keys: {len(b.missing())}, clashes: {len(b.clashes())}", f"AI mode: {self.brain.mode()} (ready: {self.brain.ready()})",
                 f"Speech: {self.settings.get('stt_model')} on {self.settings.get('stt_device')} — {self.transcriber.status}",
                 f"Voice: {self.settings.get('tts_engine')}", f"Overlay: on={self.settings.get('overlay_on')} nvidia={self.nv}",
                 f"Admin: app={B.self_elevated()} game={B.game_elevated()}", "", "Last log lines:"]
        try:
            tail = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
        except OSError:
            tail = ["(no log)"]
        try:
            crash = P.CRASH_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        except OSError:
            crash = []
        text = "\n".join(lines + tail + (["", "Last crash:"] + crash if crash else []))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.toast("Diagnostics copied. Paste them into your bug report.")

    def test_api(self):
        if self.key_entry is not None:
            self.set_and_save("license_key" if self.brain.mode() == "service" else "api_key", self.key_entry.get().strip())

        def go():
            try:
                r = self.brain.test()
                self.ui(("toast", f"Claude says: {r}"))
                self.speaker.say(r or "Co-pilot online.", True)
            except Exception as ex:
                self.ui(("toast", str(ex)))
        threading.Thread(target=go, daemon=True).start()

    def toast(self, text):
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.configure(bg=C["sel"])
        tk.Label(t, text=text, font=F["small_bold"], fg="#d5ecff", bg=C["sel"], padx=px(16), pady=px(10), wraplength=px(420)).pack()
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width() - t.winfo_reqwidth() - px(24)
        y = self.root.winfo_rooty() + self.root.winfo_height() - t.winfo_reqheight() - px(24)
        t.geometry(f"+{x}+{y}")
        t.attributes("-topmost", True)
        self.root.after(3600, t.destroy)

    def load_stt(self):
        if self.settings.get("stt_pending") == "cuda":
            self.settings["stt_device"] = "cpu"
            self.root.after(1500, lambda: self.toast("Speech model crashed on the GPU last time, so it's back on the CPU."))
        dev = self.settings.get("stt_device", "cpu")
        if dev not in dict(STT_DEVICES):
            dev = self.settings["stt_device"] = "cpu"
        self.settings["stt_pending"] = dev
        save_settings(self.settings)

        def go():
            self.transcriber.load(self.settings.get("stt_model", "base.en"), dev)
            self.settings.pop("stt_pending", None)
            save_settings(self.settings)
        threading.Thread(target=go, daemon=True).start()

    # ------------------------------------------------------------------ voices
    def set_engine(self, v):
        self.set_and_save("tts_engine", v)
        if v == "kokoro":
            if not self.kokoro.installed():
                self.toast("Download the Kokoro voices first. Until then it uses the Microsoft voice.")
                return
            threading.Thread(target=lambda: (self.kokoro.load(), self.preview_voice()), daemon=True).start()
            return
        self.preview_voice()

    def preview_voice(self):
        self.speaker.say(LN.line(self.settings, "greeting"), priority=True)

    def download_kokoro(self):
        if self.kokoro.downloading:
            return
        try:
            self.kokoro_btn.config(state="disabled", text="Downloading…")
        except (tk.TclError, AttributeError):
            pass

        def go():
            try:
                self.kokoro.download(on_progress=lambda f: self.ui(("kprog", f)))
                self.settings["tts_engine"] = "kokoro"
                save_settings(self.settings)
                ok = self.kokoro.load()
                self.ui(("toast", "Kokoro voices ready. Pick one under Kokoro voice." if ok else f"Downloaded, but: {self.kokoro.status}"))
                self.ui(("rerender_settings", None))
                if ok:
                    self.preview_voice()
            except Exception as ex:
                self.ui(("toast", f"Kokoro download failed: {ex}"))
                self.ui(("rerender_settings", None))
        threading.Thread(target=go, daemon=True, name="kokoro-dl").start()

    def refresh_edge_voices(self, rerender=True):
        voices = V.edge_voice_list(EDGE_CACHE, refresh=True)
        if voices:
            self.edge_voices = voices
        if rerender:
            self.ui(("rerender_settings", None))
            self.ui(("toast", f"{len(self.edge_voices)} Microsoft voices available"))

    # ------------------------------------------------------------------ macros
    def run_macro(self, m):
        if self.macro_running:
            self.speaker.say(LN.line(self.settings, "macro_busy"), priority=True)
            return

        def go():
            self.macro_running = True
            try:
                if m.get("say"):
                    self.ui(("copilot", m["say"]))
                    self.speaker.say(m["say"], priority=True)
                done, skipped = MAC.run(m, self.binds, B.ACTION_INDEX)
                self.ui(("action", f"{m['name']}: pressed {', '.join(done) or 'nothing'}"
                                   + (f" · skipped {', '.join(skipped)}" if skipped else "")))
                if not done and skipped:
                    if any("isn't running" in x for x in skipped):
                        self.speaker.say("Star Citizen isn't running.", priority=True)
                    else:
                        self.speaker.say(f"None of those steps have keys yet. Run auto-assign on the Controls tab.", priority=True)
            finally:
                self.macro_running = False
        threading.Thread(target=go, daemon=True, name="macro").start()

    # ------------------------------------------------------------------ personality and lines
    SAMPLE = {"victim": "Cutlass Black", "n": 3, "name": "Eliminate the Vanduul threat.", "killer": "Stormwind",
              "a_victim": "a Gladius", "who": "Shadow", "amount": "twenty thousand", "text": "Reach the comm array.",
              "shields": "down", "hull": "40 percent"}

    def build_lines(self, p):
        self.lines_frame = ScrollFrame(p, C["bg"])
        self.lines_frame.pack(fill="both", expand=True)

    def refresh_lines(self):
        if "lines" in self.frames:
            self.lines_frame.swap(self.render_lines)

    def render_lines(self, p):
        s = self.settings
        head = self.section(p, "Personality", "How your co-pilot talks. Pick a character, then change any line you like.")
        FlatButton(head, "Reset all my edits", self.reset_lines, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="right")
        FlatButton(head, "Export my lines…", self.export_lines, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="right", padx=(0, px(6)))
        FlatButton(head, "Import lines…", self.import_lines, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="right", padx=(0, px(6)))
        FlatButton(head, "Browse community packs", self.open_pack_gallery, "primary", font=F["small_bold"], padx=12,
                   pady=4).pack(side="right", padx=(0, px(6)))
        grid = tk.Frame(p, bg=C["bg"])
        grid.pack(fill="x")
        cur = s.get("personality") or "standard"
        for i, (pid, pers) in enumerate(LN.PERSONALITIES.items()):
            c = card(grid, padx=px(14), pady=px(10))
            c.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0 if i % 3 == 0 else px(8), 0), pady=(0, px(8)))
            grid.columnconfigure(i % 3, weight=1, uniform="pers")
            label(c, pers["name"], "h2", "accent" if pid == cur else "hi").pack(anchor="w")
            label(c, pers["desc"], "small", "muted", wraplength=px(300), justify="left").pack(anchor="w", pady=(px(2), px(8)))
            row = tk.Frame(c, bg=C["card"])
            row.pack(anchor="w")
            if pid == cur:
                label(row, "✓ In use", "small_bold", "good").pack(side="left", padx=(0, px(8)))
            else:
                FlatButton(row, "Use", lambda v=pid: self.set_personality(v), "primary", font=F["small_bold"], padx=12, pady=3).pack(side="left", padx=(0, px(6)))
            FlatButton(row, "Hear it", lambda v=pid: self.hear_personality(v), "normal", font=F["small_bold"], padx=10, pady=3).pack(side="left")
        label(p, "Your own edits below always win over the personality. Put | between versions and it picks one at random, "
                 "like  Gear down.|Wheels out.   Words in {braces} get filled in, like {victim} or {n}. Leave a box empty to go back to "
                 "the personality's line.", "small", "muted", "bg", wraplength=px(1100), justify="left").pack(anchor="w", pady=(px(6), px(6)))
        sr = tk.Frame(p, bg=C["bg"])
        sr.pack(fill="x", pady=(0, px(6)))
        label(sr, "Find a line:", "small_bold", "hi", "bg").pack(side="left")
        search = entry(sr, width=30)
        search.pack(side="left", padx=(px(8), 0), ipady=px(2))
        rows = []
        mine = s.get("lines") or {}
        for group, items in LN.editor_rows():
            g = label(p, group.upper(), "label", "muted", "bg")
            g.pack(anchor="w", pady=(px(10), px(4)))
            c = card(p, padx=px(14), pady=px(6))
            c.pack(fill="x")
            rows.append((g, c, group.lower(), None))
            for key, lbl, default, ph in items:
                r = tk.Frame(c, bg=C["card"])
                r.pack(fill="x", pady=px(2))
                left = tk.Frame(r, bg=C["card"], width=px(250))
                left.pack(side="left", fill="y")
                left.pack_propagate(False)
                label(left, lbl, "small_bold", "hi", anchor="w").pack(anchor="w")
                if ph:
                    label(left, ph, "tiny_bold", "dim", anchor="w").pack(anchor="w")
                e = entry(r, width=70)
                edited = bool(str(mine.get(key, "")).strip())
                e.insert(0, LN.raw(s, key))
                e.config(fg=C["accent"] if edited else C["text"])
                e.pack(side="left", fill="x", expand=True, ipady=px(2))
                e.bind("<FocusOut>", lambda ev, k=key, w=e: self.save_line(k, w))
                e.bind("<Return>", lambda ev, k=key, w=e: self.save_line(k, w))
                FlatButton(r, "▶", lambda k=key, w=e: (self.save_line(k, w), self.hear_line(k)), "normal", font=F["small_bold"],
                           padx=8, pady=2).pack(side="left", padx=(px(6), 0))
                FlatButton(r, "Reset", lambda k=key: self.reset_line(k), "ghost", font=F["small_bold"], padx=8, pady=2).pack(side="left", padx=(px(4), 0))
                rows.append((r, c, f"{lbl} {default} {LN.raw(s, key)}".lower(), r))

        def filt(_e=None):
            q = search.get().strip().lower()
            shown_cards = set()
            for w, parent, hay, is_row in rows:
                if is_row is None:
                    continue
                if not q or q in hay:
                    shown_cards.add(parent)
            for w, parent, hay, is_row in rows:
                if is_row is None:
                    if parent in shown_cards:
                        w.pack(anchor="w", pady=(px(10), px(4)))
                        parent.pack(fill="x")
                    else:
                        w.pack_forget()
                        parent.pack_forget()
                else:
                    w.pack_forget()
            for w, parent, hay, is_row in rows:
                if is_row is not None and (not q or q in hay):
                    w.pack(fill="x", pady=px(2))
        search.bind("<KeyRelease>", filt)

    def _fetch_json(self, url):
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": f"SC-CoPilot/{VER.VERSION}", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def open_pack_gallery(self):
        w = getattr(self, "pack_win", None)
        if w is not None and w.winfo_exists():
            w.lift()
            return
        w = tk.Toplevel(self.root)
        self.pack_win = w
        self.pack_cache = getattr(self, "pack_cache", {})
        w.title("Community line packs")
        w.configure(bg=C["bg"])
        w.transient(self.root)
        w.geometry(f"{px(780)}x{px(620)}+{self.root.winfo_rootx() + px(60)}+{self.root.winfo_rooty() + px(40)}")
        top = tk.Frame(w, bg=C["bg"])
        top.pack(fill="x", padx=px(16), pady=(px(14), px(6)))
        label(top, "Community line packs", "h2", "hi", "bg").pack(side="left")
        FlatButton(top, "Share your pack", lambda: webbrowser.open(VER.SHARE_PACK_URL), "normal", font=F["small_bold"],
                   padx=10, pady=4).pack(side="right")
        label(w, "Packs other players made. Hear it plays a few lines; Install replaces your edited lines (they're backed up first).",
              "small", "muted", "bg", wraplength=px(740), justify="left").pack(anchor="w", padx=px(16))
        sf = ScrollFrame(w, C["bg"])
        sf.pack(fill="both", expand=True, padx=px(16), pady=px(10))

        def loading(p):
            label(p, "Loading the gallery…", "small", "muted", "bg").pack(anchor="w", pady=px(10))
        sf.swap(loading)

        def fetch():
            try:
                data = self._fetch_json(VER.PACKS_INDEX_URL)
                packs = data.get("packs") or []
                err = None
            except Exception as ex:
                packs, err = [], f"{type(ex).__name__}"
            self.ui(("call", lambda: w.winfo_exists() and sf.swap(lambda p: self.render_pack_list(p, packs, err))))
        threading.Thread(target=fetch, daemon=True).start()

    def render_pack_list(self, p, packs, err):
        if err:
            label(p, f"Couldn't load the gallery ({err}). Check your internet, or browse it on GitHub.", "small", "low", "bg",
                  wraplength=px(700), justify="left").pack(anchor="w", pady=px(8))
            FlatButton(p, "Open the gallery on GitHub", lambda: webbrowser.open(VER.PACKS_PAGE), "normal", font=F["small_bold"],
                       padx=10, pady=4).pack(anchor="w")
            return
        if not packs:
            label(p, "No packs yet. Be the first: click Share your pack.", "small", "muted", "bg").pack(anchor="w", pady=px(8))
            return
        for e in packs:
            c = card(p, padx=px(14), pady=px(10))
            c.pack(fill="x", pady=(0, px(8)))
            label(c, e.get("name", "?"), "h2", "hi").pack(anchor="w")
            base = LN.PERSONALITIES.get(e.get("personality"), {}).get("name", "Ship AI")
            label(c, f"by {e.get('author') or 'unknown'}  ·  {e.get('lines', 0)} lines  ·  based on {base}", "small", "dim").pack(anchor="w")
            if e.get("description"):
                label(c, e["description"], "small", "text", wraplength=px(680), justify="left").pack(anchor="w", pady=(px(4), px(6)))
            row = tk.Frame(c, bg=C["card"])
            row.pack(anchor="w")
            FlatButton(row, "Hear it", lambda e=e: self.pack_action(e, "hear"), "normal", font=F["small_bold"], padx=10, pady=3).pack(side="left", padx=(0, px(6)))
            FlatButton(row, "Install", lambda e=e: self.pack_action(e, "install"), "primary", font=F["small_bold"], padx=12, pady=3).pack(side="left")

    def pack_action(self, e, what):
        def go():
            try:
                pack = self.pack_cache.get(e["file"]) or self._fetch_json(VER.PACKS_RAW + e["file"])
                self.pack_cache[e["file"]] = pack
            except Exception as ex:
                self.ui(("toast", f"Couldn't download that pack ({type(ex).__name__})."))
                return
            if what == "hear":
                tmp = {"personality": pack.get("personality", "standard"), "lines": pack.get("lines", {})}
                self.speaker.say(LN.line(tmp, "greeting"), priority=True)
                self.speaker.say(LN.line(tmp, "arm_off"))
                self.speaker.say(LN.line(tmp, "kill_n", **self.SAMPLE))
            else:
                self.ui(("call", lambda: self.install_pack(pack)))
        threading.Thread(target=go, daemon=True).start()

    def install_pack(self, pack):
        mine = self.settings.get("lines") or {}
        if mine and not messagebox.askyesno(APP_NAME, f"Install “{pack.get('name')}”? It replaces your {len(mine)} edited lines. "
                                            "Your current lines are backed up first.", parent=getattr(self, "pack_win", self.root)):
            return
        if mine:
            bdir = P.DATA_DIR / "line_backups"
            bdir.mkdir(parents=True, exist_ok=True)
            (bdir / f"lines-{datetime.now():%Y%m%d-%H%M%S}.json").write_text(LN.dumps_pack(self.settings, "Backup"), encoding="utf-8")
        try:
            n = LN.import_pack(self.settings, pack)
        except ValueError as ex:
            self.toast(str(ex))
            return
        save_settings(self.settings)
        self.refresh_lines()
        self.toast(f"Installed {pack.get('name')} ({n} lines).")
        self.preview_voice()

    def set_personality(self, pid):
        self.set_and_save("personality", pid)
        self.refresh_lines()
        self.hear_personality(pid)

    def hear_personality(self, pid):
        tmp = {"personality": pid, "lines": {}}
        self.speaker.say(LN.line(tmp, "greeting"), priority=True)
        self.speaker.say(LN.line(tmp, "arm_off"))
        self.speaker.say(LN.line(tmp, "kill_n", **self.SAMPLE))

    def hear_line(self, key):
        if key.startswith("ack."):
            text = LN.ack(self.settings, key[4:])
        else:
            text = LN.line(self.settings, key, **self.SAMPLE)
        self.speaker.say(text or "That line is empty.", priority=True)

    def save_line(self, key, w):
        try:
            val = w.get().strip()
        except tk.TclError:
            return
        lines = dict(self.settings.get("lines") or {})
        base = LN.raw({"personality": self.settings.get("personality"), "lines": {}}, key)
        if not val or val == base:
            lines.pop(key, None)
            if not val:
                w.delete(0, "end")
                w.insert(0, base)
            w.config(fg=C["text"])
        else:
            lines[key] = val[:400]
            w.config(fg=C["accent"])
        if lines != (self.settings.get("lines") or {}):
            self.set_and_save("lines", lines)

    def reset_line(self, key):
        lines = dict(self.settings.get("lines") or {})
        if lines.pop(key, None) is not None:
            self.set_and_save("lines", lines)
        self.refresh_lines()

    def reset_lines(self):
        if not (self.settings.get("lines") or {}):
            self.toast("You haven't changed any lines.")
            return
        if messagebox.askyesno(APP_NAME, "Remove all your edited lines and go back to the personality's lines?", parent=self.root):
            self.set_and_save("lines", {})
            self.refresh_lines()

    def export_lines(self):
        f = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json", initialfile="my-copilot-lines.json",
                                         filetypes=[("SC Co-Pilot lines", "*.json")])
        if not f:
            return
        try:
            Path(f).write_text(LN.dumps_pack(self.settings, Path(f).stem), encoding="utf-8")
            self.toast("Saved. Send the file to a friend and they can import it.")
        except OSError as ex:
            self.toast(f"Couldn't save: {ex}")

    def import_lines(self):
        f = filedialog.askopenfilename(parent=self.root, filetypes=[("SC Co-Pilot lines", "*.json"), ("All files", "*.*")])
        if not f:
            return
        try:
            n = LN.import_pack(self.settings, json.loads(Path(f).read_text(encoding="utf-8")))
        except (OSError, ValueError) as ex:
            self.toast(f"Couldn't import: {ex}")
            return
        save_settings(self.settings)
        self.refresh_lines()
        self.toast(f"Imported {n} lines.")

    def build_macros(self, p):
        self.macros_frame = ScrollFrame(p, C["bg"])
        self.macros_frame.pack(fill="both", expand=True)

    def refresh_macros(self):
        if "macros" in self.frames:
            self.macros_frame.swap(self.render_macros)

    def render_macros(self, p):
        head = self.section(p, "Voice macros", "Say the phrase and it presses the whole sequence, with the waits in between.")
        FlatButton(head, "Restore defaults", self.restore_macros, "normal", font=F["small_bold"], padx=10, pady=4).pack(side="right")
        FlatButton(head, "New macro", lambda: self.edit_macro(None), "primary", font=F["small_bold"], padx=10, pady=4).pack(side="right", padx=(0, px(6)))
        macros = self.settings.get("macros") or []
        missing_any = False
        if not macros:
            self.empty(p, "No macros yet", "Hit New macro to make one, or Restore defaults for the starter set.")
        for i, m in enumerate(macros):
            c = card(p, padx=px(18), pady=px(12))
            c.pack(fill="x", pady=(0, px(10)))
            top = tk.Frame(c, bg=C["card"])
            top.pack(fill="x")
            label(top, m.get("name", "Macro"), "h2", "hi").pack(side="left")
            FlatButton(top, "Delete", lambda i=i: self.delete_macro(i), "danger", font=F["tiny_bold"], padx=8, pady=2).pack(side="right")
            FlatButton(top, "Edit", lambda i=i: self.edit_macro(i), "normal", font=F["tiny_bold"], padx=8, pady=2).pack(side="right", padx=(0, px(6)))
            FlatButton(top, "Run", lambda m=m: self.run_macro(m), "normal", font=F["tiny_bold"], padx=8, pady=2).pack(side="right", padx=(0, px(6)))
            label(c, "Say: " + "  ·  ".join(f"“{ph}”" for ph in m.get("phrases", [])), "small", "accent", wraplength=px(950),
                  justify="left").pack(anchor="w", pady=(px(4), px(2)))
            if m.get("say"):
                label(c, f"Replies: “{m['say']}”", "small", "dim").pack(anchor="w")
            steps = tk.Frame(c, bg=C["card"])
            steps.pack(anchor="w", pady=(px(4), 0))
            for j, st in enumerate(m.get("steps", [])):
                a = B.ACTION_INDEX.get(st.get("action"))
                ok = bool(a) and self.binds.pressable(a["sc"])
                missing_any |= not ok
                key = self.binds.describe(a["sc"]) if a else None
                txt = f"{j + 1}. {a['label'] if a else st.get('action')}  [{key if ok else 'no key yet'}]"
                if float(st.get("wait") or 0) > 0 and j < len(m["steps"]) - 1:
                    txt += f"  → wait {float(st['wait']):g}s"
                label(steps, txt, "small", "text" if ok else "low", anchor="w").pack(anchor="w")
        if missing_any:
            label(p, "Steps marked “no key yet” get skipped. Run Auto-assign on the Controls tab to give them keys.", "small", "low",
                  "bg").pack(anchor="w", pady=(px(4), 0))

    def restore_macros(self):
        if messagebox.askyesno(APP_NAME, "Replace your macros with the starter set?", parent=self.root):
            self.settings["macros"] = MAC.defaults()
            save_settings(self.settings)
            self.refresh_macros()

    def delete_macro(self, i):
        macros = self.settings.get("macros") or []
        if 0 <= i < len(macros) and messagebox.askyesno(APP_NAME, f"Delete the “{macros[i].get('name')}” macro?", parent=self.root):
            macros.pop(i)
            save_settings(self.settings)
            self.refresh_macros()

    def action_menu(self, parent, current, on_pick):
        mb = tk.Menubutton(parent, text="", font=F["small_bold"], fg=C["text"], bg=C["btn"], activebackground=C["btn_hover"],
                           activeforeground=C["hi"], relief="flat", bd=0, padx=10, pady=4, cursor="hand2", highlightthickness=0,
                           width=34, anchor="w")
        menu = tk.Menu(mb, **menu_opts())
        groups = {}
        for aid, lbl, _sc, grp in B.ACTIONS:
            groups.setdefault(grp, []).append((aid, lbl))

        def pick(aid):
            mb.config(text=B.ACTION_INDEX[aid]["label"] + "  ▾")
            on_pick(aid)
        for grp, items in groups.items():
            sub = tk.Menu(menu, **menu_opts())
            for aid, lbl in items:
                sub.add_command(label=lbl, command=lambda a=aid: pick(a))
            menu.add_cascade(label=grp, menu=sub)
        mb.config(menu=menu, text=(B.ACTION_INDEX[current]["label"] if current in B.ACTION_INDEX else "Pick an action") + "  ▾")
        return mb

    def edit_macro(self, idx):
        macros = self.settings.setdefault("macros", [])
        m = json.loads(json.dumps(macros[idx])) if idx is not None and idx < len(macros) else \
            {"name": "", "phrases": [], "say": "", "steps": [{"action": "lights_on", "wait": 0}]}
        d = tk.Toplevel(self.root)
        d.title("Edit macro" if idx is not None else "New macro")
        d.configure(bg=C["bg"])
        d.transient(self.root)
        d.geometry(f"{px(720)}x{px(560)}")
        body = card(d, padx=px(18), pady=px(14))
        body.pack(fill="both", expand=True, padx=px(12), pady=px(12))
        fields = {}
        for key, title, sub, val in (("name", "Name", "", m.get("name", "")),
                                     ("phrases", "Phrases", "What you say. Separate with commas.", ", ".join(m.get("phrases", []))),
                                     ("say", "Reply", "Optional. What it says back.", m.get("say", ""))):
            r = self.srow(body, title, sub)
            e = entry(r, width=50)
            e.insert(0, val)
            e.pack(side="left", ipady=px(3))
            fields[key] = e
        label(body, "STEPS (pressed in order)", "label", "muted").pack(anchor="w", pady=(px(10), px(4)))
        steps_box = tk.Frame(body, bg=C["card"])
        steps_box.pack(fill="x")
        rows = []

        def redraw():
            for w in steps_box.winfo_children():
                w.destroy()
            for i, r in enumerate(rows):
                fr = tk.Frame(steps_box, bg=C["card"])
                fr.pack(fill="x", pady=px(2))
                label(fr, f"{i + 1}.", "small_bold", "dim", width=3).pack(side="left")
                self.action_menu(fr, r["action"], lambda a, r=r: r.__setitem__("action", a)).pack(side="left")
                label(fr, "  then wait", "small", "dim").pack(side="left")
                we = entry(fr, width=5)
                we.insert(0, f"{float(r.get('wait') or 0):g}")
                we.pack(side="left", padx=(px(6), px(2)), ipady=px(2))
                we.bind("<FocusOut>", lambda e, r=r, we=we: r.__setitem__("wait", self._num(we.get())))
                r["entry"] = we
                label(fr, "s", "small", "dim").pack(side="left")
                FlatButton(fr, "▲", lambda i=i: move(i, -1), "normal", font=F["tiny_bold"], padx=6, pady=1).pack(side="left", padx=(px(8), px(2)))
                FlatButton(fr, "▼", lambda i=i: move(i, 1), "normal", font=F["tiny_bold"], padx=6, pady=1).pack(side="left", padx=px(2))
                FlatButton(fr, "✕", lambda i=i: (sync(), rows.pop(i), redraw()), "danger", font=F["tiny_bold"], padx=6, pady=1).pack(side="left", padx=px(2))

        def sync():
            for r in rows:
                if r.get("entry") is not None:
                    try:
                        r["wait"] = self._num(r["entry"].get())
                    except tk.TclError:
                        pass

        def move(i, dlt):
            sync()
            j = i + dlt
            if 0 <= j < len(rows):
                rows[i], rows[j] = rows[j], rows[i]
                redraw()

        for st in m.get("steps", []):
            rows.append({"action": st.get("action"), "wait": st.get("wait", 0)})
        redraw()
        FlatButton(body, "+ Add step", lambda: (sync(), rows.append({"action": "lights_on", "wait": 0.3}), redraw()), "normal",
                   font=F["small_bold"], padx=10, pady=4).pack(anchor="w", pady=(px(6), 0))

        def save():
            sync()
            name = fields["name"].get().strip()
            phrases = [x.strip() for x in fields["phrases"].get().split(",") if x.strip()]
            steps = [{"action": r["action"], "wait": max(0.0, min(30.0, float(r.get("wait") or 0)))} for r in rows if r.get("action") in B.ACTION_INDEX]
            if not name or not phrases or not steps:
                messagebox.showwarning(APP_NAME, "A macro needs a name, at least one phrase and at least one step.", parent=d)
                return
            new = {"name": name, "phrases": phrases, "say": fields["say"].get().strip(), "steps": steps}
            if idx is not None and idx < len(macros):
                macros[idx] = new
            else:
                macros.append(new)
            save_settings(self.settings)
            d.destroy()
            self.refresh_macros()
        bar_ = tk.Frame(d, bg=C["bg"])
        bar_.pack(fill="x", padx=px(12), pady=(0, px(12)))
        FlatButton(bar_, "Save", save, "primary", padx=16, pady=6).pack(side="right")
        FlatButton(bar_, "Cancel", d.destroy, "normal", padx=16, pady=6).pack(side="right", padx=(0, px(8)))

    @staticmethod
    def _num(v):
        try:
            return max(0.0, min(30.0, float(str(v).strip() or 0)))
        except ValueError:
            return 0.0

    # ------------------------------------------------------------------ trade
    TRADE_SYSTEMS = [("auto", "My current system"), ("all", "All systems"), ("Stanton", "Stanton"), ("Pyro", "Pyro"), ("Nyx", "Nyx")]
    COMMON_GOODS = ["Hadanite", "Aphorite", "Dolivine", "Quantainium", "Laranite", "Agricium", "Gold", "Taranite"]

    def build_trade(self, p):
        top = card(p, padx=px(18), pady=px(14))
        top.pack(fill="x")
        row = tk.Frame(top, bg=C["card"])
        row.pack(fill="x")
        label(row, "COMMODITY", "label", "muted").pack(side="left", padx=(0, px(8)))
        self.trade_entry = entry(row, width=26)
        self.trade_entry.pack(side="left", ipady=px(4))
        self.trade_entry.bind("<Return>", lambda e: self.trade_search("sell"))
        label(row, "   IN", "label", "muted").pack(side="left", padx=(0, px(6)))
        chooser(row, self.TRADE_SYSTEMS, self.settings.get("trade_system", "auto"), lambda v: self.set_and_save("trade_system", v), 18).pack(side="left")
        FlatButton(row, "Where to sell", lambda: self.trade_search("sell"), "primary", font=F["small_bold"], padx=12, pady=5).pack(side="left", padx=(px(10), 0))
        FlatButton(row, "Where to buy", lambda: self.trade_search("buy"), "normal", font=F["small_bold"], padx=12, pady=5).pack(side="left", padx=(px(6), 0))
        FlatButton(row, "Best route", lambda: self.trade_search("route"), "normal", font=F["small_bold"], padx=12, pady=5).pack(side="left", padx=(px(6), 0))
        self.trade_chips = tk.Frame(top, bg=C["card"])
        self.trade_chips.pack(fill="x", pady=(px(10), 0))
        self.trade_status = label(top, "Prices are per SCU and come from UEX, where players report what terminals pay. "
                                       "They can be a few hours old, so check the terminal before you load up.", "small", "dim",
                                  wraplength=px(1000), justify="left")
        self.trade_status.pack(anchor="w", pady=(px(8), 0))
        self.trade_frame = ScrollFrame(p, C["bg"])
        self.trade_frame.pack(fill="both", expand=True, pady=(px(10), 0))
        self.draw_trade_chips()
        self.trade_frame.swap(self.render_trade_results)

    def draw_trade_chips(self):
        for w in self.trade_chips.winfo_children():
            w.destroy()
        with self.state.lock:
            texts = [o["text"] for c in self.state.active_contracts() for o in c["objectives"].values()]
        mine = T.objective_commodities(texts)
        label(self.trade_chips, "From your contracts:" if mine else "Quick picks:", "small_bold", "muted").pack(side="left", padx=(0, px(6)))
        for name in (mine + [g for g in self.COMMON_GOODS if g not in mine])[:10]:
            FlatButton(self.trade_chips, name, lambda n=name: self.trade_pick(n), "on" if name in mine else "normal",
                       font=F["tiny_bold"], padx=8, pady=3).pack(side="left", padx=(0, px(4)))

    def trade_pick(self, name):
        self.trade_entry.delete(0, "end")
        self.trade_entry.insert(0, name)
        self.trade_search("sell")

    def trade_system(self):
        v = self.settings.get("trade_system", "auto")
        if v == "auto":
            return self.state.star_system or None
        return None if v == "all" else v

    def trade_search(self, kind):
        q = self.trade_entry.get().strip()
        if not q or self.trade_busy:
            return
        sysname = self.trade_system()
        self.trade_busy = True
        self.trade_status.config(text=f"Looking up {q}{' in ' + sysname if sysname else ''}…", fg=C["muted"])

        def go():
            try:
                out = self.uex.route(q, sysname) if kind == "route" else self.uex.best(q, kind, sysname, limit=15)
                if kind == "route" and sysname and out.get("error") and out.get("commodity"):
                    out = self.uex.route(q, None)
                    if not out.get("error"):
                        out["note"] = f"No complete route inside {sysname}, so this one can cross systems."
                elif kind != "route" and sysname and not out.get("error") and not out.get("results"):
                    out = self.uex.best(q, kind, None, limit=15)
                    out["note"] = f"No {kind} data in {sysname}, so this is every system."
                self.ui(("trade", (kind, out)))
            except Exception as ex:
                self.ui(("trade", (kind, {"error": str(ex)})))
            finally:
                self.trade_busy = False
        threading.Thread(target=go, daemon=True, name="uex").start()

    def note_trade(self, out):
        kind = "route" if "margin_per_scu" in out else out.get("side", "sell")
        self.ui(("trade", (kind, out)))

    def show_trade(self, view):
        self.trade_view = view
        if "trade" in self.frames:
            kind, out = view
            if out.get("error"):
                self.trade_status.config(text=out["error"], fg=C["toss"])
            else:
                note = out.get("note") or ("Prices per SCU from UEX (community reported). Check the terminal before you load up.")
                self.trade_status.config(text=note, fg=C["dim"])
            self.trade_frame.swap(self.render_trade_results)

    def render_trade_results(self, p):
        if not self.trade_view:
            self.empty(p, "Look up a commodity", "Type a commodity (Hadanite, Laranite, Quantainium, Agricium…) and pick Where to sell, "
                                                 "Where to buy or Best route. You can also just ask the co-pilot: “Where's the best place "
                                                 "to sell Hadanite near me?”")
            return
        kind, out = self.trade_view
        if out.get("error"):
            self.empty(p, out.get("commodity") or "No result", out["error"])
            return
        if kind == "route" or "margin_per_scu" in out:
            c = card(p, padx=px(18), pady=px(14))
            c.pack(fill="x")
            label(c, f"{out['commodity']} route", "h2", "hi").pack(anchor="w")
            for tag, r, color in (("BUY AT", out["buy_at"], "accent"), ("SELL AT", out["sell_at"], "good")):
                fr = tk.Frame(c, bg=C["card"])
                fr.pack(fill="x", pady=(px(8), 0))
                label(fr, tag, "label", "muted", width=9, anchor="w").pack(side="left")
                label(fr, f"{r['terminal']}  ·  {r['where']}", "base", "hi").pack(side="left")
                label(fr, f"   {r['price']:,} aUEC/SCU", "small_bold", color).pack(side="left")
                label(fr, f"   updated {r['updated']}", "small", "dim").pack(side="left")
            m = out["margin_per_scu"]
            label(c, f"Margin: {m:,} aUEC per SCU", "h2", "good" if m > 0 else "toss").pack(anchor="w", pady=(px(10), 0))
            if out.get("profit_for_scu"):
                pf = out["profit_for_scu"]
                label(c, f"{pf['scu']} SCU: costs {pf['cost']:,}, profit {pf['profit']:,} aUEC", "small", "text").pack(anchor="w")
            return
        side = out.get("side", "sell")
        hdr = self.section(p, f"{'Where to sell' if side == 'sell' else 'Where to buy'} {out['commodity']}",
                           f"{out.get('system_filter', 'all')} · average {'sell' if side == 'sell' else 'buy'} "
                           f"{out.get('commodity_avg', {}).get(side, 0):,} aUEC/SCU"
                           + (f" · {', '.join(out['flags'])}" if out.get("flags") else ""))
        if out.get("also_matched"):
            label(hdr, f"   (also: {', '.join(out['also_matched'])})", "small", "dim", "bg").pack(side="left", pady=(px(3), 0))
        c = card(p, padx=px(18), pady=px(12))
        c.pack(fill="x")
        heads = [("#", 3), ("TERMINAL", 30), ("WHERE", 30), ("PRICE / SCU", 12), ("SCU" if side == "buy" else "DEMAND SCU", 11), ("UPDATED", 0)]
        hr = tk.Frame(c, bg=C["card"])
        hr.pack(fill="x", pady=(0, px(4)))
        for t, w in heads:
            label(hr, t, "label", "muted", width=w or None, anchor="w").pack(side="left")
        if not out.get("results"):
            label(c, f"Nobody has reported {side} prices for this{' in ' + out['system_filter'] if out.get('system_filter') not in (None, 'all') else ''} yet."
                     + (f" Data exists for: {', '.join(out['systems_with_data'])}." if out.get("systems_with_data") else ""),
                  "small", "dim").pack(anchor="w")
        for i, r in enumerate(out.get("results", [])):
            fr = tk.Frame(c, bg=C["card"])
            fr.pack(fill="x", pady=px(1))
            stale = r.get("updated_ts") and time.time() - r["updated_ts"] > 2 * 86400
            vals = [str(i + 1), r["terminal"], r["where"], f"{r['price']:,}", f"{r['scu']:,}" if r.get("scu") is not None else "—", r["updated"]]
            for (t, w), v in zip(heads, vals):
                color = "good" if (t.startswith("PRICE") and i == 0) else ("dim" if stale and t == "UPDATED" else "text")
                label(fr, v, "small_bold" if t.startswith("PRICE") else "small", color, width=w or None, anchor="w").pack(side="left")

    # ------------------------------------------------------------------ voice + events
    def _speaking(self, on):
        self.speaking_now = on

    def callout(self, text):
        self.ui(("callout", text))
        self.overlay.set_callout(text)
        self.speaker.say(text)

    def note_action(self, text):
        self.ui(("action", text))

    def note_system(self, text):
        self.ui(("sys", text))

    def on_game_event(self, name, info):
        try:
            self.callouts.handle(name, info)
        except Exception:
            traceback.print_exc()

    def prewarm(self):
        phrases = []
        for _, _, _, _, _, _, says in Q.STATEFUL:
            phrases += list(says)
        phrases += [p[2] for p in Q.PRESSES + Q.MODES + Q.ENGINEERING if p[2]]
        phrases += ["Entering armistice. Weapons locked.", "Leaving armistice. Weapons free.", "Ungoverned space. Stay sharp.",
                    "Quantum travel complete.", "Quantum path's obstructed. Try another route.", "Hangar's ready.",
                    "Leaving monitored space.", "Back in monitored space.", "Fuel's low.", "Doors locked.", "Doors unlocked.",
                    "Star Citizen isn't running.", "Didn't catch that.", "You're down. Call for help before the timer runs out.",
                    "CrimeStat increased. Security will be hostile."]

        phrases += [m.get("say") for m in self.settings.get("macros", []) if m.get("say")]

        def go():
            s = self.settings
            if self.speaker._engine(s) == "sapi":
                self.speaker._sapi_start()
                return
            if self.speaker._engine(s) == "kokoro" and not self.kokoro.load():
                return
            for ph in phrases:
                if getattr(self, "closing", False):
                    return
                if not self.speaker._cached(ph, s):
                    self.speaker._synth(ph, s)
                    time.sleep(0.15)
        threading.Thread(target=go, daemon=True, name="prewarm").start()
        threading.Thread(target=self.brain.warm, daemon=True).start()

    def ptt_down(self, src="ptt"):
        if self.listening:
            return
        threading.Thread(target=self.brain.warm, daemon=True).start()
        self.speaker.stop()
        try:
            self.recorder.start()
        except Exception as ex:
            self.ui(("sys", f"Mic problem: {ex}"))
            self.speaker.chirp("error")
            return
        self.listening = True
        self.speaker.chirp("listen")

    def ptt_up(self, src="ptt"):
        if not self.listening:
            return
        self.listening = False
        t_release = time.time()
        audio = self.recorder.stop()
        self.speaker.chirp("done")
        threading.Thread(target=self.handle_audio, args=(audio, t_release), daemon=True).start()

    def handle_audio(self, audio, t_release=None):
        t_release = t_release or time.time()
        if audio is None or len(audio) < V.Recorder.RATE * 0.35:
            self.ui(("sys", "Too short. Hold the button the whole time you're talking."))
            return
        if self.transcriber.model is None:
            self.ui(("sys", f"Speech model isn't ready: {self.transcriber.status}"))
            self.speaker.chirp("error")
            return
        self.thinking = True
        try:
            text = self.transcriber.transcribe(audio)
        except Exception as ex:
            self.thinking = False
            self.ui(("sys", f"Couldn't transcribe: {ex}"))
            return
        if len(text.strip(" .,!?")) < 2:
            self.thinking = False
            self.ui(("sys", "Didn't catch that."))
            self.speaker.chirp("error")
            return
        stt = time.time() - t_release
        if self.settings.get("instant_commands", True):
            cmd = Q.parse(text, self.settings.get("assistant_name", "Co-Pilot"), self.settings.get("macros"))
            if cmd:
                self.ui(("you", text))
                self.thinking = False
                self.run_quick(cmd, t_release, stt)
                return
        self.ask(text, t_release=t_release, stt=stt)

    def run_quick(self, cmd, t_release=None, stt=0.0):
        if cmd["kind"] == "macro":
            self.run_macro(cmd["macro"])
            if t_release:
                self.ui(("tool", f"macro · heard in {stt:.1f}s"))
            return
        if cmd["kind"] == "hud":
            r = self.hud.read()
            if r.get("ok") and r.get("visible"):
                what = cmd.get("what", "both")
                sh, hu = HUD.spoken_pct(r.get("shields")), HUD.spoken_pct(r.get("hull"))
                if what == "shields" and sh == "down":
                    say = LN.line(self.settings, "target_shields_down")
                elif what == "shields":
                    say = f"Target shields {sh}."
                elif what == "hull":
                    say = f"Target hull {hu}."
                else:
                    say = LN.line(self.settings, "target_status", shields=sh, hull=hu)
            else:
                say = r.get("text", "I can't read the target right now.")
            self.ui(("copilot", say))
            self.speaker.say(say, priority=True)
            return
        if cmd["kind"] == "overlay":
            on = cmd.get("on")
            on = (not self.settings.get("overlay_on", False)) if on is None else on
            self.settings["overlay_on"] = on
            save_settings(self.settings)
            say = LN.line(self.settings, "overlay_on" if on else "overlay_off")
            self.ui(("copilot", say))
            self.speaker.say(say, priority=True)
            return
        a = B.ACTION_INDEX[cmd["action"]]
        say = cmd.get("say")
        use = a
        fb = B.ACTION_INDEX.get(cmd.get("fallback") or "")
        if not self.binds.pressable(a["sc"]) and fb and self.binds.pressable(fb["sc"]):
            use, say = fb, cmd.get("fallback_say")
        ok, msg = self.binds.press(use["sc"])
        self.ui(("action", f"{use['label']}: {'pressed ' + msg if ok else 'NOT pressed, ' + msg}"))
        if ok:
            say = LN.ack(self.settings, use["id"], say or "") or None
        if not ok:
            say = self.press_problem(a, msg)
        if say:
            self.ui(("copilot", say))
            self.speaker.say(say, priority=True)
        if t_release:
            self.ui(("tool", f"instant command · heard in {stt:.1f}s · done {time.time() - t_release:.1f}s after you let go"))

    def press_problem(self, a, msg):
        if msg == "no keyboard key":
            return f"{a['label']} doesn't have a key yet. Hit auto-assign on the Controls tab."
        if "isn't running" in msg:
            return "Star Citizen isn't running."
        return f"Couldn't press {a['label']}: {msg}."

    def ask(self, text, t_release=None, stt=None):
        self.ui(("you", text))
        t_release = t_release or time.time()
        speak = self.settings.get("speak_answers", True)
        first = [None]

        def on_sentence(chunk):
            if first[0] is None:
                first[0] = time.time()
                self.speaker.say(chunk, priority=True, force=True)
            else:
                self.speaker.say(chunk, force=True)

        def go():
            self.thinking = True
            try:
                reply = self.brain.ask(text, on_tool=lambda n, i: self.ui(("tool", self.tool_note(n, i))),
                                       on_sentence=on_sentence if speak else None)
                self.ui(("copilot", reply))
                bits = []
                if stt is not None:
                    bits.append(f"heard in {stt:.1f}s")
                if first[0]:
                    bits.append(f"started talking {first[0] - t_release:.1f}s after you let go")
                if bits:
                    self.ui(("tool", " · ".join(bits)))
            except Exception as ex:
                self.ui(("sys", str(ex)))
                self.speaker.say(str(ex).split(".")[0] + ".", priority=True)
            finally:
                self.thinking = False
        threading.Thread(target=go, daemon=True).start()

    def tool_note(self, name, inp):
        nice = {"get_contracts": "checking contracts", "get_session_details": "checking session details",
                "get_combat_log": "checking combat log", "get_history": "checking history", "get_recent_events": "checking recent events",
                "find_keybind": "looking up keybind", "press_controls": "pressing controls", "web_search": "searching the web",
                "commodity_prices": "checking UEX prices", "trade_route": "working out a trade route", "run_macro": "running macro",
                "find_services": "finding services", "place_info": "looking up location", "ship_info": "looking up ship",
                "item_where": "finding where to buy", "refinery_yields": "checking refinery yields"}.get(name, name)
        extra = ", ".join(f"{k}: {v}" for k, v in inp.items() if k != "actions")
        if name == "press_controls":
            extra = ", ".join(a.get("action", "") + (f" x{a['times']}" if a.get("times", 1) > 1 else "") for a in inp.get("actions", []))
        return nice + (f" ({extra})" if extra else "")

    # ------------------------------------------------------------------ loop
    def update_header(self):
        st = self.state
        with st.lock:
            bits = [x for x in (st.handle, st.ship_text(), st.jurisdiction and f"{st.jurisdiction} jurisdiction") if x]
            if bits:
                self.sub.config(text="  ·  ".join(bits))
            live = st.running
        if time.time() - getattr(self, "_adm_t", 0) > 6:
            self._adm_t = time.time()
            self._adm_bad = live and B.admin_mismatch()
        if getattr(self, "_adm_bad", False):
            self.chips["game"].config(text="● Game runs as admin: restart app as admin", fg=C["toss"])
        else:
            self.chips["game"].config(text="● Star Citizen live" if live else "● Star Citizen not running", fg=C["good"] if live else C["dim"])
        ts = self.transcriber.status
        if ts.startswith("ready"):
            self.chips["voice"].config(text="● Voice ready", fg=C["good"])
        elif "loading" in ts:
            self.chips["voice"].config(text="● Voice loading", fg=C["low"])
        else:
            self.chips["voice"].config(text="● Voice off", fg=C["toss"])
        mode = self.brain.mode()
        if mode == "off":
            self.chips["brain"].config(text="● AI off", fg=C["dim"])
        elif self.brain.ready():
            self.chips["brain"].config(text="● Subscription ready" if mode == "service" else "● Claude ready", fg=C["good"])
        else:
            self.chips["brain"].config(text="● Subscription key needed" if mode == "service" else "● No API key", fg=C["low"])
        if self.listening:
            self.activity.config(text="● LISTENING", bg=C["toss"], fg="#1f0b0b")
        elif self.thinking:
            self.activity.config(text="THINKING…", bg=C["sel"], fg="#d5ecff")
        elif self.speaking_now:
            self.activity.config(text="SPEAKING", bg=C["blue_bg"], fg=C["accent"])
        else:
            self.activity.config(text="", bg=C["bar"])
        if self.chat and getattr(self, "_talk_on", None) != self.listening:
            self._talk_on = self.listening
            self.talk.set_kind("talk_on" if self.listening else "talk")
        if "settings" in self.frames:
            try:
                self.stt_lbl.config(text=f"Speech model: {self.transcriber.status}")
            except (tk.TclError, AttributeError):
                pass

    def tick(self):
        try:
            while True:
                item = self.uiq.get_nowait()
                if item[0] == "toast":
                    self.toast(item[1])
                elif item[0] == "trade":
                    self.show_trade(item[1])
                elif item[0] == "kprog":
                    try:
                        self.kokoro_lbl.config(text=f"  Downloading… {item[1] * 100:.0f}%")
                    except (tk.TclError, AttributeError):
                        pass
                elif item[0] == "rerender_settings":
                    if "settings" in self.frames:
                        self.settings_frame.swap(self.render_settings)
                elif item[0] == "call":
                    item[1]()
                else:
                    self._append(item[0], item[1])
        except queue.Empty:
            pass
        try:
            if self.capture:
                spec = self.capture.poll()
                if spec:
                    self.finish_capture(spec)
                elif time.time() - self.capture_started > 12:
                    self.finish_capture(None)
            self.update_header()
            if self.tab in self.DATA_TABS:
                self.render(self.tab)
            if time.time() - self._ov_t > 0.4:
                self._ov_t = time.time()
                status = "● Listening…" if self.listening else "Thinking…" if self.thinking else ""
                self.overlay.update(self.state, status, force=time.time() < self.overlay_test_until)
                if time.time() < self.overlay_test_until and time.time() - self.overlay_diag_t >= 1.0:
                    self.overlay_diag_t = time.time()
                    print(f"[{time.strftime('%H:%M:%S')}] overlay-test {self.overlay.report()}", flush=True)
            else:
                self.overlay.pin()
        except Exception:
            traceback.print_exc()
        self.root.after(100, self.tick)

    def on_close(self):
        WI.unbrand(self.root)
        self.closing = True
        self.hud.stop_watch()
        try:
            self.settings["geometry"] = self.root.geometry()
            save_settings(self.settings)
        except Exception:
            pass
        self.watcher.stop_flag = True
        self.speaker.stop()
        self.overlay.destroy()
        self.root.destroy()


def single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47732))
        s.listen(1)
        return s
    except OSError:
        return None


def selftest():
    """Used by the build server: can the packaged app load everything it needs?"""
    report, bad = [], 0
    for mod in ("numpy", "sounddevice", "soundfile", "faster_whisper", "ctranslate2", "edge_tts", "zstandard", "onnxruntime"):
        try:
            __import__(mod)
            report.append(f"ok   {mod}")
        except Exception as ex:
            bad += 1
            report.append(f"FAIL {mod}: {type(ex).__name__}: {ex}")
    for name in ("sc_default_binds.json", "sc_copilot.png", "sc_copilot.ico", "legal/LICENSE.txt", "legal/THIRD_PARTY_NOTICES.md",
                 "legal/PRIVACY.md"):
        ok = P.resource(name).exists()
        bad += 0 if ok else 1
        report.append(f"{'ok  ' if ok else 'FAIL'} resource {name}")
    try:
        root = tk.Tk()
        root.destroy()
        report.append("ok   tkinter")
    except Exception as ex:
        bad += 1
        report.append(f"FAIL tkinter: {ex}")
    try:
        (P.LOG_DIR / "selftest.txt").write_text("\n".join(report), encoding="utf-8")
    except OSError:
        pass
    print("\n".join(report), flush=True)
    return 1 if bad else 0


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        WI.set_app_id()
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--nvfix" in sys.argv:
        out = sys.argv[sys.argv.index("--nvfix") + 1] if len(sys.argv) > sys.argv.index("--nvfix") + 1 else str(P.cache("sc_nvfix_result.json"))
        result = NV.fix()
        Path(out).write_text(json.dumps({"result": result, "after": NV.check()}), encoding="utf-8")
        return
    relaunched = "--relaunch" in sys.argv
    if not relaunched and load_settings().get("run_as_admin") and sys.platform == "win32" and not B.self_elevated():
        if relaunch_elevated():
            return
    root = tk.Tk()
    root.withdraw()
    lock = single_instance()
    t0 = time.time()
    while lock is None and relaunched and time.time() - t0 < 10:
        time.sleep(0.3)
        lock = single_instance()
    if lock is None:
        messagebox.showinfo(APP_NAME, "SC Co-Pilot is already running.")
        root.destroy()
        return
    root._lock = lock

    def log_crash(kind, etype, exc, tb):
        try:
            with open(P.CRASH_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] {kind} in {APP_NAME} {VER.VERSION}\n")
                f.write("".join(traceback.format_exception(etype, exc, tb)))
        except OSError:
            pass
    sys.excepthook = lambda t, e, tb: (log_crash("crash", t, e, tb), sys.__excepthook__(t, e, tb))
    threading.excepthook = lambda a: log_crash(f"thread {getattr(a.thread, 'name', '')}", a.exc_type, a.exc_value, a.exc_traceback)
    SCALE[0] = max(1.0, root.winfo_fpixels("1i") / 96.0)
    setup_fonts(root)
    root.title(APP_NAME)
    root.configure(bg=C["bg"])
    root.minsize(px(980), px(640))
    s = load_settings()
    root.geometry(s.get("geometry") or f"{px(1200)}x{px(800)}")
    app = App(root)
    root.app = app

    def ui_error(t, e, tb):
        log_crash("ui", t, e, tb)
        traceback.print_exception(t, e, tb)
        try:
            app.toast("Something went wrong. It's saved in the log: Settings → About → Copy diagnostics.")
        except Exception:
            pass
    root.report_callback_exception = ui_error
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.deiconify()
    try:
        print(f"[icon] {WI.brand(root, relaunch_command())}", flush=True)
    except Exception as e:
        print(f"[icon] taskbar icon setup failed: {e}", flush=True)
    root.mainloop()


if __name__ == "__main__":
    main()
