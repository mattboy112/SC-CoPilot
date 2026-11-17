import json
import os
import re
import shutil
import string
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import sc_paths as P

APP_DIR = P.APP_DIR
SNAPSHOT = P.resource("sc_default_binds.json")
CACHE = P.cache("sc_default_binds_cache.json")
PROFILE_ENTRY = b"Data\\Libs\\Config\\defaultProfile.xml"

MODIFIERS = {"lalt", "ralt", "lctrl", "rctrl", "lshift", "rshift"}
MOUSE_OK = {"mouse3", "mouse4", "mouse5"}
BUSY = [0.0]


def busy():
    """True while the co-pilot is pressing keys (so the key watcher doesn't mistake them for yours)."""
    return time.time() < BUSY[0]

SCAN = {
    "escape": (0x01, False), "1": (0x02, False), "2": (0x03, False), "3": (0x04, False), "4": (0x05, False),
    "5": (0x06, False), "6": (0x07, False), "7": (0x08, False), "8": (0x09, False), "9": (0x0A, False), "0": (0x0B, False),
    "minus": (0x0C, False), "equals": (0x0D, False), "backspace": (0x0E, False), "tab": (0x0F, False), "q": (0x10, False),
    "w": (0x11, False), "e": (0x12, False), "r": (0x13, False), "t": (0x14, False), "y": (0x15, False), "u": (0x16, False),
    "i": (0x17, False), "o": (0x18, False), "p": (0x19, False), "lbracket": (0x1A, False), "rbracket": (0x1B, False),
    "enter": (0x1C, False), "lctrl": (0x1D, False), "a": (0x1E, False), "s": (0x1F, False), "d": (0x20, False),
    "f": (0x21, False), "g": (0x22, False), "h": (0x23, False), "j": (0x24, False), "k": (0x25, False), "l": (0x26, False),
    "semicolon": (0x27, False), "apostrophe": (0x28, False), "grave": (0x29, False), "lshift": (0x2A, False),
    "backslash": (0x2B, False), "z": (0x2C, False), "x": (0x2D, False), "c": (0x2E, False), "v": (0x2F, False),
    "b": (0x30, False), "n": (0x31, False), "m": (0x32, False), "comma": (0x33, False), "period": (0x34, False),
    "slash": (0x35, False), "rshift": (0x36, False), "np_multiply": (0x37, False), "lalt": (0x38, False),
    "space": (0x39, False), "capslock": (0x3A, False), "f1": (0x3B, False), "f2": (0x3C, False), "f3": (0x3D, False),
    "f4": (0x3E, False), "f5": (0x3F, False), "f6": (0x40, False), "f7": (0x41, False), "f8": (0x42, False),
    "f9": (0x43, False), "f10": (0x44, False), "numlock": (0x45, False), "scrolllock": (0x46, False),
    "np_7": (0x47, False), "np_8": (0x48, False), "np_9": (0x49, False), "np_subtract": (0x4A, False),
    "np_4": (0x4B, False), "np_5": (0x4C, False), "np_6": (0x4D, False), "np_add": (0x4E, False), "np_1": (0x4F, False),
    "np_2": (0x50, False), "np_3": (0x51, False), "np_0": (0x52, False), "np_period": (0x53, False),
    "f11": (0x57, False), "f12": (0x58, False), "np_enter": (0x1C, True), "rctrl": (0x1D, True),
    "np_divide": (0x35, True), "ralt": (0x38, True), "home": (0x47, True), "up": (0x48, True), "pgup": (0x49, True),
    "left": (0x4B, True), "right": (0x4D, True), "end": (0x4F, True), "down": (0x50, True), "pgdn": (0x51, True),
    "insert": (0x52, True), "delete": (0x53, True),
}

PRETTY = {"lalt": "LAlt", "ralt": "RAlt", "lctrl": "LCtrl", "rctrl": "RCtrl", "lshift": "LShift", "rshift": "RShift",
          "np_add": "Num +", "np_subtract": "Num -", "np_multiply": "Num *", "np_divide": "Num /", "np_period": "Num .",
          "np_enter": "Num Enter", "pgup": "PgUp", "pgdn": "PgDn", "lbracket": "[", "rbracket": "]", "semicolon": ";",
          "apostrophe": "'", "grave": "`", "comma": ",", "period": ".", "slash": "/", "backslash": "\\", "minus": "-",
          "equals": "=", "mouse1": "Left mouse", "mouse2": "Right mouse", "mouse3": "Middle mouse", "mouse4": "Mouse 4",
          "mouse5": "Mouse 5", "mwheel_up": "Wheel up", "mwheel_down": "Wheel down", "escape": "Esc", "backspace": "Backspace",
          "space": "Space", "tab": "Tab", "enter": "Enter", "insert": "Insert", "delete": "Delete", "home": "Home", "end": "End",
          "up": "Up", "down": "Down", "left": "Left", "right": "Right", "capslock": "Caps Lock"}

# id, label, SC action, group
ACTIONS = [
    ("flight_ready", "Flight ready (power up and start engines)", "v_flightready", "Flight"),
    ("power_on", "Ship power on", "v_power_set_on", "Flight"),
    ("power_off", "Ship power off", "v_power_set_off", "Flight"),
    ("power_toggle", "Ship power (toggle)", "v_power_toggle", "Flight"),
    ("gear_down", "Landing gear down", "v_deploy_landing_system", "Flight"),
    ("gear_up", "Landing gear up", "v_retract_landing_system", "Flight"),
    ("gear_toggle", "Landing gear (toggle)", "v_toggle_landing_system", "Flight"),
    ("request_landing", "Request landing / takeoff (ATC)", "v_atc_request", "Flight"),
    ("autoland", "Auto-land", "v_autoland", "Flight"),
    ("vtol_on", "VTOL on", "v_vtol_on", "Flight"),
    ("vtol_off", "VTOL off", "v_vtol_off", "Flight"),
    ("vtol_toggle", "VTOL (toggle)", "v_vtol_toggle", "Flight"),
    ("decouple_on", "Decoupled mode on", "v_ifcs_vector_decoupling_on", "Flight"),
    ("decouple_off", "Decoupled mode off", "v_ifcs_vector_decoupling_off", "Flight"),
    ("decouple_toggle", "Decoupled mode (toggle)", "v_ifcs_vector_decoupling_toggle", "Flight"),
    ("gsafe_toggle", "G-safe (toggle)", "v_ifcs_toggle_gforce_safety", "Flight"),
    ("esp_toggle", "ESP precision aim assist (toggle)", "v_ifcs_toggle_esp", "Flight"),
    ("prox_assist_toggle", "Proximity assist (toggle)", "v_ifcs_proximity_assist_toggle", "Flight"),
    ("nav_mode", "NAV mode", "v_master_mode_set_nav", "Modes"),
    ("scm_mode", "SCM mode (combat)", "v_master_mode_set_scm", "Modes"),
    ("master_mode_cycle", "Switch NAV / SCM (hold)", "v_master_mode_cycle_long", "Modes"),
    ("qt_engage", "Engage quantum drive", "v_toggle_qdrive_engagement", "Modes"),
    ("jump_request", "Jump point: request jump", "v_toggle_jump_request", "Modes"),
    ("guns_mode", "Guns mode", "v_set_guns_mode", "Modes"),
    ("missile_mode", "Missile mode", "v_set_missile_mode", "Modes"),
    ("scan_mode", "Scan mode", "v_set_scan_mode", "Modes"),
    ("mining_mode", "Mining mode", "v_set_mining_mode", "Modes"),
    ("salvage_mode", "Salvage mode", "v_set_salvage_mode", "Modes"),
    ("lights_on", "Lights on", "v_lights_on", "Ship"),
    ("lights_off", "Lights off", "v_lights_off", "Ship"),
    ("lights_toggle", "Lights (toggle)", "v_lights", "Ship"),
    ("shields_on", "Shields on", "v_power_set_shields_on", "Ship"),
    ("shields_off", "Shields off", "v_power_set_shields_off", "Ship"),
    ("shields_toggle", "Shields (toggle)", "v_power_toggle_shields", "Ship"),
    ("weapons_power_on", "Weapons power on", "v_power_set_weapons_on", "Ship"),
    ("weapons_power_off", "Weapons power off", "v_power_set_weapons_off", "Ship"),
    ("weapons_power_toggle", "Weapons power (toggle)", "v_power_toggle_weapons", "Ship"),
    ("thrusters_on", "Thrusters on", "v_power_set_thrusters_on", "Ship"),
    ("thrusters_off", "Thrusters off", "v_power_set_thrusters_off", "Ship"),
    ("thrusters_toggle", "Thrusters (toggle)", "v_power_toggle_thrusters", "Ship"),
    ("doors_open", "Open all doors", "v_open_all_doors", "Ship"),
    ("doors_close", "Close all doors", "v_close_all_doors", "Ship"),
    ("doors_toggle", "Doors (toggle)", "v_toggle_all_doors", "Ship"),
    ("doors_lock", "Lock all doors", "v_lock_all_doors", "Ship"),
    ("doors_unlock", "Unlock all doors", "v_unlock_all_doors", "Ship"),
    ("doorlocks_toggle", "Door locks (toggle)", "v_toggle_all_doorlocks", "Ship"),
    ("ports_lock_toggle", "Port locks (toggle)", "v_toggle_all_portlocks", "Ship"),
    ("night_vision_toggle", "Night vision (toggle)", "v_light_amplification_toggle", "Ship"),
    ("max_shields", "Power: max to shields", "v_engineering_assignment_shields_max", "Power"),
    ("max_weapons", "Power: max to weapons", "v_engineering_assignment_weapons_max", "Power"),
    ("max_engines", "Power: max to engines", "v_engineering_assignment_engine_max", "Power"),
    ("power_reset", "Power: reset / balance", "v_engineering_assignment_reset", "Power"),
    ("less_shields", "Power: one less to shields", "v_engineering_assignment_shields_decrease", "Power"),
    ("less_weapons", "Power: one less to weapons", "v_engineering_assignment_weapons_decrease", "Power"),
    ("less_engines", "Power: one less to engines", "v_engineering_assignment_engine_decrease", "Power"),
    ("min_shields", "Power: shields to minimum", "v_engineering_assignment_shields_min", "Power"),
    ("min_weapons", "Power: weapons to minimum", "v_engineering_assignment_weapons_min", "Power"),
    ("min_engines", "Power: engines to minimum", "v_engineering_assignment_engine_min", "Power"),
    ("more_shields", "Power: one more to shields", "v_engineering_assignment_shields_increase", "Power"),
    ("more_weapons", "Power: one more to weapons", "v_engineering_assignment_weapons_increase", "Power"),
    ("more_engines", "Power: one more to engines", "v_engineering_assignment_engine_increase", "Power"),
    ("decoys", "Launch decoys (flares)", "v_weapon_countermeasure_decoy_launch", "Combat"),
    ("decoys_panic", "Panic decoys (dump them all)", "v_weapon_countermeasure_decoy_launch_panic", "Combat"),
    ("noise", "Launch noise (chaff)", "v_weapon_countermeasure_noise_launch", "Combat"),
    ("gimbals_toggle", "Gimbal lock (toggle)", "v_weapon_gimbals_state_toggle", "Combat"),
    ("gimbals_lock", "Gimbals locked", "v_weapon_gimbals_state_set_locked", "Combat"),
    ("gimbals_unlock", "Gimbals unlocked", "v_weapon_gimbals_state_set_unlocked", "Combat"),
    ("target_hostile", "Target next hostile", "v_target_cycle_hostile_fwd", "Combat"),
    ("target_attacker", "Target next attacker", "v_target_cycle_attacker_fwd", "Combat"),
    ("target_ahead", "Target ahead (in view)", "v_target_cycle_in_view_fwd", "Combat"),
    ("target_unlock", "Unlock target", "v_target_unlock", "Combat"),
    ("target_reticle", "Target what's under the reticle", "v_target_under_reticle", "Combat"),
    ("target_subitem", "Target next subsystem / component", "v_target_cycle_subitem_fwd", "Combat"),
    ("target_friendly", "Target next friendly", "v_target_cycle_friendly_fwd", "Combat"),
    ("target_pin", "Pin the current target", "v_target_pin_selected", "Combat"),
    ("auto_target_toggle", "Auto-targeting (toggle)", "v_auto_targeting_toggle_long", "Combat"),
    ("ping", "Radar ping", "v_invoke_ping", "Combat"),
    ("hail", "Hail target", "v_target_hail", "Combat"),
    ("starmap", "Star map", "v_starmap", "Panels"),
    ("mobiglas", "mobiGlas", "mobiglas", "Panels"),
    ("camera", "Cycle camera view", "v_view_cycle_fwd", "Panels"),
    ("visor_wipe", "Wipe visor", "visor_wipe", "Panels"),
]
ACTION_INDEX = {a[0]: {"id": a[0], "label": a[1], "sc": a[2], "group": a[3]} for a in ACTIONS}
ACTION_LABEL = {a[2]: a[1] for a in ACTIONS}

SKIP_MAPS = {"debug", "flycam", "spectator", "view_director_mode", "character_customizer", "RemoteRigidEntityController",
             "server_renderer", "ui_textfield"}
FREE_POOL = ["np_1", "np_2", "np_3", "np_4", "np_5", "np_6", "np_7", "np_8", "np_9", "np_0", "np_enter", "insert", "delete",
             "home", "end", "pgup", "pgdn", "semicolon", "apostrophe", "backslash", "minus", "equals"]
FRIENDLY = {"toggle_chat": "Toggle chat window", "notification_accept": "Accept invite/notification",
            "ui_notification_accept": "Accept invite/notification", "notification_decline": "Decline invite/notification",
            "ui_notification_decline": "Decline invite/notification", "ui_notification_ignore": "Ignore invite/notification",
            "hmd_toggle": "VR headset toggle", "headtrack_enabled": "Head tracking on/off", "foip_cyclechannel": "FOIP channel",
            "foip_recalibrate": "FOIP recalibrate", "hmd_recenter": "VR recenter", "headtrack_recenter_device": "Head tracking recenter",
            "flymode": "Debug fly mode"}
MOUSE_KEYS = {"mouse1", "mouse2", "mouse3", "mouse4", "mouse5"}


def friendly(name):
    return FRIENDLY.get(name) or ACTION_LABEL.get(name) or name.replace("v_", "", 1).replace("_", " ")


def pretty_key(spec):
    if not spec:
        return ""
    parts = spec.split("+")
    return "+".join(PRETTY.get(p, p.upper() if len(p) == 1 else p.replace("np_", "Num ").title()) for p in parts)


def split_key(spec):
    """'lalt+n' -> ('n', ('lalt',)); 'f6+lalt' -> ('f6', ('lalt',)); 'lshift' -> ('lshift', ())."""
    toks = [t.strip().lower() for t in (spec or "").split("+") if t.strip()]
    if not toks:
        return None
    keys = [t for t in toks if t not in MODIFIERS]
    if not keys:
        return toks[-1], tuple(toks[:-1])
    if len(keys) > 1:
        return None
    return keys[0], tuple(t for t in toks if t in MODIFIERS)


def norm_spec(spec):
    s = split_key(spec)
    if not s:
        return ""
    key, mods = s
    order = ["lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt"]
    return "+".join(sorted(mods, key=order.index) + [key])


# ---------------------------------------------------------------- game files

def candidate_installs():
    out = []
    env = os.environ.get("SC_INSTALL")
    if env:
        out.append(Path(env))
    roots = [f"{d}:\\" for d in string.ascii_uppercase if d not in "AB"] if sys.platform == "win32" else []
    for r in roots:
        for sub in ("Program Files\\Roberts Space Industries\\StarCitizen", "Roberts Space Industries\\StarCitizen",
                    "Games\\Roberts Space Industries\\StarCitizen", "StarCitizen", "Games\\StarCitizen"):
            out.append(Path(r) / sub / "LIVE")
    return out


def find_install(custom=None):
    if custom:
        p = Path(custom)
        if (p / "Data.p4k").exists() or (p / "Game.log").exists():
            return p
        if (p / "LIVE" / "Data.p4k").exists():
            return p / "LIVE"
    for p in candidate_installs():
        try:
            if (p / "Data.p4k").exists():
                return p
        except OSError:
            continue
    return None


def _cryxml(raw):
    if raw[:8] != b"CryXmlB\x00":
        return ET.fromstring(raw)
    (_flen, ntp, nc, atp, ac, ctp, cc, sdp, _sds) = struct.unpack_from("<9i", raw, 8)

    def s(off):
        a = sdp + off
        return raw[a:raw.index(b"\x00", a)].decode("utf-8", "replace")
    nodes = [struct.unpack_from("<iihhiiii", raw, ntp + i * 28) for i in range(nc)]
    attrs = [struct.unpack_from("<ii", raw, atp + i * 8) for i in range(ac)]
    childs = struct.unpack_from("<%di" % cc, raw, ctp)
    els = []
    for (nameo, conto, nattr, _nchild, _parent, fattr, _fchild, _r) in nodes:
        e = ET.Element(s(nameo))
        for k in range(nattr):
            an, av = attrs[fattr + k]
            e.set(s(an), s(av))
        t = s(conto)
        if t:
            e.text = t
        els.append(e)
    for i, (_n, _c, _na, nchild, _p, _fa, fchild, _r) in enumerate(nodes):
        for k in range(nchild):
            els[i].append(els[childs[fchild + k]])
    return els[0]


def read_p4k_entry(p4k, wanted=PROFILE_ENTRY):
    import zstandard
    size = os.path.getsize(p4k)
    with open(p4k, "rb") as f:
        f.seek(max(0, size - 65536 - 22))
        tail = f.read()
        i = tail.rfind(b"PK\x06\x07")
        if i < 0:
            raise RuntimeError("Data.p4k doesn't look like a p4k archive")
        off64 = struct.unpack("<Q", tail[i + 8:i + 16])[0]
        f.seek(off64)
        z = f.read(56)
        if z[:4] != b"PK\x06\x06":
            raise RuntimeError("Data.p4k central directory not found")
        cd_size, cd_off = struct.unpack("<QQ", z[40:56])
        f.seek(cd_off)
        low = wanted.lower()
        buf, read, hit = b"", 0, -1
        while read < cd_size:
            data = f.read(min(64 << 20, cd_size - read))
            if not data:
                break
            read += len(data)
            buf += data
            hit = buf.lower().find(low)
            if hit >= 0:
                break
            buf = buf[-512:]
        if hit < 0:
            raise RuntimeError("defaultProfile.xml not in Data.p4k")
        h = buf.rfind(b"PK\x01\x02", 0, hit)
        (_sig, _vm, _vn, _flag, meth, _mt, _md, _crc, csz, usz, fnl, exl, _cml, _dsk, _ia, _ea, lho) = \
            struct.unpack("<IHHHHHHIIIHHHHHII", buf[h:h + 46])
        extra = buf[h + 46 + fnl:h + 46 + fnl + exl]
        j = 0
        while j + 4 <= len(extra):
            hid, hsz = struct.unpack("<HH", extra[j:j + 4])
            if hid == 1:
                vals, k = [], j + 4
                for want in (usz == 0xFFFFFFFF, csz == 0xFFFFFFFF, lho == 0xFFFFFFFF):
                    if want:
                        vals.append(struct.unpack("<Q", extra[k:k + 8])[0])
                        k += 8
                    else:
                        vals.append(None)
                usz = vals[0] if vals[0] is not None else usz
                csz = vals[1] if vals[1] is not None else csz
                lho = vals[2] if vals[2] is not None else lho
                break
            j += 4 + hsz
        f.seek(lho)
        lh = f.read(30)
        lfnl, lexl = struct.unpack("<HH", lh[26:30])
        f.seek(lho + 30 + lfnl + lexl)
        data = f.read(csz)
    if meth == 100:
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=max(usz, 1) * 2)
    if meth == 0:
        return data
    if meth == 8:
        import zlib
        return zlib.decompress(data, -15)
    raise RuntimeError(f"unsupported compression {meth}")


def parse_profile(root, build=""):
    modes = {}
    am = root.find("ActivationModes")
    if am is not None:
        for m in am:
            modes[m.get("name")] = {k: m.get(k) for k in ("onPress", "onHold", "onRelease", "multiTap", "pressTriggerThreshold",
                                                         "releaseTriggerThreshold", "releaseTriggerDelay")}
    actions = []
    for amap in root.findall("actionmap"):
        mn = amap.get("name")
        for a in amap.findall("action"):
            kb = a.get("keyboard")
            mode = a.get("activationMode") or a.get("ActivationMode") or ""
            if kb is None:
                k = a.find("keyboard")
                if k is not None:
                    first = k.find("inputdata")
                    if first is not None:
                        kb = first.get("input")
                        mode = first.get("activationMode") or mode
                    else:
                        kb = k.get("input")
            actions.append({"map": mn, "name": a.get("name"), "kb": (kb or "").strip(), "mode": mode,
                            "onPress": a.get("onPress"), "onHold": a.get("onHold"),
                            "hold": a.get("holdTriggerDelay")})
    return {"build": build, "modes": modes, "actions": actions}


def game_build(install):
    try:
        d = json.loads((Path(install) / "build_manifest.id").read_text(encoding="utf-8", errors="ignore"))
        return d.get("Data", {}).get("Version", "")
    except (OSError, ValueError):
        return ""


def load_defaults(install):
    """Returns (data, source_text). Prefers the live game files, then a cache, then the bundled snapshot."""
    p4k = Path(install) / "Data.p4k" if install else None
    sig = None
    if p4k and p4k.exists():
        st = p4k.stat()
        sig = f"{st.st_size}:{int(st.st_mtime)}"
        try:
            c = json.loads(CACHE.read_text(encoding="utf-8"))
            if c.get("sig") == sig:
                return c["data"], f"game files (build {c['data'].get('build') or '?'})"
        except (OSError, ValueError, KeyError):
            pass
        try:
            raw = read_p4k_entry(p4k)
            data = parse_profile(_cryxml(raw), game_build(install))
            try:
                CACHE.write_text(json.dumps({"sig": sig, "data": data}), encoding="utf-8")
            except OSError:
                pass
            return data, f"game files (build {data.get('build') or '?'})"
        except ImportError:
            why = "zstandard isn't installed (run Install.bat)"
        except Exception as ex:
            why = f"couldn't read Data.p4k ({ex})"
    else:
        why = "Data.p4k wasn't found in the game folder" if install else "the Star Citizen install wasn't found"
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        return data, f"bundled snapshot from {data.get('build', '?')}, because {why}"
    except (OSError, ValueError):
        return {"build": "", "modes": {}, "actions": []}, f"no default keybinds ({why})"


# ---------------------------------------------------------------- Windows input

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)

    LAST_SEND = {"sent": 0, "err": 0}

    def _send_scan(code, ext, up):
        flags = 0x0008 | (0x0002 if up else 0) | (0x0001 if ext else 0)
        inp = INPUT(type=1, ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags, time=0, dwExtraInfo=0))
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        LAST_SEND["sent"] += n
        if not n:
            LAST_SEND["err"] = ctypes.get_last_error()

    def _send_mouse(button, up):
        if button == "mouse3":
            flags, data = (0x0040 if up else 0x0020), 0
        else:
            flags, data = (0x0100 if up else 0x0080), (1 if button == "mouse4" else 2)
        inp = INPUT(type=0, mi=MOUSEINPUT(dx=0, dy=0, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=0))
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        LAST_SEND["sent"] += n
        if not n:
            LAST_SEND["err"] = ctypes.get_last_error()

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (EnumWindowsProc, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR)
    _pid_cache = {"t": 0.0, "pids": set()}

    def _sc_pids():
        """PIDs of StarCitizen.exe from tasklist (no process handles, so nothing for anti-cheat to object to)."""
        now = time.time()
        if now - _pid_cache["t"] < 4:
            return _pid_cache["pids"]
        pids = set()
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq StarCitizen.exe", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=5).stdout
            for line in out.splitlines():
                parts = [x.strip('"') for x in line.split('","')]
                if len(parts) > 1 and parts[0].lower() == "starcitizen.exe" and parts[1].isdigit():
                    pids.add(int(parts[1]))
        except Exception:
            pass
        _pid_cache.update(t=now, pids=pids)
        return pids

    def _pid_of(h):
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        return pid.value

    def _is_sc(h):
        if not h:
            return False
        root = user32.GetAncestor(h, 2) or h
        return _pid_of(root) in _sc_pids()

    def game_window():
        fg = user32.GetForegroundWindow()
        if _is_sc(fg):
            return user32.GetAncestor(fg, 2) or fg
        pids = _sc_pids()
        if not pids:
            return None
        found = []

        def cb(h, _):
            if user32.IsWindowVisible(h) and _pid_of(h) in pids:
                r = wintypes.RECT()
                user32.GetWindowRect(h, ctypes.byref(r))
                found.append(((r.right - r.left) * (r.bottom - r.top), h))
            return True
        user32.EnumWindows(EnumWindowsProc(cb), 0)
        if found:
            return max(found)[1]
        return user32.FindWindowW(None, "Star Citizen") or None

    def focus_game():
        if _is_sc(user32.GetForegroundWindow()):
            return True
        h = game_window()
        if not h:
            return False
        if user32.IsIconic(h):
            user32.ShowWindow(h, 9)
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(h)
        for _ in range(8):
            time.sleep(0.05)
            if _is_sc(user32.GetForegroundWindow()):
                time.sleep(0.15)
                return True
        return False

    def game_process_running():
        return bool(_sc_pids())

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD))
    _elev_cache = {"t": 0.0, "v": None}

    def self_elevated():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _pid_elevated(pid):
        h = kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            tok = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):
                return None
            try:
                elev, ret = wintypes.DWORD(0), wintypes.DWORD(0)
                if advapi32.GetTokenInformation(tok, 20, ctypes.byref(elev), 4, ctypes.byref(ret)):
                    return bool(elev.value)
                return None
            finally:
                kernel32.CloseHandle(tok)
        finally:
            kernel32.CloseHandle(h)

    def game_elevated():
        """True when Star Citizen runs as administrator (then Windows blocks keypresses from a normal app)."""
        now = time.time()
        if now - _elev_cache["t"] < 10:
            return _elev_cache["v"]
        v = None
        for pid in _sc_pids():
            try:
                v = _pid_elevated(pid)
            except Exception:
                v = None
            if v is not None:
                break
        _elev_cache.update(t=now, v=v)
        return v

    def admin_mismatch():
        return game_elevated() is True and not self_elevated()

    def game_focused():
        fg = user32.GetForegroundWindow()
        return bool(fg) and _is_sc(fg)

    def diag():
        fg = user32.GetForegroundWindow()
        return {"fg_pid": _pid_of(fg) if fg else 0, "sc_pids": sorted(_sc_pids()), "fg_is_sc": _is_sc(fg),
                "game_admin": game_elevated(), "app_admin": self_elevated()}
else:
    def _send_scan(code, ext, up):
        pass

    def _send_mouse(button, up):
        pass

    def game_window():
        return None

    def focus_game():
        return False

    def game_process_running():
        return False

    LAST_SEND = {"sent": 0, "err": 0}

    def self_elevated():
        return False

    def game_elevated():
        return None

    def admin_mismatch():
        return False

    def diag():
        return {}

    def game_focused():
        return False


# ---------------------------------------------------------------- binds

class Binds:
    def __init__(self, install=None):
        self.install = Path(install) if install else find_install()
        self.defaults = {"modes": {}, "actions": []}
        self.source = ""
        self.keys = {}       # sc action -> (spec, mode, onPress, onHold, hold)
        self.maps_of = {}    # sc action -> [actionmap names]
        self.rebinds = {}    # (map, action) -> spec ("" = cleared)
        self.used = set()
        self.owners = {}     # normalized key -> {(map, action)} for everything that key does in the game
        self.broken = {}     # (map, action) -> input the game can't use (a keyboard key filed under the mouse)
        self.error = ""
        self.load()

    @property
    def actionmaps_file(self):
        if not self.install:
            return None
        return self.install / "user" / "client" / "0" / "Profiles" / "default" / "actionmaps.xml"

    def load(self):
        self.error = ""
        self.defaults, self.source = load_defaults(self.install)
        self.rebinds = {}
        self.broken = {}
        f = self.actionmaps_file
        if f and f.exists():
            try:
                root = ET.parse(f).getroot()
                for amap in root.iter("actionmap"):
                    for a in amap.findall("action"):
                        for rb in a.findall("rebind"):
                            inp = (rb.get("input") or "").strip()
                            dev, _, key = inp.partition("_")
                            if dev == "kb1" or (dev == "mo1" and key in MOUSE_KEYS):
                                self.rebinds[(amap.get("name"), a.get("name"))] = (key.strip(), rb.get("activationMode") or "")
                            elif dev == "mo1" and key and split_key(key) and split_key(key)[0] not in MOUSE_KEYS:
                                self.broken[(amap.get("name"), a.get("name"))] = inp
            except (ET.ParseError, OSError) as ex:
                self.error = f"Couldn't read actionmaps.xml: {ex}"
        elif not self.install:
            self.error = "Couldn't find your Star Citizen install. Set the folder in Settings."
        self.keys, self.maps_of, self.used, self.owners = {}, {}, set(), {}
        for a in self.defaults.get("actions", []):
            name, mn = a["name"], a["map"]
            self.maps_of.setdefault(name, []).append(mn)
            spec, mode = a["kb"], a["mode"]
            rb = self.rebinds.get((mn, name))
            if rb is not None:
                spec, mode = rb[0], (rb[1] or mode)
            if spec and mn not in SKIP_MAPS:
                for part in spec.split(","):
                    n = norm_spec(part)
                    if n:
                        self.used.add(n)
                        self.owners.setdefault(n, set()).add((mn, name))
            if name not in self.keys and spec:
                self.keys[name] = (spec, mode, a.get("onPress"), a.get("onHold"), a.get("hold"))
        for (mn, name), (spec, mode) in self.rebinds.items():
            if spec:
                self.used.add(norm_spec(spec))
                self.owners.setdefault(norm_spec(spec), set()).add((mn, name))
                if name not in self.maps_of:
                    self.keys.setdefault(name, (spec, mode, None, None, None))

    def spec_for(self, sc):
        k = self.keys.get(sc)
        if not k:
            return None
        s = split_key(k[0])
        if not s:
            return None
        key, mods = s
        if key in SCAN or key in MOUSE_OK:
            if all(m in SCAN for m in mods):
                return k
        return None

    def describe(self, sc):
        k = self.keys.get(sc)
        return pretty_key(k[0]) if k else None

    def pressable(self, sc):
        return self.spec_for(sc) is not None

    def timing(self, mode, on_press, on_hold, hold):
        m = self.defaults.get("modes", {}).get(mode or "")
        if m:
            try:
                if int(m.get("multiTap") or 1) >= 2:
                    return "double", 0.05
                thr = float(m.get("pressTriggerThreshold") or -1)
                if thr > 0:
                    return "hold", thr + 0.15
            except ValueError:
                pass
            return "tap", 0.06
        if on_press != "1" and on_hold == "1":
            try:
                return "hold", float(hold or 0.25) + 0.15
            except ValueError:
                return "hold", 0.4
        return "tap", 0.06

    def press(self, sc, times=1, focus=True, hold=None):
        k = self.spec_for(sc)
        if not k:
            raw = self.keys.get(sc)
            if raw and split_key(raw[0]) and split_key(raw[0])[0] in ("mouse1", "mouse2"):
                return False, "only on a mouse button the app won't press (fire/aim)"
            return False, "no keyboard key"
        if sys.platform != "win32":
            return False, "Windows only"
        if admin_mismatch():
            self._log(sc, k[0], "blocked: game runs as admin")
            return False, "Star Citizen is running as administrator, so Windows blocks keypresses from this app. Use Settings → Restart as administrator"
        if focus and not focus_game():
            self._log(sc, k[0], "focus failed")
            return False, "Star Citizen isn't running" if not game_window() else "couldn't bring Star Citizen to the front"
        LAST_SEND.update(sent=0, err=0)
        spec, mode, on_press, on_hold, hold_s = k
        key, mods = split_key(spec)
        kind, dur = self.timing(mode, on_press, on_hold, hold_s)
        if hold and kind != "double":
            kind, dur = "hold", max(dur, float(hold))
        BUSY[0] = time.time() + 30
        taps = 2 if kind == "double" else 1
        for n in range(max(1, int(times))):
            for m in mods:
                _send_scan(*SCAN[m], False)
                time.sleep(0.03)
            for t in range(taps):
                if key in MOUSE_OK:
                    _send_mouse(key, False)
                    time.sleep(dur)
                    _send_mouse(key, True)
                else:
                    _send_scan(*SCAN[key], False)
                    time.sleep(dur)
                    _send_scan(*SCAN[key], True)
                if t < taps - 1:
                    time.sleep(0.07)
            for m in reversed(mods):
                time.sleep(0.03)
                _send_scan(*SCAN[m], True)
            if n < times - 1:
                time.sleep(0.18)
        BUSY[0] = time.time() + 0.3
        self._log(sc, spec, f"sent {LAST_SEND['sent']} key events" + (f", error {LAST_SEND['err']}" if LAST_SEND["err"] else "") + f", {kind} {dur:.2f}s")
        if LAST_SEND["err"] and not LAST_SEND["sent"]:
            return False, f"Windows refused the keypress (error {LAST_SEND['err']})"
        return True, pretty_key(spec) + (" (held)" if kind == "hold" else " (double-tap)" if kind == "double" else "")

    def _log(self, sc, spec, what):
        try:
            print(f"[{time.strftime('%H:%M:%S')}] press {sc} [{spec}] -> {what} | {diag()}", flush=True)
        except Exception:
            pass

    def _backups(self):
        f = self.actionmaps_file
        return sorted(f.parent.glob("actionmaps.copilot-backup-*.xml")) if f else []

    def app_added(self):
        """Keyboard binds the app's auto-assign added: everything in actionmaps.xml that wasn't in the first backup."""
        backups = self._backups()
        if not backups:
            return {}
        orig = set()
        try:
            for amap in ET.parse(backups[0]).getroot().iter("actionmap"):
                for a in amap.findall("action"):
                    for rb in a.findall("rebind"):
                        orig.add((amap.get("name"), a.get("name"), (rb.get("input") or "").strip()))
        except (ET.ParseError, OSError):
            return {}
        out = {}
        for (mn, name), (spec, _mode) in self.rebinds.items():
            if spec and (mn, name, "kb1_" + spec) not in orig and (mn, name, "mo1_" + spec) not in orig:
                out[(mn, name)] = spec
        for (mn, name), inp in self.broken.items():
            if (mn, name, inp) not in orig:
                out[(mn, name)] = inp
        return out

    def clashes(self):
        """App-added keys that also do something else in the game, plus app-added binds the game mangled."""
        seen, out = set(), []
        for (mn, name), spec in sorted(self.app_added().items()):
            if name in seen:
                continue
            if (mn, name) in self.broken:
                seen.add(name)
                out.append({"action": name, "label": friendly(name), "key": pretty_key(spec.partition("_")[2]) + " (filed under the mouse)",
                            "with": ["nothing, because the game changed it into a bind it can't use"]})
                continue
            others = sorted({friendly(n) for m, n in self.owners.get(norm_spec(spec), set()) if n != name})
            if others:
                seen.add(name)
                out.append({"action": name, "label": friendly(name), "key": pretty_key(spec), "with": others})
        return out

    def fix_clashes(self, avoid=()):
        f = self.actionmaps_file
        if not f or not f.exists():
            raise RuntimeError("actionmaps.xml wasn't found.")
        if game_process_running():
            raise RuntimeError("Close Star Citizen first. It rewrites your keybinds file when it quits.")
        todo = self.clashes()
        if not todo:
            return [], None
        tree = ET.parse(f)
        root = tree.getroot()
        prof = root.find("ActionProfiles")
        if prof is None:
            prof = root
        maps = {m.get("name"): m for m in prof.findall("actionmap")}
        pool = self.free_keys(avoid)
        changed = []
        for c in todo:
            sc = c["action"]
            try:
                spec = next(pool)
            except StopIteration:
                break
            for mn in sorted(set(self.maps_of.get(sc, [])) | {m for m, n in self.broken if n == sc}):
                amap = maps.get(mn)
                if amap is None:
                    amap = ET.SubElement(prof, "actionmap", {"name": mn})
                    maps[mn] = amap
                act = next((a for a in amap.findall("action") if a.get("name") == sc), None)
                if act is None:
                    act = ET.SubElement(amap, "action", {"name": sc})
                for r in list(act.findall("rebind")):
                    dev, _, key = (r.get("input") or "").partition("_")
                    if dev == "kb1" or (dev == "mo1" and key not in MOUSE_KEYS):
                        act.remove(r)
                ET.SubElement(act, "rebind", {"input": "kb1_" + spec})
            self.used.add(norm_spec(spec))
            changed.append((c["label"], c["key"], pretty_key(spec)))
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f.with_name(f"actionmaps.copilot-backup-{stamp}.xml")
        shutil.copy2(f, backup)
        ET.indent(tree, space=" ")
        tree.write(f, encoding="utf-8", xml_declaration=False)
        self.load()
        return changed, backup

    def missing(self):
        return [a for a in ACTIONS if not self.pressable(a[2]) and a[2] in self.maps_of]

    SYNONYMS = {"quantum": ("quantum", "qdrive"), "qt": ("quantum", "qdrive"), "gear": ("landing",), "flares": ("decoy",),
                "flare": ("decoy",), "chaff": ("noise",), "boost": ("afterburner",), "map": ("starmap", "map"),
                "door": ("door",), "doors": ("door",), "light": ("light",), "lights": ("light",), "shields": ("shield",),
                "missiles": ("missile",), "power": ("power", "engineering"), "atc": ("atc",), "land": ("landing", "autoland"),
                "target": ("target",), "lock": ("lock",), "brake": ("brake",), "cruise": ("speed_limiter", "cruise"),
                "decouple": ("decoupling",), "decoupled": ("decoupling",), "scan": ("scan",), "ping": ("ping",)}

    def search(self, query, limit=25):
        q = (query or "").lower().replace(" ", "_")
        words = [w for w in re.split(r"[\s_]+", (query or "").lower()) if w]
        alts = [self.SYNONYMS.get(w, (w.rstrip("s") if len(w) > 3 else w,)) for w in words]
        out = []
        for name, maps in self.maps_of.items():
            hay = name.lower()
            if q in hay or (alts and all(any(a in hay for a in alt) for alt in alts)):
                k = self.keys.get(name)
                out.append({"action": name, "maps": sorted(set(maps)), "key": pretty_key(k[0]) if k else "unbound",
                            "activation": (k[1] if k else "") or "press"})
        out.sort(key=lambda r: (r["key"] == "unbound", len(r["action"])))
        return out[:limit]

    def free_keys(self, avoid=()):
        avoid = {norm_spec(a) for a in avoid if a}
        for k in FREE_POOL:
            if k not in self.used and k not in avoid:
                yield k
        for mod in ("rctrl", "ralt"):
            for ch in "abcdefghijklmnopqrstuvwxyz1234567890":
                spec = f"{mod}+{ch}"
                if spec not in self.used and spec not in avoid:
                    yield spec

    def auto_assign(self, avoid=()):
        f = self.actionmaps_file
        if not f or not f.exists():
            raise RuntimeError("actionmaps.xml wasn't found. Start Star Citizen once, change any keybind, and quit, then try again.")
        if game_process_running():
            raise RuntimeError("Close Star Citizen first. It rewrites your keybinds file when it quits.")
        tree = ET.parse(f)
        root = tree.getroot()
        prof = root.find("ActionProfiles")
        if prof is None:
            prof = root
        maps = {m.get("name"): m for m in prof.findall("actionmap")}
        pool = self.free_keys(avoid)
        assigned, skipped = [], []
        for aid, label, sc, _ in ACTIONS:
            if self.pressable(sc) or sc not in self.maps_of:
                continue
            try:
                spec = next(pool)
            except StopIteration:
                skipped.append((label, "ran out of free keys"))
                continue
            for mn in sorted(set(self.maps_of[sc])):
                amap = maps.get(mn)
                if amap is None:
                    amap = ET.SubElement(prof, "actionmap", {"name": mn})
                    maps[mn] = amap
                act = next((a for a in amap.findall("action") if a.get("name") == sc), None)
                if act is None:
                    act = ET.SubElement(amap, "action", {"name": sc})
                rb = next((r for r in act.findall("rebind") if (r.get("input") or "").startswith("kb1_")), None)
                if rb is None:
                    rb = ET.SubElement(act, "rebind")
                rb.set("input", "kb1_" + spec)
            self.used.add(norm_spec(spec))
            assigned.append((label, pretty_key(spec)))
        backup = None
        if assigned:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = f.with_name(f"actionmaps.copilot-backup-{stamp}.xml")
            shutil.copy2(f, backup)
            ET.indent(tree, space=" ")
            tree.write(f, encoding="utf-8", xml_declaration=False)
            self.load()
        return assigned, skipped, backup


if __name__ == "__main__":
    # Dump a defaults snapshot from the game files: python sc_binds.py "<LIVE folder>"
    inst = find_install(sys.argv[1] if len(sys.argv) > 1 else None)
    raw = read_p4k_entry(inst / "Data.p4k")
    data = parse_profile(_cryxml(raw), game_build(inst))
    SNAPSHOT.write_text(json.dumps(data), encoding="utf-8")
    print(f"{len(data['actions'])} actions from build {data['build']} -> {SNAPSHOT}")
