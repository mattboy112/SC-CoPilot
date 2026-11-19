import base64
import io

import numpy as np
import pytest

import sc_shipstate as SS
import sc_vision as VIS

PIL = pytest.importorskip("PIL")


def frame(w=1920, h=1080, value=90):
    img = np.full((h, w, 3), value, dtype=np.uint8)
    img[100:200, 100:300] = (0, 200, 255)
    return img


def decode(shot):
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(shot["data"]))))


def test_snapshot_is_a_small_jpeg_with_our_overlay_blacked_out():
    img = frame()
    img[0:200, 1600:1920] = 255
    shot = VIS.snapshot((0, 0, 1920, 1080), hide=[(1600, 0, 1920, 200)], grab=lambda rect: img.copy())
    assert shot["media_type"] == "image/jpeg" and max(shot["width"], shot["height"]) == VIS.MAX_SIDE
    assert shot["bytes"] < 400_000
    pic = decode(shot)
    assert pic[:120, 1080:].mean() < 12, "overlay area is black"
    assert pic[300:400, 300:400].mean() > 60, "the rest of the game is still there"


def test_snapshot_handles_offsets_and_offscreen_masks():
    img = frame(800, 600)
    shot = VIS.snapshot((1920, 0, 2720, 600), hide=[(1900, -20, 2000, 50), None, (0, 0, 10, 10)], grab=lambda rect: img.copy())
    pic = decode(shot)
    assert pic[:40, :70].mean() < 15 and pic[200:300, 200:300].mean() > 60


def test_blank_or_failed_captures_give_no_picture():
    assert VIS.snapshot((0, 0, 100, 100), grab=lambda rect: np.zeros((100, 100, 3), np.uint8)) is None
    assert VIS.snapshot((0, 0, 100, 100), grab=lambda rect: None) is None
    assert VIS.snapshot(None) is None


@pytest.mark.parametrize("text,want", [
    ('{"in_seat":"yes","power":"on","engines":"off","gear":"down","seen":"MFDs lit, no speed readout"}',
     {"in_seat": "yes", "power": "on", "engines": "off", "gear": "down"}),
    ('Sure! {"power": "ON", "engines": "On", "gear": "maybe"} hope that helps',
     {"in_seat": "unknown", "power": "on", "engines": "on", "gear": "unknown"}),
    ("no idea", {"in_seat": "unknown", "power": "unknown", "engines": "unknown", "gear": "unknown"}),
    ('{"power": ["on"]', {"power": "unknown"}),
])
def test_ai_answers_are_read_strictly(text, want):
    got = VIS.parse_check(text)
    for k, v in want.items():
        assert got[k] == v


@pytest.mark.parametrize("check,want", [
    ({"in_seat": "yes", "power": "on", "engines": "on"}, True),
    ({"in_seat": "yes", "power": "on", "engines": "off"}, False),
    ({"in_seat": "unknown", "power": "off", "engines": "unknown"}, False),
    ({"in_seat": "yes", "power": "on", "engines": "unknown"}, None),
    ({"in_seat": "no", "power": "off", "engines": "off"}, None),
])
def test_flight_verdict(check, want):
    assert VIS.flight_verdict(check) is want


class Rig:
    """A fake game: the HUD answers come from a list, presses are recorded."""

    def __init__(self, readings, keys=("flight_ready", "thrusters_on"), shot=True):
        self.readings = list(readings)
        self.keys = set(keys)
        self.pressed, self.said, self.logged = [], [], []
        self.ship = SS.ShipState()
        self.shot = shot
        self.fc = VIS.FlightCheck(look=self.look, ask_ai=self.ask, press=self.press, say=self.said.append, log=self.logged.append,
                                  can_press=lambda aid: aid in self.keys, ship=self.ship, sleep=lambda s: None)

    def look(self):
        return ({"data": "x", "media_type": "image/jpeg"}, "") if self.shot else (None, "Star Citizen isn't on screen.")

    def press(self, aid):
        self.pressed.append(aid)
        return True, None

    def ask(self, shot):
        r = self.readings.pop(0)
        if isinstance(r, Exception):
            raise r
        return dict({"in_seat": "yes", "power": "unknown", "engines": "unknown", "gear": "unknown", "seen": ""}, **r)


def test_engines_on_after_preflight_stays_quiet():
    rig = Rig([{"power": "on", "engines": "on"}])
    assert rig.fc.run(pressed=True) == "ok"
    assert rig.said == [] and rig.pressed == []
    assert rig.ship.get("power") is True and rig.ship.get("thrusters") is True


def test_remembered_flight_ready_but_engines_actually_off_gets_fixed():
    rig = Rig([{"power": "on", "engines": "off"}, {"power": "on", "engines": "on"}])
    rig.ship.v["power"] = True
    assert rig.fc.run(pressed=False, from_memory=True) == "fixed"
    assert rig.pressed == ["thrusters_on"], "power was on, so only the engines get switched on"
    assert rig.said == ["Engines are off. Starting them up.", "Engines are up."]
    assert rig.ship.get("thrusters") is True


def test_cold_ship_gets_flight_ready_again():
    rig = Rig([{"power": "off", "engines": "off"}, {"power": "on", "engines": "on"}])
    assert rig.fc.run(pressed=True) == "fixed"
    assert rig.pressed == ["flight_ready"]
    assert rig.said[0] == "Engines didn't come on. Trying again."


def test_only_one_retry_then_it_tells_you():
    rig = Rig([{"power": "off"}, {"power": "off"}])
    assert rig.fc.run(pressed=True) == "still_off"
    assert len(rig.pressed) == 1 and "Check your power screen" in rig.said[-1]


def test_cant_see_the_game_never_presses_anything():
    rig = Rig([], shot=False)
    assert rig.fc.run(pressed=False, from_memory=True) == "unknown"
    assert rig.pressed == [] and "Couldn't confirm" in rig.said[0]
    assert any("isn't on screen" in t for t in rig.logged)


def test_ai_errors_never_press_anything():
    rig = Rig([RuntimeError("You've used all 2000 AI replies this month.")])
    assert rig.fc.run(pressed=True) == "unknown"
    assert rig.pressed == [] and rig.said == []


def test_on_foot_is_not_read_as_engines_off():
    rig = Rig([{"in_seat": "no", "power": "off", "engines": "off"}])
    assert rig.fc.run(pressed=True) == "unknown"
    assert rig.pressed == [] and rig.ship.get("thrusters") is None


def test_no_keys_means_no_press():
    rig = Rig([{"power": "off"}], keys=())
    assert rig.fc.run(pressed=True) == "no_key"
    assert rig.pressed == [] and "Controls tab" in rig.said[0]


def test_screen_check_beats_memory():
    s = SS.ShipState()
    s.v["power"] = True
    s.observe("power", False)
    assert s.get("power") is False
    s.observe("nonsense", True)
    s.observe("power", "maybe")
    assert "nonsense" not in s.v and s.get("power") is False


def brain_with(replies, can_look=True):
    import threading
    import types
    import sc_brain as BR
    st = types.SimpleNamespace(lock=threading.RLock(), handle="Pilot", snapshot_text=lambda: "Zone: Stanton")
    looks = []

    def look():
        looks.append(1)
        return {"media_type": "image/jpeg", "data": "QUJD", "width": 4, "height": 4, "bytes": 3}, ""
    app = types.SimpleNamespace(settings={"ai_mode": "own_key", "api_key": "x", "model": "claude-haiku-5-5"}, state=st,
                                note_system=lambda *a: None, can_look=lambda: can_look, look=look)
    b = BR.Brain(app)
    sent = []

    def fake(body, on_text=None):
        sent.append(body)
        return replies.pop(0)
    b._request = fake
    return BR, b, sent, looks


def tool_call(name, tid):
    return {"content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}], "stop_reason": "tool_use", "usage": {}}


def said(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn", "usage": {}}


def test_ai_can_look_and_gets_the_picture_as_an_image():
    BR, b, sent, looks = brain_with([tool_call("look_at_screen", "t1"), said("Engines are off.")])
    assert b.ask("are my engines on") == "Engines are off."
    assert any(t["name"] == "look_at_screen" for t in sent[0]["tools"])
    result = sent[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["content"][0] == {
        "type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    assert "look first" in BR.SYSTEM


def test_ai_gets_at_most_two_looks_per_question():
    BR, b, sent, looks = brain_with([tool_call("look_at_screen", "t1"), tool_call("look_at_screen", "t2"),
                                     tool_call("look_at_screen", "t3"), said("Gear's down.")])
    b.ask("check everything")
    images = [c for m in sent[-1]["messages"] if isinstance(m.get("content"), list) for c in m["content"]
              if c.get("type") == "tool_result" and isinstance(c.get("content"), list)]
    assert len(images) == 2
    assert "Already looked twice" in sent[-1]["messages"][-1]["content"][0]["content"]


def test_no_look_tool_when_screen_checks_are_off():
    BR, b, sent, looks = brain_with([said("Copy.")], can_look=False)
    b.ask("status")
    assert not any(t.get("name") == "look_at_screen" for t in sent[0]["tools"])


def test_ship_check_sends_one_picture_and_reads_the_answer():
    BR, b, sent, looks = brain_with([said('{"in_seat":"yes","power":"on","engines":"off","gear":"down","seen":"no speed"}')])
    res = b.check_ship({"media_type": "image/jpeg", "data": "QUJD"})
    assert res["engines"] == "off" and res["power"] == "on"
    body = sent[0]
    assert body["max_tokens"] <= 300 and body["thinking"] == {"type": "disabled"} and "tools" not in body
    assert body["messages"][0]["content"][0]["type"] == "image" and body["system"] == VIS.CHECK_SYSTEM
