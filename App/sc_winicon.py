"""Make Windows show the SC Co-Pilot logo everywhere: taskbar button, window, desktop shortcut.

Three things get in the way when the app runs from source:
- The taskbar groups the window under pythonw.exe and shows the Python logo. The Microsoft Store
  version of Python is a packaged app, which can ignore the process-wide ID, so the main window
  also gets its own ID (plus a relaunch command and icon, used when someone pins it).
- Tk's icon calls don't always reach the taskbar, so the .ico is also handed to Windows directly.
- Windows caches icons by file path, so a shortcut keeps its old picture after the logo changes.
  The icon is copied to a name that includes a hash of its contents, and shortcuts point there.
  When running from source the copy sits next to the app's files, not in AppData: the Microsoft
  Store Python quietly redirects AppData writes into its own private folder, where Explorer can't
  see them (the shortcut then shows a blank page).
"""
import base64
import ctypes
import hashlib
import subprocess
import sys
import uuid
from pathlib import Path

import sc_paths as P

APP_ID = "Mokke.SCCoPilot"
SHORTCUT_NAME = "SC Co-Pilot.lnk"
WIN = sys.platform == "win32"

_keep = []


def set_app_id():
    if not WIN:
        return False
    try:
        return ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_ID)) == 0
    except Exception:
        return False


def icon_name(data):
    return f"sc_copilot_{hashlib.sha1(data).hexdigest()[:8]}.ico"


def icon_folders():
    if P.FROZEN:
        return [P.LOCAL_DIR / "icons"]
    return [Path(P.APP_DIR) / ".icons", P.LOCAL_DIR / "icons"]


def stable_icon(src=None, folder=None):
    src = Path(src) if src else P.resource("sc_copilot.ico")
    if not src.exists():
        return None
    data = src.read_bytes()
    for base in ([Path(folder)] if folder else icon_folders()):
        dst = base / icon_name(data)
        try:
            if not dst.exists() or dst.read_bytes() != data:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
            return dst
        except OSError:
            continue
    return src


def _has(blob, text):
    return text.encode("utf-16-le") in blob or text.encode("latin-1", "ignore") in blob


def shortcut_state(blob, icon_path):
    """'ok' (already points at this exact icon file), 'stale' (made by the app, other icon) or 'other' (not ours)."""
    low = blob.lower()
    if not (_has(low, "sc_copilot") and _has(low, ".ico")):
        return "other"
    return "ok" if _has(low, str(icon_path).lower()) else "stale"


if WIN:
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

        @classmethod
        def of(cls, text):
            u = uuid.UUID(text)
            return cls(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))

    class _PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]

    class _PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("val", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]

    _AUMID_FMT = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
    _IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
    _VT_LPWSTR = 31
    _PID_RELAUNCH_COMMAND, _PID_RELAUNCH_ICON, _PID_RELAUNCH_NAME, _PID_ID = 2, 3, 4, 5

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                   wintypes.UINT]
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SendMessageW.restype = ctypes.c_ssize_t
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND

    _shell32 = ctypes.WinDLL("shell32")
    _shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    _shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    _shell32.SHChangeNotify.argtypes = [ctypes.c_long, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
    _shell32.SHChangeNotify.restype = None
    _shell32.SHGetFolderPathW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR]
    _shell32.SHGetFolderPathW.restype = ctypes.c_long

    def _method(obj, index, *argtypes):
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])

    def window_handle(tk_window):
        tk_window.update_idletasks()
        try:
            frame = int(tk_window.wm_frame(), 16)
        except (ValueError, TypeError):
            frame = 0
        inner = tk_window.winfo_id()
        return frame if frame and frame != inner else (_user32.GetParent(inner) or inner)

    def set_window_identity(hwnd, relaunch_command="", icon=None, name="SC Co-Pilot", clear=False):
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        store = ctypes.c_void_p()
        if _shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(_GUID.of(_IID_IPropertyStore)), ctypes.byref(store)) != 0:
            return False
        try:
            set_value = _method(store, 6, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT))
            values = []
            if clear:
                values = [(pid, None) for pid in (_PID_ID, _PID_RELAUNCH_COMMAND, _PID_RELAUNCH_ICON, _PID_RELAUNCH_NAME)]
            elif relaunch_command:
                values += [(_PID_RELAUNCH_COMMAND, relaunch_command), (_PID_RELAUNCH_NAME, name)]
                if icon:
                    values.append((_PID_RELAUNCH_ICON, f"{icon},0"))
            if not clear:
                values.append((_PID_ID, APP_ID))
            ok = True
            for pid, text in values:
                key = _PROPERTYKEY(_GUID.of(_AUMID_FMT), pid)
                pv = _PROPVARIANT(0, 0, 0, 0, None, None) if text is None else _PROPVARIANT(_VT_LPWSTR, 0, 0, 0, text, None)
                ok = set_value(store, ctypes.byref(key), ctypes.byref(pv)) == 0 and ok
            _method(store, 7)(store)
            return ok
        finally:
            _method(store, 2)(store)

    def set_window_icons(hwnd, icon):
        WM_SETICON, ICON_SMALL, ICON_BIG, IMAGE_ICON, LR_LOADFROMFILE = 0x0080, 0, 1, 1, 0x0010
        done = 0
        for which, metric in ((ICON_SMALL, 49), (ICON_BIG, 11)):
            size = _user32.GetSystemMetrics(metric) or (16 if which == ICON_SMALL else 32)
            h = _user32.LoadImageW(None, str(icon), IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                _keep.append(h)
                _user32.SendMessageW(hwnd, WM_SETICON, which, h)
                done += 1
        return done == 2

    def brand(tk_window, relaunch_command="", icon=None):
        """Give a Tk top-level window the app's taskbar ID and icon. Returns a short report for the log."""
        icon = icon or stable_icon()
        hwnd = window_handle(tk_window)
        ident = set_window_identity(hwnd, relaunch_command, icon)
        icons = set_window_icons(hwnd, icon) if icon else False
        return f"window {hwnd:#x}: id {'ok' if ident else 'failed'}, icons {'ok' if icons else 'failed'}"

    def unbrand(tk_window):
        """Windows asks apps to remove these window properties before the window closes."""
        try:
            set_window_identity(window_handle(tk_window), clear=True)
        except Exception:
            pass

    def desktop_dir():
        buf = ctypes.create_unicode_buffer(520)
        if _shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
        return Path.home() / "Desktop"

    def refresh_icons(path=None):
        SHCNE_UPDATEITEM, SHCNE_ASSOCCHANGED, SHCNF_PATHW, SHCNF_IDLIST = 0x00002000, 0x08000000, 0x0005, 0
        if path:
            _shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW, ctypes.c_wchar_p(str(path)), None)
        _shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)

else:
    def brand(tk_window, relaunch_command="", icon=None):
        return "not Windows"

    def unbrand(tk_window):
        pass

    def desktop_dir():
        return Path.home() / "Desktop"

    def refresh_icons(path=None):
        pass


def powershell(script):
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), capture_output=True, timeout=60)


def heal_desktop_shortcut(icon=None):
    """Point the app's own desktop shortcut at the current icon, so Windows can't keep showing an old logo."""
    if not WIN:
        return "not Windows"
    icon = icon or stable_icon()
    lnk = desktop_dir() / SHORTCUT_NAME
    if icon is None or not lnk.exists():
        return "no shortcut"
    state = shortcut_state(lnk.read_bytes(), icon)
    if state != "stale":
        return state
    q = lambda p: str(p).replace("'", "''")
    powershell(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
               f"$s.IconLocation='{q(icon)},0';$s.Save()")
    refresh_icons(lnk)
    return "fixed"
