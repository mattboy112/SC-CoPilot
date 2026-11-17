import sys
import threading
import time

import numpy as np

WIN = sys.platform == "win32"


def _gdi():
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    H = wintypes.HANDLE
    u.GetDC.argtypes = (wintypes.HWND,)
    u.GetDC.restype = H
    u.ReleaseDC.argtypes = (wintypes.HWND, H)
    g.CreateCompatibleDC.argtypes = (H,)
    g.CreateCompatibleDC.restype = H
    g.CreateCompatibleBitmap.argtypes = (H, ctypes.c_int, ctypes.c_int)
    g.CreateCompatibleBitmap.restype = H
    g.SelectObject.argtypes = (H, H)
    g.SelectObject.restype = H
    g.BitBlt.argtypes = (H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
    g.GetDIBits.argtypes = (H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
    g.DeleteObject.argtypes = (H,)
    g.DeleteDC.argtypes = (H,)
    return ctypes, u, g


def capture(rect):
    """Pixels of a screen rectangle (left, top, width, height) as an RGB uint8 array, or None if it can't."""
    if not WIN:
        return None
    x, y, w, h = (int(v) for v in rect)
    if w <= 0 or h <= 0:
        return None
    ctypes, u, g = _gdi()

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]
    screen = u.GetDC(None)
    mem = g.CreateCompatibleDC(screen)
    bmp = g.CreateCompatibleBitmap(screen, w, h)
    old = g.SelectObject(mem, bmp)
    try:
        if not g.BitBlt(mem, 0, 0, w, h, screen, x, y, 0x00CC0020 | 0x40000000):
            return None
        info = BMIH(biSize=ctypes.sizeof(BMIH), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32, biCompression=0)
        buf = (ctypes.c_ubyte * (w * h * 4))()
        if not g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0):
            return None
        return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, 2::-1].copy()
    finally:
        g.SelectObject(mem, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mem)
        u.ReleaseDC(None, screen)


def hsv(img):
    """Hue (0-360), saturation (0-1) and value (0-255) for every pixel."""
    f = img.astype(np.float32)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    mx = f.max(axis=-1)
    mn = f.min(axis=-1)
    d = mx - mn
    sat = np.where(mx > 0, d / np.maximum(mx, 1), 0)
    dd = np.maximum(d, 1e-6)
    hue = np.where(mx == r, (g - b) / dd % 6, np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4)) * 60.0
    hue = np.where(d < 1e-3, 0, hue)
    return hue, sat, mx


def bright(img, min_val=110, min_sat=0.30):
    """HUD-looking pixels: bright and colourful, unlike dark space or grey ship hulls."""
    _h, s, v = hsv(img)
    return (v >= min_val) & (s >= min_sat)


def dominant_hue(img):
    """The main HUD colour in a crop, as a hue in degrees, or None if there's nothing colourful."""
    h, s, v = hsv(img)
    m = (v >= 110) & (s >= 0.30)
    if m.sum() < 12:
        return None
    hist, edges = np.histogram(h[m], bins=36, range=(0, 360))
    i = int(np.argmax(hist))
    sel = h[m][(h[m] >= edges[i]) & (h[m] < edges[i + 1])]
    return float(np.median(sel)) if sel.size else float((edges[i] + edges[i + 1]) / 2)


def hue_mask(img, ref_hue, tol=20.0):
    h, s, v = hsv(img)
    diff = np.abs((h - ref_hue + 180.0) % 360.0 - 180.0)
    return (diff <= tol) & (v >= 90) & (s >= 0.25)


def calibrate_region(img, mode):
    """Learn what a full display looks like. mode 'color' = count pixels of its main colour (shields);
    'any' = count any HUD-looking pixels (hull, which often changes colour as it takes damage)."""
    if img is None or img.size == 0:
        raise ValueError("Empty area.")
    if mode == "color":
        hue = dominant_hue(img)
        if hue is None:
            raise ValueError("Couldn't find a coloured display in that box. Make sure the target's shields are showing.")
        count = int(hue_mask(img, hue).sum())
    else:
        hue = None
        count = int(bright(img).sum())
    if count < 12:
        raise ValueError("That box is almost empty. Draw it tightly around the display.")
    return {"mode": mode, "hue": hue, "full": count}


def measure(img, cal):
    """Fraction (0-1) of the calibrated 'full' amount that's showing now."""
    if img is None or not cal or not cal.get("full"):
        return None
    count = int(hue_mask(img, cal["hue"]).sum()) if cal.get("mode") == "color" and cal.get("hue") is not None else int(bright(img).sum())
    return max(0.0, min(1.0, count / float(cal["full"])))


def spoken_pct(frac):
    if frac is None:
        return "unknown"
    if frac < 0.06:
        return "down"
    if frac > 0.94:
        return "full"
    return f"about {int(frac * 10 + 0.5) * 10} percent"


class Reader:
    """Reads the target's shield and hull from the HUD using boxes the pilot drew during setup."""

    def __init__(self, get_settings, get_ship=None):
        self.get_settings = get_settings
        self.get_ship = get_ship or (lambda: "")
        self.last = None
        self.watching = False
        self._stop = False
        self._thread = None
        self.on_shields_down = None

    def profiles(self):
        return self.get_settings().get("hud_profiles") or {}

    def profile(self, ship=None):
        p = self.profiles()
        ship = ship if ship is not None else (self.get_ship() or "")
        return p.get(ship) or p.get("default")

    def configured(self):
        return bool(self.profile())

    def read(self, ship=None):
        """{'ok', 'shields', 'hull', 'visible', 'text'}; fractions are 0-1 or None."""
        prof = self.profile(ship)
        if not prof:
            return {"ok": False, "text": "The target reader isn't set up yet. Settings → Target reader."}
        if not WIN:
            return {"ok": False, "text": "The target reader only works on Windows."}
        try:
            sh_img = capture(prof["shield"]["rect"]) if prof.get("shield") else None
            hu_img = capture(prof["hull"]["rect"]) if prof.get("hull") else None
        except Exception as ex:
            return {"ok": False, "text": f"Couldn't read the screen ({type(ex).__name__})."}
        return self.interpret(prof, sh_img, hu_img)

    @staticmethod
    def interpret(prof, sh_img, hu_img):
        shields = measure(sh_img, prof.get("shield", {}).get("cal")) if sh_img is not None else None
        hull = measure(hu_img, prof.get("hull", {}).get("cal")) if hu_img is not None else None
        visible = True
        if hu_img is not None and prof.get("hull", {}).get("cal"):
            visible = int(bright(hu_img).sum()) >= 0.12 * prof["hull"]["cal"]["full"]
        elif sh_img is not None and shields is not None:
            visible = shields > 0.02
        if not visible:
            return {"ok": True, "visible": False, "shields": None, "hull": None,
                    "text": "I can't see a target on your HUD. Lock one first."}
        return {"ok": True, "visible": True, "shields": shields, "hull": hull,
                "text": f"Target shields {spoken_pct(shields)}, hull {spoken_pct(hull)}."}

    def start_watch(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._watch, daemon=True, name="hud-watch")
        self._thread.start()

    def stop_watch(self):
        self._stop = True

    def _watch(self):
        was_up = False
        last_call = 0.0
        while not self._stop:
            time.sleep(0.4)
            s = self.get_settings()
            if not s.get("hud_watch") or not self.configured() or not self.watch_ok():
                was_up = False
                continue
            r = self.read()
            self.last = r
            if not r.get("ok") or not r.get("visible") or r.get("shields") is None:
                was_up = False
                continue
            if r["shields"] > 0.35:
                was_up = True
            elif r["shields"] < 0.06 and was_up and time.time() - last_call > 10:
                was_up = False
                last_call = time.time()
                if self.on_shields_down:
                    self.on_shields_down()

    def watch_ok(self):
        return True
