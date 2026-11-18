import base64
import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "App"))

import sc_lines as LN
import sc_secret as SEC
import sc_update as UPD


@pytest.fixture
def fake_dpapi(monkeypatch):
    monkeypatch.setattr(SEC, "_encrypt", lambda b: b"LOCK" + b[::-1])
    monkeypatch.setattr(SEC, "_decrypt", lambda b: b[4:][::-1] if b.startswith(b"LOCK") else (_ for _ in ()).throw(OSError(13, "x")))


def test_keys_are_encrypted_on_disk(fake_dpapi):
    saved = SEC.lock_settings({"api_key": "sk-ant-secret", "license_key": "POLAR-1234", "voice": "ryan"})
    assert saved["api_key"].startswith(SEC.PREFIX) and "sk-ant-secret" not in saved["api_key"]
    assert saved["license_key"].startswith(SEC.PREFIX)
    assert saved["voice"] == "ryan"
    loaded = dict(saved)
    assert SEC.unlock_settings(loaded) == []
    assert loaded["api_key"] == "sk-ant-secret" and loaded["license_key"] == "POLAR-1234"


def test_plain_keys_from_older_versions_still_load(fake_dpapi):
    s = {"api_key": "sk-ant-old"}
    assert SEC.unlock_settings(s) == []
    assert s["api_key"] == "sk-ant-old"
    assert SEC.lock_settings(s)["api_key"].startswith(SEC.PREFIX)


def test_keys_locked_elsewhere_come_back_empty(fake_dpapi):
    s = {"api_key": SEC.PREFIX + base64.b64encode(b"someone else's").decode(), "license_key": SEC.PREFIX + "not base64!!"}
    assert sorted(SEC.unlock_settings(s)) == ["api_key", "license_key"]
    assert s["api_key"] == "" and s["license_key"] == ""


def test_empty_and_already_locked_values_left_alone(fake_dpapi):
    assert SEC.protect("") == ""
    locked = SEC.protect("abc")
    assert SEC.protect(locked) == locked


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_without_windows_nothing_is_pretend_encrypted():
    assert not SEC.available()
    assert SEC.protect("sk-ant-x") == "sk-ant-x"
    assert SEC.unprotect(SEC.PREFIX + "AAAA") == ""


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows DPAPI")
def test_real_windows_encryption_round_trip():
    locked = SEC.protect("sk-ant-real-test")
    assert locked.startswith(SEC.PREFIX) and "sk-ant" not in locked
    assert SEC.unprotect(locked) == "sk-ant-real-test"
    assert SEC.unprotect(SEC.PREFIX + base64.b64encode(b"junk junk junk").decode()) == ""


REPO = "mattboy112/SC-CoPilot"
GOOD = f"https://github.com/{REPO}/releases/download/v1.2.0/SC_CoPilot_Setup_1.2.0.exe"


@pytest.mark.parametrize("url,ok", [
    (GOOD, True),
    (f"https://github.com/someone-else/SC-CoPilot/releases/download/v1/x.exe", False),
    ("http://github.com/" + GOOD.split("github.com/")[1], False),
    ("https://evil.example/SC_CoPilot_Setup.exe", False),
    ("https://github.com.evil.example/" + GOOD.split("github.com/")[1], False),
    ("https://user:pw@github.com/" + GOOD.split("github.com/")[1], False),
    ("https://github.com:8443/" + GOOD.split("github.com/")[1], False),
])
def test_only_this_repos_github_releases_are_trusted(url, ok):
    assert UPD.trusted_url(url, REPO) is ok


def test_redirect_targets_must_stay_on_github():
    assert UPD.trusted_url("https://release-assets.githubusercontent.com/abc?sig=1", first_hop=False)
    assert not UPD.trusted_url("https://evil.example/abc", first_hop=False)


class _Resp(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self._url = url
        self.headers = {"Content-Length": str(len(data))}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _info(data, digest=None, asset=GOOD):
    return {"tag": "v1.2.0", "asset": asset, "size": len(data), "sha256": digest, "url": f"https://github.com/{REPO}/releases"}


@pytest.fixture
def served(monkeypatch, tmp_path):
    monkeypatch.setattr(UPD.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(UPD.VER, "GITHUB_REPO", REPO)
    state = {"data": b"MZ installer bytes", "final": "https://release-assets.githubusercontent.com/x"}
    monkeypatch.setattr(UPD.urllib.request, "urlopen", lambda req, timeout=0: _Resp(state["data"], state["final"]))
    return state, tmp_path


def _trusted(monkeypatch):
    real = UPD.trusted_url
    monkeypatch.setattr(UPD, "trusted_url", lambda url, repo=REPO, first_hop=True: real(url, REPO, first_hop))


def test_matching_installer_is_kept(served, monkeypatch):
    state, tmp = served
    _trusted(monkeypatch)
    path = UPD.download(_info(state["data"], hashlib.sha256(state["data"]).hexdigest()))
    assert path.read_bytes() == state["data"]


def test_tampered_installer_is_refused_and_deleted(served, monkeypatch):
    state, tmp = served
    _trusted(monkeypatch)
    with pytest.raises(UPD.UpdateRefused, match="checksum"):
        UPD.download(_info(state["data"], hashlib.sha256(b"the real one").hexdigest()))
    assert list(tmp.iterdir()) == []


def test_missing_checksum_is_refused(served, monkeypatch):
    state, _ = served
    _trusted(monkeypatch)
    with pytest.raises(UPD.UpdateRefused, match="checksum"):
        UPD.download(_info(state["data"], None))


def test_foreign_host_is_refused(served, monkeypatch):
    state, _ = served
    _trusted(monkeypatch)
    with pytest.raises(UPD.UpdateRefused, match="GitHub"):
        UPD.download(_info(state["data"], hashlib.sha256(state["data"]).hexdigest(), asset="https://evil.example/setup.exe"))


def test_redirect_to_foreign_host_is_refused(served, monkeypatch):
    state, tmp = served
    _trusted(monkeypatch)
    state["final"] = "https://evil.example/setup.exe"
    with pytest.raises(UPD.UpdateRefused, match="redirected"):
        UPD.download(_info(state["data"], hashlib.sha256(state["data"]).hexdigest()))
    assert list(tmp.iterdir()) == []


def test_latest_reads_githubs_digest(monkeypatch):
    payload = ('{"tag_name": "v1.2.0", "html_url": "https://github.com/%s/releases/tag/v1.2.0", "assets": ['
               '{"name": "SC_CoPilot_Setup_1.2.0.exe", "browser_download_url": "%s", "size": 5, "digest": "sha256:%s"},'
               '{"name": "evil_9.9.exe", "browser_download_url": "https://evil.example/x.exe", "size": 5}]}') % (REPO, GOOD, "ab" * 32)
    monkeypatch.setattr(UPD.urllib.request, "urlopen", lambda req, timeout=0: _Resp(payload.encode(), "https://api.github.com"))
    info = UPD.latest(repo=REPO)
    assert info["asset"] == GOOD and info["sha256"] == "ab" * 32


@pytest.mark.parametrize("text", ["{name.__class__.__mro__}", "{name:>999999999}", "{0}", "{name!r}", "{", "}{", "{{name}}"])
def test_pack_lines_cant_run_format_tricks(text):
    out = LN._fill(text, {"name": "Mokke"})
    assert len(out) < 100
    assert "class" not in out or "__class__" in out


def test_pack_placeholders_still_work():
    assert LN._fill("Welcome back, {name}. {missing}Ready.", {"name": "Mokke"}) == "Welcome back, Mokke. Ready."


@pytest.mark.parametrize("path,ok", [
    ("packs/noir-detective.json", True),
    ("packs/index.json", False),
    ("../secrets.json", False),
    ("packs/../../x.json", False),
    ("https://evil.example/x.json", False),
    ("packs/Evil.json", False),
    (None, False),
])
def test_gallery_only_loads_pack_files(path, ok):
    assert LN.safe_pack_path(path) is ok


def test_imported_packs_only_touch_lines():
    s = {"api_key": "keep", "ai_mode": "own_key", "personality": "standard"}
    key = next(iter(LN.DEFAULTS))
    n = LN.import_pack(s, {"lines": {key: "x" * 5000, "api_key": "stolen", "ai_mode": "off"}, "personality": "nope", "api_key": "y"})
    assert n == 1 and len(s["lines"][key]) == 400
    assert s["api_key"] == "keep" and s["ai_mode"] == "own_key" and s["personality"] == "standard"


def test_helper_programs_run_from_windows_folder(tmp_path, monkeypatch):
    import sc_paths as P
    exe = tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert P.system_exe(*P.POWERSHELL) == str(exe)
    assert P.system_exe("tasklist.exe") == "tasklist.exe"


def _brain(settings):
    import threading
    import types
    import sc_brain as BR
    st = types.SimpleNamespace(lock=threading.RLock(), handle="Pilot", snapshot_text=lambda: "")
    return BR, BR.Brain(types.SimpleNamespace(settings=settings, state=st, note_system=lambda *a: None))


def test_pasted_keys_lose_spaces_and_line_breaks():
    BR, b = _brain({"ai_mode": "own_key", "api_key": " sk-ant-abc\n def \t"})
    assert BR.clean_key(" a b\nc\r\n") == "abc"
    assert b.key() == "sk-ant-abcdef"


def test_anthropic_key_in_the_subscription_box_is_never_sent(monkeypatch):
    BR, b = _brain({"ai_mode": "service", "license_key": "sk-ant-api03-secret"})
    monkeypatch.setattr(BR.VER, "SERVICE_URL", "https://service.example")
    assert b.key() == "" and not b.ready()
    assert "Anthropic API key" in b.not_ready_reason()
    with pytest.raises(RuntimeError, match="Anthropic API key"):
        b.test()


def test_a_bad_key_never_shows_up_in_an_error(monkeypatch):
    BR, b = _brain({"ai_mode": "own_key", "api_key": "sk-ant-TOPSECRET"})

    class Boom:
        def request(self, *a, **k):
            raise ValueError("Invalid header value b'sk-ant-TOPSECRET'")

    monkeypatch.setattr(b.conn, "get", lambda **k: Boom())
    with pytest.raises(RuntimeError) as ei:
        b._request({"model": "m", "messages": []})
    assert "TOPSECRET" not in str(ei.value) and ei.value.__cause__ is None


def test_one_request_uses_one_mode_for_host_and_key(monkeypatch):
    BR, b = _brain({"ai_mode": "service", "license_key": "LIC-123456789", "api_key": "sk-ant-mine"})
    monkeypatch.setattr(BR.VER, "SERVICE_URL", "https://service.example")
    host, _port, _path, auth = b._target("service")
    assert host == "service.example" and auth["authorization"] == "Bearer LIC-123456789" and "x-api-key" not in auth
    host, _port, _path, auth = b._target("own_key")
    assert host == BR.API_HOST and auth == {"x-api-key": "sk-ant-mine"}


def test_pack_path_with_a_trailing_newline_is_refused():
    assert not LN.safe_pack_path("packs/noir-detective.json\n")


def test_pack_names_and_descriptions_cant_carry_links():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
    import packs as PK
    base = {"sc_copilot_lines": 1, "name": "Noir", "description": "Moody.", "personality": "standard",
            "lines": {k: "Copy that." for k in list(LN.DEFAULTS)[:20]}}
    assert not [e for e in PK.validate(base) if "link" in e]
    assert any("name" in e for e in PK.validate(dict(base, name="Join @everyone")))
    assert any("description" in e for e in PK.validate(dict(base, description="see https://evil.example")))
    for sneaky in ("//evil.example/x", "visit evil.net", "free stuff at scam.gg"):
        assert any("description" in e for e in PK.validate(dict(base, description=sneaky))), sneaky
    assert not [e for e in PK.validate(dict(base, description="Gruff ex-military pilot. Quantum spool at 0.5 seconds.")) if "link" in e]
