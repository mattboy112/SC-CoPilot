import base64
import sys

PREFIX = "dpapi:"
SECRET_KEYS = ("api_key", "license_key")
_ENTROPY = b"SC Co-Pilot settings v1"
_UI_FORBIDDEN = 0x1

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    for _fn in (_crypt32.CryptProtectData, _crypt32.CryptUnprotectData):
        _fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                        wintypes.DWORD, ctypes.POINTER(_Blob)]
        _fn.restype = wintypes.BOOL

    def _run(fn, data):
        src_buf = ctypes.create_string_buffer(data, len(data))
        ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
        src = _Blob(len(data), ctypes.cast(src_buf, ctypes.POINTER(ctypes.c_char)))
        ent = _Blob(len(_ENTROPY), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
        out = _Blob()
        if not fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(ctypes.get_last_error(), "Windows couldn't protect or unlock the saved key")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def _encrypt(data):
        return _run(_crypt32.CryptProtectData, data)

    def _decrypt(data):
        return _run(_crypt32.CryptUnprotectData, data)
else:
    _encrypt = None
    _decrypt = None


def available():
    return _encrypt is not None


def protect(text):
    """Locks a key to this Windows account. Other users, other PCs and anyone who copies the settings file get nothing."""
    if not text or not isinstance(text, str) or text.startswith(PREFIX) or not available():
        return text
    return PREFIX + base64.b64encode(_encrypt(text.encode("utf-8"))).decode("ascii")


def unprotect(value):
    """The plain key, or "" if it was locked on another PC or Windows account."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value if isinstance(value, str) else ""
    if not available():
        return ""
    try:
        return _decrypt(base64.b64decode(value[len(PREFIX):], validate=True)).decode("utf-8")
    except (OSError, ValueError):
        return ""


def lock_settings(data):
    out = dict(data)
    for k in SECRET_KEYS:
        if out.get(k):
            try:
                out[k] = protect(out[k])
            except OSError as ex:
                print(f"[settings] couldn't encrypt {k}, saving it unencrypted: {ex}", flush=True)
    return out


def unlock_settings(data):
    lost = []
    for k in SECRET_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.startswith(PREFIX):
            data[k] = unprotect(v)
            if not data[k]:
                lost.append(k)
    return lost
