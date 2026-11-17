import sc_winicon as WI


def test_icon_name_changes_with_the_icon():
    assert WI.icon_name(b"logo one") != WI.icon_name(b"logo two")
    assert WI.icon_name(b"same") == WI.icon_name(b"same")
    assert WI.icon_name(b"x").startswith("sc_copilot_") and WI.icon_name(b"x").endswith(".ico")


def test_stable_icon_copies_once_and_follows_changes(tmp_path):
    src = tmp_path / "sc_copilot.ico"
    src.write_bytes(b"old logo")
    first = WI.stable_icon(src, tmp_path / "icons")
    assert first.read_bytes() == b"old logo"
    assert WI.stable_icon(src, tmp_path / "icons") == first
    src.write_bytes(b"new logo")
    second = WI.stable_icon(src, tmp_path / "icons")
    assert second != first and second.read_bytes() == b"new logo"


def test_stable_icon_missing_source(tmp_path):
    assert WI.stable_icon(tmp_path / "nope.ico", tmp_path) is None


def lnk(*texts, wide=True):
    blob = b"L\x00\x00\x00junk"
    for t in texts:
        blob += (t.encode("utf-16-le") if wide else t.encode("latin-1")) + b"\x00\x00"
    return blob


def test_shortcut_state():
    new = "sc_copilot_1a2b3c4d.ico"
    old_icon = r"C:\Users\Me\Downloads\SC_CoPilot\App\sc_copilot.ico"
    assert WI.shortcut_state(lnk(r"C:\Python\pythonw.exe", old_icon), new) == "stale"
    assert WI.shortcut_state(lnk(old_icon, wide=False), new) == "stale"
    assert WI.shortcut_state(lnk(r"C:\Users\Me\AppData\Local\SC Co-Pilot\icons" "\\" + new), new) == "ok"
    assert WI.shortcut_state(lnk(r"C:\Users\Me\AppData\Local\Programs\SC Co-Pilot\SC_CoPilot.exe"), new) == "other"


def test_off_windows_helpers_are_harmless(tmp_path):
    if WI.WIN:
        return
    assert WI.brand(None) == "not Windows"
    assert WI.heal_desktop_shortcut() == "not Windows"
    WI.unbrand(None)
    WI.refresh_icons(tmp_path)
