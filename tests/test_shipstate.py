import sc_binds as B
import sc_log as L
import sc_macros as MAC
import sc_quick as Q
import sc_shipstate as SS


def keys(*bound):
    return lambda aid: aid in bound


def test_every_state_action_exists():
    for aid in SS.EFFECT:
        assert aid in B.ACTION_INDEX, aid


def test_separate_keys_always_press_and_say_when_already_set():
    s = SS.ShipState()
    can = keys("gear_down", "gear_up", "gear_toggle")
    assert s.plan("gear_down", can, now=0) == ("gear_down", None)
    s.apply("gear_down", now=0)
    assert s.plan("gear_down", can, now=1) == ("gear_down", "already")
    assert s.describe("gear") == "Gear already down."
    assert s.plan("gear_up", can, now=2) == ("gear_up", None)


def test_toggle_only_skips_a_repeat_then_forces_when_asked_again():
    s = SS.ShipState()
    can = keys("gear_toggle")
    assert s.plan("gear_down", can, now=0) == ("gear_toggle", None)
    s.apply("gear_toggle", intent=True, now=0)
    assert s.get("gear") is True
    assert s.plan("gear_down", can, now=5) == (None, "skip")
    assert s.plan("gear_down", can, now=8) == ("gear_toggle", "forced")
    s.apply("gear_toggle", intent=True, now=8)
    assert s.plan("gear_down", can, now=9) == (None, "skip")
    assert s.plan("gear_down", can, now=9 + SS.FORCE_WINDOW + 1) == (None, "skip")
    assert s.plan("gear_up", can, now=30) == ("gear_toggle", None)


def test_plain_toggle_flips_known_state_and_leaves_unknown_alone():
    s = SS.ShipState()
    s.apply("lights_toggle")
    assert s.get("lights") is None
    s.apply("lights_on")
    s.apply("lights_toggle")
    assert s.get("lights") is False


def test_flight_ready_is_not_pressed_twice():
    s = SS.ShipState()
    can = keys("flight_ready")
    assert s.plan("flight_ready", can, now=0) == ("flight_ready", None)
    s.apply("flight_ready", now=0)
    assert s.get("power") is True
    assert s.plan("flight_ready", can, now=3) == (None, "skip")
    assert s.plan("flight_ready", can, now=4) == ("flight_ready", "forced")


def test_master_mode_uses_hold_b_when_nav_has_no_key():
    s = SS.ShipState()
    can = keys("master_mode_cycle")
    assert s.plan("nav_mode", can, now=0) == ("master_mode_cycle", None)
    s.apply("master_mode_cycle", intent=True, now=0)
    assert s.describe("master") == "We're already in NAV mode."
    assert s.plan("nav_mode", can, now=1) == (None, "skip")


def test_forgets_on_new_ship_death_and_hangar():
    s = SS.ShipState()
    s.on_event("boarded", {"name": "Cutlass Black"})
    s.apply("gear_up")
    s.on_event("boarded", {"name": "Cutlass Black"})
    assert s.get("gear") is False
    s.on_event("boarded", {"name": "Gladius"})
    assert s.get("gear") is None
    s.apply("gear_up")
    s.on_event("death")
    assert s.get("gear") is None


class FakeBinds:
    def __init__(self, bound):
        self.bound, self.pressed = bound, []

    def pressable(self, sc):
        return sc in self.bound

    def press(self, sc, focus=True, hold=None):
        self.pressed.append(sc)
        return True, "x"


def test_macro_skips_flight_ready_when_already_powered_and_records_state():
    s = SS.ShipState()
    s.apply("flight_ready")
    fr, gu = B.ACTION_INDEX["flight_ready"], B.ACTION_INDEX["gear_up"]
    b = FakeBinds({fr["sc"], gu["sc"]})
    m = {"name": "t", "steps": [{"action": "flight_ready", "wait": 0}, {"action": "gear_up", "wait": 0}]}
    done, skipped = MAC.run(m, b, B.ACTION_INDEX, ship=s)
    assert b.pressed == [gu["sc"]] and s.get("gear") is False
    assert any("already" in x for x in skipped)


def test_key_watcher_sees_taps_and_holds():
    s = SS.ShipState()
    w = SS.KeyWatcher(s, None, B.ACTION_INDEX, B.split_key, lambda: False, lambda: True)
    w.watch = [("gear_toggle", (0x4E,), 0.0), ("master_mode_cycle", (0x42,), 0.25), ("lights_on", (0xA3, 0x43), 0.0)]
    s.apply("gear_up")
    s.apply("scm_mode")
    down = set()
    p = lambda vk: vk in down
    down.add(0x4E); w.poll_once(p, 0.0); down.discard(0x4E)
    assert w.poll_once(p, 0.1) == ["gear_toggle"] and s.get("gear") is True
    down.add(0x42); w.poll_once(p, 1.0)
    assert w.poll_once(p, 1.1) == []
    assert w.poll_once(p, 1.3) == ["master_mode_cycle"] and s.get("master") is True
    down.discard(0x42); assert w.poll_once(p, 1.5) == []
    down.add(0x43); w.poll_once(p, 2.0); down.discard(0x43)
    assert w.poll_once(p, 2.1) == []
    down.update({0xA3, 0x43}); w.poll_once(p, 3.0); down.clear()
    assert w.poll_once(p, 3.1) == ["lights_on"] and s.get("lights") is True


def test_vk_combo():
    assert SS.vk_combo("rctrl+z", B.split_key) == (0xA3, ord("Z"))
    assert SS.vk_combo("np_9", B.split_key) == (0x69,)
    assert SS.vk_combo("mouse5", B.split_key) == (0x06,)


def test_quantum_phrases_and_410_destination_line():
    assert Q.parse("quantum mode")["action"] == "nav_mode"
    assert Q.parse("engage quantum")["action"] == "qt_engage"
    assert "quantum_mode" not in B.ACTION_INDEX
    g = L.GameState()
    line = ("<2026-11-17T20:30:24.361Z> [Notice] <Player Requested Fuel to Quantum Target - Server Routing> [ItemNavigation][CL][38708] "
            "| NOT AUTH | CRUS_Spirit_C1_937124878350[937124878350]|CSCItemNavigation::OnPlayerRequestFuelToQuantumTarget|"
            "Player has requested fuel calculation to destination nyxstar [Team_CGP4][QuantumTravel]")
    events = g.feed_line(line)
    assert g.qt_target == "nyxstar" and any(e[0] == "qt_target" for e in (events or []))
