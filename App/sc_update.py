import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import sc_version as VER

API = "https://api.github.com/repos/{repo}/releases/latest"
DOWNLOAD_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
MAX_INSTALLER = 600 * 1024 * 1024


class UpdateRefused(RuntimeError):
    pass


def _parts(tag):
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(tag, current=VER.VERSION):
    return _parts(tag) > _parts(current)


def trusted_url(url, repo=VER.GITHUB_REPO, first_hop=True):
    u = urllib.parse.urlsplit(url or "")
    if u.scheme != "https" or (u.hostname or "").lower() not in DOWNLOAD_HOSTS or u.username or u.password or u.port not in (None, 443):
        return False
    if first_hop:
        return (u.hostname or "").lower() == "github.com" and u.path.lower().startswith(f"/{repo.lower()}/releases/download/")
    return True


def _digest(asset):
    m = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", str(asset.get("digest") or ""))
    return m.group(1).lower() if m else None


def latest(repo=VER.GITHUB_REPO, timeout=8):
    """The newest published release: {'tag', 'url', 'notes', 'asset', 'size', 'sha256'} or None."""
    req = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"SC-CoPilot/{VER.VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read(5_000_000).decode("utf-8"))
    if data.get("draft") or data.get("prerelease"):
        return None
    exes = [a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")
            and trusted_url(a.get("browser_download_url"), repo)]
    asset = next((a for a in exes if re.search(r"\d+\.\d+", a.get("name", ""))), exes[0] if exes else None)
    page = data.get("html_url") or ""
    if not page.startswith(f"https://github.com/{repo}/"):
        page = VER.RELEASES_URL
    return {"tag": data.get("tag_name", ""), "url": page, "notes": (data.get("body") or "").strip(),
            "asset": asset.get("browser_download_url") if asset else None, "size": int(asset.get("size") or 0) if asset else 0,
            "sha256": _digest(asset) if asset else None}


def check():
    """Returns release info if there's a newer version than this one, else None. Raises on network errors."""
    info = latest()
    if info and is_newer(info["tag"]):
        return info
    return None


def download(info, progress=None):
    """Downloads the installer to the temp folder, checks it's the exact file GitHub published, and returns its path."""
    if not info or not info.get("asset"):
        raise UpdateRefused("That release has no installer attached.")
    if not trusted_url(info["asset"]):
        raise UpdateRefused("That installer isn't hosted on SC Co-Pilot's GitHub page.")
    want = (info.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", want):
        raise UpdateRefused("GitHub didn't publish a checksum for that installer.")
    tag = re.sub(r"[^0-9A-Za-z.]", "", (info.get("tag") or "").lstrip("v"))[:20] or "new"
    dest = Path(tempfile.gettempdir()) / f"SC_CoPilot_Setup_{tag}.exe"
    part = dest.with_suffix(".part")
    req = urllib.request.Request(info["asset"], headers={"User-Agent": f"SC-CoPilot/{VER.VERSION}"})
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            if not trusted_url(r.geturl(), first_hop=False):
                raise UpdateRefused("The download was redirected somewhere unexpected.")
            total = int(r.headers.get("Content-Length") or info.get("size") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_INSTALLER:
                    raise UpdateRefused("The download is far bigger than an installer should be.")
                h.update(chunk)
                f.write(chunk)
                if progress and total:
                    progress(min(1.0, got / total))
        if info.get("size") and got != info["size"]:
            raise UpdateRefused("The download was incomplete.")
        if h.hexdigest() != want:
            raise UpdateRefused("The installer didn't match GitHub's checksum, so it wasn't run.")
        os.replace(part, dest)
    finally:
        try:
            part.unlink()
        except OSError:
            pass
    return dest
