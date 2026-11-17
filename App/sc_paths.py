import os
import shutil
import sys
from pathlib import Path

APP_NAME = "SC Co-Pilot"
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(getattr(sys, "_MEIPASS", "")) if FROZEN and getattr(sys, "_MEIPASS", None) else Path(__file__).resolve().parent
EXE_DIR = Path(sys.executable).resolve().parent if FROZEN else APP_DIR


def _pick_dirs():
    override = os.environ.get("SC_COPILOT_HOME")
    if override:
        base = Path(override)
        return base, base
    if (EXE_DIR / "portable.txt").exists():
        base = EXE_DIR / "userdata"
        return base, base
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return roaming / APP_NAME, local / APP_NAME
    return Path.home() / ".config" / "sc-copilot", Path.home() / ".cache" / "sc-copilot"


DATA_DIR, LOCAL_DIR = _pick_dirs()
CACHE_DIR = LOCAL_DIR / "cache"
MODELS_DIR = LOCAL_DIR / "models"
LOG_DIR = LOCAL_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "sc_settings.json"
LOG_FILE = LOG_DIR / "sc_copilot.log"
CRASH_FILE = LOG_DIR / "crash.log"

for _d in (DATA_DIR, CACHE_DIR, MODELS_DIR, LOG_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def resource(name):
    """A file shipped with the app (icons, the default keybind snapshot)."""
    return APP_DIR / name


def cache(name):
    return CACHE_DIR / name


LEGACY_FILES = {
    "sc_settings.json": DATA_DIR,
    "sc_copilot.log": LOG_DIR,
    "sc_default_binds_cache.json": CACHE_DIR,
    "sc_history_cache.json": CACHE_DIR,
    "sc_edge_voices.json": CACHE_DIR,
    "sc_nvfix_result.json": CACHE_DIR,
}


def _move(src, dst):
    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))


def migrate_legacy(old_dir=None):
    """Older builds kept everything next to the scripts. Move it into the per-user folders once."""
    old = Path(old_dir) if old_dir else APP_DIR
    if FROZEN or old.resolve() in (DATA_DIR.resolve(), LOCAL_DIR.resolve()):
        return []
    moved = []
    names = dict(LEGACY_FILES)
    for f in old.glob("sc_uex_*.json"):
        names[f.name] = CACHE_DIR
    for name, dest in names.items():
        src, dst = old / name, dest / name
        if src.is_file() and not dst.exists():
            try:
                _move(src, dst)
                moved.append(name)
            except OSError:
                pass
    models = old / "models"
    if models.is_dir():
        for item in models.iterdir():
            dst = MODELS_DIR / item.name
            if not dst.exists():
                try:
                    _move(item, dst)
                    moved.append(f"models/{item.name}")
                except OSError:
                    pass
    return moved
