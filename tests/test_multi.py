import pytest

import sc_macros as M
import sc_quick as Q
from test_quick import CASES, MACRO_PHRASES

MACROS = M.defaults()


def actions(text):
    r = Q.parse_many(text, "Co-Pilot", MACROS)
    return r and [c.get("action") or c.get("macro", {}).get("name") or c["kind"] for c in r]


@pytest.mark.parametrize("text,want", [
    ("engines on, VTOL on", ["thrusters_on", "vtol_on"]),
    ("Engines on. VTOL on.", ["thrusters_on", "vtol_on"]),
    ("engines on vtol on", ["thrusters_on", "vtol_on"]),
    ("Co-Pilot, engines on and VTOL on", ["thrusters_on", "vtol_on"]),
    ("gear down and lights on", ["gear_down", "lights_on"]),
    ("gear down and lights on then request landing", ["gear_down", "lights_on", "request_landing"]),
    ("gear up lights on", ["gear_up", "lights_on"]),
    ("flight ready, then gear up", ["flight_ready", "gear_up"]),
    ("close the doors, lock the doors, request landing", ["doors_close", "doors_lock", "request_landing"]),
    ("power on engines on vtol on gear up lights on", ["power_on", "thrusters_on", "vtol_on", "gear_up", "lights_on"]),
    ("flares and chaff", ["decoys", "noise"]),
    ("flares, flares", ["decoys", "decoys"]),
    ("shields up; weapons online", ["shields_on", "weapons_power_on"]),
    ("lights off & gear down", ["lights_off", "gear_down"]),
])
def test_several_commands(text, want):
    assert actions(text) == want


@pytest.mark.parametrize("text,want", [
    ("gear down please and thanks", ["gear_down"]),
    ("open the doors and lower the ramp", ["doors_open"]),
    ("engage quantum", ["qt_engage"]),
    ("max power to shields", ["max_shields"]),
    ("lights on, lights on", ["lights_on"]),
])
def test_one_command_stays_one(text, want):
    assert actions(text) == want


@pytest.mark.parametrize("text", [
    "max power to weapons and shields",
    "lights on and tell me the weather",
    "what is my objective and where do I sell",
    "go nav mode and plot a course to Hurston",
    "engines on and eject",
    "gear down if we're close",
    "shields and weapons",
    "is the gear down and are the lights on?",
    "gear up, gear down, lights on, lights off, shields up, shields down, flares",
])
def test_left_for_the_ai(text):
    assert Q.parse_many(text, "Co-Pilot", MACROS) is None


def test_bare_toggles_need_saying_toggle():
    assert actions("shields, then request landing") is None
    assert actions("toggle shields then request landing") == ["shields_toggle", "request_landing"]


@pytest.mark.parametrize("text,want", [
    ("engines and vtol on", ["thrusters_on", "vtol_on"]),
    ("Co-Pilot, engines and VTOL on", ["thrusters_on", "vtol_on"]),
    ("engines, vtol and lights on", ["thrusters_on", "vtol_on", "lights_on"]),
    ("turn on the engines and vtol", ["thrusters_on", "vtol_on"]),
    ("turn off the lights and engines", ["lights_off", "thrusters_off"]),
    ("shields and lights on", ["shields_on", "lights_on"]),
])
def test_shared_on_off(text, want):
    assert actions(text) == want


def test_every_single_command_still_parses_the_same():
    phrases = [p for ps in CASES.values() for p in ps] + MACRO_PHRASES + list(Q.EXAMPLES)
    for p in phrases:
        one = Q.parse(p, "Co-Pilot", MACROS)
        many = Q.parse_many(p, "Co-Pilot", MACROS)
        if one:
            assert many == [one], p
        else:
            assert not many or len(many) >= 2, p


def test_macro_inside_a_list():
    r = Q.parse_many("combat ready and lights off", "Co-Pilot", MACROS)
    assert [c["kind"] for c in r] == ["macro", "press"]
    assert r[1]["action"] == "lights_off"


def test_waits_between_presses():
    assert Q.gap_after({"action": "flight_ready"}) > Q.gap_after({"action": "power_on"}) > Q.gap_after({"action": "gear_up"})
    assert Q.gap_after({"kind": "overlay"}) == Q.STEP_GAP
    assert Q.gap_after(None) == Q.STEP_GAP


def test_one_reply_for_several():
    assert Q.combine([("Engines on.", False), ("VTOL on.", False)]) == "Engines on. VTOL on."
    assert Q.combine([("Done.", False), ("Done.", False)]) == "Done."
    five = [(f"Ok {i}.", False) for i in range(5)]
    assert Q.combine(five) == "All 5 done."
    assert Q.combine(five + [("Gear has no key.", True)]) == "5 done. Gear has no key."
    assert Q.combine([("Lights on.", False), ("Gear has no key.", True)]) == "Lights on. Gear has no key."
    assert Q.combine([("", False), ("  ", True)]) == ""
