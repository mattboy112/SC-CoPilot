import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path

import sc_version as VER

API = "https://api.github.com/repos/{repo}/releases/latest"


def _parts(tag):
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(tag, current=VER.VERSION):
    return _parts(tag) > _parts(current)


def latest(repo=VER.GITHUB_REPO, timeout=8):
    """The newest published release: {'tag', 'url', 'notes', 'asset', 'size'} or None."""
    req = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"SC-CoPilot/{VER.VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("draft") or data.get("prerelease"):
        return None
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")), None)
    return {"tag": data.get("tag_name", ""), "url": data.get("html_url") or VER.RELEASES_URL, "notes": (data.get("body") or "").strip(),
            "asset": asset.get("browser_download_url") if asset else None, "size": asset.get("size", 0) if asset else 0}


def check():
    """Returns release info if there's a newer version than this one, else None. Raises on network errors."""
    info = latest()
    if info and is_newer(info["tag"]):
        return info
    return None


def download(info, progress=None):
    """Downloads the installer to the temp folder and returns its path."""
    if not info or not info.get("asset"):
        raise RuntimeError("That release has no installer attached.")
    dest = Path(tempfile.gettempdir()) / f"SC_CoPilot_Setup_{info['tag'].lstrip('v')}.exe"
    part = dest.with_suffix(".part")
    req = urllib.request.Request(info["asset"], headers={"User-Agent": f"SC-CoPilot/{VER.VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("size") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress and total:
                progress(got / total)
    os.replace(part, dest)
    return dest
