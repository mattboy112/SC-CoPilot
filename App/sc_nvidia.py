import ctypes
import json
import sys

SETTING_ID = 0x20D690F8
LAYERED = 1
VALUES = {0: "Prefer native", 1: "Prefer layered on DXGI Swapchain", 2: "Auto"}
WHERE = {0: "the Star Citizen profile", 1: "your global settings", 2: "your global settings", 3: "the driver default"}
EXE = "StarCitizen.exe"

OK = 0
SETTING_NOT_FOUND = -160
EXECUTABLE_NOT_FOUND = -166
INCOMPATIBLE_STRUCT = -9
NEEDS_ADMIN = -137
NO_NVIDIA = -6

F_INIT = 0x0150E828
F_CREATE = 0x0694D52E
F_DESTROY = 0xDAD9CFF8
F_LOAD = 0x375DBD6B
F_SAVE = 0xFCBC7E14
F_FIND_APP = 0xEEE566B2
F_PROFILE_INFO = 0x61CD6FD6
F_GET = 0x73BF8338
F_SET = 0x577DD202
F_BASE = 0xDA8466A0

U32 = ctypes.c_uint32
USTR = ctypes.c_uint16 * 2048


class _Binary(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("valueLength", U32), ("valueData", ctypes.c_uint8 * 4096)]


class _Value(ctypes.Union):
    _pack_ = 4
    _fields_ = [("u32", U32), ("binary", _Binary), ("wsz", USTR), ("u64", ctypes.c_uint64), ("f32", ctypes.c_float)]


class Setting(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("version", U32), ("settingName", USTR), ("settingId", U32), ("settingType", U32), ("settingLocation", U32),
                ("isCurrentPredefined", U32), ("isPredefinedValid", U32), ("predefined", _Value), ("current", _Value)]


class AppV4(ctypes.Structure):
    _fields_ = [("version", U32), ("isPredefined", U32), ("appName", USTR), ("userFriendlyName", USTR), ("launcher", USTR),
                ("fileInFolder", USTR), ("flags", U32), ("commandLine", USTR)]


class AppV3(ctypes.Structure):
    _fields_ = [("version", U32), ("isPredefined", U32), ("appName", USTR), ("userFriendlyName", USTR), ("launcher", USTR),
                ("fileInFolder", USTR), ("flags", U32)]


class Profile(ctypes.Structure):
    _fields_ = [("version", U32), ("profileName", USTR), ("gpuSupport", U32), ("isPredefined", U32), ("numOfApps", U32),
                ("numOfSettings", U32)]


def _ver(struct, n):
    return ctypes.sizeof(struct) | (n << 16)


def _ustr(text):
    buf = USTR()
    for i, ch in enumerate(text[:2047]):
        buf[i] = ord(ch)
    return buf


def _text(buf):
    out = []
    for c in buf:
        if not c:
            break
        out.append(chr(c))
    return "".join(out)


class NvError(Exception):
    pass


class Session:
    def __init__(self):
        if sys.platform != "win32":
            raise NvError("only works on Windows")
        try:
            dll = ctypes.WinDLL("nvapi64.dll" if ctypes.sizeof(ctypes.c_void_p) == 8 else "nvapi.dll")
        except OSError:
            raise NvError("no NVIDIA driver found")
        self.qi = dll.nvapi_QueryInterface
        self.qi.restype = ctypes.c_void_p
        self.qi.argtypes = [ctypes.c_uint]
        H = ctypes.c_void_p
        self.init = self._fn(F_INIT)
        self.create = self._fn(F_CREATE, ctypes.POINTER(H))
        self.destroy = self._fn(F_DESTROY, H)
        self.load = self._fn(F_LOAD, H)
        self.save = self._fn(F_SAVE, H)
        self.find_app_v4 = self._fn(F_FIND_APP, H, ctypes.POINTER(USTR), ctypes.POINTER(H), ctypes.POINTER(AppV4))
        self.find_app_v3 = self._fn(F_FIND_APP, H, ctypes.POINTER(USTR), ctypes.POINTER(H), ctypes.POINTER(AppV3))
        self.profile_info = self._fn(F_PROFILE_INFO, H, H, ctypes.POINTER(Profile))
        self.get = self._fn(F_GET, H, H, U32, ctypes.POINTER(Setting))
        self.set = self._fn(F_SET, H, H, ctypes.POINTER(Setting))
        self.base = self._fn(F_BASE, H, ctypes.POINTER(H))
        rc = self.init()
        if rc == NO_NVIDIA:
            raise NvError("no NVIDIA GPU is driving a display")
        if rc != OK:
            raise NvError(f"NVIDIA driver didn't start its settings interface (code {rc})")
        self.h = H()
        rc = self.create(ctypes.byref(self.h))
        if rc != OK:
            raise NvError(f"couldn't open NVIDIA settings (code {rc})")
        rc = self.load(self.h)
        if rc != OK:
            self.close()
            raise NvError(f"couldn't load NVIDIA settings (code {rc})")

    def _fn(self, fid, *args):
        addr = self.qi(fid)
        if not addr:
            raise NvError("this NVIDIA driver is missing a settings function")
        return ctypes.CFUNCTYPE(ctypes.c_int, *args)(addr)

    def close(self):
        if getattr(self, "h", None):
            self.destroy(self.h)
            self.h = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def find_profile(self, exe=EXE):
        prof = ctypes.c_void_p()
        name = _ustr(exe)
        app = AppV4(version=_ver(AppV4, 4))
        rc = self.find_app_v4(self.h, ctypes.byref(name), ctypes.byref(prof), ctypes.byref(app))
        if rc == INCOMPATIBLE_STRUCT:
            app = AppV3(version=_ver(AppV3, 3))
            rc = self.find_app_v3(self.h, ctypes.byref(name), ctypes.byref(prof), ctypes.byref(app))
        if rc == EXECUTABLE_NOT_FOUND:
            return None, None
        if rc != OK:
            raise NvError(f"couldn't look up {exe} (code {rc})")
        info = Profile(version=_ver(Profile, 1))
        pname = _text(info.profileName) if self.profile_info(self.h, prof, ctypes.byref(info)) == OK else ""
        return prof, pname or "Star Citizen"

    def read(self, prof, sid=SETTING_ID):
        st = Setting(version=_ver(Setting, 1))
        rc = self.get(self.h, prof, sid, ctypes.byref(st))
        if rc == SETTING_NOT_FOUND:
            return None, None
        if rc != OK:
            raise NvError(f"couldn't read the setting (code {rc})")
        return st.current.u32, st.settingLocation

    def write(self, prof, value, sid=SETTING_ID):
        st = Setting(version=_ver(Setting, 1), settingId=sid, settingType=0)
        st.current.u32 = value
        rc = self.set(self.h, prof, ctypes.byref(st))
        if rc == NEEDS_ADMIN:
            return "admin"
        if rc != OK:
            raise NvError(f"couldn't change the setting (code {rc})")
        rc = self.save(self.h)
        if rc == NEEDS_ADMIN:
            return "admin"
        if rc != OK:
            raise NvError(f"couldn't save NVIDIA settings (code {rc})")
        return "ok"


def check():
    """What the NVIDIA driver will use for Star Citizen's 'Vulkan/OpenGL present method'."""
    try:
        with Session() as s:
            prof, pname = s.find_profile()
            value = loc = None
            if prof is not None:
                value, loc = s.read(prof)
            if value is None:
                base = ctypes.c_void_p()
                if s.base(ctypes.byref(base)) == OK:
                    value, loc = s.read(base)
                    loc = 1 if value is not None else None
            if value is None:
                value, loc = 2, 3
    except NvError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "value": value, "name": VALUES.get(value, f"unknown ({value})"), "from": WHERE.get(loc, "somewhere"),
            "profile": pname, "good": value == LAYERED}


def fix():
    """Set Star Citizen's profile to 'Prefer layered on DXGI Swapchain'. Returns 'ok', 'admin' or an error string."""
    try:
        with Session() as s:
            prof, _ = s.find_profile()
            if prof is None:
                return "No NVIDIA profile has StarCitizen.exe in it. Add it in NVIDIA Control Panel → Program Settings → Add."
            return s.write(prof, LAYERED)
    except NvError as e:
        return str(e)
    except Exception as e:
        return f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--fix":
        result = fix()
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump({"result": result, "after": check()}, f)
    else:
        print(json.dumps(check(), indent=2))
