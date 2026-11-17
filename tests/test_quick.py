import pytest

import sc_macros as M
import sc_quick as Q

MACROS = M.defaults()

CASES = {
    "gear_down": ["Gear down", "drop the gear", "put the landing gear down", "landing gear out", "deploy the gear", "gear dawn",
                  "lower the undercarriage", "deploy landing struts"],
    "gear_up": ["gear up", "retract the gear", "raise the landing gear", "pull the gear up", "stow the gear"],
    "lights_on": ["lights on", "turn on the lights", "hit the lights", "headlights on", "turn on my headlights", "switch on the lamps"],
    "lights_off": ["lights off", "kill the lights", "lights out", "turn the lights off", "lights of", "cut the lights"],
    "shields_on": ["shields up", "raise shields", "shields on", "bring up the shields", "sheilds up", "turn on the deflectors"],
    "shields_off": ["drop shields", "shields down", "kill the shields", "shields offline", "lower shields"],
    "weapons_power_on": ["weapons online", "guns hot", "arm weapons", "turn the guns on", "weapons hot", "power up weapons", "guns on"],
    "weapons_power_off": ["weapons offline", "guns cold", "safe the weapons", "disarm weapons", "weapons off", "turn off my guns", "cut the guns"],
    "max_weapons": ["full power weapons", "all power to guns", "max weapons", "everything into weapons", "power to weapons"],
    "max_shields": ["power to shields", "max shields", "all power to the shields", "shields to max"],
    "max_engines": ["all power to engines", "max thrusters", "full power to the engines"],
    "less_engines": ["lower engines", "reduce power to thrusters", "take power from engines", "less engines"],
    "power_reset": ["balance power", "Vallance power", "even out the power", "reset power", "power normal"],
    "target_attacker": ["target highest threat", "target the biggest threat", "who's shooting me", "lock the attacker",
                        "target whoever is shooting", "target the main threat", "lock onto the threat", "highest threat"],
    "target_hostile": ["next hostile", "target nearest enemy", "lock the closest hostile", "cycle targets", "next target", "target enemy"],
    "target_reticle": ["target that", "target what I'm looking at", "lock that up", "target under reticle"],
    "target_subitem": ["target subsystems", "target his engines", "next component", "target power plant"],
    "target_unlock": ["unlock target", "drop target", "clear target"],
    "decoys": ["flares", "pop flares", "countermeasures", "launch decoys", "flairs"],
    "decoys_panic": ["dump all flares", "panic flares", "empty the flares"],
    "noise": ["chaff", "pop chaff", "noise"],
    "flight_ready": ["flight ready", "power up", "start the engines", "fire her up", "spin it up"],
    "request_landing": ["request landing", "request takeoff", "call the tower", "ask for landing permission", "get me a pad"],
    "nav_mode": ["nav mode", "navigation mode", "switch to nav", "go nav"],
    "scm_mode": ["scm mode", "combat mode", "go scm"],
    "qt_engage": ["engage quantum", "punch it", "hit the quantum drive", "quantum jump"],
    "doors_open": ["open the doors", "open the ramp", "lower the ramp"],
    "doors_lock": ["lock the doors"],
}
MACRO_PHRASES = ["prep for takeoff", "combat ready", "battle stations", "evasive", "go dark", "landing prep"]
HUD = {"both": ["target status", "status on the target", "check target"],
       "shields": ["are his shields down", "are the target's shields down?", "his shields down?", "how are their shields holding",
                   "what are the enemy's shields at"],
       "hull": ["how's the target's hull", "is that ship's hull low"]}
NOT_COMMANDS = ["how many kills do I have", "what's my objective", "where do I sell hadanite", "lights on and gear down", "eject",
                "self destruct", "tell me about the polaris", "is my gear down", "what should I do next", "I like turtles",
                "the weather is nice today", "nice shot", "good game everyone"]


def kind(r):
    if not r:
        return None
    return r.get("action") if r["kind"] == "press" else r.get("what") if r["kind"] == "hud" else r["kind"]


@pytest.mark.parametrize("want,phrase", [(w, p) for w, ps in CASES.items() for p in ps])
def test_instant_commands(want, phrase):
    assert kind(Q.parse(phrase, "Co-Pilot", MACROS)) == want


@pytest.mark.parametrize("phrase", MACRO_PHRASES)
def test_macros(phrase):
    assert kind(Q.parse(phrase, "Co-Pilot", MACROS)) == "macro"


@pytest.mark.parametrize("want,phrase", [(w, p) for w, ps in HUD.items() for p in ps])
def test_target_questions(want, phrase):
    r = Q.parse(phrase, "Co-Pilot", MACROS)
    assert r and r["kind"] == "hud" and r["what"] == want


@pytest.mark.parametrize("phrase", NOT_COMMANDS)
def test_chatter_is_not_a_command(phrase):
    assert Q.parse(phrase, "Co-Pilot", MACROS) is None
