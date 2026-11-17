import asyncio
import base64
import hashlib
import importlib.util
import json
import math
import os
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import wave
from pathlib import Path

try:
    import sc_fx as FX
except Exception:
    FX = None

try:
    import numpy as np
except Exception:
    np = None
try:
    import sounddevice as sd
except Exception:
    sd = None

WIN = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VOICES = [
    ("en-GB-SoniaNeural", "Sonia (British, female)"),
    ("en-GB-RyanNeural", "Ryan (British, male)"),
    ("en-GB-LibbyNeural", "Libby (British, female)"),
    ("en-US-AriaNeural", "Aria (American, female)"),
    ("en-US-GuyNeural", "Guy (American, male)"),
    ("en-US-JennyNeural", "Jenny (American, female)"),
    ("en-AU-NatashaNeural", "Natasha (Australian, female)"),
    ("en-IE-EmilyNeural", "Emily (Irish, female)"),
    ("en-US-AndrewMultilingualNeural", "Andrew Multilingual (American, male)"),
    ("en-US-BrianMultilingualNeural", "Brian Multilingual (American, male)"),
    ("en-US-AvaMultilingualNeural", "Ava Multilingual (American, female)"),
    ("en-US-EmmaMultilingualNeural", "Emma Multilingual (American, female)"),
    ("en-GB-ThomasNeural", "Thomas (British, male)"),
    ("en-AU-WilliamNeural", "William (Australian, male)"),
]

ENGINES = [("kokoro", "Kokoro (local, natural, offline)"), ("neural", "Microsoft neural (online)"),
           ("sapi", "Windows voice (instant, robotic, offline)")]

KOKORO_NAMES = {"af": ("American", "female"), "am": ("American", "male"), "bf": ("British", "female"), "bm": ("British", "male")}
KOKORO_STAR = {"af_heart", "af_bella"}
KOKORO_DEFAULT = "af_heart"


def kokoro_voice_list(names=None):
    names = names or ["af_heart", "af_bella", "af_nicole", "af_aoede", "af_kore", "af_sarah", "af_nova", "af_sky", "af_alloy",
                      "af_jessica", "af_river", "am_michael", "am_fenrir", "am_puck", "am_echo", "am_eric", "am_liam",
                      "am_onyx", "am_adam", "bf_emma", "bf_isabella", "bf_alice", "bf_lily", "bm_george", "bm_fable",
                      "bm_lewis", "bm_daniel"]
    out = []
    for n in names:
        if n[:2] not in KOKORO_NAMES or n == "am_santa":
            continue
        accent, sex = KOKORO_NAMES[n[:2]]
        out.append((n, f"{n[3:].title()} ({accent}, {sex})" + ("  ★" if n in KOKORO_STAR else "")))
    return out


def edge_voice_list(cache_file, refresh=False):
    """All English Microsoft neural voices. Cached to disk; refresh pulls the live list."""
    if not refresh:
        try:
            data = json.loads(Path(cache_file).read_text(encoding="utf-8"))
            if data:
                return [tuple(x) for x in data]
        except (OSError, ValueError):
            pass
        if not refresh:
            return list(VOICES)
    try:
        import edge_tts
        voices = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout=15))
    except Exception:
        return list(VOICES)
    out = []
    for v in voices:
        sn, loc = v.get("ShortName", ""), v.get("Locale", "")
        if not loc.startswith("en-"):
            continue
        nm = sn.split("-", 2)[-1].replace("Neural", "")
        for word in ("Multilingual", "Expressive", "Turbo"):
            nm = nm.replace(word, " " + word)
        out.append((sn, f"{nm.strip()} ({loc[3:]}, {v.get('Gender', '').lower()})"))
    out.sort(key=lambda x: (x[1].split("(")[1], x[1]))
    if out:
        try:
            Path(cache_file).write_text(json.dumps(out), encoding="utf-8")
        except OSError:
            pass
    return out or list(VOICES)


class Kokoro:
    FILES = {"kokoro-v1.0.onnx": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx", 300_000_000),
             "voices-v1.0.bin": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin", 25_000_000)}

    def __init__(self, folder):
        self.folder = Path(folder)
        self.model = None
        self.lock = threading.Lock()
        self.status = "not loaded"
        self.downloading = False
        self.progress = 0.0

    def package_ok(self):
        return importlib.util.find_spec("kokoro_onnx") is not None

    def installed(self):
        try:
            return all((self.folder / n).exists() and (self.folder / n).stat().st_size >= sz for n, (_, sz) in self.FILES.items())
        except OSError:
            return False

    def ready(self):
        return self.model is not None

    def voices(self):
        try:
            if self.model is not None:
                have = set(self.model.get_voices())
                return [v for v in kokoro_voice_list() if v[0] in have]
        except Exception:
            pass
        return kokoro_voice_list()

    def load(self):
        with self.lock:
            if self.model is not None:
                return True
            if not self.package_ok():
                self.status = "kokoro-onnx isn't installed (run Install.bat)"
                return False
            if not self.installed():
                self.status = "voice files not downloaded yet"
                return False
            self.status = "loading…"
            try:
                from kokoro_onnx import Kokoro as K
                self.model = K(str(self.folder / "kokoro-v1.0.onnx"), str(self.folder / "voices-v1.0.bin"))
                self.status = "ready"
                return True
            except Exception as ex:
                self.status = f"failed to load: {str(ex).splitlines()[0][:120] if str(ex) else type(ex).__name__}"
                return False

    def synth(self, text, voice, speed=1.0):
        if self.model is None and not self.load():
            raise RuntimeError(self.status)
        voice = voice or KOKORO_DEFAULT
        lang = "en-gb" if voice.startswith("b") else "en-us"
        with self.lock:
            audio, sr = self.model.create(text, voice=voice, speed=max(0.6, min(1.5, speed)), lang=lang)
        return audio, sr

    def download(self, on_progress=None):
        if self.downloading:
            return False
        self.downloading = True
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            total = sum(sz for _, sz in self.FILES.values())
            done_before = 0
            for name, (url, approx) in self.FILES.items():
                dest = self.folder / name
                if dest.exists() and dest.stat().st_size >= approx:
                    done_before += approx
                    continue
                part = dest.with_suffix(dest.suffix + ".part")
                req = urllib.request.Request(url, headers={"User-Agent": "SC-CoPilot"})
                with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                    got = 0
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        self.progress = min(0.999, (done_before + got) / total)
                        if on_progress:
                            on_progress(self.progress)
                if part.stat().st_size < approx * 0.9:
                    raise RuntimeError(f"{name} download looks incomplete")
                os.replace(part, dest)
                done_before += approx
            self.progress = 1.0
            if on_progress:
                on_progress(1.0)
            return True
        finally:
            self.downloading = False


def write_wav(path, audio, sr):
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767.0
    return data, sr


def decode_mp3(path):
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


VK_NAMES = {0x01: "Left mouse", 0x02: "Right mouse", 0x04: "Middle mouse", 0x05: "Mouse 4", 0x06: "Mouse 5",
            0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "Caps Lock", 0x1B: "Esc", 0x20: "Space",
            0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right",
            0x28: "Down", 0x2C: "Print Screen", 0x2D: "Insert", 0x2E: "Delete", 0x5B: "Left Win", 0x5C: "Right Win",
            0x5D: "Menu key", 0x60: "Num 0", 0x61: "Num 1", 0x62: "Num 2", 0x63: "Num 3", 0x64: "Num 4", 0x65: "Num 5",
            0x66: "Num 6", 0x67: "Num 7", 0x68: "Num 8", 0x69: "Num 9", 0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -",
            0x6E: "Num .", 0x6F: "Num /", 0x90: "Num Lock", 0x91: "Scroll Lock", 0xA0: "Left Shift", 0xA1: "Right Shift",
            0xA2: "Left Ctrl", 0xA3: "Right Ctrl", 0xA4: "Left Alt", 0xA5: "Right Alt", 0xBA: ";", 0xBB: "=", 0xBC: ",",
            0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
for _i in range(24):
    VK_NAMES[0x70 + _i] = f"F{_i + 1}"
for _c in range(0x30, 0x3A):
    VK_NAMES[_c] = chr(_c)
for _c in range(0x41, 0x5B):
    VK_NAMES[_c] = chr(_c)

VK_TO_SC = {0x04: "mouse3", 0x05: "mouse4", 0x06: "mouse5", 0x09: "tab", 0x14: "capslock", 0x20: "space",
            0x21: "pgup", 0x22: "pgdn", 0x23: "end", 0x24: "home", 0x2D: "insert", 0x2E: "delete", 0x6A: "np_multiply",
            0x6B: "np_add", 0x6D: "np_subtract", 0x6E: "np_period", 0x6F: "np_divide", 0xA0: "lshift", 0xA1: "rshift",
            0xA2: "lctrl", 0xA3: "rctrl", 0xA4: "lalt", 0xA5: "ralt", 0xBA: "semicolon", 0xBB: "equals", 0xBC: "comma",
            0xBD: "minus", 0xBE: "period", 0xBF: "slash", 0xC0: "grave", 0xDB: "lbracket", 0xDC: "backslash",
            0xDD: "rbracket", 0xDE: "apostrophe"}
for _i in range(12):
    VK_TO_SC[0x70 + _i] = f"f{_i + 1}"
for _i in range(10):
    VK_TO_SC[0x60 + _i] = f"np_{_i}"
for _c in range(0x30, 0x3A):
    VK_TO_SC[_c] = chr(_c)
for _c in range(0x41, 0x5B):
    VK_TO_SC[_c] = chr(_c).lower()

PAD_BUTTONS = [(0x0001, "D-pad up"), (0x0002, "D-pad down"), (0x0004, "D-pad left"), (0x0008, "D-pad right"),
               (0x0010, "Start"), (0x0020, "Back"), (0x0040, "Left stick click"), (0x0080, "Right stick click"),
               (0x0100, "LB"), (0x0200, "RB"), (0x0400, "Xbox button"), (0x1000, "A"), (0x2000, "B"), (0x4000, "X"),
               (0x8000, "Y"), (0x10000, "LT"), (0x20000, "RT")]

if WIN:
    import ctypes
    import winsound
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32")
    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = ctypes.c_short

    class XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                    ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                    ("sThumbRY", ctypes.c_short)]

    class XINPUT_STATE(ctypes.Structure):
        _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD), ("_pad", wintypes.DWORD)]

    _xin = None
    _xin_get = None
    for _dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            _xin = ctypes.WinDLL(_dll)
            break
        except OSError:
            continue
    if _xin is not None:
        try:
            _xin_get = _xin[100]
        except (AttributeError, OSError):
            _xin_get = getattr(_xin, "XInputGetState", None)
        if _xin_get is not None:
            _xin_get.argtypes = (wintypes.DWORD, ctypes.POINTER(XINPUT_STATE))
            _xin_get.restype = wintypes.DWORD

    class JOYINFOEX(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in ("dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos",
                                                    "dwVpos", "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1",
                                                    "dwReserved2")]

    _winmm = ctypes.WinDLL("winmm")
    _winmm.joyGetPosEx.argtypes = (wintypes.UINT, ctypes.POINTER(JOYINFOEX))
    _winmm.mciSendStringW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HANDLE)

    def key_down(vk):
        return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

    def pad_buttons(index):
        if _xin_get is None:
            return None
        st = XINPUT_STATE()
        if _xin_get(index, ctypes.byref(st)) != 0:
            return None
        b = st.Gamepad.wButtons
        if st.Gamepad.bLeftTrigger > 140:
            b |= 0x10000
        if st.Gamepad.bRightTrigger > 140:
            b |= 0x20000
        return b

    def joy_buttons(jid):
        info = JOYINFOEX()
        info.dwSize = ctypes.sizeof(JOYINFOEX)
        info.dwFlags = 0x80
        if _winmm.joyGetPosEx(jid, ctypes.byref(info)) != 0:
            return None
        return info.dwButtons

    def mci(cmd):
        buf = ctypes.create_unicode_buffer(256)
        err = _winmm.mciSendStringW(cmd, buf, 255, None)
        return err, buf.value
else:
    def key_down(vk):
        return False

    def pad_buttons(index):
        return None

    def joy_buttons(jid):
        return None

    def mci(cmd):
        return 1, ""


def pad_name(mask):
    return " + ".join(n for m, n in PAD_BUTTONS if mask & m) or "nothing"


def source_down(src):
    if not src:
        return False
    kind = src.get("kind")
    if kind == "key":
        return key_down(src["vk"])
    if kind == "pad":
        b = pad_buttons(src.get("index", 0))
        return b is not None and (b & src["mask"]) == src["mask"]
    if kind == "joy":
        b = joy_buttons(src["id"])
        return b is not None and (b & src["mask"]) == src["mask"]
    return False


def source_sc_key(src):
    if src and src.get("kind") == "key":
        return VK_TO_SC.get(src["vk"])
    return None


class Capture:
    def __init__(self):
        self.joys = [j for j in range(16) if joy_buttons(j) is not None]
        self.base_joy = {j: joy_buttons(j) or 0 for j in self.joys}
        self.pads = [i for i in range(4) if pad_buttons(i) is not None]
        self.best = None
        self.started = time.time()
        self.armed = False

    def poll(self):
        if not self.armed:
            if time.time() - self.started > 0.35 and not key_down(0x01):
                self.armed = True
            return None
        pressed = None
        for i in self.pads:
            b = pad_buttons(i) or 0
            if b:
                if self.best and self.best.get("kind") == "pad":
                    b |= self.best["mask"]
                pressed = {"kind": "pad", "index": i, "mask": b, "name": f"Controller: {pad_name(b)}"}
                break
        if not pressed:
            for vk in list(range(0x02, 0x07)) + list(range(0x08, 0xFF)):
                if vk in (0x10, 0x11, 0x12, 0x15, 0x19, 0x1C, 0x1D):
                    continue
                if key_down(vk):
                    pressed = {"kind": "key", "vk": vk, "name": VK_NAMES.get(vk, f"Key {vk}")}
                    break
        if not pressed:
            for j in self.joys:
                b = (joy_buttons(j) or 0) & ~self.base_joy.get(j, 0)
                if b:
                    bit = (b & -b).bit_length()
                    pressed = {"kind": "joy", "id": j, "mask": b & -b, "name": f"Joystick {j + 1} button {bit}"}
                    break
        if pressed:
            self.best = pressed
            return None
        if self.best:
            return self.best
        return None


class PTTWatcher(threading.Thread):
    def __init__(self, get_source, on_down, on_up):
        super().__init__(daemon=True, name="ptt")
        self.get_source = get_source
        self.on_down = on_down
        self.on_up = on_up
        self.paused = False
        self.held = False

    def run(self):
        while True:
            try:
                down = False if self.paused else source_down(self.get_source())
                if down and not self.held:
                    self.held = True
                    self.on_down("ptt")
                elif not down and self.held:
                    self.held = False
                    self.on_up("ptt")
            except Exception:
                traceback.print_exc()
            time.sleep(0.02)


def input_devices():
    if sd is None:
        return []
    try:
        api = sd.query_devices(kind="input").get("hostapi", 0)
        devs = sd.query_devices()
        out = [(i, d["name"]) for i, d in enumerate(devs) if d.get("max_input_channels", 0) > 0 and d.get("hostapi") == api]
        return out or [(i, d["name"]) for i, d in enumerate(devs) if d.get("max_input_channels", 0) > 0]
    except Exception:
        return []


class Recorder:
    RATE = 16000

    def __init__(self):
        self.stream = None
        self.frames = []
        self.level = 0.0
        self.device = None

    def available(self):
        return sd is not None and np is not None

    def _cb(self, data, frames, t, status):
        self.frames.append(data.copy())
        try:
            self.level = float(np.sqrt(np.mean(data ** 2)))
        except Exception:
            pass

    def start(self):
        if not self.available():
            raise RuntimeError("Voice packages aren't installed. Run Install.bat.")
        self.frames = []
        self.stream = sd.InputStream(samplerate=self.RATE, channels=1, dtype="float32", callback=self._cb,
                                     device=self.device)
        self.stream.start()

    def stop(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                time.sleep(0.07)
                s.stop()
                s.close()
            except Exception:
                pass
        self.level = 0.0
        if not self.frames:
            return None
        return np.concatenate(self.frames, axis=0).reshape(-1)


class Transcriber:
    PROMPT = ("Star Citizen co-pilot commands: gear down, gear up, lights on, lights off, shields up, drop shields, weapons online, "
              "weapons offline, guns hot, flares, chaff, decoys, max power to shields, max power to weapons, balance power, "
              "target highest threat, target attacker, next hostile, target subsystem, unlock target, NAV mode, SCM mode, quantum, "
              "engage quantum, flight ready, request landing, autoland, VTOL, decouple, gimbals, mobiGlas, star map, armistice, "
              "CrimeStat, aUEC, SCU, Pyro, Stanton, Nyx, Ruin Station, Checkmate, Orbituary, Levski, Lorville, Area18, New Babbage, "
              "Orison, Grim HEX, Hadanite, Quantainium, Laranite, Agricium, Perseus, Guardian, Alpha Wolf, Cutlass, Gladius.")

    def __init__(self, models_dir):
        self.models_dir = Path(models_dir)
        self.model = None
        self.status = "not loaded"
        self.size = None
        self.device = None
        self.lock = threading.Lock()

    def available(self):
        return np is not None and importlib.util.find_spec("faster_whisper") is not None

    def load(self, size="base.en", device="cpu"):
        with self.lock:
            if self.model is not None and self.size == size and self.device == device:
                return
            self.model = None
            self.status = "loading speech model…"
            try:
                from faster_whisper import WhisperModel
            except Exception:
                self.status = "voice packages missing (run Install.bat)"
                return
            self.models_dir.mkdir(parents=True, exist_ok=True)
            tries = [("cuda", "float16"), ("cpu", "int8")] if device == "cuda" else [("cpu", "int8")]
            last = ""
            for dev, ct in tries:
                try:
                    threads = min(8, max(4, (os.cpu_count() or 8) // 2))
                    m = WhisperModel(size, device=dev, compute_type=ct, download_root=str(self.models_dir), cpu_threads=threads)
                    segs, _ = m.transcribe(np.zeros(16000, dtype=np.float32), language="en", beam_size=1)
                    list(segs)
                    self.model = m
                    self.size = size
                    self.device = device
                    self.status = f"ready ({size} on {'GPU' if dev == 'cuda' else 'CPU'})"
                    return
                except Exception as ex:
                    last = str(ex).splitlines()[0][:120] if str(ex) else type(ex).__name__
            self.status = f"speech model failed: {last}"

    def transcribe(self, audio):
        with self.lock:
            if self.model is None:
                raise RuntimeError("Speech model isn't loaded yet.")
            segs, _ = self.model.transcribe(audio.astype(np.float32), language="en", beam_size=1,
                                            initial_prompt=self.PROMPT, vad_filter=False, without_timestamps=True,
                                            condition_on_previous_text=False)
            return " ".join(s.text.strip() for s in segs).strip()


def _tone_wav(path, freqs, dur=0.06, vol=0.25, rate=22050):
    frames = bytearray()
    for f in freqs:
        n = int(rate * dur)
        for i in range(n):
            env = min(1.0, i / (rate * 0.005), (n - i) / (rate * 0.008))
            frames += struct.pack("<h", int(32767 * vol * env * math.sin(2 * math.pi * f * i / rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


SAPI_SCRIPT = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
[Console]::Out.WriteLine("ready")
while (($l = [Console]::In.ReadLine()) -ne $null) {
  $p = $l.Split("`t", 3)
  try { $s.Rate = [int]$p[0]; $s.Volume = [int]$p[1] } catch {}
  $s.Speak($p[2])
  [Console]::Out.WriteLine("done")
}
"""


class Speaker(threading.Thread):
    def __init__(self, get_settings, on_state=None):
        super().__init__(daemon=True, name="speaker")
        self.get_settings = get_settings
        self.on_state = on_state or (lambda s: None)
        self.q = queue.Queue()
        self.interrupt = threading.Event()
        self.tmp = Path(tempfile.gettempdir()) / "sc_copilot"
        self.cache = self.tmp / "voice_cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.speaking = False
        self.edge_ok = None
        self.last_error = ""
        self.pending = {}
        self.plock = threading.Lock()
        self.sapi = None
        self.sapi_out = queue.Queue()
        self.chirps = {}
        self.kokoro = None
        try:
            _tone_wav(self.tmp / "listen.wav", [880, 1320])
            _tone_wav(self.tmp / "done.wav", [1320, 990])
            _tone_wav(self.tmp / "error.wav", [440, 330], dur=0.09)
            self.chirps = {k: self.tmp / f"{k}.wav" for k in ("listen", "done", "error")}
        except Exception:
            pass
        self._prune()

    def _prune(self):
        try:
            files = sorted(list(self.cache.glob("*.mp3")) + list(self.cache.glob("*.wav")), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[600:]:
                f.unlink()
            for f in self.cache.glob("*.part"):
                f.unlink()
        except OSError:
            pass

    def chirp(self, name):
        if not WIN or name not in self.chirps or not self.get_settings().get("chirps", True):
            return
        try:
            winsound.PlaySound(str(self.chirps[name]), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass

    def say(self, text, priority=False, force=False):
        if not text:
            return
        if priority:
            self.clear()
        elif not force and self.q.qsize() >= 3:
            return
        self.q.put(text)
        s = self.get_settings()
        if self._engine(s) != "sapi" and self.speaking:
            self._prefetch(text, s)

    def warm(self, texts):
        s = self.get_settings()
        if self._engine(s) == "sapi":
            threading.Thread(target=self._sapi_start, daemon=True).start()
            return
        for t in texts:
            if not self._cached(t, s):
                self._prefetch(t, s)

    def clear(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def stop(self):
        self.clear()
        self.interrupt.set()

    def _engine(self, s):
        e = s.get("tts_engine", "neural")
        if e == "kokoro" and (self.kokoro is None or not self.kokoro.installed() or not self.kokoro.package_ok()):
            return "neural"
        return e if e in ("kokoro", "neural", "sapi") else "neural"

    def _fx(self, s):
        p = s.get("voice_fx", "off")
        amt = max(0, min(100, int(s.get("voice_fx_amount", 100)))) / 100.0
        return (p, amt) if p != "off" and amt > 0 and np is not None and FX is not None else ("off", 0.0)

    def _key(self, text, s, engine=None):
        engine = engine or self._engine(s)
        voice = s.get("kokoro_voice", KOKORO_DEFAULT) if engine == "kokoro" else s.get("voice", VOICES[0][0])
        fx, amt = self._fx(s)
        raw = f"{engine}|{voice}|{int(s.get('tts_rate', 0))}|{fx}|{amt:.2f}|{text}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _cached(self, text, s):
        k = self._key(text, s)
        for ext in (".wav", ".mp3"):
            p = self.cache / (k + ext)
            if p.exists() and p.stat().st_size > 0:
                return p
        return None

    def _finish(self, audio, sr, s, key):
        fx, amt = self._fx(s)
        out = FX.apply(audio, sr, fx, amt) if FX is not None else audio
        path = self.cache / (key + ".wav")
        part = path.with_name(path.stem + f".{threading.get_ident()}.part")
        write_wav(part, out, sr)
        try:
            os.replace(part, path)
        except OSError:
            return part
        return path

    def _synth(self, text, s):
        p = self._cached(text, s)
        if p:
            return p
        engine = self._engine(s)
        if engine == "kokoro":
            try:
                speed = 1.0 + int(s.get("tts_rate", 0)) / 100.0
                audio, sr = self.kokoro.synth(text, s.get("kokoro_voice", KOKORO_DEFAULT), speed)
                return self._finish(audio, sr, s, self._key(text, s, "kokoro"))
            except Exception as ex:
                self.last_error = f"Kokoro failed ({str(ex)[:80]}); using Microsoft voice"
                engine = "neural"
        key = self._key(text, s, "neural")
        mp3 = self.cache / (key + ".mp3")
        part = mp3.with_name(mp3.stem + f".{threading.get_ident()}.part")
        if not self._edge(text, s, part):
            try:
                part.unlink()
            except OSError:
                pass
            return None
        fx, _ = self._fx(s)
        if fx != "off":
            try:
                audio, sr = decode_mp3(part)
                path = self._finish(audio, sr, s, key)
                try:
                    part.unlink()
                except OSError:
                    pass
                return path
            except Exception:
                self.last_error = "Couldn't add the voice effect (soundfile missing?), playing it clean"
        try:
            os.replace(part, mp3)
        except OSError:
            return part
        return mp3

    def _prefetch(self, text, s):
        with self.plock:
            if text in self.pending:
                return
            ev = threading.Event()
            box = {}
            self.pending[text] = (ev, box)

        def go():
            try:
                box["path"] = self._synth(text, s)
            finally:
                ev.set()
        threading.Thread(target=go, daemon=True).start()

    def _audio_for(self, text, s):
        with self.plock:
            p = self.pending.pop(text, None)
        if p:
            p[0].wait(20)
            return p[1].get("path")
        return self._synth(text, s)

    def _peek(self):
        with self.q.mutex:
            return self.q.queue[0] if self.q.queue else None

    def run(self):
        while True:
            text = self.q.get()
            self.interrupt.clear()
            self.speaking = True
            self.on_state(True)
            try:
                s = self.get_settings()
                if self._engine(s) != "sapi":
                    path = self._audio_for(text, s)
                    nxt = self._peek()
                    if nxt:
                        self._prefetch(nxt, s)
                    if not self.interrupt.is_set():
                        if path:
                            self._play(path, s)
                        else:
                            self._sapi(text, s)
                else:
                    self._sapi(text, s)
            except Exception:
                self.last_error = traceback.format_exc(limit=2)
            finally:
                if self.q.empty():
                    self.speaking = False
                    self.on_state(False)

    def _edge(self, text, s, path):
        try:
            import edge_tts
        except Exception:
            self.last_error = "edge-tts not installed; using Windows voice"
            return False
        rate = int(s.get("tts_rate", 0))
        try:
            async def go():
                c = edge_tts.Communicate(text, s.get("voice", VOICES[0][0]), rate=f"{rate:+d}%")
                await asyncio.wait_for(c.save(str(path)), timeout=15)
            asyncio.run(go())
            self.edge_ok = True
            return path.exists() and path.stat().st_size > 0
        except Exception as ex:
            self.edge_ok = False
            self.last_error = f"Neural voice failed ({type(ex).__name__}); using Windows voice"
            return False

    def _play(self, path, s):
        if str(path).endswith(".wav") and sd is not None and np is not None:
            try:
                self._play_sd(path, s)
                return
            except Exception:
                self.last_error = traceback.format_exc(limit=2)
        self._play_mci(path, s)

    def _play_sd(self, path, s):
        data, sr = read_wav(path)
        gain = max(0, min(100, int(s.get("volume", 90)))) / 100.0
        sd.play(data * gain, sr)
        t0 = time.time()
        time.sleep(0.05)
        while time.time() - t0 < 90:
            if self.interrupt.is_set():
                sd.stop()
                return
            st = sd.get_stream()
            if st is None or not st.active:
                break
            time.sleep(0.02)

    def _play_mci(self, path, s):
        if not WIN:
            return
        mci("close sccopilot_tts")
        err, _ = mci(f'open "{path}" type mpegvideo alias sccopilot_tts')
        if err:
            return
        vol = int(max(0, min(100, s.get("volume", 90))) * 10)
        mci(f"setaudio sccopilot_tts volume to {vol}")
        mci("play sccopilot_tts")
        t0 = time.time()
        while time.time() - t0 < 60:
            if self.interrupt.is_set():
                break
            err, mode = mci("status sccopilot_tts mode")
            if err or mode != "playing":
                break
            time.sleep(0.03)
        mci("stop sccopilot_tts")
        mci("close sccopilot_tts")

    def _sapi_start(self):
        if not WIN:
            return False
        if self.sapi is not None and self.sapi.poll() is None:
            return True
        enc = base64.b64encode(SAPI_SCRIPT.encode("utf-16-le")).decode()
        try:
            self.sapi = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         creationflags=NO_WINDOW, text=True, encoding="utf-8", bufsize=1)
        except Exception:
            self.sapi = None
            self.last_error = traceback.format_exc(limit=2)
            return False
        self.sapi_out = queue.Queue()
        proc = self.sapi

        def reader():
            for line in proc.stdout:
                self.sapi_out.put(line.strip())
        threading.Thread(target=reader, daemon=True).start()
        try:
            return self.sapi_out.get(timeout=8) == "ready"
        except queue.Empty:
            return False

    def _sapi(self, text, s):
        if not self._sapi_start():
            return
        rate = max(-10, min(10, int(s.get("tts_rate", 0)) // 10))
        vol = int(max(0, min(100, s.get("volume", 90))))
        clean = " ".join(text.replace("\t", " ").split())
        try:
            self.sapi.stdin.write(f"{rate}\t{vol}\t{clean}\n")
            self.sapi.stdin.flush()
        except Exception:
            self._sapi_kill()
            return
        t0 = time.time()
        while time.time() - t0 < 60:
            if self.interrupt.is_set():
                self._sapi_kill()
                return
            try:
                if self.sapi_out.get(timeout=0.05) == "done":
                    return
            except queue.Empty:
                if self.sapi is None or self.sapi.poll() is not None:
                    return

    def _sapi_kill(self):
        p, self.sapi = self.sapi, None
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass
